---
name: graph-5cb7fbdf
description: >-
  边活跃度 / 图动态-边活跃度 / 动态图——边活跃度 / touch 更。用户提到这些词时使用本技能。
  场景：对照：动态图——边活跃度（时间窗内活跃判定）。
  【不适用】Not for 以下场景：op 非 {active, touch} 时
license: MIT
compatibility: >-
  op ∈ {active, touch}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["边活跃度", "图动态-边活跃度", "动态图——边活跃度", "touch 更"]
    when: "op ∈ {active, touch}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {active, touch} 时"]
  calibration: "对照：动态图——边活跃度（时间窗内活跃判定）"
---

# 图动态-边活跃度（graph-5cb7fbdf）

## When to use

任务「边活跃度」；对照：动态图——边活跃度（时间窗内活跃判定）。

## 克制条款（不适用条件）

op 非 {active, touch} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图动态-边活跃度」
