---
name: compiler-0010c4bf
description: >-
  指令重排 / 编译-指令重排 / 编译优化——指令重排 / PUSH 常。用户提到这些词时使用本技能。
  场景：对照：编译优化——指令重排（无关指令乱序减少停顿）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 instrs 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["指令重排", "编译-指令重排", "编译优化——指令重排", "PUSH 常"]
    when: "参数 instrs 合法"
    sub: []
    execute: "指令重排：PUSH 常量提前（无关指令乱序——减少停顿）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：编译优化——指令重排（无关指令乱序减少停顿）"
---

# 编译-指令重排（compiler-0010c4bf）

## When to use

任务「指令重排」；对照：编译优化——指令重排（无关指令乱序减少停顿）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

指令重排：PUSH 常量提前（无关指令乱序——减少停顿）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-指令重排」
