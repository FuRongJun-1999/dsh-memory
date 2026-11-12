# -*- coding: utf-8 -*-
# 功能名：mdcg_ingest 的 source="auto" 必须过 MDCG_INGEST_ROOT 白名单（仅显式配置时）（issue #326-①）
# 生效条件：python -X utf8 -m md_cg.test_issue326_ingest_auto_whitelist [--mutate]；被测面＝md_cg/mcp_server.py 的 mdcg_ingest auto 闸与 md_cg/security.py 的「已显式配置」判据单点 whitelist_root_configured
# 子功能：A 组＝报告逐字行为矩阵（未配白名单 ⇒ auto 放行；配受控目录 ⇒ auto 拒）＋「会话在受控目录内 ⇒ 放行」＋显式路径既有语义不变；K 组＝非恒真对照（过度收紧方向：空白 env/多根/「配了但不含 sessions」都不得把默认 auto 拦死；单点同源一致性；相邻语义不受扰）；E 组＝判据单源源码面（auto 闸不得自己再读一次 env）
# 执行：--mutate 时在镜像树里逐条把闸删掉（回缺陷）/改成无条件过闸（过度收紧），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**
# 不适用条件：不判 ~/.dsh 是 junction 时 realpath 语义差异（报告已说明属既有 check_path_root 语义、非本条引入）；不覆盖 discover_detailed 的排序策略（issue #23 另议）；不判 ingest 的内容面（sources.run）
"""issue #326-① 守卫：auto 分支不是「没有路径」，它扫 ~/.dsh/sessions 并整份 ingest。

病象（修前）：`if src_arg != "auto": check_path_root(...)` —— 把「没有入参」当成了
「没有路径」⇒ 把 root 收紧到受控目录后，`source="auto"` 仍会把白名单之外的跨项目
数据读进来（实测 ~/.dsh/sessions 2474 文件 / ≈469MB）。

**回归陷阱（报告实测）**：修法必须带「**仅在显式配置了 MDCG_INGEST_ROOT 时**才约束
auto」这一条件——未配置时 `_whitelist_roots` 回落「记忆库根」，`~/.dsh/sessions` 不在
其中，无条件过闸会把**默认 `source="auto"` 整个拦死**。本守卫的 A01/K01/K02/K06 与
变异腿 M2 就是钉这条的。

判据单源：`security.whitelist_root_configured` 是「白名单根是否被显式配置」的**单点**，
`_whitelist_roots` 与 auto 闸共用（E 组源码面断言：auto 闸不得自己再读一次 os.environ）。

「守卫必须能在变异态下跑完」（task-8/④ 的教训）：所有取数经 `_call()` 折成可命名形态，
变异态产出**命名红项**而非崩栈。
"""
from __future__ import annotations

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


_TMP = tempfile.mkdtemp(prefix="iss326a_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",   # 末段不得是 Windows 保留设备名
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
os.environ.pop("MDCG_INGEST_ROOT", None)

from md_cg import mcp_server as _ms            # noqa: E402
from md_cg import security as _sec             # noqa: E402
from md_cg import sources as _src              # noqa: E402
from md_cg.mdcos import MdCGOS                 # noqa: E402

_REAL_DISCOVER = _src.DSHSessionSource.discover_detailed

# 受控白名单目录（**不含**会话文件所在目录）与被控会话文件（白名单之外）。
_CTRL = os.path.join(_TMP, "controlled")
_SESS = os.path.join(_TMP, "outside", "sess", "session.jsonl")
os.makedirs(_CTRL, exist_ok=True)
os.makedirs(os.path.dirname(_SESS), exist_ok=True)
with open(_SESS, "w", encoding="utf-8") as _f:
    _f.write(json.dumps({"type": "user",
                        "message": {"content": [{"type": "text", "text": "你好"}]}},
                       ensure_ascii=False) + chr(10))


def _pin_discovery(path):
    """把 auto 的候选来源钉到受控路径（避开本机 ~/.dsh/sessions 是 junction 的干扰）。"""
    _src.DSHSessionSource.discover_detailed = staticmethod(
        lambda root=None, limit=None: [(path, os.path.getsize(path),
                                       os.path.getmtime(path))])


def _call(name="mdcg_ingest", **kw):
    """调 _dispatch：正常返回 ("", 结果)；抛异常（含 BaseException）返回 (类型名, 文本)。"""
    cg = MdCGOS(os.path.join(_TMP, "brain"))
    try:
        return "", _ms._dispatch(cg, name, dict(kw))
    except BaseException as exc:                 # noqa: BLE001 —— 变异态不得崩栈
        return type(exc).__name__, str(exc)


def _env(value):
    """把 MDCG_INGEST_ROOT 置为 value（None = 移除）。"""
    if value is None:
        os.environ.pop("MDCG_INGEST_ROOT", None)
    else:
        os.environ["MDCG_INGEST_ROOT"] = value


_pin_discovery(_SESS)

print("== A 组：#326-① 正题——报告逐字行为矩阵 ==")
_env(None)
_e1, _r1 = _call()
_check("A01 矩阵第 1 行｜未配 MDCG_INGEST_ROOT ⇒ auto **放行**（默认工作流不受影响）",
       _e1 == "" and isinstance(_r1, dict) and "new_events" in _r1, (_e1, str(_r1)[:80]))
_env(_CTRL)
_e2, _r2 = _call()
_check("A02 矩阵第 2 行｜配受控目录（不含 sessions）⇒ auto **拒**（PermissionError 点名白名单）",
       _e2 == "PermissionError" and "MDCG_INGEST_ROOT" in _r2, (_e2, str(_r2)[:120]))
# 会话**在**白名单内时应放行（闸不是无条件拒 auto）
_CTRL_SESS_DIR = os.path.join(_CTRL, "sess")
os.makedirs(_CTRL_SESS_DIR, exist_ok=True)
_IN_SESS = os.path.join(_CTRL_SESS_DIR, "session.jsonl")
shutil.copyfile(_SESS, _IN_SESS)
_pin_discovery(_IN_SESS)
_e3, _r3 = _call()
_check("A03 会话落在受控目录**内** ⇒ auto 放行（不是无条件拒 auto）",
       _e3 == "" and isinstance(_r3, dict), (_e3, str(_r3)[:80]))
_pin_discovery(_SESS)
_e4, _r4 = _call(source=_SESS)
_check("A04 显式路径（白名单外）⇒ 仍拒（既有语义未被削弱）",
       _e4 == "PermissionError", (_e4, str(_r4)[:100]))
_e5, _r5 = _call(source=_IN_SESS)
_check("A05 显式路径（白名单内）⇒ 仍放行", _e5 == "" and isinstance(_r5, dict),
       (_e5, str(_r5)[:80]))
_env(None)
_e6, _r6 = _call(source=_SESS)
_check("A06 未配白名单 ＋ 显式路径（库外）⇒ 仍按回落根拒（#351/既有语义不变）",
       _e6 == "PermissionError", (_e6, str(_r6)[:100]))

print("== K 组：非恒真对照（过度收紧方向——不得把默认 auto 拦死） ==")
# 空白 env ≡ 未配（与 _whitelist_roots 的 raw 口径同源）
_env("   ")
_e7, _r7 = _call()
_check("K01 空白 env（MDCG_INGEST_ROOT="   "）≡ 未配 ⇒ auto 仍放行",
       _e7 == "" and isinstance(_r7, dict), (_e7, str(_r7)[:80]))
_env("")
_e8, _r8 = _call()
_check("K02 空串 env（键存在但为空）⇒ 仍视为未配、auto 放行",
       _e8 == "" and isinstance(_r8, dict), (_e8, str(_r8)[:80]))
# 多根：其中一段含会话目录 ⇒ 放行（os.pathsep 多根语义未被破坏）
_env(_CTRL + os.pathsep + os.path.dirname(_SESS))
_e9, _r9 = _call()
_check("K03 os.pathsep 多根且有一段覆盖会话目录 ⇒ auto 放行（多根语义不变）",
       _e9 == "" and isinstance(_r9, dict), (_e9, str(_r9)[:90]))
# 配了白名单但**不含**会话 ⇒ 必须拒（不得因「目录不存在」等任何理由放行）
_env(os.path.join(_TMP, "nowhere-not-exist"))
_e10, _r10 = _call()
_check("K04 配了不存在的受控根 ⇒ auto 拒（不因路径不存在而放行）",
       _e10 == "PermissionError", (_e10, str(_r10)[:100]))
_env(_CTRL)
_e11, _r11 = _call(source=os.path.join(_CTRL, "sub", "..", "x.jsonl"))
_check("K05 realpath 语义未被绕开①：受控根内的 `..` 形态路径 ⇒ 放行",
       _e11 == "" and isinstance(_r11, dict), (_e11, str(_r11)[:90]))
_e12, _r12 = _call(source=os.path.join(_CTRL, "..", "outside", "sess", "session.jsonl"))
_check("K06 realpath 语义未被绕开②：形似在根内、realpath 落在根外 ⇒ 拒",
       _e12 == "PermissionError", (_e12, str(_r12)[:100]))
# 「已配」判据单点自洽：三态取值 与 _whitelist_roots 是否走 env 分支**逐态一致**
_env(None)
_c_unset = _sec.whitelist_root_configured("MDCG_INGEST_ROOT")
_r_unset = _sec._whitelist_roots("MDCG_INGEST_ROOT")
_env("   ")
_c_blank = _sec.whitelist_root_configured("MDCG_INGEST_ROOT")
_r_blank = _sec._whitelist_roots("MDCG_INGEST_ROOT")
_env(_CTRL)
_c_set = _sec.whitelist_root_configured("MDCG_INGEST_ROOT")
_r_set = _sec._whitelist_roots("MDCG_INGEST_ROOT")
_env(None)
_check("K07 判据单点自洽：已配 ⇒ _whitelist_roots 恰为 env 根；未配/空白 ⇒ 走回落链（非 env 根）",
       _c_set is True and _r_set == [os.path.realpath(os.path.expanduser(_CTRL))]
       and _c_unset is False and _c_blank is False
       and _r_unset != _r_set and _r_blank != _r_set,
       (_c_unset, _c_blank, _c_set, _r_set, _r_unset))


print("== E 组：判据单源（源码面） ==")


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


_Q = chr(34)
_ENV_LITERAL = "os.environ.get(" + _Q + "MDCG_INGEST_ROOT" + _Q + ")"
_check("E01 whitelist_root_configured 是 security 的模块级可调用单点",
       callable(getattr(_sec, "whitelist_root_configured", None)), "")
_check("E02 _whitelist_roots 复用该单点（不自己再判一次「已配」）",
       "if whitelist_root_configured(env_var):" in _src("md_cg/security.py"), "")
_check("E03 mdcg_ingest 的 auto 闸经该单点（源码含 whitelist_root_configured(MDCG_INGEST_ROOT)）",
       "whitelist_root_configured(" + _Q + "MDCG_INGEST_ROOT" + _Q + ")"
       in _src("md_cg/mcp_server.py"), "")
_check("E04 auto 闸**不得**自己再读一次 env（字面 os.environ.get(MDCG_INGEST_ROOT) 仍只 1 处＝#351 那处）",
       _src("md_cg/mcp_server.py").count(_ENV_LITERAL) == 1,
       _src("md_cg/mcp_server.py").count(_ENV_LITERAL))

shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #326-① 结果：%d 失败" % len(FAILS))
else:
    print("issue #326-① 结果：全部通过")


# ---------------------------------------------------------------- 定点变异表
# 锚点跨行用 chr(10) 拼接；_apply_text 按目标文件**实际行尾**折算（mcp_server.py 为 CRLF）。
_GATE = chr(10).join([
    "            # 发现到的会话路径过**同一条**白名单闸（仅在显式配置时——见上）。",
    "            if whitelist_root_configured(\"MDCG_INGEST_ROOT\"):",
    "                check_path_root(picked[0], \"MDCG_INGEST_ROOT\", \"mdcg_ingest\")",
])
_GATE_OFF = "            # 变异：删掉 auto 闸（回到「auto 不经路径参数」的缺陷形态）"
_GATE_ALWAYS = chr(10).join([
    "            # 变异：无条件过闸（去掉「仅显式配置时」条件——报告实测的回归陷阱）",
    "            check_path_root(picked[0], \"MDCG_INGEST_ROOT\", \"mdcg_ingest\")",
])

_MUTATIONS = (
    # M1 删闸（回缺陷）⇒ auto 不再过白名单：矩阵第 2 行（配受控目录仍放行）转红；
    # E03（源码面「经单点」）同步转红；K04（配了受控根 ⇒ 必须拒）也随之转红——
    # 闸没了，任何配置都不再拒。恒绿项如实说明：第 1 行（未配 ⇒ 放行）两态皆放行。
    ("M1 删闸（回缺陷：auto 不经路径参数）", "md_cg/mcp_server.py",
     ((_GATE, _GATE_OFF),),
     ("A02", "E03", "K04")),
    # M2 无条件过闸（过度收紧）⇒ 未配时 ~/.dsh/sessions 不在回落根内、默认 auto 被拦死：
    # 矩阵第 1 行与「未配/空白 env ⇒ auto 放行」项转红，E03（源码面「经单点」）同步转红。
    # 恒绿项如实说明：A02（配受控目录 ⇒ 拒）两态皆拒；K03（多根覆盖会话目录）本就被放行。
    ("M2 无条件过闸（过度收紧：默认 auto 被拦死）", "md_cg/mcp_server.py",
     ((_GATE, _GATE_ALWAYS),),
     ("A01", "E03", "K01", "K02")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss326a_mut_")
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


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT",
              "MDCG_DATA_ROOT", "MDCG_EXPORT_ROOT", "MDCG_INGEST_ROOT"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue326_ingest_auto_whitelist"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把 auto 闸改成缺陷/过度收紧形态，守卫必须按指定项转红")
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
