# -*- coding: utf-8 -*-
"""health() skips a damaged UTF-8 node instead of crashing the health endpoint."""
from __future__ import annotations

import os
import shutil
import tempfile

from md_cg.mdcos import MdCGOS


def main() -> None:
    root = tempfile.mkdtemp(prefix="health_utf8_guard_")
    cg = MdCGOS(root, autoflush=0)
    try:
        cg.add("good", "可读的健康检查节点", tags=["domain:health"])
        cg.add("bad", "待损坏节点", tags=["domain:health"])
        cg.flush()
        bad_path = os.path.join(root, cg.index["nodes"]["bad"]["path"].replace("/", os.sep))
        with open(bad_path, "wb") as fh:
            fh.write(bytes((0xff, 0xfe, 0xfd)))

        assert cg.get("bad") is None
        results, _meta = cg.search("可读", k=5, include_neg=True)
        assert any(item[0]["id"] == "good" for item in results), results
        health = cg.health()
        assert health["total_nodes"] == 2, health
        assert sum(v["total"] for v in health["ccg_by_layer"].values()) == 1, health
        print("PASS health skips invalid UTF-8 node")
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()

