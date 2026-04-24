---
name: breachpoint
description: TTL/RDF 知识文档图谱 — 增量式 LLM 驱动的跨文档关系发现
trigger: /breachpoint
---

# /breachpoint

将任意目录下的 TTL/RDF 文档转换为可导航的知识图谱。每个文档由 Claude 分析提取实例级概念节点；新文档再与整个已有图谱对比发现跨文档关系——每份文档的每个本体结构都要认真思考，直到找全所有连接。

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

### 步骤 3 — 逐文件提取节点和边

读取 `breachpoint-out/manifest.json` 中 `files` 数组，**为每个文件启动一个独立子代理并行处理**：用 Agent 工具同时派发所有文件，每个子代理只处理一个文件，完成后返回该文件的提取结果 JSON。等所有子代理完成后进入步骤 4。

每个子代理的任务指令：
> 读取文件 `<path>`（rel_path: `<rel_path>`），按下方提取规则提取所有节点和边，返回 `{ "nodes": [...], "edges": [...] }` JSON，不要写入任何文件。

**提取规则：** 
提取 TTL 文件中的每一个具名资源作为节点，统一处理。

节点包括：
- owl:Class、owl:NamedIndividual、以及任何有 rdf:type 声明的资源
- 有数据属性（字面量）或对象属性的资源
- 被其他资源引用的资源（即使本文件未声明，也作为 stub 节点保留，summary 为空字符串）

**强制语言要求：**
- 所有 label、summary、relation、type 字段必须使用中文，禁止英文单词或短语
- summary 必须是一句完整的中文句子（30-80字），不是碎片化关键词
- relation 必须是中文动词短语，禁止英文动词
- 没有通用中文译名的英文术语：保留缩写后加中文说明，如"CTSP调度系统"

**节点字段：**
- `id`：URI 本地名（# 或最后一个 / 之后的部分）
- `label`：rdfs:label 的中文值优先；无则从 id 推导简洁中文名
- `type`：根据 rdf:type / 使用模式推断中文类型名（"本体类"、"对象属性"、"系统"、"枚举"、"业务流程"等，不要用"节点"）
- `summary`：综合该资源的所有声明写一句完整中文描述（30-80字）
- `source_file`：该文件的 rel_path
- 数据属性（字面量值）以中文字段名扁平展开到节点顶层

**边字段：**
- `source` / `target`：节点的 id（本地名）
- `relation`：从属性名推导的中文动词短语（belongsTo→"属于"、subClassOf→"继承自"、imports→"导入"等）
- `confidence`：`EXTRACTED`（TTL中显式声明）或 `INFERRED`（由结构推断）
- `evidence`：一句中文说明此关系的依据

每个文件提取完成后，将结果整理为如下 JSON 结构：

```
{ "nodes": [...], "edges": [...] }
```

### 步骤 4 — 合并所有文件的提取结果

将所有文件的 nodes 和 edges 合并为一个 JSON 对象（节点按 id 去重，边按 source+target+relation 去重），写入 `breachpoint-out/extraction.json`。

### 步骤 5 — 补全遗漏的跨节点关联关系

读取 `breachpoint-out/extraction.json`，对所有节点两两审查，识别可能遗漏的关联边：

- 对比节点的 `label`、`summary`、`type` 字段，找出语义上存在关联但尚无边连接的节点对
- 重点检查：同类型节点间的继承/组合关系、跨文件节点间的引用关系、stub 节点与已有节点的潜在匹配
- 对每条新发现的边，设置 `confidence: "INFERRED"`，并用一句中文写明 `evidence`

将补全的边追加到 `extraction.json` 的 `edges` 数组（按 source+target+relation 去重，不覆盖已有 `EXTRACTED` 边）。

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

告诉用户：

```
知识图谱已构建完成。输出文件在 PATH/breachpoint-out/

  graph.html       — 交互式图谱，用浏览器打开
  GRAPH_REPORT.md  — 社区结构和核心连接
  graph.json       — 原始图数据
```

---

## 对于 query

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from networkx.readwrite import json_graph
from pathlib import Path

data = json.loads(Path('breachpoint-out/graph.json').read_text(encoding='utf-8'))
try:
    G = json_graph.node_link_graph(data, edges='links')
except TypeError:
    G = json_graph.node_link_graph(data)

question = 'QUESTION'
terms = [t.lower() for t in question.split() if len(t) > 2]
scored = []
for nid, attrs in G.nodes(data=True):
    text = f\"{attrs.get('label','')} {attrs.get('summary','')}\".lower()
    score = sum(1 for t in terms if t in text)
    if score:
        scored.append((score, nid))
scored.sort(reverse=True)
seeds = [nid for _, nid in scored[:5]]

visited, queue, result = set(), list(seeds), []
while queue and len(result) < 25:
    n = queue.pop(0)
    if n in visited: continue
    visited.add(n); result.append(n)
    queue.extend(nb for nb in G.neighbors(n) if nb not in visited)

for nid in result[:15]:
    d = G.nodes[nid]
    src = d.get('source_file', '').split('/')[-1].split(chr(92))[-1]
    print(f'  [{d.get(\"type\",\"?\")}] {d.get(\"label\", nid)}')
    if d.get('summary'): print(f'    {d[\"summary\"]}')
    if src: print(f'    Source: {src}')
    print()
" 2>&1
```

然后用图谱输出回答问题。引用具体事实时注明 `source_file`。

---

## 诚实规则

- 不要发明边。如果不确定，使用 AMBIGUOUS。
- 边的 relation 字段必须使用中文动词短语，禁止英文。
