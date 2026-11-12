# -*- coding: utf-8 -*-
"""Bounty #68 direct-script entry; CI discovers the same md_cg guard module."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from md_cg.test_chain_best_first import main

if __name__ == "__main__":
    raise SystemExit(main())
