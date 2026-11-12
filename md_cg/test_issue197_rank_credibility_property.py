# -*- coding: utf-8 -*-
"""test_issue197_rank_credibility_property · 名次可信度「性质判据」守卫（issue #197 / #205）

# 功能名：融合层名次可信度的**与路名无关**的性质判据（whole_tie / floor_mass）
# 生效条件：改动 md_cg/mdcos.py 的 rank_credibility / PATH_SCORE_FLOORS / search_rrf 融合门控，或改动 md_cg/hotcache.py 的 _ENV_SWITCHES 之后必跑
# 子功能：①判据纯函数三分支（whole_tie / floor_mass / 可信）+ 空输入 + 单候选 ②缺省关时判据一次都不被调用、meta 不落 rank_credibility 键（逐位不变） ③开关开时 temporal 的 floor 块被拦、lexical 的并列**不**被拦（锚机制不锚表象） ④3 条定点变异：判据被打坏 ⇒ 读数必须转红
# 执行：python -X utf8 -m md_cg.test_issue197_rank_credibility_property
# 验证方式：末行「通过 N / 失败 M」；变异段逐条打印「变异前 -> 变异后」读数
# 不适用条件：只测**融合层判据与其接线**，不测 reader/判分层；不碰在役库（全程 tempfile 沙箱）

## 缺陷现场（issue #197）
fix(#130) 用**硬编码路名名单** _RANK_ABSTAIN_PATHS = ("entity",) 表达「名次不可信」
这条**性质**：① 同一文件 :1966 的注释自认 temporal 同病、名单却没它，该路仍以
全权重投票；② 新增检索路不会自动纳入。本条把判据升级为**只读该路自身分数序列、
与路名无关的纯函数**（#205 §1.1），并把开关**缺省关**接入既有门控（叠加而非替换）。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import mdcos as _mdcos                                  # noqa: E402
from md_cg import nodefile                                          # noqa: E402
from md_cg.fsutil import atomic_write                               # noqa: E402
from md_cg.mdcos import (MdCGOS, PATH_SCORE_FLOORS,                 # noqa: E402
                         TEMPORAL_SCORE_FLOOR, rank_credibility)

PASS, FAILS = 0, []


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))


_BODY = ("# 功能名：{n}\n# 生效条件：无条件\n# 子功能：无\n"
         "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n正文 {n}。北极星协议 的负责人是谁？\n")

_OLD_DAYS = 900        # 远大于 10 个半衰期（300 天）=> cred_factor 被夹在 floor 上


def _mk_node(root, nid, extra_fm=None, layer="knowledge"):
    fm = {"id": nid, "layer": layer, "created_at": time.time(), "tags": []}
    fm.update(extra_fm or {})
    d = os.path.join(root, layer)
    os.makedirs(d, exist_ok=True)
    atomic_write(os.path.join(d, nid + ".md"),
                 nodefile.dumps(fm, _BODY.format(n=nid)))


def build_root(tag):
    """受控语料：6 条超视界（created_at 900 天前）+ 2 条新鲜。"""
    root = os.path.join(_TMP, tag, "root")
    old = time.time() - _OLD_DAYS * 86400
    for i in range(6):
        _mk_node(root, "old%02d" % i, {"created_at": old})
    for i in range(2):
        _mk_node(root, "new%02d" % i)
    return root


def run_case(cls, tag, cred_on):
    root = build_root(tag)
    if cred_on:
        os.environ["MDCG_RANK_CREDIBILITY"] = "1"
    else:
        os.environ.pop("MDCG_RANK_CREDIBILITY", None)
    eng = cls(root)
    try:
        # **必须传时间算子**，否则 `_path_temporal` 直接返回 []（无算子不启用）——
        # 那时 temporal 根本不在 ranked 里，判据无从触发。窗口覆盖全部 8 条。
        _res, meta = eng.search_rrf("北极星协议 的负责人是谁", k=60,
                                    paths=("lexical", "temporal"),
                                    start_time=time.time() - (_OLD_DAYS + 10) * 86400,
                                    end_time=time.time() + 86400)
    finally:
        eng.close()
        os.environ.pop("MDCG_RANK_CREDIBILITY", None)
    return {"no_rank_signal": sorted(meta.get("no_rank_signal") or []),
            "cred": meta.get("rank_credibility"),
            "has_key": "rank_credibility" in meta,
            "fp_sel_has_key": "rank_credibility" in (meta.get("path_fingerprint") or {}).get("selection", {})}


def mutant(patches, name):
    """文本级定点变异：把 mdcos.py 源码替换后 exec 成独立模块（不改盘上文件）。"""
    src = open(_mdcos.__file__, encoding="utf-8").read()
    for a, b in patches:
        assert a in src, "变异锚点未命中：%r" % a[:60]
        src = src.replace(a, b)
    mod = types.ModuleType("md_cg._mdcos_" + name)
    mod.__package__, mod.__file__ = "md_cg", _mdcos.__file__
    exec(compile(src, "<mutant:%s>" % name, "exec"), mod.__dict__)   # noqa: S102
    return mod


FLOOR_LINE = ("    if fl is not None and sum(1 for s in scores if s == fl) >= 2:\n"
              '        return "floor_mass"')
OR_LINE = "                    or _cred is not None):"
SWITCH_LINE = 'if os.environ.get("MDCG_RANK_CREDIBILITY") == "1" and len(_scores) >= 2:'


def main():
    print("=== issue #197 / #205 名次可信度「性质判据」守卫 ===")

    print("\n[1] 单元：rank_credibility 三分支（纯函数，只读该路自己的分数序列）")
    check("空输入 -> None（无可判）", rank_credibility("temporal", []) is None)
    check("整路同分 -> whole_tie",
          rank_credibility("lexical", [0.5, 0.5, 0.5]) == "whole_tie",
          rank_credibility("lexical", [0.5, 0.5, 0.5]))
    check("temporal 的 floor 被 >=2 个候选取到 -> floor_mass",
          rank_credibility("temporal", [TEMPORAL_SCORE_FLOOR] * 3 + [0.4]) == "floor_mass",
          rank_credibility("temporal", [TEMPORAL_SCORE_FLOOR] * 3 + [0.4]))
    check("floor 只被 1 个候选取到 -> 可信（无歧义，不误伤）",
          rank_credibility("temporal", [TEMPORAL_SCORE_FLOOR, 0.4, 0.3]) is None,
          rank_credibility("temporal", [TEMPORAL_SCORE_FLOOR, 0.4, 0.3]))
    check("有并列但**无下限声明**的路 -> 可信（锚机制不锚表象）",
          rank_credibility("lexical", [0.5, 0.5, 0.2, 0.1]) is None,
          rank_credibility("lexical", [0.5, 0.5, 0.2, 0.1]))
    check("PATH_SCORE_FLOORS 登记 temporal 的 floor（单点登记，非路名名单）",
          PATH_SCORE_FLOORS.get("temporal") == TEMPORAL_SCORE_FLOOR, PATH_SCORE_FLOORS)

    print("\n[2] 缺省关：判据一次都不被调用、meta 不落键（与 HEAD 逐位相同）")
    calls = []
    _orig = _mdcos.rank_credibility
    _mdcos.rank_credibility = lambda *a, **k: (calls.append(a[0]), _orig(*a, **k))[1]
    try:
        off = run_case(MdCGOS, "off", cred_on=False)
    finally:
        _mdcos.rank_credibility = _orig
    print("    读数：no_rank_signal=%s has_key=%s 调用次数=%d"
          % (off["no_rank_signal"], off["has_key"], len(calls)))
    check("缺省关时 rank_credibility 零调用", calls == [], calls)
    check("缺省关时 meta 无 rank_credibility 键", off["has_key"] is False, off)
    check("缺省关时 path_fingerprint.selection 无 rank_credibility 键（hash 不变）",
          off["fp_sel_has_key"] is False, off)

    print("\n[3] 开关开：temporal 的 floor 块被拦，lexical 的并列不被拦")
    on = run_case(MdCGOS, "on", cred_on=True)
    print("    读数：no_rank_signal=%s cred=%s" % (on["no_rank_signal"], on["cred"]))
    check("开关开时 temporal 被判 floor_mass", (on["cred"] or {}).get("temporal") == "floor_mass",
          on["cred"])
    check("开关开时 temporal 进 no_rank_signal（弃权，退回 recall_only）",
          "temporal" in on["no_rank_signal"], on["no_rank_signal"])
    check("lexical 含并列但无下限声明 -> **不**被判 floor_mass",
          "lexical" not in (on["cred"] or {}), on["cred"])
    check("开关开时 meta 落 rank_credibility 键（可审计）", on["has_key"] is True, on)

    print("\n[4] 定点变异（文本级：只改内存副本，不改盘上文件）")
    m1 = mutant([(FLOOR_LINE, '    if False:\n        return "floor_mass"')], "m1_nofloor")
    r1 = run_case(m1.MdCGOS, "m1", cred_on=True)
    print("    M1 打坏 floor_mass 判据 -> cred=%s no_rank_signal=%s"
          % (r1["cred"], r1["no_rank_signal"]))
    check("M1 判据被打坏 => temporal 逃逸（本应 floor_mass，变异后无）",
          (r1["cred"] or {}).get("temporal") is None and "temporal" not in r1["no_rank_signal"],
          "fixed=%s mutant=%s" % (on["cred"], r1["cred"]))

    m2 = mutant([(OR_LINE, "                    ):")], "m2_nogate")
    r2 = run_case(m2.MdCGOS, "m2", cred_on=True)
    print("    M2 拆掉门控 OR 分支 -> cred=%s no_rank_signal=%s"
          % (r2["cred"], r2["no_rank_signal"]))
    check("M2 门控被打坏 => 判据算出但不弃权（temporal 不进 no_rank_signal）",
          (r2["cred"] or {}).get("temporal") == "floor_mass"
          and "temporal" not in r2["no_rank_signal"],
          "fixed=%s mutant=%s" % (on["no_rank_signal"], r2["no_rank_signal"]))

    m3 = mutant([(SWITCH_LINE,
                  'if False and len(_scores) >= 2:')], "m3_always_off")
    r3 = run_case(m3.MdCGOS, "m3", cred_on=True)
    print("    M3 把开关判据打坏（恒关）-> cred=%s" % (r3["cred"],))
    check("M3 开关失效 => 开关开时也不再落键（判别力成立）", r3["has_key"] is False, r3)

    print("\n" + "=" * 68)
    print("通过 %d / 失败 %d" % (PASS, len(FAILS)))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    print("=" * 68)
    return 1 if FAILS else 0


_TMP = tempfile.mkdtemp(prefix="mdcos197_")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "root")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxstore")
os.environ.setdefault("MDCG_MASTER_KEY", "00" * 32)
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)

if __name__ == "__main__":
    sys.exit(main())