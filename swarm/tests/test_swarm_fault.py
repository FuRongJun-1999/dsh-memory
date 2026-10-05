# -*- coding: utf-8 -*-
"""test_swarm_fault.py · G5 实例级容错验收（心跳任务 2026-09-13）
透明容错口径：运行中强杀两个 --serve 实例子进程 → 协调器同线程重建重跑该轮
（轮次号幂等）→ 蜂群无感完成，终态/水位/对账与无故障基线一致。
说明：重试仍失败的 dead 分支已实现（outcomes 记 None、uptime 降、蜂群继续），
单机下确定性触发需在重建后的极窄时序窗内二次击杀，留长稳/跨机验证。
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

from swarm.rust_codegen import generate_rust_project
from swarm.rust_swarm import make_swarm_config, build_rust_exe, run_swarm, verify_wal_signatures

pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


# 生效条件：health 为真值（非 None、非空映射）且其 values() 中每一项的 |score-1.0| < 1e-9 时返回 True；health 为 None、空映射、或任一 score 掉分时返回 False（不跳空面、不隐式补齐）。
def health_full_marks(health) -> bool:
    """N263 · 健康分满分判据（单点）：「面非空 ∧ 逐项满分」。

    旧码是内联的 `all(abs(h["score"] - 1.0) < 1e-9 for h in health.values())`
    ——Python 里 `all([]) == True`，于是**空** health 面（报告缺该面 / 零实例跑完）
    时断言恒真：断言永真、守护力为零（同族 N160 已登记，本件是不同文件的新实例）。
    修法：把「面非空」并入判据——空输入不再算通过；判据收成单点函数，供断言与
    定点变异自证（见文件末「③」段）共用，避免两处各写一份。

    编号 N263：`git grep -ohE 'N[0-9]{3,4}'` 树内实占最大为 N262（N8xx 是 ruff
    lint 码 `# noqa: N802`，已排除），新号自最大值之后续编、全局唯一。
    """
    return bool(health) and all(abs(h["score"] - 1.0) < 1e-9
                                for h in health.values())


SOURCE = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
SECRET = "验收密钥-蜂群G5容错"
ROUNDS = 6000

tmp = tempfile.mkdtemp(prefix="swarm_fault_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
check("项目生成", gen["ok"])

INST = [{"id": f"实例{i}", "role": "peer", "trust": 0.1} for i in range(6)]
CFG = make_swarm_config(INST,
                        routes=[{"from": "实例0", "event_type": "gossip", "to": "*",
                                 "payload": "@trust", "level": 0}],
                        rounds=ROUNDS, shared_secret=SECRET)
exe = build_rust_exe(proj)

# ============ ① 基线：无故障一次跑 ============
print("=== ① 基线（无故障） ===")
wal_a = os.path.join(tmp, "a.jsonl")
rr_a = run_swarm(proj, CFG, wal_path=wal_a)
check("基线运行", rr_a["ok"], str(rr_a.get("stderr", ""))[:150])

# ============ ② 运行中强杀两个 --serve 实例 → 蜂群无感完成 ============
print("=== ② 运行中强杀两个实例子进程 ===")
wal_b = os.path.join(tmp, "b.jsonl")
cfg_path = os.path.join(proj, "swarm_fault.json")
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(CFG, f, ensure_ascii=False)
subprocess.run(["powershell", "-NoProfile", "-Command", "1"],
               capture_output=True, timeout=30)  # 预热 PowerShell
# N263：故障跑的**在线报告**必须留下——「重试成功即透明」的健康面只在有在线执行窗口
# 的那次跑里生成（WAL 重放路径的 health 恒为空对象：逐轮终态质量未持久化，参与性重建
# 会伪造 success_rate，G5「不伪造终态」纪律，见 swarm/rust_runtime/src/swarm.rs 早退
# 聚合注）。旧码把该报告丢进 DEVNULL，却在重放面断言 ⇒ 断言永真（守护力为零）。
# 落**文件**而非 PIPE：本进程先杀实例、之后才读，文件面没有管道缓冲死锁。
fault_out_path = os.path.join(tmp, "fault_report.jsonl")
fault_out_f = open(fault_out_path, "w", encoding="utf-8")
p = subprocess.Popen([exe, "swarm", "--config", cfg_path, "--wal", wal_b],
                     cwd=proj, stdout=fault_out_f,
                     stderr=subprocess.DEVNULL)
time.sleep(1.0)  # 6000 轮约 3-4s，1s 时杀留足窗口
killed = []
for _ in range(2):
    q = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-CimInstance Win32_Process -Filter \"ParentProcessId={p.pid}\" "
         f"| Where-Object {{ $_.CommandLine -like '*--serve*' }}).ProcessId"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    pids = [x.strip() for x in q.stdout.split() if x.strip().isdigit()]
    pids = [x for x in pids if x not in killed]
    if pids and p.poll() is None:
        subprocess.run(["taskkill", "/PID", pids[0], "/F"],
                       capture_output=True, timeout=15)
        killed.append(pids[0])
    time.sleep(0.2)
check(f"强杀了 {len(killed)} 个实例子进程", len(killed) >= 1, str(killed))
_, _se = p.communicate(timeout=180)
fault_out_f.close()
fault_out = open(fault_out_path, encoding="utf-8", errors="replace").read()
check("蜂群完成（退出码 0，未被故障击穿）", p.returncode == 0, str(p.returncode))

# ============ ③ 透明性：容错后终态/验签与基线一致 ============
print("=== ③ 透明性比对 ===")
rr_b = run_swarm(proj, CFG, wal_path=wal_b)  # WAL 已完成 → 幂等聚合拿报告
check("重入幂等聚合", rr_b["ok"])
v_b = verify_wal_signatures(wal_b, SECRET)
check(f"WAL 全验签通过（{v_b['total']} 条）", v_b["all_valid"], f"bad={v_b['bad']}")
# N263：健康面断言在**在线窗口的含值臂**（② 落盘的故障跑报告，末行 JSON 口径同
# `run_swarm` 的报告解析）——不是 WAL 重放面 `rr_b["report"]["health"]`：那个面
# 设计内恒为空对象（逐轮终态质量未持久化进 WAL，参与性重建会伪造 success_rate，
# G5「不伪造终态」纪律；见 swarm/rust_runtime/src/swarm.rs 早退聚合注与 N109 守卫注），
# 在它上面断言 `all([])` 恒真（旧码形态，断言永真、守护力为零；同族 N160 已登记）。
try:
    rep_fault = json.loads(fault_out.strip().splitlines()[-1])
except (json.JSONDecodeError, IndexError):
    rep_fault = None
check("故障跑在线报告可解析（末行 JSON —— health 面的载体）",
      isinstance(rep_fault, dict) and isinstance(rep_fault.get("health"), dict),
      fault_out.strip()[-200:])
health = (rep_fault or {}).get("health")
check("健康评分满分（重试成功即透明：在线窗口面非空且逐项满分）",
      health_full_marks(health),
      str({k: round(v["score"], 4) for k, v in (health or {}).items()}))
# N263 定点变异自证：同一判据吃「被改成不满足的值面」必须判红——否则断言仍是
# 平凡真（空面）或恒假（掉分面与满分面不可区分）。三条腿合起来钉住判别力。
mut_empty = health_full_marks({})
mut_none = health_full_marks(None)
mut_bad = health_full_marks({k: {"score": 0.5} for k in health}
                            or {"实例0": {"score": 0.5}})
mut_ok = health_full_marks({"实例0": {"score": 1.0}})
check("N263 变异自证：空 health 面判红（旧码 all([]) 恒真之处）",
      mut_empty is False and mut_none is False,
      f"空面={mut_empty} None={mut_none}")
check("N263 变异自证：掉分面判红 / 满分面对照判绿（判据非恒真非恒假）",
      mut_bad is False and mut_ok is True,
      f"掉分面={mut_bad} 满分面={mut_ok}")
if rr_a["ok"] and rr_b["ok"]:
    fa = rr_a["report"]["final_states"]
    fb = rr_b["report"]["final_states"]
    check("六实例终态与基线一致（trust 逐项相等）",
          all(abs(fa[k]["trust"] - fb[k]["trust"]) < 1e-9 for k in fa),
          str({k: fb[k]["trust"] for k in fb}))
    check("gossip 水位一致（对账通过）",
          rr_b["report"]["gossip_consistent"] is True)

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
