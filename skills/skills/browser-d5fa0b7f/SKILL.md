---
name: browser-d5fa0b7f
description: >-
  空闲调度 / 浏览器-空闲调度 / request 登。用户提到这些词时使用本技能。
  场景：对照：requestIdleCallback——空闲时段低优先任务调度。
  【不适用】Not for 以下场景：op 非 {pending, request, run} 时
license: MIT
compatibility: >-
  op ∈ {pending, request, run}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["空闲调度", "浏览器-空闲调度", "request 登"]
    when: "op ∈ {pending, request, run}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {pending, request, run} 时"]
  calibration: "对照：requestIdleCallback——空闲时段低优先任务调度"
---

# 浏览器-空闲调度（browser-d5fa0b7f）

## When to use

任务「空闲调度」；对照：requestIdleCallback——空闲时段低优先任务调度。

## 克制条款（不适用条件）

op 非 {pending, request, run} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-空闲调度」
