---
name: os-d237e500
description: >-
  内存碎片 / 内存-内存碎片 / 内存碎片——空洞记录与碎 / record 记。用户提到这些词时使用本技能。
  场景：对照：内存碎片——空洞记录与碎片率（碎片化度量）。
  【不适用】Not for 以下场景：op 非 {holes, rate, record} 时
license: MIT
compatibility: >-
  op ∈ {holes, rate, record}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["内存碎片", "内存-内存碎片", "内存碎片——空洞记录与碎", "record 记"]
    when: "op ∈ {holes, rate, record}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {holes, rate, record} 时"]
  calibration: "对照：内存碎片——空洞记录与碎片率（碎片化度量）"
---

# 内存-内存碎片（os-d237e500）

## When to use

任务「内存碎片」；对照：内存碎片——空洞记录与碎片率（碎片化度量）。

## 克制条款（不适用条件）

op 非 {holes, rate, record} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「内存-内存碎片」
