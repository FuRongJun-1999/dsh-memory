---
name: net-107ab486
description: >-
  网关 / 网络-网关 / route 转。用户提到这些词时使用本技能。
  场景：对照：网关——路由转发/默认出口/路由表。
  【不适用】Not for 以下场景：op 非 {default, route, table} 时
license: MIT
compatibility: >-
  op ∈ {default, route, table}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["网关", "网络-网关", "route 转"]
    when: "op ∈ {default, route, table}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {default, route, table} 时"]
  calibration: "对照：网关——路由转发/默认出口/路由表"
---

# 网络-网关（net-107ab486）

## When to use

任务「网关」；对照：网关——路由转发/默认出口/路由表。

## 克制条款（不适用条件）

op 非 {default, route, table} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-网关」
