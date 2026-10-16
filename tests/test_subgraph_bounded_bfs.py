from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from md_cg import test_subgraph_bounded_bfs as guard
if __name__=='__main__':raise SystemExit(guard.run_guard(vars(guard),guard.MUTATIONS))
