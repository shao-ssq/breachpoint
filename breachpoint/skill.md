---
name: breachpoint
description: TTL/RDF 知识文档图谱 — 增量式 LLM 驱动的跨文档关系发现
trigger: /breachpoint
---

# /breachpoint

将任意目录下的 TTL/RDF 文档转换为可导航的知识图谱。每个文档由 Claude 分析提取实例级概念节点；新文档再与整个已有图谱对比发现跨文档关系——每份文档的每个本体结构都要认真思考，直到找全所有连接。
- 不要发明边。如果不确定，使用 AMBIGUOUS。
- 边的 relation 字段必须使用中文动词短语，禁止英文。


## /breachpoint \<path>

如果未提供路径，使用 `.`。不要向用户询问路径。

### 步骤 1 — 确认安装，持久化解释器

```bash
PYTHON=""
BP_BIN=$(which breachpoint 2>/dev/null)
if [ -z "$PYTHON" ] && command -v uv >/dev/null 2>&1; then
    _UV_PY=$(uv tool run breachpoint python -c "import sys; print(sys.executable)" 2>/dev/null)
    if [ -n "$_UV_PY" ]; then PYTHON="$_UV_PY"; fi
fi
if [ -z "$PYTHON" ] && [ -n "$BP_BIN" ]; then
    _SHEBANG=$(head -1 "$BP_BIN" | tr -d '#!')
    case "$_SHEBANG" in
        *[!a-zA-Z0-9/_.-]*) ;;
        *) "$_SHEBANG" -c "import breachpoint" 2>/dev/null && PYTHON="$_SHEBANG" ;;
    esac
fi
if [ -z "$PYTHON" ]; then
    if command -v python >/dev/null 2>&1; then PYTHON="python"; else PYTHON="python3"; fi
fi
"$PYTHON" -c "import breachpoint" 2>/dev/null || "$PYTHON" -m pip install breachpoint -q 2>/dev/null || "$PYTHON" -m pip install breachpoint -q --break-system-packages 2>&1 | tail -3
mkdir -p breachpoint-out
"$PYTHON" -c "import sys; open('breachpoint-out/.bp_python', 'w').write(sys.executable)"
```

**后续所有 bash 块用 `$(cat breachpoint-out/.bp_python)` 替代 `python3`。**

### 步骤 2 — 发现 TTL 文件

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from breachpoint.detect import detect
print(json.dumps(detect('INPUT_PATH'), ensure_ascii=False))
" > breachpoint-out/manifest.json
cat breachpoint-out/manifest.json
```

读取输出的 JSON，其中 `files` 数组包含所有 TTL 文件的 `path` 和 `rel_path`。记录文件列表 `breachpoint-out/manifest.json`。

### 步骤 3 — rdflib 精确解析

读取 `breachpoint-out/manifest.json` 中 `files` 数组，解析所有 TTL 文件，直接写入 `extraction.json`：

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from pathlib import Path
from breachpoint.parse import parse_ttl

manifest = json.loads(Path('breachpoint-out/manifest.json').read_text(encoding='utf-8'))
files = manifest['files']

all_nodes, all_edges = {}, {}
for f in files:
    result = parse_ttl(f['path'], f['rel_path'])
    for n in result['nodes']:
        all_nodes.setdefault(n['id'], n)
    for e in result['edges']:
        key = (e.get('source'), e.get('target'), e.get('relation'))
        all_edges.setdefault(key, e)

result = {'nodes': list(all_nodes.values()), 'edges': list(all_edges.values())}
Path('breachpoint-out/extraction.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
print(f'extraction.json: {len(result[\"nodes\"])} nodes, {len(result[\"edges\"])} edges')
"
```

### 步骤 4 — 深度提炼关联边（重要）

**禁止用脚本规则代替语义分析。** 必须由 Claude 亲自阅读节点内容、用语义理解推断关系。

用 bash 读取节点数据供分析：

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from pathlib import Path
data = json.loads(Path('breachpoint-out/extraction.json').read_text(encoding='utf-8'))
existing = set()
for e in data['edges']:
    existing.add((e['source'], e['target']))
    existing.add((e['target'], e['source']))
by_type = {}
for n in data['nodes']:
    by_type.setdefault(n.get('type','?'), []).append(n)
for t, nodes in sorted(by_type.items(), key=lambda x: -len(x[1])):
    print(f'=== {t} ({len(nodes)}) ===')
    for n in nodes:
        print(f'  {n[\"id\"]} | {n[\"label\"]} | {n.get(\"comment\",\"\")[:80]}')
" 2>&1
```

Claude 阅读输出后，按以下维度逐一审查，**每个维度必须输出发现结果**：

1. **枚举类 → 宿主类**：`SessionType/TransStatus/PlanStatus/EventType/ActionType/RuleCategory` 等枚举节点，找其描述的宿主类，添加"描述"边
2. **业务流程 → 系统**：每个 `Process_UCxx` 的 comment 中提到哪些系统，添加"依赖系统"边
3. **组合关系**：`StrategyResultDetail` 与 `StrategyResult`、`ProcessStep` 与 `BusinessProcess` 等部分-整体关系
4. **数据流向**：`PhysicalTable → MaterializedView → LogicalView` 的派生链
5. **客户资产关系**：`Customer` 与 `Account/Loan/BankCard/Wallet` 的持有关系
6. **活动子类**：`BusinessProcessDerivationActivity/FieldMappingActivity/JoinActivity` 等与父类 `DataProcessingActivity` 的继承关系

将所有发现的边用 Python 追加到 `extraction.json`：

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from pathlib import Path
data = json.loads(Path('breachpoint-out/extraction.json').read_text(encoding='utf-8'))
existing = set()
for e in data['edges']:
    existing.add((e['source'], e['target'], e['relation']))

new_edges = INFERRED_EDGES  # Claude 填入推断边列表

added = 0
for e in new_edges:
    key = (e['source'], e['target'], e['relation'])
    if key not in existing:
        existing.add(key)
        data['edges'].append(e)
        added += 1
Path('breachpoint-out/extraction.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
print(f'新增 {added} 条推断边，总边数: {len(data[\"edges\"])}')
" 2>&1
```

每条推断边格式：`{"source": "...", "target": "...", "relation": "中文动词短语", "confidence": "INFERRED", "evidence": "一句中文说明推断依据"}`

### 步骤 5 — 孤立节点二次识别

找出所有孤立节点（无任何边连接），对每个孤立节点强制推断至少一条关联边：

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from pathlib import Path
data = json.loads(Path('breachpoint-out/extraction.json').read_text(encoding='utf-8'))
connected = set()
for e in data['edges']:
    connected.add(e['source'])
    connected.add(e['target'])
isolated = [n for n in data['nodes'] if n['id'] not in connected]
print(f'孤立节点数: {len(isolated)}')
for n in isolated:
    print(f'  [{n[\"type\"]}] {n[\"id\"]} | {n[\"label\"]} | {n.get(\"comment\",\"\")[:100]}')
" 2>&1
```

Claude 阅读每个孤立节点的 label/comment/type，**必须为每个孤立节点找到最相关的已有节点**，推断一条连接边。推断依据可以是：
- label 或 comment 中提到的其他节点名
- 同类型节点的归属关系
- 语义上最接近的上位概念

将这些边追加到 `extraction.json`，`confidence` 设为 `"AMBIGUOUS"`：

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from pathlib import Path
data = json.loads(Path('breachpoint-out/extraction.json').read_text(encoding='utf-8'))
existing = set()
for e in data['edges']:
    existing.add((e['source'], e['target'], e['relation']))

new_edges = ISOLATED_EDGES  # Claude 填入孤立节点推断边列表

added = 0
for e in new_edges:
    key = (e['source'], e['target'], e['relation'])
    if key not in existing:
        existing.add(key)
        data['edges'].append(e)
        added += 1
Path('breachpoint-out/extraction.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
print(f'孤立节点新增 {added} 条边，总边数: {len(data[\"edges\"])}')
" 2>&1
```

### 步骤 6 — 构建图谱

读取 `breachpoint-out/extraction.json`，执行以下步骤：

1. **校验** — 检查输入格式，过滤悬空边警告
2. **创建图** — 创建无向 `nx.Graph`
3. **添加节点** — 以 `id` 为键，其余字段作为属性
4. **添加边** — 跳过端点缺失或不在图中的悬空边，保存 `_src`/`_tgt` 保留原始方向
5. **社区检测** — `cluster(G)` 对图聚类分组
6. **导出** — 写入 `breachpoint-out/graph.json`

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from breachpoint.build import build_from_json
from pathlib import Path

extract = json.loads(Path('breachpoint-out/extraction.json').read_text(encoding='utf-8'))
from breachpoint.export import to_json
from breachpoint.cluster import cluster
G = build_from_json(extract)
communities = cluster(G)
to_json(G, communities, Path('breachpoint-out/graph.json'))
print(f'Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {len(communities)} communities')
" 2>&1
```

### 步骤 7 — 生成报告

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from breachpoint.build import build_from_json
from breachpoint.cluster import cluster
from breachpoint.report import generate
from pathlib import Path

extract = json.loads(Path('breachpoint-out/extraction.json').read_text(encoding='utf-8'))
G = build_from_json(extract)
communities = cluster(G)
labels = {cid: f'社区 {cid}' for cid in communities}
report = generate(G, communities, labels, root='INPUT_PATH', tokens={'input': 0, 'output': 0})
Path('breachpoint-out/GRAPH_REPORT.md').write_text(report, encoding='utf-8')
print('Report written')
" 2>&1
```

### 步骤 8 — 生成交互式 HTML

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from breachpoint.build import build_from_json
from breachpoint.cluster import cluster
from breachpoint.export import to_html
from pathlib import Path

extract = json.loads(Path('breachpoint-out/extraction.json').read_text(encoding='utf-8'))
G = build_from_json(extract)
communities = cluster(G)
labels = {cid: f'社区 {cid}' for cid in communities}
to_html(G, communities, Path('breachpoint-out/graph.html'), community_labels=labels)
print('HTML written')
" 2>&1
```

### 步骤 9 — 告知用户

```
知识图谱已构建完成。输出文件在 PATH/breachpoint-out/

  graph.html       — 交互式图谱，用浏览器打开
  GRAPH_REPORT.md  — 社区结构和核心连接
  graph.json       — 原始图数据
```

---

## /breachpoint query <问题>

精准查询模式，多阶段检索 + 关系路径分析 + 社区感知。

### 步骤 1 — 问题解析

Claude 分析用户问题，提取：
- **核心实体**：问题中的具体名词（系统名、类名、属性名）
- **关键词**：用于模糊匹配的词（长度 > 1）

将提取结果记录为 Python 列表格式，用于步骤 Q2。

完成后输出：`[1 完成] 实体: <entities>，关键词: <terms>`

### 步骤 2 — 多阶段节点检索

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from breachpoint.query import stage2_retrieve

entities = ENTITIES  # ['实体1', '实体2']
terms = TERMS        # ['关键词1', '关键词2']

results = stage2_retrieve('breachpoint-out/graph.json', entities, terms)
import sys; sys.stdout.buffer.write(json.dumps(results, ensure_ascii=False, indent=2).encode('utf-8'))
" > breachpoint-out/query_stage2.json 2>&1
cat breachpoint-out/query_stage2.json
```

读取输出，按优先级 `exact > label > comment > edge` 选取种子节点。

完成后输出：`[2 完成] 精确命中: <exact数量>，标签命中: <label数量>，注释命中: <comment数量>，边命中: <edge数量>，种子节点: <seeds>`

### 步骤 3 — 粗筛扩展

以 Q2 种子节点为起点，3跳 BFS 大范围扩展，获取候选节点和边：

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from breachpoint.query import stage3_coarse

seeds = SEEDS  # 由 Q2 确定的种子节点列表
output = stage3_coarse('breachpoint-out/graph.json', seeds)
import sys; sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False, indent=2).encode('utf-8'))
" > breachpoint-out/query_stage3.json 2>&1
cat breachpoint-out/query_stage3.json
```

完成后输出：`[3 完成] 粗筛节点: <数量>，边: <数量>`

> `query_stage3.json` 是 node-link 格式，边字段为 **`links`**，不是 `edges`。

### 步骤 4 — 精确目标判断

Claude 阅读 Q3 输出，结合用户问题，从候选节点中判断出**最相关的精确目标节点**（通常 2-5 个），记为 TARGETS。

完成后输出：`[4 完成] 精确目标: <TARGETS>`

### 步骤 5 — 精筛 + 社区感知扩展

对 TARGETS 做 5 跳邻域扩展，融合社区感知评分：

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from breachpoint.query import stage5_refine

targets = TARGETS  # 由 Q4 确定的精确目标节点
output = stage5_refine('breachpoint-out/graph.json', targets)
import sys; sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False, indent=2).encode('utf-8'))
" > breachpoint-out/query_stage5.json 2>&1
cat breachpoint-out/query_stage5.json
```

完成后输出：`[5 完成] 精筛节点: <数量>，涵盖 <社区数量> 个社区`

> `query_stage5.json` 是 node-link 格式，边字段为 **`links`**，不是 `edges`。

### 步骤 6 — 回答问题

**若 Q2 命中总数为 0**，输出澄清请求并终止：

```
未能在知识图谱中找到与以下内容相关的节点：
- 实体：<entities>
- 关键词：<terms>

请尝试：
1. 使用更具体的实体名称（如系统名、类名）
2. 检查拼写或使用同义词
3. 运行 /breachpoint 确认图谱已构建
```

**检索成功时**，综合 Q2-Q5 所有阶段结果，直接回答用户问题：
- 以自然语言回答，不输出原始 JSON
- 引用具体节点名、关系、evidence 作为依据
- 节点按 Q5 的 score 降序，最多引用 10 个
---

