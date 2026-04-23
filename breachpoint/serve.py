# MCP stdio server — exposes graph query tools to Claude and other agents
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
import networkx as nx
from networkx.readwrite import json_graph

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MAX_LABEL_LEN = 256


def sanitize_label(text: str) -> str:
    text = _CONTROL_CHAR_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    if len(text) > _MAX_LABEL_LEN:
        text = text[:_MAX_LABEL_LEN]
    return text


# Source file cache: path -> text (loaded on first access)
_source_cache: dict[str, str] = {}


def _load_graph(graph_path: str) -> nx.Graph:
    try:
        resolved = Path(graph_path).resolve()
        if resolved.suffix != ".json":
            raise ValueError(f"Graph path must be a .json file, got: {graph_path!r}")
        if not resolved.exists():
            raise FileNotFoundError(f"Graph file not found: {resolved}")
        data = json.loads(resolved.read_text(encoding="utf-8"))
        try:
            return json_graph.node_link_graph(data, edges="links")
        except TypeError:
            return json_graph.node_link_graph(data)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"error: graph.json is corrupted ({exc}). Re-run breachpoint process to rebuild.", file=sys.stderr)
        sys.exit(1)


def _communities_from_graph(G: nx.Graph) -> dict[int, list[str]]:
    communities: dict[int, list[str]] = {}
    for node_id, data in G.nodes(data=True):
        cid = data.get("community")
        if cid is not None:
            communities.setdefault(int(cid), []).append(node_id)
    return communities


def _strip_diacritics(text: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _score_nodes(G: nx.Graph, terms: list[str]) -> list[tuple[float, str]]:
    scored = []
    norm_terms = [_strip_diacritics(t).lower() for t in terms]
    for nid, data in G.nodes(data=True):
        norm_label = _strip_diacritics(data.get("label", "")).lower()
        summary = (data.get("summary") or "").lower()
        source = (data.get("source_file") or "").lower()
        score = (
            sum(1 for t in norm_terms if t in norm_label)
            + sum(0.5 for t in norm_terms if t in summary)
            + sum(0.3 for t in norm_terms if t in source)
        )
        if score > 0:
            scored.append((score, nid))
    return sorted(scored, reverse=True)


def _bfs(G: nx.Graph, start_nodes: list[str], depth: int) -> tuple[set[str], list[tuple]]:
    visited: set[str] = set(start_nodes)
    frontier = set(start_nodes)
    edges_seen: list[tuple] = []
    for _ in range(depth):
        next_frontier: set[str] = set()
        for n in frontier:
            for neighbor in G.neighbors(n):
                if neighbor not in visited:
                    next_frontier.add(neighbor)
                    edges_seen.append((n, neighbor))
        visited.update(next_frontier)
        frontier = next_frontier
    return visited, edges_seen


def _dfs(G: nx.Graph, start_nodes: list[str], depth: int) -> tuple[set[str], list[tuple]]:
    visited: set[str] = set()
    edges_seen: list[tuple] = []
    stack = [(n, 0) for n in reversed(start_nodes)]
    while stack:
        node, d = stack.pop()
        if node in visited or d > depth:
            continue
        visited.add(node)
        for neighbor in G.neighbors(node):
            if neighbor not in visited:
                stack.append((neighbor, d + 1))
                edges_seen.append((node, neighbor))
    return visited, edges_seen


def _subgraph_to_text(G: nx.Graph, nodes: set[str], edges: list[tuple], token_budget: int = 2000) -> str:
    char_budget = token_budget * 3
    lines = []
    for nid in sorted(nodes, key=lambda n: G.degree(n), reverse=True):
        d = G.nodes[nid]
        line = (
            f"NODE {sanitize_label(d.get('label', nid))} "
            f"[type={d.get('type', '')} src={d.get('source_file', '')} community={d.get('community', '')}]"
        )
        summary = d.get("summary", "")
        if summary:
            line += f" — {sanitize_label(summary[:120])}"
        lines.append(line)
    for u, v in edges:
        if u in nodes and v in nodes:
            raw = G[u][v]
            d = next(iter(raw.values()), {}) if isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)) else raw
            line = (
                f"EDGE {sanitize_label(G.nodes[u].get('label', u))} "
                f"--{d.get('relation', '')} [{d.get('confidence', '')}]--> "
                f"{sanitize_label(G.nodes[v].get('label', v))}"
            )
            lines.append(line)
    output = "\n".join(lines)
    if len(output) > char_budget:
        output = output[:char_budget] + f"\n... (truncated to ~{token_budget} token budget)"
    return output


def _find_node(G: nx.Graph, label: str) -> list[str]:
    term = _strip_diacritics(label).lower()
    return [
        nid for nid, d in G.nodes(data=True)
        if term in _strip_diacritics(d.get("label", "")).lower() or term == nid.lower()
    ]


def _filter_blank_stdin() -> None:
    import os
    import threading

    r_fd, w_fd = os.pipe()
    saved_fd = os.dup(sys.stdin.fileno())

    def _relay() -> None:
        try:
            with open(saved_fd, "rb") as src, open(w_fd, "wb") as dst:
                for line in src:
                    if line.strip():
                        dst.write(line)
                        dst.flush()
        except Exception:
            pass

    threading.Thread(target=_relay, daemon=True).start()
    os.dup2(r_fd, sys.stdin.fileno())
    os.close(r_fd)
    sys.stdin = open(0, "r", closefd=False)


def serve(graph_path: str = "breachpoint-out/graph.json") -> None:
    """Start the MCP server. Requires pip install mcp."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp import types
    except ImportError as e:
        raise ImportError("mcp not installed. Run: pip install mcp") from e

    G = _load_graph(graph_path)
    communities = _communities_from_graph(G)

    server = Server("breachpoint")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="query_graph",
                description="Search the knowledge graph using BFS or DFS. Returns relevant nodes and edges as text context.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "Natural language question or keyword search"},
                        "mode": {"type": "string", "enum": ["bfs", "dfs"], "default": "bfs"},
                        "depth": {"type": "integer", "default": 3, "description": "Traversal depth (1-6)"},
                        "token_budget": {"type": "integer", "default": 2000},
                    },
                    "required": ["question"],
                },
            ),
            types.Tool(
                name="get_node",
                description="Get full details for a specific node by label or ID.",
                inputSchema={
                    "type": "object",
                    "properties": {"label": {"type": "string"}},
                    "required": ["label"],
                },
            ),
            types.Tool(
                name="get_neighbors",
                description="Get all direct neighbors of a node with edge details.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "relation_filter": {"type": "string", "description": "Optional: filter by relation type"},
                    },
                    "required": ["label"],
                },
            ),
            types.Tool(
                name="get_community",
                description="Get all nodes in a community by community ID.",
                inputSchema={
                    "type": "object",
                    "properties": {"community_id": {"type": "integer"}},
                    "required": ["community_id"],
                },
            ),
            types.Tool(
                name="god_nodes",
                description="Return the most connected nodes — the core concepts of the knowledge graph.",
                inputSchema={"type": "object", "properties": {"top_n": {"type": "integer", "default": 10}}},
            ),
            types.Tool(
                name="graph_stats",
                description="Return summary statistics: node count, edge count, communities, confidence breakdown.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="shortest_path",
                description="Find the shortest path between two concepts in the knowledge graph.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "max_hops": {"type": "integer", "default": 8},
                    },
                    "required": ["source", "target"],
                },
            ),
        ]

    def _tool_query_graph(arguments: dict) -> str:
        question = arguments["question"]
        mode = arguments.get("mode", "bfs")
        depth = min(int(arguments.get("depth", 3)), 6)
        budget = int(arguments.get("token_budget", 2000))
        terms = [t.lower() for t in question.split() if len(t) > 2]
        scored = _score_nodes(G, terms)
        start_nodes = [nid for _, nid in scored[:3]]
        if not start_nodes:
            return "No matching nodes found."
        nodes, edges = _dfs(G, start_nodes, depth) if mode == "dfs" else _bfs(G, start_nodes, depth)
        header = f"Traversal: {mode.upper()} depth={depth} | Start: {[G.nodes[n].get('label', n) for n in start_nodes]} | {len(nodes)} nodes found\n\n"
        return header + _subgraph_to_text(G, nodes, edges, budget)

    def _tool_get_node(arguments: dict) -> str:
        label = arguments["label"].lower()
        matches = [(nid, d) for nid, d in G.nodes(data=True)
                   if label in d.get("label", "").lower() or label == nid.lower()]
        if not matches:
            return f"No node matching '{label}' found."
        nid, d = matches[0]
        return "\n".join([
            f"Node: {d.get('label', nid)}",
            f"  ID:        {nid}",
            f"  Type:      {d.get('type', '')}",
            f"  Summary:   {d.get('summary', '')}",
            f"  Source:    {d.get('source_file', '')}",
            f"  Community: {d.get('community', '')}",
            f"  Degree:    {G.degree(nid)}",
        ])

    def _tool_get_neighbors(arguments: dict) -> str:
        label = arguments["label"].lower()
        rel_filter = arguments.get("relation_filter", "").lower()
        matches = _find_node(G, label)
        if not matches:
            return f"No node matching '{label}' found."
        nid = matches[0]
        lines = [f"Neighbors of {G.nodes[nid].get('label', nid)}:"]
        for neighbor in G.neighbors(nid):
            d = G.edges[nid, neighbor]
            rel = d.get("relation", "")
            if rel_filter and rel_filter not in rel.lower():
                continue
            lines.append(f"  --> {G.nodes[neighbor].get('label', neighbor)} [{rel}] [{d.get('confidence', '')}]")
        return "\n".join(lines)

    def _tool_get_community(arguments: dict) -> str:
        cid = int(arguments["community_id"])
        nodes = communities.get(cid, [])
        if not nodes:
            return f"Community {cid} not found."
        lines = [f"Community {cid} ({len(nodes)} nodes):"]
        for n in nodes:
            d = G.nodes[n]
            lines.append(f"  {d.get('label', n)} [{d.get('source_file', '')}]")
        return "\n".join(lines)

    def _tool_god_nodes(arguments: dict) -> str:
        from .analyze import god_nodes as _god_nodes
        nodes = _god_nodes(G, top_n=int(arguments.get("top_n", 10)))
        lines = ["Hub nodes (most connected):"]
        lines += [f"  {i}. {n['label']} - degree {n['degree']}" for i, n in enumerate(nodes, 1)]
        return "\n".join(lines)

    def _tool_graph_stats(_: dict) -> str:
        confs = [d.get("confidence", "EXTRACTED") for _, _, d in G.edges(data=True)]
        total = len(confs) or 1
        return (
            f"Nodes: {G.number_of_nodes()}\n"
            f"Edges: {G.number_of_edges()}\n"
            f"Communities: {len(communities)}\n"
            f"EXTRACTED: {round(confs.count('EXTRACTED')/total*100)}%\n"
            f"INFERRED: {round(confs.count('INFERRED')/total*100)}%\n"
            f"AMBIGUOUS: {round(confs.count('AMBIGUOUS')/total*100)}%\n"
        )

    def _tool_shortest_path(arguments: dict) -> str:
        src_scored = _score_nodes(G, [t.lower() for t in arguments["source"].split()])
        tgt_scored = _score_nodes(G, [t.lower() for t in arguments["target"].split()])
        if not src_scored:
            return f"No node matching source '{arguments['source']}' found."
        if not tgt_scored:
            return f"No node matching target '{arguments['target']}' found."
        src_nid, tgt_nid = src_scored[0][1], tgt_scored[0][1]
        max_hops = int(arguments.get("max_hops", 8))
        try:
            path_nodes = nx.shortest_path(G, src_nid, tgt_nid)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return f"No path found between '{G.nodes[src_nid].get('label', src_nid)}' and '{G.nodes[tgt_nid].get('label', tgt_nid)}'."
        hops = len(path_nodes) - 1
        if hops > max_hops:
            return f"Path exceeds max_hops={max_hops} ({hops} hops found)."
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
        return f"Shortest path ({hops} hops):\n  " + " ".join(segments)

    _handlers = {
        "query_graph": _tool_query_graph,
        "get_node": _tool_get_node,
        "get_neighbors": _tool_get_neighbors,
        "get_community": _tool_get_community,
        "god_nodes": _tool_god_nodes,
        "graph_stats": _tool_graph_stats,
        "shortest_path": _tool_shortest_path,
    }

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        handler = _handlers.get(name)
        if not handler:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
        try:
            return [types.TextContent(type="text", text=handler(arguments))]
        except Exception as exc:
            return [types.TextContent(type="text", text=f"Error executing {name}: {exc}")]

    import asyncio

    async def main() -> None:
        async with stdio_server() as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    _filter_blank_stdin()
    asyncio.run(main())


if __name__ == "__main__":
    graph_path = sys.argv[1] if len(sys.argv) > 1 else "breachpoint-out/graph.json"
    serve(graph_path)
