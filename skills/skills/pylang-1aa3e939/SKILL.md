---
name: pylang-1aa3e939
description: >-
  格式化 / 工具-格式化 / 模板 {名} 占位符填充。用户提到这些词时使用本技能。
  场景：对照：Python f-string（{名} 占位符模板填充）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  out.replace 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["格式化", "工具-格式化", "模板 {名} 占位符填充"]
    when: "out.replace 可用"
    sub: ["① 调用 str"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python f-string（{名} 占位符模板填充）"
---

# 工具-格式化（pylang-1aa3e939）

## When to use

任务「格式化」；对照：Python f-string（{名} 占位符模板填充）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-格式化」
