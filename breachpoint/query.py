"""Query functions for breachpoint knowledge graph."""
import json
import networkx as nx
from networkx.readwrite import json_graph
from pathlib import Path


def load_graph(graph_path='breachpoint-out/graph.json'):
    """Load graph from JSON."""
    data = json.loads(Path(graph_path).read_text(encoding='utf-8'))
    try:
        return json_graph.node_link_graph(data, edges='links')
    except TypeError:
        return json_graph.node_link_graph(data)


def stage2_retrieve(graph_path, entities, terms):
    """Multi-stage node retrieval."""
    G = load_graph(graph_path)
    results = {'exact': [], 'label': [], 'summary': [], 'edge': []}

    for nid, attrs in G.nodes(data=True):
        label = attrs.get('label', '').lower()
        summary = attrs.get('summary', '').lower()
        nid_lower = nid.lower()

        if any(e.lower() in label or e.lower() in nid_lower for e in entities):
            results['exact'].append(nid)
        elif any(t in label for t in terms):
            results['label'].append(nid)
        elif any(t in summary for t in terms):
            results['summary'].append(nid)

    for u, v, edata in G.edges(data=True):
        rel = edata.get('relation', '').lower()
        ev = edata.get('evidence', '').lower()
        if any(t in rel or t in ev for t in terms):
            results['edge'].append({
                'from': u, 'to': v,
                'relation': edata.get('relation'),
                'evidence': edata.get('evidence'),
                'confidence': edata.get('confidence')
            })

    return results


def stage3_paths(graph_path, node_a, node_b, cutoff=4, max_paths=3):
    """Find paths between two nodes."""
    G = load_graph(graph_path)
    try:
        paths = list(nx.all_simple_paths(G, node_a, node_b, cutoff=cutoff))
        result = []
        for path in paths[:max_paths]:
            chain = []
            for i in range(len(path)-1):
                edata = G.edges[path[i], path[i+1]]
                chain.append(f'{path[i]} --[{edata.get("relation","?")}]--> {path[i+1]}')
            result.append(' | '.join(chain))
        return result
    except Exception as e:
        return [f'无路径: {e}']


def stage4_expand(graph_path, seeds, top_n=20):
    """Community-aware expansion."""
    G = load_graph(graph_path)
    seeds = set(seeds)
    seed_communities = {G.nodes[n].get('community') for n in seeds if G.nodes[n].get('community') is not None}

    scored = []
    for nid, attrs in G.nodes(data=True):
        if nid in seeds:
            scored.append((10, nid))
            continue
        c = attrs.get('community')
        neighbor_score = sum(1 for nb in G.neighbors(nid) if nb in seeds)
        score = (3 if c in seed_communities else 1) + neighbor_score * 2
        if score > 1:
            scored.append((score, nid))

    scored.sort(reverse=True)
    output = []
    top_nodes = {n for _, n in scored[:top_n]}

    for score, nid in scored[:top_n]:
        d = G.nodes[nid]
        src = d.get('source_file', '').split('/')[-1].split('\\')[-1]
        connections = [
            f'{nb} [{G.edges[nid, nb].get("relation","?")}]'
            for nb in G.neighbors(nid)
            if nb in top_nodes
        ][:3]
        output.append({
            'id': nid,
            'label': d.get('label', nid),
            'type': d.get('type','?'),
            'summary': d.get('summary',''),
            'source': src,
            'community': d.get('community'),
            'connections': connections
        })

    return output
