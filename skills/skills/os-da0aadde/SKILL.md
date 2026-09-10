---
name: os-da0aadde
description: >-
  最短作业 / 调度-SJF / OS 调 / SJF 最 / [] → 完成时间列表。用户提到这些词时使用本技能。
  场景：对照：OS 调度 SJF——最短作业优先（平均等待最小化）。
  【不适用】Not for 以下场景：ready 为空/非法时
license: MIT
compatibility: >-
  ready.sort 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["最短作业", "调度-SJF", "OS 调", "SJF 最", "[] → 完成时间列表"]
    when: "ready.sort 可用"
    sub: ["① 调用 sorted"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["ready 为空/非法时"]
  calibration: "对照：OS 调度 SJF——最短作业优先（平均等待最小化）"
---

# 调度-SJF（os-da0aadde）

## When to use

任务「最短作业」；对照：OS 调度 SJF——最短作业优先（平均等待最小化）。

## 克制条款（不适用条件）

ready 为空/非法时

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「调度-SJF」
