# -*- coding: utf-8 -*-
"""dsh-bounty#513 定点守卫 —— 心跳台账「失败档必须在台账可见」的读出口。

被修缺陷（`md_cg/sustain.py` · 基线 `e39d2f8bd8dd`）：唯一读出口
`heartbeat_ledger_stats` 按 `kind=="beat"` 过滤、且只把行降成一个 `t` 数值 ⇒
① 业务档失败的 `kind="tick"` 行（带 `ok=False` + `error`）零读出口；
② `kind="beat"` 且 `ok=False` 的失败心跳被当成一次正常周期，计入「连续无断」。
两表现同一根因：**统计消费逻辑丢掉了已落盘失败行的 `kind` / `ok` 语义**。

契约（实现里已有，非本守卫新立）：`sustain.py` 的 `HB_KIND_TICK` 登记逐字写着
「失败档**必须在台账可见**（不被 `heartbeat_ledger_stats` 按 `kind==HB_KIND_BEAT`
的过滤吞掉）」，写点 `_wrap_tick` 也照此落行（`kind=HB_KIND_TICK`）。本守卫钉的
就是这句承诺的**兑现面**。

断言面（每条＝一个可定点变异的判据）：
  F0 沙箱与前置：库根/心跳目录全在临时目录；真实写入面确实落了失败行。
  F1 **真实形态端到端**：真 `SustainLoop.beat()` 写戳失败 → `kind=beat` 失败行；
     真 `_wrap_tick` 业务档抛异常 → `kind=tick` 失败行。两条都必须在读数里可见，
     且失败心跳**不计入**正常连续无断（n == 成功周期数）。
  F1b **确定性时间序列**：失败心跳夹在成功心跳中间时，最长连续区间只覆盖成功周期。
  F2 **失败档按 name 可见**：`name="reflect"` 的 tick 失败行不再报 `absent=True`。
  F3 **仅失败行 ≠ 无记录**：台账只有失败行时 `absent=False`（不是「没有记录」）。
  F4 **回归**：全成功台账的既有读数（n/segments/breaks/longest_s/span_s）逐位不变。
  F5 **不越界**：`kind="rotate"` 自述行照旧不进时间序列（`:281` 已兑现的登记）。

运行：python -X utf8 -m md_cg.test_audit_heartbeat_20261015
      python -X utf8 -m md_cg.test_audit_heartbeat_20261015 --mutate
      python -X utf8 -m md_cg.test_audit_heartbeat_20261015 --mutate --list

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到——实现改了却没同步本表，不得静默跳过）。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import types

from . import sustain

_PASS = []
_FAIL = []
_SRC = {}
_REAL = sustain


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- 沙箱
_TMP = tempfile.mkdtemp(prefix="mdcg_hb513_")
_SAVED = {}
_GEN = [0]
_ENV_KEYS = ("MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_STATE_ROOT", "MDCG_SUSTAIN_DIR",
             "MDCG_HEARTBEAT_LEDGER")


def _sandbox_env():
    for k in _ENV_KEYS:
        _SAVED[k] = os.environ.get(k)
    os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cg")
    os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "aux")
    os.environ["MDCG_STATE_ROOT"] = os.path.join(_TMP, "state")
    os.environ["MDCG_SUSTAIN_DIR"] = os.path.join(_TMP, "sustain")
    os.environ.pop("MDCG_HEARTBEAT_LEDGER", None)      # 缺省＝开


def _restore_env():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _fresh_root(tag):
    _GEN[0] += 1
    root = os.path.join(_TMP, "gen%d" % _GEN[0], tag)
    os.makedirs(root, exist_ok=True)
    return root


def _netdir(tag):
    d = os.path.join(_TMP, "net", tag)
    os.makedirs(d, exist_ok=True)
    return d


def _rows(root):
    """台账原始行（回读盘上真字节，不经任何统计面）。"""
    p = sustain.heartbeat_path(root)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _loop(root, netdir, name="h513"):
    from .mdcos import MdCGOS
    S = globals()["sustain"]
    return S.SustainLoop(MdCGOS(root), name=name, d=netdir,
                         beat_interval=1e9, heal_interval=1e9,
                         scrub_interval=1e9, evolve_interval=1e9,
                         tidy_interval=1e9, sleep_interval=1e9,
                         auto_heal=False, auto_scrub=False,
                         auto_evolve=False, auto_tidy=False)


def _stats(root, **kw):
    return globals()["sustain"].heartbeat_ledger_stats(root, **kw)


# ---------------------------------------------------------------- F0 前置
def f0():
    print("== F0 隔离与前置 ==")
    S = globals()["sustain"]
    ok(os.environ["MDCG_ROOT"].startswith(_TMP)
       and S.heartbeat_ledger_enabled() is True,
       "F0a 沙箱：库根在守卫临时目录内且台账缺省开（绝不碰在役库）",
       os.environ["MDCG_ROOT"])
    root = _fresh_root("f0")
    S.record_heartbeat(root, "beat", ok=False, t=1.0, error="probe: 失败行")
    rows = _rows(root)
    ok(len(rows) == 1 and rows[0].get("ok") is False
       and rows[0].get("error") == "probe: 失败行",
       "F0b 前置：失败行确实落盘（ok=False + error 都在盘上）", rows)


# ---------------------------------------------------------------- F1 真实形态
def f1():
    print("== F1 真实形态端到端 —— beat 写戳失败 / 业务档失败都必须在读数里可见 ==")
    S = globals()["sustain"]
    root, net = _fresh_root("f1"), _netdir("f1")
    lp = _loop(root, net)
    for _ in range(3):
        lp.beat()                                     # 3 次成功心跳（真实写入面）

    # 失败心跳：把戳目录指到「父路径是文件」的位置 ⇒ write_stamp 必抛，
    # 走的正是 beat() 的 except 面（sustain.py 的 ok=False 记台账分支）。
    blocker = os.path.join(root, "blocker")
    with open(blocker, "w", encoding="utf-8") as f:
        f.write("x")
    lp_bad = _loop(root, os.path.join(blocker, "net"))
    raised = ""
    try:
        lp_bad.beat()
    except Exception as exc:                          # noqa: BLE001
        raised = "%s: %s" % (type(exc).__name__, exc)

    # 业务档失败：走真实的 _wrap_tick 包装面（生产里六档失败的同一条路）。
    def _boom():
        raise TypeError("业务档炸了")
    wrapped_ok = lp._wrap_tick("reflect", _boom)()

    rows = _rows(root)
    beats_ok = [r for r in rows if r.get("kind") == "beat" and r.get("ok") is True]
    beats_bad = [r for r in rows if r.get("kind") == "beat" and r.get("ok") is not True]
    ticks_bad = [r for r in rows if r.get("kind") == S.HB_KIND_TICK
                 and r.get("ok") is not True]
    ok(bool(raised) and len(beats_bad) == 1 and beats_bad[0].get("error"),
       "F1a 前置：真 beat() 写戳失败留下 kind=beat/ok=False 行（带 error 摘要）",
       (raised, beats_bad))
    ok(wrapped_ok is False and len(ticks_bad) == 1
       and "TypeError" in str(ticks_bad[0].get("error")),
       "F1b 前置：真 _wrap_tick 业务档失败留下 kind=tick/ok=False 行",
       ticks_bad)

    st = _stats(root)
    kinds = sorted(f.get("kind") for f in st.get("failures", []))
    ok(st.get("failed") == 2 and kinds == ["beat", "tick"],
       "F1c 两条失败行都在读数里可见（failed==2，含 kind=tick 那条）",
       (st.get("failed"), kinds))
    ok(st.get("n") == len(beats_ok) == 3,
       "F1d 失败心跳**不算**正常周期：n == 成功心跳数（3），不是 4",
       (st.get("n"), len(beats_ok)))
    ok(st.get("count_in_longest") == 3,
       "F1e 失败心跳不进最长连续区间（count_in_longest == 成功数 3）",
       st.get("count_in_longest"))
    errs = [f.get("error") for f in st.get("failures", [])]
    ok(all(e for e in errs) and len(errs) == 2,
       "F1f 失败明细带 error 摘要（失败原因可读，不只剩一个时间戳）", errs)


# ---------------------------------------------------------------- F1b 确定性序列
def f1b():
    print("== F1b 确定性时间序列 —— 失败心跳夹在成功心跳中间 ==")
    S = globals()["sustain"]
    root = _fresh_root("f1b")
    for t in (0.0, 10.0, 20.0):
        S.record_heartbeat(root, "beat", ok=True, t=t)
    S.record_heartbeat(root, "beat", ok=False, t=30.0, error="XFail: boom")
    S.record_heartbeat(root, "reflect", ok=False, t=40.0,
                       error="TypeError: 业务档炸了", kind=S.HB_KIND_TICK)
    st = _stats(root, name="beat", threshold_s=15.0)
    ok(st.get("n") == 3 and st.get("longest_s") == 20.0
       and st.get("span_s") == 20.0,
       "F1b-1 成功周期序列：n=3、最长 20s（修前 n=4、最长 30s＝把失败当正常）",
       (st.get("n"), st.get("longest_s"), st.get("span_s")))
    ok(st.get("failed") == 1 and st.get("failures")[0].get("error") == "XFail: boom",
       "F1b-2 beat 档的失败行按 name 可见（failed=1 + error）", st.get("failures"))
    st_all = _stats(root, threshold_s=15.0)
    ok(st_all.get("failed") == 2,
       "F1b-3 不过滤 name 时两条失败行都在（beat 失败 + tick 失败）",
       st_all.get("failed"))


# ---------------------------------------------------------------- F2 name 面
def f2():
    print("== F2 失败档按 name 可见 —— tick 失败行不再报 absent=True ==")
    S = globals()["sustain"]
    root = _fresh_root("f2")
    S.record_heartbeat(root, "beat", ok=True, t=100.0)
    S.record_heartbeat(root, "reflect", ok=False, t=110.0,
                       error="TypeError: 业务档炸了", kind=S.HB_KIND_TICK)
    d = _stats(root, name="reflect")
    ok(d.get("absent") is False and d.get("failed") == 1
       and d.get("failures")[0].get("name") == "reflect",
       "F2a name=reflect：有失败行 ⇒ absent=False 且 failed=1（修前 absent=True）", d)
    ok(d.get("n") == 0 and d.get("longest_s") is None,
       "F2b 该档没有成功心跳周期 ⇒ n=0、时间读数为 None（诚实不编数）", d)
    ok(_stats(root, name="nobody").get("absent") is True,
       "F2c 对照：台账里真没有该 name 的任何行 ⇒ absent=True")


# ---------------------------------------------------------------- F3 仅失败行
def f3():
    print("== F3 仅失败行 ≠ 无记录 ==")
    S = globals()["sustain"]
    root = _fresh_root("f3")
    S.record_heartbeat(root, "heal", ok=False, t=7.0, error="ValueError: 又炸",
                       kind=S.HB_KIND_TICK)
    st = _stats(root)
    ok(st.get("absent") is False and st.get("n") == 0 and st.get("failed") == 1,
       "F3a 只有失败行：absent=False（不是「没有记录」）、n=0、failed=1", st)
    ok(_stats(_fresh_root("f3_none")).get("absent") is True,
       "F3b 对照：空台账 absent=True")


# ---------------------------------------------------------------- F4 回归
def f4():
    print("== F4 回归 —— 全成功台账的既有读数逐位不变 ==")
    S = globals()["sustain"]
    r_move = _fresh_root("f4_move")
    for t in (0.0, 10.0, 20.0, 30.0, 40.0):
        S.record_heartbeat(r_move, "hb", ok=True, t=t)
    r_break = _fresh_root("f4_break")
    for t in (0.0, 10.0, 20.0, 30.0, 1000.0, 1010.0, 1020.0):
        S.record_heartbeat(r_break, "hb", ok=True, t=t)
    a = _stats(r_move, name="hb", threshold_s=15.0)
    b = _stats(r_break, name="hb", threshold_s=15.0)
    ok(a["n"] == 5 and a["breaks"] == 0 and a["longest_s"] == 40.0
       and a["segments"] == 1 and a["absent"] is False
       and a.get("failed", 0) == 0,
       "F4a 连续全成功：n=5、零断点、最长 40s、failed=0",
       (a["n"], a["breaks"], a["longest_s"], a.get("failed")))
    ok(b["n"] == 7 and b["breaks"] == 1 and b["segments"] == 2
       and b["longest_s"] == 30.0 and b["breaks_top"][0]["gap_s"] == 970.0,
       "F4b 断档可检出：breaks=1、segments=2、最长 30s、gap 970s",
       (b["n"], b["breaks"], b["longest_s"]))


# ---------------------------------------------------------------- F5 不越界
def f5():
    print("== F5 不越界 —— rotate 自述行照旧不进时间序列 ==")
    S = globals()["sustain"]
    root = _fresh_root("f5")
    S.record_heartbeat(root, "beat", ok=True, t=1.0)
    with open(S.heartbeat_path(root), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": 2.0, "name": "_rotate", "pid": 1,
                            "kind": S.HB_KIND_ROTATE, "ok": True,
                            "shard": "x", "pruned": []}, ensure_ascii=False) + "\n")
    st = _stats(root)
    ok(st["n"] == 1 and st.get("failed", 0) == 0,
       "F5a rotate 行既不是周期也不是失败（n=1、failed=0）", st)


_GROUPS = (f0, f1, f1b, f2, f3, f4, f5)


# ---------------------------------------------------------------- 变异表
# 锚点 = (名字, rel, old, new, 预期红项数下限, 预期命中的红项子串)
_MUTATIONS = (
    ("M1 恢复旧过滤（tick 失败行被丢）", "md_cg/sustain.py",
     "        if kind not in (HB_KIND_BEAT, HB_KIND_TICK):\n"
     "            continue                       # rotate 自述行不进时间序列（`:281`）\n",
     "        if kind != HB_KIND_BEAT:\n"
     "            continue\n",
     1, "F2"),
    ("M2 忽略 ok 标记（失败心跳当正常周期）", "md_cg/sustain.py",
     "        if r.get(\"ok\") is not True:        # 失败行**必须在台账可见**（`:283` 的承诺）\n"
     "            fails.append({\"kind\": kind, \"name\": r.get(\"name\"),\n"
     "                          \"t\": float(v) if ok_t else None,\n"
     "                          \"iso\": _iso(v) if ok_t else None,\n"
     "                          \"error\": r.get(\"error\")})\n"
     "            continue\n",
     "",
     1, "F1"),
)


def _rel_text(rel: str) -> str:
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(_repo_root(), rel), encoding="utf-8") as f:
        return f.read()


def _exec_module(name, rel, text):
    """把变异源码 exec 进模块自身的 __dict__（相对导入按 __package__ 解析）。"""
    m = types.ModuleType(name)
    m.__file__ = os.path.join(_repo_root(), rel)
    m.__package__ = "md_cg"
    exec(compile(text, rel, "exec"), m.__dict__)      # noqa: S102 —— 定点变异工装
    return m


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                      # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-800:])
    try:
        _REAL.stop_all()
    except Exception:                                 # noqa: BLE001
        pass
    return len(_FAIL)


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：把失败行的消费逻辑退回修前形态，套件必须转红\n")
    if list_only:
        for name, rel, _o, _n, exp, label in _MUTATIONS:
            print("  %-40s expect_red>=%d  hit~%s  (%s)" % (name, exp, label, rel))
        return 0
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, rel, old, new, expect, label in _MUTATIONS:
        src = _rel_text(rel)
        if old not in src:
            print("  ANCHOR-MISS %s —— 锚点在 %s 找不到" % (name, rel))
            anchor_miss.append(name)
            continue
        _SRC[rel] = src.replace(old, new, 1)
        live = sys.modules["md_cg.sustain"]
        mut = _exec_module("md_cg._hb513_mut", rel, _SRC[rel])
        sys.modules["md_cg.sustain"] = mut
        globals()["sustain"] = mut
        try:
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            sys.modules["md_cg.sustain"] = live
            globals()["sustain"] = _REAL
            _SRC.pop(rel, None)
        red_lines = [l.strip() for l in detail.splitlines()
                     if l.strip().startswith("FAIL ")]
        hit = any(label in l for l in red_lines)
        mark = "OK  " if (reds >= expect and hit) else "MISMATCH"
        print("  %s %-40s 红项=%d 预期>=%d 命中%s=%s"
              % (mark, name, reds, expect, label, "是" if hit else "**否**"))
        for l in red_lines[:4]:
            print("        " + l[5:])
        if reds < expect or not hit:
            bad.append("%s（红=%d 预期>=%d，命中%s=%s）"
                       % (name, reds, expect, label, hit))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（两处消费逻辑退回去都被打红）" if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    _sandbox_env()
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        n = _run_groups()
        print("\n心跳台账失败读数守卫：%d 通过，%d 失败" % (len(_PASS), n))
        return 0 if not n else 1
    finally:
        try:
            _REAL.stop_all()
        except Exception:                             # noqa: BLE001
            pass
        _restore_env()
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
