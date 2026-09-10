---
name: graph-3f920bf3
description: >-
  路由查询 / 条件路由图-查询 / 条件路由查询——条件 → / 条件路由查询 / 从条件出发影响传播 → 。用户提到这些词时使用本技能。
  场景：对照：条件路由查询——条件 → 影响面（规律集合，compose 条件链组合的图查询形态）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  queue.popleft 可用；graph.neighbors 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["路由查询", "条件路由图-查询", "条件路由查询——条件 →", "条件路由查询", "从条件出发影响传播 → "]
    when: "queue.popleft 可用；graph.neighbors 可用"
    sub: ["① 调用 sorted；② 调用 set；③ 调用 deque"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：条件路由查询——条件 → 影响面（规律集合，compose 条件链组合的图查询形态）"
---

# 条件路由图-查询（graph-3f920bf3）

## When to use

任务「路由查询」；对照：条件路由查询——条件 → 影响面（规律集合，compose 条件链组合的图查询形态）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「条件路由图-查询」
