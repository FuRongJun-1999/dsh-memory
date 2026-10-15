# -*- coding: utf-8 -*-
# 功能名：heartbeat_ledger_stats 不得丢弃业务失败、不得把失败心跳计为正常（issue #376）
# 生效条件：python -X utf8 -m md_cg.test_issue376_heartbeat_failed [--mutate]；被测面＝md_cg/sustain.py::heartbeat_ledger_stats（读面）＋ record_heartbeat（写面契约对照）
# 子功能：A 组＝#376 正题（时间序列只纳入成功 beat；失败 beat 与业务档 tick 进 failed/failures；按档查询读数）；K 组＝非恒真对照（全成功台账原有读数逐位不变、只读性、name 过滤沿用、成功 tick / 轮转行不进序列、写入路径未动）；E 组＝字段增量与只读实现判据
# 执行：--mutate 时在镜像树里逐条把读面改回缺陷形态 / 摘掉明细上界 / 回退 absent 口径，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**（多红/少红皆不合格）
# 不适用条件：不判真实调度/线程节奏与告警链路（本批刻意不改写入路径、调度、配置、告警）；不判分片轮转的字节级行为（属 test_heartbeat_ledger L4）；不判 SustainLoop.beat() 的端到端时序（属 test_p14_sustain / test_sustain_bounded）；不判跨进程并发写
"""issue #376 守卫：`heartbeat_ledger_stats` 必须让失败档**看得见**。

病象（修前）：函数只按 `kind == "beat"` 取数，再把行缩成时间戳 —— 两种表现同一
根因：①业务档失败行（`kind="tick"`, `ok=False`）被 kind 过滤**整个丢弃**；
②失败心跳（`ok=False`）被当成正常周期计入时间序列，「连续 N 周期无断」被失败行
刷长。而 `sustain.py` 早已声明失败档必须在台账可见（`HB_KIND_TICK` 注释）。

修法（读面单点，**写路径一字不改**）：时间序列只纳入**成功的 beat**；失败的 beat
与 tick 进独立失败读数 `failed`（失败行数）与 `failures`（最近 `FAILURES_KEEP`
条明细，落账序）。`absent` 口径随之钉为「该过滤名下**一条记录都没有**」——
只有失败行的档位是 `absent=False, n=0, failed=k`（那正是必须可见的形态），
空台账仍 `absent=True`。**全成功台账的原有读数逐位不变**（新字段是纯增量）。

夹具形态与 issue 原文一致：隔离台账＝3 条成功心跳 + 1 条失败心跳 + 2 条业务档失败；
读数对照 `n: 4→3`、`count_in_longest: 4→3`、`longest_s: 250.0→200.0`、
`failed=3`（1 条 beat + 2 条 tick）、按 reflect 档查询 `absent=True→False, n=0, failed=1`。
"""
import inspect
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

from md_cg import sustain as S      # noqa: E402

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


_TMP = tempfile.mkdtemp(prefix="iss376_")

#: 与 issue 原文同形的隔离台账：3 条成功心跳 + 1 条失败心跳 + 2 条业务档失败。
#: 时间戳刻意让「含失败心跳」的旧读数为 longest=250.0/count=4，修后为 200.0/3。
_ROWS = (
    {"t": 0.0, "name": "beat", "pid": 1, "kind": S.HB_KIND_BEAT, "ok": True},
    {"t": 100.0, "name": "beat", "pid": 1, "kind": S.HB_KIND_BEAT, "ok": True},
    {"t": 200.0, "name": "beat", "pid": 1, "kind": S.HB_KIND_BEAT, "ok": True},
    {"t": 250.0, "name": "beat", "pid": 1, "kind": S.HB_KIND_BEAT, "ok": False,
     "error": "beat 周期异常"},
    {"t": 260.0, "name": "heal", "pid": 1, "kind": S.HB_KIND_TICK, "ok": False,
     "error": "heal 档异常"},
    {"t": 270.0, "name": "reflect", "pid": 1, "kind": S.HB_KIND_TICK, "ok": False,
     "error": "reflect 档异常"},
)
#: 原有读数（修前修后必须逐位一致的键）——失败读数与 absent 单列。
_BASE_KEYS = ("n", "threshold_s", "shards", "file", "span_s", "span_iso",
              "last_iso", "last_age_s", "segments", "longest_s", "longest_iso",
              "count_in_longest", "breaks", "breaks_top")


def _mk(tag, rows):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    with open(S.heartbeat_path(d), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + chr(10))
    return d


_ROOT = _mk("mixed", _ROWS)
_OK_ONLY = _mk("ok_only", _ROWS[:3])
_EMPTY = _mk("empty", ())
_NAME_ONLY = _mk("name_only", (_ROWS[1], _ROWS[3]))          # 同一档的成/败混合
_ROTATE = _mk("rotate", ({"t": 5.0, "kind": S.HB_KIND_ROTATE, "shard": "x"},))

print("== A 组：#376 正题——失败档必须看得见 ==")
_st = S.heartbeat_ledger_stats(_ROOT)
_stb = S.heartbeat_ledger_stats(_ROOT, name="beat")
_check("A01 时间序列只纳入**成功**的 beat（n=3，修前为 4）", _st["n"] == 3, _st["n"])
_check("A02 最长区间内周期数随之为 3（修前 4）",
       _st["count_in_longest"] == 3, _st["count_in_longest"])
_check("A03 最长连续区间秒数为 200.0（修前 250.0）",
       _st["longest_s"] == 200.0, _st["longest_s"])
_check("A04 失败行数 failed=3（1 条失败心跳 + 2 条业务档失败）",
       _st["failed"] == 3, _st["failed"])
_kk = sorted(f["kind"] for f in _st["failures"])
_check("A05 失败明细 3 条且 kind 分布为 1 条 beat + 2 条 tick",
       len(_st["failures"]) == 3 and _kk == ["beat", "tick", "tick"], _kk)
_errs = sorted(str(f.get("error")) for f in _st["failures"])
_check("A06 失败明细带 error 摘要（与落账原值一致）",
       _errs == sorted(["beat 周期异常", "heal 档异常", "reflect 档异常"]), _errs)
_check("A07 明细字段齐备且条数为 3（t/iso/name/kind/error —— 空明细不得算通过）",
       len(_st["failures"]) == 3
       and all(sorted(f) == sorted(["t", "iso", "name", "kind", "error"])
               for f in _st["failures"]), _st["failures"][:1])
_rf = S.heartbeat_ledger_stats(_ROOT, name="reflect")
_check("A08 按 reflect 档查询：absent=False, n=0, failed=1（修前 absent=True 且无失败读数）",
       _rf["absent"] is False and _rf["n"] == 0 and _rf["failed"] == 1
       and len(_rf["failures"]) == 1, (_rf["absent"], _rf["n"], _rf["failed"]))
_check("A09 失败行不进时间序列：原有时序读数与「只有 3 条成功」的台账逐位一致",
       all(_st[k] == S.heartbeat_ledger_stats(_OK_ONLY)[k] for k in _BASE_KEYS),
       [(k, _st[k], S.heartbeat_ledger_stats(_OK_ONLY)[k]) for k in _BASE_KEYS
        if _st[k] != S.heartbeat_ledger_stats(_OK_ONLY)[k]])
_nb = S.heartbeat_ledger_stats(_NAME_ONLY, name="beat")
_check("A10 同一档成/败混合：n=1、failed=1（两读数各归其位）",
       _nb["n"] == 1 and _nb["failed"] == 1, (_nb["n"], _nb["failed"]))

_many = tuple({"t": float(i), "name": "beat", "pid": 1,
               "kind": S.HB_KIND_BEAT, "ok": False, "error": "e%d" % i}
              for i in range(7))
_r7 = S.heartbeat_ledger_stats(_mk("many", _many), name="beat")
_check("A11 失败明细有界：7 条失败 → failed=7 且 failures 只留最近 %d 条（落账序）"
       % S.FAILURES_KEEP,
       _r7["failed"] == 7 and len(_r7["failures"]) == S.FAILURES_KEEP
       and [f["error"] for f in _r7["failures"]] == ["e2", "e3", "e4", "e5", "e6"],
       (_r7["failed"], [f["error"] for f in _r7["failures"]]))

print("== K 组：非恒真对照（原有读数与正常路径不得被改动） ==")
_ok = S.heartbeat_ledger_stats(_OK_ONLY)
_check("K01 全成功台账：原有时序读数与**手工 oracle** 逐位一致"
       "（n=3 / span=200.0 / longest=200.0 / segments=1 / breaks=0 / count_in_longest=3 / absent=False）",
       _ok["n"] == 3 and _ok["span_s"] == 200.0 and _ok["longest_s"] == 200.0
       and _ok["segments"] == 1 and _ok["breaks"] == 0
       and _ok["count_in_longest"] == 3 and _ok["absent"] is False, _ok)
_check("K02 全成功台账：failed=0 且 failures=[]（新字段是纯增量）",
       _ok["failed"] == 0 and _ok["failures"] == [], (_ok["failed"], _ok["failures"]))
_e = S.heartbeat_ledger_stats(_EMPTY)
_check("K03 空台账：absent=True / n=0 / longest_s=None / failed=0 / failures=[]（修前口径不变）",
       _e["absent"] is True and _e["n"] == 0 and _e["longest_s"] is None
       and _e["failed"] == 0 and _e["failures"] == [], _e)
_pre = dict(_ok)
_check("K04 原有键集未被改名/删除（A09 的逐位对照以键表为准）",
       all(k in _pre for k in _BASE_KEYS), [k for k in _BASE_KEYS if k not in _pre])
_tick_ok = _mk("tick_ok", (_ROWS[0], _ROWS[1], _ROWS[2],
                           {"t": 55.0, "name": "heal", "pid": 1,
                            "kind": S.HB_KIND_TICK, "ok": True},
                           {"t": 56.0, "name": "tidy", "pid": 1,
                            "kind": S.HB_KIND_TICK, "ok": True}))
_ta = S.heartbeat_ledger_stats(_tick_ok)
_check("K05 成功的业务档不进心跳时间序列（原口径不变：n=3、failed=0）",
       _ta["n"] == 3 and _ta["failed"] == 0, (_ta["n"], _ta["failed"]))
_ro = S.heartbeat_ledger_stats(_ROTATE)
_check("K06 轮转自述行（kind=rotate）不计入任何读数（原口径不变）",
       _ro["absent"] is True and _ro["n"] == 0 and _ro["failed"] == 0, _ro)
_ot = S.heartbeat_ledger_stats(_ROOT, name="tidy")
_check("K07 name 过滤沿用：无该档记录 → absent=True、failed=0（不误报）",
       _ot["absent"] is True and _ot["failed"] == 0, _ot)

_before = open(S.heartbeat_path(_ROOT), "rb").read()
S.heartbeat_ledger_stats(_ROOT)
S.heartbeat_ledger_stats(_ROOT, name="beat")
_after = open(S.heartbeat_path(_ROOT), "rb").read()
_check("K08 只读性：统计调用不改台账字节（不写、不轮转）", _before == _after,
       (len(_before), len(_after)))

_rec = S.record_heartbeat(_ROOT, "beat", ok=False, error="boom", t=999.0, pid=7)
_check("K09 写入路径未被改动：失败行照样落盘且字段齐备"
       "（t/name/pid/kind/ok/error —— 契约 sustain.py:282-284）",
       isinstance(_rec, dict) and _rec.get("kind") == S.HB_KIND_BEAT
       and _rec.get("ok") is False and _rec.get("error") == "boom"
       and _rec.get("t") == 999.0 and _rec.get("pid") == 7
       and _rec.get("name") == "beat", _rec)

print("== E 组：字段增量与只读实现判据 ==")
_check("E01 新增字段 failed / failures 都在返回体里（缺一则维护者看不见失败档）",
       "failed" in _st and "failures" in _st, sorted(_st))
_check("E02 含失败台账与全成功台账的**键集**完全一致（失败字段恒在场）",
       sorted(_st) == sorted(_ok), (sorted(_st), sorted(_ok)))
_src = inspect.getsource(S.heartbeat_ledger_stats)
_check("E03 统计函数体内无任何写面（不改写入路径：不 append / 不 open 写 / 不删片）",
       not any(t in _src for t in ("append_jsonl", "write(", "os.remove",
                                   "clear_stamp", "record_heartbeat(")), "")

shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #376 结果：%d 失败" % len(FAILS))
else:
    print("issue #376 结果：全部通过")


_MUTATIONS = (
    ("M1 回缺陷：失败行按原路走（心跳计入时序、tick 被丢）", "md_cg/sustain.py",
     ('        if not r.get("ok", True):',
      '        if False:  # 变异：失败行按改动前的路径（beat 计入时序 / tick 被丢）'),
     # 机制：失败行落回改动前路径 ⇒ 失败心跳计入时序（A01–A03、A09）、
     # 业务档失败被丢（A04–A07、A11）、按档查询退化（A08、A10）。
     # K02/K07 的夹具里 failed 恒为 0（全成功台账 / 无该档记录）⇒ 如实恒绿。
     ("A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09",
      "A10", "A11")),
    ("M2 明细不限长：failures 去掉最近 N 条上界", "md_cg/sustain.py",
     ('           "failed": failed, "failures": failures[-FAILURES_KEEP:]}',
      '           "failed": failed, "failures": failures}'),
     ("A11",)),
    ("M3 absent 口径回退：恒报 absent", "md_cg/sustain.py",
     ('        out.update({"absent": failed == 0, "segments": 0, "longest_s": None,',
      '        out.update({"absent": True, "segments": 0, "longest_s": None,'),
     ("A08",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss376_mut_")
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


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue376_heartbeat_failed"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把读面改回缺陷形态 / 摘上界 / 回退 absent，守卫必须按指定项转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        bad = []
        for desc, rel, (old, new), exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次" % (desc, rel, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:10]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
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
