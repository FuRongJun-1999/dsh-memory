import argparse,importlib.util,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--output',type=Path);a=p.parse_args()
sys.path.insert(0,str(a.repo.resolve()))
source=Path(__file__).resolve().parents[1]/'md_cg/test_subgraph_bounded_bfs.py'
spec=importlib.util.spec_from_file_location('md_cg._replay_subgraph_bounded_bfs',source)
mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
raise SystemExit(mod.run_guard(vars(mod),mod.MUTATIONS,['--output',str(a.output)] if a.output else []))
