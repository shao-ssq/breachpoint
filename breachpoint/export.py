"""Export BreachPoint graph to multiple formats.

Public API:
    to_json(G, communities, path)        — GraphRAG-ready JSON
    to_html(G, communities, path, ...)   — Interactive vis.js (sidebar, search, legend)
    to_svg(G, communities, path, ...)    — Static SVG via matplotlib
    to_graphml(G, communities, path)     — GraphML for Gephi/yEd
    to_cypher(G, path)                   — Neo4j Cypher import script
    to_obsidian(G, communities, dir, ...)— Obsidian vault (one .md per node)
"""
from __future__ import annotations
import html as _html
import json
import math
import re
import re
from collections import Counter
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

COMMUNITY_COLORS = [
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
]

MAX_NODES_FOR_VIZ = 5_000


def _strip_diacritics(text: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _node_community_map(communities: dict[int, list[str]]) -> dict[str, int]:
    return {n: cid for cid, nodes in communities.items() for n in nodes}


# ── JSON ──────────────────────────────────────────────────────────────────────

def to_json(
    G: nx.Graph,
    communities: dict[int, list[str]],
    path: str | Path,
) -> None:
    """Write node-link JSON with community annotations and norm_label for search."""
    node_to_com = _node_community_map(communities)
    for nid in G.nodes():
        G.nodes[nid]["community"] = node_to_com.get(nid, -1)
        G.nodes[nid]["norm_label"] = _strip_diacritics(G.nodes[nid].get("label", "")).lower()
    try:
        data = json_graph.node_link_data(G, edges="links")
    except TypeError:
        data = json_graph.node_link_data(G)
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── HTML ──────────────────────────────────────────────────────────────────────

def _html_styles() -> str:
    return """<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f0f1a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; display: flex; height: 100vh; overflow: hidden; }
  #graph { flex: 1; }
  #sidebar { width: 280px; background: #1a1a2e; border-left: 1px solid #2a2a4e; display: flex; flex-direction: column; overflow: hidden; }
  #search-wrap { padding: 12px; border-bottom: 1px solid #2a2a4e; }
  #search { width: 100%; background: #0f0f1a; border: 1px solid #3a3a5e; color: #e0e0e0; padding: 7px 10px; border-radius: 6px; font-size: 13px; outline: none; }
  #search:focus { border-color: #4E79A7; }
  #search-results { max-height: 140px; overflow-y: auto; padding: 4px 12px; border-bottom: 1px solid #2a2a4e; display: none; }
  .search-item { padding: 4px 6px; cursor: pointer; border-radius: 4px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .search-item:hover { background: #2a2a4e; }
  #info-panel { padding: 14px; border-bottom: 1px solid #2a2a4e; min-height: 140px; }
  #info-panel h3 { font-size: 13px; color: #aaa; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em; }
  #info-content { font-size: 13px; color: #ccc; line-height: 1.6; }
  #info-content .field { margin-bottom: 5px; }
  #info-content .field b { color: #e0e0e0; }
  #info-content .empty { color: #555; font-style: italic; }
  .neighbor-link { display: block; padding: 2px 6px; margin: 2px 0; border-radius: 3px; cursor: pointer; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-left: 3px solid #333; }
  .neighbor-link:hover { background: #2a2a4e; }
  #neighbors-list { max-height: 160px; overflow-y: auto; margin-top: 4px; }
  #legend-wrap { flex: 1; overflow-y: auto; padding: 12px; }
  #legend-wrap h3 { font-size: 13px; color: #aaa; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.05em; }
  .legend-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; cursor: pointer; border-radius: 4px; font-size: 12px; }
  .legend-item:hover { background: #2a2a4e; padding-left: 4px; }
  .legend-item.dimmed { opacity: 0.35; }
  .legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
  .legend-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .legend-count { color: #666; font-size: 11px; }
  #stats { padding: 10px 14px; border-top: 1px solid #2a2a4e; font-size: 11px; color: #555; }
</style>"""


def _html_script(nodes_json: str, edges_json: str, legend_json: str) -> str:
    return f"""<script>
const RAW_NODES = {nodes_json};
const RAW_EDGES = {edges_json};
const LEGEND = {legend_json};

function esc(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}}

const nodesDS = new vis.DataSet(RAW_NODES.map(n => ({{
  id: n.id, label: n.label, color: n.color, size: n.size,
  font: n.font, title: n.title,
  _community: n.community, _community_name: n.community_name,
  _source_file: n.source_file, _type: n.type, _degree: n.degree,
  _summary: n.summary,
}})));

const edgesDS = new vis.DataSet(RAW_EDGES.map((e, i) => ({{
  id: i, from: e.from, to: e.to,
  label: '',
  title: e.title,
  dashes: e.dashes,
  width: e.width,
  color: e.color,
  arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }},
}})));

const container = document.getElementById('graph');
const network = new vis.Network(container, {{ nodes: nodesDS, edges: edgesDS }}, {{
  physics: {{
    enabled: true,
    solver: 'forceAtlas2Based',
    forceAtlas2Based: {{ gravitationalConstant: -60, centralGravity: 0.005, springLength: 120, springConstant: 0.08, damping: 0.4, avoidOverlap: 0.8 }},
    stabilization: {{ iterations: 200, fit: true }},
  }},
  interaction: {{ hover: true, tooltipDelay: 100, hideEdgesOnDrag: true }},
  nodes: {{ shape: 'dot', borderWidth: 1.5 }},
  edges: {{ smooth: {{ type: 'continuous', roundness: 0.2 }}, selectionWidth: 3 }},
}});

network.once('stabilizationIterationsDone', () => {{
  network.setOptions({{ physics: {{ enabled: false }} }});
}});

function showInfo(nodeId) {{
  const n = nodesDS.get(nodeId);
  if (!n) return;
  const neighborIds = network.getConnectedNodes(nodeId);
  const neighborItems = neighborIds.map(nid => {{
    const nb = nodesDS.get(nid);
    const color = nb ? nb.color.background : '#555';
    return `<span class="neighbor-link" style="border-left-color:${{esc(color)}}" onclick="focusNode(${{JSON.stringify(nid)}})">${{esc(nb ? nb.label : nid)}}</span>`;
  }}).join('');
  document.getElementById('info-content').innerHTML = `
    <div class="field"><b>${{esc(n.label)}}</b></div>
    <div class="field">Type: ${{esc(n._type || '—')}}</div>
    <div class="field">Community: ${{esc(n._community_name)}}</div>
    <div class="field">Source: ${{esc(n._source_file || '—')}}</div>
    <div class="field">Degree: ${{n._degree}}</div>
    ${{n._summary ? `<div class="field" style="color:#aaa;font-size:11px;margin-top:4px">${{esc(n._summary.slice(0,120))}}</div>` : ''}}
    ${{neighborIds.length ? `<div class="field" style="margin-top:8px;color:#aaa;font-size:11px">Neighbors (${{neighborIds.length}})</div><div id="neighbors-list">${{neighborItems}}</div>` : ''}}
  `;
}}

function focusNode(nodeId) {{
  network.focus(nodeId, {{ scale: 1.4, animation: true }});
  network.selectNodes([nodeId]);
  showInfo(nodeId);
}}

let hoveredNodeId = null;
network.on('hoverNode', params => {{ hoveredNodeId = params.node; container.style.cursor = 'pointer'; }});
network.on('blurNode', () => {{ hoveredNodeId = null; container.style.cursor = 'default'; }});
container.addEventListener('click', () => {{
  if (hoveredNodeId !== null) {{ showInfo(hoveredNodeId); network.selectNodes([hoveredNodeId]); }}
}});
network.on('click', params => {{
  if (params.nodes.length > 0) {{ showInfo(params.nodes[0]); }}
  else if (hoveredNodeId === null) {{
    document.getElementById('info-content').innerHTML = '<span class="empty">Click a node to inspect it</span>';
  }}
}});

const searchInput = document.getElementById('search');
const searchResults = document.getElementById('search-results');
searchInput.addEventListener('input', () => {{
  const q = searchInput.value.toLowerCase().trim();
  searchResults.innerHTML = '';
  if (!q) {{ searchResults.style.display = 'none'; return; }}
  const matches = RAW_NODES.filter(n => n.label.toLowerCase().includes(q)).slice(0, 20);
  if (!matches.length) {{ searchResults.style.display = 'none'; return; }}
  searchResults.style.display = 'block';
  matches.forEach(n => {{
    const el = document.createElement('div');
    el.className = 'search-item';
    el.textContent = n.label;
    el.style.borderLeft = `3px solid ${{n.color.background}}`;
    el.style.paddingLeft = '8px';
    el.onclick = () => {{
      network.focus(n.id, {{ scale: 1.5, animation: true }});
      network.selectNodes([n.id]);
      showInfo(n.id);
      searchResults.style.display = 'none';
      searchInput.value = '';
    }};
    searchResults.appendChild(el);
  }});
}});
document.addEventListener('click', e => {{
  if (!searchResults.contains(e.target) && e.target !== searchInput)
    searchResults.style.display = 'none';
}});

const hiddenCommunities = new Set();
const legendEl = document.getElementById('legend');
LEGEND.forEach(c => {{
  const item = document.createElement('div');
  item.className = 'legend-item';
  item.innerHTML = `<div class="legend-dot" style="background:${{c.color}}"></div>
    <span class="legend-label">${{c.label}}</span>
    <span class="legend-count">${{c.count}}</span>`;
  item.onclick = () => {{
    if (hiddenCommunities.has(c.cid)) {{
      hiddenCommunities.delete(c.cid);
      item.classList.remove('dimmed');
    }} else {{
      hiddenCommunities.add(c.cid);
      item.classList.add('dimmed');
    }}
    const updates = RAW_NODES
      .filter(n => n.community === c.cid)
      .map(n => ({{ id: n.id, hidden: hiddenCommunities.has(c.cid) }}));
    nodesDS.update(updates);
  }};
  legendEl.appendChild(item);
}});
</script>"""


def to_html(
    G: nx.Graph,
    communities: dict[int, list[str]],
    path: str | Path,
    community_labels: dict[int, str] | None = None,
) -> None:
    """Generate an interactive vis.js HTML visualization with sidebar, search, and community filter."""
    if G.number_of_nodes() > MAX_NODES_FOR_VIZ:
        raise ValueError(
            f"Graph has {G.number_of_nodes()} nodes — too large for HTML viz. "
            f"Use to_obsidian() or reduce input size."
        )

    node_to_com = _node_community_map(communities)
    degree = dict(G.degree())
    max_deg = max(degree.values(), default=1) or 1

    vis_nodes = []
    for node_id, data in G.nodes(data=True):
        cid = node_to_com.get(node_id, 0)
        color = COMMUNITY_COLORS[cid % len(COMMUNITY_COLORS)]
        label = sanitize_label(data.get("label", node_id))
        deg = degree.get(node_id, 1)
        size = 10 + 30 * (deg / max_deg)
        font_size = 12 if deg >= max_deg * 0.15 else 0
        vis_nodes.append({
            "id": node_id,
            "label": label,
            "color": {"background": color, "border": color, "highlight": {"background": "#ffffff", "border": color}},
            "size": round(size, 1),
            "font": {"size": font_size, "color": "#ffffff"},
            "title": _html.escape(label),
            "community": cid,
            "community_name": sanitize_label((community_labels or {}).get(cid, f"Community {cid}")),
            "source_file": sanitize_label(data.get("source_file", "") or ""),
            "type": data.get("type", ""),
            "summary": sanitize_label(data.get("summary", "") or ""),
            "degree": deg,
        })

    vis_edges = []
    for u, v, data in G.edges(data=True):
        confidence = data.get("confidence", "EXTRACTED")
        relation = data.get("relation", "")
        vis_edges.append({
            "from": u,
            "to": v,
            "title": _html.escape(f"{relation} [{confidence}]"),
            "dashes": confidence != "EXTRACTED",
            "width": 2 if confidence == "EXTRACTED" else 1,
            "color": {"opacity": 0.7 if confidence == "EXTRACTED" else 0.35},
        })

    legend_data = []
    for cid in sorted((community_labels or {}).keys()):
        color = COMMUNITY_COLORS[cid % len(COMMUNITY_COLORS)]
        lbl = _html.escape(sanitize_label((community_labels or {}).get(cid, f"Community {cid}")))
        n = len(communities.get(cid, []))
        legend_data.append({"cid": cid, "color": color, "label": lbl, "count": n})

    def _js_safe(obj) -> str:
        return json.dumps(obj).replace("</", "<\\/")

    nodes_json = _js_safe(vis_nodes)
    edges_json = _js_safe(vis_edges)
    legend_json = _js_safe(legend_data)
    title = _html.escape(sanitize_label(str(path)))
    stats = f"{G.number_of_nodes()} nodes &middot; {G.number_of_edges()} edges &middot; {len(communities)} communities"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>BreachPoint — {title}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
{_html_styles()}
</head>
<body>
<div id="graph"></div>
<div id="sidebar">
  <div id="search-wrap">
    <input id="search" type="text" placeholder="Search nodes..." autocomplete="off">
    <div id="search-results"></div>
  </div>
  <div id="info-panel">
    <h3>Node Info</h3>
    <div id="info-content"><span class="empty">Click a node to inspect it</span></div>
  </div>
  <div id="legend-wrap">
    <h3>Communities</h3>
    <div id="legend"></div>
  </div>
  <div id="stats">{stats}</div>
</div>
{_html_script(nodes_json, edges_json, legend_json)}
</body>
</html>"""

    Path(path).write_text(html, encoding="utf-8")


# ── SVG ───────────────────────────────────────────────────────────────────────

def to_svg(
    G: nx.Graph,
    communities: dict[int, list[str]],
    path: str | Path,
    community_labels: dict[int, str] | None = None,
    figsize: tuple[int, int] = (20, 14),
) -> None:
    """Export graph as SVG via matplotlib spring layout. Embeddable in markdown/Notion/GitHub."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError as e:
        raise ImportError("matplotlib not installed. Run: pip install matplotlib") from e

    node_to_com = _node_community_map(communities)

    fig, ax = plt.subplots(figsize=figsize, facecolor="#1a1a2e")
    ax.set_facecolor("#1a1a2e")
    ax.axis("off")

    pos = nx.spring_layout(G, seed=42, k=2.0 / (G.number_of_nodes() ** 0.5 + 1))
    degree = dict(G.degree())
    max_deg = max(degree.values(), default=1) or 1

    node_colors = [COMMUNITY_COLORS[node_to_com.get(n, 0) % len(COMMUNITY_COLORS)] for n in G.nodes()]
    node_sizes = [300 + 1200 * (degree.get(n, 1) / max_deg) for n in G.nodes()]

    for u, v, data in G.edges(data=True):
        conf = data.get("confidence", "EXTRACTED")
        style = "solid" if conf == "EXTRACTED" else "dashed"
        alpha = 0.6 if conf == "EXTRACTED" else 0.3
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        ax.plot([x0, x1], [y0, y1], color="#aaaaaa", linewidth=0.8, linestyle=style, alpha=alpha, zorder=1)

    nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_colors, node_size=node_sizes, alpha=0.9)
    nx.draw_networkx_labels(G, pos, ax=ax,
                            labels={n: G.nodes[n].get("label", n) for n in G.nodes()},
                            font_size=7, font_color="white")

    if community_labels:
        patches = [
            mpatches.Patch(
                color=COMMUNITY_COLORS[cid % len(COMMUNITY_COLORS)],
                label=f"{label} ({len(communities.get(cid, []))})",
            )
            for cid, label in sorted(community_labels.items())
        ]
        ax.legend(handles=patches, loc="upper left", framealpha=0.7,
                  facecolor="#2a2a4e", labelcolor="white", fontsize=8)

    plt.tight_layout()
    plt.savefig(str(path), format="svg", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


# ── GraphML ───────────────────────────────────────────────────────────────────

def to_graphml(
    G: nx.Graph,
    communities: dict[int, list[str]],
    path: str | Path,
) -> None:
    """Export graph as GraphML (Gephi/yEd compatible). Community IDs preserved as node attribute."""
    H = G.copy()
    node_to_com = _node_community_map(communities)
    for node_id in H.nodes():
        H.nodes[node_id]["community"] = node_to_com.get(node_id, -1)
    nx.write_graphml(H, str(path))


# ── Neo4j Cypher ──────────────────────────────────────────────────────────────

def _cypher_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def to_cypher(G: nx.Graph, path: str | Path) -> None:
    """Export graph as Neo4j Cypher import script. Uses MERGE — safe to re-run."""
    lines = ["// Neo4j Cypher import — generated by BreachPoint", ""]
    for node_id, data in G.nodes(data=True):
        label = _cypher_escape(data.get("label", node_id))
        node_id_esc = _cypher_escape(node_id)
        raw_type = data.get("type", "concept").capitalize()
        ntype = re.sub(r"[^A-Za-z0-9_]", "", raw_type) or "Concept"
        if not ntype[0].isalpha():
            ntype = "Concept"
        lines.append(f"MERGE (n:{ntype} {{id: '{node_id_esc}', label: '{label}'}});")
    lines.append("")
    for u, v, data in G.edges(data=True):
        rel = re.sub(r"[^A-Za-z0-9_]", "_", data.get("relation", "RELATES_TO").upper()) or "RELATES_TO"
        conf = _cypher_escape(data.get("confidence", "EXTRACTED"))
        u_esc = _cypher_escape(u)
        v_esc = _cypher_escape(v)
        lines.append(
            f"MATCH (a {{id: '{u_esc}'}}), (b {{id: '{v_esc}'}}) "
            f"MERGE (a)-[:{rel} {{confidence: '{conf}'}}]->(b);"
        )
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# ── Obsidian vault ────────────────────────────────────────────────────────────

def to_obsidian(
    G: nx.Graph,
    communities: dict[int, list[str]],
    output_dir: str | Path,
    community_labels: dict[int, str] | None = None,
    cohesion: dict[int, float] | None = None,
) -> int:
    """Export graph as an Obsidian vault — one .md file per node with [[wikilinks]].

    Returns the number of node notes + community notes written.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    node_to_com = _node_community_map(communities)

    def safe_name(label: str) -> str:
        cleaned = re.sub(r'[\\/*?:"<>|#^[\]]', "", label.replace("\r\n", " ").replace("\n", " ")).strip()
        cleaned = re.sub(r"\.(md|mdx|markdown)$", "", cleaned, flags=re.IGNORECASE)
        return cleaned or "unnamed"

    node_filename: dict[str, str] = {}
    seen_names: dict[str, int] = {}
    for node_id, data in G.nodes(data=True):
        base = safe_name(data.get("label", node_id))
        if base in seen_names:
            seen_names[base] += 1
            node_filename[node_id] = f"{base}_{seen_names[base]}"
        else:
            seen_names[base] = 0
            node_filename[node_id] = base

    def _dominant_confidence(node_id: str) -> str:
        confs = [edata.get("confidence", "EXTRACTED") for _, _, edata in G.edges(node_id, data=True)]
        return Counter(confs).most_common(1)[0][0] if confs else "EXTRACTED"

    _TYPE_TAG = {"concept": "breachpoint/concept", "entity": "breachpoint/entity",
                 "event": "breachpoint/event", "person": "breachpoint/person",
                 "place": "breachpoint/place", "topic": "breachpoint/topic"}

    for node_id, data in G.nodes(data=True):
        label = data.get("label", node_id)
        cid = node_to_com.get(node_id)
        community_name = (
            community_labels.get(cid, f"Community {cid}")
            if community_labels and cid is not None else f"Community {cid}"
        )
        ntype = data.get("type", "concept")
        type_tag = _TYPE_TAG.get(ntype, f"breachpoint/{ntype}")
        dom_conf = _dominant_confidence(node_id)
        comm_tag = f"community/{community_name.replace(' ', '_')}"
        node_tags = [type_tag, f"breachpoint/{dom_conf}", comm_tag]

        lines: list[str] = [
            "---",
            f'source_file: "{data.get("source_file", "")}"',
            f'type: "{ntype}"',
            f'community: "{community_name}"',
            "tags:",
        ] + [f"  - {t}" for t in node_tags] + ["---", "", f"# {label}", ""]

        if data.get("summary"):
            lines += [data["summary"], ""]

        neighbors = list(G.neighbors(node_id))
        if neighbors:
            lines.append("## Connections")
            for neighbor in sorted(neighbors, key=lambda n: G.nodes[n].get("label", n)):
                edge_data = G.edges[node_id, neighbor]
                neighbor_label = node_filename[neighbor]
                relation = edge_data.get("relation", "")
                confidence = edge_data.get("confidence", "EXTRACTED")
                lines.append(f"- [[{neighbor_label}]] — `{relation}` [{confidence}]")
            lines.append("")

        lines.append(" ".join(f"#{t}" for t in node_tags))
        (out / (node_filename[node_id] + ".md")).write_text("\n".join(lines), encoding="utf-8")

    # Community overview notes
    inter: dict[int, dict[int, int]] = {}
    for u, v in G.edges():
        cu, cv = node_to_com.get(u), node_to_com.get(v)
        if cu is not None and cv is not None and cu != cv:
            inter.setdefault(cu, {}).setdefault(cv, 0)
            inter.setdefault(cv, {}).setdefault(cu, 0)
            inter[cu][cv] += 1
            inter[cv][cu] += 1

    community_notes = 0
    for cid, members in communities.items():
        community_name = (
            community_labels.get(cid, f"Community {cid}")
            if community_labels else f"Community {cid}"
        )
        coh_value = (cohesion or {}).get(cid)

        lines = [
            "---",
            "type: community",
            *([ f"cohesion: {coh_value:.2f}" ] if coh_value is not None else []),
            f"members: {len(members)}",
            "---",
            "",
            f"# {community_name}",
            "",
            *([ f"**Cohesion:** {coh_value:.2f}" ] if coh_value is not None else []),
            f"**Members:** {len(members)} nodes",
            "",
            "## Members",
        ]
        for node_id in sorted(members, key=lambda n: G.nodes[n].get("label", n)):
            node_label = node_filename[node_id]
            src = G.nodes[node_id].get("source_file", "")
            entry = f"- [[{node_label}]]"
            if src:
                entry += f" — `{src.split('/')[-1].split(chr(92))[-1]}`"
            lines.append(entry)
        lines.append("")

        cross = inter.get(cid, {})
        if cross:
            lines.append("## Connections to Other Communities")
            for other_cid, count in sorted(cross.items(), key=lambda x: -x[1]):
                other_name = (
                    community_labels.get(other_cid, f"Community {other_cid}")
                    if community_labels else f"Community {other_cid}"
                )
                lines.append(f"- {count} edge{'s' if count != 1 else ''} to [[_COMMUNITY_{safe_name(other_name)}]]")
            lines.append("")

        fname = f"_COMMUNITY_{safe_name(community_name)}.md"
        (out / fname).write_text("\n".join(lines), encoding="utf-8")
        community_notes += 1

    # .obsidian/graph.json for community colors
    obsidian_dir = out / ".obsidian"
    obsidian_dir.mkdir(exist_ok=True)
    graph_config = {
        "colorGroups": [
            {
                "query": f"tag:#community/{label.replace(' ', '_')}",
                "color": {"a": 1, "rgb": int(COMMUNITY_COLORS[cid % len(COMMUNITY_COLORS)].lstrip("#"), 16)},
            }
            for cid, label in sorted((community_labels or {}).items())
        ]
    }
    (obsidian_dir / "graph.json").write_text(json.dumps(graph_config, indent=2), encoding="utf-8")

    return G.number_of_nodes() + community_notes
