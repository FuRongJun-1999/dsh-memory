---
name: graph-8eb38e3d
description: >-
  查询缓存 / 图查询-查询缓存 / 图查询——查询缓存 / get 命。用户提到这些词时使用本技能。
  场景：对照：图查询——查询缓存（LRU 淘汰，命中加速重复查询）。
  【不适用】Not for 以下场景：op 非 {get, put} 时
license: MIT
compatibility: >-
  op ∈ {get, put}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["查询缓存", "图查询-查询缓存", "图查询——查询缓存", "get 命"]
    when: "op ∈ {get, put}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {get, put} 时"]
  calibration: "对照：图查询——查询缓存（LRU 淘汰，命中加速重复查询）"
---

# 图查询-查询缓存（graph-8eb38e3d）

## When to use

任务「查询缓存」；对照：图查询——查询缓存（LRU 淘汰，命中加速重复查询）。

## 克制条款（不适用条件）

op 非 {get, put} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-查询缓存」
