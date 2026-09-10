---
name: pylang-50614726
description: >-
  最小堆 / 数据结构-最小堆 / heapq——最 / 下沉 / push 上 / 上浮 / 新元素与父节点比较并交换 / 根与较小子节点交换。用户提到这些词时使用本技能。
  场景：对照：heapq——最小堆上浮/下沉（push/pop/peek）。
  【不适用】Not for 以下场景：heap 为空/非法时；op 非 {peek, pop, push} 时
license: MIT
compatibility: >-
  op ∈ {peek, pop, push}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["最小堆", "数据结构-最小堆", "heapq——最", "下沉", "push 上", "上浮", "新元素与父节点比较并交换", "根与较小子节点交换"]
    when: "op ∈ {peek, pop, push}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["heap 为空/非法时；op 非 {peek, pop, push} 时"]
  calibration: "对照：heapq——最小堆上浮/下沉（push/pop/peek）"
---

# 数据结构-最小堆（pylang-50614726）

## When to use

任务「最小堆」；对照：heapq——最小堆上浮/下沉（push/pop/peek）。

## 克制条款（不适用条件）

heap 为空/非法时；op 非 {peek, pop, push} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「数据结构-最小堆」
