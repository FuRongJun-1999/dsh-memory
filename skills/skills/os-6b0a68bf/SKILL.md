---
name: os-6b0a68bf
description: >-
  文件锁 / 文件-文件锁 / OS 文 / flock 语。用户提到这些词时使用本技能。
  场景：对照：OS 文件锁——flock（独占/释放，并发写保护）。
  【不适用】Not for 以下场景：op 非 {lock, unlock} 时
license: MIT
compatibility: >-
  op ∈ {lock, unlock}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件锁", "文件-文件锁", "OS 文", "flock 语"]
    when: "op ∈ {lock, unlock}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {lock, unlock} 时"]
  calibration: "对照：OS 文件锁——flock（独占/释放，并发写保护）"
---

# 文件-文件锁（os-6b0a68bf）

## When to use

任务「文件锁」；对照：OS 文件锁——flock（独占/释放，并发写保护）。

## 克制条款（不适用条件）

op 非 {lock, unlock} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-文件锁」
