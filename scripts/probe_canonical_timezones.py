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

        from md_cg import trust
        ts=datetime(2026,10,15,tzinfo=timezone.utc).timestamp()
        text='2026-10-15T08:00:00+08:00'
        cg.add('utc','needle timezone',temporal=text,effective_until=text)
        rows,meta=query(cg,start_time=ts-1,end_time=ts+1,time_axis='observed')
        readings={'expected_epoch':ts,'offset_epoch':trust.parse_time(text),
                  'z_epoch':trust.parse_time('2026-10-15T00:00:00Z'),
                  'local_timezone':list(time.tzname),'observed_hits':ids(rows),
                  'deadline_state':trust.validity({'effective_until':text},now=ts+1)[0],
                  'bad_endpoint_error':bool(trust.check_time_args(start_time='NaN')[2])}

    finally:
        cg.close()
out={'case':'time','kind':'actual temporary-store runtime', 'readings':readings}
if a.output: a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False))
