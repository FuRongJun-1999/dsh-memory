---
name: graph-2508389f
description: >-
  执行计划 / 图查询-执行计划 / 图查询优化——执行计划 / 查询执行计划 / 按选择性排序条件。用户提到这些词时使用本技能。
  场景：对照：图查询优化——执行计划（按选择性升序，低选择性条件先执行）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 conditions/stats 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["执行计划", "图查询-执行计划", "图查询优化——执行计划", "查询执行计划", "按选择性排序条件"]
    when: "参数 conditions/stats 合法"
    sub: ["① 调用 sorted"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图查询优化——执行计划（按选择性升序，低选择性条件先执行）"
---

# 图查询-执行计划（graph-2508389f）

## When to use

任务「执行计划」；对照：图查询优化——执行计划（按选择性升序，低选择性条件先执行）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-执行计划」
