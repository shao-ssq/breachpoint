# BreachPoint

将任意文件夹中的文档转化为可导航的知识图谱。

BreachPoint 通过 LLM 调用从文档中提取概念、实体和关系，发现跨文档连接，将图谱聚类为社区，并导出交互式可视化——只需一个普通目录即可。

## 安装

```bash
pip install -e .
pip install -e ".[all]"   # 包含 watch/serve/svg/ingest 可选组件
```

要求 Python 3.10+。配置环境变量 `ANTHROPIC_API_KEY`（可选 `ANTHROPIC_BASE_URL` 用于代理）。

## 快速开始

```bash
breachpoint process ./docs      # 从所有文档构建图谱
breachpoint update  ./docs      # 增量更新——仅处理变更文件
breachpoint query   "你的问题"
breachpoint explain "某个概念"
breachpoint path    "A" "B"     # 两个概念之间的最短路径
breachpoint add     https://arxiv.org/abs/1706.03762
```

输出文件位于 `breachpoint-out/`：

| 文件 | 用途 |
|---|---|
| `graph.html` | 交互式力导向图（浏览器打开） |
| `GRAPH_REPORT.md` | 社区结构、枢纽节点、意外连接 |
| `graph.json` | 原始节点-链接数据（networkx 格式） |

## 处理流程

```
文档目录 ──► 模式生成 ──► 逐文档提取 ──► 跨文档关系发现
              (Sonnet)      (Haiku)           (Sonnet)
                                │
                                ▼
                    构建图谱 ──► 聚类（Leiden/Louvain）
                                │
                   ┌────────────┼────────────┐
                   ▼            ▼            ▼
                报告生成    HTML 可视化    Wiki 导出
```

1. **detect** — 递归扫描目录中的 `.md`、`.txt`、`.pdf`、`.docx`、`.html`、`.json`、`.csv` 等文件（自动跳过密钥/凭证文件）
2. **schema_gen** — 分析语料结构，通过 Sonnet 生成领域特定的节点/边模式
3. **extract** — 通过 Haiku 逐文档提取概念与关系（每文件一次 LLM 调用）
4. **relate** — 跨文档关系发现；不限 LLM 轮次，直至找出所有连接
5. **build** — 组装 NetworkX 图，校验，去重
6. **cluster** — Leiden 算法聚类，含超大社区重新划分；LLM 为每个社区命名
7. **analyze** — 枢纽节点、意外跨社区连接、探索问题生成
8. **export** — Markdown 报告、交互式 vis.js HTML、Wiki 文章、GraphML、Neo4j Cypher、Obsidian 知识库

## 全部命令

| 命令 | 说明 |
|---|---|
| `process <path>` | 对所有文档执行完整流程 |
| `update <path>` | 增量模式——仅处理新增/变更文档（基于 SHA-256） |
| `query <问题> [路径]` | 基于图的 BFS 关键词搜索 |
| `explain <标签> [路径]` | 描述一个节点及其连接 |
| `path <A> <B> [路径]` | 两个概念之间的最短路径 |
| `add <url>` | 抓取 URL（推文、arXiv、网页、PDF）并保存为文档 |
| `watch <path>` | 文件系统监听——文档变更时通知 |
| `cluster-only <路径>` | 重新聚类已有图谱，不重新提取 |
| `save-result` | 将问答结果保存为图谱记忆，供下次提取使用 |
| `hook install` | 安装 git post-commit/post-checkout 钩子用于自动检测 |
| `hook uninstall` | 移除 git 钩子 |
| `hook status` | 查看钩子状态 |
| `install` | 在 Claude Code 中注册 `/breachpoint` 技能 |

## 导出格式

| 格式 | 函数 | 依赖 |
|---|---|---|
| NetworkX JSON | `to_json()` | — |
| 交互式 HTML | `to_html()` | vis.js，搜索、社区切换 |
| SVG | `to_svg()` | `matplotlib` |
| GraphML | `to_graphml()` | Gephi/yEd |
| Cypher | `to_cypher()` | Neo4j 导入 |
| Obsidian | `to_obsidian()` | Wikilinks，颜色配置 |
| Wiki | wiki 导出 | `markdown-it-py` |
| MCP Server | `serve.py` | Agent 图谱查询 |

## 架构

| 模块 | 职责 |
|---|---|
| `detect.py` | 文档文件发现，安全过滤 |
| `schema_gen.py` | LLM 生成的领域特定提取模式 |
| `extract.py` | 单文档概念/边提取（Haiku） |
| `relate.py` | 跨文档关系发现（不限轮次） |
| `store.py` | 持久化 JSON 图谱存储，支持增量追踪 |
| `build.py` | NetworkX 图组装与校验 |
| `validate.py` | 提取模式校验 |
| `cluster.py` | Leiden/Louvain 社区发现，含重新划分 |
| `analyze.py` | 枢纽节点、意外连接、问题生成 |
| `report.py` | Markdown 报告组装 |
| `export.py` | 多格式导出（JSON/HTML/SVG/GraphML/Cypher/Obsidian） |
| `security.py` | URL 校验、SSRF 防护、标签清洗 |
| `ingest.py` | URL 抓取与问答记忆反馈循环 |
| `watch.py` | 文件系统监听（防抖通知） |
| `hooks.py` | Git post-commit/post-checkout 钩子管理 |
| `wiki.py` | 维基百科风格的 Markdown 导出 |
| `serve.py` | MCP stdio 服务，供 Agent 查询图谱 |

## 置信度

每条边都带有置信度标签：

- **EXTRACTED** — 文档中明确陈述
- **INFERRED** — 由上下文明确推断
- **AMBIGUOUS** — 可能存在但不确定（仍予保留）

## MCP Server

启动 MCP 服务，让 Agent 以编程方式查询图谱：

```bash
python -m breachpoint serve
```

暴露工具：`query_graph`、`get_node`、`get_neighbors`、`get_community`、`god_nodes`、`graph_stats`、`shortest_path`。

## 环境变量

```
ANTHROPIC_API_KEY=sk-...
ANTHROPIC_BASE_URL=...   # 可选代理地址
```
