"""Schema validation for BreachPoint extraction dicts."""
from __future__ import annotations


def validate_extraction(data: dict) -> list[str]:
    """Return list of error strings (empty = valid)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["extraction must be a dict"]

    nodes = data.get("nodes", [])
    if not isinstance(nodes, list):
        errors.append("nodes must be a list")
    else:
        node_ids: set[str] = set()
        for i, n in enumerate(nodes):
            if not isinstance(n, dict):
                errors.append(f"nodes[{i}] must be a dict")
                continue
            if "id" not in n:
                errors.append(f"nodes[{i}] missing 'id'")
                continue
            if "label" not in n:
                errors.append(f"nodes[{i}] missing 'label'")
            node_ids.add(n["id"])

    edges = data.get("edges", [])
    if not isinstance(edges, list):
        errors.append("edges must be a list")
    else:
        for i, e in enumerate(edges):
            if not isinstance(e, dict):
                errors.append(f"edges[{i}] must be a dict")
                continue
            for field in ("source", "target"):
                if field not in e:
                    errors.append(f"edges[{i}] missing '{field}'")
            if isinstance(nodes, list) and node_ids:
                for field in ("source", "target"):
                    val = e.get(field)
                    if val and val not in node_ids:
                        errors.append(
                            f"edges[{i}] {field}='{val}' does not match any node id"
                        )

    return errors
