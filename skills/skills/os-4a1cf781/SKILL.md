---
name: os-4a1cf781
description: >-
  软中断 / 中断-软中断 / 硬中断中延迟的低优先级工。用户提到这些词时使用本技能。
  场景：对照：软中断（softirq）——硬中断处理中延迟低优先级工作，按优先级排队执行。
  【不适用】Not for 以下场景：action 非 {defer, run} 时返回 None；不重复入队检查由调用方负责
license: MIT
compatibility: >-
  action ∈ {defer, run}；defer 时 item 为 (优先级, 工作名)
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["软中断", "中断-软中断", "硬中断中延迟的低优先级工"]
    when: "action ∈ {defer, run}；defer 时 item 为 (优先级, 工作名)"
    sub: ["① defer 入队并按优先级排序 ② run 依序弹出处理"]
    execute: "list.sort(key=优先级) + pop(0) 逐出队"
    not_applicable: ["action 非 {defer, run} 时返回 None；不重复入队检查由调用方负责"]
  calibration: "对照：软中断（softirq）——硬中断处理中延迟低优先级工作，按优先级排队执行"
---

# 中断-软中断（os-4a1cf781）

## When to use

任务「软中断」；对照：软中断（softirq）——硬中断处理中延迟低优先级工作，按优先级排队执行。

## 克制条款（不适用条件）

action 非 {defer, run} 时返回 None；不重复入队检查由调用方负责

## How to execute

list.sort(key=优先级) + pop(0) 逐出队

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「中断-软中断」
