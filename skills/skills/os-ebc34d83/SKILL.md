---
name: os-ebc34d83
description: >-
  设备驱动 / 系统-设备驱动 / register 注。用户提到这些词时使用本技能。
  场景：对照：Linux 设备驱动——设备 ID 注册/匹配。
  【不适用】Not for 以下场景：op 非 {match, register} 时
license: MIT
compatibility: >-
  op ∈ {match, register}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["设备驱动", "系统-设备驱动", "register 注"]
    when: "op ∈ {match, register}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代"
    not_applicable: ["op 非 {match, register} 时"]
  calibration: "对照：Linux 设备驱动——设备 ID 注册/匹配"
---

# 系统-设备驱动（os-ebc34d83）

## When to use

任务「设备驱动」；对照：Linux 设备驱动——设备 ID 注册/匹配。

## 克制条款（不适用条件）

op 非 {match, register} 时

## How to execute

按 op 分派；循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-设备驱动」
