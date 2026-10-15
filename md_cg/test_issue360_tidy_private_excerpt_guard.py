# -*- coding: utf-8 -*-
"""tidy 私有摘录降密级闸守卫（issue #360；#304 自述「已知遗留①」立案）。

【守什么】
md_cg/writelimit.py 的 tidy_contextual 成员循环此前把同组 private 成员
**解密后的正文前 48 字明文**追加进组内最早的保留节点（密级沿用保留节点的
internal）——internal 身份直接 get 那条 private 节点得 None，但读保留节点
就能看到内容；sustain 缺省 auto_tidy=True（sustain.py AUTO_DEFAULTS /
_tick_tidy），无需人工触发。#304（#190 修复 PR）正文自述该遗留但未立案。

复核成立（改前实测，见本守卫 git 历史与 delivery 读数；改前
writelimit.py sha256=3e8eb31f18fb3f434bb8cb3516448cf8ea5894d227c1c0ae55ccd014ae1cfed4）：
三条同签名 contextual 节点（n3 为 private 含口令 PAIR-360-S3CRET）→
  tidy applied keep=n1 converged=2
  keep n1 sensitivity=internal、正文与**盘上文件**均含口令明文
  guest 经 n1 可读出口令（guest get n3=None 不变）

修法（writelimit.py，判据同 #148 家族单点）：成员循环先过
security.merge_downgrades（target=保留节点密级、incoming=成员密级），命中即
**整体跳过该成员**——不写摘录、不降权、不计数（fail-closed）；留痕
skipped_private（返回体顶层计数 + applied 各项组内计数）；converged /
merge_count 只数真并入者；组内全被跳过时保留节点不写盘（防 #190 的每轮
重写在 private 组上复活）。

判据：
  G1 private 成员摘录不进保留节点：keep 正文与盘上字节均无口令明文，
     guest 经 keep 读不到口令。
  G2 防过修：internal 成员的摘录照常并入 keep；converged / applied_count /
     merge_count / keep 整理段成员行数 / 被降权成员数 五者相等（如实计数，
     不断言具体值——变异态下它们同样自洽，防把「诚实计数」写成魔法数）。
  G3 guest 对 private 节点本身的隔离不变：guest get(n3) 得 None；
     属主（designer）仍读得到 n3 且正文完整（隔离未被破坏性修复）。
  G4 跳过留痕 + 跳过即不收编：返回体 skipped_private==1、applied 项
     skipped_private==1；被跳过的 n3 importance 不变、无 tidy:converged、
     无 converged 状态、正文逐字不变；tidy_contextual 源码在位引用
     merge_downgrades（闸未被摘）。
  G5 幂等补充（多 private 成员组，防 #190 每轮重写复活）：1 internal keep +
     1 internal 成员 + 3 private 成员 ⇒ 轮 1 只并 internal；轮 2/3 全树
     逐字节不变、applied 空、skipped_private 仍如实上报（不静默）、
     keep merge_count 冻结。
  G6 元守卫（轻量）：#148 家族已知「拼接他节点正文」写点（converge_into /
     reinforce；tidy keep 即 G4.4；branches.merge 另有专守卫）落盘前的
     merge_downgrades 闸在位——防家族判据被后续改动无声摘除。

变异自证（--mutate）：把 merge_downgrades 闸短路（if False and …）⇒ 红组
恰为 G1/G4（题面口径）＋G5 的留痕与泄漏读数（G5 的组级判据天然随闸失效，
G5.2 写幂等两向皆绿）；G2（诚实计数自洽）/G3（隔离与本闸无关）仍绿；恢复后
全绿。

运行：python -X utf8 -m md_cg.test_issue360_tidy_private_excerpt_guard
      python -X utf8 -m md_cg.test_issue360_tidy_private_excerpt_guard --mutate
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
import io
import os
import shutil
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import writelimit                          # noqa: E402
from md_cg.mdcos import MdCGSecure                    # noqa: E402
from md_cg.security import Principal                  # noqa: E402

WL = os.path.join(_REPO, "md_cg", "writelimit.py")
MARK = "PAIR-360-S3CRET"

PASS = 0
FAIL = 0
FAILS = []


def check(cid, cond, detail=""):
    global PASS, FAIL
    cid = cid.split()[0]
    if cond:
        PASS += 1
        print("  ok   %s" % cid)
    else:
        FAIL += 1
        FAILS.append(cid)
        print("  FAIL %s  %s" % (cid, detail))


class _Box:
    """一次性沙箱：独立 root/aux/master key，退出时清理（#148 同款口径）。"""

    def __init__(self, tag):
        self.dir = tempfile.mkdtemp(prefix="iss360_%s_" % tag)

    def __enter__(self):
        os.environ["MDCG_ROOT"] = os.path.join(self.dir, "cgroot")
        os.environ["MDCG_AUX_ROOT"] = os.path.join(self.dir, "auxstore")
        os.environ.setdefault("MDCG_MASTER_KEY", "00" * 32)
        os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
        return os.environ["MDCG_ROOT"]

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


def _owner(root):
    return MdCGSecure(root, principal=Principal(
        actor="owner", clearance="private", can_write=True, can_admin=True,
        role="designer", session="s1"))


def _guest(root):
    return MdCGSecure(root, principal=Principal(
        actor="visitor", clearance="internal", can_write=False,
        role="guest"))


def _seed_r2(cg):
    """r2 复现场景：三条同签名 contextual 节点，n3 为 private 含口令。"""
    cg.add("n1", "# 功能名：批次1收官记忆\n\n常规巡检内容 AAAA",
           layer="contextual", sensitivity="internal", importance=0.6)
    cg.add("n2", "# 功能名：批次2收官记忆\n\n常规巡检内容 BBBB",
           layer="contextual", sensitivity="internal", importance=0.6)
    cg.add("n3", "# 功能名：批次3收官记忆\n\n口令%s 私有巡检备注" % MARK,
           layer="contextual", sensitivity="private", importance=0.6)


def _fm(cg, nid):
    return (cg.get(nid) or {}).get("frontmatter") or {}


def _body(cg, nid):
    return (cg.get(nid) or {}).get("content") or ""


def _tree(root):
    out = {}
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            out[os.path.relpath(p, root).replace("\\", "/")] = \
                hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def _run_r2(tag):
    """跑一遍 r2 场景，返回读数 dict（keep 即 n1：组内最早）。"""
    with _Box(tag) as root:
        cg = _owner(root)
        _seed_r2(cg)
        r = writelimit.tidy_contextual(cg, apply=True, min_group=3)
        guest = _guest(root)
        entry = (r.get("applied") or [{}])[0]
        keep_disk = b""
        kn = cg.get("n1")
        if kn:
            keep_disk = open(os.path.join(root, kn["path"]), "rb").read()
        n3fm = _fm(cg, "n3")
        out = {
            "keep": entry.get("keep"),
            "converged": entry.get("converged"),
            "entry_skipped": entry.get("skipped_private", 0),
            "top_skipped": r.get("skipped_private", 0),
            "applied_count": r.get("applied_count", 0),
            "keep_sens": _fm(cg, "n1").get("sensitivity"),
            "keep_body_has_mark": MARK in _body(cg, "n1"),
            "keep_disk_has_mark": MARK.encode("utf-8") in keep_disk,
            "n2_line_in_keep": "- n2 " in _body(cg, "n1"),
            "n3_line_in_keep": "- n3 " in _body(cg, "n1"),
            "demoted": sorted(n for n in ("n2", "n3")
                              if "tidy:converged" in (_fm(cg, n).get("tags")
                                                      or [])),
            "merge_count": int(_fm(cg, "n1").get("merge_count") or 0),
            "guest_keep_sees_mark": bool(guest.get("n1"))
            and MARK in ((guest.get("n1") or {}).get("content") or ""),
            "guest_n3": guest.get("n3"),
            "owner_n3_ok": bool(cg.get("n3"))
            and MARK in _body(cg, "n3"),
            "n3_importance": n3fm.get("importance"),
            "n3_tags": list(n3fm.get("tags") or []),
            "n3_state": n3fm.get("lifecycle_state"),
            "n3_body_intact": _body(cg, "n3")
            == "# 功能名：批次3收官记忆\n\n口令%s 私有巡检备注" % MARK,
        }
        cg.close()
        guest.close()
        return out


def g1(m):
    print("== G1 private 成员摘录不进保留节点 ==")
    check("G1.1 keep（n1，internal）正文不含口令明文",
          m["keep"] == "n1" and m["keep_sens"] == "internal"
          and m["keep_body_has_mark"] is False,
          "keep=%s sens=%s body_has_mark=%s" % (
              m["keep"], m["keep_sens"], m["keep_body_has_mark"]))
    check("G1.2 ★ keep 盘上文件字节不含口令明文（防内存态假绿）",
          m["keep_disk_has_mark"] is False, str(m["keep_disk_has_mark"]))
    check("G1.3 ★ guest 经 keep 读不到口令", m["guest_keep_sees_mark"] is False,
          str(m["guest_keep_sees_mark"]))


def g2(m):
    print("== G2 防过修：internal 成员照常并入，计数如实 ==")
    n_lines = int(m["n2_line_in_keep"]) + int(m["n3_line_in_keep"])
    check("G2.1 internal 成员 n2 的摘录照常并入 keep",
          m["n2_line_in_keep"] is True, str(m["n2_line_in_keep"]))
    check("G2.2 ★ converged/applied_count/merge_count/成员行数/降权数 五者相等"
          "（如实计数：真并入几条就报几条）",
          m["converged"] == m["applied_count"] == m["merge_count"]
          == n_lines == len(m["demoted"]),
          "converged=%s applied_count=%s merge_count=%s lines=%s demoted=%s"
          % (m["converged"], m["applied_count"], m["merge_count"], n_lines,
             m["demoted"]))
    check("G2.3 被并入的成员真的被降权收编（tidy 正常行为不变）",
          "n2" in m["demoted"], str(m["demoted"]))


def g3(m):
    print("== G3 guest 对 private 节点本身的隔离不变 ==")
    check("G3.1 ★ guest get(n3) 得 None（读隔离不因本修复改变）",
          m["guest_n3"] is None, repr(m["guest_n3"])[:80])
    check("G3.2 属主仍可读 n3 且正文完整（未破坏性修复）",
          m["owner_n3_ok"] is True, str(m["owner_n3_ok"]))


def g4(m):
    print("== G4 跳过留痕 + 跳过即不收编 ==")
    check("G4.1 ★ 返回体 skipped_private==1（不静默）",
          m["top_skipped"] == 1, str(m["top_skipped"]))
    check("G4.2 applied 项 skipped_private==1（组内留痕）",
          m["entry_skipped"] == 1, str(m["entry_skipped"]))
    check("G4.3 ★ 被跳过的 n3 不被收编：importance 不变、无 tidy:converged、"
          "lifecycle_state 未推进到 converged、正文逐字不变",
          m["n3_importance"] == 0.6 and m["n3_tags"] == []
          and m["n3_state"] != "converged" and m["n3_body_intact"] is True
          and m["n3_line_in_keep"] is False,
          "imp=%s tags=%s state=%s body_intact=%s line=%s" % (
              m["n3_importance"], m["n3_tags"], m["n3_state"],
              m["n3_body_intact"], m["n3_line_in_keep"]))
    src = inspect.getsource(writelimit.tidy_contextual)
    check("G4.4 tidy_contextual 源码在位引用 merge_downgrades（闸未被摘）",
          "merge_downgrades" in src, "absent")


def g5():
    print("== G5 幂等补充：多 private 成员组不再每轮重写（防 #190 复活） ==")
    with _Box("g5") as root:
        cg = _owner(root)
        _seed_r2(cg)
        for i in (4, 5):
            cg.add("n%d" % i, "# 功能名：批次%d收官记忆\n\n口令%s-%d 私有巡检备注"
                   % (i, MARK, i),
                   layer="contextual", sensitivity="private", importance=0.6)
        r1 = writelimit.tidy_contextual(cg, apply=True, min_group=3)
        t1 = _tree(root)
        mc1 = int(_fm(cg, "n1").get("merge_count") or 0)
        check("G5.1 轮 1 只并 internal 成员（converged==1、skipped_private==3）",
              r1.get("applied_count") == 1
              and r1.get("skipped_private") == 3,
              "applied_count=%s skipped=%s" % (r1.get("applied_count"),
                                               r1.get("skipped_private")))
        r2 = writelimit.tidy_contextual(cg, apply=True, min_group=3)
        t2 = _tree(root)
        r3 = writelimit.tidy_contextual(cg, apply=True, min_group=3)
        t3 = _tree(root)
        mc3 = int(_fm(cg, "n1").get("merge_count") or 0)
        check("G5.2 ★ 轮 2/3 全树逐字节不变（private 成员不标记 ⇒ 组会再进 "
              "planned，但全跳过 ⇒ 不写盘）",
              t1 == t2 and t2 == t3,
              "r2 变=%s r3 变=%s" % (
                  sorted(k for k in set(t1) | set(t2) if t1.get(k) != t2.get(k)),
                  sorted(k for k in set(t2) | set(t3) if t2.get(k) != t3.get(k))))
        check("G5.3 轮 2/3 applied 空、skipped_private 仍如实上报（不静默）、"
              "keep merge_count 冻结",
              r2.get("applied") == [] and r3.get("applied") == []
              and r2.get("skipped_private") == 3
              and r3.get("skipped_private") == 3 and mc3 == mc1,
              "r2.applied=%s r2.skipped=%s r3.skipped=%s mc=%s→%s"
              % (r2.get("applied"), r2.get("skipped_private"),
                 r3.get("skipped_private"), mc1, mc3))
        check("G5.4 keep 永不出口令明文（多 private 组同样不泄漏）",
              MARK not in _body(cg, "n1"), "leaked")
        cg.close()


def g6():
    print("== G6 元守卫（轻量）：#148 家族已知拼接写点的闸在位 ==")
    # 全仓 _write_node 落点的人工枚举（2026-10-15，报告随本 PR）：
    # 「拼接他节点正文」的写点共 4 处——converge_into / reinforce /
    # tidy keep（本修复）/ branches.merge；其余 _write_node 落点均为
    # 「本节点正文原样回写」（backfill/freshness/weights/lifecycle/protect/
    # scrub/trust/subgraph/rollback/sleep 影子重放等）或已按敏感度派生新建
    # （consolidate 概念归纳 derive_sensitivity fail-closed）。本判据只钉
    # 前三处（同仓可 import 面）；branches.merge 由 test_branches_sensitivity /
    # test_issue315 守卫钉。**未接闸的相邻面**（mdcos 评审 merge 分支拼提案
    # 正文入既有节点，仅 principal 层闸+protect，无 merge_downgrades）在报告
    # 登记，不在 #360 范围内修。
    src_ci = inspect.getsource(writelimit.converge_into)
    check("G6.1 converge_into 落盘前过 merge_downgrades（#148 闸在位）",
          "merge_downgrades" in src_ci, "absent")
    from md_cg import forgetting
    src_rf = inspect.getsource(forgetting.reinforce)
    check("G6.2 reinforce 落盘前过 merge_downgrades（#148 闸在位）",
          "merge_downgrades" in src_rf, "absent")


_GROUPS = ("G1", "G2", "G3", "G4", "G5", "G6")


def _run_all():
    global PASS, FAIL
    PASS = FAIL = 0
    FAILS.clear()
    m = _run_r2("main")
    print("r2 读数：%s" % m)
    g1(m)
    g2(m)
    g3(m)
    g4(m)
    try:
        g5()
    except Exception as exc:                            # noqa: BLE001
        print("  断言组 g5 抛异常：%s" % exc)
        FAILS.append("G5")
        FAIL += 1
    try:
        g6()
    except Exception as exc:                            # noqa: BLE001
        print("  断言组 g6 抛异常：%s" % exc)
        FAILS.append("G6")
        FAIL += 1
    return list(FAILS)


def main():
    print("=== issue #360 tidy 私有摘录降密级闸守卫 ===")
    print("writelimit.py sha256=%s" % hashlib.sha256(
        open(WL, "rb").read()).hexdigest())
    bad = _run_all()
    print()
    print("issue #360 守卫：通过 %d / 失败 %d" % (PASS, FAIL))
    if bad:
        print("失败项：" + "、".join(bad))
    return 1 if bad else 0


# ---------------------------------------------------------------- 定点变异自证

# 唯一变异：merge_downgrades 闸被短路（#360 病象回归）。
# 期望红组：G1（摘录/盘上/guest 三路泄漏读数）+ G4（留痕缺失、n3 被收编）
# ——题面口径；另加 G5 的组级红（G5.1/G5.3 留痕读数、G5.4 多 private 组泄漏
# 读数天然随闸失效；G5.2 写幂等两向皆绿——变异态下 private 成员被标记收敛，
# 轮 2/3 本就安静）。G2（诚实计数在变异态下同样自洽：2 条全并入报 2）、
# G3（guest 对 n3 的隔离与本闸无关）必须仍绿。
_MUT_ANCHOR = ("            if _merge_downgrades(keep_sens, "
               "mfm.get(\"sensitivity\")):\n")
_MUT_REPL = ("            if False and _merge_downgrades(keep_sens, "
             "mfm.get(\"sensitivity\")):\n")
_WANT_RED = ("G1", "G4", "G5")


def _reload():
    import md_cg.writelimit as _w
    try:
        cache = importlib.util.cache_from_source(_w.__file__)
        if os.path.exists(cache):
            os.remove(cache)
    except Exception:                                   # noqa: BLE001
        pass
    importlib.invalidate_caches()
    importlib.reload(_w)
    globals()["writelimit"] = _w


def _live_ok():
    """盘上源与内存模块一致（防空转变异，#190 同款）。"""
    with io.open(WL, encoding="utf-8", newline="") as f:
        src = f.read()
    ns = {"__name__": "md_cg._i360live", "__package__": "md_cg",
          "__file__": WL}
    try:
        exec(compile(src, WL, "exec"), ns)              # noqa: S102
    except Exception as exc:                            # noqa: BLE001
        return "COMPILE-FAIL:%s" % exc
    for name, obj in ns.items():
        cur = getattr(writelimit, name, None)
        if (callable(obj) and callable(cur)
                and getattr(obj, "__code__", None) is not None
                and getattr(cur, "__code__", None) is not None
                and obj.__code__.co_code != cur.__code__.co_code):
            return "STALE:%s" % name
    return ""


def _mutate():
    with io.open(WL, encoding="utf-8", newline="") as f:
        pristine = f.read()
    # 工作树在本仓 autocrlf=true 下是 CRLF、CI/Linux 检出可能是 LF——锚点先按
    # 盘上实际行尾归一再做在位检查（#190 守卫同款 NL 技巧）。
    NL = "\r\n" if "\r\n" in pristine else "\n"
    anchor = _MUT_ANCHOR.replace("\n", NL)
    repl = _MUT_REPL.replace("\n", NL)
    if anchor not in pristine:
        print("ANCHOR-MISS：找不到 merge_downgrades 闸锚点（源已被改？）")
        return 2
    bad = []
    try:
        with io.open(WL, "w", encoding="utf-8", newline="") as f:
            f.write(pristine.replace(anchor, repl, 1))
        _reload()
        stale = _live_ok()
        if stale:
            print("LIVE-CHECK-FAIL：%s（变异未进入内存，读数不可信）" % stale)
            return 1
        print("变异：merge_downgrades 闸短路（if False and …）")
        reds = _run_all()
        # 子判据 id（G1.1…）归并为组前缀再比对（守卫读数粒度是子判据）。
        got = sorted({cid.split(".")[0] for cid in reds})
        want = sorted(_WANT_RED)
        print("  期望红组=%s" % ",".join(want))
        print("  实测红组=%s" % (",".join(got) or "（无）"))
        print("  绿组=%s（G2/G3 必须在内）" % (
            ",".join(g for g in _GROUPS if g not in got) or "（无）"))
        ok = got == want and "G2" not in got and "G3" not in got
        print("  %s" % ("OK 恰好命中" if ok else "BAD 红项集合不符"))
        if not ok:
            bad.append("mutation")
    finally:
        with io.open(WL, "w", encoding="utf-8", newline="") as f:
            f.write(pristine)
        with io.open(WL, encoding="utf-8", newline="") as f:
            if f.read() != pristine:
                print("RESTORE-FAILED：writelimit.py 未恢复原样")
                bad.append("restore")
        _reload()
    if bad:
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print("定点变异自证：PASS（闸短路打红 G1/G4/G5，G2/G3 仍绿；源已恢复）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
