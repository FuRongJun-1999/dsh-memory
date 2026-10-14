"""Direct runtime/negative-control entry point."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from md_cg.test_trust_bounded_frontier import run_guard, MUTATIONS
import md_cg.test_trust_bounded_frontier as guard
if __name__ == "__main__":
    raise SystemExit(run_guard(vars(guard), MUTATIONS))
