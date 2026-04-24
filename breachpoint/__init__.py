"""BreachPoint — knowledge document graph with incremental LLM relationship discovery."""
from __future__ import annotations


def detect(*args, **kwargs):
    from .detect import detect as _fn
    return _fn(*args, **kwargs)



def build(*args, **kwargs):
    from .build import build as _fn
    return _fn(*args, **kwargs)


def cluster(*args, **kwargs):
    from .cluster import cluster as _fn
    return _fn(*args, **kwargs)


def to_json(*args, **kwargs):
    from .export import to_json as _fn
    return _fn(*args, **kwargs)


def to_html(*args, **kwargs):
    from .export import to_html as _fn
    return _fn(*args, **kwargs)


__all__ = ["detect", "build", "cluster", "to_json", "to_html"]
