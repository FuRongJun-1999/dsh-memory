# -*- coding: utf-8 -*-
r"""守卫 · #89② 0 分条目不得装进检索结果（2026-10-09 DSH 端实施）。

缺陷（GitHub #89）：无关查询（如「红烧肉怎么做」）会返回 k 条**分数全为 0.0** 的
条目——它们没有质量信号，对调用方无价值且有误导（LLM 会当成相关内容）。

判据（真跑真库）：
  G1 无关查询 ⇒ **不返回任何 0 分条目**（修前返回 5 条 0 分）
  G2 精确命中 ⇒ 仍正常返回（score > 0 者不受影响）
  G3 混合 ⇒ 结果集内**不存在** score == 0 的条目
运行：python -X utf8 -m md_cg.test_issue89_zero_score
退出码：0 全绿 ｜ 1 断言失败

靶区收窄（zcode 端，2026-10-09）：本守卫钉的是「T3 全量兜底 ∧ 全库无真命中」这一
**唯一**情形（判据单点 `MdCG._zero_filler_only`）——该守卫自身的判据即
`MdCG._primary_bound`（主结果裁切上界）。反面证明见 `--mutate`：

  python -X utf8 -m md_cg.test_issue89_zero_score --mutate no-cut

`no-cut` = 内存注入「去掉裁切」（`_primary_bound` 恒返回 `_primary_slots`）⇒ G1/G3
必须转红并点名（范式照 `md_cg/test_w7_redlines.py`）。
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
SIX = lambda s: ("# 功能名：t\n# 生效条件：t\n# 子功能：t\n# 执行：" + s
                 + "\n# 验证方式：t\n# 不适用条件：t\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def _run(root=None):
    """跑三条正断言（真跑真库）；返回 (转红断言名集合, PASS 数, FAIL 数)。"""
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    root = root or tempfile.mkdtemp(prefix="p89g_")
    p = Principal(actor="guard", clearance="secret", can_write=True, can_admin=True,
                  role="designer", auth_mode="local-cli", session="guard")
    cg = MdCGSecure(root, principal=p, autoflush=0)
    for i in range(120):
        cg.add("k%04d" % i, SIX("主题%d 关键词 KW%04d 说明 %d" % (i % 10, i, i)))
    cg.flush()

    def rows(q):
        docs, _stat = cg.search(q, k=5)
        out_ = []
        for it in docs:
            if isinstance(it, tuple):
                _id = (it[0] or {}).get("id") if isinstance(it[0], dict) else None
                out_.append((_id, it[1] if len(it) > 1 else None))
        return out_

    irr = rows("红烧肉怎么做")
    zero = [x for x in irr if float(x[1] or 0) == 0.0]
    check("G1 无关查询 ⇒ 不返回 0 分条目（修前返回 5 条 0 分）",
          len(zero) == 0, "返回 %d 条，其中 0 分 %d 条" % (len(irr), len(zero)))

    hit = rows("KW0007")
    check("G2 精确命中 ⇒ 仍正常返回", len(hit) >= 1 and any(float(s or 0) > 0 for _, s in hit),
          "hit=%r" % (hit[:3],))

    check("G3 结果集内不存在 score == 0 的条目",
          all(float(s or 0) > 0 for _, s in irr), "irr=%r" % (irr[:5],))

    cg.close()
    return set(FAILS), PASS, FAIL


def main():
    _red, p, f = _run()
    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (p, f))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if f else 0


# ---------------------------------------------- 定点变异（反面探针，自证判别力）
def _set_bound(fn):
    """把 `MdCG._primary_bound` 换成 fn（纯内存），返回恢复函数。

    恢复走 `__dict__` 快照（`test_neg_tail_honesty.py` 同款踩坑：对 staticmethod/
    实例方法用 `getattr` 取回会把方法**绑定**，还原时语义变了）。
    """
    from md_cg.mdcg import MdCG
    orig = MdCG.__dict__["_primary_bound"]
    MdCG._primary_bound = fn

    def _restore():
        MdCG._primary_bound = orig
    return _restore


#: 变异名 → (说明, 应用函数→恢复函数, 期望转红的断言名集合)
_MUTATIONS = {
    "no-cut": (
        "去掉 #89② 裁切（`_primary_bound` 恒返回 `_primary_slots`）"
        "——T3 兜底重新把 0 分填充行装进结果",
        lambda: _set_bound(
            lambda self, k, n_neg, tier, n_real: self._primary_slots(k, n_neg)),
        {"G1 无关查询 ⇒ 不返回 0 分条目（修前返回 5 条 0 分）",
         "G3 结果集内不存在 score == 0 的条目"}),
}


def _mutate(name):
    if name not in _MUTATIONS:
        print("未知变异名 %r（可选 %s）" % (name, sorted(_MUTATIONS)))
        return 1
    mname, apply, expect = _MUTATIONS[name]
    print("!! #89② 定点变异自证：内存注入退化，要求**恰好**命中期望红项\n")
    bad = []
    with contextlib.redirect_stdout(io.StringIO()):
        base_red, _, _ = _run()
    if base_red:
        bad.append("基线即转红：%s" % sorted(base_red))
    print("  未变异基线：红项 %d %s" % (len(base_red), sorted(base_red)))
    restore = apply()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            red, _, _ = _run()
    except Exception as exc:                                   # noqa: BLE001
        red = {"<变异体异常:%s>" % type(exc).__name__}
    finally:
        restore()
    hit = red == expect
    if not hit:
        bad.append("变异 %s：红项 %s ≠ 期望 %s" % (name, sorted(red), sorted(expect)))
    print("  变异 %s\n    红项 %d（期望 %d）%s  %s"
          % (mname, len(red), len(expect), "PASS" if hit else "**FAIL**",
             sorted(red) if not hit else ""))
    print("\n变异自证：" + ("PASS（恰好命中期望红项）" if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--mutate" in sys.argv:
        _i = sys.argv.index("--mutate")
        sys.exit(_mutate(sys.argv[_i + 1] if _i + 1 < len(sys.argv) else ""))
    sys.exit(main())
