"""图分析 — 识别 hub 节点和跨社区惊喜连接。

公开 API:
    god_nodes(G, top_n, communities) -> list[dict]
    surprising_connections(G, communities) -> list[dict]
    suggest_questions(G, communities, labels) -> list[str]
"""
from __future__ import annotations
import networkx as nx


def god_nodes(
    G: nx.Graph,
    top_n: int = 10,
    communities: dict[int, list[str]] | None = None,
) -> list[dict]:
    """返回度最高的 top-N hub 节点。

    如果传入 communities，会正确填充每个节点所属的社区 ID。
    """
    if G.number_of_nodes() == 0:
        return []

    node_to_community: dict[str, int] = {}
    if communities:
        for cid, nodes in communities.items():
            for n in nodes:
                node_to_community[n] = cid

    scored = sorted(G.nodes(data=True), key=lambda x: G.degree(x[0]), reverse=True)
    return [
        {
            "id": nid,
            "label": data.get("label", nid),
            "degree": G.degree(nid),
            "community": node_to_community.get(nid, -1),
            "type": data.get("type", ""),
        }
        for nid, data in scored[:top_n]
    ]


def surprising_connections(
    G: nx.Graph, communities: dict[int, list[str]]
) -> list[dict]:
    """返回跨越不同社区的边（跨社区惊喜连接），按社区对排序，最多返回 30 条。"""
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
    """基于图结构生成中文探索性问题。"""
    questions = []
    gods = god_nodes(G, top_n=3, communities=communities)
    for g in gods:
        questions.append(f"「{g['label']}」在图中扮演什么角色？它连接了哪些概念？")
    for cid, name in list(labels.items())[:3]:
        questions.append(f"「{name}」社区的核心主题是什么？")
    surprises = surprising_connections(G, communities)
    for s in surprises[:2]:
        questions.append(
            f"「{s['source_label']}」与「{s['target_label']}」跨文档之间存在怎样的关联？"
        )
    return questions
