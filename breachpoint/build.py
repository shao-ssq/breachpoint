"""Assemble a NetworkX graph from store extraction dict.

Public API:
    build_from_json(extraction) -> nx.Graph
    build(store)                -> nx.Graph
"""
from __future__ import annotations
import sys
import networkx as nx

from .validate import validate_extraction
from .store import Store


def build_from_json(extraction: dict, *, directed: bool = False) -> nx.Graph:
    """Build a NetworkX graph from an extraction dict {nodes, edges}."""
    errors = validate_extraction(extraction)
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
    """Build a NetworkX graph from a Store instance."""
    return build_from_json(store.to_extraction(), directed=directed)
