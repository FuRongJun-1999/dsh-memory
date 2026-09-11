---
name: compile-assign
description: >-
  编译赋值 / 编译-赋值 / 赋值编译。用户提到这些词时使用本技能。
  场景：对照：赋值 = target = expr（名实对应）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  对照：赋值 = target = expr（名实对应）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["编译赋值", "编译-赋值", "赋值编译"]
    when: "对照：赋值 = target = expr（名实对应）"
    sub: ["① 拼接值指令 ② 追加名写入指令"]
    execute: "值指令 + STORE_NAME（名实绑定语义）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：赋值 = target = expr（名实对应）"
---

# 编译-赋值（compile-assign）

## When to use

任务「编译赋值」；对照：赋值 = target = expr（名实对应）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

值指令 + STORE_NAME（名实绑定语义）

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-赋值」
