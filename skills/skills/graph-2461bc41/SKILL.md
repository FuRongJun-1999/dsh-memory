---
name: graph-2461bc41
description: >-
  条件分解 / 条件路由图-条件分解 / 条件合并 / 合取条件拆分为原子条件链。用户提到这些词时使用本技能。
  场景：对照：条件合并（v0.2 条件链叠加）的逆——合取拆为原子链，析取不可拆。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  cond 为条件表达式（AND 元组/原子条件）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["条件分解", "条件路由图-条件分解", "条件合并", "合取条件拆分为原子条件链"]
    when: "cond 为条件表达式（AND 元组/原子条件）"
    sub: ["① AND 递归拆分 ② 原子条件原样保留"]
    execute: "AND 节点分左右递归，非 AND 单元素列表（析取不可拆）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：条件合并（v0.2 条件链叠加）的逆——合取拆为原子链，析取不可拆"
---

# 条件路由图-条件分解（graph-2461bc41）

## When to use

任务「条件分解」；对照：条件合并（v0.2 条件链叠加）的逆——合取拆为原子链，析取不可拆。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

AND 节点分左右递归，非 AND 单元素列表（析取不可拆）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「条件路由图-条件分解」
