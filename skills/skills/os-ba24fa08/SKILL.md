---
name: os-ba24fa08
description: >-
  碎片整理 / 存储-碎片整理 / scan 扫。用户提到这些词时使用本技能。
  场景：对照：磁盘整理——空洞扫描/压实/碎片计数。
  【不适用】Not for 以下场景：op 非 {compact, frags, scan} 时
license: MIT
compatibility: >-
  op ∈ {compact, frags, scan}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["碎片整理", "存储-碎片整理", "scan 扫"]
    when: "op ∈ {compact, frags, scan}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {compact, frags, scan} 时"]
  calibration: "对照：磁盘整理——空洞扫描/压实/碎片计数"
---

# 存储-碎片整理（os-ba24fa08）

## When to use

任务「碎片整理」；对照：磁盘整理——空洞扫描/压实/碎片计数。

## 克制条款（不适用条件）

op 非 {compact, frags, scan} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「存储-碎片整理」
