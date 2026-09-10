---
name: compiler-11897630
description: >-
  覆盖率 / 调试-覆盖率 / C4 覆 / mark 标。用户提到这些词时使用本技能。
  场景：对照：C4 覆盖率——指令覆盖百分比（测试充分性）。
  【不适用】Not for 以下场景：total 为空/非法时；op 非 {mark, report} 时
license: MIT
compatibility: >-
  op ∈ {mark, report}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["覆盖率", "调试-覆盖率", "C4 覆", "mark 标"]
    when: "op ∈ {mark, report}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["total 为空/非法时；op 非 {mark, report} 时"]
  calibration: "对照：C4 覆盖率——指令覆盖百分比（测试充分性）"
---

# 调试-覆盖率（compiler-11897630）

## When to use

任务「覆盖率」；对照：C4 覆盖率——指令覆盖百分比（测试充分性）。

## 克制条款（不适用条件）

total 为空/非法时；op 非 {mark, report} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「调试-覆盖率」
