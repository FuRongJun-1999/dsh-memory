---
name: compiler-afe169d8
description: >-
  指令调度 / 编译-指令调度 / 编译优化——指令调度 / 无依赖指令前移。用户提到这些词时使用本技能。
  场景：对照：编译优化——指令调度（依赖无关前移）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  arg.startswith 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["指令调度", "编译-指令调度", "编译优化——指令调度", "无依赖指令前移"]
    when: "arg.startswith 可用"
    sub: ["① 调用 set；② 调用 isinstance；③ 调用 any"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：编译优化——指令调度（依赖无关前移）"
---

# 编译-指令调度（compiler-afe169d8）

## When to use

任务「指令调度」；对照：编译优化——指令调度（依赖无关前移）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-指令调度」
