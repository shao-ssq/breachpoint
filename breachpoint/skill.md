---
name: breachpoint
description: TTL/RDF 知识文档图谱 — 增量式 LLM 驱动的跨文档关系发现
trigger: /breachpoint
---

# /breachpoint

将任意目录下的 TTL/RDF 文档转换为可导航的知识图谱。每个文档由 Claude 分析提取实例级概念节点；新文档再与整个已有图谱对比发现跨文档关系——每份文档的每个本体结构都要认真思考，直到找全所有连接。

## 用法

```
/breachpoint                        # 对当前目录执行完整 pipeline
/breachpoint <path>                 # 对指定路径执行完整 pipeline
/breachpoint update <path>          # 增量模式 — 仅处理新增/变更的文档
/breachpoint query "<question>"     # 按关键词搜索图谱
/breachpoint explain "<concept>"    # 描述某个节点及其连接
/breachpoint path "<A>" "<B>"       # 两个概念之间的最短路径
/breachpoint export <format> [path] # 导出图谱 (cypher/graphml/svg/obsidian/json)
/breachpoint cluster-only [path]    # 重新聚类已有图谱，不重新提取
/breachpoint watch <path>           # 监听文档变更（写入 needs_update 标志）
/breachpoint hook install           # 安装 git post-commit hook
/breachpoint install                # 在 Claude Code 中注册 breachpoint skill
```

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

### 步骤 2 — 运行 pipeline

```bash
$(cat breachpoint-out/.bp_python) -m breachpoint process INPUT_PATH
```

pipeline 完成后告诉用户：

```
知识图谱已构建完成。输出文件在 PATH/breachpoint-out/

  graph.html       — 交互式图谱，用浏览器打开
  GRAPH_REPORT.md  — 社区结构和核心连接
  graph.json       — 原始图数据
```

然后从 GRAPH_REPORT.md 粘贴以下三个部分到聊天中：
- 核心节点（top 5）
- 跨文档连接
- 建议探索问题

---

## 对于 update（增量模式）

```bash
$(cat breachpoint-out/.bp_python) -m breachpoint update INPUT_PATH
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

## 对于 explain

加载图谱，找到匹配概念的节点，打印其连接，然后写 3-5 句话解释它是什么、连接到什么、为什么这些连接很重要。

---

## 对于 path

```bash
$(cat breachpoint-out/.bp_python) -c "
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
    conf = f' [{e.get(\"confidence\",\"\")}]' if e.get('confidence') else ''
    parts.append(f'--{e.get(\"relation\",\"\")}{conf}--> {G.nodes[v].get(\"label\", v)}')
print(f'Shortest path ({hops} hops): ' + ' '.join(parts))
" 2>&1
```

替换 SOURCE_LABEL 和 TARGET_LABEL。然后向用户解释这条路径。

---

## 对于 cluster-only

```bash
$(cat breachpoint-out/.bp_python) -c "
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
  "id": "Theme_RuleConsistency",
  "label": "规则一致性",
  "type": "主题任务",
  "summary": "负责确保系统规则在各模块间保持一致，由张三主导，预计本季度完成。",
  "source_file": "relative/path/to/file.ttl",
  "状态": "进行中",
  "优先级": "高",
  "进度百分比": "60%"
}
```

常见中文类型名：`主题任务`、`人员`、`项目`、`部门`、`工具`、`指标`、`风险`、`里程碑`、`待办`、`会议`、`文档`

## 边 Schema

```json
{
  "source": "Theme_RuleConsistency",
  "target": "Person_ZhangSan",
  "relation": "负责",
  "confidence": "EXTRACTED",
  "evidence": "文档中明确声明张三负责规则一致性主题任务。"
}
```

置信度等级：
- `EXTRACTED` — 文档中明确陈述
- `INFERRED` — 从上下文中明确推断
- `AMBIGUOUS` — 可能但不确定

## 诚实规则

- 不要发明边。如果不确定，使用 AMBIGUOUS。
- 边的 relation 字段必须使用中文动词短语，禁止英文。
