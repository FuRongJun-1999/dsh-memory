---
name: vm-compare
description: >-
  比较执行 / VM-比较执行 / VM 比 / GT / EQ。用户提到这些词时使用本技能。
  场景：对照：VM 比较指令——LT/GT/EQ（栈机比较→布尔）。
  【不适用】Not for 以下场景：op 非 {EQ, GT, LT} 时
license: MIT
compatibility: >-
  op ∈ {EQ, GT, LT}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["比较执行", "VM-比较执行", "VM 比", "GT", "EQ"]
    when: "op ∈ {EQ, GT, LT}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {EQ, GT, LT} 时"]
  calibration: "对照：VM 比较指令——LT/GT/EQ（栈机比较→布尔）"
---

# VM-比较执行（vm-compare）

## When to use

任务「比较执行」；对照：VM 比较指令——LT/GT/EQ（栈机比较→布尔）。

## 克制条款（不适用条件）

op 非 {EQ, GT, LT} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-比较执行」
