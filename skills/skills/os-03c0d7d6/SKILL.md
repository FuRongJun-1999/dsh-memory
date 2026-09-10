---
name: os-03c0d7d6
description: >-
  互斥锁 / 进程-互斥锁 / OS 并 / 互斥锁操作 / lock/unlock（。用户提到这些词时使用本技能。
  场景：对照：OS 并发——互斥锁（占用时加锁失败，释放后可用）。
  【不适用】Not for 以下场景：op 非 {lock, unlock} 时；state 非 {free} 时
license: MIT
compatibility: >-
  op ∈ {lock, unlock}；state ∈ {free}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["互斥锁", "进程-互斥锁", "OS 并", "互斥锁操作", "lock/unlock（"]
    when: "op ∈ {lock, unlock}；state ∈ {free}"
    sub: ["① op 分支处理；2 state 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {lock, unlock} 时；state 非 {free} 时"]
  calibration: "对照：OS 并发——互斥锁（占用时加锁失败，释放后可用）"
---

# 进程-互斥锁（os-03c0d7d6）

## When to use

任务「互斥锁」；对照：OS 并发——互斥锁（占用时加锁失败，释放后可用）。

## 克制条款（不适用条件）

op 非 {lock, unlock} 时；state 非 {free} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「进程-互斥锁」
