---
name: compiler-6f1c0eea
description: >-
  注释剥离 / 词法-注释剥离 / 词法预处理——注释剥离 / # 行注释 / 井号中文。用户提到这些词时使用本技能。
  场景：对照：词法预处理——注释剥离（# 行注释，中文注释同语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  src.splitlines 可用；line.find 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["注释剥离", "词法-注释剥离", "词法预处理——注释剥离", "# 行注释 / 井号中文"]
    when: "src.splitlines 可用；line.find 可用"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：词法预处理——注释剥离（# 行注释，中文注释同语义）"
---

# 词法-注释剥离（compiler-6f1c0eea）

## When to use

任务「注释剥离」；对照：词法预处理——注释剥离（# 行注释，中文注释同语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「词法-注释剥离」
