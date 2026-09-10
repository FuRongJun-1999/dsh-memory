---
name: os-92276145
description: >-
  抢占轮转 / 调度-时间片轮转 / 时间片轮转 / run 执。用户提到这些词时使用本技能。
  场景：对照：RR 时间片轮转——队首执行/时间片耗尽回队尾。
  【不适用】Not for 以下场景：ready 为空/非法时；op 非 {preempt, run, status} 时
license: MIT
compatibility: >-
  op ∈ {preempt, run, status}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["抢占轮转", "调度-时间片轮转", "时间片轮转", "run 执"]
    when: "op ∈ {preempt, run, status}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["ready 为空/非法时；op 非 {preempt, run, status} 时"]
  calibration: "对照：RR 时间片轮转——队首执行/时间片耗尽回队尾"
---

# 调度-时间片轮转（os-92276145）

## When to use

任务「抢占轮转」；对照：RR 时间片轮转——队首执行/时间片耗尽回队尾。

## 克制条款（不适用条件）

ready 为空/非法时；op 非 {preempt, run, status} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「调度-时间片轮转」
