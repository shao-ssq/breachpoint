"""社区检测 — BreachPoint。

公开 API:
    cluster(G) -> dict[int, list[str]]    社区ID → 节点ID列表
    score_all(G, communities) -> dict[int, float]
    cohesion_score(G, nodes) -> float
"""
from __future__ import annotations
import contextlib
import io
import sys
import networkx as nx


def _suppress():
    return contextlib.redirect_stdout(io.StringIO())


def _partition(G: nx.Graph) -> dict[str, int]:
    """对图进行分区，返回 {节点ID: 社区ID}。

    优先使用 Leiden（graspologic），失败则降级到 Louvain（networkx），
    再失败则每个节点独立成一个社区。
    """
    try:
        from graspologic.partition import leiden
        old_err = sys.stderr
        try:
            sys.stderr = io.StringIO()
            with _suppress():
                result = leiden(G)
        finally:
            sys.stderr = old_err
        return result
    except Exception:
        pass
    try:
        kwargs: dict = {"seed": 42}
        import inspect
        if "max_level" in inspect.signature(nx.community.louvain_communities).parameters:
            kwargs["max_level"] = 8
        parts = nx.community.louvain_communities(G, **kwargs)
        return {node: i for i, part in enumerate(parts) for node in part}
    except Exception:
        return {n: i for i, n in enumerate(G.nodes())}


def cluster(G: nx.Graph) -> dict[int, list[str]]:
    """对图进行社区检测，返回按社区规模降序编号的结果。

    孤立节点（度为0）各自单独成一个社区，避免污染算法输入。
    超大社区（超过 max(10, 总节点数/4) 个节点）会额外再切分一次。
    最终社区按规模降序重新编号，社区0最大。
    """
    if G.number_of_nodes() == 0:
        return {}
    Gu = G.to_undirected() if G.is_directed() else G
    isolated = [n for n in Gu.nodes() if Gu.degree(n) == 0]
    connected = [n for n in Gu.nodes() if Gu.degree(n) > 0]

    communities: dict[int, list[str]] = {}
    cid = 0
    for node in isolated:
        communities[cid] = [node]
        cid += 1

    if connected:
        sub = Gu.subgraph(connected)
        raw = _partition(sub)
        mapping: dict[int, list[str]] = {}
        for node, pid in raw.items():
            mapping.setdefault(pid, []).append(node)
        for nodes in mapping.values():
            # 超大社区再切分一次（仅一层递归）
            if len(nodes) > max(10, G.number_of_nodes() // 4):
                sub2 = Gu.subgraph(nodes)
                raw2 = _partition(sub2)
                sub_map: dict[int, list[str]] = {}
                for n, pid2 in raw2.items():
                    sub_map.setdefault(pid2, []).append(n)
                for snodes in sub_map.values():
                    communities[cid] = snodes
                    cid += 1
            else:
                communities[cid] = nodes
                cid += 1

    # 按社区规模降序重新编号
    sorted_ids = sorted(communities, key=lambda k: len(communities[k]), reverse=True)
    return {new_id: communities[old_id] for new_id, old_id in enumerate(sorted_ids)}


def cohesion_score(G: nx.Graph, nodes: list[str]) -> float:
    """计算社区内聚度：实际边数 / 可能边数（无向）。"""
    if len(nodes) < 2:
        return 1.0
    sub = G.subgraph(nodes)
    actual = sub.number_of_edges()
    possible = len(nodes) * (len(nodes) - 1) // 2
    return actual / possible if possible else 0.0


def score_all(G: nx.Graph, communities: dict[int, list[str]]) -> dict[int, float]:
    """计算所有社区的内聚度得分。"""
    return {cid: cohesion_score(G, nodes) for cid, nodes in communities.items()}
