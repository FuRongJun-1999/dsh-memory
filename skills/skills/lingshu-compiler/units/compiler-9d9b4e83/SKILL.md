---
name: compiler-9d9b4e83
description: >-
  三元表达式 / 语法-三元表达式 / 条件 ? 真值 : 假值。用户提到这些词时使用本技能。
  场景：对照：三元条件表达式——条件跳转选真/假分支。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 cond/then_expr/else_expr 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["三元表达式", "语法-三元表达式", "条件 ? 真值 : 假值"]
    when: "参数 cond/then_expr/else_expr 合法"
    sub: ["① 调用 list；② 调用 len"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：三元条件表达式——条件跳转选真/假分支"
---

# 语法-三元表达式（compiler-9d9b4e83）

## When to use

任务「三元表达式」；对照：三元条件表达式——条件跳转选真/假分支。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「语法-三元表达式」
