"""文档文件发现 — BreachPoint（仅支持 TTL/RDF 格式）。

扫描目录中的 RDF/Turtle 文件并返回结构化清单。

公开 API:
    detect(root) -> dict
"""
from __future__ import annotations
from pathlib import Path

TTL_EXTENSIONS: frozenset[str] = frozenset({".ttl", ".turtle", ".n3"})

SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", "breachpoint-out", ".omc", ".claude",
})


def _count_triples(path: Path) -> int:
    """粗略估算 TTL 文件的三元组数量（按行数估算）。"""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))
    except Exception:
        return 0


def detect(root: str | Path) -> dict:
    """扫描 *root* 目录，返回所有 TTL/RDF 文件的清单。

    返回::

        {
            "root": str,
            "total_files": int,
            "total_triples": int,          # 估算三元组行数
            "files": [{"path", "rel_path", "ext", "category", "words"}],
            "by_category": {"rdf": int},
        }
    """
    root = Path(root).resolve()
    files: list[dict] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        ext = path.suffix.lower()
        if ext not in TTL_EXTENSIONS:
            continue
        triples = _count_triples(path)
        files.append({
            "path": str(path),
            "rel_path": str(path.relative_to(root)),
            "ext": ext,
            "category": "rdf",
            "words": triples,   # 保持字段兼容性，实际含义为估算三元组行数
        })

    return {
        "root": str(root),
        "total_files": len(files),
        "total_triples": sum(f["words"] for f in files),
        "files": files,
        "by_category": {"rdf": len(files)},
        "skipped_sensitive": [],
    }
