# -*- coding: utf-8 -*-
"""薄壳：由 registry 真源生成**文档参数表**。

    python -X utf8 scripts/gen_config_doc.py [--check]

`--check` 只比对（生成件陈旧即非零退出，供 CI / 守卫调用），不写盘。
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from md_cg import config_registry as cr            # noqa: E402
from md_cg import config_render as rnd             # noqa: E402

OUT = os.path.join(REPO, "docs", "reference", "配置参数表_v0.1.md")


def main(argv):
    text = rnd.render_doc(cr)
    if "--check" in argv:
        cur = open(OUT, encoding="utf-8").read() if os.path.isfile(OUT) else ""
        if cur != text:
            print("生成件陈旧：", os.path.relpath(OUT, REPO))
            return 1
        print("生成件最新：", os.path.relpath(OUT, REPO))
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("已写：", os.path.relpath(OUT, REPO), len(text), "字节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
