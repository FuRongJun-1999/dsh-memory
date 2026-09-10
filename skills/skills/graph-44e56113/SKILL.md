---
name: graph-44e56113
description: >-
  弦图判定 / 图算法-弦图判定 / 弦图——无弦环判定 / 简化 / 三角图判定——遍历环检测。用户提到这些词时使用本技能。
  场景：对照：弦图——无弦环判定（完美消除序）。
  【不适用】Not for 以下场景：n 越界（LtE）时
license: MIT
compatibility: >-
  参数 adj 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["弦图判定", "图算法-弦图判定", "弦图——无弦环判定", "简化", "三角图判定——遍历环检测"]
    when: "参数 adj 合法"
    sub: ["① 调用 len；② 调用 set"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["n 越界（LtE）时"]
  calibration: "对照：弦图——无弦环判定（完美消除序）"
---

# 图算法-弦图判定（graph-44e56113）

## When to use

任务「弦图判定」；对照：弦图——无弦环判定（完美消除序）。

## 克制条款（不适用条件）

n 越界（LtE）时

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-弦图判定」
