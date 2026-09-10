---
name: os-300ef22c
description: >-
  生产者消费者 / 并发-生产者消费者 / OS 并 / 生产者-消费者 / 有界缓冲。用户提到这些词时使用本技能。
  场景：对照：OS 并发——生产者-消费者（有界缓冲，满/空边界）。
  【不适用】Not for 以下场景：buf 为空/非法时；op 非 {consume, produce} 时
license: MIT
compatibility: >-
  op ∈ {consume, produce}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["生产者消费者", "并发-生产者消费者", "OS 并", "生产者-消费者", "有界缓冲"]
    when: "op ∈ {consume, produce}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["buf 为空/非法时；op 非 {consume, produce} 时"]
  calibration: "对照：OS 并发——生产者-消费者（有界缓冲，满/空边界）"
---

# 并发-生产者消费者（os-300ef22c）

## When to use

任务「生产者消费者」；对照：OS 并发——生产者-消费者（有界缓冲，满/空边界）。

## 克制条款（不适用条件）

buf 为空/非法时；op 非 {consume, produce} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「并发-生产者消费者」
