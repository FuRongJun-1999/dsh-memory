# -*- coding: utf-8 -*-
# 功能名：工具面 op 闸词不得弱于规范面真源（issue #398）
# 生效条件：python -X utf8 -m md_cg.test_issue398_toolface_op_parity [--mutate]；被测面＝md_cg/mcp_server.py 的 _MDCG_TOOL_OP / _MDCG_OP_REQUIRE 派生表与其在 _dispatch 的消费
# 子功能：A 组＝复现报告两条链（README 逐字窄化令牌驱动 mdcg_self_state(refresh) 真落盘；guest 可调 mdcg_review_records）+ 规范出口同判；K 组＝非恒真对照（含过度收紧方向：把闸词收到比真源更严 ⇒ 正常调用被误拒）；E 组＝**全表一致性断言**（30 条逐条与 op_table 真源对齐核验，凡工具面弱于真源的当场报出）；S 组＝**收尾块可执行**（issue #438：S01 静态钉「__main__ 之后无模块级语句 / main 内单 return 且 return 前有 rmtree」；S02 在隔离 TEMP 下子进程实跑，钉「结论行恰 1 条且 iss398_* 无残留」）
# 执行：--mutate 时在镜像树里把两处改回 read（回缺陷）、把正常条目收到更严（过度收紧）、新增一条未登记弱化条目、把收尾块搬回模块级并复现双 return（#438 回退），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**
# 不适用条件：不判库层（mdcos/tokens）自身的读可见性过滤；不判 cg 面 op 表（op_table）本身；已知的 7 条同类弱化条目**登记在案不修**（见 E 组 KNOWN_WEAK，非本报告面）；不判 stg 面；S02 只判「本守卫自身的收尾块可执行」，不判其它守卫的临时目录卫生
"""issue #398 守卫：`_MDCG_OP_REQUIRE` 的工具面闸词不得弱于规范面真源。

病象（修前）：`mdcg_self_state` 与 `mdcg_review_records` 的闸词写成粗粒度 `read`，而真源
`op_table` 里分别是 `self_state` / `review` ⇒ 同一 principal 在规范出口 `cg(op=…)` 被拒、
在工具面放行：前者 `refresh` **真写 self 层**状态卡（override=True），后者让仅有 read 的
guest 读回裁决台账。

★ 本形态在本仓已被修过 **N201/N227/N228/N229/#435** 五次（本轮还修了同族 #348-A）
⇒ **逐点修治不住**。故本件的主产出是两层：① 闸词改为**从 `op_table` 单一真源派生**
（`_MDCG_OP_REQUIRE = {name: _op_require(op) …}`，不在表里再写死值）；② 本守卫的
**全表一致性断言**——枚举全部条目逐条与真源对齐，凡「工具面弱于真源」的当场报出，
且**新出现的弱化条目一律转红**（既有同类条目进显式登记清单，见 KNOWN_WEAK）。

「守卫必须能在变异态下跑完」：取数经包装折成可命名形态，不崩栈。
"""
from __future__ import annotations

import ast
import io
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


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


_TMP = tempfile.mkdtemp(prefix="iss398_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_TOKEN_FILE": _TMP + "/auxstore/tokens.json"})

from md_cg import mcp_server as _ms          # noqa: E402
from md_cg import op_table as _ot
import md_cg._guard_kit as _kit          # noqa: E402 —— 回退即绿自证骨架（task-16）            # noqa: E402
from md_cg import tokens as _tk              # noqa: E402
from md_cg.mdcos import MdCGSecure           # noqa: E402

_KEK = b"k" * 32


def _err(fn):
    """调 fn：正常返回 ("", 结果)；抛异常（含 BaseException）返回 (类型名, 文本)。"""
    try:
        return "", fn()
    except BaseException as exc:                 # noqa: BLE001 —— 变异态不得崩栈
        return type(exc).__name__, str(exc)


def _principal(role, **kw):
    r = _tk.issue(role, actor="iss398-" + role, path=_tk.token_file(None),
                  _allow_bootstrap=True, **kw)   # 测试搭架：闸的证明在 test_issue543
    return _tk.verify_token(r["token"], path=_tk.token_file(None))


def _cg(principal, tag):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    return MdCGSecure(d + "/root", principal=principal, master_key=_KEK, autoflush=1)


def _call(cg, name, **args):
    return _ms._dispatch(cg, name, dict(args))


#: README:145-147 逐字示例（DSH 接入推荐配置）：含 self 层、**不含** self_state op。
_README_OPS = ["info", "route", "read", "write", "recent", "goal", "identity",
               "whitebox", "verify"]
_README_LAYERS = ["knowledge", "contextual", "structural", "self", "goals",
                  "unresolved", "rejected"]

print("== A 组 站点 1：mdcg_self_state（refresh 真写 self 层） ==")
_p_self = _principal("designer", ops_allow=list(_README_OPS),
                      layers_allow=list(_README_LAYERS))
_cg1 = _cg(_p_self, "self_state")
_check("A01 前提：窄化令牌**不含** self_state op 且**含** self 层（README 逐字）",
       "self_state" not in _README_OPS and "self" in _README_LAYERS, "")
_t1, _e1 = _err(lambda: _call(_cg1, "cg", op="self_state", action="refresh"))
_check("A02 规范出口 cg(op=self_state, action=refresh) → AccessDenied（两态皆然，真源不变）",
       _t1 == "AccessDenied", (_t1, _e1))
_t2, _e2 = _err(lambda: _call(_cg1, "mdcg_self_state", action="refresh"))
_check("A03 ★行：工具面 mdcg_self_state(action=refresh) → **AccessDenied**（修前放行）",
       _t2 == "AccessDenied", (_t2, _e2))
_disk = []
for _r, _d, _f in os.walk(_cg1.root):
    for _x in _f:
        if _x.endswith(".md"):
            _disk.append(_x)
_check("A04 ★行：self 层状态卡**未落盘**（修前真落盘 self_state_self_lingshu.md）",
       not any("self_state" in x for x in _disk), _disk)

print("== A 组 站点 2：mdcg_review_records（guest 读裁决台账） ==")
_p_guest = _principal("guest", ops_allow=["info", "route", "read", "recent",
                                          "whitebox", "status", "edges"],
                       clearance="internal")
_cg2 = _cg(_p_guest, "review_records")
_t3, _e3 = _err(lambda: _call(_cg2, "cg", op="review", action="records"))
_check("A05 规范出口 cg(op=review, action=records) → AccessDenied（两态皆然）",
       _t3 == "AccessDenied", (_t3, _e3))
_t4, _e4 = _err(lambda: _call(_cg2, "mdcg_review_records", pid="x"))
_check("A06 ★行：工具面 mdcg_review_records → **AccessDenied**（修前放行、回吐台账）",
       _t4 == "AccessDenied", (_t4, _e4))

print("== K 组：非恒真对照（含过度收紧方向——不得比真源更严） ==")
_cg3 = _cg(_principal("designer", ops_allow=["read"], clearance="internal"), "k_normal")
_t5, _e5 = _err(lambda: _call(_cg3, "mdcg_recall", query="x", limit=1))
_check("K01 过度收紧方向的对照：普通读面工具（mdcg_recall）对持 read 的令牌**仍放行**",
       _t5 != "AccessDenied", (_t5, _e5))
_cg3b = _cg(_principal("designer", ops_allow=["read", "self_state"]), "k_selfstate")
_t6, _e6 = _err(lambda: _call(_cg3b, "mdcg_self_state", action="snapshot"))
_check("K02 持 self_state（另有 read）的令牌在工具面照常可用（收紧不等于全拒；角色自身白名单不含该 "
       "op 的令牌由 tokens 收窄，本组改用 designer 显式窄化）",
       _t6 != "AccessDenied", (_t6, _e6))
_cg4 = _cg(_principal("designer"), "k_designer")
_t7, _e7 = _err(lambda: _call(_cg4, "mdcg_self_state", action="snapshot"))
_check("K03 designer（ops 星号）两态照常放行（不得把高权角色也拒掉）",
       _t7 == "", (_t7, _e7))
_cg3c = _cg(_principal("designer", ops_allow=["read", "review"]), "k_review")
_t8, _e8 = _err(lambda: _call(_cg3c, "mdcg_review_list"))
_check("K04 N201 姊妹条目（mdcg_review_list→review）行为不变：持 review 的令牌放行",
       _t8 != "AccessDenied", (_t8, _e8))

print("== E 组：全表一致性断言（本件主产出） ==")


def _roles_with(op):
    """持有该 op 词的角色集合（ops_allow 为 None 或含 * ⇒ 全角色）。"""
    out = set()
    for role, spec in _tk.ROLE_SPECS.items():
        allow = (spec or {}).get("ops_allow") if isinstance(spec, dict) else None
        if allow is None or "*" in allow:
            out.add(role)
        elif op in allow:
            out.add(role)
    return out


_REL = "md_cg/mcp_server.py"
with io.open(os.path.join(_REPO, _REL), encoding="utf-8") as _f:
    _SRC = _f.read()

_MISMATCH, _WEAK, _ALL = [], [], []
for _name, _op in sorted(_ms._MDCG_TOOL_OP.items()):
    _mapped = _ms._MDCG_OP_REQUIRE.get(_name)
    _entry = _ot._OP_TABLE.get(_op)
    _truth = (_entry.get("require") if isinstance(_entry, dict) else None) or _op
    _ALL.append((_name, _op, _mapped, _truth))
    if _mapped != _truth:
        _MISMATCH.append((_name, _op, _mapped, _truth))
    _same = _name[len("mdcg_"):]
    _se = _ot._OP_TABLE.get(_same)
    if isinstance(_se, dict):
        _t2 = _se.get("require") or _same
        if _roles_with(_mapped) > _roles_with(_t2):
            _WEAK.append((_name, _mapped, _t2))

_check("E01 全表逐条与真源对齐：%d 条无一「闸词 ≠ op_table 里该 op 的 require」" % len(_ALL),
       _MISMATCH == [], _MISMATCH)
_check("E02 枚举非空转：工具数 == 闸词表条目数 且 ≥ 30",
       len(_ms._MDCG_TOOL_OP) == len(_ms._MDCG_OP_REQUIRE) >= 30,
       (len(_ms._MDCG_TOOL_OP), len(_ms._MDCG_OP_REQUIRE)))
#: 同类但**非本报告面**的既有弱化条目（登记在案、本轮不修；理由见注释）。
#: 断言口径：弱化集必须**恰等于**本清单——修好一条会因清单陈旧而红（逼你更新），
#: 新增一条会因未登记而红（第 6 次当场拦住）。
_KNOWN_WEAK = {
    # 均为「同名 op 在真源要求更细的词，而工具面只查 read/write」的同族形态，
    # 但都不属 #398 报告面（报告只点名 self_state / review_records），且各有
    # 「工具面刻意比 cg 面宽」的可能解释需维护者裁定 ⇒ 登记不擅改。
    ("mdcg_causal", "read", "causal"),
    ("mdcg_consistency", "write", "consistency"),
    ("mdcg_forget", "write", "forget"),
    ("mdcg_identity", "read", "identity"),
    ("mdcg_ingest", "write", "ingest"),
    ("mdcg_metacognition", "read", "metacognition"),
    ("mdcg_predict", "read", "predict"),
    ("mdcg_whitebox", "read", "whitebox"),
}
_CUR_WEAK = set(tuple(x) for x in _WEAK)
_check("E03 ★：**弱化集 ⊆ 登记清单**（新出现的「工具面弱于真源」当场报出）",
       _CUR_WEAK <= _KNOWN_WEAK, sorted(_CUR_WEAK - _KNOWN_WEAK))
_check("E04 ★：登记清单**无陈旧项**（已修好的条目必须从清单移除，防清单变免死金牌）",
       _KNOWN_WEAK <= _CUR_WEAK, sorted(_KNOWN_WEAK - _CUR_WEAK))
_check("E05 源码面：闸词表由 `_op_require` **派生**（不在表里再写一遍死值）",
       "for name, op in _MDCG_TOOL_OP.items()}" in _SRC
       and "_op_require(op)" in _SRC, "")
_check("E06 站点 1/2 在派生表中的值与真源一致（self_state / review）",
       _ms._MDCG_OP_REQUIRE["mdcg_self_state"] == "self_state"
       and _ms._MDCG_OP_REQUIRE["mdcg_review_records"] == "review",
       (_ms._MDCG_OP_REQUIRE["mdcg_self_state"],
        _ms._MDCG_OP_REQUIRE["mdcg_review_records"]))

print("== S 组：收尾块可执行（issue #438 的回归判据） ==")


def _tail_static():
    """静态：`if __name__ == "__main__":` 必须是模块最后一条语句；main() 里只有
    一个顶层 return，且 return 之前有 `shutil.rmtree(_TMP…)`。

    #438 的病灶是「收尾块写在 `sys.exit(main())` 之后」⇒ 恒为死代码：既不打结论行，
    也永不回收 _TMP（每次执行泄漏 1 个 iss398_*）。把「收尾块在 main() 里、且在
    return 之前」「__main__ 之后无模块级语句」钉成判据，回退到缺陷形态当场转红。
    """
    with open(os.path.abspath(__file__), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    main_if = None
    for i, node in enumerate(tree.body):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and any(isinstance(c, ast.Constant) and c.value == "__main__"
                        for c in [node.test.left] + list(node.test.comparators))):
            main_if = i
    after = [] if main_if is None else [type(n).__name__ for n in tree.body[main_if + 1:]]
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    returns = [] if fn is None else [n for n in fn.body if isinstance(n, ast.Return)]
    cleanup_idx = []
    if fn is not None:
        for i, n in enumerate(fn.body):
            for sub in ast.walk(n):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "rmtree"):
                    cleanup_idx.append(i)
    ok = (main_if is not None and not after and len(returns) == 1
          and bool(cleanup_idx) and min(cleanup_idx) < fn.body.index(returns[0]))
    return ok, {"__main__ 之后": after, "main 顶层 return 数": len(returns),
                "rmtree 位置": cleanup_idx}


_tail_ok, _tail_detail = _tail_static()
_check("S01 收尾块在 main() 内且在 return 之前；__main__ 之后无模块级语句（#438）",
       _tail_ok, _tail_detail)


def _tail_behavior():
    """行为：在**隔离的 TEMP** 下子进程跑一遍本守卫，结论行必须出现、临时目录不得残留。

    这是 #438 的直接判据（不是推演）：缺陷形态下 summary 块在 `sys.exit()` 之后，
    输出里没有「issue #398 结果：」，且 iss398_* 目录留在隔离 TEMP 里。
    """
    d = tempfile.mkdtemp(prefix="iss398_tail_")
    env = dict(os.environ)
    env["PYTHONPATH"] = _REPO
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # 防自递归：子进程只做一层 S02（它再起的孙进程按 depth>=1 跳过 S02）。
    env["MDCG_ISSUE398_TAIL_DEPTH"] = str(
        int(os.environ.get("MDCG_ISSUE398_TAIL_DEPTH", "0")) + 1)
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
              "MDCG_EXPORT_ROOT", "MDCG_TOKEN_FILE", "MDCG_TOKEN", "MDCG_VERIFY_KEY"):
        env.pop(k, None)
    for k in ("TMPDIR", "TEMP", "TMP"):          # tempfile.gettempdir() 的三个来源
        env[k] = d
    try:
        pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                             "md_cg.test_issue398_toolface_op_parity"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", cwd=_REPO, env=env, timeout=900)
        out = (pr.stdout or "") + (pr.stderr or "")
        lines = [ln for ln in out.splitlines() if ln.startswith("issue #398 结果：")]
        leftovers = sorted(x for x in os.listdir(d) if x.startswith("iss398_"))
        ok = (pr.returncode == 0 and len(lines) == 1 and not leftovers)
        return ok, "rc=%d 结论行=%r 残留=%r" % (pr.returncode, lines[:1], leftovers)
    finally:
        shutil.rmtree(d, ignore_errors=True)


_TAIL_DEPTH = int(os.environ.get("MDCG_ISSUE398_TAIL_DEPTH") or 0)
if _TAIL_DEPTH > 0:
    print("  SKIP S02（子进程侧：已有一层 S02 在跑，按 TAIL_DEPTH 跳过，防自递归）")
else:
    _tb_ok, _tb_detail = _tail_behavior()
    _check("S02 隔离 TEMP 下跑完：结论行恰 1 条且 iss398_* 无残留（#438）",
           _tb_ok, _tb_detail)

# ---------------------------------------------------------------- 定点变异表
# 锚点跨行用 chr(10) 拼接；_apply_text 按目标文件实际行尾折算（mcp_server.py 为 CRLF）。
_SELF_OK = '    "mdcg_metacognition": "read", "mdcg_self_state": "self_state",'
_SELF_BAD = '    "mdcg_metacognition": "read", "mdcg_self_state": "read",'
_REC_OK = '    "mdcg_review_records": "review",'
_REC_BAD = '    "mdcg_review_records": "read",'
_READ3_OK = '    "mdcg_recall": "read", "mdcg_search": "read", "mdcg_get": "read",'
_READ3_TIGHT = '    "mdcg_recall": "write", "mdcg_search": "read", "mdcg_get": "read",'
_PROTECT_OK = '    "mdcg_protect": "protect",'
_PROTECT_BAD = '    "mdcg_protect": "read",'
# #438 的回退锚点（M5）：把收尾块搬回模块级、并复现「双 return」缺陷形态。
# 锚点用**逐行拼接**构造（不写成整段三引号字面量）：否则锚点文本会同时出现在
# 「被变异的目标块」与「锚点字面量自身」里，命中数=2 ⇒ M5 永远 ANCHOR-MISS。
def _L(*lines):
    return chr(10).join(lines) + chr(10)


_TAIL_OK = _L(
    '    shutil.rmtree(_TMP, ignore_errors=True)',
    '    print("")',
    '    if FAILS:',
    '        print("issue #398 结果：%d 失败" % len(FAILS))',
    '    else:',
    '        print("issue #398 结果：全部通过（弱化集 %d 条，全部登记在案）" % len(_CUR_WEAK))',
    '    return 1 if (FAILS or _bad) else 0',
    '',
    '',
    'if __name__ == "__main__":',
    '    sys.exit(main())',
)
_TAIL_BAD = _L(
    '    return 1 if (FAILS or _bad) else 0',
    '    return 1 if (FAILS or _bad) else 0',
    '',
    '',
    'if __name__ == "__main__":',
    '    sys.exit(main())',
    'shutil.rmtree(_TMP, ignore_errors=True)',
    'print("")',
    'if FAILS:',
    '    print("issue #398 结果：%d 失败" % len(FAILS))',
    'else:',
    '    print("issue #398 结果：全部通过（弱化集 %d 条，全部登记在案）" % len(_CUR_WEAK))',
)

_MUTATIONS = (
    # M1 回缺陷（站点 1 闸词回 read）⇒ 工具面放行 + self 层真落盘（A03/A04）；
    # 且弱化集新增一条未登记项 ⇒ E03 同红；E06（站点值）也红。
    ("M1 回缺陷：mdcg_self_state 闸词回 read", "md_cg/mcp_server.py",
     ((_SELF_OK, _SELF_BAD),),
     ("A03", "A04", "E03", "E06")),
    # M2 回缺陷（站点 2 闸词回 read）⇒ guest 可调 mdcg_review_records（A06）+ E06。
    # E03 不红（如实）：弱化判定按**同名 op**（review_records 非 op 名）⇒ 本变异不加弱化项。
    ("M2 回缺陷：mdcg_review_records 闸词回 read", "md_cg/mcp_server.py",
     ((_REC_OK, _REC_BAD),),
     ("A06", "E06")),
    # M3 **过度收紧方向**（把 mdcg_recall 收到比真源更严的 write）⇒ 持 read 的令牌被误拒（K01）。
    ("M3 过度收紧：mdcg_recall 收到 write（正常读被误拒）", "md_cg/mcp_server.py",
     ((_READ3_OK, _READ3_TIGHT),),
     ("K01",)),
    # M4 新增一条**未登记**的弱化条目（protect→read）⇒ 全表断言当场报出（E03/E04）。
    ("M4 未登记弱化：mdcg_protect 闸词回 read", "md_cg/mcp_server.py",
     ((_PROTECT_OK, _PROTECT_BAD),),
     ("E03",)),
    # M5 **#438 的回退即红自证**：把收尾块搬回模块级（`sys.exit(main())` 之后）并
    # 复现双 return ⇒ S01（静态：__main__ 之后无模块级语句 / return 前有 rmtree）与
    # S02（行为：隔离 TEMP 下无结论行、iss398_* 残留）必须转红。
    # 本变异显式 tail_depth="0"，让镜像子进程真的跑 S02（其余变异为防递归跳过它）。
    ("M5 #438 回退：收尾块搬回模块级 + 双 return", "md_cg/test_issue398_toolface_op_parity.py",
     ((_TAIL_OK, _TAIL_BAD),),
     ("S01", "S02"), "0"),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss398_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _apply_text(text, rel, pairs):
    """按目标文件实际行尾折算锚点后逐条替换；任一锚点命中数 != 1 返回 (None, 原因)。"""
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _run_in(tree, tail_depth="1"):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # 镜像子进程默认跳过 S02（防递归 + 省时）；M5（收尾块回退）显式给 "0" 让 S02 真跑。
    env["MDCG_ISSUE398_TAIL_DEPTH"] = tail_depth
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT",
              "MDCG_DATA_ROOT", "MDCG_EXPORT_ROOT", "MDCG_TOKEN_FILE"):
        env.pop(k, None)
    # 隔离 TEMP（#438 卫生面）：M5 是**有意复现**「收尾块成死代码」的变异，
    # 该次子进程会按缺陷形态泄漏一个 iss398_*；把镜像运行的 TEMP 指到一次性目录，
    # 使变异腿本身不污染真实 %TEMP%（其余变异与基线在目录删掉时一并回收）。
    _td = tempfile.mkdtemp(prefix="iss398_run_")
    for k in ("TMPDIR", "TEMP", "TMP"):
        env[k] = _td
    try:
        pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                             "md_cg.test_issue398_toolface_op_parity"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", cwd=tree, env=env, timeout=1800)
    finally:
        shutil.rmtree(_td, ignore_errors=True)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：回缺陷（两处）／过度收紧／新增未登记弱化，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-25:]))
        for mut in _MUTATIONS:
            desc, rel, pairs, exp = mut[:4]
            depth = mut[4] if len(mut) > 4 else "1"
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut_src, why = _apply_text(bak, rel, pairs)
            if mut_src is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut_src)
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree, depth)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:12]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


# ---------------------------------------------------------------- R 组：回退即绿自证（实跑，非推演）
# task-16 要求 2（#421 的指控点）：把**被守护的修复**真的回退一次，实跑守卫看是否转红。
# 与上方变异表的区别：变异是「等价改写/过度收紧」，本组是**修复本体回退**。
_REVERT = [
    (("md_cg/mcp_server.py", '    "mdcg_metacognition": "read", "mdcg_self_state": "self_state",', '    "mdcg_metacognition": "read", "mdcg_self_state": "read",')),
    (("md_cg/mcp_server.py", '    "mdcg_review_records": "review",', '    "mdcg_review_records": "read",')),
    ]


def _revert_proof():
    _ok, _det = _kit.assert_revert_reddens(_mirror_build, _REVERT, _run_in,
                                          tuple(["A03","A04","A06","E03","E06"]), "?")
    print("!! 回退即绿自证：把修复本体回退一次，守卫必须转红（实跑）")
    print("  %s  红项=%s" % ("OK  " if _ok else "FAIL", _det.get("实际红项")))
    if not _ok:
        print("  不合格：回退后未按预期转红 —— " + str(_det)[:400])
    return 0 if _ok else 1


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    if "--mutate" in sys.argv and _bad == 0:
        _bad += _revert_proof()
    # 收尾块（#438）：原先它写在模块级、且在一条重复 return 之后 ⇒ 恒为死代码，
    # 既不打结论行也永不回收 _TMP（每次执行泄漏 1 个 iss398_*）。收进 main() 的
    # return 之前，恢复「跑完即清理、末段必有结论行」的可执行语义。
    shutil.rmtree(_TMP, ignore_errors=True)
    print("")
    if FAILS:
        print("issue #398 结果：%d 失败" % len(FAILS))
    else:
        print("issue #398 结果：全部通过（弱化集 %d 条，全部登记在案）" % len(_CUR_WEAK))
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())

