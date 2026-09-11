---
name: compile-expr-tree
description: >-
  表达式树 / 编译-表达式树 / 语法——中缀表达式 → 。用户提到这些词时使用本技能。
  场景：对照：语法——中缀表达式 → 嵌套树（AST 构建）。
  【不适用】Not for 以下场景：tok 非 {(, )} 时
license: MIT
compatibility: >-
  tok ∈ {(, )}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["表达式树", "编译-表达式树", "语法——中缀表达式 → "]
    when: "tok ∈ {(, )}"
    sub: ["1 tok 分支处理"]
    execute: "按 op 分派；循环迭代"
    not_applicable: ["tok 非 {(, )} 时"]
  calibration: "对照：语法——中缀表达式 → 嵌套树（AST 构建）"
---

# 编译-表达式树（compile-expr-tree）

## When to use

任务「表达式树」；对照：语法——中缀表达式 → 嵌套树（AST 构建）。

## 克制条款（不适用条件）

tok 非 {(, )} 时

## How to execute

按 op 分派；循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-表达式树」
