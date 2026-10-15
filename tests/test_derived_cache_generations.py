"""Direct runtime/negative-control entry point."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from md_cg.test_derived_cache_generations import run_guard, MUTATIONS
import md_cg.test_derived_cache_generations as guard
if __name__ == "__main__":
    raise SystemExit(run_guard(vars(guard), MUTATIONS))
