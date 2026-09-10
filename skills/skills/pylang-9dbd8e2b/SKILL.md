---
name: pylang-9dbd8e2b
description: >-
  控制流 / 求值-控制流 / 语句执行器。用户提到这些词时使用本技能。
  场景：对照：mini_python.py exec_stmt（assign/if/while 语义）。
  【不适用】Not for 以下场景：k 非 {assign, if, while} 时
license: MIT
compatibility: >-
  k ∈ {assign, if, while}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["控制流", "求值-控制流", "语句执行器"]
    when: "k ∈ {assign, if, while}"
    sub: ["1 k 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["k 非 {assign, if, while} 时"]
  calibration: "对照：mini_python.py exec_stmt（assign/if/while 语义）"
---

# 求值-控制流（pylang-9dbd8e2b）

## When to use

任务「控制流」；对照：mini_python.py exec_stmt（assign/if/while 语义）。

## 克制条款（不适用条件）

k 非 {assign, if, while} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「求值-控制流」
