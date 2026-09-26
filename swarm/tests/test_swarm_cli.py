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

# ============ ⑥ 异常面单行 JSON 契约（v5 留档 N25） ============
# 缺陷：cmd_run/cmd_verify 多处异常（config 打不开/非法 JSON/@file 源缺失/
# 构建穿透/验签内部）裸奔 traceback，stdout 0 字节——破坏文件头
# 「stdout 恒为单行 JSON」harness 解析契约（swarm_cli.py:5）。
# 修复面：异常 → _fail（stderr 留 traceback 现场，stdout 单行 JSON，rc=1）。
print("=== ⑥ 异常面单行 JSON 契约（traceback 进 stderr，不进 stdout） ===")

# ⑥a config 文件不存在
code, out6a, err6a = cli("run", "--config", os.path.join(td, "nope.json"))
check("⑥a config 不存在 → ok=false stage=config + stderr 有现场",
      code == 1 and out6a.get("ok") is False and out6a.get("stage") == "config"
      and "Traceback" in err6a and "FileNotFoundError" in err6a,
      f"code={code} stage={out6a.get('stage')}")

# ⑥b config 非法 JSON（截断）
bad_json = os.path.join(td, "bad_json.json")
with open(bad_json, "w", encoding="utf-8") as f:
    f.write('{"source": "问曰：x", "instances": [')
code, out6b, err6b = cli("run", "--config", bad_json)
check("⑥b config 非法 JSON → ok=false stage=config",
      code == 1 and out6b.get("ok") is False and
      out6b.get("stage") == "config" and "JSONDecodeError" in err6b,
      f"code={code} stage={out6b.get('stage')}")

# ⑥c source @file 引用缺失（config 本身合法）
cfg_missing_src = os.path.join(td, "missing_src.json")
with open(cfg_missing_src, "w", encoding="utf-8") as f:
    json.dump({"source": "@不存在源.txt", "instances": [{"id": "实例甲"}]},
              f, ensure_ascii=False)
code, out6c, err6c = cli("run", "--config", cfg_missing_src)
check("⑥c @file 源缺失 → ok=false stage=config（不裸奔）",
      code == 1 and out6c.get("ok") is False and
      out6c.get("stage") == "config" and "FileNotFoundError" in err6c,
      f"code={code} stage={out6c.get('stage')}")

# ⑥d --project 指向已存在文件（项目目录生成失败 → 段内兜底）
proj_as_file = os.path.join(td, "proj_is_file.txt")
with open(proj_as_file, "w", encoding="utf-8") as f:
    f.write("not a dir")
ok_cfg = os.path.join(td, "ok_min.json")
with open(ok_cfg, "w", encoding="utf-8") as f:
    json.dump({"source": SOURCE, "instances": [{"id": "实例甲", "trust": 0.1}]},
              f, ensure_ascii=False)
code, out6d, err6d = cli("run", "--config", ok_cfg, "--project", proj_as_file)
check("⑥d project 路径不可生成（指向文件）→ ok=false 单行 JSON 兜底",
      code == 1 and out6d.get("ok") is False and out6d.get("stage") == "run"
      and err6d.strip() != "", f"code={code} stage={out6d.get('stage')}")

# ⑥e cargo 不可用（PATH 掏空 + 全新 project 无缓存 exe）→ build_rust_exe
# 异常自 rust_swarm.py:71 穿透 run_swarm 的 try（只包执行段）→ CLI 须兜底
no_cargo_env = {**os.environ, "PYTHONUTF8": "1",
                "PATH": tempfile.gettempdir()}
r6e = subprocess.run([sys.executable, "-m", "swarm.swarm_cli", "run",
                      "--config", ok_cfg,
                      "--project", os.path.join(td, "proj_nocache")],
                     capture_output=True, text=True, encoding="utf-8",
                     errors="replace", env=no_cargo_env,
                     cwd=ROOT, timeout=300)
lines6e = [l for l in r6e.stdout.strip().splitlines() if l.strip()]
try:
    out6e = json.loads(lines6e[-1]) if lines6e else {}
except json.JSONDecodeError:
    out6e = {"_raw": r6e.stdout[-300:]}
check("⑥e cargo 不可用（构建穿透）→ ok=false 单行 JSON 兜底",
      r6e.returncode == 1 and out6e.get("ok") is False
      and out6e.get("stage") == "run" and r6e.stderr.strip() != "",
      f"code={r6e.returncode} stage={out6e.get('stage')}")

# ⑥f verify --wal 指向目录
code, out6f, err6f = cli("verify", "--wal", td, "--secret", "x")
check("⑥f verify WAL 是目录 → ok=false stage=verify + stderr 现场",
      code == 1 and out6f.get("ok") is False and
      out6f.get("stage") == "verify" and "Traceback" in err6f,
      f"code={code} stage={out6f.get('stage')}")

# ⑥g verify --wal 含非法 UTF-8 字节（撕裂写/污染）→ 验签器须自身容错：
# 计 bad + all_valid=False（不崩、不靠 CLI 兜底吞异常——「不得自己先崩」契约）
bad_utf8 = os.path.join(td, "bad_utf8.jsonl")
with open(bad_utf8, "wb") as f:
    f.write(b'{"seq":1,"type":"\xff\xfe","hmac":"x"}\n')
code, out6g, err6g = cli("verify", "--wal", bad_utf8, "--secret", "x")
check("⑥g WAL 非法 UTF-8 → 验签器自身容错：all_valid=False bad>=1 单行 JSON",
      code == 1 and out6g.get("ok") is False and
      out6g.get("stage") == "verify" and
      out6g.get("all_valid") is False and out6g.get("bad", 0) >= 1,
      f"code={code} bad={out6g.get('bad')}")

# ============ ⑦ --out 指针口径（文件落点 = report_path） ============
# 缺陷：相对 --out 实际按 config 目录（base_dir）落盘，摘要 report_path 却按
# CWD 解析（os.path.abspath(args.out)）——CWD≠config 目录时悬空指针。
# 本节 CWD=ROOT、config 在 td（tempdir），口径分裂即复现。
print("=== ⑦ --out 指针口径（文件落点 = report_path） ===")
code, out7, _ = cli("run", "--config", cfg_path, "--out", "rep_ptr.json",
                    "--wal", "w7a.jsonl")
rep_ptr = out7.get("report_path", "")
check("⑦a 相对 --out：report_path 指向真实落盘文件（config 目录，非 CWD）",
      code == 0 and bool(rep_ptr) and os.path.exists(rep_ptr)
      and os.path.normcase(os.path.abspath(rep_ptr)) ==
      os.path.normcase(os.path.join(td, "rep_ptr.json")),
      f"report_path={rep_ptr}")
check("⑦a 落盘文件确为蜂群报告（含 health/final_states）",
      os.path.exists(rep_ptr) and
      all(k in json.load(open(rep_ptr, encoding="utf-8"))
          for k in ("health", "final_states")),
      f"path={rep_ptr}")

abs_out = os.path.join(td, "rep_abs.json")
code, out7b, _ = cli("run", "--config", cfg_path, "--out", abs_out,
                     "--wal", "w7b.jsonl")
rep_abs = out7b.get("report_path", "")
check("⑦b 绝对 --out：口径不破（指针=该绝对路径且文件在）",
      code == 0 and os.path.exists(rep_abs)
      and os.path.normcase(os.path.abspath(rep_abs)) ==
      os.path.normcase(abs_out),
      f"report_path={rep_abs}")

# ============ ⑧ 空串密钥显式拒绝（N143 · 2026-09-26 修复守卫） ============
# 缺陷：cmd_verify 把 args.secret 原样透传 verify_wal_signatures——空串照验
# 全绿（空串自签伪造行 + verify --secret "" → rc=0 ok=true，fail-open；
# config 忘写 shared_secret 时整条审计链即以空串签名）。
# 修复：CLI 面空串显式拒绝 rc=2（用法错口径，与 WAL 不存在同码）；库面
# verify_wal_signatures 入口同口径抛 ValueError（test_rust_swarm.py ③c）。
# run 侧缺省密钥语义（cfg_in.get("shared_secret","")）属全量语义专项维持
# deferred，不在本修复面。
print("=== ⑧ 空串密钥显式拒绝（N143） ===")
code, out8, err8 = cli("verify", "--wal", first_wal, "--secret", "")
check("⑧a verify --secret 空串 → rc=2 + ok=false stage=verify（不透传验签）",
      code == 2 and out8.get("ok") is False and out8.get("stage") == "verify",
      f"code={code} {out8}")
check("⑧b 拒绝信息明示密钥面（结构化单行 JSON，非 traceback 裸奔）",
      "密钥" in (out8.get("error") or "") and err8.strip() != "",
      str(out8.get("error"))[:120])

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
