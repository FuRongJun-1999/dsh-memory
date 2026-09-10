---
name: os-b718657b
description: >-
  多核均衡 / 调度-多核均衡 / SMP——多 / assign 分。用户提到这些词时使用本技能。
  场景：对照：SMP——多核负载均衡（最小负载核分配）。
  【不适用】Not for 以下场景：cores 为空/非法时；op 非 {assign, balance, loads} 时
license: MIT
compatibility: >-
  op ∈ {assign, balance, loads}；cores.index 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["多核均衡", "调度-多核均衡", "SMP——多", "assign 分"]
    when: "op ∈ {assign, balance, loads}；cores.index 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["cores 为空/非法时；op 非 {assign, balance, loads} 时"]
  calibration: "对照：SMP——多核负载均衡（最小负载核分配）"
---

# 调度-多核均衡（os-b718657b）

## When to use

任务「多核均衡」；对照：SMP——多核负载均衡（最小负载核分配）。

## 克制条款（不适用条件）

cores 为空/非法时；op 非 {assign, balance, loads} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「调度-多核均衡」
