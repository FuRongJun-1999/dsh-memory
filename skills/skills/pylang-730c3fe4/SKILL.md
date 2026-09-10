---
name: pylang-730c3fe4
description: >-
  矩阵运算 / 工具-矩阵运算 / 矩阵运算——逐元素加 / 矩阵乘 / add 逐。用户提到这些词时使用本技能。
  场景：对照：矩阵运算——逐元素加/矩阵乘（内积和）。
  【不适用】Not for 以下场景：op 非 {add, mul} 时
license: MIT
compatibility: >-
  op ∈ {add, mul}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["矩阵运算", "工具-矩阵运算", "矩阵运算——逐元素加", "矩阵乘", "add 逐"]
    when: "op ∈ {add, mul}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {add, mul} 时"]
  calibration: "对照：矩阵运算——逐元素加/矩阵乘（内积和）"
---

# 工具-矩阵运算（pylang-730c3fe4）

## When to use

任务「矩阵运算」；对照：矩阵运算——逐元素加/矩阵乘（内积和）。

## 克制条款（不适用条件）

op 非 {add, mul} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-矩阵运算」
