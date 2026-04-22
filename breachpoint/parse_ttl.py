"""TTL/RDF 文件解析器 — BreachPoint 知识图谱构建。

两阶段处理：
  1. rdflib 结构解析：提取所有三元组、类、个体、对象属性、数据属性（不遗漏）
  2. LLM 信息补全：通过 claude CLI 子进程（无需 API key），生成全面中文标签和摘要

所有标签与关系名均输出为中文。

公开 API:
    parse_ttl(path) -> dict   — {nodes, edges}
"""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path

# ── 谓词 URI 本地名 → 中文关系名 ─────────────────────────────────────────────

_PREDICATE_CN: dict[str, str] = {
    # RDF 核心
    "type": "类型为",
    # RDFS
    "label": "标签",
    "comment": "描述",
    "subClassOf": "是子类",
    "subPropertyOf": "是子属性",
    "domain": "定义域",
    "range": "值域",
    "isDefinedBy": "定义于",
    "seeAlso": "参见",
    "member": "成员",
    # OWL
    "sameAs": "等同于",
    "differentFrom": "不同于",
    "equivalentClass": "等价类",
    "equivalentProperty": "等价属性",
    "inverseOf": "逆属性",
    "disjointWith": "不相交",
    "hasValue": "取值",
    "onProperty": "属性为",
    "someValuesFrom": "某些值来自",
    "allValuesFrom": "所有值来自",
    "unionOf": "并集",
    "intersectionOf": "交集",
    "complementOf": "补集",
    # 通用数据属性
    "name": "名称",
    "nameCn": "中文名称",
    "nameEn": "英文名称",
    "nameShort": "简称",
    "description": "描述",
    "contentDescription": "内容描述",
    "status": "状态",
    "priority": "优先级",
    "startTime": "开始时间",
    "endTime": "结束时间",
    "deadlineTime": "截止时间",
    "updateTime": "更新时间",
    "plannedCompletionTime": "计划完成时间",
    "actualCompletionTime": "实际完成时间",
    "riskLevel": "风险等级",
    "batchLevel": "批量等级",
    "themeCategory": "主题分类",
    "effectiveness": "成效",
    "savedManMonths": "节省人月数",
    "efficiencyGain": "效率提升",
    "responsibility": "职责",
    "role": "角色",
    "email": "邮箱",
    "progress": "进度",
    "remark": "备注",
    "basis": "依据",
    "requirement": "需求",
    "solution": "解决方案",
    "blockingIssue": "阻碍事项",
    "meetingTitle": "会议标题",
    "meetingType": "会议类型",
    "meetingContent": "会议内容",
    "meetingConclusion": "会议结论",
    "decisionRecorded": "决策记录",
    "attendees": "参会人员",
    "host": "主持人",
    "recorder": "记录人",
    "departmentName": "部门名称",
    "departmentCn": "部门中文名",
    "departmentEn": "部门英文名",
    "departmentShort": "部门简称",
    # 对象属性（关系）
    "belongsTo": "属于",
    "contains": "包含",
    "subordinateTo": "隶属于",
    "partOf": "是...的一部分",
    "responsibleFor": "负责",
    "supervises": "分管",
    "leads": "牵头",
    "collaboratesWith": "配合",
    "supports": "支持",
    "hostedBy": "主持人为",
    "recordedBy": "记录人为",
    "assignedTo": "指派给",
    "reportsTo": "汇报给",
    "precedes": "前置于",
    "succeeds": "后续于",
    "parallelWith": "并行于",
    "hasMilestone": "有里程碑",
    "achievedMilestone": "达成里程碑",
    "relatedTo": "关联",
    "reliesOn": "依赖",
    "references": "参考",
    "hasDocument": "有文档",
    "hasRisk": "有风险",
    "hasTodo": "有待办",
    "hasIndicator": "有指标",
    "usesTool": "使用工具",
    "involvesSystem": "涉及系统",
    "discussedIn": "在...中讨论",
    "decisionMadeIn": "决策于",
    "trackedIn": "跟踪于",
    "reportedIn": "报告于",
    "derivesFrom": "源于",
    "contactPerson": "联系人",
    "isCompleted": "是否完成",
}

# ── 节点类型 URI 本地名 → 中文类型名 ─────────────────────────────────────────

_TYPE_CN: dict[str, str] = {
    "Class": "类",
    "ObjectProperty": "对象属性",
    "DatatypeProperty": "数据属性",
    "AnnotationProperty": "注解属性",
    "FunctionalProperty": "函数属性",
    "InverseFunctionalProperty": "反函数属性",
    "TransitiveProperty": "传递属性",
    "SymmetricProperty": "对称属性",
    "Ontology": "本体",
    "Restriction": "约束",
    "NamedIndividual": "命名个体",
    "Project": "项目",
    "Theme": "主题",
    "Task": "任务",
    "Meeting": "会议",
    "Person": "人员",
    "Department": "部门",
    "TodoItem": "待办事项",
    "Risk": "风险",
    "Document": "文档",
    "System": "系统",
    "Tool": "工具",
    "Milestone": "里程碑",
    "Indicator": "指标",
    "Tag": "标签",
}

_SCHEMA_NS = (
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2001/XMLSchema#",
)

_ENRICH_PROMPT_TMPL = """\
你是 RDF 知识图谱专家。给定从 TTL 文件解析出的一批节点原始数据（包含所有属性），以及对应的 TTL 原文片段，请为每个节点生成：

1. **label**：简洁中文标签（2-6字，优先使用已有中文名称）
2. **summary**：全面中文摘要（一段话，必须涵盖节点的所有重要属性值，不得遗漏任何信息）

规则：
- 如果节点已有合适的中文名称，保留并使用它作为 label
- summary 需将所有属性值用自然语言串联，避免直接罗列 key:value
- 输出 JSON 数组，格式：[{{"id": "节点id", "label": "中文标签", "summary": "全面中文摘要"}}, ...]
- 仅输出 JSON 数组，不输出任何其他内容

TTL 原文片段（供上下文参考）：
```
{ttl_context}
```

节点原始数据（共 {count} 个）：
{nodes_json}
"""


def _local_name(uri: str) -> str:
    if "#" in uri:
        return uri.split("#")[-1]
    return uri.rstrip("/").split("/")[-1]


def _camel_to_cn(name: str) -> str:
    s = re.sub(r"([A-Z][a-z]+)", r" \1", name)
    s = re.sub(r"([A-Z]+)(?=[A-Z][a-z])", r" \1", s)
    s = re.sub(r"_+", " ", s)
    return s.strip()


def _make_id(uri: str) -> str:
    local = _local_name(uri)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", local)
    return cleaned.strip("_").lower()[:80] or "node"


def _get_label(graph, uri_ref, local: str) -> str:
    try:
        from rdflib.namespace import RDFS
        zh = [str(o) for o in graph.objects(uri_ref, RDFS.label)
              if hasattr(o, "language") and o.language in ("zh", "zh-CN", "zh-TW")]
        if zh:
            return zh[0]
        any_label = [str(o) for o in graph.objects(uri_ref, RDFS.label)]
        if any_label:
            return any_label[0]
    except Exception:
        pass
    return _camel_to_cn(local)


def _get_comment(graph, uri_ref) -> str:
    try:
        from rdflib.namespace import RDFS
        comments = [str(o) for o in graph.objects(uri_ref, RDFS.comment)]
        return comments[0] if comments else ""
    except Exception:
        return ""


def _get_node_type(graph, uri_ref) -> str:
    try:
        from rdflib.namespace import RDF
        for t in graph.objects(uri_ref, RDF.type):
            t_local = _local_name(str(t))
            if t_local in _TYPE_CN:
                return _TYPE_CN[t_local]
    except Exception:
        pass
    return "个体"


def _pred_to_cn(pred_uri: str) -> str:
    local = _local_name(pred_uri)
    return _PREDICATE_CN.get(local, _camel_to_cn(local) or local)


def _build_node_context(node: dict) -> str:
    """将节点所有字段拼接为可读文本，供 LLM 参考。"""
    parts = []
    skip = {"id", "label", "type", "summary", "source_file"}
    for k, v in node.items():
        if k not in skip and v:
            parts.append(f"{k}={v}")
    return " | ".join(parts) if parts else ""


def _enrich_with_llm(
    nodes: list[dict],
    ttl_text: str,
    batch_size: int = 15,
) -> dict[str, dict]:
    """通过 claude CLI 子进程为节点补全中文标签和全面摘要。

    使用本机已配置的 Claude Code CLI（claude -p），无需 API key 或 client 对象。
    Returns:
        {node_id: {"label": "...", "summary": "..."}}
    """
    import sys
    enriched: dict[str, dict] = {}
    ttl_context = ttl_text[:6000] if len(ttl_text) > 6000 else ttl_text

    for i in range(0, len(nodes), batch_size):
        batch = nodes[i: i + batch_size]

        node_descs = []
        for n in batch:
            ctx = _build_node_context(n)
            node_descs.append({
                "id": n["id"],
                "当前标签": n.get("label", ""),
                "节点类型": n.get("type", ""),
                "已有摘要": n.get("summary", ""),
                "所有属性": ctx,
            })

        prompt = _ENRICH_PROMPT_TMPL.format(
            ttl_context=ttl_context,
            count=len(batch),
            nodes_json=json.dumps(node_descs, ensure_ascii=False, indent=2),
        )

        try:
            result = subprocess.run(
                ["claude", "-p", prompt],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            raw = result.stdout.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            items = json.loads(raw)
            for item in items:
                nid = item.get("id", "")
                if nid:
                    enriched[nid] = {
                        "label": item.get("label", ""),
                        "summary": item.get("summary", ""),
                    }
        except FileNotFoundError:
            print("[parse_ttl] 未找到 claude 命令，跳过 LLM 补全（请确认 Claude Code CLI 已安装）", file=sys.stderr)
            break
        except Exception as exc:
            print(f"[parse_ttl] LLM 补全批次 {i//batch_size+1} 失败: {exc}", file=sys.stderr)

    return enriched


def parse_ttl(
    path: str | Path,
) -> dict:
    """解析 TTL/RDF 文件，两阶段处理后返回 {nodes, edges}。

    阶段一：rdflib 提取所有三元组（结构完整，零遗漏）
    阶段二：claude CLI 子进程补全中文标签和摘要

    Returns:
        {
            "nodes": [{"id", "label", "type", "summary", "source_file", ...所有数据属性}],
            "edges": [{"source", "target", "relation", "confidence", "evidence"}],
        }
    """
    try:
        import rdflib
        from rdflib import URIRef, Literal, BNode
        from rdflib.namespace import RDF, RDFS, OWL
    except ImportError:
        raise ImportError("rdflib 未安装 — 请运行: pip install rdflib")

    path = Path(path)
    ttl_text = path.read_text(encoding="utf-8", errors="ignore")

    g = rdflib.Graph()
    g.parse(str(path), format="turtle")

    source_file = str(path)

    # ── 阶段一：rdflib 结构解析 ────────────────────────────────────────────

    uri_subjects: set[str] = set()
    for s, _p, o in g:
        if isinstance(s, URIRef) and not any(str(s).startswith(ns) for ns in _SCHEMA_NS):
            uri_subjects.add(str(s))
        if isinstance(o, URIRef) and not any(str(o).startswith(ns) for ns in _SCHEMA_NS):
            uri_subjects.add(str(o))

    nodes: list[dict] = []
    uri_to_id: dict[str, str] = {}
    used_ids: set[str] = set()

    for uri_str in sorted(uri_subjects):
        uri_ref = URIRef(uri_str)
        local = _local_name(uri_str)
        base_id = _make_id(uri_str)

        node_id = base_id
        counter = 1
        while node_id in used_ids:
            node_id = f"{base_id}_{counter}"
            counter += 1
        used_ids.add(node_id)
        uri_to_id[uri_str] = node_id

        label = _get_label(g, uri_ref, local)
        summary = _get_comment(g, uri_ref)
        node_type = _get_node_type(g, uri_ref)

        node: dict = {
            "id": node_id,
            "label": label,
            "type": node_type,
            "summary": summary,
            "source_file": source_file,
        }

        # 收集所有字面量属性（数据属性）
        for pred, obj in g.predicate_objects(uri_ref):
            if not isinstance(obj, Literal):
                continue
            pred_local = _local_name(str(pred))
            if pred_local in ("label", "comment"):
                continue
            cn_key = _PREDICATE_CN.get(pred_local, _camel_to_cn(pred_local) or pred_local)
            node[cn_key] = str(obj)

        nodes.append(node)

    # 边：对象属性三元组
    edges: list[dict] = []
    seen_edges: set[tuple] = set()
    SKIP_PREDS = {str(RDFS.label), str(RDFS.comment)}
    _SKIP_TYPE_TARGETS = _SCHEMA_NS

    for s, p, o in g:
        if not isinstance(s, URIRef) or not isinstance(o, URIRef):
            continue
        if isinstance(o, Literal):
            continue
        s_str, p_str, o_str = str(s), str(p), str(o)
        if any(s_str.startswith(ns) for ns in _SCHEMA_NS):
            continue
        if p_str in SKIP_PREDS:
            continue
        if p_str == str(RDF.type) and any(o_str.startswith(ns) for ns in _SKIP_TYPE_TARGETS):
            continue

        src_id = uri_to_id.get(s_str)
        tgt_id = uri_to_id.get(o_str)
        if not src_id or not tgt_id:
            continue

        relation = _pred_to_cn(p_str)
        key = (src_id, tgt_id, relation)
        if key in seen_edges:
            continue
        seen_edges.add(key)

        src_label = next((n["label"] for n in nodes if n["id"] == src_id), src_id)
        tgt_label = next((n["label"] for n in nodes if n["id"] == tgt_id), tgt_id)

        edges.append({
            "source": src_id,
            "target": tgt_id,
            "relation": relation,
            "confidence": "EXTRACTED",
            "evidence": f"三元组：{src_label} → {relation} → {tgt_label}",
        })

    # ── 阶段二：claude CLI 补全中文标签和摘要 ─────────────────────────────────

    if nodes:
        enriched = _enrich_with_llm(nodes, ttl_text)
        for node in nodes:
            nid = node["id"]
            if nid in enriched:
                if enriched[nid].get("label"):
                    node["label"] = enriched[nid]["label"]
                if enriched[nid].get("summary"):
                    node["summary"] = enriched[nid]["summary"]
        # 同步更新边中的 evidence（使用新标签）
        id_to_label = {n["id"]: n["label"] for n in nodes}
        for edge in edges:
            src_lbl = id_to_label.get(edge["source"], edge["source"])
            tgt_lbl = id_to_label.get(edge["target"], edge["target"])
            edge["evidence"] = f"三元组：{src_lbl} → {edge['relation']} → {tgt_lbl}"

    return {"nodes": nodes, "edges": edges}
