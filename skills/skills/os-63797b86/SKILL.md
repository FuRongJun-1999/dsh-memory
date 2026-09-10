---
name: os-63797b86
description: >-
  中断优先级 / 中断-嵌套优先级 / OS 中 / 中断嵌套 / 新中断优先级更高 → 可。用户提到这些词时使用本技能。
  场景：对照：OS 中断——嵌套优先级（高优先级中断可抢占低优先级，同级不嵌套）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 current_prio/new_prio 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["中断优先级", "中断-嵌套优先级", "OS 中", "中断嵌套", "新中断优先级更高 → 可"]
    when: "参数 current_prio/new_prio 合法"
    sub: []
    execute: "中断嵌套：新中断优先级更高 → 可抢占当前（NMI/高优先抢占）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 中断——嵌套优先级（高优先级中断可抢占低优先级，同级不嵌套）"
---

# 中断-嵌套优先级（os-63797b86）

## When to use

任务「中断优先级」；对照：OS 中断——嵌套优先级（高优先级中断可抢占低优先级，同级不嵌套）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

中断嵌套：新中断优先级更高 → 可抢占当前（NMI/高优先抢占）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「中断-嵌套优先级」
