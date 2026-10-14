"""Frozen in-memory time-index workload; both revisions run this same file.

No model/network/production data. A sorted-pair oracle checks every query and
the final partition; timings are observations, never pass/fail thresholds.
"""
import argparse
import bisect
import hashlib
import importlib
import json
from pathlib import Path
import random
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--sizes', nargs='+', type=int, default=[10000, 40000, 160000])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    sys.path.insert(0, str(repo))
    stgidx = importlib.import_module('md_cg.stgidx')
    records = []
    for n in args.sizes:
        order = list(range(n))
        random.Random(1337).shuffle(order)
        nodes = {f'n{i:08}': {'temporal': float(i + 1), 'session': 's', 'layer': 'knowledge'}
                 for i in order}
        began = time.perf_counter()
        index = stgidx.build({'nodes': nodes})
        built = time.perf_counter() - began
        assert not index.broken and len(index.by_time) == n
        oracle = sorted((entry['temporal'], nid) for nid, entry in nodes.items())
        windows = [(float(i), float(i + 31)) for i in random.Random(47).sample(range(n - 32), 120)]
        began = time.perf_counter()
        actual = [index.range_ids(lo, hi) for lo, hi in windows]
        queried = time.perf_counter() - began
        expected = []
        for lo, hi in windows:
            start = bisect.bisect_left(oracle, (lo,))
            stop = bisect.bisect_left(oracle, (hi + 1,))
            expected.append([nid for t, nid in oracle[start:stop]])
        assert actual == expected, 'inclusive range output must equal independent sorted oracle'
        digest = hashlib.sha256(json.dumps(actual, separators=(',', ':')).encode()).hexdigest()
        began = time.perf_counter()
        for _, nid in oracle:
            index.remove(nid)
            nodes.pop(nid)
        removed = time.perf_counter() - began
        assert not index.broken and list(index.by_time) == [] and stgidx.verify(index, nodes) == []
        records.append({'nodes': n, 'timed_before': n, 'build_ms': built * 1000,
                        'query_120_ms': queried * 1000, 'delete_ms': removed * 1000,
                        'query_sha256': digest, 'remaining': len(index.by_time), 'oracle_equal': True})
    report = {'python': sys.version, 'repo': str(repo), 'seed': 1337,
              'source_sha256': hashlib.sha256(Path(stgidx.__file__).read_bytes()).hexdigest(),
              'benchmark_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'results': records}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
