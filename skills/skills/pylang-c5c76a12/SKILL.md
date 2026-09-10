---
name: pylang-c5c76a12
description: >-
  异步队列 / 异步-异步队列 / asyncio.Queu / 出队 / 大小 / put 入。用户提到这些词时使用本技能。
  场景：对照：asyncio.Queue——异步入队/出队/大小（FIFO）。
  【不适用】Not for 以下场景：op 非 {get, put, size} 时
license: MIT
compatibility: >-
  op ∈ {get, put, size}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["异步队列", "异步-异步队列", "asyncio.Queu", "出队", "大小", "put 入"]
    when: "op ∈ {get, put, size}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {get, put, size} 时"]
  calibration: "对照：asyncio.Queue——异步入队/出队/大小（FIFO）"
---

# 异步-异步队列（pylang-c5c76a12）

## When to use

任务「异步队列」；对照：asyncio.Queue——异步入队/出队/大小（FIFO）。

## 克制条款（不适用条件）

op 非 {get, put, size} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「异步-异步队列」
