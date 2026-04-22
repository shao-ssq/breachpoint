"""Graph analysis for BreachPoint — identifies hub nodes and surprising connections.

Public API:
    god_nodes(G, top_n) -> list[dict]
    surprising_connections(G, communities) -> list[dict]
    suggest_questions(G, communities, labels) -> list[str]
"""
from __future__ import annotations
import networkx as nx


def god_nodes(G: nx.Graph, top_n: int = 10) -> list[dict]:
    """Return top-N highest-degree nodes (hubs that connect many concepts)."""
    if G.number_of_nodes() == 0:
        return []
    scored = sorted(G.nodes(data=True), key=lambda x: G.degree(x[0]), reverse=True)
    return [
        {
            "id": nid,
            "label": data.get("label", nid),
            "degree": G.degree(nid),
            "community": data.get("community", -1),
            "type": data.get("type", ""),
        }
        for nid, data in scored[:top_n]
    ]


def surprising_connections(
    G: nx.Graph, communities: dict[int, list[str]]
) -> list[dict]:
    """Return edges that bridge different communities (cross-community links)."""
    node_to_community = {
        node: cid for cid, nodes in communities.items() for node in nodes
    }
    surprises = []
    for u, v, data in G.edges(data=True):
        cu = node_to_community.get(u, -1)
        cv = node_to_community.get(v, -1)
        if cu != cv and cu >= 0 and cv >= 0:
            surprises.append({
                "source": u,
                "source_label": G.nodes[u].get("label", u),
                "target": v,
                "target_label": G.nodes[v].get("label", v),
                "relation": data.get("relation", ""),
                "confidence": data.get("confidence", ""),
                "community_a": cu,
                "community_b": cv,
            })
    return sorted(surprises, key=lambda x: (x["community_a"], x["community_b"]))[:30]


def suggest_questions(
    G: nx.Graph,
    communities: dict[int, list[str]],
    labels: dict[int, str],
) -> list[str]:
    """Generate exploration questions based on graph structure."""
    questions = []
    gods = god_nodes(G, top_n=3)
    for g in gods:
        questions.append(f"What is the role of '{g['label']}' and what does it connect?")
    for cid, name in list(labels.items())[:3]:
        questions.append(f"What are the key themes in the '{name}' cluster?")
    surprises = surprising_connections(G, communities)
    for s in surprises[:2]:
        questions.append(
            f"How are '{s['source_label']}' and '{s['target_label']}' related across documents?"
        )
    return questions
