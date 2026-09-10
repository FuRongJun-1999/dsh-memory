---
name: graph-3721be1c
description: >-
  增量备份 / 图存储-增量备份 / 数据库备份——全量+增量 / full 全。用户提到这些词时使用本技能。
  场景：对照：数据库备份——全量+增量（变更记录，还原叠加）。
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
    trigger_words: ["增量备份", "图存储-增量备份", "数据库备份——全量+增量", "full 全"]
    when: "op ∈ {full, incr, restore}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {full, incr, restore} 时"]
  calibration: "对照：数据库备份——全量+增量（变更记录，还原叠加）"
---

# 图存储-增量备份（graph-3721be1c）

## When to use

任务「增量备份」；对照：数据库备份——全量+增量（变更记录，还原叠加）。

## 克制条款（不适用条件）

op 非 {full, incr, restore} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图存储-增量备份」
