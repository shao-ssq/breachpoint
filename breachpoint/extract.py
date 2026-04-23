"""TTL/RDF 单文件提取 — BreachPoint。

通过 claude CLI 子进程（LLM）直接从 TTL 原文提取节点和边。
跨文件引用的外部节点以 stub 形式保留，待其所在文件处理后自动合并。

公开 API:
    extract(path) -> dict   — {nodes, edges, input_tokens, output_tokens}
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

_TTL_EXTENSIONS: frozenset[str] = frozenset({".ttl", ".turtle", ".n3"})

_API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "")
_MODEL = os.environ.get("ANTHROPIC_MODEL", os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-20250514"))


def _run_claude(prompt: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic 包未安装")
    kwargs = {"model": _MODEL, "max_tokens": 8192, "messages": [{"role": "user", "content": prompt}]}
    if _API_KEY and _BASE_URL:
        client = anthropic.Anthropic(api_key=_API_KEY, base_url=_BASE_URL)
    elif _API_KEY:
        client = anthropic.Anthropic(api_key=_API_KEY)
    else:
        raise RuntimeError("未设置 ANTHROPIC_AUTH_TOKEN 环境变量")
    msg = client.messages.create(**kwargs)
    raw = "".join(b.text for b in msg.content if b.type == "text")
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```\s*$", "", raw)
    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last != -1 and last > first:
        raw = raw[first:last+1]
    return raw

_PROMPT = """\
你是知识图谱提取专家，专门从 TTL/RDF 本体文件中提取结构化的知识图谱（节点和边）。

【提取目标】
提取 TTL 文件中的每一个具名资源作为节点，统一处理。

节点包括：
- owl:Class、owl:NamedIndividual、以及任何有 rdf:type 声明的资源
- 有数据属性（字面量）或对象属性的资源
- 被其他资源引用的资源（即使本文件未声明，也作为 stub 节点保留）

【强制语言要求】
- 所有 label、summary、relation、type 字段必须使用中文（汉字），禁止任何英文单词或短语。
- summary 必须是一句完整的中文句子（30-80字），不是碎片化关键词。
- relation 必须是中文动词短语，禁止英文动词。
- 没有通用中文译名的英文术语：保留缩写后加中文说明，如"CTSP调度系统"。

【节点提取规则】
- id：URI 本地名（# 或最后一个 / 之后的部分）
- label：rdfs:label 的中文值优先；无则从 id 推导简洁中文名
- type：根据该资源在 TTL 中的 rdf:type / 使用模式自动推断一个中文类型名。
  可以是"本体类"、"对象属性"、"系统"、"枚举"、"业务流程"等具体类型，不要用"节点"这种泛泛的词。
- summary：综合该资源的所有声明写一句完整中文描述（30-80字）

如果一个资源有数据属性（字面量值），以中文字段名扁平展开到节点顶层：
  - 从英文属性名推导简洁中文，如 startTime → "开始时间"、status → "状态"
  - 无法推断的保留英文原名并加中文括号标注，如 "progressPercentage（进度百分比）"

【边提取规则】
- 提取所有对象属性三元组（目标值为 URI 的属性）
- 提取所有结构关系（rdfs:subClassOf、rdfs:domain、rdfs:range、owl:imports、owl:equivalentClass 等）
- relation 从属性名推导中文动词短语，如：
    belongsTo → "属于"、responsibleFor → "负责"、hasTool → "使用工具"
    subClassOf → "继承自"、domain → "属性域为"、range → "属性值域为"
    imports → "导入"、equivalentClass → "等价于"、inverseOf → "逆属性为"
    disjointWith → "互斥于"、subPropertyOf → "子属性为"

通用边字段：
- source / target：节点的 id（本地名）
- confidence：EXTRACTED（TTL中显式声明）或 INFERRED（由结构推断）
- evidence：一句中文说明此关系的依据

【外部引用】
列出所有在边中被引用、但本文件中未完整定义的节点 id（本地名）。

只输出 JSON，不输出任何其他内容，格式如下：
  nodes: 数组，每个元素包含 id, label, type, summary 及附加中文字段
  edges: 数组，每个元素包含 source, target, relation, confidence, evidence
  external_refs: 字符串数组，列出本文件引用但未定义的节点 id

TTL 文件内容：
```
{ttl_content}
```
"""


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
        # 实例前缀（Type_Name 模式）
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
        # 本体层启发：无下划线的 id 通常是类或属性定义
        if not node_type and "_" not in ref_id:
            node_type = "本体类" if ref_id[:1].isupper() else "对象属性"
        return {"id": ref_id, "label": label, "type": node_type, "summary": ""}

    defined_ids = {n["id"] for n in nodes}
    for ref_id in external_refs:
        if ref_id not in defined_ids:
            nodes.append(_make_stub(ref_id))
            defined_ids.add(ref_id)

    return {"nodes": nodes, "edges": edges, "input_tokens": 0, "output_tokens": 0}
