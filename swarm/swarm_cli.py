# -*- coding: utf-8 -*-
"""swarm_cli · 蜂群命令行面（v0.6.1 插件化内核）。

为各类 harness（CodeBuddy/Claude/Codex 等）提供统一的子代理执行引擎入口：
Bash 即可调用，stdout 恒为**单行 JSON**（机器面），过程细节走 stderr（人面）。

用法：
  python -m swarm.swarm_cli run --config swarm.json [--project DIR]
                               [--wal events.jsonl] [--out report.json]
                               [--timeout 120] [--strict]
  python -m swarm.swarm_cli verify --wal events.jsonl --secret 密钥

config schema（swarm.json）：
  {"source": "术数源码（或 \"@file\" 引用源码文件）",
   "instances": [{"id","role","trust","symbols"}], "routes": [...],
   "rounds": 3, "shared_secret": "...", "topology": "hierarchical|mesh|centralized"}

安全模型（三重，全部可审计）：
  ① 实例 = 确定性 VM 子进程：纯 std 指令面（无网络/无文件 I/O/无系统调用），
     术数源码经 C2 编译期校验后才生成项目——不可执行任意代码。
  ② HMAC-SHA256 全事件签名 + WAL 本地留痕；verify 子命令用 Python hashlib
     独立复核 Rust 手写 SHA256（跨实现交叉验证）。
  ③ 断点续跑/幂等聚合：同 project + 同 WAL 重入即续跑，重放经坏尾守卫
     （半行/篡改截断）——中途被杀不产生重复事件。

诚实边界：shared_secret 会明文写入 project_dir/swarm.json（本机盘）；
跨机部署时项目目录应放临时目录并按本机密钥管理策略处置。
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from typing import Dict, List

from .rust_codegen import generate_rust_project
from .rust_swarm import make_swarm_config, run_swarm, verify_wal_signatures


def _emit(payload: Dict, code: int) -> None:
    """stdout 单行 JSON 契约（harness 解析面）；stderr 留给人类细节。"""
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(code)


def _fail(stage: str, detail: str, code: int = 1) -> None:
    print(detail, file=sys.stderr)
    _emit({"ok": False, "stage": stage, "error": detail[:2000]}, code)


def _load_source(spec: str, base_dir: str) -> str:
    """source 字段：内嵌术数源码，或 "@file" 引用（相对 config 所在目录）。"""
    if spec.startswith("@"):
        path = spec[1:]
        if not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        with open(path, encoding="utf-8") as f:
            return f.read()
    return spec


def cmd_run(args: argparse.Namespace) -> None:
    with open(args.config, encoding="utf-8") as f:
        cfg_in = json.load(f)
    if "source" not in cfg_in or "instances" not in cfg_in:
        _fail("config", "config 须含 source 与 instances 字段")
    base_dir = os.path.dirname(os.path.abspath(args.config))
    source = _load_source(cfg_in["source"], base_dir)
    project = args.project or os.path.join(base_dir, "swarm_proj")

    gen = generate_rust_project(source, project, strict=args.strict)
    if not gen.get("ok"):
        _emit({"ok": False, "stage": "compile", "result": gen.get("result")}, 1)

    cfg = make_swarm_config(cfg_in["instances"], cfg_in.get("routes"),
                            rounds=cfg_in.get("rounds", 1),
                            shared_secret=cfg_in.get("shared_secret", ""),
                            topology=cfg_in.get("topology", ""))
    rr = run_swarm(project, cfg, wal_path=args.wal, timeout=args.timeout)
    if not rr.get("ok"):
        _emit({"ok": False, "stage": rr.get("stage", "swarm"),
               "stderr": rr.get("stderr", rr.get("stdout", ""))[-2000:]}, 1)

    report = rr["report"]
    if args.out:
        out_path = args.out if os.path.isabs(args.out) else \
            os.path.join(base_dir, args.out)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    # 摘要 = harness 关心字段的轻投影（全量在 report 文件 / rr["report"]）
    health = report.get("health", {})
    _emit({"ok": True, "stage": "run",
           "report_path": os.path.abspath(args.out) if args.out else None,
           "wal": rr["wal"], "project": os.path.abspath(project),
           "rounds": report.get("rounds"), "instances": report.get("instances"),
           "events": report.get("events"), "acks": report.get("acks"),
           "gossip_consistent": report.get("gossip_consistent"),
           "global_seq": report.get("global_seq"),
           "trust": report.get("trust"),
           "health_min_score": min((h["score"] for h in health.values()),
                                   default=None),
           "health": health}, 0)


def cmd_verify(args: argparse.Namespace) -> None:
    if not os.path.exists(args.wal):
        _fail("verify", f"WAL 不存在: {args.wal}", 2)
    v = verify_wal_signatures(args.wal, args.secret)
    _emit({"ok": bool(v["all_valid"]), "stage": "verify", **v}, 0 if v["all_valid"] else 1)


def main(argv: List[str] = None) -> None:
    # Windows GBK 教训（仓 25ff66f 先例）：stdout 强制 UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(
        prog="swarm_cli", description="蜂群多智能体命令行面（确定性子代理引擎）")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="执行蜂群（同 project+wal 重入 = 断点续跑/幂等聚合）")
    pr.add_argument("--config", required=True, help="swarm.json 配置路径")
    pr.add_argument("--project", default=None, help="Rust 项目目录（默认 config 同目录/swarm_proj）")
    pr.add_argument("--wal", default="events.jsonl", help="WAL 文件名（相对 project 目录）")
    pr.add_argument("--out", default=None, help="报告 JSON 输出路径（默认仅 stdout 摘要）")
    pr.add_argument("--timeout", type=int, default=120)
    pr.add_argument("--strict", action="store_true", help="编译严格模式")
    pr.set_defaults(fn=cmd_run)

    pv = sub.add_parser("verify", help="WAL HMAC 验签（Python 独立复核）")
    pv.add_argument("--wal", required=True)
    pv.add_argument("--secret", required=True)
    pv.set_defaults(fn=cmd_verify)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
