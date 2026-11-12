"""Run this PR's frozen guards against a separate unmodified checkout."""
import argparse
from pathlib import Path
import runpy
import sys

p = argparse.ArgumentParser()
p.add_argument('--repo', required=True, type=Path)
p.add_argument('--output', type=Path)
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(a.repo.resolve()))
import md_cg
if Path(md_cg.__file__).resolve().parent != (a.repo.resolve()/'md_cg'):
    raise SystemExit('wrong production checkout imported')
md_cg.__path__.append(str(root/'md_cg'))
sys.argv = ['guard'] + (['--output', str(a.output)] if a.output else [])
runpy.run_module('md_cg.test_stg_interval_candidates', run_name='__main__', alter_sys=True)
