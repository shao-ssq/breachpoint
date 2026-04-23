# BreachPoint

将 TTL/RDF 本体文件夹转化为可导航的知识图谱。

BreachPoint 通过 LLM 从 TTL/RDF 文档中提取实例级节点和关系，发现跨文档连接，将图谱聚类为社区，并生成交互式可视化——只需一个普通目录即可。

## 安装

### 第一步：安装 Python 包

```bash
pip install -e .                  # 基础安装
pip install -e ".[all]"           # 含全部可选组件（watch / serve / svg）
```

可选组件：

| 扩展 | 依赖 | 用途 |
|---|---|---|
| `[watch]` | watchdog | `breachpoint watch` 文件监听 |
| `[serve]` | mcp | MCP stdio 服务 |
| `[export]` | matplotlib | `export svg` 导出 |
| `[all]` | 以上全部 | — |

要求 Python 3.10+。

### 第二步：配置环境变量

```bash
export ANTHROPIC_AUTH_TOKEN=sk-ant-...     # 必须
export ANTHROPIC_BASE_URL=https://...      # 可选，用于代理
export ANTHROPIC_MODEL=claude-sonnet-4-...  # 可选，覆盖默认模型
```

默认模型：`claude-sonnet-4-20250514`（同时被 `ANTHROPIC_DEFAULT_SONNET_MODEL` 覆盖）。

> **注意**：环境变量名是 `ANTHROPIC_AUTH_TOKEN`，不是 `ANTHROPIC_API_KEY`。

### 第三步（可选）：注册 Claude Code Skill

在 Claude Code 中启用 `/breachpoint` 命令：

```bash
breachpoint install
```

这一步会：
- 复制 `skill.md` → `~/.claude/skills/breachpoint/SKILL.md`
- 在 `~/.claude/CLAUDE.md` 追加 `/breachpoint` 触发条目
- 在当前目录的 `.claude/settings.json` 注册 PreToolUse hook（图谱存在时提示 Claude 先读报告）

### 第四步（可选）：安装 Git Hook

在 git 仓库目录下运行，提交或切换分支后自动设置"图谱需要更新"标志：

```bash
breachpoint hook install
```

安装后，每次 `git commit` 或 `git checkout` 变更文档时会在 `breachpoint-out/` 写入 `needs_update` 标志，下次运行 `breachpoint update` 时自动检测。

---

## 支持的文件格式

BreachPoint 目前只处理 RDF/Turtle 文件：

| 扩展名 | 格式 |
|---|---|
| `.ttl` | Turtle |
| `.turtle` | Turtle（长扩展名） |
| `.n3` | Notation3 |

## 快速开始

```bash
breachpoint process ./docs      # 构建完整图谱
breachpoint update  ./docs      # 增量更新——仅处理变更文件（基于 SHA-256）
breachpoint query   "你的问题"
breachpoint explain "某个概念"
breachpoint path    "概念A" "概念B"   # 最短路径
```

输出文件位于 `breachpoint-out/`：

| 文件 | 用途 |
|---|---|
| `graph.html` | 交互式力导向图（浏览器打开） |
| `GRAPH_REPORT.md` | 社区结构、枢纽节点、跨文档连接 |
| `graph.json` | 原始节点-链接数据（networkx 格式） |

## 处理流程

```
TTL 目录
   │
   ▼
detect          扫描 .ttl / .turtle / .n3 文件
   │
   ▼
extract         逐文档：LLM 提取实例节点 + 文档内边
   │
   ▼
relate          逐文档：与已有节点对比，发现跨文档边
   │
   ▼
build           组装 NetworkX 图，悬空边静默跳过
   │
   ▼
cluster         Leiden（优先）/ Louvain 社区发现，超大社区二次切分
   │
   ▼
export          graph.html · GRAPH_REPORT.md · graph.json
```

## 全部命令

| 命令 | 说明 |
|---|---|
| `process <path>` | 完整流程——提取、关联、聚类、导出 |
| `update <path>` | 增量模式——仅处理新增/变更文件 |
| `query <问题> [路径]` | BFS 关键词搜索图谱 |
| `explain <标签> [路径]` | 描述节点及其连接 |
| `path <A> <B> [路径]` | 两概念之间的最短路径 |
| `watch <path>` | 监听文件变更，写入 `needs_update` 标志 |
| `cluster-only <路径>` | 重新聚类已有图谱，不重新提取 |
| `export <格式> [路径]` | 导出图谱（见下表） |
| `hook install` | 安装 git post-commit / post-checkout hook |
| `hook uninstall` | 移除 git hook |
| `hook status` | 查看 git hook 状态 |
| `install` | 注册 Claude Code `/breachpoint` skill |

## 导出格式

```bash
breachpoint export json      # NetworkX node-link JSON（默认已生成）
breachpoint export cypher    # Neo4j Cypher 导入脚本
breachpoint export graphml   # GraphML，适用于 Gephi / yEd
breachpoint export svg       # 静态 SVG（需要 matplotlib）
breachpoint export obsidian  # Obsidian 知识库（每节点一个 .md）
```

## 架构

| 模块 | 职责 |
|---|---|
| `detect.py` | 递归扫描目录，返回 TTL 文件清单 |
| `extract.py` | 单文档实例提取——节点、文档内边、外部引用 stub |
| `relate.py` | 跨文档关系发现，批量 LLM 对比 |
| `store.py` | 持久化 JSON 图谱存储，支持增量追踪（SHA-256） |
| `build.py` | NetworkX 图组装，悬空边跳过 |
| `validate.py` | 提取结果 schema 校验 |
| `cluster.py` | Leiden / Louvain 社区发现，含超大社区二次切分 |
| `analyze.py` | 枢纽节点、跨社区惊喜连接、探索问题生成 |
| `report.py` | Markdown 报告组装 |
| `export.py` | 多格式导出（JSON / HTML / SVG / GraphML / Cypher / Obsidian） |
| `wiki.py` | Wiki 风格 Markdown 导出 |
| `watch.py` | 文件系统监听（需要 watchdog） |
| `hooks.py` | Git hook 安装 / 卸载 / 状态查询 |
| `serve.py` | MCP stdio 服务，供 Agent 查询图谱（需要 mcp） |

## 置信度

每条边都带置信度标签：

- **EXTRACTED** — 文档中明确陈述
- **INFERRED** — 由上下文明确推断
- **AMBIGUOUS** — 可能存在但不确定（仍予保留）

## MCP Server

启动 MCP 服务，让 Agent 以编程方式查询图谱：

```bash
python -m breachpoint serve
```

暴露工具：`query_graph`、`get_node`、`get_neighbors`、`get_community`、`god_nodes`、`graph_stats`、`shortest_path`。
