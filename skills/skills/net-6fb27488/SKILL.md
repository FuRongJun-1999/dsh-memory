---
name: net-6fb27488
description: >-
  距离矢量 / 网络-距离矢量 / 网络路由——距离矢量 / 距离矢量路由 / 收到邻居路由表 → 合并。用户提到这些词时使用本技能。
  场景：对照：网络路由——距离矢量（邻居路由表合并，距离+1 取最短——RIP 语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 routes/neighbor/neighbor_routes 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["距离矢量", "网络-距离矢量", "网络路由——距离矢量", "距离矢量路由", "收到邻居路由表 → 合并"]
    when: "参数 routes/neighbor/neighbor_routes 合法"
    sub: ["① 调用 dict"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：网络路由——距离矢量（邻居路由表合并，距离+1 取最短——RIP 语义）"
---

# 网络-距离矢量（net-6fb27488）

## When to use

任务「距离矢量」；对照：网络路由——距离矢量（邻居路由表合并，距离+1 取最短——RIP 语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-距离矢量」
