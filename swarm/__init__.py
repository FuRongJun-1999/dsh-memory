# -*- coding: utf-8 -*-
"""swarm · 蜂群多智能体执行层（灵枢大脑核心内部能力）。

自 protocol-compiler 迁入（v0.6.1，2026-09-13 荣裁定：蜂群并入大脑作为
高并发多智能体执行层）。零第三方依赖——Python 侧 stdlib only，
Rust 侧纯 std（对齐 md_cg D-005）。

模块分组：
  术数编译链（已独立为 compiler/ 包——编译器并入大脑核心能力，v0.6.2；
    本包经 from compiler.compiler/pbc import 驱动编译与字节码面）
  Rust 桥接（.pbc → cargo 项目 → protocol_vm 可执行）
    rust_codegen.py
  蜂群协调（多进程实例 + WAL/ACK/HMAC + 信任聚合 + 健康评分）
    rust_swarm.py swarm_cli.py
  Rust 引擎（protocol_vm crate，swarm 子命令）
    rust_runtime/
  测试与基准
    tests/

用法：
  python -m swarm.swarm_cli run --config swarm.json
  python -m swarm.swarm_cli verify --wal events.jsonl --secret 密钥

诚实边界：shared_secret 会明文写入 project_dir/swarm.json（本机盘）；
跨机部署时项目目录应放临时目录并按本机密钥管理策略处置。
"""
__version__ = "0.6.2"
ALGO = "rust_swarm-0.1"
