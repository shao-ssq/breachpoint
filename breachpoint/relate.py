"""Cross-document relationship discovery — the core innovation of BreachPoint.

Given a batch of newly extracted nodes, compare them against all existing graph
nodes and call Claude (via Anthropic Python SDK) to discover cross-document edges.

Public API:
    relate(new_nodes, existing_nodes, *, batch_size, max_rounds) -> list[dict]
"""
from __future__ import annotations
import anthropic
import json
import os
import re
import sys

_API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "")
_MODEL = os.environ.get("ANTHROPIC_MODEL", os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-20250514"))

DEFAULT_BATCH_SIZE = 20
DEFAULT_MAX_ROUNDS = 0   # 0 = unlimited

_SYSTEM = """\
你是一名知识图谱关系分析专家。

你将收到：
1. 新节点（NEW NODES）— 刚从新文档提取的节点。
2. 已有节点（EXISTING NODES）— 知识图谱中已存在的节点（来自其他文档）。

你的任务：识别新节点与已有节点之间有意义的跨文档关系。

规则：
- 只输出新节点与已有节点之间的跨文档连接。
- confidence=EXTRACTED：两文档中明确陈述的关系。
- confidence=INFERRED：可合理推断的关系。
- confidence=AMBIGUOUS：可能存在但不确定，若有价值仍可包含。
- 特别关注：时序关系（前置、后续）、因果关系（导致、源于）、归属关系（属于、负责）。
- 无有意义关系时输出空数组 []。
- 只输出 JSON 数组，不输出任何其他内容。

输出格式：
[
  {
    "source": "<节点ID>",
    "target": "<节点ID>",
    "relation": "<中文关系动词短语>",
    "confidence": "EXTRACTED|INFERRED|AMBIGUOUS",
    "evidence": "<一句中文说明>"
  }
]
"""


def _format_nodes(nodes: list[dict], label: str) -> str:
    lines = [f"## {label}"]
    skip = {"_source", "id"}
    for n in nodes:
        props = " | ".join(
            f"{k}={v}" for k, v in n.items()
            if k not in skip and v
        )
        lines.append(f"- id={n['id']} | {props}")
    return "\n".join(lines)


def _parse_edges(raw: str) -> list[dict]:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    return []


def relate(
    new_nodes: list[dict],
    existing_nodes: list[dict],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    verbose: bool = False,
) -> list[dict]:
    """Discover cross-document edges between *new_nodes* and *existing_nodes*.

    Args:
        new_nodes:      nodes just extracted from the current document (real nodes only, no stubs)
        existing_nodes: all nodes currently in the store
        batch_size:     how many existing nodes to compare per LLM call
        max_rounds:     max LLM calls (0 = unlimited)
        verbose:        print progress to stderr
    """
    if not new_nodes or not existing_nodes:
        return []

    current_source = new_nodes[0].get("_source", "")
    # 排除同文档节点和 stub 节点
    existing_other = [
        n for n in existing_nodes
        if n.get("_source") and n.get("_source") != current_source
    ]
    if not existing_other:
        return []

    new_ids = {n["id"] for n in new_nodes}
    new_block = _format_nodes(new_nodes, "NEW NODES")
    all_edges: list[dict] = []
    seen_keys: set[tuple] = set()

    batches = [existing_other[i: i + batch_size] for i in range(0, len(existing_other), batch_size)]
    if max_rounds > 0:
        batches = batches[:max_rounds]

    for round_idx, batch in enumerate(batches, 1):
        existing_block = _format_nodes(batch, f"EXISTING NODES (batch {round_idx}/{len(batches)})")
        prompt = f"{_SYSTEM}\n\n{new_block}\n\n{existing_block}"

        if verbose:
            print(f"[relate] round {round_idx}/{len(batches)} — {len(new_nodes)} new × {len(batch)} existing", file=sys.stderr)

        try:
            if _API_KEY and _BASE_URL:
                client = anthropic.Anthropic(api_key=_API_KEY, base_url=_BASE_URL)
            elif _API_KEY:
                client = anthropic.Anthropic(api_key=_API_KEY)
            else:
                print("[relate] 未设置 ANTHROPIC_AUTH_TOKEN", file=sys.stderr)
                break
            msg = client.messages.create(
                model=_MODEL, max_tokens=4096, messages=[{"role": "user", "content": prompt}],
            )
            raw = "".join(b.text for b in msg.content if b.type == "text")
            edges = _parse_edges(raw)
        except Exception as exc:
            print(f"[relate] round {round_idx} error: {exc}", file=sys.stderr)
            continue

        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            rel = edge.get("relation", "")
            if not src or not tgt:
                continue
            # 必须是真正的跨文档边（一端在新节点，一端在已有节点）
            if not ((src in new_ids) ^ (tgt in new_ids)):
                continue
            key = (src, tgt, rel)
            if key not in seen_keys:
                seen_keys.add(key)
                all_edges.append(edge)

    if verbose:
        print(f"[relate] found {len(all_edges)} cross-document edges", file=sys.stderr)

    return all_edges
