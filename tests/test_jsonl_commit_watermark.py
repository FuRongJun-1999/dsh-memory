"""Direct acceptance entry; CI runs the identical md_cg suite."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from md_cg.test_jsonl_commit_watermark import main
if __name__ == "__main__":
    raise SystemExit(main())
