"""Automatic schema generation for BreachPoint.

Analyses ALL documents with lightweight structural scanning (headings,
tables, ID patterns, metadata fields) to produce a tailored schema dict.

Public API:
    generate_schema(manifest, client, model) -> dict
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "claude-sonnet-4-6"

_SYSTEM = """\
You are a knowledge graph schema designer.

Given a structural analysis of ALL documents in a collection, produce a schema
that defines the node types, edge types, and field structure for extracting
knowledge from these documents.

The structural analysis shows:
- Document file paths and sizes
- Heading hierarchy (H1, H2, H3…)
- Table column headers found in each document
- Metadata patterns (key:value tables, ID formats like UC-01, BR-A001, etc.)
- Repeated structural patterns across documents

Output ONLY valid JSON in this exact format:

{
  "nodes": [
    {
      "type": "TYPE_NAME",
      "label_template": "pattern like UC-<number>",
      "fields": {
        "id": "str — unique identifier",
        "label": "str — human readable name",
        "field_name": "str — description and type"
      }
    }
  ],
  "edges": [
    {
      "relation": "verb_phrase",
      "description": "what this relation means",
      "from_type": "SOURCE_TYPE or *",
      "to_type": "TARGET_TYPE or *"
    }
  ],
  "confidence_levels": ["EXTRACTED", "INFERRED", "AMBIGUOUS"],
  "edge_template": {
    "source": "str — source node id",
    "target": "str — target node id",
    "relation": "str — one of the defined relation types",
    "confidence": "str — EXTRACTED|INFERRED|AMBIGUOUS",
    "evidence": "str — quote or reasoning from document"
  }
}

Rules:
- Define 3-8 node types based on the structural patterns you observe.
- Each node type should have 4-12 fields that capture the document's information.
- Define 5-12 edge types covering the relationships between node types.
- Include a mandatory "source_file" field in every node type.
- Node type names should be UPPERCASE_UNDERSCORE.
- Edge relation names should be lowercase_underscore verb phrases.
- Group documents with similar structure into the same node type.
- Output nothing but the JSON object.
"""


def _scan_document(path: str) -> dict:
    """Lightweight structural scan of a document.

    Extracts headings, table headers, metadata patterns without reading full text.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {"headings": [], "table_headers": [], "id_patterns": [], "key_value_pairs": []}

    # Headings
    headings = re.findall(r'^(#{1,6})\s+(.+)', text, re.MULTILINE)
    heading_list = [f"{h[0]} {h[1].strip()}" for h in headings[:30]]  # cap at 30

    # Table header rows (markdown tables: | col1 | col2 | ...)
    table_headers = re.findall(r'^\|(.+?)\|$', text, re.MULTILINE)
    # Filter out separator rows (|---|---|)
    table_headers = [h.strip() for h in table_headers if not re.match(r'^[\s|:-]+$', h)]

    # ID patterns (UC-01, BR-A001, ACT-001, EVT-001, LK-001, etc.)
    id_patterns = set(re.findall(r'\b([A-Z]{1,4}-\d{2,4})\b', text))

    # Key-value table rows (| 项目 | 内容 | or | key | value | style)
    kv_pairs = []
    kv_match = re.findall(r'^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$', text, re.MULTILINE)
    for k, v in kv_match[:15]:
        if not re.match(r'^[\s|:-]+$', k) and not re.match(r'^[\s|:-]+$', v):
            kv_pairs.append(f"{k.strip()}: {v.strip()[:80]}")

    return {
        "headings": heading_list,
        "table_headers": table_headers[:10],
        "id_patterns": sorted(id_patterns)[:15],
        "key_value_pairs": kv_pairs[:10],
    }


def _is_ttl_manifest(manifest: dict) -> bool:
    """判断文件清单是否全部为 TTL/RDF 文件。"""
    files = manifest.get("files", [])
    return bool(files) and all(f.get("ext") in (".ttl", ".turtle", ".n3") for f in files)


def _generate_ttl_schema() -> dict:
    """直接从 RDF/OWL 本体结构生成中文 schema，无需 LLM 调用。"""
    return {
        "nodes": [
            {
                "type": "类",
                "label_template": "本体类",
                "fields": {
                    "id": "唯一标识符（URI 本地名）",
                    "label": "中文标签",
                    "summary": "描述（rdfs:comment）",
                    "source_file": "来源 TTL 文件路径",
                },
            },
            {
                "type": "个体",
                "label_template": "命名个体",
                "fields": {
                    "id": "唯一标识符",
                    "label": "中文标签",
                    "summary": "描述",
                    "source_file": "来源 TTL 文件路径",
                },
            },
            {
                "type": "属性",
                "label_template": "本体属性",
                "fields": {
                    "id": "唯一标识符",
                    "label": "中文标签",
                    "summary": "描述",
                    "source_file": "来源 TTL 文件路径",
                },
            },
        ],
        "edges": [
            {"relation": "类型为", "description": "实例与其所属类型的关系", "from_type": "个体", "to_type": "类"},
            {"relation": "是子类", "description": "类的继承关系", "from_type": "类", "to_type": "类"},
            {"relation": "属于", "description": "归属关系", "from_type": "*", "to_type": "*"},
            {"relation": "负责", "description": "人员对任务/主题的负责关系", "from_type": "*", "to_type": "*"},
            {"relation": "关联", "description": "通用语义关联", "from_type": "*", "to_type": "*"},
            {"relation": "依赖", "description": "依赖或前置关系", "from_type": "*", "to_type": "*"},
            {"relation": "包含", "description": "包含或组成关系", "from_type": "*", "to_type": "*"},
        ],
        "confidence_levels": ["EXTRACTED", "INFERRED", "AMBIGUOUS"],
        "edge_template": {
            "source": "源节点标识符",
            "target": "目标节点标识符",
            "relation": "中文关系名称",
            "confidence": "EXTRACTED|INFERRED|AMBIGUOUS",
            "evidence": "来源三元组或推断依据（中文描述）",
        },
    }


def generate_schema(
    manifest: dict,
    client: Any,
    *,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Analyse all documents structurally and generate a schema dict.

    Args:
        manifest: detection manifest from detect()
        client: anthropic.Anthropic instance
        model: Claude model ID (required, no default)

    Returns:
        schema dict matching the document collection
    """
    import json

    files = manifest.get("files", [])

    # TTL 文件直接从本体结构生成 schema，无需 LLM
    if _is_ttl_manifest(manifest):
        print(f"\n  检测到 {len(files)} 个 TTL/RDF 文件，直接从本体提取 schema…", end=" ", flush=True)
        schema = _generate_ttl_schema()
        print("✓")
        # 保存 schema
        out_env = os.environ.get("BREACHPOINT_OUT")
        if out_env:
            out_path = Path(out_env)
        else:
            first = manifest.get("files", [{}])[0].get("path", ".")
            out_path = Path(first).parent / "breachpoint-out"
        out_path.mkdir(parents=True, exist_ok=True)
        schema_file = out_path / "generated_schema.json"
        schema_file.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Schema 已保存 → {schema_file}")
        return schema

    print(f"\n  Scanning {len(files)} documents structurally…", end=" ", flush=True)

    # Lightweight structural scan of ALL documents
    scans: list[tuple[str, dict]] = []
    for finfo in files:
        struct = _scan_document(finfo["path"])
        scans.append((finfo["rel_path"], struct))

    print(f"✓ scanned {len(scans)} docs")

    # Build structural summary for LLM
    doc_summaries = []
    for rel_path, s in scans:
        lines = [f"## {rel_path}"]
        if s["headings"]:
            lines.append(f"  Headings: {' | '.join(s['headings'][:8])}")
        if s["table_headers"]:
            lines.append(f"  Table cols: {' | '.join(s['table_headers'][:4])}")
        if s["id_patterns"]:
            lines.append(f"  IDs: {', '.join(s['id_patterns'][:8])}")
        if s["key_value_pairs"]:
            lines.append(f"  Metadata: {'; '.join(s['key_value_pairs'][:5])}")
        doc_summaries.append("\n".join(lines))

    structural_text = "\n\n".join(doc_summaries)

    # Build context from manifest
    file_list = "\n".join(
        f"- {f['rel_path']} ({f['words']} words, {f['category']})"
        for f in files[:50]
    )

    prompt = (
        f"Document manifest ({manifest['total_files']} files, {manifest['total_words']:,} words):\n\n"
        f"{file_list}\n\n"
        f"---\n\n"
        f"Structural analysis of ALL documents (headings, tables, IDs, metadata):\n\n"
        f"{structural_text}"
    )

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip code fences
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Schema generation returned invalid JSON: {e}")

    # Save generated schema to breachpoint-out/
    out_env = os.environ.get("BREACHPOINT_OUT")
    if out_env:
        out_path = Path(out_env)
    else:
        # Derive from first file's parent
        first = manifest.get("files", [{}])[0].get("path", ".")
        out_path = Path(first).parent / "breachpoint-out"
    out_path.mkdir(parents=True, exist_ok=True)
    schema_file = out_path / "generated_schema.json"
    schema_file.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Schema generated → {schema_file}")

    return schema
