---
name: os-26a4f86a
description: >-
  权限提升 / 系统-权限提升 / sudo——命 / check 校。用户提到这些词时使用本技能。
  场景：对照：sudo——命令白名单授权（提权执行）。
  【不适用】Not for 以下场景：op 非 {check, run} 时
license: MIT
compatibility: >-
  op ∈ {check, run}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["权限提升", "系统-权限提升", "sudo——命", "check 校"]
    when: "op ∈ {check, run}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {check, run} 时"]
  calibration: "对照：sudo——命令白名单授权（提权执行）"
---

# 系统-权限提升（os-26a4f86a）

## When to use

任务「权限提升」；对照：sudo——命令白名单授权（提权执行）。

## 克制条款（不适用条件）

op 非 {check, run} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-权限提升」
