# -*- coding: utf-8 -*-
"""issue #298 守卫：冲突台账 _consistency.jsonl 的密级面（落盘去原文 + 读面收口）。

病灶（bfc40c1，复现 3/3）：consistency.check() 不知道写入密级，log() 无条件把整条
判定明文追加——pos/neg（生效条件/不适用条件原文）、conflicts[].pos_side/neg_side、
slot（功能名前 40 字）、cond_routes.only_new_side/only_existing_side 全部明文；
而 consistency.history 只要求 write 权限、不做可见性过滤，于是 clearance 仅 internal 的
record/sustain/verify/reflect/orchestr 令牌能读到同一批节点 get 判 not_found 的条件原文。

修法（两层，各自独立生效）：
  ① 落盘去原文（consistency.py）：落账密级 = 调用方声明值与**本次真进了判定的既有节点**
     密级中的最高档；高于 internal 时以 scrub_record() 去原文，并加 sensitivity /
     redacted 两个键。**只改落盘副本**，check() 返回给调用方的回执不变。
     另：声明值缺失而 exclude 指向已存在节点时，继承该节点盘面密级（#297 的继承语义，
     cg(op=write) 动词面走这条路）。
  ② 读面收口（mdcos.py）：MdCGSecure.consistency_history 覆写——can_admin 原样；
     其他身份只有 sensitivity 为 public/internal 且 clearance 覆盖的记录保留原文，
     其余（含**升级前没有 sensitivity 键**的旧记录）一律去原文。条数与顺序不变。

运行：python -X utf8 -m md_cg.test_issue298_consistency_ledger_sensitivity
      python -X utf8 -m md_cg.test_issue298_consistency_ledger_sensitivity --mutate
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import consistency as C
from md_cg.mdcos import MdCGSecure
from md_cg.security import Principal

MODULE = "md_cg.test_issue298_consistency_ledger_sensitivity"
KEK = bytes.fromhex("ab" * 32)
MARK = "PRVCOND298"
MARK_NEG = "PRVNAC298"
MARK_FN = "PRVFN298"

CARD = ("# 功能名：%s晚间用药\n# 生效条件：%s 确诊后 每晚睡前\n# 子功能：用药提醒\n"
        "# 执行：服用舍曲林 %s\n# 验证方式：医嘱\n# 不适用条件：%s 住院期间")

_PASS, _FAIL, _SKIP = [], [], []


def _check(name, ok, detail=""):
    (_PASS if ok else _FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name,
                         ("  —— " + str(detail)[:180]) if (detail and not ok) else ""))


def _tmp():
    return tempfile.mkdtemp(prefix="i298g_")


def _os(root, role="designer", clearance="private", admin=True, actor="alice"):
    return MdCGSecure(root, principal=Principal(tenant="t1", actor=actor, role=role,
                                                clearance=clearance, can_admin=admin),
                      master_key=KEK)


def _ledger(root):
    p = os.path.join(root, C.LOG_FILE)
    if not os.path.exists(p):
        return []
    with io.open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _raw(root):
    p = os.path.join(root, C.LOG_FILE)
    return io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def g1():
    """private 声明 → 台账无原文、redacted=true、sensitivity=private；判据数值保留。"""
    root = _tmp()
    try:
        cg = _os(root)
        r = cg.add("i298_p1", CARD % (MARK_FN, MARK, "50mg", MARK_NEG),
                   layer="knowledge", sensitivity="private", consistency=True)
        _check("G1a private 写入成功", r == "i298_p1", r)
        raw = _raw(root)
        _check("G1b 台账不含生效条件原文", MARK not in raw)
        _check("G1c 台账不含不适用条件原文", MARK_NEG not in raw)
        _check("G1d 台账不含功能名原文", MARK_FN not in raw)
        rec = _ledger(root)[-1]
        _check("G1e redacted=true", rec.get("redacted") is True, rec.get("redacted"))
        _check("G1f sensitivity=private", rec.get("sensitivity") == "private")
        _check("G1g pos/neg 置空", rec.get("pos") == [] and rec.get("neg") == [])
        _check("G1h 判据数值保留（verdict/conflict_strength 仍在）",
               "verdict" in rec and "conflict_strength" in rec and "scanned" in rec)
        _check("G1i 节点本体加密（无明文 .md）",
               not any(MARK in io.open(os.path.join(dp, f), encoding="utf-8",
                                       errors="replace").read()
                       for dp, _d, fs in os.walk(root) for f in fs
                       if f.endswith(".md")))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g2():
    """check() 返回给调用方的回执仍带原文（去原文只作用于落盘副本）。"""
    root = _tmp()
    try:
        cg = _os(root)
        vd = cg.check_consistency(CARD % (MARK_FN, MARK, "50mg", MARK_NEG),
                                  layer="knowledge", sensitivity="private")
        _check("G2a 回执 pos 带原文", any(MARK in x for x in (vd.get("pos") or [])), vd.get("pos"))
        _check("G2b 回执 neg 带原文", any(MARK_NEG in x for x in (vd.get("neg") or [])))
        _check("G2c 回执不含 sensitivity/redacted 键",
               "sensitivity" not in vd and "redacted" not in vd,
               [k for k in vd if k in ("sensitivity", "redacted")])
        _check("G2d 落盘副本已去原文", MARK not in _raw(root))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g3():
    """读面收口（**独立于层①**）：手工植入带 sensitivity 键的**明文**记录——

    这正是层①覆盖不到的存量/夹缝形态（本仓升级前写下、或手改过的台账）。
    can_admin 原样返回；internal 令牌去原文；条数与 verdict 不变；
    internal 档记录不得被过度抹除。
    """
    root = _tmp()
    try:
        _os(root)
        p = os.path.join(root, C.LOG_FILE)
        rows = [
            {"t": 1.0, "verdict": "DEFER", "conflict_strength": 0.5,
             "sensitivity": "private", "pos": [MARK + " 明文条件"],
             "neg": [MARK_NEG + " 明文负条件"], "actor": "designer"},
            {"t": 2.0, "verdict": "ACCEPT", "conflict_strength": 0.0,
             "sensitivity": "internal", "pos": ["内档条件"], "neg": [], "actor": "bob"},
        ]
        with io.open(p, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        admin = _os(root).consistency_history(limit=50)
        low = _os(root, role="recorder", clearance="internal", admin=False,
                  actor="bob").consistency_history(limit=50)
        _check("G3a can_admin 读到原文（复核面不瞎）",
               any(MARK in json.dumps(r, ensure_ascii=False) for r in admin))
        _check("G3b internal 令牌读不到 private 记录原文",
               MARK not in json.dumps(low, ensure_ascii=False))
        _check("G3c internal 令牌仍读得到条数与 verdict",
               len(low) == len(admin) and
               [r.get("verdict") for r in low] == [r.get("verdict") for r in admin])
        _check("G3d internal 档记录不被过度抹除（仍带原文）",
               any("内档条件" in json.dumps(r, ensure_ascii=False) for r in low))
        _check("G3e 明文文件仍在盘上（读面过滤不改写历史文件，如实边界）",
               MARK in io.open(p, encoding="utf-8").read())
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g4():
    """internal 声明 → 台账照旧带原文（零变化面）。"""
    root = _tmp()
    try:
        cg = _os(root)
        cg.add("i298_i1", CARD % (MARK_FN, MARK, "50mg", MARK_NEG),
               layer="knowledge", sensitivity="internal", consistency=True)
        rec = _ledger(root)[-1]
        _check("G4a redacted=false", rec.get("redacted") is False, rec.get("redacted"))
        _check("G4b sensitivity=internal", rec.get("sensitivity") == "internal")
        _check("G4c pos 原样", any(MARK in x for x in (rec.get("pos") or [])), rec.get("pos"))
        _check("G4d neg 原样", any(MARK_NEG in x for x in (rec.get("neg") or [])))
        _check("G4e 未声明密级的默认档也是 internal",
               _os(root, role="recorder", clearance="internal", admin=False)
               .consistency_history(limit=1)[0].get("sensitivity") == "internal")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g5():
    """restricted 声明 → 同样去原文（错误处置标记也在密级面内）。"""
    root = _tmp()
    try:
        cg = _os(root, clearance="restricted")
        cg.add("i298_r1", CARD % (MARK_FN, MARK, "50mg", MARK_NEG),
               layer="knowledge", sensitivity="restricted", consistency=True)
        rec = _ledger(root)[-1]
        _check("G5a redacted=true", rec.get("redacted") is True, rec.get("redacted"))
        _check("G5b sensitivity=restricted", rec.get("sensitivity") == "restricted")
        _check("G5c 台账无原文", MARK not in _raw(root))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g6():
    """未声明的写入比对一个 private 既有节点 → 落账仍按 private 去原文。"""
    root = _tmp()
    try:
        cg = _os(root)
        a = cg.add("i298_old", CARD % ("既有功能", MARK, "50mg", MARK_NEG),
                   layer="knowledge", sensitivity="private", consistency=True)
        cg.add("i298_new", CARD % ("既有功能", MARK, "100mg", MARK_NEG),
               layer="knowledge", sensitivity="internal", consistency=True)
        rec = _ledger(root)[-1]
        _check("G6a 第二条落账 sensitivity 被既有节点抬到 private",
               rec.get("sensitivity") == "private", rec.get("sensitivity"))
        _check("G6b redacted=true", rec.get("redacted") is True)
        _check("G6c 台账无原文", MARK not in _raw(root))
        div = [c for c in (rec.get("conflicts") or [])
               if c.get("type") == "same_condition_divergence"]
        if div:
            cr = div[0].get("cond_routes") or {}
            _check("G6d only_existing_side 已去原文", cr.get("only_existing_side") == [], cr)
            _check("G6e slot 已去原文", div[0].get("slot") == "", div[0].get("slot"))
        else:
            print("  SKIP G6d/G6e 本次未产出分歧条目（verdict=%s）" % rec.get("verdict"))
            _SKIP.extend(["G6d", "G6e"])
        _check("G6f 声明 private 的既有节点 id 仍可审计",
               a in json.dumps(rec, ensure_ascii=False) or not div)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g7():
    """升级前写下、没有 sensitivity 键的旧记录：非 admin 去原文，admin 原样。"""
    root = _tmp()
    try:
        _os(root)
        legacy = {"t": 1.0, "layer": "knowledge", "verdict": "BLINDSPOT",
                  "reason": "既有节点均未声明条件：无法建立比对路径",
                  "conflict_strength": 0.0, "pos": [MARK + " 旧条件"],
                  "neg": [MARK_NEG + " 旧负条件"], "actor": "designer"}
        with io.open(os.path.join(root, C.LOG_FILE), "a", encoding="utf-8") as f:
            f.write(json.dumps(legacy, ensure_ascii=False) + "\n")
        admin = _os(root).consistency_history(limit=10)
        low = _os(root, role="recorder", clearance="internal", admin=False)\
            .consistency_history(limit=10)
        _check("G7a admin 读到旧记录原文",
               any(MARK in json.dumps(r, ensure_ascii=False) for r in admin))
        _check("G7b 非 admin 读旧记录已去原文（密级不可判 ⇒ fail-closed）",
               MARK not in json.dumps(low, ensure_ascii=False))
        _check("G7c 条数与 verdict 不变",
               len(low) == 1 and low[0].get("verdict") == "BLINDSPOT")
        _check("G7d 去原文后仍是合法记录（判据字段在）",
               "conflict_strength" in low[0] and "actor" in low[0])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g8():
    _check("G8a 声明值优先于无", C.ledger_level("private", None) == "private")
    _check("G8b 取最高档", C.ledger_level("internal", ["private"]) == "private")
    _check("G8c 全缺省回落 internal", C.ledger_level(None, None) == "internal")
    _check("G8d 非法值 fail-closed 最高档", C.ledger_level("bogus", None) == "secret")
    _check("G8e 大小写/空白归一", C.ledger_level(" PRIVATE ", None) == "private")
    _check("G8f restricted 在 private 之下",
           C.ledger_level("restricted", None) == "restricted"
           and C.ledger_level("private", ["restricted"]) == "private")
    import md_cg.security as S
    _check("G8g 序与 security.SENSITIVITY_ORDER 逐位同序",
           S.SENSITIVITY_ORDER == C._LEDGER_LEVELS)


def g9():
    src = {"pos": ["A"], "neg": ["B"], "conflicts": [
        {"pos_side": ["x"], "neg_side": ["y"], "slot": "S",
         "cond_routes": {"only_new_side": ["p"], "only_existing_side": ["q"], "c3": 0.5}}]}
    out = C.scrub_record(src)
    _check("G9a 副本已去原文", out["pos"] == [] and out["neg"] == []
           and out["conflicts"][0]["slot"] == ""
           and out["conflicts"][0]["cond_routes"]["only_existing_side"] == [])
    _check("G9b 判据数值保留", out["conflicts"][0]["cond_routes"]["c3"] == 0.5)
    _check("G9c 入参未被改动（纯副本）",
           src["pos"] == ["A"] and src["conflicts"][0]["slot"] == "S"
           and src["conflicts"][0]["cond_routes"]["only_existing_side"] == ["q"])
    _check("G9d 非字典入参原样返回", C.scrub_record(None) is None)


def g10():
    """声明值缺失、exclude 指向**已存在**的 private 节点 → 继承该节点密级（同一漏传族）。

    `writepipe` 的 `cg(op=write)` 动词面只透传 `a.get("sensitivity")`；未声明时
    （None）落账若按 internal，一条改写既有 private 节点的写入就会把新条件原文
    明文记进台账。故 check() 在声明缺失时查一次 exclude 的盘面密级。
    """
    root = _tmp()
    try:
        cg = _os(root)
        cg.add("i298_h1", CARD % (MARK_FN, MARK, "50mg", MARK_NEG),
               layer="knowledge", sensitivity="private", consistency=True)
        # 未声明密级地改写同一节点（#297 继承语义 ⇒ 盘面仍是 private）
        cg.add("i298_h1", CARD % (MARK_FN, MARK, "100mg", MARK_NEG),
               layer="knowledge", consistency=True)
        rec = _ledger(root)[-1]
        _check("G10a 落账 sensitivity 继承既有节点 private",
               rec.get("sensitivity") == "private", rec.get("sensitivity"))
        _check("G10b redacted=true", rec.get("redacted") is True)
        _check("G10c 台账无原文", MARK not in _raw(root))
        _check("G10d 节点密级未被降级（#297 继承语义未受影响）",
               (_os(root).get("i298_h1") or {}).get("frontmatter", {})
               .get("sensitivity") == "private")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def g11():
    """库内只有该节点自身、判定无冲突（allc 空）时，继承路径是**唯一**密级来源。

    g10 的既有节点同时也在冲突面里（`ledger_sens` 已能取到 private），
    故它盖不住「声明缺失 ⇒ 继承」这条路径。本组刻意让 `allc` 为空
    （库内仅此一节点，`exclude` 把自身排除 ⇒ comparable=0 ⇒ BLINDSPOT），
    此时落账密级只能来自 `exclude` 指向的既有节点。
    """
    root = _tmp()
    try:
        cg = _os(root)
        cg.add("i298_j1", CARD % (MARK_FN, MARK, "50mg", MARK_NEG),
               layer="knowledge", sensitivity="private", consistency=True)
        # 走 `writepipe._gate_consistency` 的同形调用：直接 consistency.check，
        # `sensitivity` 是**调用方原始声明**（缺省 None），`exclude` 指向既有节点。
        # （`MdCGSecure.add` 那条路传的是 #297 归一后的值，盖不住本路径。）
        vd = C.check(cg, CARD % (MARK_FN, MARK, "100mg", MARK_NEG),
                     layer="knowledge", exclude="i298_j1", sensitivity=None)
        rec = _ledger(root)[-1]
        _check("G11a 无冲突（allc 空）确实成立",
               not rec.get("conflicts") and rec.get("verdict") in
               ("BLINDSPOT", "ACCEPT"), rec.get("verdict"))
        _check("G11b 回执 pos 有内容（本组非空转：红不红有可观测面）",
               bool(vd.get("pos")), vd.get("pos"))
        _check("G11c 落账 sensitivity 继承 private",
               rec.get("sensitivity") == "private", rec.get("sensitivity"))
        _check("G11d redacted=true", rec.get("redacted") is True)
        _check("G11e 台账无原文", MARK not in _raw(root))
    finally:
        shutil.rmtree(root, ignore_errors=True)


GROUPS = (g1, g2, g3, g4, g5, g6, g7, g8, g9, g10, g11)

MUTS = [
    ("M1 落盘不去原文（退回 log(cg, rec)）", "md_cg/consistency.py",
     "        _rec = scrub_record(rec) if _redact else dict(rec)",
     "        _rec = dict(rec)"),
    ("M2 密级恒 internal（永不判红）", "md_cg/consistency.py",
     '        _redact = bool(_lr is not None and _lr > _LEDGER_LEVELS.index("internal"))',
     "        _redact = False"),
    ("M3 读面不过滤（覆写退化）", "md_cg/mdcos.py",
     "        if self.principal.can_admin:\r\n            return recs",
     "        if True:\r\n            return recs"),
    ("M4 既有节点侧密级不进面", "md_cg/consistency.py",
     '               {c.get("with") for c in allc if isinstance(c, dict)}]',
     "               []]"),
    ("M5 声明值缺失时不继承既有节点密级", "md_cg/consistency.py",
     "    if not sensitivity and exclude:",
     "    if False and exclude:"),
]


def _run_quiet():
    """**子进程**重跑本守卫，返回失败判据名列表。

    必须子进程：本模块在导入期已 `from md_cg import consistency as C`，
    同进程 `del sys.modules[...]` 只让**新**导入者拿到变异后的模块，
    本模块手里的 `C` / `MdCGSecure` 仍是旧对象——变异对同进程无效
    （首轮实测 5/5 BAD 即此因）。子进程重跑才是真隔离。
    """
    p = subprocess.run([sys.executable, "-X", "utf8", "-m", MODULE],
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    out = (p.stdout or "") + (p.stderr or "")
    return [l.strip()[5:] for l in out.splitlines() if l.strip().startswith("FAIL ")]


def mutate():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backups = {}
    for _n, rel, _o, _x in MUTS:
        p = os.path.join(root, rel)
        with io.open(p, encoding="utf-8", newline="") as f:
            backups[p] = f.read()
    bad = []
    for name, rel, old, new in MUTS:
        p = os.path.join(root, rel)
        src = backups[p]
        if src.count(old) != 1:
            print("  ANCHOR-AMBIGUOUS/MISS %s（命中 %d 处）" % (name, src.count(old)))
            bad.append(name)
            continue
        try:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(src.replace(old, new, 1))
            out = _run_quiet()
            print("  %-4s %-34s 红项=%-3d %s" % ("OK" if out else "BAD", name, len(out),
                                                ("；".join(out[:3])[:110])))
            if not out:
                bad.append(name)
        finally:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(backups[p])
    print()
    print("定点变异自证：%s" % ("PASS（每处判据都被打红）" if not bad else "FAIL -- " + "、".join(bad)))
    return 0 if not bad else 1


def main():
    if "--mutate" in sys.argv:
        return mutate()
    print("issue #298 守卫：冲突台账密级面")
    for fn in GROUPS:
        fn()
    print()
    print("===== issue298 守卫：%d 通过，%d 失败，%d 跳过 =====" %
          (len(_PASS), len(_FAIL), len(_SKIP)))
    if _FAIL:
        print("失败：" + "、".join(_FAIL))
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
