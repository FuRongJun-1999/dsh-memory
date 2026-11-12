"""Run this PR's frozen guards against another checkout's production modules."""
import argparse
import importlib.util
from pathlib import Path
import sys
p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, required=True)
p.add_argument('--output', type=Path)
a = p.parse_args()
sys.path.insert(0, str(a.repo.resolve()))
import md_cg
path = Path(__file__).resolve().parents[1] / 'md_cg/test_chain_candidate_scope.py'
spec = importlib.util.spec_from_file_location('md_cg._frozen_chain_candidate_scope', path)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
argv = ['--output', str(a.output)] if a.output else []
raise SystemExit(mod.run_guard(vars(mod), [], argv))
