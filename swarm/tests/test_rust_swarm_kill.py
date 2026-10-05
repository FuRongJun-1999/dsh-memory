# -*- coding: utf-8 -*-
"""test_rust_swarm_kill.py · C1 恢复演练：强杀协调器后重入续跑（心跳任务 2026-09-13）
A6 验收口径第 1 条硬核版：kill 落在任意中途点（含「事件已写、快照未写」的半轮），
重入同 WAL 跑到完成 → 终态/HMAC 链/事件结构与一次跑完一致。
前置加固：B1 回滚规则——快照=提交点，快照后未提交轮次整体回滚（防重放+重跑重复）。
N264（测试侧时序缝隙）：kill 落在 WAL 行追加窗口时末行是半行——产品合同容忍坏尾
（重放停在截断点 / 恢复物理截断坏尾后续跑），故读取侧走 _read_wal 分层容忍：
末行坏尾=torn（如实记录片段），非末行失败=bads（调用处必判 FAIL）；恢复后全行严格可解析。
内嵌确定性自检（每次运行都跑；`--selfcheck` 快路只跑自检段）。
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


# ===== N264：WAL 读取助手（坏尾分层容忍）+ 内嵌确定性自检 =====
# 修前现场（CI run 37264469853）：kill 落在 WAL 行追加中途 → 末行半行，
# 原直读 `lines = [json.loads(x) ...]`（本文件 ② 后）无容忍 →
# json.decoder.JSONDecodeError: Unterminated string ... 崩测。
# 产品合同明确容忍坏尾：重放经坏尾守卫停在截断点（swarm/rust_runtime/src/
# swarm.rs:525「半行（崩溃残留）→ 提交点搜索止于此」），恢复模式「好行原子
# 换入（物理截断坏尾）→ append 续跑」（同文件 :633）——故：
#   末行解析失败 = torn（kill 撕裂窗口的合法坏尾，容忍并如实记录片段）；
#   非末行解析失败 = bads（不在容忍面，调用处必须判 FAIL，不得无条件放过）。
# 恢复（③ 重入）完成后产品已物理截断坏尾 ⇒ wal_b 每条非空行必须可完整解析。


def _read_wal(path):
    """读 WAL 非空行 → (events, torn, bads, torn_frag)。

    events: [(行号, dict)] 解析成功的行（按行序）。
    torn:   末条非空行解析失败的条数（0 或 1）——半行坏尾，容忍面。
    bads:   [(行号, 片段)] 非末条非空行解析失败——容忍面之外，调用处必判 FAIL。
    torn_frag: torn=1 时末行片段（如实记录，供打印）；否则空串。
    """
    rows = []  # (行号, strip 后原文)
    with open(path, encoding="utf-8", errors="replace") as f:
        for line_no, raw in enumerate(f, 1):
            text = raw.strip()
            if text:
                rows.append((line_no, text))
    events, bads = [], []
    torn_frag = ""
    for idx, (line_no, text) in enumerate(rows):
        try:
            events.append((line_no, json.loads(text)))
        except json.JSONDecodeError:
            if idx == len(rows) - 1:
                torn_frag = text[:160]  # 末行坏尾：容忍 + 如实记录片段
            else:
                bads.append((line_no, text[:160]))
    return events, (1 if torn_frag else 0), bads, torn_frag


def _fail_on_bads(name, bads):
    """非末行解析失败 → 必须判 FAIL（打印行号与片段），返回 False 阻断放行。

    返回 True = 无非末行失败（放过）。「非末行必须 FAIL」的语义由自检②钉住。
    """
    for line_no, frag in bads:
        print(f"    [{name}] WAL 行 {line_no} 解析失败（非末行，不容忍）：{frag}")
    return not bads


def _run_selfcheck():
    """N264 内嵌确定性自检：不依赖 kill/子进程，每次运行都跑。

    ① 好行+末行半行 → 助手不崩、torn=1、不算 bads（产品合同容忍面）；
    ② 好行+中间半行+好行 → bads 非空且调用处必判 FAIL（不容忍面）。
    """
    d = tempfile.mkdtemp(prefix="swarm_kill_selfcheck_")
    good = json.dumps({"type": "__snapshot__", "round": 1, "seq": 1},
                      ensure_ascii=False)
    half = '{"type": "__snapshot__", "round": 2, "seq":'  # 半行（无结尾换行）
    print("=== ⓪ 内嵌自检（N264：坏尾容忍 / 非末行必 FAIL） ===")

    # ① 末行半行 = kill 撕裂窗口的确定性等价夹具
    p1 = os.path.join(d, "torn_tail.jsonl")
    with open(p1, "w", encoding="utf-8") as f:
        f.write(good + "\n" + half)
    ev1, torn1, bads1, frag1 = _read_wal(p1)
    check("自检①：好行+末行半行 → 助手不崩（读出 1 条好行）", len(ev1) == 1)
    check("自检①：末行半行计 torn=1（容忍面）", torn1 == 1)
    check("自检①：末行半行不进 bads", not bads1)
    check("自检①：末行片段如实记录", frag1 == half)

    # ② 中间半行 = 非末行失败（若被放过即掩盖损坏，必须 FAIL）
    p2 = os.path.join(d, "torn_mid.jsonl")
    with open(p2, "w", encoding="utf-8") as f:
        f.write(good + "\n" + half + "\n" + good + "\n")
    ev2, torn2, bads2, _frag2 = _read_wal(p2)
    check("自检②：中间半行 → bads 非空且 torn=0",
          len(ev2) == 2 and len(bads2) == 1 and torn2 == 0,
          f"events={len(ev2)} bads={len(bads2)} torn={torn2}")
    check("自检②：调用处对非末行失败必判 FAIL",
          _fail_on_bads("自检②", bads2) is False)
    return d


# `--selfcheck` 快路：只跑自检段（供变异自证与快速回归），
# 不生成项目 / 不 kill / 不跑 600 轮；故置于 swarm 包导入之前。
if "--selfcheck" in sys.argv:
    _run_selfcheck()
    print(f"\n{pass_n} passed, {fail_n} failed")
    sys.exit(1 if fail_n else 0)


from swarm.rust_codegen import generate_rust_project
from swarm.rust_swarm import (make_swarm_config, run_swarm,
                             verify_wal_signatures)

SOURCE = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
SECRET = "验收密钥-蜂群C1击杀"
ROUNDS = 600  # 每轮 ~8ms：sleep(1.0) 时 K≈120，确保 kill 落在真实中途点

_run_selfcheck()  # N264：确定性判据，不依赖 kill，每次运行都跑

tmp = tempfile.mkdtemp(prefix="swarm_kill_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
check("项目生成", gen["ok"])

CFG = make_swarm_config(
    instances=[
        {"id": "实例甲", "role": "记录", "trust": 0.1},
        {"id": "实例乙", "role": "验证", "trust": 0.2},
        {"id": "实例丙", "role": "观察", "trust": 0.1},
        {"id": "实例丁", "role": "备份", "trust": 0.2},
    ],
    routes=[{"from": "实例甲", "event_type": "信任同步", "to": "实例乙",
             "payload": "@trust", "level": 0}],
    rounds=ROUNDS, shared_secret=SECRET)

# ============ ① 基线：一次跑完（另一 WAL） ============
print("=== ① 基线：一次跑完 ===")
wal_a = os.path.join(tmp, "events_a.jsonl")
rr_a = run_swarm(proj, CFG, wal_path=wal_a)
check("基线运行", rr_a["ok"], str(rr_a.get("stderr", ""))[:150])

# ============ ② 强杀：Popen 启动 → sleep → kill ============
print("=== ② 强杀协调器（中途点不确定=演练真实性） ===")
wal_b = os.path.join(tmp, "events_b.jsonl")
cfg_path = os.path.join(proj, "swarm_kill.json")
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)
exe = None
for cand in (os.path.join(proj, "target", "release", "protocol_vm.exe"),
             os.path.join(proj, "target", "release", "protocol_vm")):
    if os.path.exists(cand):
        exe = cand
        break
check("可执行文件在位", exe is not None, str(exe))
p = subprocess.Popen([exe, "swarm", "--config", cfg_path, "--wal", wal_b],
                     cwd=proj, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
# 轮询等快照轮 ≥50 即杀（B2 并行后每轮 ~1.6ms，固定 sleep 无法确定性命中中途）
target_round = 50
k = 0
while k < target_round and p.poll() is None:
    time.sleep(0.02)
    try:
        with open(wal_b, encoding="utf-8") as f:
            for line in f:
                if '"__snapshot__"' in line:
                    k = json.loads(line)["round"]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
p.kill()
p.wait()
time.sleep(0.5)  # 子实例因管道关闭退场（serve.rs:268）的余量

wal_b_rows, torn_b, bads_b, torn_frag_b = _read_wal(wal_b)
if torn_frag_b:
    print(f"    [WAL 坏尾·容忍] 末行半行（kill 撕裂窗口）：{torn_frag_b}")
check("kill 后直读：坏尾至多一条且仅在末行（非末行失败=0）",
      torn_b <= 1 and _fail_on_bads("kill 后直读", bads_b),
      f"rows={len(wal_b_rows)} torn={torn_b} bads={len(bads_b)}")
lines = [d for _, d in wal_b_rows]
snaps_k = [x for x in lines if x["type"] == "__snapshot__"]
k = snaps_k[-1]["round"] if snaps_k else 0
check(f"kill 时快照轮 K={k}（1 ≤ K，真实中途点）", k >= 1, f"rows={len(lines)}")

# ============ ③ 重入：同 WAL 跑到完成 ============
print("=== ③ 重入续跑 ===")
rr_b = run_swarm(proj, CFG, wal_path=wal_b)
check("恢复续跑完成", rr_b["ok"], str(rr_b.get("stderr", ""))[:200])

# ============ ④ 结构不变量：kill 恢复 = 基线 ============
print("=== ④ 结构不变量比对 ===")
v_a = verify_wal_signatures(wal_a, SECRET)
v_b = verify_wal_signatures(wal_b, SECRET)
check("kill 恢复 WAL 全验签通过", v_b["all_valid"], f"bad={v_b['bad']}")
check(f"事件计数=基线({v_a['total']})", v_b["total"] == v_a["total"],
      f"a={v_a['total']} b={v_b['total']}")
wal_b_rows2, torn_b2, bads_b2, _torn_frag_b2 = _read_wal(wal_b)
check("恢复后 WAL 每条非空行可完整解析（产品已物理截断坏尾）",
      torn_b2 == 0 and _fail_on_bads("恢复后 WAL", bads_b2),
      f"torn={torn_b2} bads={len(bads_b2)}")
snaps_b = [d["round"] for _, d in wal_b_rows2
           if isinstance(d, dict) and d.get("type") == "__snapshot__"]
check(f"快照轮号连续 1..{ROUNDS}（无重复无缺失）",
      snaps_b == list(range(1, ROUNDS + 1)),
      f"n={len(snaps_b)} head={snaps_b[:3]} tail={snaps_b[-3:]}")
if rr_b["ok"] and rr_a["ok"]:
    fs_a, fs_b = rr_a["report"]["final_states"], rr_b["report"]["final_states"]
    same = all(abs(fs_a[i]["trust"] - fs_b[i]["trust"]) < 1e-9
               for i in fs_a)
    check("四实例终态 trust 与基线一致", same,
          json.dumps({k2: fs_b[k2]["trust"] for k2 in fs_b}))
    check("信任聚合与基线一致(T_avg)",
          abs(rr_a["report"]["trust"]["T_avg"]
              - rr_b["report"]["trust"]["T_avg"]) < 1e-9)
    check("无重复事件(事件总数=基线)",
          rr_b["report"]["events"] == rr_a["report"]["events"],
          f"b={rr_b['report']['events']} a={rr_a['report']['events']}")

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
