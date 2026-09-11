---
name: compiler-39fb5926
description: >-
  断点 / 调试-断点 / C4 调 / enable=True 。用户提到这些词时使用本技能。
  场景：对照：C4 调试器断点（登记/清除/命中判定——调试器暂停点）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  breaks.discard 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["断点", "调试-断点", "C4 调", "enable=True "]
    when: "breaks.discard 可用"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "断点：enable=True 登记 / False 清除 / None 查询命中（调试器暂停点）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：C4 调试器断点（登记/清除/命中判定——调试器暂停点）"
---

# 调试-断点（compiler-39fb5926）

## When to use

任务「断点」；对照：C4 调试器断点（登记/清除/命中判定——调试器暂停点）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

断点：enable=True 登记 / False 清除 / None 查询命中（调试器暂停点）

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「调试-断点」
