"""LLM-based single-document analysis for BreachPoint.

Each document is fed to Claude which extracts:
  - Concept nodes  (entities, topics, ideas, people, places, events…)
  - Intra-document edges (relationships found within the document)

Public API:
    read_document(path) -> str           — read any supported file to plain text
    extract(path, client, model) -> dict — {nodes, edges, input_tokens, output_tokens}
    build_system_prompt(schema) -> str   — build extraction prompt from schema
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

_BASE = """\
You are a knowledge graph extractor. Given a document, extract nodes and edges.

Output ONLY valid JSON in this exact schema:
{
  "nodes": [...],
  "edges": [...]
}

Rules:
- Node IDs must be lowercase_underscore slugs, max 40 chars, globally unique.
- Extract 5-25 nodes per document. Quality over quantity.
- Only include edges where both source and target are in your node list.
- confidence=EXTRACTED means the relation is stated explicitly; INFERRED means it is clearly implied; AMBIGUOUS means possible but uncertain.
- Output nothing but the JSON object.
"""


def build_system_prompt(schema: dict | None = None) -> str:
    """Build the system prompt for extraction, optionally using a schema."""
    if schema is None:
        # Default generic prompt
        return _BASE + """
1. **Nodes**: Key concepts, entities, topics, people, places, events, ideas, or themes.
   Each node must have a short unique `label` (2-5 words), a `type` (concept|entity|event|person|place|topic), and a one-sentence `summary`.
2. **Edges**: Relationships between nodes found explicitly or clearly implied in this document.

{
  "nodes": [
    {"id": "<slug>", "label": "<short label>", "type": "<type>", "summary": "<one sentence>"}
  ],
  "edges": [
    {"source": "<id>", "target": "<id>", "relation": "<verb phrase>", "confidence": "EXTRACTED|INFERRED|AMBIGUOUS", "evidence": "<quote or reasoning>"}
  ]
}
"""

    parts = [_BASE]

    # Node type definitions
    node_types = schema.get("nodes", [])
    if node_types:
        parts.append("Extract nodes matching these type definitions:")
        for nt in node_types:
            ntype = nt["type"]
            tmpl = nt.get("label_template", "")
            fields = nt.get("fields", {})
            field_lines = []
            for fname, fdesc in fields.items():
                field_lines.append(f"    - {fname}: {fdesc}")
            fields_block = "\n".join(field_lines)
            parts.append(
                f"\n### {ntype}"
                f"\n  label pattern: {tmpl}"
                f"\n  fields:"
                f"\n{fields_block}"
            )

    # Edge type definitions
    edge_types = schema.get("edges", [])
    if edge_types:
        parts.append("\nUse these edge relation types:")
        for et in edge_types:
            parts.append(
                f"  - \"{et['relation']}\" — {et['description']}"
                f" (from {et.get('from_type','*')} to {et.get('to_type','*')})"
            )

    edge_tmpl = schema.get("edge_template", {})
    if edge_tmpl:
        parts.append("\nEach edge object must have these fields:")
        for ename, edesc in edge_tmpl.items():
            parts.append(f"  - {ename}: {edesc}")

    confidence_levels = schema.get("confidence_levels", ["EXTRACTED", "INFERRED", "AMBIGUOUS"])
    parts.append(f"\nConfidence must be one of: {', '.join(confidence_levels)}")

    return "\n".join(parts)


def read_document(path: str | Path) -> str:
    """Read a document file to plain text regardless of format."""
    path = Path(path)
    ext = path.suffix.lower()

    if ext == ".pdf":
        return _read_pdf(path)
    if ext in (".docx", ".doc"):
        return _read_docx(path)
    if ext in (".html", ".htm"):
        return _read_html(path)
    if ext in (".json",):
        return path.read_text(encoding="utf-8", errors="ignore")
    # Plain text variants (.md, .txt, .rst, .org, .tex, .csv, .adoc, etc.)
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
    except ImportError:
        return f"[PDF: {path.name} — install pypdf to extract text]"
    except Exception as e:
        return f"[PDF read error: {e}]"


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    except ImportError:
        return f"[DOCX: {path.name} — install python-docx to extract text]"
    except Exception as e:
        return f"[DOCX read error: {e}]"


def _read_html(path: Path) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(path.read_bytes(), "html.parser")
        return soup.get_text(separator="\n")
    except ImportError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _truncate(text: str, max_chars: int = 12000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[...truncated...]"


def _parse_llm_json(raw: str) -> dict:
    """Extract JSON from LLM response (handles markdown code fences)."""
    raw = raw.strip()
    # Strip markdown code fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\n---\n{raw[:500]}")


def _stamp_source(nodes: list[dict], source_file: str) -> list[dict]:
    return [dict(n, source_file=source_file) for n in nodes]


_TTL_EXTENSIONS = frozenset({".ttl", ".turtle", ".n3"})


def _extract_ttl(path: Path) -> dict:
    """解析 TTL/RDF 文件，直接提取节点和边，无需 LLM 调用。"""
    from .parse_ttl import parse_ttl
    result = parse_ttl(path)
    return {
        "nodes": result["nodes"],
        "edges": result["edges"],
        "input_tokens": 0,
        "output_tokens": 0,
    }


def extract(
    path: str | Path,
    client: Any,
    *,
    model: str = DEFAULT_MODEL,
    schema: dict | None = None,
) -> dict:
    """Analyse a single document with Claude and return {nodes, edges, tokens}.

    Args:
        path:   path to the document file
        client: an ``anthropic.Anthropic`` client instance
        model:  Claude model ID (required, no default — caller must specify)
        schema: optional schema dict controlling node/edge types

    Returns::

        {
            "nodes": [...],
            "edges": [...],
            "input_tokens": int,
            "output_tokens": int,
        }
    """
    path = Path(path)

    # TTL/RDF 文件：直接解析，无需 LLM
    if path.suffix.lower() in _TTL_EXTENSIONS:
        return _extract_ttl(path)

    text = read_document(path)
    system_prompt = build_system_prompt(schema)
    prompt = f"Document: {path.name}\n\n{_truncate(text)}"

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text
    data = _parse_llm_json(raw)

    nodes = _stamp_source(data.get("nodes", []), str(path))
    edges = data.get("edges", [])

    # Ensure every edge references existing node IDs
    node_ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e.get("source") in node_ids and e.get("target") in node_ids]

    return {
        "nodes": nodes,
        "edges": edges,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
