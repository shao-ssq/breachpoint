# ODL项目本体使用说明

## 概述

ODL(运维开发生命周期管理)项目本体是基于RDF/TTL格式构建的知识图谱，用于管理ODL项目的主题任务、会议记录、人员分工、待办事项、风险等核心信息。

### 文件结构

```
本体/
├── odl_ontology_core.ttl              # 核心本体定义（类、属性）
├── odl_instances_project.ttl          # 项目、部门、人员实例
├── odl_instances_themes.ttl           # 主题任务实例1-4
├── odl_instances_themes2.ttl          # 主题任务实例5-8
├── odl_instances_meetings.ttl         # 会议实例
├── odl_instances_todos_risks.ttl      # 待办事项和风险实例
├── odl_instances_tools_indicators_documents.ttl  # 工具、指标、文档、里程碑实例
└── README.md                          # 本使用说明
```

## 核心概念

### 1. 项目结构层次

```
ODL_Project (项目)
    ├── Theme (主题任务) × 8个
    │   ├── Task (具体的任务)
    │   ├── TodoItem (待办事项)
    │   ├── Risk (风险)
    │   ├── Indicator (指标)
    │   ├── Milestone (里程碑)
    │   ├── Tool (使用的工具)
    │   └── Document (相关文档)
    ├── Meeting (会议)
    │   ├── Participant (参与者)
    │   ├── Host (主持人)
    │   ├── Recorder (记录人)
    │   ├── Conclusion (结论)
    │   └── Decision (决策)
    ├── Person (人员)
    │   ├── Role (角色)
    │   ├── Responsibility (职责)
    │   └── Department (所属部门)
    └── Department (部门)
```

### 2. 八大主题任务

| 主题 | 分类 | 负责人 | 状态 |
|------|------|--------|------|
| 1. 监管规则一致性agent | 运维效能类 | 黄俏龙 | 运营中 |
| 2. 异常报错辅助定位交付物 | 运维效能类 | 何流 | 推广中 |
| 3. 大数据领域可运维性左移 | 数据治理类 | 朱嘉伟/玉如 | 推进中 |
| 4. 关键系统参数开关生命周期管理 | 运维效能类 | 刘林 | 常态化 |
| 5. AI应用可运维性 | AI赋能类 | 徐胜安 | 推广中 |
| 6. 关键批量的量时趋势监控 | 数据治理类 | 刘世芬 | 实施中 |
| 7. ODL会议智能体的应用 | AI赋能类 | - | 启动中 |
| 8. 新专题探索 | - | - | 推进中 |

### 3. 核心关系类型

#### 归属关系
- `belongsTo` - 属于什么项目、主题
- `contains` - 包含什么主题、任务
- `subordinateTo` - 隶属于什么部门
- `partOf` - 是...的一部分

#### 负责关系
- `responsibleFor` - 负责什么主题、任务
- `supervises` - 分管什么主题
- `leads` - 牵头什么工作
- `collaboratesWith` - 配合什么工作
- `supports` - 支持什么工作
- `hostedBy` - 由谁主持会议
- `recordedBy` - 由谁记录会议
- `assignedTo` - 指派给谁

#### 时序关系
- `precedes` - 前置关系
- `succeeds` - 后续关系
- `parallelWith` - 并行关系
- `delayedUntil` - 延期至
- `hasMilestone` - 有里程碑

#### 关联关系
- `relatedTo` - 关联
- `reliesOn` - 依赖
- `references` - 引用文档
- `hasDocument` - 有相关文档
- `hasRisk` - 有风险
- `hasTodo` - 有待办
- `hasIndicator` - 有指标
- `usesTool` - 使用工具
- `hasParticipant` - 有参与者

## 常用查询示例 (SPARQL)

### 1. 查询项目整体概览

```sparql
PREFIX odl: <http://webank.com/odl/ontology#>
PREFIX ex: <http://webank.com/odl/instance#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?theme ?themeLabel ?status ?responsiblePerson
WHERE {
  ex:ODL_Project odl:contains ?theme .
  ?theme a odl:Theme ;
           rdfs:label ?themeLabel ;
           odl:status ?status ;
           odl:responsibleFor ?responsiblePerson .
  ?responsiblePerson rdfs:label ?responsiblePerson .
}
ORDER BY ?theme
```

### 2. 查询某人的职责和负责事项

```sparql
PREFIX odl: <http://webank.com/odl/ontology#>
PREFIX ex: <http://webank.com/odl/instance#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?person ?personLabel ?role ?responsibleTheme ?themeLabel
WHERE {
  ?person a odl:Person ;
          rdfs:label ?personLabel ;
          odl:role ?role ;
          odl:responsibleFor ?responsibleTheme .
  ?responsibleTheme rdfs:label ?themeLabel .
  FILTER (?personLabel IN ("何流", "徐高骞", "江旻"))
}
```

### 3. 查询即将到期的待办事项

```sparql
PREFIX odl: <http://webank.com/odl/ontology#>
PREFIX ex: <http://webank.com/odl/instance#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?todo ?todoLabel ?deadline ?assignedPerson ?personLabel
WHERE {
  ?todo a odl:TodoItem ;
        rdfs:label ?todoLabel ;
        odl:deadlineTime ?deadline ;
        odl:assignedTo ?assignedPerson ;
        odl:isCompleted false .
  ?assignedPerson rdfs:label ?personLabel .
  FILTER (?deadline > NOW())
}
ORDER BY ?deadline
LIMIT 20
```

### 4. 查询各主题的风险情况

```sparql
PREFIX odl: <http://webank.com/odl/ontology#>
PREFIX ex: <http://webank.com/odl/instance#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?theme ?themeLabel ?risk ?riskLabel ?riskLevel ?riskStatus
WHERE {
  ?theme a odl:Theme ;
         rdfs:label ?themeLabel ;
         odl:hasRisk ?risk .
  ?risk rdfs:label ?riskLabel ;
        odl:riskLevel ?riskLevel ;
        odl:riskStatus ?riskStatus .
}
```

### 5. 查询会议决策

```sparql
PREFIX odl: <http://webank.com/odl/ontology#>
PREFIX ex: <http://webank.com/odl/instance#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?meeting ?meetingDate ?decision
WHERE {
  ?meeting a odl:Meeting ;
          odl:meetingDate ?meetingDate ;
          odl:hasDecision ?decision .
  FILTER (?decision != "")
}
ORDER BY DESC(?meetingDate)
```

### 6. 查询项目关键指标

```sparql
PREFIX odl: <http://webank.com/odl/ontology#>
PREFIX ex: <http://webank.com/odl/instance#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?theme ?themeLabel ?indicator ?indicatorName ?value ?target
WHERE {
  ?theme a odl:Theme ;
         rdfs:label ?themeLabel ;
         odl:hasIndicator ?indicator .
  ?indicator rdfs:label ?indicatorName ;
            odl:indicatorValue ?value ;
            odl:targetValue ?target .
}
```

### 7. 查询何流的工作动线

```sparql
PREFIX odl: <http://webank.com/odl/ontology#>
PREFIX ex: <http://webank.com/odl/instance#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?activity ?activityLabel ?type ?content ?meeting ?relatedTheme
WHERE {
  VALUES ?person { ex:Person_HeLiu }

  {
    ?person odl:responsibleFor ?activity .
    ?activity rdfs:label ?activityLabel .
    BIND("责任" AS ?type)
    BIND(?activityLabel AS ?content)
    OPTIONAL { ?activity odl:discussedIn ?relatedTheme }
  }
  UNION
  {
    ?meeting odl:host ?person .
    ?meeting rdfs:label ?activityLabel .
    BIND("主持" AS ?type)
    BIND(ex:Person_HeLiu AS ?activity)
  }
  UNION
  {
    ?todo odl:assignedTo ?person .
    ?todo rdfs:label ?activityLabel ;
          odl:todoDescription ?content .
    BIND("待办" AS ?type)
    OPTIONAL { ?todo odl:belongsTo ?meeting }
    OPTIONAL { ?todo odl:belongsTo ?relatedTheme }
  }
}
ORDER BY ?type, ?activityLabel
```

### 8. 查询徐高骞需要关注的内容

```sparql
PREFIX odl: <http://webank.com/odl/ontology#>
PREFIX ex: <http://webank.com/odl/instance#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?type ?item ?label ?status ?deadline ?theme
WHERE {
  VALUES ?person { ex:Person_XuGaoQian }

  {
    ex:ODL_Project odl:hasRisk ?risk .
    ?risk rdfs:label ?label ;
         odl:riskLevel ?riskLevel .
    FILTER (STR(?riskLevel) = "高")
    BIND("高优先级风险" AS ?type)
    BIND(?risk AS ?item)
    BIND(STR(?riskLevel) AS ?status)
    BIND("" AS ?deadline)
    BIND(?risk AS ?theme)
  }
  UNION
  {
    ?todo odl:assignedTo ?person .
    ?todo rdfs:label ?label ;
          odl:status ?status ;
          odl:deadlineTime ?deadline .
    BIND("待办事项" AS ?type)
    BIND(?todo AS ?item)
    OPTIONAL { ?todo odl:belongsTo ?theme }
  }
  UNION
  {
    ?theme odl:responsibleFor ?person .
    ?theme rdfs:label ?label ;
           odl:status ?status .
    BIND("负责主题" AS ?type)
    BIND(?theme AS ?item)
    BIND(?theme AS ?theme)
  }
}
ORDER BY ?type, ?status
```

### 9. 查询江旻需要关注的报告

```sparql
PREFIX odl: <http://webank.com/odl/ontology#>
PREFIX ex: <http://webank.com/odl/instance#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?document ?documentTitle ?documentType ?date ?theme
WHERE {
  {
    ?document a odl:Document ;
              odl:documentType "月报" ;
              rdfs:label ?documentTitle ;
              odl:documentDate ?date .
    BIND("月度报告" AS ?documentType)
  }
  UNION
  {
    ?meeting a odl:Meeting ;
            odl:meetingType "月度例会" ;
            odl:hasDocument ?document .
    ?document rdfs:label ?documentTitle ;
              odl:documentType ?documentType .
    OPTIONAL { ?meeting odl:startTime ?date }
    BIND("月度例会纪要" AS ?documentType)
  }
  UNION
  {
    ?theme a odl:Theme ;
           odl:hasRisk ?risk .
    ?risk odl:affectsSchedule true .
    ?theme rdfs:label ?documentTitle .
    BIND("延期风险提示" AS ?documentType)
    BIND(?theme AS ?date)
    BIND(?theme AS ?theme)
  }
}
ORDER BY DESC(?date)
```

### 10. 查询各部门批量等级分布

```sparql
PREFIX odl: <http://webank.com/odl/ontology#>
PREFIX ex: <http://webank.com/odl/instance#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?department ?departmentLabel ?indicatorName ?indicatorValue
WHERE {
  ?indicator odl:reportedIn ex:Document_ProgressTracking .
  OPTIONAL { ?department odl:contactPerson ex:Person_XuGaoQian ; rdfs:label ?departmentLabel }
  FILTER (CONTAINS(STR(?indicator), "WTSS") || CONTAINS(STR(?indicator), "批量等级"))
}
```

## GraphDB导入指南

### 1. 创建仓库
1. 登录GraphDB
2. 创建新的仓库，选择"Free Text"存储方式
3. 命名仓库为"ODL_Project"

### 2. 导入文件
1. 进入"Import"标签页
2. 选择"RDF"格式
3. 按以下顺序导入TTL文件：
   - 首先导入: `odl_ontology_core.ttl` (核心本体)
   - 然后导入其他实例文件（顺序不严格要求）
   - `odl_instances_project.ttl`
   - `odl_instances_themes.ttl`
   - `odl_instances_themes2.ttl`
   - `odl_instances_meetings.ttl`
   - `odl_instances_todos_risks.ttl`
   - `odl_instances_tools_indicators_documents.ttl`

### 3. 验证导入
使用以下SPARQL查询验证数据是否正确导入：

```sparql
SELECT (COUNT(?s) AS ?triples)
WHERE {
  ?s ?p ?o .
}
```

## 约束规则说明

### 待办事项约束
- 所有待办事项必须关联到责任人
- 所有待办事项必须有截止时间
- 所有待办事项必须关联到所属会议或项目

### 风险管理约束
- 所有风险必须绑定对应项目或任务
- 所有风险必须标注影响工期和成本的情况

### 会议管理约束
- 所有会议纪要实体必须溯源到项目本体
- 重大会议必须有明确的决策记录

## 知识图谱应用场景

### 1. 会议自动汇总
按项目聚合所有会议决议、待办、风险

### 2. 智能问答
- 项目进度总体如何？
- 谁负责什么工作？
- 哪些任务延期了？
- 上次会议的结论是什么？

### 3. 告警推理
- 计划逾期告警
- 风险未闭环告警
- 待办超时告警

### 4. 人员工作追踪
- 关键人员（何流、徐高骞、江旻）的工作动线
- 待办事项跟踪
- 推进进度分析

## 维护更新

### 添加新的会议
1. 在`odl_instances_meetings.ttl`中添加会议实例
2. 提取会议决策、待办事项，添加到对应文件
3. 更新相关主题的进度信息

### 添加新的待办事项
1. 在`odl_instances_todos_risks.ttl`中添加待办实例
2. 确保关联责任人和截止时间
3. 关联到对应的会议或主题

### 更新指标数据
1. 在`odl_instances_tools_indicators_documents.ttl`中更新指标值
2. 记录测量日期
3. 与历史数据对比分析

## 命名空间说明

| 前缀 | URI | 说明 |
|------|-----|------|
| odl: | http://webank.com/odl/ontology# | 本体类和属性 |
| ex: | http://webank.com/odl/instance# | 实例 |
| rdf: | http://www.w3.org/1999/02/22-rdf-syntax-ns# | RDF核心 |
| rdfs: | http://www.w3.org/2000/01/rdf-schema# | RDFS核心 |
| owl: | http://www.w3.org/2002/07/owl# | OWL核心 |
| xsd: | http://www.w3.org/2001/XMLSchema# | XML Schema |

## 注意事项

1. 本体设计遵循ODL项目的工作流程和管理规范
2. 重点关注何流、徐高骞、江旻等关键人员的工作动线
3. 所有数据来源来自项目讨论过程和知识沉淀
4. 保持与CLAUDE.md中定义的项目结构规范一致
5. 本体不存储源材料，但尽可能保留关键信息

---

*最后更新时间: 2026-04-22*
*版本: 1.0*
