"""Markdown report generation for BreachPoint."""
from __future__ import annotations
import networkx as nx

from .analyze import god_nodes, surprising_connections, suggest_questions
from .cluster import score_all


def generate(
    G: nx.Graph,
    communities: dict[int, list[str]],
    labels: dict[int, str],
    *,
    root: str = ".",
    tokens: dict | None = None,
) -> str:
    tokens = tokens or {"input": 0, "output": 0}
    cohesion = score_all(G, communities)
    gods = god_nodes(G, top_n=10)
    surprises = surprising_connections(G, communities)
    questions = suggest_questions(G, communities, labels)

    lines = [
        "# BreachPoint 知识图谱报告",
        "",
        f"**来源：** `{root}`",
        f"**节点数：** {G.number_of_nodes()}  |  "
        f"**边数：** {G.number_of_edges()}  |  "
        f"**社区数：** {len(communities)}",
        "",
    ]

    if tokens["input"] or tokens["output"]:
        lines += [
            f"**LLM 用量：** 输入 {tokens['input']:,} / 输出 {tokens['output']:,} tokens",
            "",
        ]

    # Communities
    lines += ["## 社区", ""]
    for cid in sorted(communities, key=lambda k: len(communities[k]), reverse=True):
        name = labels.get(cid, f"社区 {cid}")
        nodes = communities[cid]
        coh = cohesion.get(cid, 0.0)
        lines.append(f"### {name}（{len(nodes)} 节点，凝聚度={coh:.2f}）")
        for nid in sorted(nodes, key=lambda n: G.degree(n), reverse=True)[:8]:
            label = G.nodes[nid].get("label", nid)
            summary = G.nodes[nid].get("summary", "")
            src = G.nodes[nid].get("source_file", "")
            src_short = src.split("/")[-1].split("\\")[-1] if src else ""
            lines.append(f"- **{label}** — {summary}" + (f"  *（来自 {src_short}）*" if src_short else ""))
        if len(nodes) > 8:
            lines.append(f"  … 另有 {len(nodes) - 8} 个节点")
        lines.append("")

    # Hub nodes
    if gods:
        lines += ["## 核心节点（连接最多）", ""]
        for g in gods:
            lines.append(f"- **{g['label']}** — 度数 {g['degree']}，{g['type']}")
        lines.append("")

    # Surprising cross-document connections
    if surprises:
        lines += ["## 跨文档连接", ""]
        for s in surprises[:15]:
            conf = f" [{s['confidence']}]" if s["confidence"] else ""
            lines.append(
                f"- **{s['source_label']}** → *{s['relation']}* → **{s['target_label']}**{conf}"
                f"  *（社区 {s['community_a']} ↔ {s['community_b']}）*"
            )
        lines.append("")

    # Suggested questions
    if questions:
        lines += ["## 建议探索问题", ""]
        for q in questions:
            lines.append(f"- {q}")
        lines.append("")

    return "\n".join(lines)
