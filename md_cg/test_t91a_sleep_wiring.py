# -*- coding: utf-8 -*-
"""t91a-20261011/t1 门禁守卫：sleep.py 的 ⑤权重 / ⑥索引重建**真接线**。

accept 判据（逐条）：
  ① `STEPS` 顺序与语义不变（`:743`）；台账里对 ("weights","reindex") 硬写
     `{"skipped": "未接线", "planned": NOT_WIRED[key]}` 的分支（原 `:1339-1341`）
     改成调用真实现并记真实读数；`NOT_WIRED` 常量已删且无其它引用。
  ② ⑤ 调既有权重入口并回报**本轮实际参与重算的节点数/改动数**（非空转占位）。
  ③ ⑥ 调既有索引重建入口并回报**重建条目数 / 耗时**。
  ④ 两步**自身失败不阻断整轮 sleep**（异常吞掉 → ok=False + error 摘要）。
  ⑤ 不新增顶层模块、不动 nodefile.py / mdcos.py。

断言分组：
  G1 台账形态：恒九条、顺序 = STEPS、⑤⑥ 不再 skipped=="未接线"、带真读数；
     其余七步逐条形状与接线前一致（字段集逐个钉死）。
  G2 入口指向：⑤⑥ 步骤读数由 `sleep.wired_steps()` 真正调既有函数产出
     （weights.recalc / refindex.rebuild + provenance.rebuild_ledger），
     且 `NOT_WIRED` 已删、源码里再无对这两步的 "未接线" 记账分支。
  G3 真读数端到端：临时影子根造最小库 → 跑一轮 sleep 台账生成 →
     weights 记 nodes_scanned/changed（非空转）、reindex 记 entries/elapsed_ms。
  G4 失败不阻断：把 ⑥ 的既有入口打成**必抛**，整轮 `run_cycle` 仍返回
     完整九条台账（ok=False + error 摘要），且其余七步读数形状不变。

运行：python D:\\wook\\lingshu-src\\md_cg\\test_t91a_sleep_wiring.py
退出码（fail-closed）：0 = 全绿；1 = 有断言失败。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import types                                                   # noqa: E402

try:                                                           # 包内跑（-m）
    from . import sleep as SL
    from . import weights as W
except ImportError:                                            # 直接跑（python 文件路径）
    _pkg = types.ModuleType("md_cg")
    _pkg.__path__ = [_HERE]
    sys.modules.setdefault("md_cg", _pkg)
    from md_cg import sleep as SL
    from md_cg import weights as W

SLEEP_PY = os.path.join(_HERE, "sleep.py")

_PASS = []
_FAIL = []
_TMP = tempfile.mkdtemp(prefix="mdcg_t91a_")
_SAVED = {}
_CCG = ("# 功能名：%s\n# 生效条件：全时窗\n# 子功能：s\n# 执行：e\n"
        "# 验证方式：test\n# 不适用条件：无\n")


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _src() -> str:
    with open(SLEEP_PY, encoding="utf-8") as f:
        return f.read()


def _code(src: str) -> str:
    """去掉注释行与文档串——结构判据只看**活代码**（注释里提旧名不算引用）。"""
    out = []
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith('"') or s.startswith("'"):
            continue
        out.append(line)
    return "\n".join(out)


def _sandbox_env():
    for k in ("MDCG_ROOT", "MDCG_AUX_ROOT", "MDCG_STATE_ROOT", "MDCG_DATA_ROOT",
              "MDCG_MASTER_KEY", "MDCG_TOKEN_FILE", "MDCG_SUSTAIN_DIR",
              "MDCG_SLEEP", "MDCG_SLEEP_INTERVAL", "MDCG_SLEEP_WINDOW",
              "MDCG_SLEEP_MERGE", "MDCG_SLEEP_GITDIR", "MDCG_SLEEP_SHADOW",
              "MDCG_SLEEP_SCRUB_APPLY", "MDCG_AUTONOMY"):
        _SAVED[k] = os.environ.get(k)
        os.environ.pop(k, None)


def _restore_env():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _fixture(tag: str, *, contextual_hot: int = 0, unverified: int = 0):
    """临时影子根造最小库：8 个 LAYERS + 两个知识节点。返回 (root, state)。

    `contextual_hot` / `unverified` 为真时额外造「情境热记忆」与「无基底知识」
    —— 前者是**真迭代能产出 Δ** 的唯一源头（升层候选），守卫 c 需要它；
    只造知识甲的库候选数为 0，会走稳态早退而非真迭代。
    """
    gen = os.path.join(_TMP, tag)
    root = os.path.join(gen, "data", "mdcg")
    state = os.path.join(gen, "state")
    os.environ["MDCG_STATE_ROOT"] = state
    os.environ["MDCG_ROOT"] = root
    # 末段不得是 Windows 保留设备名（datapath 的 issue #57 守卫直判末段）
    os.environ["MDCG_AUX_ROOT"] = os.path.join(gen, "auxroot")
    os.environ["MDCG_MASTER_KEY"] = "ab" * 32
    os.environ["MDCG_TOKEN_FILE"] = os.path.join(gen, "tokens.json")
    os.environ["MDCG_SUSTAIN_DIR"] = os.path.join(gen, "sustain")
    os.environ["MDCG_SLEEP_WINDOW"] = ""            # 全时段（门拦不参与本守卫）
    os.makedirs(root, exist_ok=True)
    os.makedirs(state, exist_ok=True)
    from md_cg.mdcos import MdCGOS
    cg = MdCGOS(root)
    for i in range(int(contextual_hot)):
        cg.add("ctx_hot%d" % i, _CCG % ("情境热记忆%d" % i), layer="contextual",
               verification_basis="test", importance=0.9, merge_count=5,
               non_applicable_conditions=["无"])
    for i in range(int(unverified)):
        cg.add("kn_plain%d" % i, _CCG % ("无基底知识%d" % i), layer="knowledge",
               non_applicable_conditions=["无"])
    cg.add("kn_a", _CCG % "知识甲", layer="knowledge",
           verification_basis="test", non_applicable_conditions=["无"])
    cg.add("kn_b", _CCG % "知识乙", layer="knowledge",
           verification_basis="test", non_applicable_conditions=["无"])
    cg.flush()
    return root, state


def _git(root, state, *args):
    G = os.path.join(state, "sleep", "lib.git")
    import subprocess
    return subprocess.run(["git", "--git-dir=" + G, "--work-tree=" + root]
                          + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", shell=False)


def _listing(root):
    """主库根下**全部文件**的相对路径集（含派生面——越权判据要含派生面）。"""
    out = set()
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            out.add(os.path.relpath(os.path.join(dp, fn), root).replace("\\", "/"))
    return out


def _maintain_lines(root):
    p = os.path.join(root, "_maintain.jsonl")
    if not os.path.isfile(p):
        return 0
    with open(p, encoding="utf-8", errors="replace") as f:
        return sum(1 for ln in f if ln.strip())


def _wired(steps, key):
    return _step(steps, key) or {}


#: 接线前七步的**字段形状**（逐条钉死；④ 带 skip 文案时形状不变）。
_PRE_SHAPE = {
    "recall_scan": {"step", "name", "candidates", "ccg_backlog",
                    "importance_drift", "by_fix", "readonly"},
    "induce": {"step", "name", "written", "clusters", "note"},
    "promote": {"step", "name", "written", "promoted", "targeted", "note"},
    "scrub": {"step", "name", "apply", "dry_run", "n_issues", "n_high_medium",
              "applied"},
    "record": {"step", "name", "ledger", "round", "delta", "phases"},
    "feedback": {"step", "name", "candidates", "prev_round_candidates", "delta"},
    "self_check": {"step", "name", "round", "due", "auto_apply", "note"},
}
#: ④ 只在**未迭代**时才有的键（接线前即如此；形状断言按在场情形取并集）。
_SKIP_OK = {"skipped"}


def _step(steps, key):
    for s in steps:
        if s.get("step") == key:
            return s
    return None


# ---------------------------------------------------------------- G1
def g1_ledger_shape():
    print("== G1 九步台账形态：⑤⑥ 去占位、其余七步形状不变 ==")
    wired = {"weights": {"ok": True,
                         "readout": {"apply": True, "nodes_scanned": 3,
                                     "changed": 1, "unchanged": 2, "written": 1,
                                     "elapsed_ms": 4}},
             "reindex": {"ok": True,
                         "readout": {"apply": True, "entries": 7, "groups": 1,
                                     "indexed": 7, "elapsed_ms": 9}}}
    steps = SL.ledger_steps(scan={"candidates": 3, "ccg_backlog": 1,
                                  "importance_drift": 2, "by_fix": {}},
                            iterated={"induce": {"written": 0, "clusters": 0,
                                                 "note": ""},
                                      "promote": {"written": 0, "promoted": [],
                                                  "targeted": 0, "note": ""},
                                      "scrub": {"dry_run": True, "apply": False,
                                                "n_issues": 0, "n_high_medium": 0,
                                                "applied": 0}},
                            round_index=7, prev_candidates=5, wired=wired)

    ok([s["step"] for s in steps] == list(SL.STEPS),
       "G1 台账恒九条且顺序 = STEPS（不变）", [s["step"] for s in steps])
    ok(SL.STEPS.index("weights") == 4 and SL.STEPS.index("reindex") == 5,
       "G1a STEPS 里 ⑤⑥ 位次仍是 4/5（顺序语义不变）")
    ok(all(s.get("name") for s in steps), "G1b 每步都有显式中文名")

    w5, w6 = _step(steps, "weights"), _step(steps, "reindex")
    ok("skipped" not in w5 and "skipped" not in w6,
       "G1c ⑤⑥ **不再**记 skipped=='未接线'（占位分支已撤）",
       (w5.get("skipped"), w6.get("skipped")))
    ok(w5.get("ok") is True and w6.get("ok") is True,
       "G1d ⑤⑥ 记 ok=True（真跑过）")
    ok(w5.get("readout", {}).get("nodes_scanned") == 3
       and w5["readout"].get("changed") == 1,
       "G1e ⑤ 带真读数：nodes_scanned / changed（非空转占位）", w5.get("readout"))
    ok(w6.get("readout", {}).get("entries") == 7
       and isinstance(w6["readout"].get("elapsed_ms"), int),
       "G1f ⑥ 带真读数：entries / elapsed_ms", w6.get("readout"))
    # ⑤ 的既有读数里也有一个 `skipped`（跳过的节点**计数**，与台账的 skip 标记
    # 同名不同义）——整块并入会让 ⑤ 条目带上该字面量，正好踩中判据。故显式钉住。
    ok("skipped" not in w5 and "skipped" not in w6,
       "G1j ⑤⑥ 条目**任何来源**都不带 skipped 键（含同名计数键）",
       (sorted(set(w5) & {"skipped"}), sorted(set(w6) & {"skipped"})))
    ok(w5.get("wired") and w6.get("wired"),
       "G1g ⑤⑥ 附 wired 接线说明（替代旧 planned）")

    for key, shape in _PRE_SHAPE.items():
        s = _step(steps, key)
        want = set(shape) | (_SKIP_OK if s is not None
                             and "skipped" in s else set())
        got = set(s or {})
        ok(s is not None and want <= got,
           "G1h 其余七步·%s 字段形状不变（⊇ 接线前字段集）" % key,
           sorted(want - got))
    ok([_step(steps, k)["step"] for k in
        ("record", "feedback", "self_check")] == ["record", "feedback",
                                                  "self_check"],
       "G1i ⑦⑧⑨ 次序与在场不变")


# ---------------------------------------------------------------- G2
def g2_entry_points():
    print("== G2 入口指向：真调既有权重/索引入口 + NOT_WIRED 已删 ==")
    src = _src()
    code = _code(src)
    ok("NOT_WIRED" not in code,
       "G2 NOT_WIRED 常量已删且无其它引用（活代码零命中）")
    ok('"未接线"' not in code,
       "G2a sleep.py 活代码里再无 '未接线' 字面量（旧记账分支已撤）")
    ok("def wired_steps(" in code and "from . import weights as _w" in code
       and "_w.recalc(cg, apply=allow_apply" in code,
       "G2b ⑤ 经既有入口 weights.recalc 调用（import 后调用，非另写一份）")
    ok("from . import refindex as _ri" in code
       and "_ri.rebuild(cg, ledger=" in code
       and "_ri.Ledger(cg.root) if allow_apply else None" in code,
       "G2c ⑥ 经既有入口 refindex.rebuild 调用（写盘态挂 Ledger(root)、"
       "只读态传 None）")
    ok("from . import provenance as _pv" in code
       and "_pv.rebuild_ledger(cg, apply=allow_apply)" in code,
       "G2d ⑥ 并调 provenance.rebuild_ledger（六面/因果台账重建）")
    ok("'weights':" not in code.split("def ledger_steps")[1][:400]
       or "skipped" not in code.split("def ledger_steps")[1][:600],
       "G2g ledger_steps 里 ⑤⑥ 分支不再硬写 skip 占位")

    # 真调用（最小库）：回报的键来自既有实现的返回体
    root, _state = _fixture("g2")
    from md_cg.mdcos import MdCGOS
    cg = MdCGOS(root)
    r5 = SL.wired_steps(cg, "weights")
    r6 = SL.wired_steps(cg, "reindex")
    ok(r5.get("ok") is True and "nodes_scanned" in (r5.get("readout") or {}),
       "G2e ⑤ 真跑 weights.recalc 并回报 nodes_scanned",
       r5.get("readout") or r5.get("error"))
    ok(r6.get("ok") is True and "entries" in (r6.get("readout") or {}),
       "G2f ⑥ 真跑重建入口并回报 entries",
       r6.get("readout") or r6.get("error"))
    cg.close()


# ---------------------------------------------------------------- G3
def g3_end_to_end_ledger():
    print("== G3 端到端：临时影子根造最小库 → 跑一轮 sleep 台账生成 ==")
    root, state = _fixture("g3")
    from md_cg.mdcos import MdCGOS
    cg = MdCGOS(root)
    rec = SL.run_cycle(cg, batch="T91A-G3", window="", now="12:00",
                       merge_mode="never", round_index=3)
    steps = rec.get("steps") or []
    ok(len(steps) == 9 and [s["step"] for s in steps] == list(SL.STEPS),
       "G3 一轮 run_cycle 落九条台账", [s.get("step") for s in steps])

    w5, w6 = _step(steps, "weights"), _step(steps, "reindex")
    ok(w5 is not None and w5.get("skipped") != "未接线",
       "G3a 台账 ⑤weights 不再是 skipped:'未接线'", (w5 or {}).get("skipped"))
    ok(w6 is not None and w6.get("skipped") != "未接线",
       "G3b 台账 ⑥reindex 不再是 skipped:'未接线'", (w6 or {}).get("skipped"))
    ok((w5 or {}).get("readout", {}).get("nodes_scanned", 0) >= 2,
       "G3c ⑤ 真读数·本轮参与重算的节点数 ≥ 2（非空转）",
       (w5 or {}).get("readout"))
    ok("skipped" not in (w5 or {}) and "skipped" not in (w6 or {}),
       "G3g 真跑一轮后台账 ⑤⑥ 也无 skipped 键",
       ((w5 or {}).get("skipped"), (w6 or {}).get("skipped")))
    ok("changed" in ((w5 or {}).get("readout") or {}),
       "G3d ⑤ 真读数·改动数 changed 在场", (w5 or {}).get("readout"))
    ok(isinstance((w6 or {}).get("readout", {}).get("entries"), int)
       and isinstance((w6 or {}).get("readout", {}).get("elapsed_ms"), int),
       "G3e ⑥ 真读数·重建条目数 entries 与耗时 elapsed_ms 在场",
       (w6 or {}).get("readout"))

    led = SL.read_ledger(limit=1)
    ok(bool(led) and led[-1].get("batch") == "T91A-G3",
       "G3f 台账已落盘（read_ledger 读回本轮）",
       [r.get("batch") for r in led])
    cg.close()


# ---------------------------------------------------------------- G4
def g4_failure_does_not_block():
    print("== G4 失败不阻断：⑥ 入口打成必抛 → 整轮仍出九条台账 ==")
    # 对照轮：同一库、同一轮次、**不注入失败**，先取本轮七步的基线形状。
    # ②③④ 在门拦/未迭代时只记 {step,name,skipped}（接线前即如此，已对
    # git HEAD 版 sleep.py 实测比对），故「形状不变」须按**同一路径**对照，
    # 不能拿「已迭代」轮的字段集去套「门拦」轮。
    root_c, _sc = _fixture("g4ctl")
    from md_cg.mdcos import MdCGOS
    cg_c = MdCGOS(root_c)
    rec_c = SL.run_cycle(cg_c, batch="T91A-G4CTL", window="", now="12:00",
                         merge_mode="never", round_index=4)
    cg_c.close()
    base_shape = {k: set(_step(rec_c.get("steps") or [], k) or {})
                  for k in _PRE_SHAPE}
    print("  对照轮（无注入）②③④形状：%s"
          % {k: sorted(v) for k, v in base_shape.items()
             if k in ("induce", "promote", "scrub")})

    root, _state = _fixture("g4")
    from md_cg import refindex as RI
    real = RI.rebuild
    try:
        def boom(*a, **kw):
            raise RuntimeError("T91A-注入失败：重建入口必抛")
        RI.rebuild = boom
        cg = MdCGOS(root)
        rec = SL.run_cycle(cg, batch="T91A-G4", window="", now="12:00",
                           merge_mode="never", round_index=4)
        cg.close()
    finally:
        RI.rebuild = real

    steps = rec.get("steps") or []
    ok(len(steps) == 9, "G4 ⑥ 抛异常后整轮**未被阻断**：台账仍是九条",
       len(steps))
    ok([s["step"] for s in steps] == list(SL.STEPS),
       "G4f ⑥ 抛异常后台账次序仍是 STEPS")
    w6 = _step(steps, "reindex")
    ok(w6 is not None and w6.get("ok") is False,
       "G4a ⑥ 记 ok=False（如实说没做成）", (w6 or {}).get("ok"))
    ok("RuntimeError" in ((w6 or {}).get("error") or ""),
       "G4b ⑥ 记 error 摘要（异常类型 + 消息）", (w6 or {}).get("error"))
    w5 = _step(steps, "weights")
    ok(w5 is not None and w5.get("ok") is True,
       "G4c ⑤ 不受 ⑥ 影响（各自独立吞异常）", (w5 or {}).get("ok"))
    for key in _PRE_SHAPE:
        s = _step(steps, key)
        got = set(s or {})
        want = base_shape[key]
        ok(s is not None and got == want,
           "G4d 其余七步·%s 形状在失败轮里与对照轮**逐字段相同**" % key,
           (sorted(want - got), sorted(got - want)))
    ok(rec.get("skipped") is None or isinstance(rec.get("skipped"), str),
       "G4e run_cycle 正常返回（未把异常抛给调用方）")


def g5_wired_no_overreach():
    """t91a-20261011/t1 **返工守卫**：wired 两步不许越权写主库。

    旧形态把 wired 段放在四道门**之外**且对主库 apply=True 直接执行 ⇒
    窗口外 / ask 档 / 稳态照写主库工作树，留**未提交脏工作树**，连锁污染
    下一轮 semantic_delta 与 git revert。本组按三条落地：
      a) 窗口外：主库真源面逐位不变、_maintain.jsonl 零新增、无派生面新增；
      b) ask 档：主库零写入；
      c) 正常 auto 档真迭代：wired 写盘后工作树保持干净（无未提交残留）。
    """
    print("== G5 wired 不越权：四道门 + merge 语义约束（返工守卫）==")
    from md_cg.mdcos import MdCGOS

    # ---- a) 窗口外（gate_reason 非 None）：主库零写入 ----------------------
    root, state = _fixture("g5a", contextual_hot=1, unverified=1)
    cg = MdCGOS(root)
    face0 = SL.source_face_hashes(root)
    mnt0 = _maintain_lines(root)
    files0 = _listing(root)
    rec = SL.run_cycle(cg, batch="T91A-G5A", window="23:00-07:00", now="12:00",
                       round_index=5)
    ok(bool(rec.get("skipped")) and "窗口外" in rec["skipped"],
       "G5a0 前置：本轮确实是窗口外门拦（未迭代）", rec.get("skipped"))
    ok(SL.source_face_hashes(root) == face0,
       "G5a 窗口外 ⇒ wired **不写主库真源面**（.md 哈希逐位不变）",
       SL.face_delta(face0, SL.source_face_hashes(root)))
    ok(_maintain_lines(root) == mnt0,
       "G5a2 窗口外 ⇒ **_maintain.jsonl 零新增行**（★返工缺陷的直接判据）",
       (_maintain_lines(root), mnt0))
    ok(_listing(root) == files0,
       "G5a3 窗口外 ⇒ **主库无任何新增文件**（含派生面 _refindex.json）",
       sorted(_listing(root) - files0))
    w5, w6 = _wired(rec["steps"], "weights"), _wired(rec["steps"], "reindex")
    ok((w5.get("readout") or {}).get("apply") is False
       and (w6.get("readout") or {}).get("apply") is False,
       "G5a4 窗口外 ⇒ ⑤⑥ 台账条目如实记 apply=False（只预演）",
       ((w5.get("readout") or {}).get("apply"),
        (w6.get("readout") or {}).get("apply")))
    ok(bool(w5.get("not_written_reason")) and bool(w6.get("not_written_reason")),
       "G5a5 窗口外 ⇒ ⑤⑥ 如实记「为何没写盘」（不静默）",
       (w5.get("not_written_reason"), w6.get("not_written_reason")))
    ok(isinstance((w5.get("readout") or {}).get("nodes_scanned"), int)
       and isinstance((w6.get("readout") or {}).get("elapsed_ms"), int),
       "G5a6 窗口外 ⇒ ⑤⑥ 仍出**真读数**（只读预演不是空转占位）",
       (w5.get("readout"), w6.get("readout")))
    cg.close()

    # ---- b) ask 档：主库零写入 -------------------------------------------
    root, state = _fixture("g5b", contextual_hot=1, unverified=1)
    cg = MdCGOS(root)
    face0 = SL.source_face_hashes(root)
    mnt0 = _maintain_lines(root)
    files0 = _listing(root)
    ra = SL.run_cycle(cg, batch="T91A-G5B", round_index=6, now="03:00",
                      window="", merge_mode="ask")
    ph = (ra["steps"][6]["phases"] or {}).get("merge") or {}
    ok(ph.get("deferred") == "ask",
       "G5b0 前置：ask 档合并确实挂起（merge deferred=ask）", ph)
    ok(SL.source_face_hashes(root) == face0,
       "G5b ask 档 ⇒ 主库真源面逐位不变",
       SL.face_delta(face0, SL.source_face_hashes(root)))
    ok(_maintain_lines(root) == mnt0,
       "G5b2 ask 档 ⇒ _maintain.jsonl 零新增行", (_maintain_lines(root), mnt0))
    ok(_listing(root) == files0,
       "G5b3 ask 档 ⇒ 主库无任何新增文件", sorted(_listing(root) - files0))
    w5 = _wired(ra["steps"], "weights")
    ok((w5.get("readout") or {}).get("apply") is False,
       "G5b4 ask 档 ⇒ ⑤ apply=False（不写主库）",
       (w5.get("readout") or {}).get("apply"))
    cg.close()

    # ---- c) 正常 auto 档真迭代：写盘后工作树干净 --------------------------
    root, state = _fixture("g5c", contextual_hot=1, unverified=1)
    cg = MdCGOS(root)
    rc = SL.run_cycle(cg, batch="T91A-G5C", round_index=7, now="03:00",
                      window="")
    ok(rc.get("merged") is True,
       "G5c0 前置：本轮走的是**真迭代 + 真合并**路径", rc.get("merged"))
    st = _git(root, state, "status", "--porcelain").stdout or ""
    dirty_md = [ln for ln in st.splitlines()
                if ln.strip().endswith(".md") and ln[:2].strip() in ("M", "A", "D")]
    ok(not dirty_md,
       "G5c 真迭代轮 ⇒ wired 写盘后**无未提交脏 .md**（工作树保持干净）",
       dirty_md)
    ok(_maintain_lines(root) == 0,
       "G5c2 真迭代轮 ⇒ _maintain.jsonl 无未提交新增行（写盘须随提交走）",
       _maintain_lines(root))
    w5 = _wired(rc["steps"], "weights")
    ok(isinstance((w5.get("readout") or {}).get("nodes_scanned"), int),
       "G5c3 真迭代轮 ⇒ ⑤ 仍有真读数（判据 ② 不被返工打回）", w5.get("readout"))
    ok((w5.get("readout") or {}).get("apply") is False,
       "G5c4 真迭代轮 ⇒ 本轮 wired 仍只预演（写盘会留脏，故不放行）",
       (w5.get("readout") or {}).get("apply"))
    cg.close()

    # ---- d) 端到端一致性：合并轮的工作树干净，下一轮 Δ 才不被污染 ---------
    root, state = _fixture("g5d", contextual_hot=1, unverified=1)
    cg = MdCGOS(root)
    SL.run_cycle(cg, batch="T91A-G5D1", round_index=8, now="03:00", window="")
    st = _git(root, state, "status", "--porcelain").stdout or ""
    ok(not [ln for ln in st.splitlines()
            if ln.strip().endswith(".md") and ln[:2].strip() in ("M", "A", "D")],
       "G5d 第一轮合并后工作树干净（链条起点：不留脏）", st.splitlines())
    cg.close()


def main() -> int:
    _sandbox_env()
    try:
        for fn in (g1_ledger_shape, g2_entry_points, g3_end_to_end_ledger,
                   g4_failure_does_not_block, g5_wired_no_overreach):
            try:
                fn()
            except Exception as e:                             # noqa: BLE001
                import traceback
                traceback.print_exc()
                ok(False, "%s 抛异常：%s: %s" % (fn.__name__, type(e).__name__, e))
        print("\nt91a 睡眠接线守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
        return 0 if not _FAIL else 1
    finally:
        _restore_env()
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
