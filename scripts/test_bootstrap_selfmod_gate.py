# -*- coding: utf-8 -*-
"""test_bootstrap_selfmod_gate —— 自举循环「固化前快照/审计/裁决」闭环守卫（A5）

背景（2026-10-05 使用者裁决 A5）：`scripts/bootstrap_loop.py:16` 的 docstring 承诺
「四机制安全闭环：selfmod 快照/审计/裁决 在每次固化前强制执行」，但全仓
`git grep selfmod` **只命中该行自身**——两条固化路径（通道 A `persist_triggers`
写 WISDOM 单元表源文件、通道 B verified 落盘 `channel_b_verified_units.json`）
零快照、零审计、零裁决调用。裁决＝补实现（原话「这是理论设计和实践脱节，固化前
必须验证，这是血的教训」）。

守卫断言面（全部为**行为断言**：真跑固化路径 + 真读盘面字节，不做源码文本匹配）：
  S0 前提坐实：修后台架确实能固化（通道 A 真写进单元表、通道 B 真落 verified 账）
  S1 固化发生时快照在位：每个被改目标都有逐字节前像（== 改前字节），且审计台账
     有本次记录（动作类/前像引用/判据值齐备）
  S2 裁决不通过时固化被拒且**不改盘**（五条拒绝路径逐条）：
     a) 未过既有验证  b) 目标在授权自改写面之外  c) 前像失效（TOCTOU：拍像后文件
     被第三方改动）  d) 快照失败  e) 审计失败——后四条均以**故障注入**触发
  S3 通道 B 同款：固化时快照+台账在场；裁决拒绝时 verified 账**不落盘**、条目
     不标 verified（不谎报已固化）、stats 记 selfmod_rejected

台架隔离：哑 datapath（STATE 落临时目录）+ 临时 WISDOM 副本——绝不触真实数据根
与仓内 wisdom 源文件（与同目录 test_bootstrap_channel_b_state.py 同隔离法）。

运行：python -X utf8 scripts/test_bootstrap_selfmod_gate.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

passed = failed = skipped = 0

_UNIT_SRC = '''# -*- coding: utf-8 -*-
DOMAIN_UNITS = {
    "graph": {
        "gap-unit-1": {
            "task": "图单元占位",
        },
    },
}
'''


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail).replace("\n", " | ")[:400])


def skip(name, why):
    global skipped
    skipped += 1
    print("  [SKIP] %s（%s）" % (name, why))


def _load(tmp):
    """哑 datapath + 临时 STATE/WISDOM 装载 bootstrap_loop（与 N169 守卫同隔离法）。"""
    dp = types.ModuleType("datapath")
    dp.data_root = staticmethod(lambda: tmp)
    dp.find_existing = staticmethod(lambda name: None)
    sys.modules["datapath"] = dp
    spec = importlib.util.spec_from_file_location(
        "bl_a5_selfmod", os.path.join(HERE, "scripts", "bootstrap_loop.py"))
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    return m


def _mk_wisdom(tmp):
    w = os.path.join(tmp, "wisdom")
    os.makedirs(w, exist_ok=True)
    with open(os.path.join(w, "graph_db_units.py"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(_UNIT_SRC)
    return w


def _selfmod_files(state):
    d = os.path.join(state, "selfmod")
    out = {"dir": d, "snapshots": [], "audit": os.path.join(d, "selfmod_audit.jsonl")}
    sd = os.path.join(d, "snapshots")
    if os.path.isdir(sd):
        out["snapshots"] = sorted(os.path.join(sd, n) for n in os.listdir(sd))
    return out


def _audit_records(path):
    if not os.path.isfile(path):
        return []
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except ValueError:
                pass
    return recs


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    tmp = tempfile.mkdtemp(prefix="a5_selfmod_")
    m = _load(tmp)
    m.STATE = os.path.join(tmp, "bootstrap")
    os.makedirs(m.STATE, exist_ok=True)
    m.WISDOM = _mk_wisdom(tmp)
    unit_path = os.path.join(m.WISDOM, "graph_db_units.py")
    patch = {"domain": "graph", "unit": "gap-unit-1", "add_triggers": ["触发甲"]}

    print("[1] 通道 A：固化 → 快照在位 + 审计台账有记录")
    before = open(unit_path, "rb").read()
    changed = m.persist_triggers([patch])
    after = open(unit_path, "rb").read()
    check("S0 前提：通道 A 真固化（单元表被写进 triggers）",
          changed == 1 and b'"triggers"' in after and after != before,
          "changed=%s" % changed)
    sm = _selfmod_files(m.STATE)
    check("S1 快照目录在场且逐字节前像 == 改前字节",
          len(sm["snapshots"]) == 1
          and open(sm["snapshots"][0], "rb").read() == before,
          (len(sm["snapshots"]), sm["dir"]))
    recs = _audit_records(sm["audit"])
    check("S1 审计台账有本次记录（动作类/前像引用/判据齐备）",
          len(recs) >= 1 and any(
              r.get("action") == "C" and r.get("ok") is True
              and r.get("snapshots") for r in recs),
          recs[-1] if recs else "台账不存在")

    print("[2] 裁决不通过 → 拒且不改盘（五条路径）")
    # a) 未过既有验证
    b1 = open(unit_path, "rb").read()
    v = m.selfmod_gate([unit_path], action="C", why="S2a", verified=False,
                       expect_sha={unit_path: m._selfmod_sha(b1)})
    check("S2a 未过验证 → 拒（ok=False）", v.get("ok") is False, v)
    check("S2a 拒后目标字节不变", open(unit_path, "rb").read() == b1)
    check("S2a 拒绝也在台账留痕（ok=False 记录）",
          any(r.get("ok") is False for r in _audit_records(sm["audit"])),
          _audit_records(sm["audit"])[-1:])

    # b) 授权自改写面之外
    outside = os.path.join(tmp, "outside.py")
    with open(outside, "w", encoding="utf-8", newline="\n") as f:
        f.write("X = 1\n")
    ob = open(outside, "rb").read()
    v = m.selfmod_gate([outside], action="C", why="S2b")
    check("S2b 写面外目标 → 拒", v.get("ok") is False, v)
    check("S2b 拒后写面外文件字节不变", open(outside, "rb").read() == ob)

    # c) 前像失效（TOCTOU：拍像之后文件被第三方改动）
    b3 = open(unit_path, "rb").read()
    real_snap = m._selfmod_snapshot

    def _snap_then_tamper(path):
        rel = real_snap(path)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write("# 第三方改动\n")
        return rel

    m._selfmod_snapshot = _snap_then_tamper
    try:
        v = m.selfmod_gate([unit_path], action="C", why="S2c",
                           expect_sha={unit_path: m._selfmod_sha(b3)})
    finally:
        m._selfmod_snapshot = real_snap
    tampered = open(unit_path, "rb").read()
    check("S2c 前像失效（TOCTOU）→ 拒", v.get("ok") is False, v)
    check("S2c 拒后不覆盖第三方改动（文件保留新内容）",
          tampered != b3 and "第三方改动".encode("utf-8") in tampered,
          tampered[-40:])

    # d) 快照失败
    b4 = open(unit_path, "rb").read()

    def _snap_boom(path):
        raise OSError("S2d 注入：快照盘不可写")

    m._selfmod_snapshot = _snap_boom
    try:
        v = m.selfmod_gate([unit_path], action="C", why="S2d",
                           expect_sha={unit_path: m._selfmod_sha(b4)})
    finally:
        m._selfmod_snapshot = real_snap
    check("S2d 快照失败 → 拒", v.get("ok") is False, v)
    check("S2d 拒后目标字节不变", open(unit_path, "rb").read() == b4)

    # e) 审计失败（台账不可写 ⇒ 固化不许发生）
    import fsutil                                   # 既有单点（纯标准库）
    real_append = fsutil.append_jsonl
    b5 = open(unit_path, "rb").read()
    fsutil.append_jsonl = lambda *a, **k: (_ for _ in ()).throw(OSError("S2e 注入：台账不可写"))
    try:
        v = m.selfmod_gate([unit_path], action="C", why="S2e",
                           expect_sha={unit_path: m._selfmod_sha(b5)})
    finally:
        fsutil.append_jsonl = real_append
    check("S2e 审计失败 → 拒", v.get("ok") is False, v)
    check("S2e 拒后目标字节不变", open(unit_path, "rb").read() == b5)

    # 端到端：调用方（persist_triggers）必须服从裁决——裁决拒 ⇒ 不写盘
    print("[3] 端到端：调用方服从裁决（拒 ⇒ 不改盘）")
    m2 = _load(os.path.join(tmp, "e2e"))
    m2.STATE = os.path.join(tmp, "e2e", "bootstrap")
    os.makedirs(m2.STATE, exist_ok=True)
    m2.WISDOM = _mk_wisdom(os.path.join(tmp, "e2e"))
    e2e_unit = os.path.join(m2.WISDOM, "graph_db_units.py")
    e2e_before = open(e2e_unit, "rb").read()
    m2.selfmod_gate = lambda *a, **k: {"ok": False, "why": "S3 注入：裁决拒"}
    changed2 = m2.persist_triggers([patch])
    check("S3 通道 A：裁决拒 ⇒ changed=0 且单元表字节不变",
          changed2 == 0 and open(e2e_unit, "rb").read() == e2e_before,
          "changed=%s" % changed2)

    print("[4] 通道 B：verified 固化 → 快照/台账在场；裁决拒 ⇒ 不落盘")
    good_code = "def good_add(a, b):\n    return a + b\n"
    q = {"pending": [{"task": "A5好1", "code": good_code,
                      "cases": [[[3, 4], 7]], "status": "new"}]}
    m4 = _load(os.path.join(tmp, "chb_ok"))     # 独立装载：不带 S3 的注入桩
    m4.STATE = os.path.join(tmp, "chb_ok", "bootstrap")
    os.makedirs(m4.STATE, exist_ok=True)
    m4.WISDOM = _mk_wisdom(os.path.join(tmp, "chb_ok"))
    with open(os.path.join(m4.STATE, "channel_b_queue.json"), "w",
              encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False)
    res = m4.run_channel_b(None, max_tasks=5)
    check("S4 前提：verified 账真落盘（passed=1）",
          res.get("passed") == 1, repr(res))
    sm2 = _selfmod_files(m4.STATE)
    check("S4 通道 B 固化：审计台账有本次记录（动作类 A）",
          any(r.get("action") == "A" and r.get("ok") is True
              for r in _audit_records(sm2["audit"])),
          _audit_records(sm2["audit"])[-1:])
    check("S4 通道 B 固化：台账记录含前像引用字段（files/snapshots 键）",
          any("files" in r and "snapshots" in r
              for r in _audit_records(sm2["audit"])),
          _audit_records(sm2["audit"])[-1:])
    # 第二轮（verified 账已存在）：固化时必须先拍**该账的逐字节前像**
    ledger = os.path.join(m4.STATE, "channel_b_verified_units.json")
    ledger_before = open(ledger, "rb").read()
    q2 = {"pending": [{"task": "A5好2", "code": good_code,
                       "cases": [[[5, 6], 11]], "status": "new"}]}
    with open(os.path.join(m4.STATE, "channel_b_queue.json"), "w",
              encoding="utf-8") as f:
        json.dump(q2, f, ensure_ascii=False)
    res_b = m4.run_channel_b(None, max_tasks=5)
    sm2b = _selfmod_files(m4.STATE)
    check("S4b 第二轮固化（账已存在）：真落盘 second 条目",
          res_b.get("passed") == 1, repr(res_b))
    check("S4b 第二轮固化：verified 账的逐字节前像在位",
          any(open(s, "rb").read() == ledger_before for s in sm2b["snapshots"]),
          (len(sm2b["snapshots"]), sm2b["snapshots"][-2:]))

    # 裁决拒 ⇒ verified 账不落盘、条目不得标 verified、stats 记 selfmod_rejected
    m3 = _load(os.path.join(tmp, "chb"))
    m3.STATE = os.path.join(tmp, "chb", "bootstrap")
    os.makedirs(m3.STATE, exist_ok=True)
    m3.WISDOM = _mk_wisdom(os.path.join(tmp, "chb"))
    with open(os.path.join(m3.STATE, "channel_b_queue.json"), "w",
              encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False)
    m3.selfmod_gate = lambda *a, **k: {"ok": False, "why": "S4 注入：裁决拒"}
    res3 = m3.run_channel_b(None, max_tasks=5)
    ledger = os.path.join(m3.STATE, "channel_b_verified_units.json")
    check("S4 裁决拒 ⇒ verified 账不落盘（无可固化即无文件）",
          not os.path.exists(ledger), os.path.exists(ledger))
    q3 = json.load(open(os.path.join(m3.STATE, "channel_b_queue.json"),
                        encoding="utf-8"))
    st3 = {t.get("task"): t.get("status") for t in q3.get("pending", [])}
    check("S4 裁决拒 ⇒ 条目不标 verified（不谎报已固化，仍 pending 待下轮）",
          st3.get("A5好1") != "verified", st3)
    check("S4 裁决拒 ⇒ stats 记 selfmod_rejected=1 且不计 passed",
          res3.get("selfmod_rejected") == 1 and res3.get("passed") == 0,
          repr(res3))

    print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
