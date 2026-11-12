# -*- coding: utf-8 -*-
# 功能名：hive serve_start.status() 的 job_states 对「合法 JSON 非映射」status.json 不得抛穿（issue #427）
# 生效条件：python -X utf8 -m md_cg.test_issue427_serve_status_shape [--mutate]；被测面＝hive/serve_start.py::status() 的 status.json 遍历段
# 子功能：A 组＝四种非映射载荷（list/str/null/number）复现（修前 AttributeError 打崩 --status）；K 组＝非恒真对照（合法对象照常计数、非法 JSON 照旧跳过、缺 state 记 "?" 语义不变、混合池只跳坏件）；E 组＝锚点自检（形状闸字面量必须在源码里，缺失即 exit 2）
# 执行：默认断言；--mutate 在内存源码里把形状闸摘掉（回缺陷）与做成「一切皆跳过」（过度收紧），红项须与预期逐项相符
# 验证方式：默认全 PASS 且 exit 0；--mutate 每条变异的红项集合与声明一致
# 不适用条件：不判 heartbeat/serve_alive 三层判据（hive/test_serve_entry.py 覆盖）；不判 Rust 侧 serve 对同输入的行为；不判 CLI 端到端退出码（本守卫直调 status()，CLI 无 try 为静态事实）
"""issue #427 守卫：`serve_start.status()` 对「合法 JSON 非映射」status.json 抛 AttributeError。

病象（修前）：`st = json.load(f).get("state", "?")` —— `[1,2,3]`/`"x"`/`null`/`123` 是
**合法 JSON**，`json.load` 正常返回非 dict，`.get` 抛 AttributeError；而 except 只捕
`(OSError, ValueError)` ⇒ 异常逃出 ⇒ `--status` 整条命令崩（运维观测面在盘面损坏时失效）。

修法：读回值先过形状闸（非映射 ⇒ 按读件失败跳过），判据与 `scoreboard._obj` 同口径
（#399/#155③），**不静默归一成 "?"**（归一会让坏件伪装成正常缺 state 的作业）。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO, "hive", "serve_start.py")
_JID = "h_u09_任务_验证单元_0001"
_FAILS = []


def ok(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        _FAILS.append(name.split()[0])


def _load(src_text, name="ss427"):
    mod = types.ModuleType(name)
    mod.__file__ = _SRC
    exec(compile(src_text, "<ss427>", "exec"), mod.__dict__)
    return mod


def _pool(root, payloads):
    """payloads: [(dirname, kind, value)]；kind=obj/raw/missing。返回池路径（job 目录直接位于池下）。"""
    jobs = os.path.join(root, "jobs")
    os.makedirs(jobs, exist_ok=True)
    for dirname, kind, val in payloads:
        d = os.path.join(jobs, dirname)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "status.json")
        if kind == "missing":
            continue
        with io.open(p, "w", encoding="utf-8") as f:
            if kind == "raw":
                f.write(val)
            else:
                json.dump(val, f, ensure_ascii=False)
    return jobs


def _status(mod, jobs):
    mod.serve_alive = lambda *_a, **_k: True     # stub：本守卫只测 job_states 遍历面
    try:
        return "", mod.status(jobs)
    except BaseException as exc:                  # noqa: BLE001 —— 变异态不得崩栈
        return type(exc).__name__, str(exc)


def run_checks(mod):
    root = tempfile.mkdtemp(prefix="iss427_")
    try:
        for i, payload in enumerate(([1, 2, 3], "x", None, 123), start=1):
            jobs = _pool(os.path.join(root, "p%d" % i), [(_JID, "obj", payload)])
            t, info = _status(mod, jobs)
            ok("A0%d status.json=%r 不抛（修前 AttributeError 打崩 --status）" % (i, payload),
               t == "", (t, info))
            ok("A0%db 该条目按读件失败跳过（job_states 为空，**不**归一成 \"?\"）" % i,
               t == "" and info.get("job_states") == {}, (t, info))

        jobs = _pool(os.path.join(root, "ok"), [(_JID, "obj", {"state": "done"})])
        t, info = _status(mod, jobs)
        ok("K01 对照：合法对象照常计数（{\"state\":\"done\"} ⇒ {'done':1}）",
           t == "" and info.get("job_states") == {"done": 1}, (t, info))

        jobs = _pool(os.path.join(root, "bad"), [(_JID, "raw", "{bad")])
        t, info = _status(mod, jobs)
        ok("K02 对照：非法 JSON 照旧跳过（与修前逐位一致）",
           t == "" and info.get("job_states") == {}, (t, info))

        jobs = _pool(os.path.join(root, "nostate"), [(_JID, "obj", {})])
        t, info = _status(mod, jobs)
        ok("K03 既有语义不变：合法对象缺 state 键仍记 \"?\"",
           t == "" and info.get("job_states") == {"?": 1}, (t, info))

        jobs = _pool(os.path.join(root, "mix"),
                     [("h_a_任务_验证单元_0001", "obj", {"state": "done"}),
                      ("h_b_任务_验证单元_0001", "obj", [1, 2]),
                      ("h_c_任务_验证单元_0001", "raw", "{bad"),
                      ("h_d_任务_验证单元_0001", "obj", {"state": "error"})])
        t, info = _status(mod, jobs)
        ok("K04 混合池：坏件被跳过、好件逐条计数（done=1/error=1）",
           t == "" and info.get("job_states") == {"done": 1, "error": 1}, (t, info))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---- 定点变异（源码级）-------------------------------------------------------
_GATE = chr(10).join([
    "                    v = json.load(f)",
    "                if not isinstance(v, dict):",
    "                    continue",
    "                st = v.get(\"state\", \"?\")",
])
_OLD = "                    st = json.load(f).get(\"state\", \"?\")"
_ALWAYS = chr(10).join([
    "                    v = json.load(f)",
    "                continue   # 变异：一切皆跳过（过度收紧）",
])

_MUTATIONS = (
    # M1 回缺陷：摘掉形状闸 ⇒ 非映射再次 AttributeError：A01..A04b 红；K04 池里
    # 也含一个非映射条目（混合池对照），故同样红（其合法条目根本走不到计数）。
    ("M1 回缺陷：摘掉 status.json 形状闸", ((_GATE, _OLD),),
     ("A01", "A01b", "A02", "A02b", "A03", "A03b", "A04", "A04b", "K04")),
    # M2 过度收紧：所有 status.json 都跳过 ⇒ 合法对象计数丢失：K01/K03/K04 红。
    ("M2 过度收紧：所有 status.json 一律跳过", ((_GATE, _ALWAYS),),
     ("K01", "K03", "K04")),
)


def _apply(text, pairs):
    for old, new in pairs:
        if text.count(old) != 1:
            return None, "锚点命中 %d 次" % text.count(old)
        text = text.replace(old, new, 1)
    return text, ""


def _mutate(base):
    print("!! 定点变异自证：摘掉形状闸（回缺陷）＋ 一切皆跳过（过度收紧）")
    bad = []
    for desc, pairs, expect in _MUTATIONS:
        mut, why = _apply(base, pairs)
        if mut is None:
            print("  ANCHOR-MISS %s  %s" % (desc, why))
            bad.append(desc)
            continue
        global _FAILS
        _FAILS = []
        try:
            run_checks(_load(mut))
        except BaseException as exc:              # noqa: BLE001
            _FAILS = ["<崩溃:%s>" % type(exc).__name__]
        got = sorted(set(_FAILS))
        if got == sorted(expect):
            print("  OK   %s  红项=%s" % (desc, got))
        else:
            print("  MISMATCH %s  实际=%s 期望=%s" % (desc, got, sorted(expect)))
            bad.append(desc)
    print("定点变异：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
    return len(bad)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    base = io.open(_SRC, encoding="utf-8").read()
    # 锚点自检（fail-closed）：修法的关键判据不在源码里 ⇒ exit 2，不给假绿。
    if _GATE not in base:
        print("ANCHOR-FAIL：status() 的形状闸字面量不在 hive/serve_start.py 里")
        return 2
    if "--mutate" in argv:
        return 1 if _mutate(base) else 0
    print("== #427 hive/serve_start.py::status() 形状闸 ==")
    run_checks(_load(base))
    print("")
    if _FAILS:
        print("issue #427 结果：%d 失败 —— %s" % (len(_FAILS), " ".join(_FAILS)))
        return 1
    print("issue #427 结果：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
