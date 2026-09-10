---
name: graph-f56fa220
description: >-
  条件路由映射 / 条件路由图-映射 / 条件单元库 / 条件单元库 → 条件路由 / 知识=节点 / units: {知。用户提到这些词时使用本技能。
  场景：对照：条件单元库（{条件→规律}）→ 条件路由图（第4阶段知识图同构）。
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
    trigger_words: ["条件路由映射", "条件路由图-映射", "条件单元库", "条件单元库 → 条件路由", "知识=节点", "units: {知"]
    when: "g.add_node 可用；g.add_edge 可用"
    sub: ["① 调用 Graph"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：条件单元库（{条件→规律}）→ 条件路由图（第4阶段知识图同构）"
---

# 条件路由图-映射（graph-f56fa220）

## When to use

任务「条件路由映射」；对照：条件单元库（{条件→规律}）→ 条件路由图（第4阶段知识图同构）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「条件路由图-映射」
