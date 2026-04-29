"""rdflib-based TTL parser — parses bp:Entity schema only.

Public API:
    parse_ttl(path, rel_path) -> dict  # {"nodes": [...], "edges": [...]}
"""
from __future__ import annotations
from pathlib import Path
from rdflib import Graph, RDF, URIRef, Namespace

BP = Namespace("https://breachpoint.dev/schema#")


def _local_name(uri: str) -> str:
    for sep in ("#", "/"):
        idx = uri.rfind(sep)
        if idx != -1:
            return uri[idx + 1:]
    return uri


def parse_ttl(path: str | Path, rel_path: str) -> dict:
    """Parse bp:Entity-based TTL (bp:id / bp:label / bp:next / bp:comment)."""
    g = Graph()
    g.parse(str(path), format="turtle")

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    for subj in g.subjects(RDF.type, BP.Entity):
        if not isinstance(subj, URIRef):
            continue
        bp_id = g.value(subj, BP.id)
        bp_label = g.value(subj, BP.label)
        bp_comment = g.value(subj, BP.comment)

        nid = str(bp_id) if bp_id else _local_name(str(subj))
        label = str(bp_label) if bp_label else nid
        comment = str(bp_comment) if bp_comment else ""

        nodes[nid] = {
            "id": nid,
            "label": label,
            "type": "实体",
            "comment": comment,
            "source_file": rel_path,
        }

        # bp:next → edges
        for next_ref in g.objects(subj, BP.next):
            tgt_id = _local_name(str(next_ref)) if isinstance(next_ref, URIRef) else str(next_ref)
            edges.append({
                "source": nid,
                "target": tgt_id,
                "relation": "关联",
                "confidence": "EXTRACTED",
                "evidence": f"bp:next 声明 {nid} → {tgt_id}",
            })

    # Deduplicate edges
    seen: set[tuple] = set()
    unique_edges = []
    for e in edges:
        key = (e["source"], e["target"], e["relation"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    return {"nodes": list(nodes.values()), "edges": unique_edges}
