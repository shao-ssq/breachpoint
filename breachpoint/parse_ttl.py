"""TTL/RDF 文件解析器 — BreachPoint 知识图谱构建。

使用 rdflib 解析 Turtle 格式的 RDF 文件，提取：
  - 所有命名个体（节点）
  - 数据属性（节点属性，存为字段）
  - 对象属性（边，节点间关系）
  - 类层次结构
  - 标注属性（标签、描述）

所有标签与关系名均输出为中文。

公开 API:
    parse_ttl(path) -> dict   — {nodes, edges}
"""
from __future__ import annotations
import re
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
    # OWL/RDF 结构类型
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
    # 业务领域类型
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

# 跳过这些命名空间的主体（纯模式层，不作为数据节点）
_SCHEMA_NS = (
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2001/XMLSchema#",
)

# rdf:type 的对象属于这些命名空间时，不创建"类型为"边（避免冗余 OWL 结构边）
_SKIP_TYPE_TARGETS = _SCHEMA_NS


def _local_name(uri: str) -> str:
    """提取 URI 的本地名（# 或最后一个 / 之后的部分）。"""
    if "#" in uri:
        return uri.split("#")[-1]
    return uri.rstrip("/").split("/")[-1]


def _camel_to_cn(name: str) -> str:
    """将 CamelCase / underscore 标识符转为可读的空格分隔词组。"""
    s = re.sub(r"([A-Z][a-z]+)", r" \1", name)
    s = re.sub(r"([A-Z]+)(?=[A-Z][a-z])", r" \1", s)
    s = re.sub(r"_+", " ", s)
    return s.strip()


def _make_id(uri: str) -> str:
    """从 URI 生成 ASCII slug ID。"""
    local = _local_name(uri)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", local)
    return cleaned.strip("_").lower()[:80] or "node"


def _get_label(graph, uri_ref, local: str) -> str:
    """获取中文标签：优先 rdfs:label（中文），其次任意 label，最后拆分本地名。"""
    try:
        from rdflib.namespace import RDFS
        # 优先 @zh 语言标注
        zh = [str(o) for o in graph.objects(uri_ref, RDFS.label)
              if hasattr(o, "language") and o.language in ("zh", "zh-CN", "zh-TW")]
        if zh:
            return zh[0]
        # 任意标签
        any_label = [str(o) for o in graph.objects(uri_ref, RDFS.label)]
        if any_label:
            return any_label[0]
    except Exception:
        pass
    return _camel_to_cn(local)


def _get_comment(graph, uri_ref) -> str:
    """获取 rdfs:comment 作为摘要。"""
    try:
        from rdflib.namespace import RDFS
        comments = [str(o) for o in graph.objects(uri_ref, RDFS.comment)]
        return comments[0] if comments else ""
    except Exception:
        return ""


def _get_node_type(graph, uri_ref) -> str:
    """从 rdf:type 三元组确定节点中文类型名。"""
    try:
        from rdflib.namespace import RDF, OWL, RDFS
        for t in graph.objects(uri_ref, RDF.type):
            t_local = _local_name(str(t))
            if t_local in _TYPE_CN:
                return _TYPE_CN[t_local]
    except Exception:
        pass
    return "个体"


def _pred_to_cn(pred_uri: str) -> str:
    """将谓词 URI 转为中文关系名。"""
    local = _local_name(pred_uri)
    return _PREDICATE_CN.get(local, _camel_to_cn(local) or local)


def parse_ttl(path: str | Path) -> dict:
    """解析 TTL/RDF 文件，返回 BreachPoint 格式的 {nodes, edges}。

    所有标签、关系名均为中文。
    数据属性作为节点的额外字段存储。
    对象属性作为边记录。

    返回::

        {
            "nodes": [{"id", "label", "type", "summary", "source_file", ...附加属性}],
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
    g = rdflib.Graph()
    g.parse(str(path), format="turtle")

    source_file = str(path)

    # ── 第一步：收集所有数据层主体（排除 OWL/RDF/RDFS/XSD 命名空间） ──────

    uri_subjects: set[str] = set()
    for s, _p, o in g:
        if isinstance(s, URIRef) and not any(str(s).startswith(ns) for ns in _SCHEMA_NS):
            uri_subjects.add(str(s))
        if isinstance(o, URIRef) and not any(str(o).startswith(ns) for ns in _SCHEMA_NS):
            uri_subjects.add(str(o))

    # ── 第二步：构建节点 ───────────────────────────────────────────────────

    nodes: list[dict] = []
    uri_to_id: dict[str, str] = {}  # URI → slug id
    used_ids: set[str] = set()

    for uri_str in sorted(uri_subjects):
        uri_ref = URIRef(uri_str)
        local = _local_name(uri_str)
        base_id = _make_id(uri_str)

        # 处理 ID 碰撞
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

        # 收集所有字面量属性（数据属性）作为节点额外字段
        for pred, obj in g.predicate_objects(uri_ref):
            if not isinstance(obj, Literal):
                continue
            pred_local = _local_name(str(pred))
            if pred_local in ("label", "comment"):
                continue  # 已作为 label/summary 处理
            cn_key = _PREDICATE_CN.get(pred_local, _camel_to_cn(pred_local) or pred_local)
            node[cn_key] = str(obj)

        nodes.append(node)

    # ── 第三步：构建边（对象属性三元组） ──────────────────────────────────

    edges: list[dict] = []
    seen_edges: set[tuple] = set()

    # 跳过纯字面量谓词和 rdfs:label/comment（已处理为节点属性）
    SKIP_PREDS = {str(RDFS.label), str(RDFS.comment)}

    for s, p, o in g:
        if not isinstance(s, URIRef) or not isinstance(o, URIRef):
            continue
        if isinstance(o, Literal):
            continue

        s_str, p_str, o_str = str(s), str(p), str(o)

        # 排除模式层主体/宾体
        if any(s_str.startswith(ns) for ns in _SCHEMA_NS):
            continue
        if p_str in SKIP_PREDS:
            continue

        # rdf:type：若目标在 OWL/RDF/RDFS 命名空间则跳过（纯结构信息）
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

    return {"nodes": nodes, "edges": edges}
