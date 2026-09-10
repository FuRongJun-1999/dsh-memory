---
name: pylang-a88db70d
description: >-
  队列栈 / 数据结构-队列栈 / collections. / dequeue 队。用户提到这些词时使用本技能。
  场景：对照：collections.deque——队首 FIFO/栈顶 LIFO（双端操作）。
  【不适用】Not for 以下场景：op 非 {dequeue, pop, push} 时
license: MIT
compatibility: >-
  op ∈ {dequeue, pop, push}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["队列栈", "数据结构-队列栈", "collections.", "dequeue 队"]
    when: "op ∈ {dequeue, pop, push}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {dequeue, pop, push} 时"]
  calibration: "对照：collections.deque——队首 FIFO/栈顶 LIFO（双端操作）"
---

# 数据结构-队列栈（pylang-a88db70d）

## When to use

任务「队列栈」；对照：collections.deque——队首 FIFO/栈顶 LIFO（双端操作）。

## 克制条款（不适用条件）

op 非 {dequeue, pop, push} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「数据结构-队列栈」
