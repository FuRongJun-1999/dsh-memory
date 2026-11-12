# -*- coding: utf-8 -*-
"""证据层 node_id 路径穿越守卫（issue #277）。

【守什么】
#277 报：MDCG_NODE_ID（或 node_id(explicit=...)）零校验，而 publish_card
把它直接拼进 os.path.join(peers_dir(swarm), nid + ".json") ⇒ **任意文件写**，
且落点可越出 swarm 目录（实测 "../../../evil_pwned"）。

【修法】
复用仓内既有范式（#147 的「汇点兜底」+ mdcos._restore_id_ok 的「先拦后读」）：
  · 入口 node_id() **先拦后返回**——非法即 EvidenceError，不返回可拼路径的值；
  · 汇点 publish_card() **再拦一次** + realpath 包含性判定——即使调用方绕过
    node_id() 直接构造 card，也 fail-closed；
  · 判据与写面 MdCG.add() 的 P0-1 白名单**同源**（同一 _NODE_ID_RE、同一
    ".." 禁令、同一 _NODE_ID_FORBIDDEN），不是第二份判据。

判据：
  P1  ".." 形态一律拒（../x、..反斜杠evil、a/../../b、has%2e%2e 等）
  P1b 环境变量腿：MDCG_NODE_ID 同样被拦
  P2  绝对路径 / 盘符 / UNC 拒
  P3  含分隔符（斜杠/反斜杠）拒
  P4  保留字（None / null）拒——空语义值的字符串化污染形态
  P5  超长（>128）拒；非字符串拒
  P6  **反向**：合法 id（字母数字 _ . @ - 与中文、逗号）行为不变
  P7  **端到端**：恶意 MDCG_NODE_ID 下 publish_card 抛 EvidenceError，
      且**盘上不产生任何越界文件**（真写盘腿，不是只看返回值）
  P8  **汇点兜底**：绕过 node_id()（直接构造 card）也拒
  P9  **缺陷曾真实存在**：从 git HEAD 取**修复前**源码逐字核对原形 ——
      证明本守卫守的是真缺陷，不是自证同义反复
  P10 判据同源：_node_id_error 的通过集 == MdCG.add() 白名单的通过集

运行：python -X utf8 -m md_cg.test_issue277_node_id_traversal
      python -X utf8 -m md_cg.test_issue277_node_id_traversal --mutate

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红。

沙箱纪律：swarm 根落守卫临时目录，绝不碰在役库与 ~/.mdcg。
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile

from . import evidence as E
from .evidence import EvidenceError

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

_PASS: list = []
_FAIL: list = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  -> " + str(extra)) if (extra and not cond) else ""))


def _raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return "OK"
    except EvidenceError:
        return "EvidenceError"
    except Exception as exc:                                  # noqa: BLE001
        return type(exc).__name__


def _envname():
    return getattr(E, "NODE_ID_ENV", "MDCG_NODE_ID")


_BAD = (
    "../../../evil_pwned",
    "../evil",
    r"..\evil",
    "a/../../b",
    "..",
    "a..b/../c",
    "/etc/passwd",
    r"C:\Windows\evil",
    r"\\server\share\evil",
    "sub/dir",
    r"sub\dir",
    "has:colon",
    "has%2e%2e",
    "None",
    "null",
    "x" * 129,
)


def p1():
    print("== P1/P2/P3/P4/P5 非法形态一律拒 ==")
    for bad in _BAD:
        r = _raises(E.node_id, "R", explicit=bad)
        ok(r == "EvidenceError", "P 拒 node_id(explicit=%r)" % (bad[:34],), r)


def p1b():
    print("== P1b 环境变量腿：MDCG_NODE_ID 同样被拦 ==")
    k = _envname()
    old = os.environ.get(k)
    try:
        os.environ[k] = "../../../evil_env"
        r = _raises(E.node_id, "R")
        ok(r == "EvidenceError", "P1b MDCG_NODE_ID 穿越形态被拦", r)
        os.environ[k] = "node-legit"
        ok(E.node_id("R") == "node-legit", "P1b2 合法环境值仍正常返回")
    finally:
        if old is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = old


def p5b():
    print("== P5b 非字符串拒 ==")
    for v in (123, 1.5, True, ["x"], {"a": 1}, ("x",)):
        r = _raises(E.node_id, "R", explicit=v)
        ok(r == "EvidenceError", "P5b 拒 node_id(explicit=%r)" % (v,), r)


def p6():
    print("== P6 反向：合法 id 行为不变 ==")
    for good in ("node-0123456789ab", "mem_1791909293720_48076f",
                 "中文节点", "a.b@c", "a,b", "a-b_c"):
        try:
            got = E.node_id("R", explicit=good)
        except Exception as exc:                              # noqa: BLE001
            got = "RAISED:%s" % type(exc).__name__
        ok(got == good, "P6 合法 id 原样返回：%r" % (good,), got)


def _purge(paths):
    """清掉上一轮（或历史跑）可能残留的同名文件——判据只认**本次**是否写出。"""
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def _outside_candidates(tmp):
    d1 = os.path.dirname(tmp)
    d2 = os.path.dirname(d1)
    return [os.path.join(tmp, n) for n in ("evil_pwned.json", "evil_bypass.json")] + \
           [os.path.join(d1, n) for n in ("evil_pwned.json", "evil_bypass.json")] + \
           [os.path.join(d2, n) for n in ("evil_pwned.json", "evil_bypass.json")]


def p7():
    print("== P7 端到端：恶意 MDCG_NODE_ID 下不产生越界文件 ==")
    tmp = tempfile.mkdtemp(prefix="p277_")
    swarm = os.path.join(tmp, "swarm")
    os.makedirs(swarm, exist_ok=True)
    _purge(_outside_candidates(tmp))
    k = _envname()
    old = os.environ.get(k)
    try:
        os.environ[k] = "../../../evil_pwned"
        r = _raises(E.publish_card, "R", swarm=swarm)
        ok(r == "EvidenceError", "P7a publish_card 抛 EvidenceError", r)
    finally:
        if old is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = old
    hits = [p for p in _outside_candidates(tmp) if os.path.exists(p)]
    ok(not hits, "P7b 盘上无越界文件（真写盘腿）", hits[:3])
    inner = []
    for dp, _dn, fns in os.walk(swarm):
        inner += [os.path.join(dp, f) for f in fns]
    ok(inner == [], "P7c swarm 内无任何落盘", inner[:4])


def p8():
    print("== P8 汇点兜底：绕过 node_id() 也拒 ==")
    tmp = tempfile.mkdtemp(prefix="p277b_")
    swarm = os.path.join(tmp, "swarm")
    os.makedirs(swarm, exist_ok=True)
    _purge(_outside_candidates(tmp))
    orig = E.card
    try:
        E.card = lambda *a, **kw: {"node_id": "../../../evil_bypass"}
        r = _raises(E.publish_card, "R", swarm=swarm)
    finally:
        E.card = orig
    ok(r == "EvidenceError", "P8a 汇点兜底拦下绕过 node_id() 的恶意 card", r)
    hits = [p for p in _outside_candidates(tmp) if os.path.exists(p)]
    ok(not hits, "P8b 盘上无越界文件（兜底真生效）", hits[:3])


def _prepatch_src():
    """取**引入本修复的那个提交**的父版本 evidence.py。

    ★ 不能用 HEAD：本修复提交后 HEAD **就是**修复本身，"HEAD 无 _node_id_error"
      会恒假（实测：提交后全量门禁里本守卫必红，而提交前独立跑是绿的）。
      改为用 git log -S 定位引入提交，再看它的父提交——该断言因此**跨提交稳定**。
    """
    def _g(*a):
        return subprocess.run(list(a), cwd=_REPO, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
    try:
        lg = _g("git", "log", "-S_node_id_error", "--format=%H", "--",
                "md_cg/evidence.py")
    except Exception as exc:                                  # noqa: BLE001
        return None, "git 调用失败：%r" % (exc,)
    if lg.returncode != 0:
        return None, "git log rc=%s" % lg.returncode
    shas = [x.strip() for x in (lg.stdout or "").splitlines() if x.strip()]
    if not shas:
        return None, "git log -S 未找到引入提交（历史过浅？）"
    intro = shas[-1]                      # 最早那次引入
    src = _g("git", "show", intro + "^:md_cg/evidence.py")
    if src.returncode != 0:
        return None, "git show %s^ rc=%s（根提交？）" % (intro[:8], src.returncode)
    return src.stdout, ""


def p9():
    print("== P9 缺陷曾真实存在（核对修复前源码原形）==")
    t, err = _prepatch_src()
    if t is None:
        ok(False, "P9 取修复前源失败：%s" % err)
        return
    ok("_node_id_error" not in t,
       "P9a 引入提交的**父版本**无 _node_id_error —— 判据由本修复引入")
    ok("explicit or os.environ.get(NODE_ID_ENV)" in t,
       "P9b 修复前的 node_id() 确为「只 strip、零校验」原形")
    ok("c[\"node_id\"] + \".json\"" in t,
       "P9c 修复前的 publish_card 确为「直接拼路径」原形")
    ok("os.path.realpath(p)" not in t,
       "P9d 修复前无 realpath 包含性判定 —— 越界无第二道防线")


def p9b():
    print("== P9b 空串语义：= 未提供 ⇒ 回落派生（不是穿越形态）==")
    got = E.node_id("R", explicit="")
    ok(isinstance(got, str) and got.startswith("node-"),
       "P9b explicit='' ⇒ 回落派生 node-<hex>（旧行为保持）", got)


def p11():
    print("== P11 汇点纵深防御：两道独立防线都在场 ==")
    with io.open(os.path.join(_REPO, "md_cg", "evidence.py"),
                 encoding="utf-8", errors="replace") as f:
        src = f.read()
    # **必须收窄到 publish_card 函数体**：write_pack 里有逐字同形的
    # realpath 包含性判定（#147 引入），全文件 in 匹配会读到那一份而假绿。
    i0 = src.index("def publish_card(")
    i1 = src.index("def peers(")
    body = src[i0:i1]
    ok('_node_id_error(c.get("node_id"))' in body,
       "P11a 第一道：汇点白名单（同 add() 判据）")
    ok("os.path.realpath(p)" in body and "startswith(base + os.sep)" in body,
       "P11b 第二道：realpath 包含性判定")
    # 单去一道不足以转红 P8 —— 这正是「纵深」的含义，如实记录而非隐藏：
    # 变异 V2 必须同时去掉两道才转红；本组保证两道**都**在场。
    print("      注：单去任一道 P8 仍绿（另一道兜住）——V2 故须同时去掉两道")


def p10():
    print("== P10 判据同源：与写面 add() 白名单一致 ==")
    from .mdcg import _NODE_ID_RE, _NODE_ID_FORBIDDEN
    sample = ("node-abc", "mem_1_a", "中文", "a.b@c", "a,b", "a-b_c",
              "a/b", "..", "x" * 129, "None", "null", "a\b", "C:x")
    mism = []
    for s in sample:
        try:
            E.node_id("R", explicit=s)
            mine = True
        except Exception:                                     # noqa: BLE001
            mine = False
        theirs = bool(isinstance(s, str) and s and len(s) <= 128
                      and ".." not in s and s not in _NODE_ID_FORBIDDEN
                      and _NODE_ID_RE.match(s))
        if mine != theirs:
            mism.append((s[:20], mine, theirs))
    ok(not mism, "P10 通过集 == add() 白名单通过集（抽样 %d）" % len(sample), mism)


_GROUPS = (p1, p1b, p5b, p6, p7, p8, p9, p9b, p10, p11)


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                              # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-700:])
    return len(_FAIL)


def main() -> int:
    n = _run_groups()
    print("\n证据层 node_id 穿越守卫：%d 通过，%d 失败" % (len(_PASS), n))
    return 1 if n else 0


_MUTATIONS = (
    ('V1 去掉入口闸（node_id 恢复零校验）',
     '        err = _node_id_error(nid)',
     '        err = ""', 'P'),
    ('V2 去掉汇点白名单（第一道防线）',
     '    err = _node_id_error(c.get("node_id"))',
     '    err = ""', 'P11'),
    ('V5 去掉 realpath 包含性（第二道防线）',
     '    if real != base and not real.startswith(base + os.sep):',
     '    if False:', 'P11'),
    ('V3 放宽判据（去掉 .. 禁令）',
     '    if ".." in nid:',
     '    if False:', 'P'),
    ('V4 放宽判据（去掉字符白名单）',
     '    if not _NODE_ID_RE.match(nid):',
     '    if False:', 'P'),
)

def _reload():
    import importlib
    from . import evidence as _m
    importlib.reload(_m)
    globals()["E"] = _m


def _mutate() -> int:
    bad = []
    src_p = os.path.join(_REPO, "md_cg", "evidence.py")
    with io.open(src_p, encoding="utf-8", newline="") as f:
        pristine = f.read()
    # 前置自检：源码必须处于**未变异**态，否则上一轮变异没收干净，本轮判据无意义
    if "        err = _node_id_error(nid)" not in pristine:
        print("  SOURCE-ALREADY-MUTATED：evidence.py 入口闸缺失，请先恢复源码再跑 --mutate")
        return 1
    for name, anchor, repl, want in _MUTATIONS:
        with io.open(src_p, encoding="utf-8", newline="") as f:
            orig = f.read()
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        try:
            if a_ not in orig:
                print("  ANCHOR-MISS %s" % name)
                bad.append(name)
                continue
            with io.open(src_p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            _reload()
            _run_groups()
            reds = list(_FAIL)
            hit = any(r.startswith(want) for r in reds)
            print("  %-4s %-46s 红项=%-3d" % ("OK" if hit else "BAD", name, len(reds)))
            if not hit:
                bad.append(name)
        finally:
            # 从**开头备份**恢复（不是从本轮 orig——那会把上一轮的变异当成基线，
            # 一旦某轮恢复失败，变异态就会被后续每轮"恢复"成新常态）。
            with io.open(src_p, "w", encoding="utf-8", newline="") as f:
                f.write(pristine)
            with io.open(src_p, encoding="utf-8", newline="") as f:
                if f.read() != pristine:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
            _reload()
    if bad:
        print("\n定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print("\n定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
