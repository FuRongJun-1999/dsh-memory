---
name: os-313ef4ed
description: >-
  屏障同步 / 并发-屏障同步 / OS 并 / wait 到。用户提到这些词时使用本技能。
  场景：对照：OS 并发——屏障同步（全部到达汇合点才释放）。
  【不适用】Not for 以下场景：op 非 {wait} 时
license: MIT
compatibility: >-
  op ∈ {wait}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["屏障同步", "并发-屏障同步", "OS 并", "wait 到"]
    when: "op ∈ {wait}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {wait} 时"]
  calibration: "对照：OS 并发——屏障同步（全部到达汇合点才释放）"
---

# 并发-屏障同步（os-313ef4ed）

## When to use

任务「屏障同步」；对照：OS 并发——屏障同步（全部到达汇合点才释放）。

## 克制条款（不适用条件）

op 非 {wait} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「并发-屏障同步」
