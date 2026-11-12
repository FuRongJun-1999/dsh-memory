# -*- coding: utf-8 -*-
# 功能名：命名别名（aliases）守卫——别名可召回、且不污染身份/锚点判据
# 生效条件：python -X utf8 -m md_cg.test_aliases_r2r3；被测面＝md_cg/mdcg.py 的 _like/_canonical_state 与 tasks/predict 的 tags 判据
# 子功能：
#   A. 别名参与词法召回（R2 的「检索能命中」）——只改 aliases、不改正文，用别名查询应命中
#   B. aliases 不在 anchor 的 STATE_FIELDS 里 ⇒ 加别名不改变锚定状态摘要（R3 的 anchor 面）
#   C. tasks 的「是不是任务卡」只读 tags ⇒ 加别名不翻转（R3 的 tasks 面）
#   D. predict 的 ANCHOR_SKIP_TAGS 只读 tags ⇒ 加别名不触发跳过（R3 的 predict 面）
# 执行：纯函数级断言，不建库、不写盘
# 验证方式：全部 PASS exit 0；每条都注明「怎么让它红」
# 不适用条件：不覆盖语义检索（本守卫只测词法面）；不覆盖 aliases 的写入/索引面（那是工程文档的活）
"""为什么需要它（issue：命名与检索规范 R2/R3 的可验证载体）

规范此前写「别名落 aliases、只参与召回不参与判据」，但 aliases 字段根本不存在 ⇒
那条「加别名后三个判据结果不变」的验证是**恒真空断言**（没有可加的东西）。
本守卫的三组 B/C/D 就是为了让那句话**能红**：只要有人把 aliases 塞进 tags、
或把 aliases 加进 STATE_FIELDS / ANCHOR_SKIP_TAGS，本守卫立刻红。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg.mdcg import MdCG  # noqa: E402

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


def main():
    like = MdCG._like

    print("== A 别名参与词法召回（怎么让它红：从 _like 里去掉 aliases 拼接）")
    fm_base = {"tags": ["记忆"], "layer": "knowledge"}
    body = "这是一段完全无关的正文内容"
    ok(not like(body, fm_base, ["旁白"]), "A0 基线：无 aliases 时别名查不到（证明下面 A1 不是恒真）")
    fm_alias = {"tags": ["记忆"], "layer": "knowledge", "aliases": ["旁白"]}
    ok(like(body, fm_alias, ["旁白"]), "A1 加了 aliases 后，用别名「旁白」能命中", "未命中")
    ok(like(body, fm_alias, ["记忆"]), "A2 原 tags 仍然命中（别名不挤掉原标签）")
    ok(not like(body, {"tags": [], "aliases": ["旁白"]}, ["无关词"]),
       "A3 别名不等于万能命中（不相关词仍不命中）")

    print("== A4 脏数据容错（怎么让它红：去掉 isinstance 判断后传字符串）")
    try:
        like(body, {"tags": [], "aliases": "旁白"}, ["旁白"])
        ok(True, "A4 aliases 为字符串时不抛异常（按空处理，不误命中）")
    except Exception as e:  # noqa: BLE001
        ok(False, "A4 aliases 为字符串时不抛异常", "%s: %s" % (type(e).__name__, e))

    print("== B aliases 不进锚定状态摘要（怎么让它红：把 aliases 加进 STATE_FIELDS）")
    from md_cg import anchor as _anchor
    ok("aliases" not in _anchor.STATE_FIELDS,
       "B1 STATE_FIELDS 不含 aliases（含了 → 每次改别名都会让全部在册回执失效）",
       _anchor.STATE_FIELDS)
    fm1 = {"layer": "knowledge", "tags": ["a"], "condition_space": {}}
    fm2 = dict(fm1, aliases=["别名甲", "别名乙"])
    ok(_anchor._canonical_state(fm1) == _anchor._canonical_state(fm2),
       "B2 加 aliases 后 state_digest 的原料完全相同（锚定不受影响）")

    print("== C 任务卡判据只读 tags（怎么让它红：把 aliases 并进 tags 或并进判据）")
    from md_cg import tasks as _tasks
    ok("aliases" not in getattr(_tasks, "TASK_TAG", ""),
       "C1 TASK_TAG 仍是\"task\"，没被改名成别名机制", getattr(_tasks, "TASK_TAG", None))
    src = open(os.path.join(ROOT, "md_cg", "tasks.py"), encoding="utf-8").read()
    ok("aliases" not in src,
       "C2 tasks.py 全文不出现 aliases（任务卡判据不看别名）",
       [l for l in src.splitlines() if "aliases" in l][:2])

    print("== D 预测锚点判据只读 tags（怎么让它红：把 aliases 并进 ANCHOR_SKIP_TAGS 的读取处）")
    from md_cg import predict as _predict
    ok(tuple(_predict.ANCHOR_SKIP_TAGS) == ("gap_hint", "scene"),
       "D1 ANCHOR_SKIP_TAGS 未被扩成含别名机制", _predict.ANCHOR_SKIP_TAGS)
    psrc = open(os.path.join(ROOT, "md_cg", "predict.py"), encoding="utf-8").read()
    ok("aliases" not in psrc,
       "D2 predict.py 全文不出现 aliases（能不能当锚点不看别名）",
       [l for l in psrc.splitlines() if "aliases" in l][:2])

    print()
    print("别名守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())