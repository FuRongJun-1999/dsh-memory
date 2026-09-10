---
name: graph-8727827c
description: >-
  备份恢复 / 图存储-备份恢复 / 图备份——全量+增量合并 / 图备份 / 全量备份/增量合并/恢复。用户提到这些词时使用本技能。
  场景：对照：图备份——全量+增量合并恢复（数据安全）。
  【不适用】Not for 以下场景：op 非 {full, incr, restore} 时
license: MIT
compatibility: >-
  op ∈ {full, incr, restore}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["备份恢复", "图存储-备份恢复", "图备份——全量+增量合并", "图备份", "全量备份/增量合并/恢复"]
    when: "op ∈ {full, incr, restore}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {full, incr, restore} 时"]
  calibration: "对照：图备份——全量+增量合并恢复（数据安全）"
---

# 图存储-备份恢复（graph-8727827c）

## When to use

任务「备份恢复」；对照：图备份——全量+增量合并恢复（数据安全）。

## 克制条款（不适用条件）

op 非 {full, incr, restore} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图存储-备份恢复」
