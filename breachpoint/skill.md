---
name: breachpoint
description: TTL/RDF 知识文档图谱 — 增量式 LLM 驱动的跨文档关系发现
trigger: /breachpoint
---

# /breachpoint

将任意目录下的 TTL/RDF 文档转换为可导航的知识图谱。每个文档由 Claude 分析提取概念节点；新文档再与整个已有图谱对比发现跨文档关系——每份文档的每个本体结构都要认真思考，直到找全所有连接。

## 用法

```
/breachpoint                        # 对当前目录执行完整 pipeline
/breachpoint <path>                 # 对指定路径执行完整 pipeline
/breachpoint <path> --update        # 增量模式 — 仅处理新增/变更的文档
/breachpoint query "<question>"     # 按关键词搜索图谱
/breachpoint explain "<concept>"    # 描述某个节点及其连接
/breachpoint path "<A>" "<B>"       # 两个概念之间的最短路径
/breachpoint export <format> [path] # 导出图谱 (cypher/graphml/svg/obsidian/json)
/breachpoint cluster-only [path]    # 重新聚类已有图谱，不重新提取
```

## 被调用时必须做的事

如果未提供路径，使用 `.`（当前目录）。不要向用户询问路径。

按顺序执行以下步骤，不要跳过。

### 第一步 — 确保 breachpoint 已安装

```bash
if command -v python &>/dev/null; then
    PY=python
elif command -v python3 &>/dev/null; then
    PY=python3
else
    echo "ERROR: No python or python3 found"
    exit 1
fi
$PY -c "import breachpoint" 2>/dev/null || $PY -m pip install breachpoint -q 2>/dev/null || $PY -m pip install breachpoint -q --break-system-packages 2>&1 | tail -3
mkdir -p breachpoint-out
```

如果导入成功，静默进入第二步。

**后续所有 bash 块中使用 `python` 或 `python3`：**

```bash
if command -v python &>/dev/null; then PY=python; elif command -v python3 &>/dev/null; then PY=python3; fi
```

### 第二步 — 检测文档

```bash
$PY -c "
import json
from breachpoint.detect import detect
from pathlib import Path
result = detect(Path('INPUT_PATH'))
print(json.dumps(result))
" > breachpoint-out/.bp_detect.json
```

将 INPUT_PATH 替换为实际路径。静默读取 JSON 并展示简洁摘要：

```
Documents: X files · ~Y triples
  ttl:   N (.ttl .turtle)
  n3:    N (.n3)
```

省略数量为 0 的类别。如果 `total_files == 0` 则停止。

如果 `total_triples` > 500,000 或 `total_files` > 150：展示按文件数排序的前 5 个子目录，询问用户在哪个子目录上运行。等待用户回答后再继续。

否则：直接进入第三步。

### 第三步 — 提取概念和关系

**优先使用原生 pipeline。** 直接运行 `python -m breachpoint process INPUT_PATH`——它处理提取、跨文档关系、聚类、以及用内置 `to_html()` 生成 HTML（含侧边栏、搜索、社区过滤、暗色主题）。

如果原生 pipeline 失败（如缺少 `ANTHROPIC_AUTH_TOKEN`、网络错误），再回退到下面的子代理提取方案。

#### 回退方案：子代理提取

在调度子代理之前，打印时间预估：
- 从 `breachpoint-out/.bp_detect.json` 加载 `total_files`
- 估算需要 agents 数量：`ceil(uncached_files / 15)`
- 打印：`"Extracting: ~N files → X agents"`

##### 第三步.0 — 检查提取缓存

```bash
$PY -c "
import json, hashlib
from pathlib import Path

detect = json.loads(Path('breachpoint-out/.bp_detect.json').read_text())
files = detect.get('files', [])
cache_dir = Path('breachpoint-out/.cache')
cache_dir.mkdir(exist_ok=True)

uncached = []
cached_nodes, cached_edges = [], []

for f in files:
    fpath = Path(f['path'])
    try:
        h = hashlib.sha256(fpath.read_bytes()).hexdigest()[:16]
    except Exception:
        h = 'missing'
    cache_file = cache_dir / f'{h}.json'
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            cached_nodes.extend(data.get('nodes', []))
            cached_edges.extend(data.get('edges', []))
        except Exception:
            uncached.append({**f, 'hash': h})
    else:
        uncached.append({**f, 'hash': h})

Path('breachpoint-out/.bp_cached.json').write_text(json.dumps({'nodes': cached_nodes, 'edges': cached_edges}))
Path('breachpoint-out/.bp_uncached.json').write_text(json.dumps(uncached))
print(f'Cache: {len(files)-len(uncached)} files hit, {len(uncached)} files need extraction')
"
```

如果所有文件都已缓存，直接跳到第四步。

##### 第三步.1 — 拆分为 10-15 文件一组

加载 `breachpoint-out/.bp_uncached.json`。拆分为每组 10-15 个文件。将同一目录的文件分到同一组，使相关文档落在同一 chunk 中。

##### 第三步.2 — 在同一消息中调度所有子代理

调用 Agent 工具多次，**在同一条响应中**——每个 chunk 一次调用。这是它们并行运行的唯一方式。始终使用 `subagent_type="general-purpose"`。

3 个 chunk 的具体示例：
```
[Agent tool call 1: files 1-15, subagent_type="general-purpose"]
[Agent tool call 2: files 16-30, subagent_type="general-purpose"]
[Agent tool call 3: files 31-45, subagent_type="general-purpose"]
```
全部在同一条消息中。不是三条分开的消息。

每个子代理收到完全相同的提示词（替换 FILE_LIST, CHUNK_NUM, TOTAL_CHUNKS, CACHE_DIR）：

```
You are a breachpoint extraction subagent for knowledge documents.

Read each file listed and extract a knowledge graph fragment. Write results to disk.

Files (chunk CHUNK_NUM of TOTAL_CHUNKS):
FILE_LIST

For each file:
1. Read ALL files in this chunk in a SINGLE parallel batch — issue all Read tool calls in one message. NEVER read files one at a time. Sequential reads make the pipeline 5-10x slower.
2. Extract named concepts, entities, claims, topics, methods as nodes
3. Extract relationships between nodes as edges
4. Also note potential connections to concepts in other documents (you will see their IDs in the existing graph if available)

Node schema — output exactly this shape:
{"id": "snake_case_unique_id", "label": "Human Readable Name", "type": "concept|entity|method|claim|topic", "summary": "one sentence description", "source_file": "relative/path/to/file"}

Edge schema — output exactly this shape:
{"source": "node_id", "target": "node_id", "relation": "describes|supports|contradicts|uses|extends|references|semantically_similar_to", "confidence": "EXTRACTED|INFERRED|AMBIGUOUS", "evidence": "direct quote or reasoning"}

Confidence levels:
- EXTRACTED: relationship stated explicitly in the document
- INFERRED: clearly implied by context
- AMBIGUOUS: possible but uncertain — include it, mark it

Output ONLY valid JSON matching this schema (no markdown fences, no explanation):
{"nodes": [...], "edges": [...], "input_tokens": 0, "output_tokens": 0}

Write each individual file's result to: CACHE_DIR/<file_hash>.json  (use the hash from the file list)
Write the merged chunk result to: breachpoint-out/.bp_chunk_CHUNK_NUM.json
```

对于 FILE_LIST 中的每个文件，包含来自 `.bp_uncached.json` 的 hash，以便子代理写入独立的缓存文件。

##### 第三步.3 — 收集、缓存、合并

等待所有子代理完成。对每个 chunk：
- 检查 `breachpoint-out/.bp_chunk_NN.json` 是否存在于磁盘
- 如果缺失，警告：`"chunk N missing — subagent may have been read-only. Re-run with general-purpose agent."`
- 如果超过一半的 chunk 失败，停止并告诉用户重新运行

合并缓存 + 新结果：

```bash
$PY -c "
import json
from pathlib import Path

cached = json.loads(Path('breachpoint-out/.bp_cached.json').read_text())
all_nodes = list(cached.get('nodes', []))
all_edges = list(cached.get('edges', []))
seen_ids = {n['id'] for n in all_nodes}
total_input = 0
total_output = 0

for chunk_file in sorted(Path('breachpoint-out').glob('.bp_chunk_*.json')):
    try:
        data = json.loads(chunk_file.read_text())
        for n in data.get('nodes', []):
            if n['id'] not in seen_ids:
                all_nodes.append(n)
                seen_ids.add(n['id'])
        all_edges.extend(data.get('edges', []))
        total_input += data.get('input_tokens', 0)
        total_output += data.get('output_tokens', 0)
    except Exception as e:
        print(f'warning: {chunk_file.name}: {e}')

Path('breachpoint-out/.bp_extract.json').write_text(json.dumps({
    'nodes': all_nodes,
    'edges': all_edges,
    'input_tokens': total_input,
    'output_tokens': total_output,
}))
print(f'Extraction complete: {len(all_nodes)} nodes, {len(all_edges)} edges')
"
```

清理：`rm -f breachpoint-out/.bp_cached.json breachpoint-out/.bp_uncached.json breachpoint-out/.bp_chunk_*.json`

### 第四步 — 跨文档关系发现

这是 breachpoint 的核心差异化能力：在逐文档提取之后，发现跨文档的关系。

读取 `breachpoint-out/.bp_extract.json`。按 `source_file` 分组节点。对每个文档，识别其节点，然后查看其他文档的节点并寻找连接。

**对于 ≤ 20 个文件的语料库**：自行内联完成——读取节点列表并直接将跨文档边写入 `.bp_extract.json`。

**对于 > 20 个文件的语料库**：在单条消息中为每个源文档调度一个子代理：

子代理提示词：
```
You are a cross-document relationship finder for a knowledge graph.

Nodes from this document (SOURCE_FILE):
SOURCE_NODES_JSON

Sample of nodes from all other documents:
OTHER_NODES_JSON

Find relationships between the source nodes and other-document nodes. Only add edges where there is genuine semantic connection: shared concept, contradicting claim, method used in another paper, prerequisite relationship, etc.

Output ONLY valid JSON (no markdown fences):
{"edges": [{"source": "id", "target": "id", "relation": "...", "confidence": "EXTRACTED|INFERRED|AMBIGUOUS", "evidence": "..."}]}

Write result to: breachpoint-out/.bp_cross_INDEX.json
```

所有子代理完成后，将跨文档边合并到 `.bp_extract.json`：

```bash
$PY -c "
import json
from pathlib import Path

extract = json.loads(Path('breachpoint-out/.bp_extract.json').read_text())
for cross_file in sorted(Path('breachpoint-out').glob('.bp_cross_*.json')):
    try:
        data = json.loads(cross_file.read_text())
        extract['edges'].extend(data.get('edges', []))
    except Exception as e:
        print(f'warning: {cross_file.name}: {e}')

Path('breachpoint-out/.bp_extract.json').write_text(json.dumps(extract))
total_cross = sum(len(json.loads(f.read_text()).get('edges',[])) for f in Path('breachpoint-out').glob('.bp_cross_*.json') if f.exists())
print(f'Cross-document edges added: {total_cross}')
"
rm -f breachpoint-out/.bp_cross_*.json
```

### 第五步 — 构建图谱、聚类、分析、生成输出

```bash
$PY -c "
import json
from breachpoint.build import build_from_json
from breachpoint.cluster import cluster, score_all
from breachpoint.report import generate
from breachpoint.export import to_json, to_html
from breachpoint.analyze import god_nodes
from pathlib import Path

extract = json.loads(Path('breachpoint-out/.bp_extract.json').read_text())

G = build_from_json(extract)
communities = cluster(G)
cohesion = score_all(G, communities)
gods = god_nodes(G, top_n=10, communities=communities)
labels = {cid: f'社区 {cid}' for cid in communities}
tokens = {'input': extract.get('input_tokens', 0), 'output': extract.get('output_tokens', 0)}

report = generate(G, communities, labels, root='INPUT_PATH', tokens=tokens)
Path('breachpoint-out/GRAPH_REPORT.md').write_text(report, encoding='utf-8')
to_json(G, communities, Path('breachpoint-out/graph.json'))
to_html(G, communities, Path('breachpoint-out/graph.html'), community_labels=labels)

Path('breachpoint-out/.bp_analysis.json').write_text(json.dumps({
    'communities': {str(k): v for k, v in communities.items()},
    'cohesion': {str(k): v for k, v in cohesion.items()},
    'gods': gods,
}))

if G.number_of_nodes() == 0:
    print('ERROR: Graph is empty — extraction produced no nodes.')
    raise SystemExit(1)
print(f'Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {len(communities)} communities')
" 2>&1
```

将 INPUT_PATH 替换为实际路径。如果因为包未安装而失败，手动构建输出：
- 将 `breachpoint-out/graph.json` 写为 NetworkX node-link 格式
- 使用 vis.js 编写 `breachpoint-out/graph.html`，节点/边数据以内联 JSON 放入 `<script>` 标签
- 编写 `breachpoint-out/GRAPH_REPORT.md`，总结社区和中心节点

### 第六步 — 标记社区

读取 `breachpoint-out/.bp_analysis.json`。对每个社区键，查看其节点标签并写一个 2-5 个词的中文名称（如 "注意力机制"、"数据管道"、"安全协议"）。默认为 `社区 {cid}`。

然后重新生成报告并保存标签：

```bash
$PY -c "
import json
from breachpoint.build import build_from_json
from breachpoint.cluster import score_all
from breachpoint.report import generate
from pathlib import Path

extract  = json.loads(Path('breachpoint-out/.bp_extract.json').read_text())
analysis = json.loads(Path('breachpoint-out/.bp_analysis.json').read_text())

G = build_from_json(extract)
communities = {int(k): v for k, v in analysis['communities'].items()}
tokens = {'input': extract.get('input_tokens', 0), 'output': extract.get('output_tokens', 0)}

labels = LABELS_DICT

report = generate(G, communities, labels, root='INPUT_PATH', tokens=tokens)
Path('breachpoint-out/GRAPH_REPORT.md').write_text(report, encoding='utf-8')
Path('breachpoint-out/.bp_labels.json').write_text(json.dumps({str(k): v for k, v in labels.items()}))
print('Report updated with community labels')
" 2>&1
```

将 `LABELS_DICT` 替换为你构建的实际字典（如 `{0: "本体核心类", 1: "数据属性", 2: "实例关系"}`）。
将 INPUT_PATH 替换为实际路径。

### 第七步 — 清理和报告

```bash
rm -f breachpoint-out/.bp_detect.json breachpoint-out/.bp_extract.json
rm -f breachpoint-out/.bp_analysis.json breachpoint-out/.bp_labels.json
```

告诉用户：
```
Knowledge graph built. Outputs in PATH/breachpoint-out/

  graph.html       — interactive graph, open in browser
  GRAPH_REPORT.md  — community structure and surprising connections
  graph.json       — raw graph data
```

将 PATH 替换为实际绝对路径。

然后从 GRAPH_REPORT.md 直接粘贴以下三个部分到聊天中：
- Hub Nodes (top 5)
- Surprising Cross-document Connections
- Suggested Questions

不要粘贴完整报告——只贴这三个部分。

然后挑选最有趣的一个建议问题并询问：

> "The most interesting question this graph can answer: **[question]**. Want me to trace it?"

---

## 对于 --update（增量模式）

检查 `breachpoint-out/graph.json` 中的 `processed_files` 映射。重新检测语料库，找出 SHA-256 hash 与存储值不同的文件，仅对变更/新增的文件重新运行第三步到第七步，并与已有图谱合并。

---

## 对于 query

加载 `breachpoint-out/graph.json` 用 Python。

```bash
$PY -c "
import json
from networkx.readwrite import json_graph
from pathlib import Path

data = json.loads(Path('breachpoint-out/graph.json').read_text())
try:
    G = json_graph.node_link_graph(data, edges='links')
except TypeError:
    G = json_graph.node_link_graph(data)

question = 'QUESTION'
terms = [t.lower() for t in question.split() if len(t) > 2]
scored = [(sum(1 for t in terms if t in G.nodes[n].get('label','').lower()), n) for n in G.nodes()]
scored = sorted([(s, n) for s, n in scored if s > 0], reverse=True)
seeds = [n for _, n in scored[:5]]

visited, queue, result = set(), list(seeds), []
while queue and len(result) < 25:
    n = queue.pop(0)
    if n in visited: continue
    visited.add(n); result.append(n)
    queue.extend(nb for nb in G.neighbors(n) if nb not in visited)

for nid in result[:15]:
    d = G.nodes[nid]
    print(f'  [{d.get("type","?")}] {d.get("label", nid)}')
    if d.get('summary'): print(f'    {d["summary"]}')
    if d.get('source_file'): print(f'    Source: {d["source_file"].split("/")[-1]}')
    print()
" 2>&1
```

然后用图谱输出回答问题。引用具体事实时注明 `source_file`。

---

## 对于 explain

加载图谱，找到匹配概念的节点，打印其连接，然后写 3-5 句话解释它是什么、连接到什么、为什么这些连接很重要。

---

## 对于 path

加载图谱，模糊匹配两个标签，打印最短路径及边关系和置信度。

```bash
$PY -c "
import json, sys
import networkx as nx
from networkx.readwrite import json_graph as jg
from pathlib import Path

data = json.loads(Path('breachpoint-out/graph.json').read_text(encoding='utf-8'))
try:
    G = jg.node_link_graph(data, edges='links')
except TypeError:
    G = jg.node_link_graph(data)

def find(q):
    q_l = q.lower()
    scored = [(nid, len(set(q_l.split()) & set(G.nodes[nid].get('label','').lower().split())))
              for nid in G.nodes() if q_l in G.nodes[nid].get('label','').lower()]
    scored.sort(key=lambda x: -x[1])
    return scored[0][0] if scored else None

src = find('SOURCE_LABEL')
tgt = find('TARGET_LABEL')
if not src or not tgt:
    print('Node not found'); sys.exit(1)

try:
    path_nodes = nx.shortest_path(G, src, tgt)
except (nx.NetworkXNoPath, nx.NodeNotFound):
    print('No path found'); sys.exit(0)

hops = len(path_nodes) - 1
parts = [G.nodes[path_nodes[0]].get('label', path_nodes[0])]
for i in range(len(path_nodes)-1):
    u, v = path_nodes[i], path_nodes[i+1]
    e = G.edges[u, v]
    conf = f' [{e.get("confidence","")}]' if e.get('confidence') else ''
    parts.append(f'--{e.get("relation","")} {conf}--> {G.nodes[v].get("label", v)}')
print(f'Shortest path ({hops} hops): ' + ' '.join(parts))
" 2>&1
```

替换 SOURCE_LABEL 和 TARGET_LABEL。然后向用户解释这条路径。

---

## 对于 cluster-only

重新聚类已有图谱，不重新运行提取。适用于手动添加新边或调优社区检测后。

```bash
$PY -c "
import json
from breachpoint.build import build_from_json
from breachpoint.cluster import cluster, score_all
from breachpoint.report import generate
from breachpoint.export import to_json
from pathlib import Path

raw = json.loads(Path('breachpoint-out/graph.json').read_text(encoding='utf-8'))
G = build_from_json(raw)
print(f'Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges')
communities = cluster(G)
labels = {cid: f'社区 {cid}' for cid in communities}
report = generate(G, communities, labels, root='INPUT_PATH', tokens={'input':0,'output':0})
out = Path('breachpoint-out')
(out / 'GRAPH_REPORT.md').write_text(report, encoding='utf-8')
to_json(G, communities, out / 'graph.json')
print(f'Done — {len(communities)} communities. GRAPH_REPORT.md and graph.json updated.')
" 2>&1
```

替换 INPUT_PATH。向用户报告新的社区数量。

---

## 节点 Schema

```json
{
  "id": "attention_mechanism",
  "label": "Attention Mechanism",
  "type": "concept",
  "summary": "Mechanism allowing models to weigh importance of different input positions.",
  "source_file": "relative/path/to/file.pdf"
}
```

## 边 Schema

```json
{
  "source": "attention_mechanism",
  "target": "transformer_architecture",
  "relation": "is core component of",
  "confidence": "EXTRACTED",
  "evidence": "The paper explicitly states attention is the main building block."
}
```

置信度等级：
- `EXTRACTED` — 文档中明确陈述
- `INFERRED` — 从上下文中明确推断
- `AMBIGUOUS` — 可能但不确定

## 诚实规则

- 不要发明边。如果不确定，使用 AMBIGUOUS。
- 不要跳过语料库大小警告。
- 始终在最终报告中显示 token 成本。
- 优先使用 `python -m breachpoint process <path>` 而非手动提取。
