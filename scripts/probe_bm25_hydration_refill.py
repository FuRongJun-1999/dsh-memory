"""Read-only baseline investigation; writes/deletes only owned temporary fixtures."""
import argparse,hashlib,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--case',choices=['hydrate'],default='hydrate');a=p.parse_args()
sys.path.insert(0,str(a.repo.resolve()))
os.environ.update(MDCG_MASTER_KEY='ab'*32,MDCG_HOTCACHE='0',MDCG_READ_CACHE='0',MDCG_SUSTAIN='0',
    MDCG_RETRIEVAL_PIPELINE='0',MDCG_UNIFY_QUERY='0',MDCG_RRF_CANDIDATES='0',MDCG_SEMANTIC='0',MDCG_EN_ATOMS='0')
from md_cg import mdcos,bm25,subgraph
result={}
with tempfile.TemporaryDirectory(prefix='expert_probe_') as td:
    cg=mdcos.MdCGOS(str(Path(td)/'bm25'))
    try:
        for i in range(53):cg.add(f'd{i:03}',('apple '*(1+i%5))+'pear',importance=0.1+i/100)
        cg.flush();fired=[];original=bm25.BM25Index.rank
        def race(idx,*args,**kw):
            ranked=original(idx,*args,**kw)
            if not fired and ranked:
                path=ranked[0][0];target=Path(cg.root)/path
                assert target.resolve().is_relative_to(Path(td).resolve())
                target.unlink();fired.append(path)
            return ranked
        opts=dict(k=50,paths=('bm25',),judge=False,record=False)
        with mock.patch.object(bm25.BM25Index,'rank',race):hits,meta=cg.search_rrf('apple pear',**opts)
        fresh=mdcos.MdCGOS(cg.root)
        try:
            fresh.rebuild_index();oracle,_=fresh.search_rrf('apple pear',**opts)
        finally:fresh.close()
        ids=[row[0]['id'] for row in hits];expected=[row[0]['id'] for row in oracle]
        result['bm25_hydration']={'actual_markdown_nodes_before':53,'actual_deleted_after_rank':fired,
            'returned':len(hits),'fresh_oracle_returned':len(oracle),'ids_equal_fresh_oracle':ids==expected,
            'returned_ids':ids,'oracle_ids':expected,'report':meta.get('bm25',{})}
    finally:cg.close()
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
