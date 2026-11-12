"""STG overlap correctness/cost microbenchmark; no production store is opened."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
p.add_argument('--nodes', type=int, default=50000)
p.add_argument('--repeat', type=int, default=5)
p.add_argument('--output', type=Path)
a = p.parse_args()
if a.nodes < 100 or a.repeat < 1:
    p.error('nodes >= 100 and repeat >= 1 required')
sys.path.insert(0, str(a.repo.resolve()))
from md_cg import stgidx, stg

nodes = {f'n{i:07}': {'time_window': [float(i), float(i+1000 if i % 20 == 0 else i)]}
         for i in range(a.nodes)}
windows = [(i, i+10) for i in range(50, a.nodes-10, max(1, a.nodes//100))]
expected = [sum(stg.time_relation(tuple(e['time_window']), w)
                in ('during', 'contains', 'overlaps', 'equals') for e in nodes.values()) for w in windows]
builds, queries, correct = [], [], []
for _ in range(a.repeat):
    start = time.perf_counter()
    ix = stgidx.build({'nodes': nodes})
    builds.append((time.perf_counter()-start)*1000)
    start = time.perf_counter()
    counts = []
    for lo, hi in windows:
        ids, _ = ix.subset(time_range=(lo, hi))
        counts.append(sum(stg.time_relation(tuple(nodes[nid]['time_window']), (lo, hi))
                          in ('during', 'contains', 'overlaps', 'equals') for nid in ids))
    queries.append((time.perf_counter()-start)*1000)
    correct.append(sum(x == y for x, y in zip(counts, expected)))
result = dict(nodes=a.nodes, interval_fraction=0.05, windows=len(windows),
              dataset_sha256=hashlib.sha256(json.dumps(nodes, sort_keys=True).encode()).hexdigest(),
              correct_windows=correct, expected_total_hits=sum(expected), actual_total_hits=sum(counts),
              build_ms=builds, query_ms=queries, median_build_ms=statistics.median(builds),
              median_query_ms=statistics.median(queries),
              scope='in-memory structure and exact overlap post-filter, not end-to-end recall')
if a.output:
    a.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
print(json.dumps(result, indent=2))
