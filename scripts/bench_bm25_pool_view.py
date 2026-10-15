"""Paired candidate-container microbenchmark; synthetic metadata, not corpus retrieval."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc
from types import SimpleNamespace

p=argparse.ArgumentParser();p.add_argument('--repo',required=True,type=Path)
p.add_argument('--sizes',type=int,nargs='+',default=[10000,100000,1000000]);p.add_argument('--output',type=Path)
a=p.parse_args();sys.path.insert(0,str(a.repo.resolve()))
from md_cg import bm25

readings=[]
for n in a.sizes:
    # Legitimate distinct candidate records, no repeated dummy pointer pool.
    nodes={str(i):{'path':f'knowledge/n{i:07d}.md'} for i in range(n)}
    class Store:
        index={'nodes':nodes}
        _dirty=SimpleNamespace(write_gen=0,broad_gen=0,path_gen={})
        _read_cache={}
        def _candidates(self,**options): return list(self.index['nodes'].values())
    cg=Store()
    fn=getattr(bm25,'candidate_pool_view',bm25.candidate_pool)
    view=fn(cg)
    assert len(view)==n and view[-1]['path']==f'knowledge/n{n-1:07d}.md'
    samples=[]
    for _ in range(21):
        started=time.perf_counter();result=fn(cg);samples.append((time.perf_counter()-started)*1000)
        assert len(result)==n
    result=None;gc.collect();tracemalloc.start()
    result=fn(cg);current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    public=bm25.candidate_pool(cg); public.pop()
    assert len(fn(cg))==n
    digest=hashlib.sha256('\n'.join(e['path'] for e in nodes.values()).encode()).hexdigest()
    readings.append({'candidates':n,'samples_ms':samples,'median_ms':statistics.median(samples),
                     'one_call_allocated_peak_bytes':peak,'dataset_sha256':digest,
                     'execution':'read-only view' if hasattr(bm25,'candidate_pool_view') else 'defensive list'})
    del cg,view,result,public,nodes;gc.collect()
report={'kind':'warm candidate-container microbenchmark', 'readings':readings,
        'limits':'Synthetic metadata only. Cold filtering remains O(N); scoring, file I/O, guards, gates and fusion are outside this measurement. Public mutable API deliberately retains O(N) copies.'}
if a.output:a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
