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
    results = {'exact': [], 'label': [], 'comment': [], 'edge': []}
    entities_lower = [e.lower() for e in entities]
    terms_lower = [t.lower() for t in terms]

    for nid, attrs in G.nodes(data=True):
        label = attrs.get('label', '').lower()
        comment = attrs.get('comment', '').lower()
        nid_lower = nid.lower()

        if any(e == label or e == nid_lower for e in entities_lower):
            results['exact'].append(nid)
        else:
            if any(t in label for t in terms_lower):
                results['label'].append(nid)
            if any(t in comment for t in terms_lower):
                results['comment'].append(nid)

    for u, v, edata in G.edges(data=True):
        rel = edata.get('relation', '').lower()
        ev = edata.get('evidence', '').lower()
        if any(t in rel or t in ev for t in terms_lower):
            results['edge'].append({
                'from': u, 'to': v,
                'relation': edata.get('relation'),
                'evidence': edata.get('evidence'),
                'confidence': edata.get('confidence')
            })

    return results


def stage3_coarse(graph_path, seeds, hops=3):
    """Coarse expansion: BFS up to `hops` from seeds, return all reachable nodes with edges."""
    G = load_graph(graph_path)
    seeds = set(seeds)
    visited = set()
    frontier = seeds & set(G.nodes)
    for _ in range(hops):
        next_frontier = set()
        for n in frontier:
            for nb in G.neighbors(n):
                if nb not in visited and nb not in frontier:
                    next_frontier.add(nb)
        visited |= frontier
        frontier = next_frontier
    visited |= frontier

    nodes = []
    for nid in visited:
        d = G.nodes[nid]
        nodes.append({
            'id': nid,
            'label': d.get('label', nid),
            'type': d.get('type', '?'),
            'comment': d.get('comment', ''),
            'community': d.get('community'),
            'is_seed': nid in seeds,
        })

    edges = []
    for u, v, edata in G.edges(data=True):
        if u in visited and v in visited:
            edges.append({'from': u, 'to': v, 'relation': edata.get('relation'), 'confidence': edata.get('confidence')})

    return {'nodes': nodes, 'links': edges}


def stage5_refine(graph_path, targets, hops=5, top_n=30):
    """Fine-grained expansion: deep neighborhood + community-aware scoring."""
    G = load_graph(graph_path)
    targets = set(targets) & set(G.nodes)
    target_communities = {G.nodes[n].get('community') for n in targets if G.nodes[n].get('community') is not None}

    # BFS up to hops
    visited = set()
    frontier = set(targets)
    for _ in range(hops):
        next_f = set()
        for n in frontier:
            for nb in G.neighbors(n):
                if nb not in visited and nb not in frontier:
                    next_f.add(nb)
        visited |= frontier
        frontier = next_f
    visited |= frontier

    scored = []
    for nid in visited:
        d = G.nodes[nid]
        c = d.get('community')
        nb_score = sum(1 for nb in G.neighbors(nid) if nb in targets)
        score = (10 if nid in targets else 0) + (3 if c in target_communities else 1) + nb_score * 2
        scored.append((score, nid))

    scored.sort(reverse=True)
    top_nodes = {n for _, n in scored[:top_n]}

    output = []
    for score, nid in scored[:top_n]:
        d = G.nodes[nid]
        src = d.get('source_file', '').split('/')[-1].split('\\')[-1]
        connections = []
        for nb in G.neighbors(nid):
            if nb in top_nodes:
                edata = G.edges[nid, nb]
                connections.append(f'→{nb} [{edata.get("relation","?")}]')
        output.append({
            'id': nid,
            'label': d.get('label', nid),
            'type': d.get('type', '?'),
            'comment': d.get('comment', ''),
            'source': src,
            'community': d.get('community'),
            'score': score,
            'connections': connections[:5],
        })

    return output
