---
name: compile-recursive
description: >-
  递归调用 / 编译-递归 / protocol-com / 递归函数 / 若 基条件 则 返回 基 / 组装为函数体字节码。用户提到这些词时使用本技能。
  场景：对照：protocol-compiler 递归函数（若则体内 RETURN，对齐阶乘 da997ef 语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  对照：protocol-compiler 递归函数（若则体内 RETURN，对齐阶乘 da997ef 语义）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["递归调用", "编译-递归", "protocol-com", "递归函数", "若 基条件 则 返回 基", "组装为函数体字节码"]
    when: "对照：protocol-compiler 递归函数（若则体内 RETURN，对齐阶乘 da997ef 语义）"
    sub: []
    execute: "递归函数：若 基条件 则 返回 基值，否则 返回 表达式（含自身调用）；组装为函数体字节码（CALL 自身由调用方回填入口）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：protocol-compiler 递归函数（若则体内 RETURN，对齐阶乘 da997ef 语义）"
---

# 编译-递归（compile-recursive）

## When to use

任务「递归调用」；对照：protocol-compiler 递归函数（若则体内 RETURN，对齐阶乘 da997ef 语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

递归函数：若 基条件 则 返回 基值，否则 返回 表达式（含自身调用）；组装为函数体字节码（CALL 自身由调用方回填入口）

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-递归」
