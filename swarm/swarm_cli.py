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
import tempfile
import traceback
from typing import Dict, List

from .rust_codegen import generate_rust_project
from .rust_swarm import make_swarm_config, run_swarm, verify_wal_signatures


# 生效条件：无条件把 payload 以 ensure_ascii=False 序列化为单行 JSON 打印到 stdout，随后 sys.exit(code)；
def _emit(payload: Dict, code: int) -> None:
    """stdout 单行 JSON 契约（harness 解析面）；stderr 留给人类细节。"""
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(code)


# 生效条件：先把 detail 原样写入 stderr，再以 {"ok": False, "stage": stage, "error": detail[:2000]} 与 code（默认 1）调用 _emit 退出；
def _fail(stage: str, detail: str, code: int = 1) -> None:
    print(detail, file=sys.stderr)
    _emit({"ok": False, "stage": stage, "error": detail[:2000]}, code)


# 生效条件：spec 以 "@" 开头时取 spec[1:] 为路径、非绝对路径则拼接 base_dir 并读取该文件内容返回，spec 不以 "@" 开头时原样返回 spec；
def _load_source(spec: str, base_dir: str) -> str:
    """source 字段：内嵌术数源码，或 "@file" 引用（相对 config 所在目录）。"""
    if spec.startswith("@"):
        path = spec[1:]
        if not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        with open(path, encoding="utf-8") as f:
            return f.read()
    return spec


# 生效条件：把 obj 以 ensure_ascii=False、indent=1 序列化为 UTF-8 JSON 写入 path——同目录 mkstemp 建临时文件 → json.dump → flush + fsync → os.replace 原子换入；任一步失败（含序列化中途抛错）清理临时文件后原样抛出，path 处旧内容逐字节不动（无半写/截断窗口）；落盘字节恒等于 json.dumps(obj, ensure_ascii=False, indent=1) 的 UTF-8 编码（newline 不翻译，跨平台逐位一致）；
def _atomic_write_json(path: str, obj) -> None:
    """报告落盘原子单点（N248）：tmp + flush + fsync + os.replace。

    与 Rust 侧 WAL 重写同口径（swarm.rs:650 rewrite_wal_atomic：写
    <wal>.tmp → flush → fsync → rename 覆盖）——两侧对称，中途失败沿用
    旧全量、绝不出现截断/半写中间态（旧实现 open(path, "w") 先截断再
    dump：dump 中途失败即永久毁掉同路径旧报告）。
    失败清理：异常路径删临时文件（不留半成品），异常原样上抛（cmd_run
    的兜底段照旧落单行 JSON 失败契约）。
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".swarm_report_", suffix=".tmp",
                               dir=directory)
    try:
        # newline=""：不翻译行尾——落盘字节 == json.dumps 规范文本（LF）。
        # 报告是一次性终态文件（不追加、不读回平台行尾），LF 口径消解
        # Windows 文本模式的 \n→\r\n 平台差异，跨平台逐位一致。
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cmd_run(args: argparse.Namespace) -> None:
    # 异常面兜底（v5 留档 N25）：任一异常须落成单行 JSON + rc=1（文件头
    # 「stdout 恒为单行 JSON」契约），traceback 全文走 stderr（诚实失败不吞现场）。
    # _emit/_fail 内 sys.exit 抛 SystemExit（BaseException），不被 except Exception
    # 捕获——成功/结构化失败路径不受兜底影响。
    try:
        with open(args.config, encoding="utf-8") as f:
            cfg_in = json.load(f)
    except (OSError, ValueError):  # 打不开 / 非法 JSON / 非法 UTF-8
        _fail("config", traceback.format_exc())
    if "source" not in cfg_in or "instances" not in cfg_in:
        _fail("config", "config 须含 source 与 instances 字段")
    base_dir = os.path.dirname(os.path.abspath(args.config))
    try:
        source = _load_source(cfg_in["source"], base_dir)
    except OSError:  # @file 源缺失/不可读
        _fail("config", traceback.format_exc())
    project = args.project or os.path.join(base_dir, "swarm_proj")

    try:
        gen = generate_rust_project(source, project, strict=args.strict)
        if not gen.get("ok"):
            _emit({"ok": False, "stage": "compile",
                   "result": gen.get("result")}, 1)

        cfg = make_swarm_config(cfg_in["instances"], cfg_in.get("routes"),
                                rounds=cfg_in.get("rounds", 1),
                                shared_secret=cfg_in.get("shared_secret", ""),
                                topology=cfg_in.get("topology", ""),
                                condition_space=cfg_in.get("condition_space"))
        rr = run_swarm(project, cfg, wal_path=args.wal, timeout=args.timeout)
        if not rr.get("ok"):
            _emit({"ok": False, "stage": rr.get("stage", "swarm"),
                   "stderr": rr.get("stderr", rr.get("stdout", ""))[-2000:]}, 1)

        report = rr["report"]
        out_path = None
        if args.out:
            out_path = args.out if os.path.isabs(args.out) else \
                os.path.join(base_dir, args.out)
            # N248：报告落盘走原子单点（旧实现先截断再 dump——中途失败即
            # 毁掉同路径旧报告且留截断产物；Rust 侧 WAL 早已原子化，两侧
            # 口径原先不对称）
            _atomic_write_json(out_path, report)
        # 摘要 = harness 关心字段的轻投影（全量在 report 文件 / rr["report"]）
        # report_path 与实际落盘同口径（base_dir 拼接结果）——按 CWD 解析会因
        # CWD≠config 目录产生悬空指针（v5 留档缺陷）
        health = report.get("health", {})
        _emit({"ok": True, "stage": "run",
               "report_path": os.path.abspath(out_path) if out_path else None,
               "wal": rr["wal"], "project": os.path.abspath(project),
               "rounds": report.get("rounds"),
               "instances": report.get("instances"),
               "events": report.get("events"), "acks": report.get("acks"),
               "gossip_consistent": report.get("gossip_consistent"),
               "global_seq": report.get("global_seq"),
               "trust": report.get("trust"),
               "health_min_score": min((h["score"] for h in health.values()),
                                       default=None),
               "health": health}, 0)
    except Exception:  # 编译/构建穿透（build_rust_exe 异常在 run_swarm try 外）/
        # 蜂群调用 / 报告落盘等任一未预期异常 → 兜底契约
        _fail("run", traceback.format_exc())


# 生效条件：args.secret 为空串时 _fail("verify", ..., 2) 显式拒绝（N143：空串密钥 fail-open 缺口——原样透传则伪造行自签 + verify --secret "" 全绿 rc=0；空串在透传给 verify_wal_signatures 之前即拒，库面同口径抛 ValueError）；args.wal 路径不存在时 _fail("verify", ..., 2) 退出，否则用 verify_wal_signatures(args.wal, args.secret) 的结果：all_valid 为真时输出 ok=True 且 exit 0，为假时 ok=False 且 exit 1；验签过程抛异常（WAL 是目录/非法 UTF-8 读行崩溃等）时 _fail("verify", traceback 全文) exit 1——stdout 恒单行 JSON 契约不因异常面破洞；
def cmd_verify(args: argparse.Namespace) -> None:
    # N143（2026-09-26）：空串密钥显式拒绝（rc=2 用法错口径，与 WAL 不存在
    # 同码）——空串密钥下 HMAC 对持空串者零判别力，宁拒不绿。
    if not args.secret:
        _fail("verify", "验签密钥不得为空（--secret 空串拒绝——fail-closed，N143）", 2)
    if not os.path.exists(args.wal):
        _fail("verify", f"WAL 不存在: {args.wal}", 2)
    try:
        v = verify_wal_signatures(args.wal, args.secret)
    except Exception:
        _fail("verify", traceback.format_exc())
    _emit({"ok": bool(v["all_valid"]), "stage": "verify", **v}, 0 if v["all_valid"] else 1)


# 生效条件：argparse 用法错（required 缺失/取值类型非法/未知子命令）经 _UsageArgumentParser.error() 抛出本异常，消息含 usage 全文与 "prog: error: 原因"；
class _UsageError(Exception):
    """argparse 用法错的结构化出口（N249）——替代默认 print_usage + sys.exit(2)。"""


# 生效条件：作为顶层解析器类（子解析器经 parser_class 缺省继承同型）时，error() 一律抛 _UsageError 而非 argparse 默认的「stderr 打印 + sys.exit(2)」；不覆盖 exit()——-h/--help 的 exit(0) 路径原样放行；
class _UsageArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        # N249：缺 --config / 缺子命令 / --timeout 非整数 / 未知子命令等用法错，
        # 原由 argparse error() 直接 sys.exit(2)——stdout 恒 0 字节，破坏文件头
        # 第 5 行「stdout 恒为单行 JSON（机器面）」契约（同命令 WAL 面早已
        # 结构化）。改抛：交还 main 走 _fail("usage", 消息, 2)——stderr 留现场、
        # stdout 单行 JSON、rc=2 用法错口径。
        raise _UsageError("%s%s: error: %s"
                          % (self.format_usage(), self.prog, message))


# 生效条件：解析 argv（None 时取 sys.argv）并在 stdout/stderr 支持 reconfigure 时改为 UTF-8，子命令由 required=True 保证存在；用法错经 _UsageArgumentParser.error() 抛 _UsageError，由本函数捕获后走 _fail("usage", 消息, 2)（stdout 单行 JSON，N249），-h/--help 的 exit 0 路径未覆盖、原样放行；解析成功调用 args.fn —— run 走 cmd_run、verify 走 cmd_verify；
def main(argv: List[str] = None) -> None:
    # Windows GBK 教训（仓 25ff66f 先例）：stdout 强制 UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    p = _UsageArgumentParser(
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

    try:
        args = p.parse_args(argv)
    except _UsageError as e:  # N249：用法错 → 结构化 usage 出口（rc=2）
        _fail("usage", str(e), 2)
    args.fn(args)


if __name__ == "__main__":
    main()