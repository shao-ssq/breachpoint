"""rdflib-based TTL parser — extracts structural nodes and EXTRACTED edges.

Public API:
    parse_ttl(path, rel_path) -> dict  # {"nodes": [...], "edges": [...]}
"""
from __future__ import annotations
from pathlib import Path
from rdflib import Graph, RDF, RDFS, OWL, URIRef, Literal

_EDGE_PREDICATES: dict[str, str] = {
    str(RDFS.subClassOf):     "继承自",
    str(OWL.equivalentClass): "等价于",
    str(OWL.disjointWith):    "互斥于",
    str(RDFS.seeAlso):        "参见",
    str(RDFS.isDefinedBy):    "定义于",
    str(OWL.imports):         "导入",
}

_CLASS_TYPES: dict[str, str] = {
    str(OWL.Class):              "本体类",
    str(OWL.ObjectProperty):     "对象属性",
    str(OWL.DatatypeProperty):   "数据属性",
    str(OWL.AnnotationProperty): "注解属性",
    str(OWL.NamedIndividual):    "命名个体",
    str(OWL.Ontology):           "本体",
}

_SKIP_LITERAL_PREDICATES = frozenset({
    str(RDFS.label), str(RDFS.comment), str(OWL.versionInfo),
})

_SKIP_OBJECT_PREDICATES = frozenset({
    str(RDF.type), str(RDFS.domain), str(RDFS.range),
    str(RDFS.subClassOf), str(OWL.equivalentClass), str(OWL.disjointWith),
    str(RDFS.seeAlso), str(RDFS.isDefinedBy), str(OWL.imports),
    str(OWL.inverseOf), str(OWL.onProperty), str(OWL.someValuesFrom),
    str(OWL.allValuesFrom), str(OWL.hasValue),
})


def _local_name(uri: str) -> str:
    for sep in ("#", "/"):
        idx = uri.rfind(sep)
        if idx != -1:
            return uri[idx + 1:]
    return uri


def _zh_label(g: Graph, subj: URIRef) -> str:
    for obj in g.objects(subj, RDFS.label):
        if isinstance(obj, Literal) and obj.language and obj.language.startswith("zh"):
            return str(obj)
    lbl = g.value(subj, RDFS.label)
    if lbl:
        return str(lbl)
    return _local_name(str(subj))


def _zh_comment(g: Graph, subj: URIRef) -> str:
    for obj in g.objects(subj, RDFS.comment):
        if isinstance(obj, Literal) and obj.language and obj.language.startswith("zh"):
            return str(obj)
    c = g.value(subj, RDFS.comment)
    return str(c) if c else ""


def _resource_type(g: Graph, subj: URIRef, class_labels: dict[str, str]) -> str:
    """Return Chinese type: OWL built-ins first, then parent class label, else '资源'."""
    for obj in g.objects(subj, RDF.type):
        t = _CLASS_TYPES.get(str(obj))
        if t:
            return t
    # instance of a domain class → use that class's label
    for obj in g.objects(subj, RDF.type):
        if isinstance(obj, URIRef):
            cid = _local_name(str(obj))
            if cid in class_labels:
                return class_labels[cid]
    return "资源"


def _data_props(g: Graph, subj: URIRef) -> dict:
    """Flatten literal data properties onto node (skip label/comment)."""
    props: dict[str, str] = {}
    for pred, obj in g.predicate_objects(subj):
        if not isinstance(obj, Literal):
            continue
        if str(pred) in _SKIP_LITERAL_PREDICATES:
            continue
        key = _local_name(str(pred))
        props[key] = str(obj)
    return props


def parse_ttl(path: str | Path, rel_path: str) -> dict:
    """Parse a TTL file; return structural nodes + EXTRACTED edges (summaries empty for LLM)."""
    g = Graph()
    g.parse(str(path), format="turtle")

    # Pre-build class label map for instance type resolution
    class_labels: dict[str, str] = {}
    for cls in g.subjects(RDF.type, OWL.Class):
        if isinstance(cls, URIRef):
            cid = _local_name(str(cls))
            class_labels[cid] = _zh_label(g, cls)

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    for subj in set(g.subjects()):
        if not isinstance(subj, URIRef):
            continue
        nid = _local_name(str(subj))
        if not nid or nid in nodes:
            continue
        node = {
            "id": nid,
            "label": _zh_label(g, subj),
            "type": _resource_type(g, subj, class_labels),
            "comment": _zh_comment(g, subj),
            "source_file": rel_path,
        }
        node.update(_data_props(g, subj))
        nodes[nid] = node

    # Edges from object property domain/range (skip inverseOf props — covered by their forward counterpart)
    for prop in g.subjects(RDF.type, OWL.ObjectProperty):
        if not isinstance(prop, URIRef):
            continue
        if (prop, OWL.inverseOf, None) in g:
            continue
        pid = _local_name(str(prop))
        plabel = _zh_label(g, prop)
        domains = list(g.objects(prop, RDFS.domain))
        ranges = list(g.objects(prop, RDFS.range))
        for domain in domains:
            for range_ in ranges:
                src, tgt = _local_name(str(domain)), _local_name(str(range_))
                edges.append({
                    "source": src, "target": tgt, "relation": plabel,
                    "confidence": "EXTRACTED",
                    "evidence": f"对象属性 {pid} 声明 domain={src}, range={tgt}",
                })
        # Connect property node itself to domain and range
        for domain in domains:
            src = _local_name(str(domain))
            edges.append({
                "source": pid, "target": src, "relation": "定义域为",
                "confidence": "EXTRACTED",
                "evidence": f"对象属性 {pid} rdfs:domain {src}",
            })
        for range_ in ranges:
            tgt = _local_name(str(range_))
            edges.append({
                "source": pid, "target": tgt, "relation": "值域为",
                "confidence": "EXTRACTED",
                "evidence": f"对象属性 {pid} rdfs:range {tgt}",
            })

    # Edges from datatype property domain/range
    for prop in g.subjects(RDF.type, OWL.DatatypeProperty):
        if not isinstance(prop, URIRef):
            continue
        pid = _local_name(str(prop))
        plabel = _zh_label(g, prop)
        domains = list(g.objects(prop, RDFS.domain))
        ranges = list(g.objects(prop, RDFS.range))
        for domain in domains:
            for range_ in ranges:
                src, tgt = _local_name(str(domain)), _local_name(str(range_))
                edges.append({
                    "source": src, "target": tgt, "relation": plabel,
                    "confidence": "EXTRACTED",
                    "evidence": f"数据属性 {pid} 声明 domain={src}, range={tgt}",
                })
        # Connect property node itself to domain
        for domain in domains:
            src = _local_name(str(domain))
            edges.append({
                "source": pid, "target": src, "relation": "定义域为",
                "confidence": "EXTRACTED",
                "evidence": f"数据属性 {pid} rdfs:domain {src}",
            })

    # Edges from structural predicates (subClassOf, imports, etc.)
    for subj, pred, obj in g:
        if not isinstance(subj, URIRef) or not isinstance(obj, URIRef):
            continue
        relation = _EDGE_PREDICATES.get(str(pred))
        if not relation:
            continue
        src, tgt = _local_name(str(subj)), _local_name(str(obj))
        if src != tgt:
            edges.append({
                "source": src, "target": tgt, "relation": relation,
                "confidence": "EXTRACTED",
                "evidence": f"TTL中显式声明 {_local_name(str(pred))}",
            })

    # Collect all declared ObjectProperty URIs to avoid re-extracting them as instance triples
    _declared_obj_props = frozenset(
        str(p) for p in g.subjects(RDF.type, OWL.ObjectProperty) if isinstance(p, URIRef)
    )

    # Edges from custom domain predicates (instance-level triples)
    for subj, pred, obj in g:
        if not isinstance(subj, URIRef) or not isinstance(obj, URIRef):
            continue
        ps = str(pred)
        if ps in _SKIP_OBJECT_PREDICATES or ps in _EDGE_PREDICATES or ps in _declared_obj_props:
            continue
        src, tgt = _local_name(str(subj)), _local_name(str(obj))
        if src == tgt or not src or not tgt:
            continue
        relation = _zh_label(g, pred) if isinstance(pred, URIRef) else _local_name(ps)
        edges.append({
            "source": src, "target": tgt, "relation": relation,
            "confidence": "EXTRACTED",
            "evidence": f"TTL实例三元组 {_local_name(ps)}",
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
