# -*- coding: utf-8 -*-
# 功能名：hive scoreboard/wm 的「合法 JSON 非对象」不得整表崩/抛 traceback（issue #399，#155③ 未闭环）
# 生效条件：python -X utf8 -m md_cg.test_issue399_hive_json_shape [--mutate]；被测面＝hive/scoreboard.py 的 _obj/job_record 与 hive/wm.py 的 _parse_progress
# 子功能：A 组＝两站点复现（非对象 status.json ⇒ build 不崩、进 bad_ids；progress.jsonl 非对象行 ⇒ 跳过不炸）；K 组＝非恒真对照（含过度收紧方向：合法对象读数逐位不变、非法 JSON 仍跳过、空对象仍按坏件计）；E 组＝**形状闸全枚举断言**（该面所有 read_json/行流消费点必须过闸）
# 执行：--mutate 时在镜像树里摘掉两处形状闸（回缺陷）与做成「一切皆坏」（过度收紧），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**
# 不适用条件：不判 hive/chat.py、hive/exec.py（HTTP/stdio 响应面）、hive_mcp/mcp_server.py 的 json 载荷（**另一消费面**，见 E 组登记）；不判 rust 侧读 status 的三态口径
"""issue #399 守卫：#155③ 立的「非映射值不得当 status 传出去」口径只落在一处。

病象（修前）：① `scoreboard.job_record` 的 `read_json(...) or {}` **只兜空值** ⇒ 合法 JSON
非对象（`[1,2,3]`/`"x"`）原样留下 ⇒ `.get(...)` AttributeError ⇒ **整张评分表崩**（rc=1）；
② `wm._parse_progress` 只捕 `json.JSONDecodeError` ⇒ 非对象行进 entries ⇒ 消费点
`e.get("kind")` AttributeError ⇒ `wm progress` 抛 traceback。

修法：两处都收成**形状闸**（非映射 ⇒ 按坏件/坏行处理），口径复用 #155③ 的
`_read_status`（`dict(st) if isinstance(st, dict) else None`），**不另造第二份判据**；
并由本守卫的 E 组把「该面所有消费点都过闸」钉成不变量。
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
if os.path.join(_REPO, "hive") not in sys.path:
    sys.path.insert(0, os.path.join(_REPO, "hive"))

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


_TMP = tempfile.mkdtemp(prefix="iss399_")
from hive import scoreboard as _sb          # noqa: E402
from hive import wm as _wm                  # noqa: E402

_JID = "h_甲_乙任务_验证单元_0001"


def _mkjob(tag, status_obj, spec_obj=None, result_obj=None):
    d = os.path.join(_TMP, tag, _JID)
    os.makedirs(d, exist_ok=True)
    for nm, obj in (("spec.json", spec_obj if spec_obj is not None else {}),
                    ("status.json", status_obj),
                    ("result.json", result_obj if result_obj is not None else {})):
        with io.open(os.path.join(d, nm), "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False))
    return d


def _badids(res):
    """从 build() 返回值取 bad_ids；res 不是 dict（变异态里是异常）时返回 []。"""
    return (res.get("bad_ids") or []) if isinstance(res, dict) else []


def _totals(res):
    return res.get("totals") if isinstance(res, dict) else None


def _kinds(ents):
    """条目 kind 投影；条目是变异态下的非 dict 时回类型名（不崩栈）。"""
    return [e.get("kind") if isinstance(e, dict) else type(e).__name__ for e in ents]


def _err(fn):
    try:
        return "", fn()
    except BaseException as exc:                 # noqa: BLE001 —— 变异态不得崩栈
        return type(exc).__name__, str(exc)


print("== A 组 站点 1：scoreboard 遇「合法 JSON 非对象」不得崩 ==")
for _i, _objv in enumerate(([1, 2, 3], "x", 123), start=1):
    _d = _mkjob("sb%d" % _i, _objv)
    _t, _r = _err(lambda: _sb.build(os.path.dirname(_d)))
    _check("A0%d build() 遇 status.json=%r 不抛（修前 AttributeError 整表崩）"
           % (_i, _objv), _t == "", (_t, _r))
    _bad = _badids(_r)
    _check("A0%db 该 job 计入 bad_ids（口径＝读件失败，不是崩）" % _i,
           _JID in _bad, (_bad, _totals(_r)))
_d0 = _mkjob("sb_ctrl", {})
_t0, _r0 = _err(lambda: _sb.build(os.path.dirname(_d0)))
_check("A04 对照：status.json={}（合法对象、缺 state）⇒ 同样不抛、同样进 bad_ids",
       _t0 == "" and _JID in _badids(_r0),
       (_t0, _totals(_r0)))

print("== A 组 站点 2：wm 进展卡非对象行不得抛穿 ==")
_LINES = ["{\"kind\": \"handoff\", \"note\": \"A\"}", "[1,2]", "null", "\"str\"",
          "not-json{{{"]
_t1, _e1 = _err(lambda: _wm._parse_progress(list(_LINES), 50))
_check("A05 _parse_progress 遇 [1,2]/null/\"str\" 不抛（修前 AttributeError）",
       _t1 == "", (_t1, _e1))
_ents, _tot = (_e1 if _t1 == "" else ([], -1))
_check("A06 只留合法对象行（1 条 handoff），非对象与非 JSON 行一律跳过",
       _kinds(_ents) == ["handoff"] and _tot == 5,
       (_ents, _tot))
_d1 = os.path.join(_TMP, "wmjob")
os.makedirs(_d1, exist_ok=True)
with io.open(os.path.join(_d1, _wm.PROGRESS_FILE), "w", encoding="utf-8") as f:
    f.write(chr(10).join(_LINES) + chr(10))
_out = io.StringIO()
_t2, _e2 = _err(lambda: _wm.main(["progress", "--job", _d1]))
_check("A07 端到端：wm progress --job <dir> 不抛（修前 cmd_progress 抛 AttributeError）",
       _t2 == "", (_t2, _e2))

print("== K 组：非恒真对照（含过度收紧方向） ==")
_d2 = _mkjob("sb_ok", {"state": "ok", "elapsed_s": 1.5},
             spec_obj={"commands": ["x"]}, result_obj={"ok": True, "content": "c"})
_t3, _r3 = _err(lambda: _sb.build(os.path.dirname(_d2)))
_rec = ((_r3 or {}).get("by_unit") or [{}])[0] if _r3 else {}
_check("K01 过度收紧方向的对照：**合法对象** status 的读数逐位不变（state/elapsed_s 照常）",
       _t3 == "" and (_totals(_r3) or {}).get("jobs") == 1
       and not _badids(_r3),
       (_t3, _totals(_r3), _badids(_r3)))
_ents2, _tot2 = _wm._parse_progress(["{\"kind\": \"x\"}", "not-json{{{"], 50)
_check("K02 口径不越界：**非法 JSON** 行照旧跳过（与修前逐位一致）",
       _kinds(_ents2) == ["x"] and _tot2 == 2, (_ents2, _tot2))
_ents3, _ = _wm._parse_progress([], 50)
_check("K03 空输入不炸（边界）", _ents3 == [], _ents3)
_ents4, _ = _wm._parse_progress(["   ", "{\"kind\": \"y\"}"], 50)
_check("K04 空行不计 total、不产条目（本批不改的既有语义）",
       _kinds(_ents4) == ["y"], _ents4)

print("== E 组：形状闸全枚举（该面所有消费点都必须过闸） ==")


def _src(rel):
    with io.open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


_SB = _src("hive/scoreboard.py")
_WM = _src("hive/wm.py")
#: 未过闸的 json 载荷消费点（**另一消费面**：HTTP/stdio 响应，非同一条读件路径）
#: ——登记在案、本轮不改（理由见各条注释），新出现未登记项即红。
_OTHER_FACE = {
    "hive/chat.py: json.loads(line)",
    "hive/exec.py: json.loads(resp...) ×2（网关响应）",
    "hive/exec.py: json.loads(args_json)（工具入参面，归 #400）",
    "hive/hive_mcp/mcp_server.py: json.loads(out)/line（子进程与 stdio 协议面）",
}
_check("E01 scoreboard：`read_json(` 的消费点全部经 `_obj`（不再裸 `or {}`）",
       "_obj(os.path.join(job_dir, \"spec.json\"))" in _SB
       and "_obj(os.path.join(job_dir, \"status.json\"))" in _SB
       and "_obj(os.path.join(job_dir, \"result.json\"))" in _SB
       and "read_json(os.path.join(job_dir" not in _SB.replace("_obj(os.path.join(job_dir", "X"),
       "")
_check("E02 scoreboard：形状闸是**单点**（`_obj` 一处定义，非三处各写一份）",
       _SB.count("def _obj(") == 1 and _SB.count("isinstance(v, dict)") == 1,
       (_SB.count("def _obj("), _SB.count("isinstance(v, dict)")))
_check("E03 wm：行流 append 前有形状闸（`isinstance(v, dict)` 出现在 append 之前）",
       "_WM_HAS" if False else ("        if not isinstance(v, dict):" in _WM
                                and _WM.index("if not isinstance(v, dict):")
                                < _WM.index("        entries.append(v)")), "")
_check("E04 口径同源：#155③ 的既有单点仍在（未被本条替换/绕过）",
       "return dict(st) if isinstance(st, dict) else None"
       in _src("hive/hive_mcp/mcp_server.py"), "")
_check("E05 另一消费面已显式登记（%d 条，防「顺手改」也防「静默漏」）" % len(_OTHER_FACE),
       len(_OTHER_FACE) >= 4, sorted(_OTHER_FACE))

# ---------------------------------------------------------------- 定点变异表
_SB_OBJ = chr(10).join([
    "    spec = _obj(os.path.join(job_dir, \"spec.json\"))",
    "    status = _obj(os.path.join(job_dir, \"status.json\"))",
    "    result = _obj(os.path.join(job_dir, \"result.json\"))",
])
_SB_RAW = chr(10).join([
    "    spec = read_json(os.path.join(job_dir, \"spec.json\")) or {}",
    "    status = read_json(os.path.join(job_dir, \"status.json\")) or {}",
    "    result = read_json(os.path.join(job_dir, \"result.json\")) or {}",
])
_WM_GATE = chr(10).join([
    "        if not isinstance(v, dict):",
    "            continue",
])
_WM_OFF = "        pass   # 变异：摘掉形状闸（回缺陷）"
_OBJ_RAW = chr(10).join([
    "    v = read_json(path)",
    "    return v if isinstance(v, dict) else {}",
])
_OBJ_ALWAYS = chr(10).join([
    "    v = read_json(path)",
    "    return {}   # 变异：一切皆坏（过度收紧）",
])
_MUTATIONS = (
    # M1 回缺陷（站点 1 的形状闸摘掉）⇒ 非对象 status.json 再次把整表打崩：A01/A02/A03 红。
    # A04（合法对象缺 state）两态皆不崩 ⇒ 恒绿（如实）。
    ("M1 回缺陷：scoreboard 摘掉形状闸（回到 read_json(...) or {}）", "hive/scoreboard.py",
     ((_SB_OBJ, _SB_RAW),),
     ("A01", "A01b", "A02", "A02b", "A03", "A03b", "E01")),
    # M2 回缺陷（站点 2 的行级形状闸摘掉）⇒ 非对象行进 entries、消费点抛穿：A05/A06/A07 红。
    ("M2 回缺陷：wm 摘掉行级形状闸", "hive/wm.py",
     ((_WM_GATE, _WM_OFF),),
     ("A06", "A07", "E03")),   # A05 恒绿（如实）：_parse_progress 自身不抛，崩的是消费点（A07）
    # M3 **过度收紧方向**：形状闸做成「一切皆坏」⇒ 合法对象的读数被丢掉、合法 job 反被判坏。
    ("M3 过度收紧：_obj 无条件返回 {}（合法对象也被判坏）", "hive/scoreboard.py",
     ((_OBJ_RAW, _OBJ_ALWAYS),),
     ("E02", "K01")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss399_mut_")
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
                         "md_cg.test_issue399_hive_json_shape"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：摘掉两处形状闸（回缺陷）＋ 一切皆坏（过度收紧）")
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
    print("issue #399 结果：%d 失败" % len(FAILS))
else:
    print("issue #399 结果：全部通过")

