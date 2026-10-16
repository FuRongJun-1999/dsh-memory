"""Direct bounty acceptance entry point."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from md_cg.test_chain_candidate_scope import run_guard, MUTATIONS
import md_cg.test_chain_candidate_scope as guard
if __name__ == "__main__":
    raise SystemExit(run_guard(vars(guard), MUTATIONS))
