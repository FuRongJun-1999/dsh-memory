---
name: pylang-f2d6ec27
description: >-
  解包赋值 / 求值-解包赋值 / CPython 解 / a, b = b, a  / 递归遍历 / 嵌套列表目标逐层绑定值。用户提到这些词时使用本技能。
  场景：对照：CPython 解包赋值（RHS 先求值后按目标逐层写入，嵌套列表递归解包）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  targets 与 values 结构对应（嵌套列表匹配嵌套值）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["解包赋值", "求值-解包赋值", "CPython 解", "a, b = b, a ", "递归遍历", "嵌套列表目标逐层绑定值"]
    when: "targets 与 values 结构对应（嵌套列表匹配嵌套值）"
    sub: ["① 逐目标遍历 ② 嵌套列表递归解包 ③ 叶子目标绑定值"]
    execute: "zip 配对 + 递归 walk，RHS 先求值后逐层写入"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：CPython 解包赋值（RHS 先求值后按目标逐层写入，嵌套列表递归解包）"
---

# 求值-解包赋值（pylang-f2d6ec27）

## When to use

任务「解包赋值」；对照：CPython 解包赋值（RHS 先求值后按目标逐层写入，嵌套列表递归解包）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

zip 配对 + 递归 walk，RHS 先求值后逐层写入

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「求值-解包赋值」
