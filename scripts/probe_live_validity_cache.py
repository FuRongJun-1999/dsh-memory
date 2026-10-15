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

        from md_cg import hotcache
        hotcache.attach(cg)
        deadline=time.time()+2.0
        cg.add('a_expiring','needle',importance=.9,valid_until=deadline)
        cg.add('z_stable','needle',importance=.4)
        before,bmeta=query(cg,validity=True)
        time.sleep(max(0,deadline-time.time()+.1))
        after,meta=query(cg,validity=True)
        readings={'before':ids(before),'after_deadline':ids(after),'cached':meta.get('cached',False),
                  'seconds_past_deadline':time.time()-deadline,'query_ttl':hotcache.QUERY_TTL,
                  'clock':'real wall clock; no mocked clock'}

    finally:
        cg.close()
out={'case':'validity','kind':'actual temporary-store runtime', 'readings':readings}
if a.output: a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
