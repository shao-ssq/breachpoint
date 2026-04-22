"""Persistent JSON graph store for BreachPoint.

Manages breachpoint-out/graph.json — nodes, edges, and processed-doc manifest.
All mutations go through this module so incremental processing is always safe.

Public API:
    load(out_dir)           -> Store
    Store.add_nodes(nodes)
    Store.add_edges(edges)
    Store.mark_processed(path, doc_hash)
    Store.is_processed(path, doc_hash) -> bool
    Store.save()
    Store.to_extraction() -> dict      (nodes + edges for build.py)
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any


class Store:
    """In-memory graph store backed by a JSON file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._nodes: dict[str, dict] = {}   # id -> node attrs
        self._edges: list[dict] = []
        self._processed: dict[str, str] = {}  # rel_path -> sha256

    # ── persistence ─────────────────────────────────────────────────────────

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "nodes": list(self._nodes.values()),
            "edges": self._edges,
            "processed": self._processed,
        }
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def _from_data(cls, path: Path, data: dict) -> "Store":
        s = cls(path)
        for n in data.get("nodes", []):
            s._nodes[n["id"]] = n
        s._edges = list(data.get("edges", []))
        s._processed = dict(data.get("processed", {}))
        return s

    # ── mutation ─────────────────────────────────────────────────────────────

    def add_node_and_save(self, node: dict) -> bool:
        """添加单个节点并立即持久化到磁盘。返回 True 表示是新节点。"""
        nid = node.get("id") or _make_id(node.get("label", ""))
        node = dict(node, id=nid)
        is_new = nid not in self._nodes
        if not is_new:
            existing = self._nodes[nid]
            for k, v in node.items():
                if v:
                    existing[k] = v
            self._nodes[nid] = existing
        else:
            self._nodes[nid] = node
        self.save()
        return is_new

    def add_edge_and_save(self, edge: dict) -> bool:
        """添加单条边并立即持久化。返回 True 表示是新边。"""
        key = (edge.get("source", ""), edge.get("target", ""), edge.get("relation", ""))
        existing_keys = {
            (e["source"], e["target"], e.get("relation", ""))
            for e in self._edges
        }
        if key not in existing_keys:
            self._edges.append(edge)
            self.save()
            return True
        return False

    def add_nodes(self, nodes: list[dict]) -> list[str]:
        """Upsert nodes. Returns list of new node IDs (not previously seen)."""
        new_ids = []
        for n in nodes:
            nid = n.get("id") or _make_id(n.get("label", ""))
            n = dict(n, id=nid)
            if nid not in self._nodes:
                new_ids.append(nid)
            else:
                # merge: preserve existing fields, overlay new non-empty ones
                existing = self._nodes[nid]
                for k, v in n.items():
                    if v:
                        existing[k] = v
                n = existing
            self._nodes[nid] = n
        return new_ids

    def add_edges(self, edges: list[dict]) -> None:
        """Append edges, deduplicating by (source, target, relation)."""
        existing_keys = {
            (e["source"], e["target"], e.get("relation", ""))
            for e in self._edges
        }
        for e in edges:
            key = (e.get("source", ""), e.get("target", ""), e.get("relation", ""))
            if key not in existing_keys:
                self._edges.append(e)
                existing_keys.add(key)

    def mark_processed(self, rel_path: str, doc_hash: str) -> None:
        self._processed[rel_path] = doc_hash

    def is_processed(self, rel_path: str, doc_hash: str) -> bool:
        return self._processed.get(rel_path) == doc_hash

    # ── read ─────────────────────────────────────────────────────────────────

    @property
    def nodes(self) -> list[dict]:
        return list(self._nodes.values())

    @property
    def edges(self) -> list[dict]:
        return list(self._edges)

    @property
    def node_ids(self) -> frozenset[str]:
        return frozenset(self._nodes)

    def to_extraction(self) -> dict:
        """Return nodes + edges dict suitable for build.build_from_json()."""
        return {"nodes": self.nodes, "edges": self.edges}

    def __len__(self) -> int:
        return len(self._nodes)


def load(out_dir: str | Path) -> Store:
    """Load or create a Store from *out_dir*/graph.json."""
    path = Path(out_dir) / "graph.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Store._from_data(path, data)
        except Exception:
            pass
    return Store(path)


def file_hash(path: str | Path) -> str:
    """SHA-256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_id(label: str) -> str:
    import re
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip())
    return cleaned.strip("_").lower()[:80] or "node"
