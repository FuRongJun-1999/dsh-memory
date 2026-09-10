---
name: net-d67ec725
description: >-
  消息路由 / 网络-消息路由 / 消息中间件——主题绑定队 / bind 绑。用户提到这些词时使用本技能。
  场景：对照：消息中间件——主题绑定队列路由（发布订阅）。
  【不适用】Not for 以下场景：op 非 {bind, route} 时
license: MIT
compatibility: >-
  op ∈ {bind, route}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["消息路由", "网络-消息路由", "消息中间件——主题绑定队", "bind 绑"]
    when: "op ∈ {bind, route}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {bind, route} 时"]
  calibration: "对照：消息中间件——主题绑定队列路由（发布订阅）"
---

# 网络-消息路由（net-d67ec725）

## When to use

任务「消息路由」；对照：消息中间件——主题绑定队列路由（发布订阅）。

## 克制条款（不适用条件）

op 非 {bind, route} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-消息路由」
