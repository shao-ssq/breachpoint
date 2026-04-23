"""TTL/RDF 单文件提取 — BreachPoint。

通过 claude CLI 子进程（LLM）直接从 TTL 原文提取节点和边。
跨文件引用的外部节点以 stub 形式保留，待其所在文件处理后自动合并。

公开 API:
    extract(path) -> dict   — {nodes, edges, input_tokens, output_tokens}
"""
from __future__ import annotations
import anthropic
import json
import os
import re
import sys
from pathlib import Path

_TTL_EXTENSIONS: frozenset[str] = frozenset({".ttl", ".turtle", ".n3"})

# 直接使用 Anthropic Python SDK，避免 Windows 上 claude CLI 子进程 PATH/bash 问题
_API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "")
_MODEL = os.environ.get("ANTHROPIC_MODEL", os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-20250514"))

_PROMPT = """\
你是知识图谱提取专家，专门从 TTL/RDF 本体中提取实例级知识图谱。

【提取目标】
只提取具体的实例个体（具名实例），例如：
- odl:Theme（主题任务）的实例
- odl:Person（人员）的实例
- odl:Project（项目）的实例
- odl:Department（部门）的实例
- odl:Tool（工具/系统）的实例
- odl:Indicator（指标）的实例
- odl:Risk（风险）的实例
- odl:Milestone（里程碑）的实例

【跳过本体声明】
以下类型的声明全部跳过，不提取：
- owl:Class、owl:ObjectProperty、owl:DatatypeProperty
- owl:AnnotationProperty、owl:Ontology、owl:Restriction
- rdf:Property、rdfs:Class
- 任何本体类定义（如 odl:hasTodo、odl:belongsTo 等对象属性的定义）

【节点提取规则】
- id：URI 本地名（# 或最后一个 / 之后的部分），例如 ex:Theme_RuleConsistency → "Theme_RuleConsistency"
- label：rdfs:label 的值（优先中文），无则从 id 推导简洁中文名
- type：rdf:type 对应的中文类型名，例如 odl:Theme → "主题任务"、odl:Person → "人员"
- summary：综合该实例所有属性写一句完整中文描述（30-80字）
- 所有数据属性（字面量）以中文字段名扁平保存在节点顶层，例如：
    odl:startTime                → "开始时间"
    odl:status                   → "状态"
    odl:priority                 → "优先级"
    odl:description              → "描述"
    odl:progress                 → "进度"
    odl:riskLevel                → "风险等级"
    odl:departmentName           → "部门名称"
    odl:responsibility           → "职责"
    odl:themeCategory            → "主题类别"
    odl:themeFocus               → "关注领域"
    odl:contentDescription       → "内容描述"
    odl:effectiveness            → "成效"
    odl:savedManMonths           → "节省人月"
    odl:efficiencyGain           → "效率提升"
    odl:progressPercentage       → "进度百分比"
    odl:plannedCompletionTime    → "计划完成时间"
    odl:actualCompletionTime     → "实际完成时间"

【边提取规则】
- 提取所有目标值为 URI 的属性（对象属性三元组）
- source / target：节点的 id（本地名）
- relation：属性的中文名，例如 odl:belongsTo → "属于"、odl:responsibleFor → "负责人"、odl:hasTool → "使用工具"
- confidence：EXTRACTED
- evidence：一句中文说明此关系

【外部引用】
- 列出所有在边中被引用、但本文件中未完整定义的节点 id（本地名）

只输出 JSON，不输出任何其他内容，格式如下：
  nodes: 数组，每个元素包含 id, label, type, summary 及附加中文字段
  edges: 数组，每个元素包含 source, target, relation, confidence, evidence
  external_refs: 字符串数组，列出本文件引用但未定义的节点 id

TTL 文件内容：
```
{ttl_content}
```
"""


def _run_claude(prompt: str) -> str:
    kwargs = {"model": _MODEL, "max_tokens": 8192, "messages": [{"role": "user", "content": prompt}]}
    if _API_KEY and _BASE_URL:
        client = anthropic.Anthropic(api_key=_API_KEY, base_url=_BASE_URL)
    elif _API_KEY:
        client = anthropic.Anthropic(api_key=_API_KEY)
    else:
        raise RuntimeError("未设置 ANTHROPIC_AUTH_TOKEN 环境变量")
    msg = client.messages.create(**kwargs)
    raw = "".join(b.text for b in msg.content if b.type == "text")
    # Strip markdown fences
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$", "", raw)
    # Find first { and last } to extract JSON block
    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last != -1 and last > first:
        raw = raw[first:last+1]
    return raw


def extract(path: str | Path, client=None) -> dict:
    """解析 TTL/RDF 文件，通过 LLM 提取节点和边。

    外部引用节点以 stub 形式返回，
    待其所在文件被处理时 store 会自动合并补全。

    Raises:
        ValueError: 若文件不是支持的 TTL 格式。
    """
    path = Path(path)
    if path.suffix.lower() not in _TTL_EXTENSIONS:
        raise ValueError(f"不支持的文件格式：{path.suffix}。breachpoint 当前仅支持 TTL/RDF 文件。")

    ttl_content = path.read_text(encoding="utf-8", errors="ignore")

    try:
        raw = _run_claude(_PROMPT.format(ttl_content=ttl_content))
        data = json.loads(raw)
    except RuntimeError:
        print("[extract] 未配置 ANTHROPIC_AUTH_TOKEN 环境变量", file=sys.stderr)
        return {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}
    except Exception as exc:
        print(f"[extract] LLM 提取失败: {exc}", file=sys.stderr)
        return {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}

    nodes: list[dict] = data.get("nodes", [])
    edges: list[dict] = data.get("edges", [])
    external_refs: list[str] = data.get("external_refs", [])

    # 为外部引用节点创建 stub，store 后续 merge 会补全
    # 从 ID 前缀推断类型和中文标签
    _STUB_TYPES = {
        "Tool_": "工具", "Indicator_": "指标", "Risk_": "风险",
        "Milestone_": "里程碑", "Department_": "部门", "Meeting_": "会议",
        "Document_": "文档", "Theme_": "主题任务", "Person_": "人员",
        "Project_": "项目", "Todo_": "待办",
    }

    def _make_stub(ref_id: str) -> dict:
        label = ref_id
        node_type = ""
        for prefix, t in _STUB_TYPES.items():
            if ref_id.startswith(prefix):
                label = ref_id[len(prefix):]
                node_type = t
                break
        return {"id": ref_id, "label": label, "type": node_type, "summary": ""}

    defined_ids = {n["id"] for n in nodes}
    for ref_id in external_refs:
        if ref_id not in defined_ids:
            nodes.append(_make_stub(ref_id))
            defined_ids.add(ref_id)

    return {"nodes": nodes, "edges": edges, "input_tokens": 0, "output_tokens": 0}
