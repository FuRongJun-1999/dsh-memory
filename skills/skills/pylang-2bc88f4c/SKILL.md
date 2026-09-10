---
name: pylang-2bc88f4c
description: >-
  栈机执行 / 栈机-字节码执行 / mini_python.。用户提到这些词时使用本技能。
  场景：对照：mini_python.py VM 栈机（指令→栈操作）。
  【不适用】Not for 以下场景：op 非 {ADD, MUL, PUSH, SUB} 时
license: MIT
compatibility: >-
  op ∈ {ADD, MUL, PUSH, SUB}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["栈机执行", "栈机-字节码执行", "mini_python."]
    when: "op ∈ {ADD, MUL, PUSH, SUB}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代"
    not_applicable: ["op 非 {ADD, MUL, PUSH, SUB} 时"]
  calibration: "对照：mini_python.py VM 栈机（指令→栈操作）"
---

# 栈机-字节码执行（pylang-2bc88f4c）

## When to use

任务「栈机执行」；对照：mini_python.py VM 栈机（指令→栈操作）。

## 克制条款（不适用条件）

op 非 {ADD, MUL, PUSH, SUB} 时

## How to execute

按 op 分派；循环迭代

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「栈机-字节码执行」
