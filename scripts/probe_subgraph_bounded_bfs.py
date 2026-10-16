"""Read-only baseline investigation; writes/deletes only owned temporary fixtures."""
import argparse,hashlib,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--case',choices=['traverse'],default='traverse');a=p.parse_args()
sys.path.insert(0,str(a.repo.resolve()))
os.environ.update(MDCG_MASTER_KEY='ab'*32,MDCG_HOTCACHE='0',MDCG_READ_CACHE='0',MDCG_SUSTAIN='0',
    MDCG_RETRIEVAL_PIPELINE='0',MDCG_UNIFY_QUERY='0',MDCG_RRF_CANDIDATES='0',MDCG_SEMANTIC='0',MDCG_EN_ATOMS='0')
from md_cg import mdcos,bm25,subgraph
result={}
with tempfile.TemporaryDirectory(prefix='expert_probe_') as td:
    cg=mdcos.MdCGOS(str(Path(td)/'traverse'))
    try:
        graph={'r':['a','b'],'a':['x'],'x':['c'],'b':['c'],'c':['tail'],'tail':[]}
        for nid,kids in graph.items():cg.add(nid,'hierarchy '+nid,subgraph=kids)
        ex=cg.subgraph_expand('r',max_depth=3)
        capped=subgraph.expand(cg,'r',max_nodes=1)
        result['traversal']={'actual_markdown_nodes':len(graph),'depth3_ids':ex['nodes'],
            'tail_recalled':'tail' in ex['nodes'],'tail_path':ex['paths'].get('tail'),
            'max_nodes_one':capped['n_nodes'],'edges_at_budget_one':capped['n_edges'],
            'edges_closed':all(e['source'] in capped['nodes'] and e['target'] in capped['nodes'] for e in capped['edges'])}
    finally:cg.close()

a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
