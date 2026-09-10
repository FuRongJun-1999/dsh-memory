---
name: pylang-f92bc49b
description: >-
  集合推导 / 推导式-集合推导 / CPython 集 / {x for x in 。用户提到这些词时使用本技能。
  场景：对照：CPython 集合推导（{x for ...} 去重 + 条件过滤，与列表/字典推导同族）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  items 可迭代；cond 为谓词函数或 None（不过滤）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["集合推导", "推导式-集合推导", "CPython 集", "{x for x in "]
    when: "items 可迭代；cond 为谓词函数或 None（不过滤）"
    sub: ["① 无谓词直接去重建集 ② 有谓词过滤后建集"]
    execute: "set(items) 或 {x for x in items if cond(x)}"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：CPython 集合推导（{x for ...} 去重 + 条件过滤，与列表/字典推导同族）"
---

# 推导式-集合推导（pylang-f92bc49b）

## When to use

任务「集合推导」；对照：CPython 集合推导（{x for ...} 去重 + 条件过滤，与列表/字典推导同族）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

set(items) 或 {x for x in items if cond(x)}

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「推导式-集合推导」
