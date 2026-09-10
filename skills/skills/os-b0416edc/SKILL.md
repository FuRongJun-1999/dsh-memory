---
name: os-b0416edc
description: >-
  调优建议 / 性能-调优建议 / OS 性 / 调优 / 指标 → 建议。用户提到这些词时使用本技能。
  场景：对照：OS 性能——调优建议（瓶颈 → 参数调整建议）。
  【不适用】Not for 以下场景：adv 为空/非法时
license: MIT
compatibility: >-
  参数 metrics 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["调优建议", "性能-调优建议", "OS 性", "调优", "指标 → 建议"]
    when: "参数 metrics 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "调优：指标 → 建议（瓶颈 → 调整参数）"
    not_applicable: ["adv 为空/非法时"]
  calibration: "对照：OS 性能——调优建议（瓶颈 → 参数调整建议）"
---

# 性能-调优建议（os-b0416edc）

## When to use

任务「调优建议」；对照：OS 性能——调优建议（瓶颈 → 参数调整建议）。

## 克制条款（不适用条件）

adv 为空/非法时

## How to execute

调优：指标 → 建议（瓶颈 → 调整参数）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「性能-调优建议」
