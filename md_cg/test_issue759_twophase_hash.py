# -*- coding: utf-8 -*-
"""issue #759：twophase 指纹与索引条目同源（不再先剥尾换行再哈希）。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import nodefile, twophase   # noqa: E402
from md_cg.mdcg import MdCG   # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


BODY = ("# 功能名：x\n# 生效条件：y\n# 子功能：z\n# 执行：e\n"
        "# 验证方式：test\n# 不适用条件：无\n\n正文")


def main():
    print("=" * 68)
    print("issue #759 · twophase 指纹与索引同源")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="iss759_")
    try:
        cg = MdCG(os.path.join(tmp, "r"), autoflush=1)
        # A1：常盘形态（无尾换行入参）——begin 指纹 == 索引条目口径
        tok = twophase.begin(cg, "n759a", BODY)
        ok(tok.get("content_hash") == nodefile.content_hash(BODY),
           "A1 begin 指纹 == content_hash(正文)（与索引同函数）", tok.get("content_hash"))
        # A2：≥2 尾换行——不再被剥掉（旧口径会剥成 1 个尾换行，产生第二个指纹）
        tok2 = twophase.begin(cg, "n759b", BODY + "\n\n")
        ok(tok2.get("content_hash") == nodefile.content_hash(BODY + "\n\n"),
           "A2 ≥2 尾换行指纹不被剥（旧行为会算成 1 个尾换行）")
        ok(tok2.get("content_hash") != nodefile.content_hash(BODY + "\n"),
           "A2b 与 1 尾换行形态不同值（同节点不再有两个指纹）")
        # A3：落盘后判 judge 为 committed（同源自洽）
        cg.add("n759a", BODY, layer="knowledge")
        # intent 记录里 id 字段名与 _judge 读取口径不同（按 node_id 落账），这里直接按判定契约构造。
        st, why = twophase._judge(cg, {"id": "n759a", "content_hash": tok["content_hash"]})
        ok(st == twophase.STATUS_COMMITTED, "A3 begin→add→judge = committed", (st, why))
        # A4（复核要求）：**legacy intent 放行**——旧 begin 存的是 content_hash(_norm(x))。
        ok(twophase._judge(cg, {"id": "n759a", "content_hash": nodefile.content_hash(twophase._norm(BODY))})[0]
           == twophase.STATUS_COMMITTED,
           "A4 legacy 口径 intent 仍判 committed（兼容分支不是死代码）")
        cg.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("issue #759：%d 项失败" % len(FAILS) if FAILS else "issue #759：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())