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

### 步骤 4 — 构建图谱

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

### 步骤 5 — 生成报告

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

### 步骤 6 — 生成交互式 HTML

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

---

## /breachpoint query <问题>

精准查询模式，多阶段检索 + 关系路径分析 + 社区感知。**每步必须等上一步完成并读取其输出后才能继续。**

### 步骤 Q1 — 问题解析 + 节点检索

Claude 从用户问题提取 `ENTITIES`（具体名词）和 `TERMS`（模糊匹配词，长度 > 1），直接内联到下方脚本执行：

```bash
$(cat breachpoint-out/.bp_python) -c "
import json, sys
from breachpoint.query import stage2_retrieve
results = stage2_retrieve('breachpoint-out/graph.json', ENTITIES, TERMS)
sys.stdout.buffer.write(json.dumps(results, ensure_ascii=False, indent=2).encode('utf-8'))
" > breachpoint-out/query_stage1.json 2>&1
cat breachpoint-out/query_stage1.json
```

结果写入 `breachpoint-out/query_stage1.json`。

### 步骤 Q2 — 选取种子节点

按优先级 `exact > label > comment > edge` 从 `breachpoint-out/query_stage1.json` 中选取种子节点，记为 `SEEDS`，写入 `breachpoint-out/query_stage2.json`。

输出：`[Q2] 精确命中: <exact数量>，标签命中: <label数量>，注释命中: <comment数量>，边命中: <edge数量> → SEEDS: <seeds>`

### 步骤 Q3 — 粗筛扩展

```bash
$(cat breachpoint-out/.bp_python) -c "
import json, sys
from pathlib import Path
from breachpoint.query import stage3_coarse

stage2 = json.loads(Path('breachpoint-out/query_stage2.json').read_text(encoding='utf-8'))
seeds = stage2 if isinstance(stage2, list) else (stage2.get('exact') or stage2.get('label') or stage2.get('comment') or [])
output = stage3_coarse('breachpoint-out/graph.json', seeds)
sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False, indent=2).encode('utf-8'))
" > breachpoint-out/query_stage3.json 2>&1
cat breachpoint-out/query_stage3.json
```

> `query_stage3.json` 是 node-link 格式，边字段为 **`links`**，不是 `edges`。

输出：`[Q3] 粗筛节点: <数量>，边: <数量>`

### 步骤 Q4 — 精确目标判断

读取 `breachpoint-out/query_stage3.json` 的候选节点（id / label / comment / type），结合用户原始问题，选出最相关的5个精确目标节点，记为 `TARGETS`，**以 JSON 列表格式**写入 `breachpoint-out/query_stage4.json`。

判断依据：
- 节点 label/comment 与问题语义最接近
- 优先选 Q2 `exact` 命中节点
- 排除仅因路径经过而出现的无关中间节点

**格式要求：`query_stage4.json` 必须是字符串列表，如 `["node1", "node2", "node3"]`**

输出：`[Q4] 精确目标 TARGETS: <TARGETS>`

### 步骤 Q5 — 精筛 + 社区感知扩展

```bash
$(cat breachpoint-out/.bp_python) -c "
import json, sys
from pathlib import Path
from breachpoint.query import stage5_refine

targets = json.loads(Path('breachpoint-out/query_stage4.json').read_text(encoding='utf-8'))
output = stage5_refine('breachpoint-out/graph.json', targets)
sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False, indent=2).encode('utf-8'))
" > breachpoint-out/query_stage5.json 2>&1
```

### 步骤 Q6 — 回答问题

**先读取以下中间文件（每个文件的格式不同，注意区分）：**
- `query_stage1.json` — dict，包含 `exact`/`label`/`comment`/`edge` 四个键
- `query_stage2.json` — 字符串列表，如 `["seed1", "seed2"]`
- `query_stage3.json` — dict，包含 `nodes`（列表）和 `links`（列表）两个键
- `query_stage4.json` — 字符串列表，如 `["target1", "target2"]`
- `query_stage5.json` — 列表，每个元素是 `{id, label, type, comment, source, community, score, connections}` 的字典

**以 `query_stage5.json` 为主要数据源**（score 降序排列的最终结果节点），结合 Q2 种子、Q3 粗筛上下文和 Q4 精确目标，直接回答用户问题：
- 先给出一句话结论，再展开说明
- 用通俗语言，避免术语堆砌，像向非技术人员解释一样清晰
- 用类比、举例帮助理解复杂关系
- 引用具体节点名、关系、evidence 作为依据，但要解释其含义而非直接罗列
- 节点按 Q5 的 score 降序，最多引用 10 个
- 不输出原始 JSON、SQL、代码片段等技术查询语句
---

