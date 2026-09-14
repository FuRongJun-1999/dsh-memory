# -*- coding: utf-8 -*-
"""swarm_cli 端到端测试（v0.6.1 插件化内核）：
① run 全链路（config→编译→蜂群→报告/摘要）
② verify 全验签（Python 独立复核）
③ 幂等重入（已完成≥目标 → 不重启实例直接聚合，事件史一致、health 空对象）
④ 篡改检测（改 payload 一字符 → 验签即爆）
stdout 恒单行 JSON；subprocess 走 `python -m swarm.swarm_cli`（相对导入约束）。"""
import io
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pass_n = fail_n = 0


def check(name, cond, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print(f"[✓] {name}" + (f" — {detail}" if detail else ""))
    else:
        fail_n += 1
        print(f"[✗] {name} — {detail}")


def cli(*argv):
    """跑 CLI：stdout 必须是单行 JSON（机器面契约本身即被测对象）。"""
    r = subprocess.run([sys.executable, "-m", "swarm.swarm_cli", *argv],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env={**os.environ, "PYTHONUTF8": "1"},
                       cwd=ROOT, timeout=300)
    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    try:
        payload = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError:
        payload = {"_raw": r.stdout[-500:]}
    return r.returncode, payload, r.stderr


SOURCE = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""

td = tempfile.mkdtemp(prefix="swarm_cli_")
src_path = os.path.join(td, "algo.txt")
with open(src_path, "w", encoding="utf-8") as f:
    f.write(SOURCE)
cfg_path = os.path.join(td, "swarm.json")
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump({"source": "@algo.txt",  # @file 引用形态（插件主路径）
               "instances": [
                   {"id": "实例甲", "role": "记录", "trust": 0.1},
                   {"id": "实例乙", "role": "验证", "trust": 0.2}],
               "routes": [{"from": "实例甲", "event_type": "信任同步",
                           "to": "实例乙", "payload": "@trust", "level": 0}],
               "rounds": 2, "shared_secret": "测试密钥",
               "topology": "hierarchical"}, f, ensure_ascii=False)
report_path = os.path.join(td, "report.json")

# ============ ① run 全链路 ============
print("=== ① run 全链路（config→编译→蜂群→报告） ===")
code, out, err = cli("run", "--config", cfg_path, "--out", report_path)
check("run 退出码 0 且 ok=true", code == 0 and out.get("ok") is True,
      f"code={code} err={err[-300:]}")
check("stdout 摘要含规模与 trust",
      all(k in out for k in ("rounds", "instances", "events", "trust", "wal")),
      str({k: out.get(k) for k in ("rounds", "instances", "events")}))
check("health 摘要在位且满分（全成功场景）",
      out.get("health_min_score") == 1.0 and len(out.get("health", {})) == 2,
      f"min={out.get('health_min_score')}")
check("报告文件落盘且含 health/trust/final_states",
      os.path.exists(report_path) and
      all(k in json.load(open(report_path, encoding="utf-8"))
          for k in ("health", "trust", "final_states")))
first_wal = out["wal"]

# ============ ② verify 全验签 ============
print("=== ② verify（Python 独立复核） ===")
code, v, _ = cli("verify", "--wal", first_wal, "--secret", "测试密钥")
check("verify 退出码 0 且 all_valid", code == 0 and v.get("all_valid") is True,
      f"code={code} {v}")

# ============ ③ 幂等重入 ============
print("=== ③ 幂等重入（同 project+wal） ===")
code, out2, _ = cli("run", "--config", cfg_path)
check("重入退出码 0（已完成≥目标 → 幂等聚合）",
      code == 0 and out2.get("ok") is True, f"code={code}")
check("重入事件史与首轮一致（零重复事件）",
      out2.get("events") == out.get("events") and out2.get("acks") == out.get("acks"),
      f"events {out.get('events')}→{out2.get('events')}")
check("重入 health 为空对象（在线窗口口径，B1 语义）", out2.get("health") == {})

# ============ ④ 篡改检测 ============
print("=== ④ 篡改检测 ===")
tampered = os.path.join(td, "tampered.jsonl")
with open(first_wal, encoding="utf-8") as f:
    lines = f.readlines()
rec = json.loads(lines[0])
rec["payload"] = ("0" if rec["payload"] != "0" else "1")  # 改 payload 一字符
lines[0] = json.dumps(rec, ensure_ascii=False) + "\n"
with open(tampered, "w", encoding="utf-8") as f:
    f.writelines(lines)
code, v2, _ = cli("verify", "--wal", tampered, "--secret", "测试密钥")
check("篡改行验签即爆（all_valid=false，退出码 1）",
      code == 1 and v2.get("all_valid") is False and v2.get("bad", 0) >= 1,
      f"code={code} bad={v2.get('bad')}")

# ============ 坏 config 诚实报错 ============
print("=== ⑤ 坏 config 诚实报错 ===")
bad_cfg = os.path.join(td, "bad.json")
with open(bad_cfg, "w", encoding="utf-8") as f:
    json.dump({"instances": []}, f, ensure_ascii=False)
code, out3, _ = cli("run", "--config", bad_cfg)
check("缺 source 字段 → ok=false + stage=config", code == 1 and
      out3.get("ok") is False and out3.get("stage") == "config", f"code={code}")

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
