# -*- coding: utf-8 -*-
"""link 的 swarm 参数路径闸守卫（issue #245）。

【守什么】
#245 报：evidence.swarm_dir() 对 swarm 零校验直接返回，后被 os.path.join
用作**写盘根**——传绝对路径或 ../ 即可在记忆库之外建目录写文件。

复核**成立**（实测：publish_card(root, swarm=<root 之外>) 在 root 之外建出
peers/）。且既有的 realpath 兜底（#147 的 write_pack、#277 的 publish_card）
**兜不住**：那些判据的基准 base = realpath(peers_dir(swarm)) 本身由 swarm
派生 ⇒ real.startswith(base) 恒真，是自证同义反复。故收口必须在**入口**。

修法：MCP link 分支入口加 _gate_link_swarm，与 issue #167 的
_gate_link_signers_file 同形——只接受运维侧现行共享目录（realpath 归一）；
未传则行为逐位不变。

判据：
  S1  闸在场，且在 link 分支内被调用（结构性）。
  S2  MCP 面：恶意 swarm 被拒——link 分支的**每个** action 逐一验（从源码
      提取 action 名，故后续新增 action 自动纳入）。
  S3  MCP 面：相对 ../ 穿越被拒。
  S4  MCP 面：非字符串 swarm 被拒（fail-closed，不落成 TypeError）。
  S5  未传 swarm ⇒ 闸放行（行为逐位不变）。
  S6  现行共享目录放行；realpath 归一等价形态也放行（证明比的是 realpath）。
  S7  **边界如实**：库层直调仍可指定任意 swarm——那是进程内调用者权限，
      与 MCP 面不是同一信任级（同 #279 的库 API 面定性）。本组**钉住**该
      边界，免得后来者以为库层也被收口了。
  S8  反陈化：闸的**理由**（base 由 swarm 派生 ⇒ 兜底恒真）在源码里。
  S9  **兜底无效性自证**：现算 base 与目标，证明 realpath 包含性恒真。
  S10 修复前源码原形——用 git log -S 定位引入提交取父版本；**未提交**时
      回落 HEAD（两种状态下都稳定，不假设 HEAD 处于某历史状态：项目方在
      #277 踩过该坑）。并钉住「收口在 MCP 入口、库层未改」这一边界。

运行：python -X utf8 -m md_cg.test_issue245_swarm_traversal
      python -X utf8 -m md_cg.test_issue245_swarm_traversal --mutate
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="i245_")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "lib")
# ★ 目录名**不可**用 "aux"——AUX 是 Windows 保留设备名，os.makedirs 会抛
# NotADirectoryError [WinError 267]（项目方实测踩到，最小复现：<tmp>/lib 成功、
# <tmp>/aux 失败）。同理避开 CON/PRN/NUL/COM1-9/LPT1-9。
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxstore")
os.environ["MDCG_MASTER_KEY"] = "ab" * 32
os.environ.pop("MDCG_SWARM_DIR", None)
os.makedirs(os.environ["MDCG_ROOT"], exist_ok=True)
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import evidence as E          # noqa: E402
from md_cg import mcp_server             # noqa: E402
from md_cg.mdcos import MdCGSecure       # noqa: E402
from md_cg.security import Principal     # noqa: E402

_KEK = os.urandom(32)
_OK = 0
_BAD = []

#: 恶意 swarm：记忆库之外的绝对路径
_OUTSIDE = os.path.join(_TMP, "outside", "evil_abs")
_REL = os.path.join("..", "..", "..", "evil_rel")
_GATE_MSG = "只能指向现行共享目录"


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _mk():
    return MdCGSecure(os.environ["MDCG_ROOT"],
                      principal=Principal(tenant="t1", actor="a1",
                                          role="designer", clearance="private",
                                          can_write=True, can_admin=True),
                      master_key=_KEK)


def _raised(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return False, "", ""
    except Exception as exc:                       # noqa: BLE001
        return True, type(exc).__name__, str(exc)


def _link(act, **extra):
    """调 MCP link 分支的某个 action → (是否抛, 异常名, 文本)。"""
    args = {"op": "link", "action": act}
    args.update(extra)
    return _raised(mcp_server._dispatch, _mk(), "cg", args)


def _src(rel):
    return io.open(os.path.join(_REPO, rel), encoding="utf-8",
                   errors="replace").read()


def _link_body():
    src = _src(os.path.join("md_cg", "mcp_server.py"))
    i0 = src.index('    if op == "link":')
    i1 = src.index("    if op ==", i0 + 10)
    return src, src[i0:i1]


def _link_actions(body):
    return sorted(set(re.findall('act == "([a-z_]+)"', body)))


def s1():
    print("== S1 闸在场且在 link 分支内 ==")
    src, body = _link_body()
    _check("S1a _gate_link_swarm 已定义", "def _gate_link_swarm(a):" in src)
    _check("S1b 闸在 link 分支内被调用", "_gate_link_swarm(a)" in body)


def s2():
    print("== S2 MCP 面：恶意 swarm 被拒（逐 action）==")
    _, body = _link_body()
    acts = _link_actions(body)
    _check("S2a 从源码提取到 action 名", len(acts) >= 5, acts)
    for act in acts:
        hit, ename, txt = _link(act, swarm=_OUTSIDE)
        _check("S2 恶意绝对 swarm 被拒：action=%s" % act,
               hit and _GATE_MSG in txt, (ename, txt[:90]))


def s3():
    print("== S3 MCP 面：相对穿越被拒 ==")
    for act in ("card", "peers", "export", "import"):
        hit, ename, txt = _link(act, swarm=_REL)
        _check("S3 ../ 穿越被拒：action=%s" % act,
               hit and _GATE_MSG in txt, (ename, txt[:90]))


def s4():
    print("== S4 MCP 面：非字符串被拒 ==")
    for bad in (123, ["x"], {"a": 1}):
        hit, ename, txt = _link("card", swarm=bad)
        _check("S4 非字符串 swarm 被拒：%r" % (bad,),
               hit and ename == "ValueError" and "必须是字符串路径" in txt,
               (ename, txt[:90]))


def s5():
    print("== S5 未传 swarm ⇒ 放行（行为逐位不变）==")
    for absent in ({}, {"swarm": None}, {"swarm": ""}):
        hit, ename, txt = _raised(mcp_server._gate_link_swarm, absent)
        _check("S5 闸对 %r 放行" % (absent,), not hit, (ename, txt[:80]))


def s6():
    print("== S6 现行共享目录放行（比的是 realpath 而非字符串）==")
    cur = os.path.join(_TMP, "swarm_ok")
    os.makedirs(cur, exist_ok=True)
    os.environ["MDCG_SWARM_DIR"] = cur
    try:
        hit, ename, txt = _raised(mcp_server._gate_link_swarm, {"swarm": cur})
        _check("S6a 现行共享目录放行", not hit, (ename, txt[:80]))
        equiv = os.path.join(cur, "..", os.path.basename(cur))
        hit2, ename2, txt2 = _raised(mcp_server._gate_link_swarm,
                                     {"swarm": equiv})
        _check("S6b realpath 归一等价形态放行（证明比的是 realpath）",
               not hit2, (equiv, ename2, txt2[:80]))
        hit3, ename3, txt3 = _raised(mcp_server._gate_link_swarm,
                                     {"swarm": os.path.join(_TMP, "other")})
        _check("S6c 另一个目录仍被拒", hit3 and _GATE_MSG in txt3,
               (ename3, txt3[:80]))
    finally:
        os.environ.pop("MDCG_SWARM_DIR", None)


def s7():
    print("== S7 边界如实：库层直调仍可指定任意 swarm（未收口）==")
    root = os.path.join(_TMP, "lib_s7")
    os.makedirs(root, exist_ok=True)
    target = os.path.join(_TMP, "outside_s7")
    hit, ename, txt = _raised(E.publish_card, root, swarm=target)
    _check("S7a 库层 publish_card 不拒任意 swarm（进程内调用者权限）",
           not hit, (ename, txt[:90]))
    _check("S7b 确在 root 之外建出了 peers/（边界属实）",
           os.path.isdir(os.path.join(target, "peers")), target)
    _check("S7c 闸只加在 MCP 面（evidence 模块内无该闸）",
           "_gate_link_swarm" not in _src(os.path.join("md_cg", "evidence.py")))


def s8():
    print("== S8 反陈化：闸的理由在源码里 ==")
    src = _src(os.path.join("md_cg", "mcp_server.py"))
    i0 = src.index("def _gate_link_swarm(a):")
    i1 = src.index("def _import_subsystem_gate(a, ev):")
    body = src[i0:i1]
    _check("S8a 标注 issue #245", "issue #245" in body)
    _check("S8b 写明「兜不住」的理由（base 由 swarm 派生）",
           "startswith(base)" in body and "派生" in body)
    _check("S8c 写明「收口必须在入口，不能靠汇点」",
           "入口" in body and "汇点" in body)
    _check("S8d 写明「未传则行为逐位不变」", "逐位不变" in body)


def s9():
    print("== S9 兜底无效性自证：realpath 包含性对恶意 swarm 恒真 ==")
    base = os.path.realpath(E.peers_dir(_OUTSIDE))
    target = os.path.join(base, "node-abc.json")
    real = os.path.realpath(target)
    contained = real == base or real.startswith(base + os.sep)
    _check("S9a 兜底基准 base 本身由恶意 swarm 派生", _OUTSIDE in base, base)
    _check("S9b 目标「在 base 内」恒真 ⇒ 兜底拦不住恶意 swarm", contained,
           (base, real))
    _check("S9c 故 #147/#277 的 realpath 判据与 swarm 面无关",
           "realpath(peers_dir(swarm))" in _src(os.path.join("md_cg",
                                                             "evidence.py")))


def _prepatch_src():
    def _g(*a):
        return subprocess.run(list(a), cwd=_REPO, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=60)
    lg = _g("git", "log", "-S_gate_link_swarm", "--format=%H", "--",
            "md_cg/mcp_server.py")
    if lg.returncode == 0:
        shas = [x.strip() for x in (lg.stdout or "").splitlines() if x.strip()]
        if shas:
            intro = shas[-1]
            src = _g("git", "show", intro + "^:md_cg/mcp_server.py")
            if src.returncode == 0:
                return src.stdout, "引入提交 %s 的父版本" % intro[:8]
    src = _g("git", "show", "HEAD:md_cg/mcp_server.py")
    if src.returncode != 0:
        return None, "git show HEAD rc=%s" % src.returncode
    return src.stdout, "HEAD（本改动尚未提交）"


def s10():
    print("== S10 修复前源码原形（提交前/后都稳定）==")
    t, how = _prepatch_src()
    if t is None:
        _check("S10 取修复前源失败：%s" % how, False)
        return
    print("       （修复前源取自 %s）" % how)
    _check("S10a 修复前的 mcp_server.py 无 _gate_link_swarm",
           "_gate_link_swarm" not in t)
    _check("S10b 修复前 link 分支只有 signers_file 闸、无 swarm 闸",
           "_gate_link_signers_file(a)" in t and "_gate_link_swarm(a)" not in t)
    # 根因面**未改**：evidence.swarm_dir 仍是零校验（收口在 MCP 入口，不在库层）
    ev = _src(os.path.join("md_cg", "evidence.py"))
    _check("S10c evidence.swarm_dir 仍是零校验原形（收口在 MCP 入口）",
           "return path or os.environ.get(SWARM_DIR_ENV) or DEFAULT_SWARM_DIR"
           in ev)


_GROUPS = (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10)


def _run_groups():
    global _OK
    _OK = 0
    _BAD.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                   # noqa: BLE001
            _check("断言组 %s 抛异常：%s" % (g.__name__, exc), False)
            import traceback
            print(traceback.format_exc()[-600:])
    return len(_BAD)


def main():
    n = _run_groups()
    print()
    print("swarm 路径闸守卫：%d 通过，%d 失败" % (_OK, n))
    return 1 if n else 0


_MUTATIONS = (
    ("V1 去掉 link 分支里的闸调用（回到零约束）",
     '        _gate_link_signers_file(a)\n        _gate_link_swarm(a)\n',
     '        _gate_link_signers_file(a)\n', "S1"),
    ("V2 闸体失效（非字符串检查被关掉）",
     "    if not isinstance(sw, str):\n",
     "    if False:\n", "S4"),
    ("V3 只比字符串不比 realpath（去掉归一）",
     "    if os.path.realpath(os.path.expanduser(sw)) != os.path.realpath(\n"
     "            os.path.expanduser(cur)):\n",
     "    if sw != cur:\n", "S6"),
)


def _reload():
    import importlib
    from md_cg import mcp_server as _m
    importlib.reload(_m)
    globals()["mcp_server"] = _m


def _mutate():
    bad = []
    p = os.path.join(_REPO, "md_cg", "mcp_server.py")
    with io.open(p, encoding="utf-8", newline="") as f:
        pristine = f.read()
    if "_gate_link_swarm" not in pristine:
        print("  SOURCE-ALREADY-MUTATED：mcp_server.py 缺 _gate_link_swarm")
        return 1
    for name, anchor, repl, want in _MUTATIONS:
        with io.open(p, encoding="utf-8", newline="") as f:
            orig = f.read()
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
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
            hit = any(x.startswith(want) for x in reds)
            print("  %-4s %-46s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(reds), want,
                     "是" if hit else "否"))
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
    if bad:
        print()
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print()
    print("定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
