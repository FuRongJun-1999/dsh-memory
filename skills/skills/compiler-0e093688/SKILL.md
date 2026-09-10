---
name: compiler-0e093688
description: >-
  污点分析 / 分析-污点分析 / 静态分析——污点传播 / mark 标。用户提到这些词时使用本技能。
  场景：对照：静态分析——污点传播（标记/传播/查询）。
  【不适用】Not for 以下场景：op 非 {check, mark, propagate} 时
license: MIT
compatibility: >-
  op ∈ {check, mark, propagate}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["污点分析", "分析-污点分析", "静态分析——污点传播", "mark 标"]
    when: "op ∈ {check, mark, propagate}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {check, mark, propagate} 时"]
  calibration: "对照：静态分析——污点传播（标记/传播/查询）"
---

# 分析-污点分析（compiler-0e093688）

## When to use

任务「污点分析」；对照：静态分析——污点传播（标记/传播/查询）。

## 克制条款（不适用条件）

op 非 {check, mark, propagate} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「分析-污点分析」
