# -*- coding: utf-8 -*-
"""signer.signers_file 的路径闸守卫（issue #279）。

【守什么】
#279 报：`signer.signers_file(path)` 对显式 path 零校验，任意路径直接
返回并被 `load_policies`/`save_policies` 当作策略文件读写——MCP 参数即可
指向任意 JSON 文件。

PR #316 值守复核实测（2bac760 旧形态）：任意目录 secret.json → ACCEPTED
（返回**原串**）；non-json .txt → ValueError（唯一真拦截）；无参缺省 →
ACCEPTED。静态复核：if 块 body 是单个 `pass`（无 raise/return），函数唯一
return 在末尾且返回原串而非 norm ⇒ 白名单比较对控制流零影响，是死代码——
「部分收窄，非关闭」。判据面也不够：`.json` 后缀挡不住
`<受信>/ok.json/../../x` 穿越，symlink/junction 指向任意目标仍通过。

修法（值守建议的最小改法，不做 risk-accept 妥协）：
  · 返回 **norm**（abspath 归一后的受信形态），不再返回原串；
  · `real = realpath(norm)`；`trusted = realpath(dirname(已配置路径))`
    （已配置 = 环境变量 MDCG_SIGNERS_FILE，缺省则 DEFAULT_SIGNERS_FILE）；
    `commonpath([real, trusted]) == trusted` 之外 ⇒ raise ValueError
    （消息含两侧路径与 #279）；跨盘符触发的 commonpath ValueError 按越界
    处理（不同盘必然越界）；
  · `.json` 后缀保留为**格式闸**；路径闸由 realpath+commonpath 承担；
  · 显式路径与已配置路径各自单点，无 `pass` 占位。

判据：
  G1  受信目录之外的绝对路径 x.json ⇒ ValueError（消息含两侧路径与 #279）
  G1b 非 .json 后缀 ⇒ ValueError（格式闸在场——值守三行之二）
  G2  穿越形态 `<受信>/ok.json/../../evil.json` ⇒ ValueError
      （abspath 归约后越界）
  G2b 跨盘符形态 ⇒ ValueError 而非 commonpath 的裸 ValueError 崩形
      （单盘机器自动 SKIP 并注明）
  G3  受信目录内的链接（symlink；无权限时 junction 替代并注明平台限制）
      指向受信目录外的目标 ⇒ ValueError；两种链接形态都造不出时 SKIP
  G4  （阴性对照）受信目录内 ok.json ⇒ 放行
  G5  （防过修）无参 ⇒ 放行，逐位返回已配置路径
  G6  （归一面）受信目录内非规整形态 `sub/../ok.json` ⇒ 放行且返回
      **归一后的 norm**（≠原串）——钉住「返回 norm 不返回原串」

运行：python -X utf8 -m md_cg.test_issue279_signers_path_guard
      python -X utf8 -m md_cg.test_issue279_signers_path_guard --mutate
"""
from __future__ import annotations

import importlib
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

from md_cg import signer            # noqa: E402

_OK = 0
_BAD = []

_TMP = None
_TRUSTED = None
_OUTER = None
_ENV_PATH = None
_ENV_SAVE = None
_LINK_KIND = None      # G3 实际使用的链接形态（None = 不可用，SKIP）
_LINK_WHY = ""
_LINK_PATH = None
_JUNCTIONS = []        # 结束时须先 os.rmdir 再 rmtree（防穿越删除目标）


def _check(name, cond, detail=""):
    if cond:
        globals()["_OK"] += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _raised(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return False, "", ""
    except Exception as exc:                       # noqa: BLE001
        return True, type(exc).__name__, str(exc)


def _repled(p):
    """路径在 %r 消息里的形态（去掉引号壳），用于消息含路径的断言。"""
    return repr(p)[1:-1]


def _mk_escape_link():
    """在受信目录内造指向外部目标的链接形态。

    优先 symlink；Windows 无特权（WinError 1314）时以目录 junction 替代
    （realpath 同样解析 junction）。都造不出则返回 None —— G3 届时 SKIP。
    """
    global _LINK_KIND, _LINK_WHY, _LINK_PATH
    tgt = os.path.join(_OUTER, "leak_target.json")
    with io.open(tgt, "w", encoding="utf-8") as f:
        f.write('{"leak": true}')
    sl = os.path.join(_TRUSTED, "leak_link.json")
    try:
        os.symlink(tgt, sl)
        _LINK_KIND, _LINK_PATH = "symlink", sl
        return
    except (OSError, NotImplementedError) as e:
        _LINK_WHY = "os.symlink: %s: %s" % (type(e).__name__, e)
    jn = os.path.join(_TRUSTED, "leak_junction")
    try:
        import _winapi
        _winapi.CreateJunction(_OUTER, jn)
        _JUNCTIONS.append(jn)
        _LINK_KIND = "junction"
        _LINK_PATH = os.path.join(jn, "leak_target.json")
        # realpath 必须真的解析出界，否则该形态无鉴别力
        if os.path.dirname(os.path.realpath(_LINK_PATH)) == \
                os.path.realpath(_OUTER):
            return
        _LINK_KIND, _LINK_PATH, _LINK_WHY = None, None, "junction 未被 realpath 解析出界"
    except (ImportError, AttributeError, OSError) as e2:
        _LINK_WHY = "%s；junction: %s" % (_LINK_WHY, e2)
        _LINK_KIND, _LINK_PATH = None, None


def _other_drive():
    """找一个与受信目录不同盘的现存盘符；无则 None（G2b SKIP）。"""
    home = os.path.splitdrive(os.path.realpath(_TRUSTED))[0]
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        drv = letter + ":\\"
        if os.path.splitdrive(drv)[0] and os.path.exists(drv) \
                and os.path.splitdrive(drv)[0].upper() != home.upper():
            return drv
    return None


def g1():
    print("== G1 受信目录外的 x.json ⇒ raise（消息含两侧路径与 #279）==")
    p = os.path.join(_OUTER, "secret.json")
    hit, typ, msg = _raised(signer.signers_file, p)
    _check("G1  越界 .json 被 ValueError 拒收", hit and typ == "ValueError",
           "%s %s" % (typ, msg))
    _check("G1  消息含 #279 与两侧路径",
           "#279" in msg and _repled(os.path.abspath(p)) in msg
           and _repled(os.path.realpath(_TRUSTED)) in msg, msg)


def g1b():
    print("== G1b 非 .json 后缀 ⇒ raise（格式闸在场）==")
    hit, typ, msg = _raised(signer.signers_file, os.path.join(_OUTER, "x.txt"))
    _check("G1b 非 .json 被 ValueError 拒收", hit and typ == "ValueError",
           "%s %s" % (typ, msg))


def g2():
    print("== G2 穿越/跨盘形态 ⇒ raise ==")
    trav = os.path.join(_TRUSTED, "ok.json", "..", "..", "evil.json")
    hit, typ, msg = _raised(signer.signers_file, trav)
    _check("G2  穿越 `<受信>/ok.json/../../evil.json` 被拒",
           hit and typ == "ValueError", "%s %s" % (typ, msg))
    drv = _other_drive()
    if not drv:
        print("  --   G2b 跨盘形态 SKIP（本机无第二块盘）")
        return
    cd = os.path.join(drv, "i279_crossdrive.json")
    hit, typ, msg = _raised(signer.signers_file, cd)
    _check("G2b 跨盘符路径被本闸拒收（而非 commonpath 裸崩）",
           hit and typ == "ValueError" and "#279" in msg,
           "%s %s" % (typ, msg))


def g3():
    print("== G3 受信目录内链接指向外目标 ⇒ raise（%s）=="
          % (_LINK_KIND or "不可用"))
    if not _LINK_KIND:
        print("  --   G3 SKIP（平台限制：%s）" % _LINK_WHY)
        return
    hit, typ, msg = _raised(signer.signers_file, _LINK_PATH)
    _check("G3  %s 越界被 ValueError 拒收" % _LINK_KIND,
           hit and typ == "ValueError" and "#279" in msg,
           "%s %s" % (typ, msg))


def g4():
    print("== G4（阴性对照）受信目录内 ok.json ⇒ 放行 ==")
    p = os.path.join(_TRUSTED, "ok.json")
    with io.open(p, "w", encoding="utf-8") as f:
        f.write('{"schema": 1, "subsystems": {}}')
    hit, typ, msg = _raised(signer.signers_file, p)
    _check("G4  受信目录内 ok.json 放行且返回归一形态",
           not hit and signer.signers_file(p) == os.path.abspath(p) == p,
           "%s %s" % (typ, msg))


def g5():
    print("== G5（防过修）无参 ⇒ 放行，逐位返回已配置路径 ==")
    hit, typ, msg = _raised(signer.signers_file)
    _check("G5  无参放行且返回值逐位等于已配置路径",
           not hit and signer.signers_file() == _ENV_PATH,
           "%s %s" % (typ, msg))


def g6():
    print("== G6（归一面）受信目录内非规整形态 ⇒ 放行且返回 norm ==")
    dirty = os.path.join(_TRUSTED, "sub", "..", "ok.json")
    want = os.path.join(_TRUSTED, "ok.json")
    hit, typ, msg = _raised(signer.signers_file, dirty)
    got = None if hit else signer.signers_file(dirty)
    _check("G6  `sub/../ok.json` 放行且返回归一 norm（≠原串）",
           not hit and got == want and got != dirty,
           "hit=%s %s got=%r" % (hit, msg, got))


_GROUPS = (g1, g1b, g2, g3, g4, g5, g6)


def _run_groups():
    global _OK
    _OK = 0
    del _BAD[:]
    for g in _GROUPS:
        g()
    return len(_BAD)


# --------------------------------------------------------------------------
# 定点变异自证：把修复回退成旧形态 ⇒ 判据必须打红；恢复后全绿
# --------------------------------------------------------------------------

_OLD_GATE = (
    "    real = os.path.realpath(norm)\n"
    "    trusted = os.path.realpath(os.path.dirname(os.path.abspath(configured)))\n"
    "    try:\n"
    "        inside = (os.path.commonpath([os.path.normcase(real),\n"
    "                                      os.path.normcase(trusted)])\n"
    "                  == os.path.normcase(trusted))\n"
    "    except ValueError:\n"
    "        inside = False  # 跨盘符（Windows 不同盘）/ UNC 混形：必然越界\n"
    "    if not inside:\n")

_V1_BODY = (
    "    real = os.path.realpath(norm)\n"
    "    trusted = os.path.realpath(os.path.dirname(os.path.abspath(configured)))\n"
    "    if real == trusted and False:\n"
    "        pass  # 变异 V1：路径闸死代码化（2bac760 的「部分收窄非关闭」形态）\n"
    "    if False:\n")


def _mutations():
    g3_on = ["G3"] if _LINK_KIND else []
    return (
        ("V1 路径闸死代码化（保留 .json 闸与 norm 返回）",
         _OLD_GATE, _V1_BODY, ["G1", "G2", "G2b"] + g3_on),
        ("V2 整体回退零校验形态（main@0e17513：return path or env or default）",
         "    configured = os.environ.get(SIGNERS_FILE_ENV) or DEFAULT_SIGNERS_FILE\n"
         "    if not path:\n"
         "        return configured\n"
         "    norm = os.path.abspath(str(path))\n"
         "    if not norm.endswith(\".json\"):\n",
         "    return path or os.environ.get(SIGNERS_FILE_ENV) or DEFAULT_SIGNERS_FILE\n"
         "    if True:\n"
         "        return path\n"
         "    if False:\n", ["G1", "G1b", "G2", "G2b"] + g3_on),
        ("V3 返回原串不返回 norm（丢归一形态）",
         "    return norm", "    return str(path)", ["G6"]),
    )


def _reload():
    importlib.reload(signer)


def _mutate():
    p = os.path.join(_REPO, "md_cg", "signer.py")
    with io.open(p, encoding="utf-8", newline="") as f:
        pristine = f.read()
    if "commonpath" not in pristine:
        print("  SOURCE-ALREADY-MUTATED：signer.py 缺路径闸")
        return 1
    bad = []
    for name, anchor, repl, want in _mutations():
        with io.open(p, encoding="utf-8", newline="") as f:
            orig = f.read()
        nl = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", nl)
        r_ = repl.replace("\n", nl)
        try:
            if a_ not in orig:
                print("  ANCHOR-MISS %s" % name)
                bad.append(name)
                continue
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            _reload()
            _run_groups()
            reds = list(_BAD)
            hit = all(any(x.startswith(w) for x in reds) for w in want)
            print("  %-4s %-56s 红项=%d  需红%s=%s  实红=[%s]"
                  % ("OK" if hit else "BAD", name, len(reds),
                     "/".join(want), "全中" if hit else "缺",
                     "、".join(reds)))
            if not hit:
                bad.append(name)
        finally:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(pristine)
            with io.open(p, encoding="utf-8", newline="") as f:
                if f.read() != pristine:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
            _reload()
    # V4：V1 与 V3 同时施加（完整复刻 2bac760——判据面「部分收窄非关闭」）
    try:
        with io.open(p, encoding="utf-8", newline="") as f:
            orig = f.read()
        nl = "\r\n" if "\r\n" in orig else "\n"
        a1 = _OLD_GATE.replace("\n", nl)
        r1 = _V1_BODY.replace("\n", nl)
        a3 = "    return norm".replace("\n", nl)
        r3 = "    return str(path)".replace("\n", nl)
        if a1 not in orig or a3 not in orig:
            print("  ANCHOR-MISS V4")
            bad.append("V4")
        else:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a1, r1, 1).replace(a3, r3, 1))
            _reload()
            _run_groups()
            reds = list(_BAD)
            want4 = ["G1", "G2", "G2b"] + (["G3"] if _LINK_KIND else []) + ["G6"]
            hit = all(any(x.startswith(w) for x in reds) for w in want4)
            greens = [g.__name__ for g in (g4, g5)
                      if not any(x == g.__name__ for x in reds)]
            print("  %-4s %-56s 红项=%d  需红%s=%s  阴性对照绿=[%s]"
                  % ("OK" if hit else "BAD", "V4 完整 2bac760 复刻（值守矩阵）",
                     len(reds), "/".join(want4), "全中" if hit else "缺",
                     "、".join(greens)))
            if not hit:
                bad.append("V4")
    finally:
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            f.write(pristine)
        with io.open(p, encoding="utf-8", newline="") as f:
            if f.read() != pristine:
                print("  RESTORE-FAILED V4")
                bad.append("V4(恢复失败)")
        _reload()
    if bad:
        print()
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print()
    print("定点变异自证：PASS（每处判据都被打红，恢复后源码逐位还原）")
    return 0


def _setup():
    global _TMP, _TRUSTED, _OUTER, _ENV_PATH, _ENV_SAVE
    _TMP = tempfile.mkdtemp(prefix="i279_")
    _TRUSTED = os.path.join(_TMP, "trusted")
    _OUTER = os.path.join(_TMP, "outer", "deep")
    os.makedirs(_TRUSTED)
    os.makedirs(_OUTER)
    _ENV_PATH = os.path.join(_TRUSTED, "_signers.json")
    _ENV_SAVE = os.environ.get("MDCG_SIGNERS_FILE")
    os.environ["MDCG_SIGNERS_FILE"] = _ENV_PATH
    _mk_escape_link()


def _teardown():
    if _ENV_SAVE is None:
        os.environ.pop("MDCG_SIGNERS_FILE", None)
    else:
        os.environ["MDCG_SIGNERS_FILE"] = _ENV_SAVE
    for j in _JUNCTIONS:                 # 先摘链接，防 rmtree 穿越删目标
        try:
            os.rmdir(j)
        except OSError:
            pass
    shutil.rmtree(_TMP, ignore_errors=True)


def main():
    try:
        _setup()
        n = _run_groups()
        print()
        print("signers_file 路径闸守卫：%d 通过，%d 失败"
              "（G3 链接形态=%s）" % (_OK, n, _LINK_KIND or "SKIP"))
        return 1 if n else 0
    finally:
        _teardown()


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        try:
            _setup()
            code = _mutate()
        finally:
            _teardown()
        sys.exit(code)
    sys.exit(main())
