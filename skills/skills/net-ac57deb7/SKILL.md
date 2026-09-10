---
name: net-ac57deb7
description: >-
  报文调度 / 网络-报文调度 / WFQ——加 / dequeue 按。用户提到这些词时使用本技能。
  场景：对照：WFQ——加权公平队列调度（按权重选队出队）。
  【不适用】Not for 以下场景：op 非 {dequeue, enqueue} 时
license: MIT
compatibility: >-
  op ∈ {dequeue, enqueue}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["报文调度", "网络-报文调度", "WFQ——加", "dequeue 按"]
    when: "op ∈ {dequeue, enqueue}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {dequeue, enqueue} 时"]
  calibration: "对照：WFQ——加权公平队列调度（按权重选队出队）"
---

# 网络-报文调度（net-ac57deb7）

## When to use

任务「报文调度」；对照：WFQ——加权公平队列调度（按权重选队出队）。

## 克制条款（不适用条件）

op 非 {dequeue, enqueue} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-报文调度」
