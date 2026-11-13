# -*- coding: utf-8 -*-
"""守卫 · issue #694 会话级私有（默认公开，逐会话自选）。

使用者裁定（2026-11-12）：**默认公开**，自己选会话内容可私有；每个会话独立。

底座：`_readable` 已实现「private/secret = 会话绑定档」（仅 frontmatter.session 归属会话可见）。
本件只做两件事：① 会话账本记 private 标志；② 新写入未声明密级时按该标志取档。

守卫（只打公开面）：
  G1 默认（未设标志）新写入仍是 internal（不回归）
  G2 标记 private 后新写入 = private
  G3 私有节点：本会话可读、他会话不可读
  G4 切回 public 后新写入恢复 internal，**旧私有节点不被改写**
  G5 显式声明的 sensitivity 优先于会话标志
  G6 未带 session 的调用不受影响（仍 internal）
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg.sustain import SessionLedger  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def mk(root, sess):
    p = Principal(clearance="private", can_write=True, session=sess)
    g = MdCGSecure(root, principal=p)
    g.session = sess
    return g


def main():
    print("=" * 70)
    print("issue #694：会话级私有（默认公开）")
    print("=" * 70)

    root = tempfile.mkdtemp(prefix="i694_")
    a = mk(root, "sessA")
    a.add("n_a1", "A 公开内容", layer="contextual", consistency=False)
    ok(a.get("n_a1")["frontmatter"]["sensitivity"] == "internal",
       "G1 默认（未设标志）新写入 = internal（不回归）",
       a.get("n_a1")["frontmatter"]["sensitivity"])

    led = SessionLedger(root)
    ok(led.is_private("sessA") is False, "G1b 新会话默认非私有")
    led.set_private("sessA", True)
    ok(led.is_private("sessA") is True, "G2a 标记后账本读回为私有")
    a.add("n_a2", "A 私有内容", layer="contextual", consistency=False)
    ok(a.get("n_a2")["frontmatter"]["sensitivity"] == "private",
       "G2 标记 private 后新写入 = private",
       a.get("n_a2")["frontmatter"]["sensitivity"])

    b = mk(root, "sessB")
    ok(bool(a.get("n_a2")) is True, "G3a 本会话可读自己的私有节点")
    ok(bool(b.get("n_a2")) is False, "G3b 他会话读不到私有节点（隔离成立）")
    ok(bool(b.get("n_a1")) is True, "G3c 旧公开节点仍跨会话可见")

    led.set_private("sessA", False)
    a.add("n_a3", "A 再次公开内容", layer="contextual", consistency=False)
    ok(a.get("n_a3")["frontmatter"]["sensitivity"] == "internal",
       "G4 切回 public 后新写入恢复 internal",
       a.get("n_a3")["frontmatter"]["sensitivity"])
    ok(a.get("n_a2")["frontmatter"]["sensitivity"] == "private",
       "G4b 旧私有节点不被改写（只影响后续写入）")

    a.add("n_a4", "A 显式声明内容", layer="contextual",
          sensitivity="public", consistency=False)
    ok(a.get("n_a4")["frontmatter"]["sensitivity"] == "public",
       "G5 显式声明优先于会话标志",
       a.get("n_a4")["frontmatter"]["sensitivity"])

    c = mk(root, "sessC")
    c.add("n_c1", "C 未带 session 场景", layer="contextual", consistency=False)
    ok(c.get("n_c1")["frontmatter"]["sensitivity"] == "internal",
       "G6 未标私有的会话不受影响（仍 internal）")

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())