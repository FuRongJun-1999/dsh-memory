---
name: graph-df1ebb63
description: >-
  物化视图 / 图查询-物化视图 / 图查询——物化视图 / 预计算子查询结果。用户提到这些词时使用本技能。
  场景：对照：图查询——物化视图（预计算复用，refresh 重算）。
  【不适用】Not for 以下场景：op 非 {query, refresh} 时
license: MIT
compatibility: >-
  op ∈ {query, refresh}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["物化视图", "图查询-物化视图", "图查询——物化视图", "预计算子查询结果"]
    when: "op ∈ {query, refresh}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {query, refresh} 时"]
  calibration: "对照：图查询——物化视图（预计算复用，refresh 重算）"
---

# 图查询-物化视图（graph-df1ebb63）

## When to use

任务「物化视图」；对照：图查询——物化视图（预计算复用，refresh 重算）。

## 克制条款（不适用条件）

op 非 {query, refresh} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-物化视图」
