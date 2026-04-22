"""Cross-document relationship discovery — the core innovation of BreachPoint.

Given a batch of newly extracted nodes, compare them against all existing graph
nodes and call Claude (potentially many times) to discover cross-document edges.
This is the key difference from graphify: LLM is called *unlimited* times to
thoroughly map relationships between documents.

Public API:
    relate(new_nodes, store, client, model, *, batch_size, max_rounds, schema) -> list[dict]
        Returns list of new cross-document edges discovered.
"""
from __future__ import annotations
import json
import re
import sys
from typing import Any

DEFAULT_BATCH_SIZE = 20   # existing nodes per LLM call
DEFAULT_MAX_ROUNDS = 0    # 0 = unlimited (process all batches)

_BASE = """\
你是一名知识图谱关系分析专家。

你将收到：
1. 新节点（NEW NODES）— 刚从新文档提取的节点。
2. 已有节点（EXISTING NODES）— 知识图谱中已存在的节点（来自其他文档）。

你的任务：识别新节点与已有节点之间有意义的跨文档关系。

输出格式：仅输出有效 JSON 数组，每个元素为一条边对象。
所有关系名称（relation 字段）必须使用中文。
所有 evidence 字段必须使用中文描述。

规则：
- 只输出新节点与已有节点之间的跨文档连接（cross-document）。
- 不重复文档内部的边（source_file 相同的两端不算跨文档）。
- confidence=EXTRACTED：两文档中明确陈述的关系。
- confidence=INFERRED：可合理推断的关系。
- confidence=AMBIGUOUS：可能存在但不确定，若有价值仍可包含。
- 特别关注：时序关系（前置、后续）、因果关系（导致、源于）、潜在未来连接（可能影响、待确认）。
- 无有意义关系时输出空数组 []。
- 只输出 JSON 数组，不输出任何其他内容。
"""


def build_relate_system_prompt(schema: dict | None = None) -> str:
    """Build the system prompt for cross-document relationship discovery."""
    parts = [_BASE]

    if schema:
        edge_types = schema.get("edges", [])
        if edge_types:
            parts.append("\nUse these relation types for edges:")
            for et in edge_types:
                parts.append(
                    f'  - "{et["relation"]}" — {et["description"]}'
                    f' (from {et.get("from_type", "*")} to {et.get("to_type", "*")})'
                )

        edge_tmpl = schema.get("edge_template", {})
        if edge_tmpl:
            parts.append("\nEach edge object must have these fields:")
            for ename, edesc in edge_tmpl.items():
                parts.append(f"  - {ename}: {edesc}")

        confidence_levels = schema.get("confidence_levels", ["EXTRACTED", "INFERRED", "AMBIGUOUS"])
        parts.append(f"\nConfidence must be one of: {', '.join(confidence_levels)}")
    else:
        parts.append("""
[
  {
    "source": "<已有节点ID或新节点ID>",
    "target": "<已有节点ID或新节点ID>",
    "relation": "<中文关系动词短语，如：负责、属于、前置于、导致、关联、参考、依赖>",
    "confidence": "EXTRACTED|INFERRED|AMBIGUOUS",
    "evidence": "<一句中文说明，解释为何存在此关系>"
  }
]
""")

    return "\n".join(parts)


def _format_nodes(nodes: list[dict], label: str) -> str:
    lines = [f"## {label}"]
    for n in nodes:
        src = n.get("source_file", "")
        lines.append(
            f"- id={n['id']} | label={n.get('label','')} | "
            f"type={n.get('type','')} | summary={n.get('summary','')} | src={src}"
        )
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
    client: Any,
    *,
    model: str = "claude-sonnet-4-6",
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    verbose: bool = False,
    schema: dict | None = None,
) -> list[dict]:
    """Discover cross-document edges between *new_nodes* and *existing_nodes*.

    Splits existing_nodes into batches of *batch_size* and calls Claude for
    each batch. If *max_rounds* == 0, all batches are processed (unlimited).

    Args:
        new_nodes:      nodes just extracted from the new document
        existing_nodes: all nodes currently in the store (from prior documents)
        client:         anthropic.Anthropic instance
        model:          Claude model ID (required, no default)
        batch_size:     how many existing nodes to compare per LLM call
        max_rounds:     max number of LLM calls (0 = unlimited)
        verbose:        print progress to stderr
        schema:         optional schema for edge types

    Returns:
        Deduplicated list of cross-document edge dicts.
    """
    if not new_nodes or not existing_nodes:
        return []

    new_ids = {n["id"] for n in new_nodes}
    # Only compare against nodes from *other* documents
    existing_other = [
        n for n in existing_nodes
        if n.get("source_file") != (new_nodes[0].get("source_file") if new_nodes else "")
    ]
    if not existing_other:
        return []

    new_block = _format_nodes(new_nodes, "NEW NODES")
    all_edges: list[dict] = []
    seen_keys: set[tuple] = set()

    batches = [
        existing_other[i: i + batch_size]
        for i in range(0, len(existing_other), batch_size)
    ]
    if max_rounds > 0:
        batches = batches[:max_rounds]

    for round_idx, batch in enumerate(batches, 1):
        existing_block = _format_nodes(batch, f"EXISTING NODES (batch {round_idx}/{len(batches)})")
        prompt = f"{new_block}\n\n{existing_block}"

        if verbose:
            print(
                f"[relate] round {round_idx}/{len(batches)} — "
                f"{len(new_nodes)} new × {len(batch)} existing",
                file=sys.stderr,
            )

        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=build_relate_system_prompt(schema),
                messages=[{"role": "user", "content": prompt}],
            )
            edges = _parse_edges(response.content[0].text)
        except Exception as exc:
            print(f"[relate] round {round_idx} error: {exc}", file=sys.stderr)
            continue

        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            rel = edge.get("relation", "")
            if not src or not tgt:
                continue
            # Must be a true cross-document edge (one end in new, one in existing)
            if not ((src in new_ids) ^ (tgt in new_ids)):
                continue
            key = (src, tgt, rel)
            if key not in seen_keys:
                seen_keys.add(key)
                all_edges.append(edge)

    if verbose:
        print(f"[relate] found {len(all_edges)} cross-document edges", file=sys.stderr)

    return all_edges
