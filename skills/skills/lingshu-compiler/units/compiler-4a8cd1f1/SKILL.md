---
name: compiler-4a8cd1f1
description: >-
  条件求值 / 求值-条件表达式 / 中文比较词 / 中文条件表达式求值 / 左值 比较词 右值（比较。用户提到这些词时使用本技能。
  场景：对照：中文比较词（CHINESE_COMP_MAP：等于/大于/小于/不等于/不小于/不大于）；未定义符号诚实返回 None。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  right_s.strip 可用；left_s.strip 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["条件求值", "求值-条件表达式", "中文比较词", "中文条件表达式求值", "左值 比较词 右值（比较"]
    when: "right_s.strip 可用；left_s.strip 可用"
    sub: ["① 调用 float"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：中文比较词（CHINESE_COMP_MAP：等于/大于/小于/不等于/不小于/不大于）；未定义符号诚实返回 None"
---

# 求值-条件表达式（compiler-4a8cd1f1）

## When to use

任务「条件求值」；对照：中文比较词（CHINESE_COMP_MAP：等于/大于/小于/不等于/不小于/不大于）；未定义符号诚实返回 None。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「求值-条件表达式」
