# -*- coding: utf-8 -*-
# 功能名：mdcg_service_info 必须与 mdcg_whoami 同闸，且工具面闸表对 TOOLS 完备（issue #578 / dsh-bounty#435）
# 生效条件：python -X utf8 -m md_cg.test_issue578_service_info_gate [--mutate]；被测面＝md_cg/mcp_server.py 的 _MDCG_TOOL_OP / _MDCG_OP_REQUIRE 与 _dispatch 对该入口的处置
# 子功能：G01-G03 静态完备性（对 TOOLS 求双向差集 + 同载荷同档）；G04-G06 行为同判（4 个 principal 逐格对照 whoami，含反向对照）；G07 载荷收敛**观察项**（不判红，设计取舍未定）；M 组＝--mutate 定点变异（删掉那一行 ⇒ 必须转红）
# 执行：--mutate 时在镜像树里删掉 "mdcg_service_info": "read", 一行（回缺陷），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下红项集合须与预期逐项相符
# 不适用条件：① 不判 mdcg_whitebox 的工具面口径（#398 KNOWN_WEAK 已登记、另案）；② 不判 MDCG_MCP_SURFACE 的面成员（tools/call 不受 surface 约束，另案）；③ 不判载荷该不该带 token_id/session（G07 只打印观察值，不改判据）；④ 不判 service_info 的触发面是否应更窄（full surface 才有 tools/list 条目，属产品取舍）。
"""issue #578 守卫：mdcg_service_info 不得绕过工具面闸表。

病象（修前）：该入口**不在** _MDCG_TOOL_OP（31 个工具里唯一缺项）⇒ _dispatch 取
_MDCG_OP_REQUIRE.get(name) 得 None ⇒ 跳过 require_op；而它回吐的 principal.as_dict()
与**受 read 闸管着**的 mdcg_whoami 是同一份身份清单（tenant/actor/role/clearance/
can_write/can_admin/session/token_id/layers_allow/ops_allow）＋库根绝对路径 ⇒ 只读访客
与「被 --ops-allow 收窄到不含 read」的令牌都能拿到它。

同时钉住上一轮修法没覆盖到的盲点：#398 的守卫
test_issue398_toolface_op_parity.py 的 E02 断言是
len(_MDCG_TOOL_OP) == len(_MDCG_OP_REQUIRE) >= 30 —— 两边同源派生，**自比自恒真**，
「映射缺一项」在结构上不可见。本守卫改为**对 TOOLS 求双向差集**，缺项当场点名。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS = []
NOTES = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _note(name, detail):
    print("  NOTE " + name + "  " + str(detail)[:200])
    NOTES.append(name)


_TMP = tempfile.mkdtemp(prefix="iss578_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_TOKEN_FILE": _TMP + "/auxstore/tokens.json"})

from md_cg import crypto                        # noqa: E402
os.environ[crypto.MASTER_ENV] = "ab" * 32
from md_cg import mcp_server as _ms             # noqa: E402
from md_cg.mdcos import MdCGSecure              # noqa: E402
from md_cg.security import Principal            # noqa: E402

_KEK = b"k" * 32


def _err(fn):
    """调 fn：正常返回 ("", 结果)；抛异常（含 BaseException）返回 (类型名, 文本)。"""
    try:
        return "", fn()
    except BaseException as exc:                 # noqa: BLE001 —— 变异态不得崩栈
        return type(exc).__name__, str(exc)


#: 四个 principal：闸的**两侧**都要覆盖（有 read / 无 read / 空 ops / 全域）。
#: C 是 B 的更极端形态（连 info 都没有）——只看 B 会漏掉 ops_allow 为空这一支。
_MATRIX = (
    ("A 无令牌等价 guest（含 read）",
     dict(role="guest", clearance="internal", can_write=False,
          ops_allow=["info", "route", "read", "recent", "whitebox", "status", "edges"],
          layers_allow=[]),
     "pass"),                                  # guest 本就持 read ⇒ 同闸后仍应放行
    ("B 窄化令牌（有 write 无 read）",
     dict(role="designer", clearance="internal", can_write=True,
          ops_allow=["write", "info"], layers_allow=["knowledge"]),
     "deny"),                                  # 修前放行、修后 AccessDenied
    ("C 空 ops_allow",
     dict(role="designer", clearance="internal", can_write=True,
          ops_allow=[], layers_allow=["knowledge"]),
     "deny"),
    ("D 全域 designer（ops_allow=None）",
     dict(role="designer", clearance="internal", can_write=True,
          ops_allow=None, layers_allow=None),
     "pass"),
)


def _cg(tag, kw):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    return MdCGSecure(d + "/root",
                      principal=Principal(tenant="default", actor="iss578", **kw),
                      master_key=_KEK, autoflush=1)


print("== G 组 站点 1：闸表对 TOOLS 的**完备性**（静态，双向差集） ==")

_tools = [t["name"] for t in _ms.TOOLS]
_tool_set = set(_tools)
_toolop = set(_ms._MDCG_TOOL_OP)
_opreq = set(_ms._MDCG_OP_REQUIRE)
_missing = sorted(_tool_set - _toolop)
_extra = sorted(_toolop - _tool_set)

_check("G01 ★：TOOLS(%d) 与闸表(%d) 双向差集为空——漏登的工具当场点名（修前漏登 = ['mdcg_service_info']）"
       % (len(_tool_set), len(_toolop)),
       not _missing and not _extra,
       {"漏登": _missing, "多余": _extra})
_check("G02 派生表与工具表同源同形（_MDCG_OP_REQUIRE 由 _MDCG_TOOL_OP 派生，不得多键/少键）",
       _opreq == _toolop, sorted(_opreq ^ _toolop))
_check("G03 ★：mdcg_service_info 在闸表内，且与 mdcg_whoami **同档**"
       "（同一份 principal 载荷，闸词不得一有一无）",
       _ms._MDCG_TOOL_OP.get("mdcg_service_info") is not None
       and _ms._MDCG_TOOL_OP.get("mdcg_service_info") == _ms._MDCG_TOOL_OP.get("mdcg_whoami"),
       (_ms._MDCG_TOOL_OP.get("mdcg_service_info"), _ms._MDCG_TOOL_OP.get("mdcg_whoami")))

print("== G 组 站点 2：同载荷同闸（行为，逐格对照 whoami） ==")

_rows = []
for _tag, _kw, _expect in _MATRIX:
    _c = _cg(_tag.split()[0], _kw)
    _ts, _ = _err(lambda c=_c: _ms._dispatch(c, "mdcg_service_info", {}))
    _tw, _ = _err(lambda c=_c: _ms._dispatch(c, "mdcg_whoami", {}))
    _rows.append((_tag, _ts or "200", _tw or "200", _expect))

_check("G04 ★：service_info 与 whoami 对同一 principal **同判**"
       "（修前 B/C 两格分叉：service_info=200 / whoami=AccessDenied）",
       all(si == wh for _, si, wh, _ in _rows),
       [(t, si, wh) for t, si, wh, _ in _rows if si != wh])
_check("G05 ★：无 read 的两格对 service_info 是 AccessDenied"
       "（修前 200：身份清单 + token_id/session/ops_allow + 库根绝对路径全量回吐）",
       [si for _, si, _, ex in _rows if ex == "deny"] == ["AccessDenied", "AccessDenied"]
       and [si for _, si, _, ex in _rows if ex == "pass"] == ["200", "200"],
       _rows)
_check("G06 反向对照：whoami 的读数在任何修法下都不得变化（同闸 ≠ 把 whoami 一起关掉）",
       [wh for _, _, wh, _ in _rows] == ["200", "AccessDenied", "AccessDenied", "200"],
       [(t, wh) for t, _, wh, _ in _rows])

print("== G 组 站点 3：载荷收敛观察项（不判红） ==")

_guest_cg = _cg("payload", _MATRIX[0][1])
_, _payload = _err(lambda: _ms._dispatch(_guest_cg, "mdcg_service_info", {}))
_pr = (_payload or {}).get("principal") or {}
_exposed = [k for k in ("token_id", "session", "ops_allow", "layers_allow", "harness")
            if k in _pr]
if _exposed:
    _note("G07 观察：guest 的 service_info 仍带 %s（与 whoami 同载荷）——"
          "「要不要只回版本/计数」属设计取舍，本守卫不判红，交维护者裁定" % _exposed,
          _exposed)
else:
    _note("G07 观察：guest 的 service_info 已不带头部身份句柄（只回版本/计数）", "clean")

# ---------------------------------------------------------------- 定点变异
_ANCHOR = '    "mdcg_service_info": "read",'
_EXPECT_RED = ("G01", "G03", "G04", "G05")
_EOL = chr(13) + chr(10)


def _mirror_build():
    """镜像树：md_cg/ ＋ 仓根 .py（utf8_boot.py 等引导依赖）＋ README/pyproject/package.json。

    只拷 md_cg/ 会在 import 期炸 `No module named 'utf8_boot'`（mcp_server 的引导依赖，
    第 66 行），与 #398 守卫 _mirror_build 的口径保持一致。
    """
    dst = tempfile.mkdtemp(prefix="iss578_mut_")
    shutil.copytree(os.path.join(_REPO, "md_cg"), os.path.join(dst, "md_cg"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    """在镜像树里跑本守卫（禁变异递归），返回 (rc, 红项代号集合, 输出)。"""
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MDCG_ISSUE578_NO_MUTATE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT",
              "MDCG_DATA_ROOT", "MDCG_EXPORT_ROOT", "MDCG_TOKEN_FILE"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue578_service_info_gate"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=600)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = sorted({ln.split("FAIL ", 1)[1].split(" ")[0].strip()
                   for ln in out.splitlines() if ln.strip().startswith("FAIL ")})
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：删掉闸表那一行（回缺陷），守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%s（必须 rc=0 且 0 红）" % (rc, reds))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-20:]))
        p = os.path.join(tree, "md_cg", "mcp_server.py")
        with open(p, encoding="utf-8", newline="") as f:
            bak = f.read()
        eol = chr(13) + chr(10) if (chr(13) + chr(10)) in bak else chr(10)
        anchor = (_ANCHOR + chr(10)).replace(chr(10), eol)
        if bak.count(anchor) != 1:
            bad.append("变异锚点命中 %d 次（要求 1）" % bak.count(anchor))
            print("  ANCHOR-MISS 删行变异：锚点命中 %d 次" % bak.count(anchor))
        else:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak.replace(anchor, "", 1))
            for root, _dd, _ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            if rc2 != 0 and reds2 == sorted(_EXPECT_RED):
                print("  OK   删行变异：红项=%s" % reds2)
            else:
                bad.append("删行变异红项不符")
                print("  MISMATCH 删行变异：实际=%s 期望=%s rc=%d"
                      % (reds2, sorted(_EXPECT_RED), rc2))
                for ln in out2.splitlines():
                    if ln.strip().startswith("FAIL "):
                        print("        " + ln[:170])
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    _bad = 0
    if "--mutate" in sys.argv and not os.environ.get("MDCG_ISSUE578_NO_MUTATE"):
        _bad = _mutate()
    shutil.rmtree(_TMP, ignore_errors=True)
    print("")
    if FAILS:
        print("issue #578 结果：%d 失败（%s）" % (len(FAILS), ", ".join(FAILS)))
    else:
        print("issue #578 结果：全部通过（观察项 %d 条未判红）" % len(NOTES))
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
