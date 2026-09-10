---
name: net-6c3b02c2
description: >-
  带宽分配 / 网络-带宽分配 / 带宽分配——按权重比例公 / 按权重比例分总带宽。用户提到这些词时使用本技能。
  场景：对照：带宽分配——按权重比例公平分配（weighted sharing）。
  【不适用】Not for 以下场景：s 越界（LtE）时
license: MIT
compatibility: >-
  参数 total/weights 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["带宽分配", "网络-带宽分配", "带宽分配——按权重比例公", "按权重比例分总带宽"]
    when: "参数 total/weights 合法"
    sub: ["① 调用 sum；② 调用 round"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["s 越界（LtE）时"]
  calibration: "对照：带宽分配——按权重比例公平分配（weighted sharing）"
---

# 网络-带宽分配（net-6c3b02c2）

## When to use

任务「带宽分配」；对照：带宽分配——按权重比例公平分配（weighted sharing）。

## 克制条款（不适用条件）

s 越界（LtE）时

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-带宽分配」
