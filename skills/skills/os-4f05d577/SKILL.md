---
name: os-4f05d577
description: >-
  自旋锁 / 并发-自旋锁 / 自旋锁——忙等获取 / 释放 / acquire 忙。用户提到这些词时使用本技能。
  场景：对照：自旋锁——忙等获取/释放（短临界区）。
  【不适用】Not for 以下场景：op 非 {acquire, release} 时
license: MIT
compatibility: >-
  op ∈ {acquire, release}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["自旋锁", "并发-自旋锁", "自旋锁——忙等获取", "释放", "acquire 忙"]
    when: "op ∈ {acquire, release}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {acquire, release} 时"]
  calibration: "对照：自旋锁——忙等获取/释放（短临界区）"
---

# 并发-自旋锁（os-4f05d577）

## When to use

任务「自旋锁」；对照：自旋锁——忙等获取/释放（短临界区）。

## 克制条款（不适用条件）

op 非 {acquire, release} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「并发-自旋锁」
