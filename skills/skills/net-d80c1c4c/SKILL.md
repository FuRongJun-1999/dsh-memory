---
name: net-d80c1c4c
description: >-
  消息队列 / 网络-消息队列 / 入队/出队。用户提到这些词时使用本技能。
  场景：对照：消息队列——FIFO 入队出队（生产消费解耦）。
  【不适用】Not for 以下场景：q 为空/非法时；op 非 {dequeue, enqueue} 时
license: MIT
compatibility: >-
  op ∈ {dequeue, enqueue}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["消息队列", "网络-消息队列", "入队/出队"]
    when: "op ∈ {dequeue, enqueue}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["q 为空/非法时；op 非 {dequeue, enqueue} 时"]
  calibration: "对照：消息队列——FIFO 入队出队（生产消费解耦）"
---

# 网络-消息队列（net-d80c1c4c）

## When to use

任务「消息队列」；对照：消息队列——FIFO 入队出队（生产消费解耦）。

## 克制条款（不适用条件）

q 为空/非法时；op 非 {dequeue, enqueue} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-消息队列」
