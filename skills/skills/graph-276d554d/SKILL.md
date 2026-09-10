---
name: graph-276d554d
description: >-
  游标遍历 / 图查询-游标遍历 / 查询游标——分页遍历 / next 取。用户提到这些词时使用本技能。
  场景：对照：查询游标——分页遍历（next/has_next/reset）。
  【不适用】Not for 以下场景：op 非 {has_next, next, reset} 时
license: MIT
compatibility: >-
  op ∈ {has_next, next, reset}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["游标遍历", "图查询-游标遍历", "查询游标——分页遍历", "next 取"]
    when: "op ∈ {has_next, next, reset}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {has_next, next, reset} 时"]
  calibration: "对照：查询游标——分页遍历（next/has_next/reset）"
---

# 图查询-游标遍历（graph-276d554d）

## When to use

任务「游标遍历」；对照：查询游标——分页遍历（next/has_next/reset）。

## 克制条款（不适用条件）

op 非 {has_next, next, reset} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-游标遍历」
