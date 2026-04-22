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
        "# BreachPoint Knowledge Graph Report",
        "",
        f"**Source:** `{root}`",
        f"**Nodes:** {G.number_of_nodes()}  |  "
        f"**Edges:** {G.number_of_edges()}  |  "
        f"**Communities:** {len(communities)}",
        "",
    ]

    if tokens["input"] or tokens["output"]:
        lines += [
            f"**LLM tokens:** {tokens['input']:,} in / {tokens['output']:,} out",
            "",
        ]

    # Communities
    lines += ["## Communities", ""]
    for cid in sorted(communities, key=lambda k: len(communities[k]), reverse=True):
        name = labels.get(cid, f"Community {cid}")
        nodes = communities[cid]
        coh = cohesion.get(cid, 0.0)
        lines.append(f"### {name} ({len(nodes)} nodes, cohesion={coh:.2f})")
        for nid in sorted(nodes, key=lambda n: G.degree(n), reverse=True)[:8]:
            label = G.nodes[nid].get("label", nid)
            summary = G.nodes[nid].get("summary", "")
            src = G.nodes[nid].get("source_file", "")
            src_short = src.split("/")[-1].split("\\")[-1] if src else ""
            lines.append(f"- **{label}** — {summary}" + (f" *(from {src_short})*" if src_short else ""))
        if len(nodes) > 8:
            lines.append(f"  … and {len(nodes) - 8} more")
        lines.append("")

    # Hub nodes
    if gods:
        lines += ["## Hub Nodes (most connected)", ""]
        for g in gods:
            lines.append(f"- **{g['label']}** — degree {g['degree']}, {g['type']}")
        lines.append("")

    # Surprising cross-document connections
    if surprises:
        lines += ["## Cross-Document Connections", ""]
        for s in surprises[:15]:
            conf = f" [{s['confidence']}]" if s["confidence"] else ""
            lines.append(
                f"- **{s['source_label']}** → *{s['relation']}* → **{s['target_label']}**{conf}"
                f"  *(community {s['community_a']} ↔ {s['community_b']})*"
            )
        lines.append("")

    # Suggested questions
    if questions:
        lines += ["## Suggested Exploration Questions", ""]
        for q in questions:
            lines.append(f"- {q}")
        lines.append("")

    return "\n".join(lines)
