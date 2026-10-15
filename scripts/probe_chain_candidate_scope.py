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

        edge=lambda target:{'target':target,'relation_type':'causal','confidence':1.0}
        cg.add('seed','needle seed',edges=[edge('bridge')])
        cg.add('bridge','experiment',branch_id='experiment',edges=[edge('tail')])
        cg.add('tail','remote destination')
        rows,meta=query(cg,paths=('lexical','chain'),k=20)
        explicit,_=query(cg,paths=('lexical','chain'),k=20,branch='experiment')
        readings={'main_hits':ids(rows),'explicit_branch_hits':ids(explicit),
                  'expected_main_hits':['seed'],'hidden_bridge':'bridge'}

    finally:
        cg.close()
out={'case':'chain','kind':'actual temporary-store runtime', 'readings':readings}
if a.output: a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
