---
name: os-878c18b3
description: >-
  文件系统日志 / 文件-文件系统日志 / log 记。用户提到这些词时使用本技能。
  场景：对照：journaling——日志记录/崩溃重放/待重放。
  【不适用】Not for 以下场景：op 非 {log, pending, replay} 时
license: MIT
compatibility: >-
  op ∈ {log, pending, replay}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件系统日志", "文件-文件系统日志", "log 记"]
    when: "op ∈ {log, pending, replay}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {log, pending, replay} 时"]
  calibration: "对照：journaling——日志记录/崩溃重放/待重放"
---

# 文件-文件系统日志（os-878c18b3）

## When to use

任务「文件系统日志」；对照：journaling——日志记录/崩溃重放/待重放。

## 克制条款（不适用条件）

op 非 {log, pending, replay} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-文件系统日志」
