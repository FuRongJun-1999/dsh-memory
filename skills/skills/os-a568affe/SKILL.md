---
name: os-a568affe
description: >-
  实时调度 / 调度-实时EDF / OS 实 / 最早截止时间优先。用户提到这些词时使用本技能。
  场景：对照：OS 实时调度 EDF——最早截止时间优先（deadline 最近先执行）。
  【不适用】Not for 以下场景：ready 为空/非法时
license: MIT
compatibility: >-
  参数 ready/now 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["实时调度", "调度-实时EDF", "OS 实", "最早截止时间优先"]
    when: "参数 ready/now 合法"
    sub: ["① 调用 min"]
    execute: "顺序调用"
    not_applicable: ["ready 为空/非法时"]
  calibration: "对照：OS 实时调度 EDF——最早截止时间优先（deadline 最近先执行）"
---

# 调度-实时EDF（os-a568affe）

## When to use

任务「实时调度」；对照：OS 实时调度 EDF——最早截止时间优先（deadline 最近先执行）。

## 克制条款（不适用条件）

ready 为空/非法时

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「调度-实时EDF」
