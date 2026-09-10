---
name: os-e0ad3364
description: >-
  文件快照 / 文件-文件系统快照 / 文件系统快照——写时复制 / 文件系统快照 / 写时复制。用户提到这些词时使用本技能。
  场景：对照：文件系统快照——写时复制（修改前复制原块，可回滚）。
  【不适用】Not for 以下场景：op 非 {rollback, snap, write} 时
license: MIT
compatibility: >-
  op ∈ {rollback, snap, write}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件快照", "文件-文件系统快照", "文件系统快照——写时复制", "文件系统快照", "写时复制"]
    when: "op ∈ {rollback, snap, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {rollback, snap, write} 时"]
  calibration: "对照：文件系统快照——写时复制（修改前复制原块，可回滚）"
---

# 文件-文件系统快照（os-e0ad3364）

## When to use

任务「文件快照」；对照：文件系统快照——写时复制（修改前复制原块，可回滚）。

## 克制条款（不适用条件）

op 非 {rollback, snap, write} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-文件系统快照」
