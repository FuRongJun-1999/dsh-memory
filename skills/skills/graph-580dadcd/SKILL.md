---
name: graph-580dadcd
description: >-
  条件单元对接 / 条件路由图-对接 / 真实条件单元库 / compose_engi / conditions=条 / 条件 → 影响的知识单元。用户提到这些词时使用本技能。
  场景：对照：真实条件单元库（compose_engine 43 单元）→ 条件路由图（条件 → 影响的规律单元）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  g.add_node 可用；g.add_edge 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["条件单元对接", "条件路由图-对接", "真实条件单元库", "compose_engi", "conditions=条", "条件 → 影响的知识单元"]
    when: "g.add_node 可用；g.add_edge 可用"
    sub: ["① 调用 Graph"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：真实条件单元库（compose_engine 43 单元）→ 条件路由图（条件 → 影响的规律单元）"
---

# 条件路由图-对接（graph-580dadcd）

## When to use

任务「条件单元对接」；对照：真实条件单元库（compose_engine 43 单元）→ 条件路由图（条件 → 影响的规律单元）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「条件路由图-对接」
