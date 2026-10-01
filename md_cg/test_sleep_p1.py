# -*- coding: utf-8 -*-
"""P1 睡眠周期引擎守卫（九步显式化 + 副本迭代 + git 周期合并 + §4.7 env 表）。

契约（设计稿 `docs/plans/睡眠与自迭代_功能优化设计_v0.4.md` §三 / §四 / §4.7）：

    【1】九步显式化——`sustain._tick_sleep` 是**第六档 tick**（`_run` 到期链
        里 `next_sleep` + try/except + `_stop.wait(_POLL)`，形态与既有五档一致）；
        九步逐步留读数；⑤权重 / ⑥索引重建本轮是**显式 no-op 占位**，台账里
        标 `skipped == "未接线"`（不许悄悄跳过）。
    【2】四阶段——物化 / 影子迭代 / 对账+四闸 / 语义重放 + `--no-ff` 合并；
        Δ 空 ⇒ 零提交零写入；同批次幂等；冲突项**挂起**且**不进主库**。
    【3】§4.7 七键 + 缺省关的 `MDCG_SLEEP_SCRUB_APPLY`；缺省**只有一份**
        （`sleep.SLEEP_ENV_DEFAULTS` / `SLEEP_ENV_KEYS`），两入口共用读取器。
    【4】机械判据（本文件即其守卫）：跨午夜窗口三态、Δ 空零提交、幂等、
        冲突挂起、九步台账在场且 ⑤⑥ 标 skipped、P0-1 判据仍成立。

断言分组：

  G0 沙箱与真源——四根全落守卫临时目录；§4.7 七键缺省逐项对表；④实改闸缺省关；
     缺省字面量全仓只有一份（`MDCG_SLEEP*` 带引号字面量只许出现在 sleep.py 的
     SLEEP_ENV_KEYS 里）。
  G1 窗口判定——跨午夜（23:00-07:00）在 23:30 / 03:00 判在窗内、12:00 判窗外；
     留空 = 全时段恒真；同起止 = 全天；非法形态不误判（回落全时段）。
  G2 九步台账在場——`ledger_steps` 恒九条、顺序 = §3.1 表；⑤⑥ 逐条
     `skipped == "未接线"`；⑨ 只产记录（`auto_apply is False`）。
  G3 第六档 tick——`_run` 原文含 next_sleep 到期链且形态与既有五档一致；
     真起 `SustainLoop` 跑一次 `_tick_sleep` 后 `last_sleep.steps` 为九步、
     ⑤⑥ 标 skipped，且 `status()` 暴露 sleep_* 字段。
  G4 四阶段端到端——一轮 `run_cycle` 后：影子分支有 1 个提交 + 主库有重放提交
     + `--no-ff` 合并提交；被提升的节点**真的**落在主库新层；两条机械判据
     （历史禁入零命中 / 追踪集合 ⊆ 8 层且 ⊇ 全部 .md）仍全绿。
  G5 Δ 为空 ⇒ 零提交且主库真源面逐字节不变（提交计数前后相同）。
  G6 幂等——同批次 id 再跑一次：`idempotent=True`、零提交、真源面逐字节不变。
  G7 冲突挂起——主库/影子同 id 并发改动 ⇒ 该 id 进 `conflicts`、**未写进主库**、
     也未进影子分支的树；另一条（未冲突的）正常合并。
  G8 回滚——对合并提交 `revert`：主库真源面回到合并前，历史不丢（只增不减）。

运行：python -X utf8 -m md_cg.test_sleep_p1
      python -X utf8 -m md_cg.test_sleep_p1 --mutate         # 定点变异自证
      python -X utf8 -m md_cg.test_sleep_p1 --mutate --list  # 只列变异表

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到——实现改了却没同步本表）。

**基线纪律**：不以 git HEAD 为基线源——「改动前形态」由在当前工作区源码上做
**定点文本变异**（`_MUTATIONS`）复现，锚点漂移即退出码 2。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

from . import sleep as SL
from . import sustain as SUS

_PASS = []
_FAIL = []
_SKIP = []
_SRC = {}
_TMP = tempfile.mkdtemp(prefix="mdcg_sleepp1_")
_SAVED = {}
_GEN = [0]
_REAL_SL = SL
_REAL_SUS = SUS
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: §4.7 七键（逐字抄设计稿表）：短名 → (env 名, 缺省)。
ENV_TABLE = {
    "sleep": ("MDCG_SLEEP", "1"),
    "interval": ("MDCG_SLEEP_INTERVAL", "3600"),
    "window": ("MDCG_SLEEP_WINDOW", "23:00-07:00"),
    "merge": ("MDCG_SLEEP_MERGE", "auto"),
    "gitdir": ("MDCG_SLEEP_GITDIR", ""),
    "shadow": ("MDCG_SLEEP_SHADOW", ""),
    "scrub_apply": ("MDCG_SLEEP_SCRUB_APPLY", "0"),
}
_CCG = ("# 功能名：%s\n# 生效条件：全时窗\n# 子功能：s\n# 执行：e\n"
        "# 验证方式：test\n# 不适用条件：无\n")


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _rel_text(rel: str) -> str:
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _sandbox_env():
    for k in list(ENV_TABLE) + ["MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_STATE_ROOT",
                                "MDCG_DATA_ROOT", "MDCG_MASTER_KEY",
                                "MDCG_TOKEN_FILE", "MDCG_SUSTAIN_DIR",
                                "MDCG_TENANT", "MDCG_TOKEN", "MDCG_CLEARANCE",
                                "MDCG_SESSION", "DSH_SESSION_ID",
                                "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE",
                                "MDCG_VERIFIER_MODULES", "MDCG_POOLING",
                                "MDCG_SEMANTIC", "MDCG_EN_ATOMS",
                                "MDCG_UNIFY_QUERY", "MDCG_SPREAD"]:
        _SAVED[k] = os.environ.get(k)
        os.environ.pop(k, None)


def _restore_env():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _fixture(*, contextual_hot=0, unverified=0, extra=()):
    """沙箱数据面：新 gen 目录 + 8 个 LAYERS + 若干节点。返回 (gen, root, state)。"""
    _GEN[0] += 1
    gen = os.path.join(_TMP, "gen%d" % _GEN[0])
    root = os.path.join(gen, "data", "mdcg")
    state = os.path.join(gen, "state")
    os.environ["MDCG_STATE_ROOT"] = state
    os.environ["MDCG_ROOT"] = root
    os.environ["MDCG_AUX_ROOT"] = os.path.join(gen, "auxroot")
    os.environ["MDCG_MASTER_KEY"] = "ab" * 32
    os.environ["MDCG_TOKEN_FILE"] = os.path.join(gen, "tokens.json")
    os.environ["MDCG_SUSTAIN_DIR"] = os.path.join(gen, "sustain")
    os.makedirs(root, exist_ok=True)
    os.makedirs(state, exist_ok=True)
    from .mdcos import MdCGOS
    cg = MdCGOS(root)
    for i in range(int(contextual_hot)):
        nid = "ctx_hot%d" % i
        cg.add(nid, _CCG % ("情境热记忆%d" % i), layer="contextual",
               verification_basis="test", importance=0.9, merge_count=5,
               non_applicable_conditions=["无"])
    for i in range(int(unverified)):
        cg.add("kn_plain%d" % i, _CCG % ("无基底知识%d" % i), layer="knowledge",
               non_applicable_conditions=["无"])
    cg.add("kn_a", _CCG % "知识甲", layer="knowledge", verification_basis="test",
           non_applicable_conditions=["无"])
    cg.add("kn_b", _CCG % "知识乙", layer="knowledge", verification_basis="test",
           non_applicable_conditions=["无"])
    for nid, layer in extra:
        cg.add(nid, _CCG % nid, layer=layer, verification_basis="test",
               non_applicable_conditions=["无"])
    cg.flush()
    return gen, root, state


def _git(root, state, *args):
    G = os.path.join(state, "sleep", "lib.git")
    return subprocess.run(["git", "--git-dir=" + G, "--work-tree=" + root]
                          + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", shell=False)


def _commits(root, state):
    r = _git(root, state, "rev-list", "--count", "HEAD")
    return int(r.stdout.strip() or 0) if r.returncode == 0 else 0


def _node(root, *parts):
    return os.path.join(root, *parts)


# ---------------------------------------------------------------- G0
def g0():
    print("== G0 沙箱与 §4.7 env 表真源 ==")
    S = globals()["SL"]
    ok(dict(S.SLEEP_ENV_DEFAULTS) == {k: v[1] for k, v in ENV_TABLE.items()},
       "G0a SLEEP_ENV_DEFAULTS 七键缺省逐字等于 §4.7 表", S.SLEEP_ENV_DEFAULTS)
    ok(dict(S.SLEEP_ENV_KEYS) == {k: v[0] for k, v in ENV_TABLE.items()},
       "G0b SLEEP_ENV_KEYS 七键名逐字等于 §4.7 表", S.SLEEP_ENV_KEYS)
    for k, (env_name, want) in ENV_TABLE.items():
        got = S.sleep_env(k, {})
        ok(got == want, "G0d 空环境下 %s 的读数为 %r" % (env_name, want), got)
    ok(S.sleep_enabled() is True, "G0e MDCG_SLEEP 缺省 = 开（True）")
    ok(S.sleep_enabled({"MDCG_SLEEP": "0"}) is False,
       "G0f MDCG_SLEEP=0 → 关（opt-out 可达）")
    ok(S.sleep_interval() == 3600.0, "G0g MDCG_SLEEP_INTERVAL 缺省 = 3600 秒",
       S.sleep_interval())
    ok(S.sleep_interval({"MDCG_SLEEP_INTERVAL": "abc"}) == 3600.0,
       "G0h 非法周期值回落缺省（不抛、不猜测）")
    ok(S.sleep_merge_mode() == "auto", "G0i MDCG_SLEEP_MERGE 缺省 = auto")
    ok(S.sleep_merge_mode({"MDCG_SLEEP_MERGE": "never"}) == "never",
       "G0j MDCG_SLEEP_MERGE=never 可显式取到")
    ok(S.sleep_merge_mode({"MDCG_SLEEP_MERGE": "乱写"}) == "auto",
       "G0k 越界策略回落 auto（不静默降级成 never）")
    ok(S.sleep_scrub_apply() is False,
       "G0l **MDCG_SLEEP_SCRUB_APPLY 缺省关**（第④步缺省只在副本上盘点）")
    ok(S.sleep_scrub_apply({"MDCG_SLEEP_SCRUB_APPLY": "1"}) is True,
       "G0m 显式 =1 才放行第④步实改")
    ok(S.sleep_window() == "23:00-07:00",
       "G0n MDCG_SLEEP_WINDOW 缺省 = 23:00-07:00", S.sleep_window())


def _production_py():
    d = os.path.join(_REPO, "md_cg")
    return {"md_cg/" + fn: _rel_text("md_cg/" + fn)
            for fn in sorted(os.listdir(d)) if fn.endswith(".py")
            and not fn.startswith("test_")}


def g8():
    print("== G8 单一真源（静态）==")
    import re as _re
    want = sorted(v[0] for v in ENV_TABLE.values())
    pat = _re.compile(r'"MDCG_SLEEP[A-Z_]*"')
    bad = {rel: sorted(set(_re.findall(pat, t)))
           for rel, t in _production_py().items() if rel != "md_cg/sleep.py"
           and pat.search(t)}
    ok(not bad,
       "G8 除 sleep.py 外，生产源码里 **零**个带引号的 MDCG_SLEEP* 字面量"
       "（缺省与键名不许有第二份）", bad)
    lit = sorted(set(_re.findall(pat, _rel_text("md_cg/sleep.py"))))
    ok(lit == ['"%s"' % n for n in want],
       "G8a sleep.py 内带引号的 MDCG_SLEEP* 字面量 == §4.7 七键（恰一份，在 "
       "SLEEP_ENV_KEYS）", lit)
    m = _rel_text("md_cg/mcp_server.py")
    ok(m.count("_sleep.sleep_interval()") == 2
       and m.count("_sleep.sleep_enabled()") == 2
       and m.count("_sleep.sleep_merge_mode()") == 2
       and m.count("_sleep.sleep_window()") == 2
       and m.count("_sleep.sleep_scrub_apply()") == 2,
       "G8a 两入口各恰好一处经 sleep 读取器读五个sleep参数"
       "（env 路径 + op 路径，无字面量）")
    s = _rel_text("md_cg/sustain.py")
    ok('"MDCG_SLEEP' not in s,
       "G8b sustain.py 内不写 env 键名字面量（缺省与键名都归 sleep.py 真源）")
    ok("SLEEP_ENV_DEFAULTS" in _rel_text("md_cg/sleep.py")
       and "SLEEP_ENV_KEYS" in _rel_text("md_cg/sleep.py"),
       "G8c 真源表在 sleep.py 定义（SLEEP_ENV_DEFAULTS / SLEEP_ENV_KEYS）")


# ---------------------------------------------------------------- G1
def g1():
    print("== G1 窗口判定（跨午夜 / 留空）==")
    S = globals()["SL"]
    w = "23:00-07:00"
    ok(S.parse_window(w) == (23 * 60, 7 * 60),
       "G1 解析 23:00-07:00 → (1380, 420)", S.parse_window(w))
    ok(S.in_window(w, "23:30") is True, "G1a 跨午夜：23:30 在窗内")
    ok(S.in_window(w, "03:00") is True, "G1b 跨午夜：03:00 在窗内")
    ok(S.in_window(w, "12:00") is False, "G1c 跨午夜：12:00 在窗外")
    ok(S.in_window(w, "19:00") is False, "G1d 跨午夜：19:00 在窗外")
    ok(S.in_window(w, "07:00") is False and S.in_window(w, "23:00") is True,
       "G1e 边界：左闭右开（23:00 在窗内、07:00 在窗外）")
    ok(S.in_window("", "12:00") is True and S.in_window(None, "12:00") is True,
       "G1f 留空 = 全时段恒真")
    ok(S.in_window("01:00-05:00", "03:00") is True
       and S.in_window("01:00-05:00", "06:00") is False,
       "G1g 非跨午夜窗口照常判定")
    # 裁定⑰（2026-10-01）：非法形态**回落缺省窗**（不再是全时段 fail-open）
    ok(S.in_window("乱写", "12:00") is False and S.in_window("乱写", "03:00") is True,
       "G1h 非法形态回落缺省窗 23:00-07:00（12:00 窗外 / 03:00 窗内）")
    ok(S.in_window("23:00-99:99", "12:00") is False
       and S.in_window("23:00-99:99", "03:00") is True,
       "G1h2 打错字窗口（越界时分）同样回落缺省窗——不再白天也迭代")
    ok(S.parse_window("乱写") == S.parse_window("23:00-07:00"),
       "G1h3 非法形态解析结果 == 缺省窗（单一真源 SLEEP_ENV_DEFAULTS['window']）")
    ok(S.in_window("00:00-00:00", "12:00") is True,
       "G1i 同起止 = 全天恒真")
    # 真时间戳形态（_tick_sleep 走的是无参 localtime）
    import time as _t
    ok(S.in_window(w, _t.localtime()) is True
       or S.in_window(w, _t.localtime()) is False,
       "G1j 传入 time.struct_time 不抛（真对象形态可用）")
    # 窗口外 ⇒ 只记账不迭代（端到端）
    gen, root, state = _fixture(unverified=1)
    from .mdcos import MdCGOS
    cg = MdCGOS(root)
    face0 = S.source_face_hashes(root)
    n0 = _commits(root, state)
    ro = S.run_cycle(cg, batch="G1OUT", window="23:00-07:00", now="12:00")
    ok(ro.get("skipped") and "窗口外" in ro["skipped"],
       "G1k 窗口外 ⇒ 整轮只记账（skipped 记窗口外）", ro.get("skipped"))
    ok(all(s.get("skipped") for s in ro["steps"][1:4]) and len(ro["steps"]) == 9,
       "G1l 窗口外时 ②③④ 记 skip、台账仍是九条")
    ok(S.source_face_hashes(root) == face0 and _commits(root, state) == n0,
       "G1m 窗口外**零写入零提交**（真源面与提交计数都不动）")


# ---------------------------------------------------------------- G2
def g2():
    print("== G2 九步台账在场且 ⑤⑥ 标 skipped ==")
    S = globals()["SL"]
    steps = S.ledger_steps(scan={"candidates": 3, "ccg_backlog": 1,
                                 "importance_drift": 2},
                           iterated={"induce": {"written": 0},
                                     "promote": {"written": 0},
                                     "scrub": {"dry_run": True}},
                           round_index=7, prev_candidates=5)
    ok([s["step"] for s in steps] == list(S.STEPS),
       "G2 台账恒九条且顺序 = §3.1 表次序", [s["step"] for s in steps])
    ok(all(s.get("name") for s in steps), "G2a 每步都有显式中文名")
    ok(steps[0]["step"] == "recall_scan" and steps[0].get("readonly") is True,
       "G2b ①感知盘点标 readonly=True（只读）")
    ok(steps[4].get("skipped") == "未接线" and steps[5].get("skipped") == "未接线",
       "G2c **⑤权重 / ⑥索引重建 标 skipped=='未接线'**（不许悄悄跳过）",
       (steps[4].get("skipped"), steps[5].get("skipped")))
    ok(steps[4].get("planned") and steps[5].get("planned"),
       "G2d ⑤⑥ 附 planned（接线条目：P4 / P2P3）")
    ok(steps[8]["step"] == "self_check" and steps[8].get("auto_apply") is False,
       "G2e ⑨方向性自检只产记录（auto_apply=False，不自动触发修改）")
    ok(steps[7]["step"] == "feedback"
       and steps[7].get("prev_round_candidates") == 5
       and steps[7].get("candidates") == 3 and steps[7].get("delta") == -2,
       "G2f ⑧反馈 = 候选数前后变化（可判）", steps[7])
    ok(steps[6]["step"] == "record" and steps[6].get("ledger"),
       "G2g ⑦记录带台账落点")
    # 只记账路径：②③④ 记 skip_reason
    st2 = S.ledger_steps(scan={"candidates": 0}, round_index=1,
                         skip_reason="稳态：盘点候选数为 0")
    ok(all(s.get("skipped") == "稳态：盘点候选数为 0" for s in st2[1:4]),
       "G2h 只记账时 ②③④ 显式记 skip_reason（不是留空）",
       [s.get("skipped") for s in st2[1:4]])
    ok(len(st2) == 9 and st2[4].get("skipped") == "未接线",
       "G2i 只记账路径仍是九条、⑤⑥ 仍是「未接线」")


# ---------------------------------------------------------------- G3
def g3():
    print("== G3 第六档 tick（_run 到期链 + 真起循环）==")
    S = globals()["SUS"]
    src = _rel_text("md_cg/sustain.py")
    ok("next_sleep = time.time() + self.sleep_interval" in src,
       "G3 _run 内新增 next_sleep 到期变量")
    ok("            if now >= next_sleep:\n"
       "                try:\n"
       "                    self._tick_sleep()\n"
       "                except Exception:\n"
       "                    pass                       # 睡眠周期失败不中断常驻\n"
       "                next_sleep = now + self.sleep_interval\n"
       "            self._stop.wait(_POLL)" in src,
       "G3a 第六档形态与既有五档逐字同构（try/except 吞异常 + 末尾 _stop.wait(_POLL)）")
    gen, root, state = _fixture(unverified=1)
    from .mdcos import MdCGOS
    lp = S.SustainLoop(MdCGOS(root), name="g3loop",
                       d=os.environ["MDCG_SUSTAIN_DIR"])
    ok(lp.sleep_interval == 3600.0 and lp.auto_sleep is True
       and lp.sleep_merge == "auto" and lp.sleep_window == "23:00-07:00"
       and lp.sleep_scrub_apply is False,
       "G3b SustainLoop 五个 sleep 属性取自 §4.7 真源读取器",
       (lp.sleep_interval, lp.auto_sleep, lp.sleep_merge, lp.sleep_window,
        lp.sleep_scrub_apply))
    lp._tick_sleep()
    rec = lp.last_sleep
    ok(rec is not None and rec["steps"] == list(SL.STEPS),
       "G3c 真跑 _tick_sleep 后 last_sleep.steps = 九步", rec and rec["steps"])
    ok(any(s.startswith("weights:未接线") for s in rec["steps_skipped"])
       and any(s.startswith("reindex:未接线") for s in rec["steps_skipped"]),
       "G3d 台账里 ⑤⑥ 标 skipped=未接线", rec["steps_skipped"])
    ok("sleep_interval" in lp.status() and "last_sleep" in lp.status()
       and "auto_sleep" in lp.status(),
       "G3e status() 暴露睡眠档字段（可观测）")
    ok(rec["skipped"] is None or "窗口" in rec["skipped"],
       "G3f tick 的只记账判据只可能是窗口（缺省 23:00-07:00），不是别的静默跳过",
       rec["skipped"])
    S.stop_all()
    # 无参 tick 走的是 localtime；窗口关掉窗口（留空=全时段）后可确定性跑真迭代
    os.environ["MDCG_SLEEP_WINDOW"] = ""
    lp2 = S.SustainLoop(MdCGOS(root), name="g3loop2",
                        d=os.environ["MDCG_SUSTAIN_DIR"])
    ok(lp2.sleep_window == "" and lp2.auto_sleep is True,
       "G3g 窗口留空 = 全时段（可确定性跑真迭代）")
    lp2._tick_sleep()
    rec2 = lp2.last_sleep
    ok(rec2["skipped"] is None and (rec2["candidates"] or 0) > 0,
       "G3h 全时段下 tick 真迭代并留读（非只记账）",
       {k: rec2.get(k) for k in ("skipped", "candidates")})
    ok(len(rec2["steps"]) == 9 and rec2["steps"][:8] == list(SL.STEPS)[:8],
       "G3i tick 台账九步顺序不变")
    os.environ.pop("MDCG_SLEEP_WINDOW", None)
    S.stop_all()


# ---------------------------------------------------------------- G4
def g4():
    print("== G4 四阶段端到端（物化→迭代→对账→合并）==")
    S = globals()["SL"]
    gen, root, state = _fixture(contextual_hot=1, unverified=1)
    from .mdcos import MdCGOS
    cg = MdCGOS(root)
    before = S.source_face_hashes(root)
    n0 = _commits(root, state)
    r = S.run_cycle(cg, batch="G4B1", round_index=1, now="03:00")
    ok(r.get("skipped") is None and r.get("candidates", 0) > 0,
       "G4 本轮真迭代（非只记账）", {k: r.get(k) for k in
                                     ("skipped", "candidates")})
    ok(r.get("accepted") and "ctx_hot0" in r["accepted"],
       "G4a 影子上被提升的情境节点进了 accepted", r.get("accepted"))
    after = S.source_face_hashes(root)
    ok("knowledge/orphan/ctx_hot0.md" in after.keys()
       or any("ctx_hot0" in k and k.startswith("knowledge/") for k in after),
       "G4b 合并后主库**真的**多了知识层的 ctx_hot0", sorted(after))
    ok(not any(k.startswith("contextual/") for k in after),
       "G4c 层迁移的旧位置在主库已清掉（不留双份）", sorted(after))
    mg = r["steps"][6]["phases"]
    ok("merge" in mg, "G4d 四阶段都在位（materialize/iterate/reconcile/merge）", mg)
    n1 = _commits(root, state)
    ok(n1 >= n0 + 3,
       "G4e 一轮 = 基线/对账/重放/合并多个提交（实测 %s→%s）" % (n0, n1))
    log = _git(root, state, "log", "--oneline", "--all").stdout
    ok("merge" in log and "sleep/" in log,
       "G4f 历史里留下 sleep/<ts> 分支与合并提交")
    tr = S.audit_tracking(root, git_dir_path=os.path.join(state, "sleep", "lib.git"))
    hi = S.audit_history(root, git_dir_path=os.path.join(state, "sleep", "lib.git"))
    ok(hi["ok"] and not hi["hits"],
       "G4g P0-1 判据一仍成立：历史里 _keys.json/_access.log/_index.json/*.tmp/*.lock 零命中",
       hi["hits"])
    ok(tr["ok"], "G4h P0-1 判据二仍成立：追踪集合 ⊆ 8 层且 ⊇ 全部 .md",
       {"outside": tr["outside_layers"], "missing": tr["missing_md"]})
    ok(set(S.tracked_paths(root, git_dir_path=os.path.join(state, "sleep", "lib.git")))
       == set(after), "G4i 追踪集合 = 主库真源面 .md 全集")
    ok(before != after, "G4j 前置：真源面确实变了（对照 G5 的不变）")
    # 影子目录里那些非白名单件（_index.json 等）不进版本库
    sh = os.path.join(state, "sleep", "shadow")
    ok(os.path.isdir(sh), "G4k 影子工作树落在 state_root()/sleep/shadow", sh)
    sc = r["steps"][3]
    ok(sc.get("step") == "scrub" and sc.get("apply") is False
       and sc.get("dry_run") is True,
       "G4l 第④步缺省只在副本上盘点（未设 MDCG_SLEEP_SCRUB_APPLY ⇒ "
       "dry_run=True、不落盘）", sc)
    # ④ 的正向通路：显式放行时 dry_run=False（闸真的接线，不是恒 dry_run）
    gen3, root3, state3 = _fixture(contextual_hot=1, unverified=1)
    cg3 = MdCGOS(root3)
    r3 = S.run_cycle(cg3, batch="G4SCRUB", round_index=1, now="03:00",
                     scrub_apply=True)
    sc3 = r3["steps"][3]
    ok(sc3.get("apply") is True and sc3.get("dry_run") is False,
       "G4l2 显式放行第④步实改时 dry_run=False（闸接线，非恒 dry_run）", sc3)
    # MDCG_SLEEP_MERGE=ask：走完前三段，**合并挂起待人工**（不写主库）
    gen2, root2, state2 = _fixture(contextual_hot=1, unverified=1)
    cg2 = MdCGOS(root2)
    face2 = S.source_face_hashes(root2)
    n02 = _commits(root2, state2)
    ra = S.run_cycle(cg2, batch="G4ASK", round_index=1, now="03:00",
                     merge_mode="ask")
    ph = ra["steps"][6]["phases"].get("merge") or {}
    ok(ph.get("deferred") == "ask",
       "G4m MDCG_SLEEP_MERGE=ask：合并挂起留待人工", ph)
    log2 = _git(root2, state2, "log", "--oneline", "--all").stdout
    ok(S.source_face_hashes(root2) == face2,
       "G4n ask 档不写主库（主库真源面逐位不变；物化/对账只动影子分支）")
    ok("into main" not in log2,
       "G4o ask 档不产生合并提交（历史里只有基线与对账）", log2)


# ---------------------------------------------------------------- G5
def g5():
    print("== G5 Δ 为空 ⇒ 零提交 + 主库逐字节不变 ==")
    S = globals()["SL"]
    gen, root, state = _fixture(contextual_hot=1, unverified=1)
    from .mdcos import MdCGOS
    cg = MdCGOS(root)
    S.run_cycle(cg, batch="G5B1", round_index=1, now="03:00")
    face = S.source_face_hashes(root)
    n0 = _commits(root, state)
    # 第二轮：情境热记忆已被提升 ⇒ 迭代不再产出任何改动（候选数仍 >0）
    r2 = S.run_cycle(cg, batch="G5B2", round_index=2, now="03:00")
    ok(r2.get("candidates", 0) > 0 and r2.get("skipped") is None,
       "G5 前置：第二轮走的是真迭代路径（不是稳态短路）",
       {k: r2.get(k) for k in ("candidates", "skipped")})
    ok(r2["steps"][6]["delta"]["n"] == 0,
       "G5a 第二轮语义差异集 Δ 为空", r2["steps"][6]["delta"])
    ok(not r2.get("accepted"), "G5b 无 accepted（Δ 空 ⇒ 整轮跳过）", r2.get("accepted"))
    ok(_commits(root, state) == n0,
       "G5c **Δ 为空 ⇒ 零提交**（提交计数 %s 不变）" % n0)
    ok(S.source_face_hashes(root) == face,
       "G5d **主库真源面逐字节不变**（内容哈希集合逐位相同）")


# ---------------------------------------------------------------- G6
def g6():
    print("== G6 幂等：同批次再合并 = 零改动 ==")
    S = globals()["SL"]
    gen, root, state = _fixture(contextual_hot=1, unverified=1)
    from .mdcos import MdCGOS
    cg = MdCGOS(root)
    r1 = S.run_cycle(cg, batch="G6B1", round_index=1, now="03:00")
    ok(r1.get("merged") is True, "G6 第一轮合并成功（前置）", r1.get("merged"))
    face = S.source_face_hashes(root)
    n0 = _commits(root, state)
    r2 = S.run_cycle(cg, batch="G6B1", round_index=2, now="03:00")
    ok(r2.get("idempotent") is True,
       "G6a 同批次 id 第二次 → idempotent=True", r2.get("idempotent"))
    ok(_commits(root, state) == n0,
       "G6b 第二次零提交（提交计数 %s 不变）" % n0)
    ok(S.source_face_hashes(root) == face,
       "G6c 第二次零改动：主库真源面逐字节不变")
    ok(S.batch_merged("G6B1") is True and S.batch_merged("不存在的批次") is False,
       "G6d 批次 id 落台账（幂等判据可查）")


# ---------------------------------------------------------------- G7
def g7():
    print("== G7 冲突项挂起且不进主库 ==")
    S = globals()["SL"]
    gen, root, state = _fixture()
    from .mdcos import MdCGOS
    cg = MdCGOS(root)
    G = os.path.join(state, "sleep", "lib.git")
    m = S.materialize(root, git_dir_path=G, ts="G7T1")
    ok(m.get("ok") is True, "G7 前置：物化成功", m.get("error"))
    ok(m.get("baseline_face"), "G7a 物化记录**基准水位**（并发闸的判据面）")
    sh = m["shadow"]
    rel_a = "knowledge/orphan/kn_a.md"
    rel_b = "knowledge/orphan/kn_b.md"
    # 影子侧改 A 与 B
    for rel, tag in ((rel_a, "影子改A"), (rel_b, "影子改B")):
        with open(os.path.join(sh, rel), "a", encoding="utf-8", newline="\n") as f:
            f.write(tag + "\n")
    # 主库侧**并发**改同一个 id B（模拟迭代期间另一写方落盘）
    with open(os.path.join(root, rel_b), "a", encoding="utf-8", newline="\n") as f:
        f.write("主库并发改B\n")
    main_b = open(os.path.join(root, rel_b), "rb").read()
    rc = S.reconcile_gated(root, git_dir_path=G, shadow=sh, branch=m["branch"],
                           batch="G7B1", baseline_face=m["baseline_face"], cg=cg)
    cids = [c["id"] for c in rc["conflicts"]]
    ok("kn_b" in cids, "G7b 同 id 并发改动 → 进 conflicts 清单", cids)
    ok(all(c.get("gate") for c in rc["conflicts"]) and
       all(c.get("reason") for c in rc["conflicts"]),
       "G7c 冲突项带 gate 与 reason（可展示的清单）")
    ok("kn_b" not in rc["accepted"] and "kn_a" in rc["accepted"],
       "G7d 并发冲突项**不在 accepted**、无关项照常通过", rc["accepted"])
    mg = S.merge_cycle(cg, root, git_dir_path=G, branch=rc["branch"], shadow=sh,
                       delta=rc["delta"], accepted=rc["accepted"], batch="G7B1")
    ok(mg.get("ok") is True, "G7e 合并本身成功（冲突项已被挂起，不在合并面）",
       {k: mg.get(k) for k in ("ok", "error", "deferred")})
    ok(open(os.path.join(root, rel_b), "rb").read() == main_b,
       "G7f **冲突项未被写入主库**（主库优先，逐字节不变）")
    ok("影子改B" not in open(os.path.join(root, rel_b), encoding="utf-8").read(),
       "G7g 影子侧的冲突改动没有渗进主库正文")
    ok(mg.get("main_written") == [rel_a],
       "G7h 主库只多了应写的那一项（A）", mg.get("main_written"))
    branch_b = _git(root, state, "show", "%s:%s" % (rc["branch"], rel_b)).stdout
    ok("影子改B" not in branch_b,
       "G7i 冲突项也**未进影子分支的树**（不会借合并回灌）")
    ok(S.audit_history(root, git_dir_path=G)["ok"] and
       S.audit_tracking(root, git_dir_path=G)["ok"],
       "G7j 冲突轮之后两条机械判据仍全绿")
    # 密文项（保护闸 fail-closed 面）：影子侧的密文节点不得随分支入册，
    # 否则重放后两侧树不同 ⇒ 合并被 tree_divergence 永久堵死。
    gen2, root2, state2 = _fixture()
    cg2 = MdCGOS(root2)
    G2 = os.path.join(state2, "sleep", "lib.git")
    m2 = S.materialize(root2, git_dir_path=G2, ts="G7T2")
    sh2 = m2["shadow"]
    from . import nodefile as _nf
    _pa = os.path.join(sh2, "knowledge", "orphan", "kn_a.md")
    _fm_a, _ = _nf.loads(open(_pa, encoding="utf-8").read())
    with open(_pa, "w", encoding="utf-8", newline="\n") as f:
        # 密文形态：**整段正文**就是密文标记块（is_encrypted 判正文开头）
        f.write(_nf.dumps(_fm_a, "<!-- mdcg-enc:v1:AAAA -->"))
    with open(os.path.join(sh2, "knowledge", "orphan", "kn_b.md"), "a",
              encoding="utf-8", newline="\n") as f:
        f.write("明文改动\n")
    rc2 = S.reconcile_gated(root2, git_dir_path=G2, shadow=sh2,
                            branch=m2["branch"], batch="G7B2",
                            baseline_face=m2["baseline_face"], cg=cg2)
    ok("kn_a" not in rc2["accepted"]
       and any(r["id"] == "kn_a" for r in rc2["rejected"]),
       "G7k 影子侧密文节点被闸拦下（fail-closed，不进 accepted）",
       {"accepted": rc2["accepted"], "rejected": rc2["rejected"]})
    ok("kn_b" in rc2["accepted"], "G7l 同轮的明文项照常通过", rc2["accepted"])
    mg2 = S.merge_cycle(cg2, root2, git_dir_path=G2, branch=rc2["branch"],
                        shadow=sh2, delta=rc2["delta"],
                        accepted=rc2["accepted"], batch="G7B2")
    ok(mg2.get("ok") is True and not mg2.get("deferred"),
       "G7m 密文项不再堵死合并（本轮正常合并）",
       {k: mg2.get(k) for k in ("ok", "deferred", "error")})
    ok(mg2.get("main_written") == ["knowledge/orphan/kn_b.md"],
       "G7n 主库只写明文那一项", mg2.get("main_written"))


# ---------------------------------------------------------------- G8r
def g8_revert():
    print("== G8 回滚（revert）：真源面可回、历史不丢 ==")
    S = globals()["SL"]
    gen, root, state = _fixture(contextual_hot=1, unverified=1)
    from .mdcos import MdCGOS
    cg = MdCGOS(root)
    G = os.path.join(state, "sleep", "lib.git")
    pre = S.source_face_hashes(root)
    r = S.run_cycle(cg, batch="G8B1", round_index=1, now="03:00")
    ok(r.get("merged") is True, "G8 前置：一轮合并成功")
    mid = S.source_face_hashes(root)
    ok(mid != pre, "G8a 前置：合并确实改了真源面")
    mg = r["steps"][6]["phases"].get("merge") or {}
    mc = mg.get("round_commit")
    ok(bool(mc), "G8b 台账里能拿到**本轮内容所在的提交**（round_commit = 回退入口）", mc)
    ok(bool(mg.get("merge_commit")) and mg.get("merge_commit") != mc,
       "G8b2 合并提交与重放提交是两个提交（前者是拓扑记录）",
       (mg.get("merge_commit"), mc))
    hist_before = set(S.history_paths(root, git_dir_path=G))
    rv = S.revert(mc, root, git_dir_path=G)
    ok(rv.get("ok") is True, "G8c revert 成功",
       {k: rv.get(k) for k in ("ok", "error", "conflict", "hint")})
    ok(S.source_face_hashes(root) == pre,
       "G8d 回滚后主库真源面 == 合并前（逐位）",
       S.face_delta(pre, S.source_face_hashes(root)))
    ok(set(S.history_paths(root, git_dir_path=G)) >= hist_before,
       "G8e 历史只增不减（revert 自身也进历史）")


_GROUPS = (g0, g8, g1, g2, g3, g4, g5, g6, g7, g8_revert)


def _run_groups() -> int:
    _GEN[0] += 1
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                       # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-1200:])
        finally:
            try:
                globals()["SUS"].stop_all()
            except Exception:                          # noqa: BLE001
                pass
    return len(_FAIL)


# ---------------------------------------------------------------- 变异表
# 锚点 = (名字, rel, old, new)。每次变异必须让套件**转红**。
_MUTATIONS = (
    ("窗口跨午夜判据写反", "md_cg/sleep.py",
     "    return t >= start or t < end",
     "    return t >= start and t < end"),
    ("留空/非法窗口不再视作全时段", "md_cg/sleep.py",
     "    s = str(spec or \"\").strip()\n    if not s or \"-\" not in s:\n        return None",
     "    s = str(spec or \"\").strip()\n    if not s or \"-\" not in s:\n        return (0, 1)"),
    ("密文项不再被闸拦下（会随分支入册）", "md_cg/sleep.py",
     '                                 "reason": ("影子侧为密文节点（无密钥不重放、"\n'
     '                                            "fail-closed），不入册也不合并")})\n'
     '                continue',
     '                                 "reason": ("影子侧为密文节点（无密钥不重放、"\n'
     '                                            "fail-closed），不入册也不合并")})\n'
     '                pass'),
    ("④实改闸不接线（恒 dry_run）", "md_cg/sleep.py",
     "        r4 = _sc.sweep(cg, dry_run=not scrub_apply)",
     "        r4 = _sc.sweep(cg, dry_run=True)"),
    ("Δ 不看内容哈希（未改动也算差异）", "md_cg/sleep.py",
     "        if a and b:\n            if ha == hb:\n                continue\n            kind = \"changed\"",
     "        if a and b:\n            kind = \"changed\""),
    ("⑤⑥ 不再标「未接线」（悄悄跳过）", "md_cg/sleep.py",
     '        steps.append({"step": key, "name": STEP_NAMES[key],\n'
     '                      "skipped": "未接线", "planned": NOT_WIRED[key]})',
     '        steps.append({"step": key, "name": STEP_NAMES[key],\n'
     '                      "planned": NOT_WIRED[key]})'),
    ("④实改闸缺省翻成开", "md_cg/sleep.py",
     '    "scrub_apply": "0",      # 第④步去污染**实改**闸（缺省关：只盘点不落盘）',
     '    "scrub_apply": "1",      # 第④步去污染**实改**闸（缺省关：只盘点不落盘）'),
    ("并发闸不记 conflict（主库不再优先）", "md_cg/sleep.py",
     '                conflicts.append({"id": nid, "gate": "concurrent", "kind": kind,',
     '                accepted.append(nid)\n                conflicts.append({"id": nid, "gate": "concurrent", "kind": kind,'),
    ("幂等判据失效（同批次不再拦截）", "md_cg/sleep.py",
     "    return any(r.get(\"batch\") == batch and r.get(\"merged\") is True\n"
     "               for r in read_ledger())",
     "    return False"),
    ("第六档 tick 不进 _run 到期链", "md_cg/sustain.py",
     "            if now >= next_sleep:\n                try:\n"
     "                    self._tick_sleep()\n                except Exception:\n"
     "                    pass                       # 睡眠周期失败不中断常驻\n"
     "                next_sleep = now + self.sleep_interval\n",
     ""),
    ("两入口不再共用 sleep 读取器（写死 auto）", "md_cg/mcp_server.py",
     "        sleep_interval=_sleep.sleep_interval(),\n"
     "        auto_sleep=_sleep.sleep_enabled(),\n"
     "        sleep_merge=_sleep.sleep_merge_mode(),\n"
     "        sleep_window=_sleep.sleep_window(),\n"
     "        sleep_scrub_apply=_sleep.sleep_scrub_apply())",
     "        sleep_interval=3600.0, auto_sleep=True, sleep_merge=\"auto\",\n"
     "        sleep_window=\"23:00-07:00\", sleep_scrub_apply=False)"),
)


def _exec_module(name: str, rel: str, text: str):
    ns = {"__name__": name, "__package__": "md_cg",
          "__file__": os.path.join(_REPO, rel)}
    exec(compile(text, rel, "exec"), ns)               # noqa: S102 —— 基线自证用
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


_MUT_KIND = {"md_cg/sleep.py": ("SL", "md_cg.sleep"),
             "md_cg/sustain.py": ("SUS", "md_cg.sustain")}


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把实现改回「改动前/错误」形态，套件必须转红\n")
    if list_only:
        for name, rel, _o, _n in _MUTATIONS:
            print("  %-40s [%s]" % (name, rel))
        return 0
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, rel, old, new in _MUTATIONS:
        src = _rel_text(rel)
        if old not in src:
            print("  ANCHOR-MISS %s —— 锚点在 %s 源码里找不到（实现改了却没同步"
                  "本表）" % (name, rel))
            anchor_miss.append(name)
            continue
        mut_src = src.replace(old, new, 1)
        _SRC[rel] = mut_src
        live_sl, live_sus = globals()["SL"], globals()["SUS"]
        swapped = None
        try:
            if rel in _MUT_KIND:
                attr, modname = _MUT_KIND[rel]
                mut = _exec_module(modname.replace("md_cg.", "md_cg._p1mut_"), rel,
                                   mut_src)
                sys.modules[modname] = mut
                swapped = (attr, mut)
                globals()[attr] = mut
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            if swapped:
                attr, _m = swapped
                sys.modules[_MUT_KIND[rel][1]] = (live_sl if attr == "SL"
                                                  else live_sus)
                globals()["SL"], globals()["SUS"] = live_sl, live_sus
            _SRC.pop(rel, None)
        red_lines = [l for l in detail.splitlines()
                     if l.strip().startswith("FAIL ")]
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        print("  %s %-40s 红项=%d  %s"
              % ("OK    " if reds else "MISS  ", name, reds, verdict))
        for l in red_lines[:6]:
            print("        " + l.strip()[5:])
        if not reds:
            bad.append(name)

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都有一条断言把它钉死）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    _sandbox_env()
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        n = _run_groups()
        print("\nP1 睡眠周期引擎守卫：%d 通过，%d 失败，%d 跳过"
              % (len(_PASS), n, len(_SKIP)))
        return 0 if not n else 1
    finally:
        try:
            _REAL_SUS.stop_all()
        except Exception:                              # noqa: BLE001
            pass
        _restore_env()
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
