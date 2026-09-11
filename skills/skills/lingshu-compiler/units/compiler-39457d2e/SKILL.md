---
name: compiler-39457d2e
description: >-
  位运算 / 语法-位运算 / 位运算——与 / 异或 / 取反 / 按位与/或/异或/取反。用户提到这些词时使用本技能。
  场景：对照：位运算——与/或/异或/取反（bitwise 语义）。
  【不适用】Not for 以下场景：op 非 {and, not, or, xor} 时
license: MIT
compatibility: >-
  op ∈ {and, not, or, xor}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["位运算", "语法-位运算", "位运算——与", "异或", "取反", "按位与/或/异或/取反"]
    when: "op ∈ {and, not, or, xor}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {and, not, or, xor} 时"]
  calibration: "对照：位运算——与/或/异或/取反（bitwise 语义）"
---

# 语法-位运算（compiler-39457d2e）

## When to use

任务「位运算」；对照：位运算——与/或/异或/取反（bitwise 语义）。

## 克制条款（不适用条件）

op 非 {and, not, or, xor} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「语法-位运算」
