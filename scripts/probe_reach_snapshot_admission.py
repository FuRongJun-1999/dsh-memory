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

        from md_cg import reach
        cg.add('a','needle retrieval'); cg.add('b','unrelated filler'); cg.flush()
        idx=reach.ReachIndex(root).build(cg); idx.save()
        snapshot=json.loads(Path(idx.path).read_text(encoding='utf-8'))
        readings=[]
        for field,value in [('post',['wrong']),('built_at','bad'),('sem','a/path.md')]:
            data=dict(snapshot);data[field]=value
            Path(idx.path).write_text(json.dumps(data),encoding='utf-8');reach._CACHE.clear()
            os.environ['MDCG_REACH']='1'
            try:
                rows,meta=cg.search('needle',judge=False,record=False)
                readings.append({'field':field,'hits':ids(rows),'error':None})
            except Exception as exc: readings.append({'field':field,'hits':[], 'error':type(exc).__name__})
        reach._CACHE.clear()

    finally:
        cg.close()
out={'case':'reach','kind':'actual temporary-store runtime', 'readings':readings}
if a.output: a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
