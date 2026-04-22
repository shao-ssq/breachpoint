"""从 store 或 extraction dict 组装 NetworkX 图。

公开 API:
    build_from_json(extraction) -> nx.Graph
    build(store)                -> nx.Graph
"""
from __future__ import annotations
import sys
import networkx as nx

from .validate import validate_extraction
from .store import Store


def build_from_json(extraction: dict, *, directed: bool = False) -> nx.Graph:
    """从 extraction dict {nodes, edges} 构建 NetworkX 图。

    无向图中边属性会额外保存 _src/_tgt 以保留原始方向信息。
    端点不存在的悬空边（stub 未补全）会被静默跳过。
    """
    errors = validate_extraction(extraction)
    # 过滤悬空边警告（stub 节点尚未补全属正常情况）
    real_errors = [e for e in errors if "does not match any node id" not in e]
    if real_errors:
        print(f"[breachpoint] extraction warning: {real_errors[0]}", file=sys.stderr)

    G: nx.Graph = nx.DiGraph() if directed else nx.Graph()
    for node in extraction.get("nodes", []):
        G.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})

    node_set = set(G.nodes())
    for edge in extraction.get("edges", []):
        src, tgt = edge.get("source", ""), edge.get("target", "")
        if not src or not tgt:
            continue
        if src not in node_set or tgt not in node_set:
            continue
        attrs = {k: v for k, v in edge.items() if k not in ("source", "target")}
        attrs["_src"] = src
        attrs["_tgt"] = tgt
        G.add_edge(src, tgt, **attrs)

    return G


def build(store: Store, *, directed: bool = False) -> nx.Graph:
    """从 Store 实例构建 NetworkX 图。"""
    return build_from_json(store.to_extraction(), directed=directed)
