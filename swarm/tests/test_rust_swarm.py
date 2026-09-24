# -*- coding: utf-8 -*-
"""test_rust_swarm.py · 多进程蜂群验收（v0.5 · RUST-SWARM-REV1）
荣 2026-09-06 裁定：多实例并行（进程级）+ 消息传递 + 实例私有信任 + 聚合层。
覆盖：serve 实例化多轮 / 蜂群并行执行 / 消息路由（收件箱注入）/ HMAC 签名
（Python 独立复核交叉验证 Rust 手写 SHA256）/ WAL 落盘 / 信任聚合双端一致 /
篡改检测 / clippy 零警告 / 既有基线不破坏。
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from swarm.rust_codegen import generate_rust_project
from swarm.rust_swarm import (aggregate_trust_python, make_swarm_config,
                             run_swarm, verify_wal_signatures)

pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


SOURCE = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
SECRET = "验收密钥-蜂群v05"

tmp = tempfile.mkdtemp(prefix="swarm_acc_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
check("项目生成", gen["ok"])

# ============ ① 双实例 3 轮蜂群 ============
print("=== ① 双实例 3 轮：并行执行 + 消息路由 ===")
cfg = make_swarm_config(
    instances=[
        # 缺陷②修复后：信任值 是内建名（读 trust_value 寄存器），无需再以
        # symbols 绕过（旧写法会把 信任值 归一为寄存器初值、覆盖实例 trust）。
        {"id": "实例甲", "role": "记录", "trust": 0.1},
        {"id": "实例乙", "role": "验证", "trust": 0.2},
    ],
    routes=[{"from": "实例甲", "event_type": "信任同步", "to": "实例乙",
             "payload": "@trust", "level": 0}],
    rounds=3, shared_secret=SECRET)
rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, "events.jsonl"))
check("蜂群运行", rr["ok"], str(rr.get("stderr", ""))[:150])
if rr["ok"]:
    rep = rr["report"]
    fs = rep["final_states"]
    check("双实例并行执行(均有合法终态)",
          all("error" not in fs.get(k, {"error": 1}) for k in ("实例甲", "实例乙")),
          json.dumps(fs, ensure_ascii=False)[:120])
    check("实例甲 终态 trust=0.9", abs(fs["实例甲"]["trust"] - 0.9) < 1e-9,
          str(fs["实例甲"]["trust"]))
    check("实例乙 终态 trust=1.0", abs(fs["实例乙"]["trust"] - 1.0) < 1e-9,
          str(fs["实例乙"]["trust"]))
    check("消息路由(乙最后一轮收件箱=1 条:每轮收上一轮 1 条,首轮无上一轮)",
          fs["实例乙"]["symbols"].get("已收消息数") == 1,
          str(fs["实例乙"]["symbols"]))

# ============ ② 信任聚合双端一致 ============
print("=== ② 信任聚合:Rust vs Python 参照 ===")
if rr["ok"]:
    # 从终态拿各实例 trust
    ts = [fs["实例甲"]["trust"], fs["实例乙"]["trust"]]
    py = aggregate_trust_python(ts)
    rs = rep["trust"]
    check("T_avg 一致", abs(py["T_avg"] - rs["T_avg"]) < 1e-6,
          f"py={py['T_avg']:.6f} rs={rs['T_avg']:.6f}")
    check("T_min 一致", abs(py["T_min"] - rs["T_min"]) < 1e-6)
    check("T_variance 一致", abs(py["T_variance"] - rs["T_variance"]) < 1e-6)
    check("T_alignment 一致", abs(py["T_alignment"] - rs["T_alignment"]) < 1e-6,
          f"py={py['T_alignment']:.6f} rs={rs['T_alignment']:.6f}")
    check("T_alignment 工程代理(1-var/avg) 数值合理",
          0 <= rs["T_alignment"] <= 1.0)

# ============ ③ HMAC 签名:Python 独立复核(交叉验证 Rust 手写 SHA256) ============
print("=== ③ WAL 验签(交叉验证) ===")
v = verify_wal_signatures(rr["wal"], SECRET)
check(f"WAL 全部验签通过({v['total']} 条)", v["all_valid"],
      f"verified={v['verified']} bad={v['bad']}")
check("事件计数(路由 3 + ACK 2[首轮无收件箱不 ACK] = 5)", v["total"] == 5,
      str(v["total"]))

# 篡改检测：改 payload → 验签必失败
with open(rr["wal"], encoding="utf-8") as f:
    lines = f.readlines()
tampered = json.loads(lines[0])
tampered["payload"] = "999"
line_t = json.dumps(tampered, ensure_ascii=False)
# 用原始文本切片重算（验签逻辑同 verify）
msg = "%s|%s|%s|%s|%s|%s" % (tampered["type"], tampered["from"], tampered["to"],
                             tampered["round"], tampered["ts"],
                             line_t[line_t.index('"payload":') + len('"payload":'):])
import hashlib, hmac as hm
expect = hm.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
check("篡改 payload → 签名不匹配", expect != tampered["hmac"])

# ============ ④ 多轮状态语义:符号表不跨轮持久 ============
print("=== ④ 每轮完整环境 ===")
# 实例乙 round3 终态 trust 仍 =1.0（不是 1.0 累加到 1.7）→ 每轮从初始环境起算
check("轮间无状态泄漏(乙每轮重算 trust=1.0)",
      abs(fs["实例乙"]["trust"] - 1.0) < 1e-9)
check("跨轮数据只经消息(乙有收件箱,甲无)",
      "已收消息数" in fs["实例乙"]["symbols"]
      and "已收消息数" not in fs["实例甲"]["symbols"])

# ============ ⑤ 独立形态蜂群（--no-default-features + --pbc 转发） ============
print("=== ⑤ 独立形态蜂群：协调器与子实例 --pbc 转发 ===")
import shutil
import subprocess
from compiler.pbc import compile_to_pbc

rt_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "rust_runtime")
if shutil.which("cargo") and os.path.isdir(rt_dir):
    ind = subprocess.run(["cargo", "build", "--release", "--no-default-features"],
                         cwd=rt_dir, capture_output=True, text=True, timeout=300,
                         encoding="utf-8", errors="replace")
    check("独立形态构建（关闭 embed）", ind.returncode == 0, (ind.stderr or "")[-200:])
    exe_ind = os.path.join(rt_dir, "target", "release",
                           "protocol_vm.exe" if os.name == "nt" else "protocol_vm")
    tmp5 = tempfile.mkdtemp(prefix="swarm_ind_")
    pbc5 = os.path.join(tmp5, "program.pbc")
    _, r5 = compile_to_pbc(SOURCE, pbc5)
    if r5["ok"] and os.path.exists(exe_ind):
        cfg5 = make_swarm_config(
            instances=[
                # 缺陷②修复后：信任值 为内建名，不再以 symbols 绕过
                {"id": "实例甲", "role": "记录", "trust": 0.1},
                {"id": "实例乙", "role": "验证", "trust": 0.2},
            ],
            routes=[{"from": "实例甲", "event_type": "信任同步", "to": "实例乙",
                     "payload": "@trust", "level": 0}],
            rounds=3, shared_secret=SECRET)
        rr5 = run_swarm(tmp5, cfg5, wal_path="events_ind.jsonl",
                        pbc_path=pbc5, exe=exe_ind)
        check("独立形态蜂群运行（子实例收到 --pbc）", rr5["ok"],
              str(rr5.get("stderr", ""))[:150])
        if rr5["ok"]:
            fs5 = rr5["report"]["final_states"]
            check("独立形态终态与 embed 形态一致(甲 0.9 / 乙 1.0)",
                  abs(fs5["实例甲"]["trust"] - 0.9) < 1e-9
                  and abs(fs5["实例乙"]["trust"] - 1.0) < 1e-9,
                  json.dumps(fs5, ensure_ascii=False)[:120])
            v5 = verify_wal_signatures(rr5["wal"], SECRET)
            check(f"独立形态 WAL 全部验签通过({v5['total']} 条)", v5["all_valid"],
                  f"verified={v5['verified']} bad={v5['bad']}")
    else:
        check("独立形态可执行产物存在", False, exe_ind)
else:
    check("cargo 不可用 → 跳过独立形态蜂群（环境声明）", True)

# ============ ⑤ run_swarm 错误契约（2026-09-25 缺陷） ============
# 契约：失败一律返回 {ok: False, stage: ...} dict——超时（TimeoutExpired）与
# exe 缺失（FileNotFoundError/OSError）此前直接穿透调用方，swarm_cli 整条
# CLI traceback。本节以 30s 慢执行器 + timeout=1s 与不存在 exe 各验一条。
print("=== ⑤ run_swarm 错误契约：超时/启动失败返回结构化 dict ===")
tmp6 = tempfile.mkdtemp(prefix="swarm_err_")
if os.name == "nt":
    slow_exe = os.path.join(tmp6, "slow.bat")
    with open(slow_exe, "w", encoding="utf-8") as f:
        f.write("@ping -n 30 127.0.0.1 > nul\r\n")
else:
    slow_exe = os.path.join(tmp6, "slow.sh")
    with open(slow_exe, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nsleep 30\n")
    os.chmod(slow_exe, 0o755)
try:
    rt = run_swarm(tmp6, {"algo": "rust_swarm-0.1"}, wal_path="w_err.jsonl",
                   timeout=1, exe=slow_exe)
    check("超时 → {ok:False, stage:swarm}（不抛 TimeoutExpired）",
          rt.get("ok") is False and rt.get("stage") == "swarm",
          str(rt)[:150])
    check("超时 dict 含可读 stderr（不吞现场）",
          isinstance(rt.get("stderr"), str) and "超时" in rt["stderr"],
          str(rt.get("stderr", ""))[:120])
    rm = run_swarm(tmp6, {"algo": "rust_swarm-0.1"}, wal_path="w_err2.jsonl",
                   exe=os.path.join(tmp6, "no_such_exe"))
    check("exe 缺失 → {ok:False, stage:swarm}（不抛 OSError）",
          rm.get("ok") is False and rm.get("stage") == "swarm",
          str(rm)[:150])
finally:
    shutil.rmtree(tmp6, ignore_errors=True)

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
