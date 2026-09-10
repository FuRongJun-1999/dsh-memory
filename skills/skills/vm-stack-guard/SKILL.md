---
name: vm-stack-guard
description: >-
  栈保护 / VM-栈保护 / VM 运 / 压栈前检查深度。用户提到这些词时使用本技能。
  场景：对照：VM 运行时——栈深度限制（防递归栈溢出）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 stack/limit/value 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["栈保护", "VM-栈保护", "VM 运", "压栈前检查深度"]
    when: "参数 stack/limit/value 合法"
    sub: ["① 调用 len"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：VM 运行时——栈深度限制（防递归栈溢出）"
---

# VM-栈保护（vm-stack-guard）

## When to use

任务「栈保护」；对照：VM 运行时——栈深度限制（防递归栈溢出）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-栈保护」
