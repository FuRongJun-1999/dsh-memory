# -*- coding: utf-8 -*-
"""N249 守卫：swarm_cli 用法错不破「stdout 恒为单行 JSON（机器面）」契约。

缺陷（修前）：缺 --config / 缺子命令 / --timeout 非整数 / 未知子命令由 argparse
error() 直接 print_usage(stderr) + sys.exit(2) → stdout 恒 0 字节（修前实测四形
全 rc=2、stdout_bytes=0），harness 机器面解析即崩；同命令的异常面早已走 _fail
单行 JSON（test_swarm_cli.py ⑥），用法面独缺。

修复：_UsageArgumentParser.error() 抛 _UsageError（消息含 usage 与原因）；
main 捕获后走 _fail("usage", 消息, 2)。

本守卫：
  ① 四种用法错（缺 --config / 缺子命令 / --timeout 非整数 / 未知子命令）：
     rc==2、stdout 恰一行且 json.loads 可解、ok=false、stage=="usage"、
     error 含 usage 全文与对应原因、stderr 留现场；
  ② -h/--help（含子命令 run --help）：rc==0 且输出非空（exit 0 路径原样放行）。

红机制：撤掉 error() 覆盖（回落 argparse 默认 sys.exit(2)）→ ① 必红。
子进程带 PYTHONUTF8=1；路径全由 tempfile 派生，无本机绝对路径字面量。
"""
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
    """从仓根跑 CLI（子进程带 PYTHONUTF8=1）；返回 CompletedProcess。"""
    return subprocess.run([sys.executable, "-m", "swarm.swarm_cli", *argv],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace",
                          env={**os.environ, "PYTHONUTF8": "1"},
                          cwd=ROOT, timeout=120)


td = tempfile.mkdtemp(prefix="swarm_cli_usage_")
cfg_path = os.path.join(td, "swarm.json")
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump({"source": "问曰：x", "instances": [{"id": "实例甲"}]}, f,
              ensure_ascii=False)

# ============ ① 四种用法错：rc=2 且 stdout 恰一行 JSON ============
print("=== ① 四种用法错 → rc=2 + stdout 恰一行 JSON（stage=usage） ===")
CASES = [
    # (名称, argv, error 中应含的原因片段)
    ("缺 --config", ["run"], "required: --config"),
    ("缺子命令", [], "required: cmd"),
    ("--timeout 非整数", ["run", "--config", cfg_path, "--timeout", "abc"],
     "invalid int value"),
    ("未知子命令", ["bogus"], "invalid choice"),
]
for name, argv, needle in CASES:
    r = cli(*argv)
    body = r.stdout
    lines = [l for l in body.splitlines() if l.strip()]
    payload = None
    if len(lines) == 1:
        try:
            payload = json.loads(lines[0])
        except json.JSONDecodeError:
            payload = None
    check(f"①{name}a rc==2", r.returncode == 2, f"rc={r.returncode}")
    one_line = len(lines) == 1 and lines[0] == body.strip()
    check(f"①{name}b stdout 恰一行且 json.loads 可解",
          payload is not None and one_line, f"stdout={body[:160]!r}")
    check(f"①{name}c ok=false 且 stage=usage",
          isinstance(payload, dict) and payload.get("ok") is False
          and payload.get("stage") == "usage", f"payload={payload}")
    err = (payload or {}).get("error") or ""
    check(f"①{name}d error 含 usage 与原因",
          "usage:" in err and needle in err, f"err={err[:180]!r}")
    check(f"①{name}e stderr 留现场（非空）", r.stderr.strip() != "",
          f"stderr={r.stderr[:120]!r}")

# ============ ② -h/--help：exit 0 路径原样放行 ============
print("=== ② -h/--help：rc=0 且输出非空 ===")
r = cli("--help")
check("②a --help rc==0", r.returncode == 0, f"rc={r.returncode}")
check("②b --help stdout 非空且含 usage",
      r.stdout.strip() != "" and "usage:" in r.stdout,
      f"stdout={r.stdout[:120]!r}")
r2 = cli("run", "--help")
check("②c run --help rc==0（子解析器同放行）", r2.returncode == 0
      and r2.stdout.strip() != "", f"rc={r2.returncode}")

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
