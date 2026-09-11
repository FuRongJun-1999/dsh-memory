---
name: vm-refcount
description: >-
  引用计数 / VM-引用计数 / VM 垃 / inc/dec 增。用户提到这些词时使用本技能。
  场景：对照：VM 垃圾回收——引用计数（归零回收）。
  【不适用】Not for 以下场景：op 非 {dec, inc} 时
license: MIT
compatibility: >-
  op ∈ {dec, inc}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["引用计数", "VM-引用计数", "VM 垃", "inc/dec 增"]
    when: "op ∈ {dec, inc}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {dec, inc} 时"]
  calibration: "对照：VM 垃圾回收——引用计数（归零回收）"
---

# VM-引用计数（vm-refcount）

## When to use

任务「引用计数」；对照：VM 垃圾回收——引用计数（归零回收）。

## 克制条款（不适用条件）

op 非 {dec, inc} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-引用计数」
