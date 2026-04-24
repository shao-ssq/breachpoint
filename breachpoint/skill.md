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

## /breachpoint query <问题>

精准查询模式，多阶段检索 + 关系路径分析 + 社区感知。

### 步骤 1 — 问题解析

Claude 分析用户问题，提取：
- **核心实体**：问题中的具体名词（系统名、类名、属性名）
- **关键词**：用于模糊匹配的词（长度 > 1）
- **查询类型**：
  - `definition`：定义查询（"X是什么"）
  - `relation`：关系查询（"X和Y的关系"、"X如何连接到Y"）
  - `enumeration`：枚举查询（"所有X"、"哪些系统"）

将提取结果记录为 Python 列表格式，用于步骤 Q2。

完成后输出：`[1 完成] 实体: <entities>，关键词: <terms>，查询类型: <type>`

### 步骤 2 — 多阶段节点检索

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from breachpoint.query import stage2_retrieve

entities = ENTITIES  # ['实体1', '实体2']
terms = TERMS        # ['关键词1', '关键词2']

results = stage2_retrieve('breachpoint-out/graph.json', entities, terms)
print(json.dumps(results, ensure_ascii=False, indent=2))
" > breachpoint-out/query_stage2.json 2>&1
cat breachpoint-out/query_stage2.json
```

读取输出，按优先级 `exact > label > summary > edge` 选取种子节点。

完成后输出：`[2 完成] 精确命中: <exact数量>，标签命中: <label数量>，摘要命中: <summary数量>，边命中: <edge数量>，种子节点: <seeds>`

### 步骤 3 — 关系路径分析

仅当 Q1 判断为 `relation` 类型时执行。将 Q2 中 exact/label 命中的前两个节点作为 NODE_A 和 NODE_B：

```bash
$(cat breachpoint-out/.bp_python) -c "
from breachpoint.query import stage3_paths
for path in stage3_paths('breachpoint-out/graph.json', 'NODE_A', 'NODE_B'):
    print(path)
" 2>&1
```

完成后输出：`[3 完成] 找到 <数量> 条路径`（若跳过则输出 `[3 跳过] 非关系查询`）

### 步骤 4 — 社区感知扩展

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from breachpoint.query import stage4_expand

seeds = SEEDS  # 由 Q2 确定的种子节点列表
output = stage4_expand('breachpoint-out/graph.json', seeds)
print(json.dumps(output, ensure_ascii=False, indent=2))
" 2>&1
```

完成后输出：`[4 完成] 扩展到 <数量> 个节点，涵盖 <社区数量> 个社区`

### 步骤 5 — 输出结果

**判断检索是否成功**：若 Q2 的 `exact + label + summary` 命中总数为 0，则输出澄清请求并终止：

```
未能在知识图谱中找到与以下内容相关的节点：
- 实体：<entities>
- 关键词：<terms>

请尝试：
1. 使用更具体的实体名称（如系统名、类名）
2. 检查拼写或使用同义词
3. 运行 /breachpoint 确认图谱已构建
```

**检索成功时**，输出以下结构化内容：

```
**相关节点**（共 N 个）：
- [类型] 节点名 (来源: file.ttl)
  摘要内容
  连接：A --[关系]--> B, ...

**关键关系**：
- A --[关系]--> B（EXTRACTED/INFERRED）
  依据：evidence 内容

**跨文件关联**（如有）：
- file1.ttl 中的 X 与 file2.ttl 中的 Y 通过 [关系] 连接
```

规则：
- 节点按 Q4 的 score 降序排列，最多输出 10 个
- 推断关系标注 `[推断]`，引用事实注明 `source_file`
- 不作额外解释，仅输出结构化内容供调用方使用
---

