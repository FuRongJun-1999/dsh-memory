---
name: os-ecbebbe3
description: >-
  工作窃取 / 调度-工作窃取 / 空闲核从最忙队列窃取一个。用户提到这些词时使用本技能。
  场景：对照：工作窃取（work stealing）——空闲核从最忙队列窃取任务，无其他非空队列则不动。
  【不适用】Not for 以下场景：candidates 为空/非法时
license: MIT
compatibility: >-
  queues 为各核任务队列列表；worker 为申请窃取的核号
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["工作窃取", "调度-工作窃取", "空闲核从最忙队列窃取一个"]
    when: "queues 为各核任务队列列表；worker 为申请窃取的核号"
    sub: ["① 空闲判定（自己队列非空则不窃取）② 找最忙非空队列 ③ 迁移一个任务"]
    execute: "忙核直返；空闲则取最忙队列 pop(0) 到本队列"
    not_applicable: ["candidates 为空/非法时"]
  calibration: "对照：工作窃取（work stealing）——空闲核从最忙队列窃取任务，无其他非空队列则不动"
---

# 调度-工作窃取（os-ecbebbe3）

## When to use

任务「工作窃取」；对照：工作窃取（work stealing）——空闲核从最忙队列窃取任务，无其他非空队列则不动。

## 克制条款（不适用条件）

candidates 为空/非法时

## How to execute

忙核直返；空闲则取最忙队列 pop(0) 到本队列

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「调度-工作窃取」
