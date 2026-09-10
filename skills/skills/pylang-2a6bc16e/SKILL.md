---
name: pylang-2a6bc16e
description: >-
  嵌套扁平化 / 工具-嵌套扁平化 / 递归展开——嵌套列表扁平 / 递归展开嵌套列表。用户提到这些词时使用本技能。
  场景：对照：递归展开——嵌套列表扁平化（flatten）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 items 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["嵌套扁平化", "工具-嵌套扁平化", "递归展开——嵌套列表扁平", "递归展开嵌套列表"]
    when: "参数 items 合法"
    sub: ["① 调用 isinstance；② 调用 flatten"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：递归展开——嵌套列表扁平化（flatten）"
---

# 工具-嵌套扁平化（pylang-2a6bc16e）

## When to use

任务「嵌套扁平化」；对照：递归展开——嵌套列表扁平化（flatten）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-嵌套扁平化」
