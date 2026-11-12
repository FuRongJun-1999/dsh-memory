"""Actual temporary-store before/after probe; offline, standard library only."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time

p=argparse.ArgumentParser(); p.add_argument('--repo',type=Path,required=True)
p.add_argument('--output',type=Path); a=p.parse_args()
sys.path.insert(0,str(a.repo.resolve()))
os.environ.update(MDCG_MASTER_KEY='ab'*32,MDCG_HOTCACHE='0',MDCG_SEMANTIC='0',
                  MDCG_RRF_CANDIDATES='0',MDCG_UNIFY_QUERY='0',MDCG_EN_ATOMS='0',
                  MDCG_RETRIEVAL_PIPELINE='0',MDCG_RANK_CREDIBILITY='0')
from md_cg import mdcos

def ids(rows): return [r[0]['id'] for r in rows]
def query(cg,**kw):
    options=dict(paths=('lexical',),judge=False,record=False,k=1); options.update(kw)
    return cg.search_rrf('needle',**options)

with tempfile.TemporaryDirectory(prefix='five_native_') as root:
    cg=mdcos.MdCGOS(root)
    try:

        from md_cg import bm25
        for i in range(1000): cg.add('n%04d'%i,'needle' if i%127==0 else 'filler %d'%i)
        cg.flush(); before,_=query(cg,paths=('bm25',),k=20)
        copied=[];orig=bm25._PoolEntries.__init__
        def counted(obj,items,key): copied.append(len(items));orig(obj,items,key)
        bm25._PoolEntries.__init__=counted
        times=[]
        try:
            for _ in range(9):
                started=time.perf_counter(); rows,meta=query(cg,paths=('bm25',),k=20)
                times.append((time.perf_counter()-started)*1000)
                assert ids(rows)==ids(before)
        finally: bm25._PoolEntries.__init__=orig
        import statistics
        readings={'nodes':len(cg.index['nodes']),'repeats':len(times),'copied_candidate_references':sum(copied),
                  'hits':ids(rows),'pool_reused':meta['bm25'].get('pool_reused'),
                  'warm_query_ms':times,'median_ms':statistics.median(times),
                  'boundary':'1000 actual Markdown nodes; no million-node end-to-end claim'}

    finally:
        cg.close()
out={'case':'pool','kind':'actual temporary-store runtime', 'readings':readings}
if a.output: a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
