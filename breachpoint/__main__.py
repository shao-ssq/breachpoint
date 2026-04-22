"""BreachPoint CLI — document knowledge graph with incremental LLM relationship discovery.

Commands:
  process <path>     analyse all documents and build the knowledge graph
  update  <path>     process only new / changed documents
  query   <q>        BFS search over the graph
  explain <label>    describe a node and its connections
  path    <A> <B>    shortest path between two concepts
  add     <url>      fetch a URL and save it as a document
  watch   <path>     watch for document changes (writes needs_update flag)
  export  <format> [path]  export graph (cypher/graphml/svg/obsidian/json)
  cluster-only <path>  re-cluster existing graph without re-extracting
  save-result        save a Q&A result to graph memory
  hook    install    install git post-commit hook
  install            register BreachPoint skill in Claude Code / platform

Usage:
  breachpoint process ./docs
  breachpoint update  ./docs
  breachpoint query   "transformer architecture"
  breachpoint explain "attention mechanism"
  breachpoint path    "BERT" "attention"
  breachpoint add     https://arxiv.org/abs/1706.03762
  breachpoint watch   ./docs
  breachpoint cluster-only .
  breachpoint hook install
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

# Allow running as script (PyCharm debugger) without package context
if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _out_dir(root: Path) -> Path:
    return root / "breachpoint-out"


def _community_labels(communities: dict) -> dict:
    return {cid: f"社区 {cid}" for cid in communities}


# ── process / update ─────────────────────────────────────────────────────────

def cmd_process(args: list[str], incremental: bool = False) -> None:
    from .detect import detect
    from .extract import extract
    from .relate import relate
    from .store import load, file_hash
    from .build import build
    from .cluster import cluster
    from .report import generate
    from .export import to_json, to_html
    from .cluster import score_all
    from .analyze import god_nodes

    path = Path(args[0]) if args else Path(".")
    do_wiki = "--wiki" in args

    out = _out_dir(path)
    out.mkdir(parents=True, exist_ok=True)

    # ── Phase 0: detect documents ────────────────────────────────────────────
    manifest = detect(path)
    files = manifest["files"]
    print(f"发现 {manifest['total_files']} 个 TTL/RDF 文件（约 {manifest['total_triples']:,} 行三元组）")
    if not files:
        print("未找到 TTL 文件，请确认目录中存在 .ttl / .turtle / .n3 文件。")
        return

    # ── Phase 1: extract & relate ────────────────────────────────────────────
    store = load(out)
    processed_count = 0

    for i, finfo in enumerate(files, 1):
        fpath = finfo["path"]
        rel = finfo["rel_path"]
        fhash = file_hash(fpath)

        if incremental and store.is_processed(rel, fhash):
            continue

        print(f"[{i}/{len(files)}] {rel}", end=" ", flush=True)

        try:
            result = extract(fpath)
        except Exception as e:
            print(f"  ✗ {e}")
            continue

        # 写入节点（含 stub）
        new_real_nodes: list[dict] = []
        for node in result["nodes"]:
            store.add_node_and_save(node)
            if node.get("source_file"):   # 非 stub
                new_real_nodes.append(node)

        # 写入文档内部边
        for edge in result["edges"]:
            store.add_edge_and_save(edge)

        # 跨文档关系发现（仅在已有其他文件节点时执行）
        if new_real_nodes and len(store) > len(new_real_nodes):
            cross_edges = relate(new_real_nodes, store.nodes)
            for edge in cross_edges:
                store.add_edge_and_save(edge)
            if cross_edges:
                print(f"  +{len(cross_edges)} 跨文档边", end=" ", flush=True)

        store.mark_processed(rel, fhash)
        store.save()
        processed_count += 1
        print(f"  ✓ {len(new_real_nodes)} 个节点")

    if processed_count == 0 and incremental:
        print("Nothing changed — graph is up to date.")
        return

    print(f"\nBuilding graph ({len(store)} nodes)…")
    G = build(store)
    communities = cluster(G)
    labels = _community_labels(communities)
    cohesion = score_all(G, communities)
    gods = god_nodes(G, top_n=10, communities=communities)

    report = generate(G, communities, labels, root=str(path), tokens={"input": 0, "output": 0})
    (out / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    to_json(G, communities, out / "graph.json")
    to_html(G, communities, out / "graph.html", community_labels=labels)

    if do_wiki:
        from .wiki import to_wiki
        wiki_dir = out / "wiki"
        count = to_wiki(G, communities, wiki_dir, community_labels=labels,
                        cohesion=cohesion, hub_nodes_data=gods)
        print(f"  wiki: {count} articles → {wiki_dir}/")

    # Clear needs_update flag if present
    flag = out / "needs_update"
    if flag.exists():
        flag.unlink()

    print(f"\nDone. {G.number_of_nodes()} nodes · {G.number_of_edges()} edges · {len(communities)} communities")
    print(f"  {out}/graph.html")
    print(f"  {out}/GRAPH_REPORT.md")


# ── query ─────────────────────────────────────────────────────────────────────

def cmd_query(args: list[str]) -> None:
    from .store import load
    from .build import build_from_json
    import networkx as nx

    question = args[0] if args else ""
    root = Path(args[1]) if len(args) > 1 else Path(".")
    graph_path = _out_dir(root) / "graph.json"

    if not graph_path.exists():
        print(f"No graph found at {graph_path}. Run 'breachpoint process' first.")
        return

    data = json.loads(graph_path.read_text(encoding="utf-8"))
    from networkx.readwrite import json_graph as jg
    try:
        G = jg.node_link_graph(data, edges="links")
    except TypeError:
        G = jg.node_link_graph(data)

    terms = [t.lower() for t in question.split() if len(t) > 2]
    scored: list[tuple[float, str]] = []
    for nid, attrs in G.nodes(data=True):
        text = f"{attrs.get('label','')} {attrs.get('summary','')}".lower()
        score = sum(1 for t in terms if t in text)
        if score:
            scored.append((score, nid))

    if not scored:
        print("No matching nodes found.")
        return

    scored.sort(reverse=True)
    seeds = [nid for _, nid in scored[:5]]

    visited: set[str] = set()
    queue = list(seeds)
    result_nodes: list[str] = []
    while queue and len(result_nodes) < 30:
        n = queue.pop(0)
        if n in visited:
            continue
        visited.add(n)
        result_nodes.append(n)
        queue.extend(nb for nb in G.neighbors(n) if nb not in visited)

    print(f"\nTop results for: '{question}'\n")
    for nid in result_nodes[:15]:
        d = G.nodes[nid]
        src = d.get("source_file", "").split("/")[-1].split("\\")[-1]
        print(f"  [{d.get('type','?')}] {d.get('label', nid)}")
        if d.get("summary"):
            print(f"    {d.get('summary','')}")
        if src:
            print(f"    Source: {src}")
        print()

# ── explain ───────────────────────────────────────────────────────────────────

def cmd_explain(args: list[str]) -> None:
    label = args[0] if args else ""
    root = Path(args[1]) if len(args) > 1 else Path(".")
    graph_path = _out_dir(root) / "graph.json"

    if not graph_path.exists():
        print(f"No graph found at {graph_path}.")
        return

    data = json.loads(graph_path.read_text(encoding="utf-8"))
    from networkx.readwrite import json_graph as jg
    try:
        G = jg.node_link_graph(data, edges="links")
    except TypeError:
        G = jg.node_link_graph(data)

    label_lower = label.lower()
    matches = [
        nid for nid in G.nodes()
        if label_lower in G.nodes[nid].get("label", "").lower()
    ]
    if not matches:
        print(f"No node matching '{label}'.")
        return

    nid = matches[0]
    d = G.nodes[nid]
    print(f"\nNode: {d.get('label', nid)}")
    print(f"  ID:       {nid}")
    print(f"  Type:     {d.get('type', '')}")
    print(f"  Summary:  {d.get('summary', '')}")
    print(f"  Source:   {d.get('source_file', '')}")
    print(f"  Degree:   {G.degree(nid)}")
    neighbors = sorted(G.neighbors(nid), key=lambda n: G.degree(n), reverse=True)
    if neighbors:
        print(f"\nConnections ({len(neighbors)}):")
        for nb in neighbors[:15]:
            e = G.edges[nid, nb]
            conf = e.get("confidence", "")
            conf_str = f" [{conf}]" if conf else ""
            print(f"  → {G.nodes[nb].get('label', nb)} [{e.get('relation','')}]{conf_str}")
        if len(neighbors) > 15:
            print(f"  ... and {len(neighbors) - 15} more")


# ── path ──────────────────────────────────────────────────────────────────────

def cmd_path(args: list[str]) -> None:
    if len(args) < 2:
        print("Usage: breachpoint path \"<source>\" \"<target>\" [<path>]", file=sys.stderr)
        sys.exit(1)

    source_label = args[0]
    target_label = args[1]
    root = Path(args[2]) if len(args) > 2 else Path(".")
    graph_path = _out_dir(root) / "graph.json"

    if not graph_path.exists():
        print(f"No graph found at {graph_path}.", file=sys.stderr)
        sys.exit(1)

    data = json.loads(graph_path.read_text(encoding="utf-8"))
    from networkx.readwrite import json_graph as jg
    import networkx as nx
    try:
        G = jg.node_link_graph(data, edges="links")
    except TypeError:
        G = jg.node_link_graph(data)

    def _find(q: str) -> str | None:
        q_lower = q.lower()
        scored = [
            (nid, len(set(q_lower.split()) & set(G.nodes[nid].get("label", "").lower().split())))
            for nid in G.nodes()
            if q_lower in G.nodes[nid].get("label", "").lower()
        ]
        scored.sort(key=lambda x: -x[1])
        return scored[0][0] if scored else None

    src_nid = _find(source_label)
    tgt_nid = _find(target_label)

    if not src_nid:
        print(f"No node matching '{source_label}'.", file=sys.stderr)
        sys.exit(1)
    if not tgt_nid:
        print(f"No node matching '{target_label}'.", file=sys.stderr)
        sys.exit(1)

    try:
        path_nodes = nx.shortest_path(G, src_nid, tgt_nid)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        print(f"No path found between '{source_label}' and '{target_label}'.")
        return

    hops = len(path_nodes) - 1
    segments = []
    for i in range(len(path_nodes) - 1):
        u, v = path_nodes[i], path_nodes[i + 1]
        edata = G.edges[u, v]
        rel = edata.get("relation", "")
        conf = edata.get("confidence", "")
        conf_str = f" [{conf}]" if conf else ""
        if i == 0:
            segments.append(G.nodes[u].get("label", u))
        segments.append(f"--{rel}{conf_str}--> {G.nodes[v].get('label', v)}")
    print(f"Shortest path ({hops} hops):\n  " + " ".join(segments))


# ── export ──────────────────────────────────────────────────────────────────────

def cmd_export(args: list[str]) -> None:
    if not args:
        print("Usage: breachpoint export <format> [path] [--out <dir>]", file=sys.stderr)
        print("Formats: cypher, graphml, svg, obsidian, json", file=sys.stderr)
        sys.exit(1)

    fmt = args[0]
    root = Path(args[1]) if len(args) > 1 and not args[1].startswith("--") else Path(".")
    out_dir = None
    for i, a in enumerate(args):
        if a == "--out" and i + 1 < len(args):
            out_dir = Path(args[i + 1])

    graph_path = _out_dir(root) / "graph.json"
    if not graph_path.exists():
        print(f"No graph found at {graph_path}. Run 'breachpoint process' first.", file=sys.stderr)
        sys.exit(1)

    data = json.loads(graph_path.read_text(encoding="utf-8"))
    from networkx.readwrite import json_graph as jg
    try:
        G = jg.node_link_graph(data, edges="links")
    except TypeError:
        G = jg.node_link_graph(data)

    analysis_path = _out_dir(root) / "analysis.json"
    communities: dict[int, list[str]] = {}
    labels: dict[int, str] = {}
    if analysis_path.exists():
        import networkx as nx
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        communities = {int(k): v for k, v in analysis.get("communities", {}).items()}
        labels = {int(k): v for k, v in analysis.get("labels", {}).items()}
    else:
        from .cluster import cluster
        from .analyze import god_nodes
        communities = cluster(G)
        labels = {cid: f"Community {cid}" for cid in communities}

    if out_dir is None:
        out_dir = _out_dir(root)
    out_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "cypher":
        from .export import to_cypher
        out_path = out_dir / "import.cypher"
        to_cypher(G, out_path)
        print(f"Cypher → {out_path}")
    elif fmt == "graphml":
        from .export import to_graphml
        out_path = out_dir / "graph.graphml"
        to_graphml(G, communities, out_path)
        print(f"GraphML → {out_path}")
    elif fmt == "svg":
        from .export import to_svg
        out_path = out_dir / "graph.svg"
        try:
            to_svg(G, communities, out_path, community_labels=labels)
            print(f"SVG → {out_path}")
        except ImportError as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(1)
    elif fmt == "obsidian":
        from .export import to_obsidian
        from .cluster import score_all
        cohesion = score_all(G, communities)
        out_path = out_dir / "obsidian"
        count = to_obsidian(G, communities, out_path, community_labels=labels, cohesion=cohesion)
        print(f"Obsidian vault → {out_path}/  ({count} notes)")
    elif fmt == "json":
        from .export import to_json
        out_path = out_dir / "graph.json"
        to_json(G, communities, out_path)
        print(f"JSON → {out_path}")
    else:
        print(f"error: unknown format '{fmt}'", file=sys.stderr)
        print("Supported: cypher, graphml, svg, obsidian, json", file=sys.stderr)
        sys.exit(1)


# ── cluster-only ──────────────────────────────────────────────────────────────

def cmd_cluster_only(args: list[str]) -> None:
    root = Path(args[0]) if args else Path(".")
    graph_json = _out_dir(root) / "graph.json"

    if not graph_json.exists():
        print(f"No graph found at {graph_json} — run 'breachpoint process' first.", file=sys.stderr)
        sys.exit(1)

    from networkx.readwrite import json_graph as jg
    from .build import build_from_json
    from .cluster import cluster, score_all
    from .analyze import god_nodes
    from .report import generate
    from .export import to_json

    print("Loading existing graph…")
    raw = json.loads(graph_json.read_text(encoding="utf-8"))
    G = build_from_json(raw)
    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print("Re-clustering…")
    communities = cluster(G)
    labels = {cid: f"Community {cid}" for cid in communities}
    report = generate(G, communities, labels, root=str(root), tokens={"input": 0, "output": 0})
    out = _out_dir(root)
    (out / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    to_json(G, communities, out / "graph.json")
    print(f"Done — {len(communities)} communities. GRAPH_REPORT.md and graph.json updated.")


# ── install ───────────────────────────────────────────────────────────────────

_SKILL_SRC = Path(__file__).parent / "skill.md"
_SKILL_DST = Path.home() / ".claude" / "skills" / "breachpoint" / "SKILL.md"
_CLAUDE_MD_ENTRY = (
    "\n# breachpoint\n"
    "- **breachpoint** (`~/.claude/skills/breachpoint/SKILL.md`) "
    "- knowledge document graph. Trigger: `/breachpoint`\n"
    "When the user types `/breachpoint`, invoke the Skill tool "
    'with `skill: "breachpoint"` before doing anything else.\n'
)

_SETTINGS_HOOK = {
    "matcher": "Glob|Grep",
    "hooks": [
        {
            "type": "command",
            "command": (
                "[ -f breachpoint-out/graph.json ] && "
                r"""echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"breachpoint: Knowledge graph exists. Read breachpoint-out/GRAPH_REPORT.md for hub nodes and community structure before searching raw files."}}' """
                "|| true"
            ),
        }
    ],
}


def _install_claude_hook(project_dir: Path) -> None:
    settings_path = project_dir / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    except json.JSONDecodeError:
        settings = {}
    hooks = settings.setdefault("hooks", {})
    pre_tool = hooks.setdefault("PreToolUse", [])
    hooks["PreToolUse"] = [h for h in pre_tool if "breachpoint" not in str(h)]
    hooks["PreToolUse"].append(_SETTINGS_HOOK)
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"  .claude/settings.json  →  PreToolUse hook registered")


def cmd_install() -> None:
    import shutil
    _SKILL_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_SKILL_SRC, _SKILL_DST)
    print(f"  skill installed  →  {_SKILL_DST}")
    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")
        if "breachpoint" not in content:
            claude_md.write_text(content.rstrip() + _CLAUDE_MD_ENTRY, encoding="utf-8")
            print(f"  CLAUDE.md        →  skill registered")
        else:
            print(f"  CLAUDE.md        →  already registered")
    _install_claude_hook(Path("."))
    print("\nDone. Type /breachpoint in Claude Code to start.")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        if not args:
            cmd = "process"
            rest = ["./odl3"]
        else:
            print("Usage: breachpoint <command> [options]")
            print()
            print("Commands:")
            print("  process <path>              analyse all documents and build knowledge graph")
            print("    --wiki                      also generate wiki/ articles")
            print("  update  <path>              process only new/changed documents")
            print("    --wiki                      also generate wiki/ articles")
            print("  query   <question> [path]   search the graph by keyword")
            print("  explain <label> [path]      describe a node and its connections")
            print("  path    <A> <B> [path]      shortest path between two concepts")
            print("  watch   <path>              watch for document changes")
            print("  export  <format> [path]     export graph (cypher/graphml/svg/obsidian/json)")
            print("  cluster-only <path>         re-cluster existing graph, no re-extraction")
            print("  hook    install             install git post-commit hook")
            print("          uninstall           remove git hooks")
            print("          status              check hook status")
            print("  install                     register skill in Claude Code")
            return
    else:
        cmd = args[0]
        rest = args[1:]

    if cmd == "process":
        cmd_process(rest, incremental=False)
    elif cmd == "update":
        cmd_process(rest, incremental=True)
    elif cmd == "query":
        cmd_query(rest)
    elif cmd == "explain":
        cmd_explain(rest)
    elif cmd == "path":
        cmd_path(rest)
    elif cmd == "watch":
        watch_path = Path(rest[0]) if rest else Path(".")
        if not watch_path.exists():
            print(f"error: path not found: {watch_path}", file=sys.stderr)
            sys.exit(1)
        from .watch import watch as _watch
        try:
            _watch(watch_path)
        except ImportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
    elif cmd == "export":
        cmd_export(rest)
    elif cmd == "cluster-only":
        cmd_cluster_only(rest)
    elif cmd == "hook":
        from .hooks import install as hook_install, uninstall as hook_uninstall, status as hook_status
        subcmd = rest[0] if rest else ""
        if subcmd == "install":
            print(hook_install(Path(".")))
        elif subcmd == "uninstall":
            print(hook_uninstall(Path(".")))
        elif subcmd == "status":
            print(hook_status(Path(".")))
        else:
            print("Usage: breachpoint hook [install|uninstall|status]", file=sys.stderr)
            sys.exit(1)
    elif cmd == "install":
        cmd_install()
    else:
        print(f"error: unknown command '{cmd}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
