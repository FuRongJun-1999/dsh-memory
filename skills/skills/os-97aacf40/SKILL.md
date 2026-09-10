---
name: os-97aacf40
description: >-
  电源管理 / 系统-电源管理 / suspend 休。用户提到这些词时使用本技能。
  场景：对照：ACPI 电源管理——休眠/唤醒/状态。
  【不适用】Not for 以下场景：op 非 {resume, status, suspend} 时
license: MIT
compatibility: >-
  op ∈ {resume, status, suspend}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["电源管理", "系统-电源管理", "suspend 休"]
    when: "op ∈ {resume, status, suspend}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {resume, status, suspend} 时"]
  calibration: "对照：ACPI 电源管理——休眠/唤醒/状态"
---

# 系统-电源管理（os-97aacf40）

## When to use

任务「电源管理」；对照：ACPI 电源管理——休眠/唤醒/状态。

## 克制条款（不适用条件）

op 非 {resume, status, suspend} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-电源管理」
