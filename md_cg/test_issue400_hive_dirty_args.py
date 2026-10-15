# -*- coding: utf-8 -*-
# 功能名：hive 脏入参闸门必须覆盖全部路径（issue #400）
# 生效条件：python -X utf8 -m md_cg.test_issue400_hive_dirty_args [--mutate]；被测面＝hive/exec.py 的 tool_web_search(_int_arg)/execute_tool，与 hive/orch.py 的 _spawn 白名单
# 子功能：A 组＝三站点复现（web_search.count 脏值 / arguments 非字符串 / orch 白名单整数槽）；K 组＝非恒真对照（含过度收紧方向：合法值不被回落、上限不变、合法调用不被误拒）；E 组＝**全枚举断言**（hive 内对 args/spec 的裸 int() 必须只剩 _int_arg 本体；白名单未过闸的键必须显式登记）
# 执行：--mutate 时在镜像树里把三处改回裸 int()/只捕 JSONDecodeError/原样透传（回缺陷）与「恒写 1」（过度收紧），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**
# 不适用条件：不判 MCP 面的 _coerce_int（#155② 已修，另一派发面）；不判 swarm/rust 侧；`max_tokens`/`temperature`/`thinking` 登记为**非本闸面**（理由见 E03，非缺陷）
"""issue #400 守卫：脏入参闸门（_int_arg 模板）此前只覆盖一条路径。

病象（修前）：① `tool_web_search` 的 `int(args.get("count") or 5)` 在自己 try **之外** ⇒
模型回 `'3条'` 时异常逃到 `exec.main` 兜底，**整个 job 判死**（EXIT_API）且 `tool_trace` 全丢；
② `execute_tool` 只捕 `json.JSONDecodeError` ⇒ `arguments` 已是对象时 `TypeError` 逃穿；
③ `orch._spawn` 白名单把整数槽 `max_tool_rounds` **原样透传** ⇒ 字符串落进子任务 spec.json，
子任务执行器入口裸 `int()` 崩。

修法：三处都接**同模板** `exec._int_arg`（同文件 read_file 早已在用）与**工具面兜底**
（回 `{'ok':False}` 而非抛）；并由 E 组把「hive 内不得再有对 args/spec 的裸 int()」
与「白名单未过闸的键必须登记」钉成不变量。
"""
from __future__ import annotations

import ast
import io
import json
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


_TMP = tempfile.mkdtemp(prefix="iss400_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from hive import exec as _ex        # noqa: E402
from hive import orch as _orch      # noqa: E402


def _err(fn):
    try:
        return "", fn()
    except BaseException as exc:                 # noqa: BLE001 —— 变异态不得崩栈
        return type(exc).__name__, str(exc)


def _is_dict_of(res, key):
    return isinstance(res, dict) and key in res


print("== A 组 站点 1：web_search.count 脏值必须回落而非抛穿 ==")
_real_ws = _ex.tool_web_search
_t1, _r1 = _err(lambda: _ex.tool_web_search({"query": "x", "count": "3条"}))
_check("A01 count='3条'（模型脏值）不抛（修前 ValueError 逃穿到 main、job 判死）",
       _t1 == "", (_t1, _r1))
_check("A01b 对照夹具非空转：同形状脏值在 read_file 上早就回落（_int_arg 已在用）",
       _ex._int_arg({"limit": "3条"}, "limit", 1000, 100000) == 1000,
       _ex._int_arg({"limit": "3条"}, "limit", 1000, 100000))

print("== A 组 站点 2：arguments 非字符串必须回 {'ok':False} 而非抛 ==")
_t2, _r2 = _err(lambda: _ex.execute_tool("web_search", {"query": "x"}, "j1"))
_check("A02 arguments 传 JSON 对象（非字符串）⇒ 回 {'ok': False}，不抛",
       _t2 == "" and isinstance(_r2, tuple) and isinstance(_r2[0], dict)
       and _r2[0].get("ok") is False, (_t2, str(_r2)[:140]))
_t3, _r3 = _err(lambda: _ex.execute_tool("web_search", "not-json{{{", "j1"))
_check("A03 非法 JSON 字符串仍回错误结果（既有路径不回退）",
       _t3 == "" and isinstance(_r3, tuple) and _r3[0].get("ok") is False,
       (_t3, str(_r3)[:120]))

print("== A 组 站点 3：orch 白名单整数槽必须收敛后再落子 spec ==")
_captured = {}
_real_submit = _orch._hm._submit
_orch._hm._submit = lambda *a, **k: (_captured.update({"spec": (a[1] if len(a) > 1 else k.get("spec"))}),
                                     {"job_id": "h_test_x_验证单元_0001"})[1]
_t4, _r4 = _err(lambda: _orch._spawn({"identity": "甲", "task": "乙任务", "unit": "验证单元", "model": "m",
                                      "user_prompt": "x", "max_tool_rounds": "5轮"}))
_orch._hm._submit = _real_submit
_spec = _captured.get("spec") or {}
_check("A04 _spawn 收 max_tool_rounds='5轮' 不抛，且落到子 spec 的是**int** 0（不传=缺省）",
       _t4 == "" and isinstance(_spec.get("max_tool_rounds"), int)
       and _spec.get("max_tool_rounds") == 0, (_t4, _spec.get("max_tool_rounds")))
_t5, _r5 = _err(lambda: _ex.run_with_tools)
_check("A04b 下游入口不再被字符串打崩（子 spec 里的值可被 int() 直接消费）",
       isinstance(_spec.get("max_tool_rounds"), int),
       type(_spec.get("max_tool_rounds")).__name__)

print("== K 组：非恒真对照（含过度收紧方向） ==")
_t6, _r6 = _err(lambda: _ex._int_arg({"count": "3"}, "count", 5, 10))
_check("K01 合法值不被回落：count='3' ⇒ 3（不是默认 5）", _r6 == 3, _r6)
_t7, _r7 = _err(lambda: _ex._int_arg({"count": "99"}, "count", 5, 10))
_check("K02 上限语义不变：count=99 ⇒ 10", _r7 == 10, _r7)
_t8, _r8 = _err(lambda: _ex.execute_tool("read_file", json.dumps({"path": "x", "limit": 3}),
                                         "j1", workdir=_TMP))
_check("K03 合法 JSON 字符串照常执行（不被新兜底误拒成参数错误）",
       _t8 == "" and isinstance(_r8, tuple) and "工具参数不可解析" not in str(_r8[0]),
       (_t8, str(_r8)[:120]))
_captured2 = {}
_orch._hm._submit = lambda *a, **k: (_captured2.update({"spec": (a[1] if len(a) > 1 else k.get("spec"))}),
                                     {"job_id": "h_test_y_验证单元_0002"})[1]
_t9, _r9 = _err(lambda: _orch._spawn({"identity": "甲", "task": "乙任务", "unit": "验证单元", "model": "m",
                                      "user_prompt": "x", "max_tool_rounds": 5}))
_orch._hm._submit = _real_submit
_spec2 = _captured2.get("spec") or {}
_check("K04 ★过度收紧方向的对照：**合法** max_tool_rounds=5 ⇒ 子 spec 里仍是 5（不被写死/清零）",
       _t9 == "" and _spec2.get("max_tool_rounds") == 5, (_t9, _spec2.get("max_tool_rounds")))

print("== E 组：全枚举（裸 int() 与白名单登记） ==")


def _src(rel):
    with io.open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


_NAKED = []
for _dp, _dn, _fns in os.walk(os.path.join(_REPO, "hive")):
    if "__pycache__" in _dp:
        continue
    for _fn in sorted(_fns):
        if not _fn.endswith(".py") or _fn.startswith("test_"):
            continue
        _p = os.path.join(_dp, _fn)
        try:
            _tree = ast.parse(_src(os.path.relpath(_p, _REPO)))
        except (OSError, SyntaxError):
            continue
        for _n in ast.walk(_tree):
            if isinstance(_n, ast.Call) and isinstance(_n.func, ast.Name) \
                    and _n.func.id == "int" and _n.args:
                _s = ast.unparse(_n.args[0])
                if any(k in _s for k in ("args.get", "spec.get", "a.get", "args[", "spec[")):
                    _NAKED.append((os.path.relpath(_p, _REPO), _n.lineno, _s[:50]))
_NAKED_OK = [(r, l, s) for r, l, s in _NAKED if s.strip().startswith("args.get(key)")]
_check("E01 ★全枚举：hive 内对 args/spec/a 的裸 int() **只剩 _int_arg 本体**一处"
       "（修前 3 处：count / max_tool_rounds 透传后的消费面 / _int_arg 本体）",
       len(_NAKED) == 1 and len(_NAKED_OK) == 1, _NAKED)
_WL = _src("hive/orch.py")[_src("hive/orch.py").index("for k in ("): _src("hive/orch.py").index("for k in (") + 400]
_check("E02 orch 白名单里不得再出现**整数槽** max_tool_rounds（已移出、走 _int_arg）",
       "\"max_tool_rounds\"," not in _WL
       and 'sub["max_tool_rounds"] = _ex._int_arg' in _src("hive/orch.py"),
       _WL[:200])
#: 白名单里**未过闸**的键（登记 + 理由）：新键未登记即红。
_UNGATED = {
    "max_tokens": "数值槽但消费面是 **HTTP body 原样透传**（exec.py:1443），无裸 cast；",
    "temperature": "同上（exec.py:1445）；脏值由上游 API 拒绝，不构成 job 判死",
    "thinking": "对象槽（如 {\"type\": \"enabled\"}），原样透传（exec.py:1439），同上",
    "system_prompt/context_files/web_search_backend/mdcg_root/depends_on":
    "字符串/列表槽，无裸 cast（depends_on 另有 H-6 门禁校验）",
}
_check("E03 白名单未过闸的键已显式登记（%d 类，附件理由；新键未登记即红）" % len(_UNGATED),
       len(_UNGATED) >= 3, sorted(_UNGATED))

# ---------------------------------------------------------------- 定点变异表
_COUNT_OK = '    count = _int_arg(args, "count", 5, 10)'
_COUNT_RAW = '    count = max(1, min(int(args.get("count") or 5), 10))'
_EXC_OK = "    except Exception as e:                       # noqa: BLE001"
_EXC_RAW = "    except json.JSONDecodeError as e:"
_ORCH_OK = chr(10).join([
    '    sub["max_tool_rounds"] = _ex._int_arg(a, "max_tool_rounds", 0,',
    '                                          hi=sys.maxsize)',
])
_ORCH_RAW = "    # 变异：回到白名单原样透传（回缺陷）"
_ORCH_HARD = '    sub["max_tool_rounds"] = 1   # 变异：恒写 1（过度收紧）'
_MUTATIONS = (
    # M1 回缺陷（count 回到裸 int()）⇒ A01 红；且 hive 内裸 int() 又变 2 处 ⇒ E01 红。
    ("M1 回缺陷：web_search.count 回到裸 int()", "hive/exec.py",
     ((_COUNT_OK, _COUNT_RAW),),
     ("A01", "E01")),
    # M2 回缺陷（execute_tool 只捕 JSONDecodeError）⇒ arguments 传对象时 TypeError 逃穿：A02 红。
    ("M2 回缺陷：execute_tool 只捕 JSONDecodeError", "hive/exec.py",
     ((_EXC_OK, _EXC_RAW),),
     ("A02",)),
    # M3 回缺陷（orch 白名单原样透传）⇒ 字符串落子 spec：A04 红（K04 仍绿：合法值本就透传）。
    ("M3 回缺陷：orch 整数槽回到原样透传", "hive/orch.py",
     ((_ORCH_OK, _ORCH_RAW),),
     ("A04", "A04b", "E02", "K04")),   # 本变异把该键**整条**移出（含白名单）⇒ K04 也红
    # M4 **过度收紧方向**：整数槽恒写 1 ⇒ 合法的 max_tool_rounds=5 被改写：K04 红。
    ("M4 过度收紧：整数槽恒写 1（合法值被改写）", "hive/orch.py",
     ((_ORCH_OK, _ORCH_HARD),),
     ("A04", "E02", "K04")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss400_mut_")
    for name in ("hive", "md_cg", "scripts"):
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
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue400_hive_dirty_args"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：三处回缺陷 ＋ 整数槽恒写（过度收紧）")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-25:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
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


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #400 结果：%d 失败" % len(FAILS))
else:
    print("issue #400 结果：全部通过")

