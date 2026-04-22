"""Community detection for BreachPoint (adapted from graphify).

Public API:
    cluster(G) -> dict[int, list[str]]   community_id -> [node_ids]
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
            # Split oversized communities
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

    # Re-number by descending size
    sorted_ids = sorted(communities, key=lambda k: len(communities[k]), reverse=True)
    return {new_id: communities[old_id] for new_id, old_id in enumerate(sorted_ids)}


def cohesion_score(G: nx.Graph, nodes: list[str]) -> float:
    if len(nodes) < 2:
        return 1.0
    sub = G.subgraph(nodes)
    actual = sub.number_of_edges()
    possible = len(nodes) * (len(nodes) - 1) // 2
    return actual / possible if possible else 0.0


def score_all(G: nx.Graph, communities: dict[int, list[str]]) -> dict[int, float]:
    return {cid: cohesion_score(G, nodes) for cid, nodes in communities.items()}
