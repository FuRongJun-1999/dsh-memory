# -*- coding: utf-8 -*-
"""issue #757：验证态继承的正文比对改用索引 hash（不再读盘回正文）。"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

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


def _state(cg, nid):
    return ((cg.get(nid) or {}).get("frontmatter") or {}).get("verification_state")


def main():
    print("=" * 68)
    print("issue #757 · 验证态继承用索引 hash 比对")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="iss757_")
    try:
        cg = MdCG(os.path.join(tmp, "r"), autoflush=1)
        cg.add("n757", BODY, layer="knowledge", verification_basis="test")
        cg.verify("n757", "初始确认", "confirmed")
        ok(_state(cg, "n757") == "verified", "A0 前置：节点为 verified", _state(cg, "n757"))
        # 无 verify 权限的 principal
        cg.principal = SimpleNamespace(allows_op=lambda op: False)
        # A1 正文未变 ⇒ 仍 verified（索引 hash 相等 ⇒ 不降级）
        cg.add("n757", BODY, layer="knowledge")
        ok(_state(cg, "n757") == "verified", "A1 正文未变 ⇒ 仍 verified", _state(cg, "n757"))
        # A2 正文变了 ⇒ doubted
        cg.add("n757", BODY + "\n追加一行", layer="knowledge")
        ok(_state(cg, "n757") == "doubted", "A2 正文变 ⇒ 降 doubted", _state(cg, "n757"))
        cg.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # A3/A4（复核要求：钉实现路径，而不只钉语义）——直接测判定函数，
    # 用会计数 cg.get 的假 cg 证明「有索引 hash 时不读盘」。
    class _CountCG:
        def __init__(self, content):
            self.n = 0
            self._c = content
        def get(self, nid):
            self.n += 1
            return {'content': self._c}

    from md_cg import nodefile as _nf
    _c1 = _CountCG(BODY + chr(10))
    _pe = {'content_hash': _nf.content_hash(BODY)}
    _r1 = MdCG._vstate_body_changed(_c1, 'x', _pe, BODY)
    ok(_r1 is False and _c1.n == 0, 'A3 有索引 hash 时判定不读盘（快路径）', (_r1, _c1.n))
    _c2 = _CountCG(BODY + chr(10))
    _r2 = MdCG._vstate_body_changed(_c2, 'x', {}, BODY)
    ok(_r2 is False and _c2.n == 0, 'A4 无 prev_entry 时也不读盘', (_r2, _c2.n))
    _c3 = _CountCG(BODY + chr(10))
    _r3 = MdCG._vstate_body_changed(_c3, 'x', {'content_hash': ''}, BODY)
    ok(_r3 is False and _c3.n == 1, 'A5 缺 hash 时回退读盘一次（同函数归一）', (_r3, _c3.n))
    print()
    print("issue #757：%d 项失败" % len(FAILS) if FAILS else "issue #757：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())