"""Schema 生成 — BreachPoint（TTL/RDF 专用）。

直接从 RDF/OWL 本体结构生成中文 schema，无需 LLM 调用。

公开 API:
    generate_schema(manifest, client, model) -> dict
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any


def generate_schema(manifest: dict, client: Any = None, *, model: str = "") -> dict:
    """从 TTL 文件清单生成中文 schema。

    client / model 参数保留仅为接口兼容，实际不使用。
    """
    files = manifest.get("files", [])
    print(f"\n  检测到 {len(files)} 个 TTL/RDF 文件，直接生成中文 schema…", end=" ", flush=True)

    schema: dict = {
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
