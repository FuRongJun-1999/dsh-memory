---
name: os-955c4d66
description: >-
  多级反馈队列 / 调度-多级反馈队列 / OS 多 / 低等级定期提升 / enqueue 按 / / boost 低。用户提到这些词时使用本技能。
  场景：对照：OS 多级反馈队列 MLFQ——高等级优先调度，低等级定期提升（防饿死）。
  【不适用】Not for 以下场景：op 非 {boost, enqueue, pick} 时
license: MIT
compatibility: >-
  op ∈ {boost, enqueue, pick}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["多级反馈队列", "调度-多级反馈队列", "OS 多", "低等级定期提升", "enqueue 按", "/ boost 低"]
    when: "op ∈ {boost, enqueue, pick}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {boost, enqueue, pick} 时"]
  calibration: "对照：OS 多级反馈队列 MLFQ——高等级优先调度，低等级定期提升（防饿死）"
---

# 调度-多级反馈队列（os-955c4d66）

## When to use

任务「多级反馈队列」；对照：OS 多级反馈队列 MLFQ——高等级优先调度，低等级定期提升（防饿死）。

## 克制条款（不适用条件）

op 非 {boost, enqueue, pick} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「调度-多级反馈队列」
