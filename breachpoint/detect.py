"""Document file discovery for BreachPoint.

Scans a directory for supported knowledge document types and returns
a structured manifest with file counts and word estimates.

Public API:
    detect(root) -> dict   — scan directory, return file manifest
"""
from __future__ import annotations
import re
from pathlib import Path

DOC_EXTENSIONS: frozenset[str] = frozenset({
    ".md", ".markdown",
    ".txt", ".text",
    ".rst",
    ".pdf",
    ".docx", ".doc",
    ".html", ".htm",
    ".json",
    ".csv",
    ".tex",
    ".org",
    ".adoc", ".asciidoc",
    # RDF/知识图谱格式
    ".ttl", ".turtle",
    ".n3",
})

SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", "breachpoint-out", ".omc", ".claude",
})

SENSITIVE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(password|secret|token|credential|api[_-]?key)", re.I),
    re.compile(r"\.(pem|key|pfx|p12|cer|crt)$"),
)


def _is_sensitive(path: Path) -> bool:
    return any(p.search(path.name) for p in SENSITIVE_PATTERNS)


def _count_words(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return len(text.split())
    except Exception:
        return 0


def _ext_category(ext: str) -> str:
    if ext in (".md", ".markdown", ".rst", ".txt", ".text", ".org", ".adoc", ".asciidoc", ".tex"):
        return "docs"
    if ext == ".pdf":
        return "pdfs"
    if ext in (".docx", ".doc"):
        return "office"
    if ext in (".html", ".htm"):
        return "web"
    if ext in (".json", ".csv"):
        return "data"
    if ext in (".ttl", ".turtle", ".n3"):
        return "rdf"
    return "other"


def detect(root: str | Path) -> dict:
    """Scan *root* for knowledge documents and return a manifest dict.

    Returns::

        {
            "root": str,
            "total_files": int,
            "total_words": int,
            "files": [{"path": str, "ext": str, "category": str, "words": int}],
            "by_category": {"docs": int, "pdfs": int, ...},
            "skipped_sensitive": [str],
        }
    """
    root = Path(root).resolve()
    files: list[dict] = []
    skipped: list[str] = []
    by_cat: dict[str, int] = {}

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        ext = path.suffix.lower()
        if ext not in DOC_EXTENSIONS:
            continue
        if _is_sensitive(path):
            skipped.append(str(path.relative_to(root)))
            continue
        words = _count_words(path)
        cat = _ext_category(ext)
        by_cat[cat] = by_cat.get(cat, 0) + 1
        files.append({
            "path": str(path),
            "rel_path": str(path.relative_to(root)),
            "ext": ext,
            "category": cat,
            "words": words,
        })

    return {
        "root": str(root),
        "total_files": len(files),
        "total_words": sum(f["words"] for f in files),
        "files": files,
        "by_category": by_cat,
        "skipped_sensitive": skipped,
    }
