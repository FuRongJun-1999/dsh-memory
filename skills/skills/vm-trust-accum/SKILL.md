---
name: vm-trust-accum
description: >-
  信任累积 / VM-信任累积 / 德——信任值累积。用户提到这些词时使用本技能。
  场景：对照：德指令 → accumulate_trust（v0.2 INSTRUCTION_MAP 同语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  trust/amount 为数值（信任值 0-1 区间）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["信任累积", "VM-信任累积", "德——信任值累积"]
    when: "trust/amount 为数值（信任值 0-1 区间）"
    sub: ["① 信任值相加 ② 三位小数归整"]
    execute: "round(trust + amount, 3)"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：德指令 → accumulate_trust（v0.2 INSTRUCTION_MAP 同语义）"
---

# VM-信任累积（vm-trust-accum）

## When to use

任务「信任累积」；对照：德指令 → accumulate_trust（v0.2 INSTRUCTION_MAP 同语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

round(trust + amount, 3)

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-信任累积」
