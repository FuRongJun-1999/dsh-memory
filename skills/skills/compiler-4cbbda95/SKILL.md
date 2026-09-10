---
name: compiler-4cbbda95
description: >-
  编译指令 / 编译-指令 / INSTRUCTION_MAP。用户提到这些词时使用本技能。
  场景：对照：INSTRUCTION_MAP（道→create_path 等；未接入指令诚实边界）。
  【不适用】Not for 以下场景：kind 非 {DAO, DE} 时
license: MIT
compatibility: >-
  kind ∈ {DAO, DE}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["编译指令", "编译-指令", "INSTRUCTION_MAP"]
    when: "kind ∈ {DAO, DE}"
    sub: ["1 kind 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["kind 非 {DAO, DE} 时"]
  calibration: "对照：INSTRUCTION_MAP（道→create_path 等；未接入指令诚实边界）"
---

# 编译-指令（compiler-4cbbda95）

## When to use

任务「编译指令」；对照：INSTRUCTION_MAP（道→create_path 等；未接入指令诚实边界）。

## 克制条款（不适用条件）

kind 非 {DAO, DE} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-指令」
