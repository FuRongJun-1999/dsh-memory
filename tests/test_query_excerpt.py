"""Direct acceptance entry; implementation is discovered by the normal CI."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from md_cg.test_query_excerpt import main

if __name__ == "__main__":
    raise SystemExit(main())
