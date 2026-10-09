# -*- coding: utf-8 -*-
"""N248 守卫：swarm_cli 报告落盘原子化（_atomic_write_json 单点）。

缺陷（修前 swarm_cli.py:102-107）：cmd_run 的 --out 落盘先 open(out_path, "w")
截断再 json.dump——中途失败留截断报告，且已毁掉同路径旧报告（修前实测：旧报告
'OLD-REPORT-CONTENT-旧报告' → '{"partial'）；同命令的 WAL 面走 Rust 侧
rewrite_wal_atomic（tmp+flush+fsync+rename，swarm.rs:650），两侧口径不对称。

本守卫三条：
  ① 成功路径：cmd_run（--out）落盘字节 == json.dumps(report, ensure_ascii=False,
     indent=1).encode("utf-8")——序列化口径逐位钉住（中文不转义 / indent=1 /
     LF 无平台翻译）。
     说明：生成段与蜂群段以 stub 换入（generate_rust_project / run_swarm），
     驱动的是 cmd_run 真身的落盘代码路径；真实引擎 E2E 由 test_swarm_cli.py
     覆盖（同一收集面）。
  ② 失败注入：先写旧报告 → patch json.dump 中途抛错 → 直调单点后旧文件逐字节
     不变、目标目录无任何残留文件（原子写无半写窗口）。
  ③ 源码面：cmd_run 不再出现 open(out_path, 'w'、引用 _atomic_write_json；
     单点源码含 mkstemp 与 os.replace。

红机制：单点变异回截断写（open(path,"w") + json.dump）→ ② 必红。
守卫内路径一律 tempfile 派生；不出现本机绝对路径字面量。
"""
import argparse
import inspect
import io
import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from swarm import swarm_cli as sc  # noqa: E402

pass_n = fail_n = 0


def check(name, cond, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print(f"[✓] {name}" + (f" — {detail}" if detail else ""))
    else:
        fail_n += 1
        print(f"[✗] {name} — {detail}")


# 报告样本：覆盖中文（ensure_ascii=False 面）、缩进（indent=1 面）、
# 空容器/None/浮点/嵌套（序列化边界）。
REPORT = {
    "rounds": 2,
    "instances": {"实例甲": {"score": 1.0}, "实例乙": {"score": 0.5}},
    "trust": {"T_avg": 0.75, "实例": "中文不转义"},
    "final_states": {"实例甲": {"信任值": 0.5, "flags": None}},
    "empty_obj": {}, "empty_arr": [], "seq": [1, 2, None],
    "nested": {"a": {"b": [1.5, 2, "中"]}},
}
CANON = json.dumps(REPORT, ensure_ascii=False, indent=1).encode("utf-8")

td = tempfile.mkdtemp(prefix="swarm_cli_atomic_")

# ============ ① 成功路径：cmd_run --out 落盘字节逐位钉住 ============
print("=== ① 成功路径：cmd_run --out 落盘字节 == json.dumps(report, ensure_ascii=False, indent=1) ===")
cfg_path = os.path.join(td, "swarm.json")
# issue #81（fail-closed，提交 303f3b9a）后 shared_secret 为**必填**：
# rust_swarm.make_swarm_config 对缺/空密钥一律抛 ValueError，不再回落源码内公开
# 常量。本件只测「报告落盘原子化」，与密钥无关——故按同批其它 swarm 测试的口径
# 补上显式密钥（config schema 本就含 shared_secret，见 swarm_cli.py:16 docstring），
# 不依赖已废除的缺省默认（补此键前本件红于 make_swarm_config 的 ValueError）。
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump({"source": "问曰：x", "instances": [{"id": "实例甲"}],
               "shared_secret": "report-atomic-测试密钥"}, f,
              ensure_ascii=False)
out_path = os.path.join(td, "report_out.json")
args = argparse.Namespace(config=cfg_path, project=None, wal="events.jsonl",
                          out=out_path, strict=False, timeout=120)


def run_cmd_run(report):
    """stub 生成/蜂群两段，驱动 cmd_run 真身；捕获 SystemExit 与 stdout。"""
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    code = None
    try:
        with mock.patch.object(sc, "generate_rust_project",
                               lambda *a, **k: {"ok": True}), \
             mock.patch.object(sc, "run_swarm",
                               lambda *a, **k: {"ok": True, "report": report,
                                                "wal": os.path.join(td, "events.jsonl")}):
            try:
                sc.cmd_run(args)
            except SystemExit as e:
                code = e.code
    finally:
        sys.stdout = old_stdout
    return code, buf.getvalue()


code, stdout = run_cmd_run(REPORT)
check("①a cmd_run 成功路径 rc=0", code == 0, f"code={code}")
lines = [l for l in stdout.strip().splitlines() if l.strip()]
check("①b 成功路径 stdout 单行 JSON 且 ok=true",
      len(lines) == 1 and json.loads(lines[0]).get("ok") is True,
      f"stdout={stdout[:160]!r}")
check("①c 报告文件已落盘", os.path.exists(out_path), out_path)
got = open(out_path, "rb").read()
check("①d 落盘字节 == json.dumps(report, ensure_ascii=False, indent=1)",
      got == CANON, f"落盘 {len(got)}B vs 规范 {len(CANON)}B; 前 80B={got[:80]!r}")
payload = json.loads(lines[0]) if lines else {}
check("①e report_path 指向落盘文件",
      os.path.normcase(os.path.abspath(payload.get("report_path") or "")) ==
      os.path.normcase(os.path.abspath(out_path)),
      f"report_path={payload.get('report_path')}")

# ============ ② 失败注入：旧报告逐字节不变 + 零残留 ============
print("=== ② 失败注入：patch json.dump 中途抛错 → 旧报告逐字节不变、目录无残留 ===")
inj_dir = os.path.join(td, "inj")
os.makedirs(inj_dir)
target = os.path.join(inj_dir, "old_report.json")
OLD = 'OLD-REPORT-CONTENT-旧报告\n{"旧": 1}'
with open(target, "w", encoding="utf-8") as f:
    f.write(OLD)
before = open(target, "rb").read()


def boom(obj, fp, **kw):
    fp.write('{"partial')  # 模拟写到一半就炸
    raise OSError("模拟落盘中途失败")


raised = False
try:
    with mock.patch.object(json, "dump", new=boom):
        sc._atomic_write_json(target, REPORT)
except OSError:
    raised = True
check("②a 中途失败原样抛错（不吞异常）", raised)
check("②b 旧报告逐字节不变（无截断/半写）",
      open(target, "rb").read() == before,
      f"现内容={open(target, 'rb').read()[:60]!r}")
check("②c 目标目录无任何残留文件",
      sorted(os.listdir(inj_dir)) == ["old_report.json"],
      f"目录={sorted(os.listdir(inj_dir))}")

# ②d 成功写：同路径覆盖旧报告（原子替换语义不只在失败面）
with open(target, "w", encoding="utf-8") as f:
    f.write("NEW-OLD")
sc._atomic_write_json(target, REPORT)
check("②d 成功路径原子换入：旧内容被完整新内容替换",
      open(target, "rb").read() == CANON and
      sorted(os.listdir(inj_dir)) == ["old_report.json"],
      f"目录={sorted(os.listdir(inj_dir))}")

# ============ ③ 源码面 ============
print("=== ③ 源码面：cmd_run 走单点、截断写已移除 ===")
cmd_run_src = inspect.getsource(sc.cmd_run)
check("③a cmd_run 不再出现 open(out_path, 'w'（截断写已移除）",
      "open(out_path" not in cmd_run_src,
      "命中 open(out_path" if "open(out_path" in cmd_run_src else "")
check("③b cmd_run 引用 _atomic_write_json(out_path, ...)",
      "_atomic_write_json(out_path" in cmd_run_src)
check("③c 模块级单点存在且可调用",
      callable(getattr(sc, "_atomic_write_json", None)))
single_src = inspect.getsource(sc._atomic_write_json)
check("③d 单点源码含 mkstemp 与 os.replace（原子换入实现在位）",
      "mkstemp" in single_src and "os.replace(" in single_src)

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
