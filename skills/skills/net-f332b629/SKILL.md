---
name: net-f332b629
description: >-
  策略路由 / 网络-策略路由 / 策略路由——按流量特征匹 / add 注。用户提到这些词时使用本技能。
  场景：对照：策略路由——按流量特征匹配策略（条件路由）。
  【不适用】Not for 以下场景：op 非 {add, match} 时
license: MIT
compatibility: >-
  op ∈ {add, match}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["策略路由", "网络-策略路由", "策略路由——按流量特征匹", "add 注"]
    when: "op ∈ {add, match}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {add, match} 时"]
  calibration: "对照：策略路由——按流量特征匹配策略（条件路由）"
---

# 网络-策略路由（net-f332b629）

## When to use

任务「策略路由」；对照：策略路由——按流量特征匹配策略（条件路由）。

## 克制条款（不适用条件）

op 非 {add, match} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-策略路由」
