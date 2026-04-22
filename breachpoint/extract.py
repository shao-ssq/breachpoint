"""TTL/RDF 单文件提取 — BreachPoint。

通过 claude CLI 子进程（LLM）直接从 TTL 原文提取节点和边。
跨文件引用的外部节点以 stub 形式保留，待其所在文件处理后自动合并。

公开 API:
    extract(path) -> dict   — {nodes, edges, input_tokens, output_tokens}
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

TTL_EXTENSIONS: frozenset[str] = frozenset({".ttl", ".turtle", ".n3"})

_PROMPT = """\
你是知识图谱提取专家。请从以下 TTL/RDF 文件中提取知识图谱数据。

【节点提取规则】
- 只提取具体实例（某个领域类的具名个体），例如 odl:Project、odl:Person、odl:Theme 的实例
- 跳过本体声明：owl:Class、owl:ObjectProperty、owl:DatatypeProperty、owl:AnnotationProperty、owl:Ontology、owl:Restriction
- id：URI 本地名（# 或最后一个 / 之后的部分），例如 ex:ODL_Project → "ODL_Project"
- label：rdfs:label 的值（优先中文），无则从 id 推导简洁中文名
- type：rdf:type 对应的中文类型名，例如 odl:Project → "项目"、odl:Person → "人员"
- summary：综合所有属性写一句完整中文描述
- 所有数据属性（字面量）以中文字段名扁平保存在节点顶层，例如：
    odl:startTime       → "开始时间"
    odl:status          → "状态"
    odl:priority        → "优先级"
    odl:description     → "描述"
    odl:progress        → "进度"
    odl:riskLevel       → "风险等级"
    odl:departmentName  → "部门名称"
    odl:responsibility  → "职责"
    odl:meetingTitle    → "会议标题"
    odl:meetingContent  → "会议内容"
    odl:effectiveness   → "成效"
    （其他属性自行推断中文名）

【边提取规则】
- 提取所有目标值为 URI 的属性（对象属性三元组）
- source / target：节点的 id（本地名）
- relation：属性的中文名，例如 odl:belongsTo → "属于"、odl:responsibleFor → "负责人"、odl:contains → "包含"
- confidence：EXTRACTED
- evidence：一句中文说明此关系

【外部引用】
- 列出所有在边中被引用、但本文件中未完整定义的节点 id（本地名）

只输出 JSON，不输出任何其他内容：
{
  "nodes": [
    {
      "id": "...",
      "label": "...",
      "type": "...",
      "summary": "...",
      "开始时间": "...",
      "状态": "..."
    }
  ],
  "edges": [
    {
      "source": "...",
      "target": "...",
      "relation": "...",
      "confidence": "EXTRACTED",
      "evidence": "..."
    }
  ],
  "external_refs": ["id1", "id2"]
}

TTL 文件内容：
```
{ttl_content}
```
"""


def _run_claude(prompt: str) -> str:
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    raw = result.stdout.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw


def extract(path: str | Path, client=None) -> dict:
    """解析 TTL/RDF 文件，通过 LLM 提取节点和边。

    外部引用节点以 stub 形式返回，
    待其所在文件被处理时 store 会自动合并补全。

    Raises:
        ValueError: 若文件不是支持的 TTL 格式。
    """
    path = Path(path)
    if path.suffix.lower() not in TTL_EXTENSIONS:
        raise ValueError(f"不支持的文件格式：{path.suffix}。breachpoint 当前仅支持 TTL/RDF 文件。")

    ttl_content = path.read_text(encoding="utf-8", errors="ignore")

    try:
        raw = _run_claude(_PROMPT.format(ttl_content=ttl_content))
        data = json.loads(raw)
    except FileNotFoundError:
        print("[extract] 未找到 claude 命令，请确认 Claude Code CLI 已安装", file=sys.stderr)
        return {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}
    except Exception as exc:
        print(f"[extract] LLM 提取失败: {exc}", file=sys.stderr)
        return {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}

    nodes: list[dict] = data.get("nodes", [])
    edges: list[dict] = data.get("edges", [])
    external_refs: list[str] = data.get("external_refs", [])

    # 为外部引用节点创建 stub，store 后续 merge 会补全
    defined_ids = {n["id"] for n in nodes}
    for ref_id in external_refs:
        if ref_id not in defined_ids:
            nodes.append({
                "id": ref_id,
                "label": ref_id,
                "type": "",
                "summary": "",
            })
            defined_ids.add(ref_id)

    return {"nodes": nodes, "edges": edges, "input_tokens": 0, "output_tokens": 0}
