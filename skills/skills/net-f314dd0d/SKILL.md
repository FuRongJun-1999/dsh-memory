---
name: net-f314dd0d
description: >-
  QoS队列 / 网络-QoS队列 / QoS 队 / classify 流。用户提到这些词时使用本技能。
  场景：对照：网络 QoS——流量分类+优先级队列（高优先先出）。
  【不适用】Not for 以下场景：op 非 {classify, dequeue, enqueue} 时
license: MIT
compatibility: >-
  op ∈ {classify, dequeue, enqueue}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["QoS队列", "网络-QoS队列", "QoS 队", "classify 流"]
    when: "op ∈ {classify, dequeue, enqueue}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代"
    not_applicable: ["op 非 {classify, dequeue, enqueue} 时"]
  calibration: "对照：网络 QoS——流量分类+优先级队列（高优先先出）"
---

# 网络-QoS队列（net-f314dd0d）

## When to use

任务「QoS队列」；对照：网络 QoS——流量分类+优先级队列（高优先先出）。

## 克制条款（不适用条件）

op 非 {classify, dequeue, enqueue} 时

## How to execute

按 op 分派；循环迭代

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-QoS队列」
