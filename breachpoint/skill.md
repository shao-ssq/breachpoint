---
name: breachpoint
description: knowledge document graph — incremental LLM-driven relationship discovery across documents
trigger: /breachpoint
---

# /breachpoint

Turn any folder of documents into a navigable knowledge graph. Every document gets analysed by Claude to extract concept nodes; new documents are then compared against the entire existing graph to discover cross-document relationships — with unlimited LLM calls per document until all connections are found.

## Usage

```
/breachpoint                        # full pipeline on current directory
/breachpoint <path>                 # full pipeline on specific path
/breachpoint <path> --update        # incremental — process only new/changed docs
/breachpoint query "<question>"     # search the graph by keyword
/breachpoint explain "<concept>"    # describe a node and its connections
```

## What You Must Do When Invoked

If no path was given, use `.` (current directory). Do not ask the user for a path.

Follow these steps in order. Do not skip steps.

### Step 1 — Ensure breachpoint is installed

```bash
BREACHPOINT_BIN=$(which breachpoint 2>/dev/null)
if [ -n "$BREACHPOINT_BIN" ]; then
    PYTHON=$(head -1 "$BREACHPOINT_BIN" | tr -d '#!')
    case "$PYTHON" in
        *[!a-zA-Z0-9/_.-]*) PYTHON="python3" ;;
    esac
else
    PYTHON="python3"
fi
"$PYTHON" -c "import breachpoint" 2>/dev/null || "$PYTHON" -m pip install breachpoint -q 2>/dev/null || "$PYTHON" -m pip install breachpoint -q --break-system-packages 2>&1 | tail -3
mkdir -p breachpoint-out
"$PYTHON" -c "import sys; open('breachpoint-out/.bp_python', 'w').write(sys.executable)"
```

If the import succeeds, print nothing and move straight to Step 2.

**In every subsequent bash block, replace `python3` with `$(cat breachpoint-out/.bp_python)` to use the correct interpreter.**

### Step 2 — Detect documents

```bash
$(cat breachpoint-out/.bp_python) -c "
import json
from breachpoint.detect import detect
from pathlib import Path
result = detect(Path('INPUT_PATH'))
print(json.dumps(result))
" > breachpoint-out/.bp_detect.json
```

Replace INPUT_PATH with the actual path. Read the JSON silently and present a clean summary:

```
Documents: X files · ~Y words
  docs:   N (.md .txt .rst …)
  pdfs:   N (.pdf)
  office: N (.docx)
  web:    N (.html)
```

Omit categories with 0 files. Stop if `total_files == 0`.

If `total_words` > 500,000 OR `total_files` > 150: show the top 5 subdirectories by file count and ask which subfolder to run on. Wait for the user's answer before proceeding.

Otherwise: proceed directly to Step 3.

### Step 3 — Extract concepts and relationships (parallel subagents)

**MANDATORY: You MUST use the Agent tool here. Running `python3 -m breachpoint process` is FORBIDDEN — it spawns a subprocess that calls the Anthropic SDK directly and will be blocked by the proxy. You must extract documents via Agent subagents which run inside the current Claude Code session.**

Before dispatching subagents, print a timing estimate:
- Load `total_files` from `breachpoint-out/.bp_detect.json`
- Estimate agents needed: `ceil(uncached_files / 15)`
- Print: `"Extracting: ~N files → X agents"`

#### Step 3.0 — Check extraction cache

```bash
$(cat breachpoint-out/.bp_python) -c "
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

If all files are cached, skip to Step 4 directly.

#### Step 3.1 — Split into chunks of 10-15 files

Load `breachpoint-out/.bp_uncached.json`. Split into chunks of 10-15 files. Group files from the same directory together so related documents land in the same chunk.

#### Step 3.2 — Dispatch ALL subagents in a single message

Call the Agent tool multiple times IN THE SAME RESPONSE — one call per chunk. This is the only way they run in parallel. Always use `subagent_type="general-purpose"`.

Concrete example for 3 chunks:
```
[Agent tool call 1: files 1-15, subagent_type="general-purpose"]
[Agent tool call 2: files 16-30, subagent_type="general-purpose"]
[Agent tool call 3: files 31-45, subagent_type="general-purpose"]
```
All three in one message. Not three separate messages.

Each subagent receives this exact prompt (substitute FILE_LIST, CHUNK_NUM, TOTAL_CHUNKS, CACHE_DIR):

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

For each file in FILE_LIST, include the hash from `.bp_uncached.json` so the subagent can write individual cache files.

#### Step 3.3 — Collect, cache, and merge

Wait for all subagents. For each chunk:
- Check that `breachpoint-out/.bp_chunk_NN.json` exists on disk
- If missing, warn: "chunk N missing — subagent may have been read-only. Re-run with general-purpose agent."
- If more than half the chunks failed, stop and tell the user to re-run

Merge cached + new results:

```bash
$(cat breachpoint-out/.bp_python) -c "
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

Clean up: `rm -f breachpoint-out/.bp_cached.json breachpoint-out/.bp_uncached.json breachpoint-out/.bp_chunk_*.json`

### Step 4 — Cross-document relationship discovery

This is breachpoint's core differentiator: after per-document extraction, find relationships ACROSS documents.

Read `breachpoint-out/.bp_extract.json`. Group nodes by `source_file`. For each document, identify its nodes, then look at nodes from OTHER documents and find connections.

**For corpora ≤ 20 files**: do this yourself inline — read the node list and write cross-document edges directly into `.bp_extract.json`.

**For corpora > 20 files**: dispatch one subagent per source document in a single message:

Subagent prompt:
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

After all subagents complete, merge cross-document edges into `.bp_extract.json`:

```bash
$(cat breachpoint-out/.bp_python) -c "
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

### Step 5 — Build graph, cluster, analyze, generate outputs

```bash
$(cat breachpoint-out/.bp_python) -c "
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
gods = god_nodes(G, top_n=10)
labels = {cid: f'Community {cid}' for cid in communities}
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

Replace INPUT_PATH with the actual path. If this fails because the package is not installed, build the outputs manually:
- Write `breachpoint-out/graph.json` as NetworkX node-link format
- Write `breachpoint-out/graph.html` using vis.js with the node/edge data inlined as JSON in a `<script>` tag
- Write `breachpoint-out/GRAPH_REPORT.md` summarizing communities and hub nodes

### Step 6 — Label communities

Read `breachpoint-out/.bp_analysis.json`. For each community key, look at its node labels and write a 2-5 word plain-language name (e.g. "Attention Mechanism", "Data Pipeline", "Security Protocols").

Then regenerate report and save labels:

```bash
$(cat breachpoint-out/.bp_python) -c "
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

Replace `LABELS_DICT` with the actual dict you constructed (e.g. `{0: "Attention Mechanism", 1: "Data Pipeline"}`).
Replace INPUT_PATH with the actual path.

### Step 7 — Clean up and report

```bash
rm -f breachpoint-out/.bp_detect.json breachpoint-out/.bp_extract.json
rm -f breachpoint-out/.bp_analysis.json breachpoint-out/.bp_labels.json
```

Tell the user:
```
Knowledge graph built. Outputs in PATH/breachpoint-out/

  graph.html       — interactive graph, open in browser
  GRAPH_REPORT.md  — community structure and surprising connections
  graph.json       — raw graph data
```

Replace PATH with the actual absolute path.

Then paste these sections from GRAPH_REPORT.md directly into chat:
- Hub Nodes (top 5)
- Surprising Cross-document Connections
- Suggested Questions

Do NOT paste the full report — just those three sections.

Then pick the single most interesting suggested question and ask:

> "The most interesting question this graph can answer: **[question]**. Want me to trace it?"

---

## For --update (incremental)

Check `breachpoint-out/graph.json` for a `processed_files` map. Re-detect the corpus, find files whose SHA-256 hash differs from the stored value, then re-run Steps 3–7 on changed/new files only and merge with the existing graph.

---

## For query

Load `breachpoint-out/graph.json` with Python. Do NOT spawn a subprocess that calls the API.

```bash
$(cat breachpoint-out/.bp_python) -c "
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
    print(f'  [{d.get(\"type\",\"?\")}] {d.get(\"label\", nid)}')
    if d.get('summary'): print(f'    {d[\"summary\"]}')
    if d.get('source_file'): print(f'    Source: {d[\"source_file\"].split(\"/\")[-1]}')
    print()
" 2>&1
```

Then answer the question using the graph output. Quote `source_file` when citing a specific fact.

---

## For explain

Load the graph, find the node matching the concept, print its connections, then write a 3-5 sentence explanation of what it is, what it connects to, and why those connections are significant.

---

## Node Schema

```json
{
  "id": "attention_mechanism",
  "label": "Attention Mechanism",
  "type": "concept",
  "summary": "Mechanism allowing models to weigh importance of different input positions.",
  "source_file": "relative/path/to/file.pdf"
}
```

## Edge Schema

```json
{
  "source": "attention_mechanism",
  "target": "transformer_architecture",
  "relation": "is core component of",
  "confidence": "EXTRACTED",
  "evidence": "The paper explicitly states attention is the main building block."
}
```

Confidence levels:
- `EXTRACTED` — stated explicitly in the document(s)
- `INFERRED` — clearly implied by context
- `AMBIGUOUS` — possible but uncertain

## Honesty Rules

- Never invent an edge. If unsure, use AMBIGUOUS.
- Never skip the corpus size warning.
- Always show token cost in the final report.
- Never run `python3 -m breachpoint process` — it will be blocked by the proxy.
