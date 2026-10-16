"""Read-only baseline investigation; writes/deletes only owned temporary fixtures."""
import argparse,hashlib,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--case',choices=['topology'],default='topology');a=p.parse_args()
sys.path.insert(0,str(a.repo.resolve()))
os.environ.update(MDCG_MASTER_KEY='ab'*32,MDCG_HOTCACHE='0',MDCG_READ_CACHE='0',MDCG_SUSTAIN='0',
    MDCG_RETRIEVAL_PIPELINE='0',MDCG_UNIFY_QUERY='0',MDCG_RRF_CANDIDATES='0',MDCG_SEMANTIC='0',MDCG_EN_ATOMS='0')
from md_cg import mdcos,bm25,subgraph
result={}
with tempfile.TemporaryDirectory(prefix='expert_probe_') as td:
    cg=mdcos.MdCGOS(str(Path(td)/'audit'))
    try:
        cg.add('p','parent p',edges=[dict(target='q',relation_type='contains')])
        cg.add('q','parent q',edges=[dict(target='p',relation_type='contains')])
        check=cg.subgraph_validate()
        result['edge_only_audit']={'actual_markdown_nodes':2,'children':subgraph.children_index(cg),
            'cycle_detected':any(i['issue']=='cycle' for i in check['items']),'report':check}
    finally:cg.close()
    rows=[]
    for n in (100,300):
        nodes={str(i):{'subgraph':[str(i+1)] if i<n-1 else []} for i in range(n)}
        carrier=SimpleNamespace(index={'nodes':nodes},get=lambda _nid:None)
        events=[0]
        def trace(frame,event,arg):
            if frame.f_code.co_filename==subgraph.__file__:
                if event=='line':events[0]+=1
                return trace
            return None
        start=time.perf_counter()
        try:
            sys.settrace(trace);report=subgraph.validate(carrier)
        finally:sys.settrace(None)
        rows.append(dict(n=n,line_events=events[0],seconds=time.perf_counter()-start,issues=report['issues']))
    result['audit_scaling']={'fixture':'synthetic metadata only; CPython source-line execution counts, not file I/O benchmark','readings':rows}

a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
