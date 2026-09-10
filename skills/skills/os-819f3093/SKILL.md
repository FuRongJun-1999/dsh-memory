---
name: os-819f3093
description: >-
  写时复制快照 / 文件-写时复制快照 / OS 文 / snapshot 冻。用户提到这些词时使用本技能。
  场景：对照：OS 文件系统——写时复制快照（快照冻结，写共享块先复制）。
  【不适用】Not for 以下场景：op 非 {read, snapshot, write} 时
license: MIT
compatibility: >-
  op ∈ {snapshot, write}；snapshots 为快照表（可空）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["写时复制快照", "文件-写时复制快照", "OS 文", "snapshot 冻"]
    when: "op ∈ {snapshot, write}；snapshots 为快照表（可空）"
    sub: ["① snapshot 冻结块引用 ② write 写块时复制原值"]
    execute: "按 op 分派快照/写时复制"
    not_applicable: ["op 非 {read, snapshot, write} 时"]
  calibration: "对照：OS 文件系统——写时复制快照（快照冻结，写共享块先复制）"
---

# 文件-写时复制快照（os-819f3093）

## When to use

任务「写时复制快照」；对照：OS 文件系统——写时复制快照（快照冻结，写共享块先复制）。

## 克制条款（不适用条件）

op 非 {read, snapshot, write} 时

## How to execute

按 op 分派快照/写时复制

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-写时复制快照」
