---
name: graph-656e7bd4
description: >-
  主从复制 / 图存储-主从复制 / 分布式图——主从复制 / 写主节点 → 同步从节点。用户提到这些词时使用本技能。
  场景：对照：分布式图——主从复制（写全副本同步，读主副本）。
  【不适用】Not for 以下场景：op 非 {read, write} 时
license: MIT
compatibility: >-
  op ∈ {read, write}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["主从复制", "图存储-主从复制", "分布式图——主从复制", "写主节点 → 同步从节点"]
    when: "op ∈ {read, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {read, write} 时"]
  calibration: "对照：分布式图——主从复制（写全副本同步，读主副本）"
---

# 图存储-主从复制（graph-656e7bd4）

## When to use

任务「主从复制」；对照：分布式图——主从复制（写全副本同步，读主副本）。

## 克制条款（不适用条件）

op 非 {read, write} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图存储-主从复制」
