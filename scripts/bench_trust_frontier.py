"""Paired reproducible microbenchmark of real temporary-store propagation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
p.add_argument('--nodes', type=int, default=2000)
p.add_argument('--repeat', type=int, default=5)
p.add_argument('--output', type=Path)
a = p.parse_args()
if a.nodes < 1 or a.repeat < 1:
    p.error('nodes and repeat must be positive')
sys.path.insert(0, str(a.repo.resolve()))
for key in list(os.environ):
    if key.startswith('MDCG_') or key == 'DSH_SESSION_ID':
        os.environ.pop(key)
os.environ.update(MDCG_SUSTAIN='0', MDCG_HOTCACHE='0')
from md_cg.mdcos import MdCGOS
from md_cg import trust

with tempfile.TemporaryDirectory(prefix='bench_trust_frontier_') as root:
    cg = MdCGOS(root)
    try:
        cg.add('root', 'expired premise', verification_state='expired')
        for i in range(a.nodes):
            cg.add('child%06d' % i, 'dependent memory', depends_on=['root'])
        cg.flush()
        timings = []
        for _ in range(a.repeat):
            started = time.perf_counter()
            rep = trust.propagate(cg, apply=False, max_nodes=a.nodes+1)
            timings.append((time.perf_counter()-started)*1000)
            assert rep['reachable'] == a.nodes, 'all dependent memories must remain reachable'
        result = dict(shape='one expired root, N unverified leaf dependencies',
                      nodes=a.nodes+1, edges=a.nodes, apply=False,
                      dataset_sha256=hashlib.sha256(''.join('root->child%06d\n' % i for i in range(a.nodes)).encode()).hexdigest(),
                      timings_ms=timings, median_ms=statistics.median(timings),
                      reachable=rep['reachable'], visited=rep.get('visited'),
                      truncated=rep.get('truncated'))
    finally:
        cg.close()
if a.output:
    a.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
print(json.dumps(result, indent=2))
