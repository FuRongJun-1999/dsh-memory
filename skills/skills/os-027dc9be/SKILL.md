---
name: os-027dc9be
description: >-
  日志轮转 / 系统-日志轮转 / append 追。用户提到这些词时使用本技能。
  场景：对照：logrotate——日志大小超限轮转。
  【不适用】Not for 以下场景：op 非 {append, size} 时
license: MIT
compatibility: >-
  op ∈ {append, size}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["日志轮转", "系统-日志轮转", "append 追"]
    when: "op ∈ {append, size}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {append, size} 时"]
  calibration: "对照：logrotate——日志大小超限轮转"
---

# 系统-日志轮转（os-027dc9be）

## When to use

任务「日志轮转」；对照：logrotate——日志大小超限轮转。

## 克制条款（不适用条件）

op 非 {append, size} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-日志轮转」
