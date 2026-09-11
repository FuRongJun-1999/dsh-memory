---
name: compiler-94b8d72d
description: >-
  闭包捕获分析 / 编译-闭包捕获分析 / 闭包自由变量分析——引用 / 函数体引用 且 非参数  / （词法作用域。用户提到这些词时使用本技能。
  场景：对照：闭包自由变量分析——引用∩外层-参数（CPython cell 捕获语义·词法作用域）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 func_refs/params/outer_vars 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["闭包捕获分析", "编译-闭包捕获分析", "闭包自由变量分析——引用", "函数体引用 且 非参数 ", "（词法作用域"]
    when: "参数 func_refs/params/outer_vars 合法"
    sub: []
    execute: "闭包捕获分析：函数体引用 且 非参数 且 外层可见 = 自由变量；（词法作用域：内层函数用到的外层名字 → 需捕获为 cell；保持源码引用顺序）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：闭包自由变量分析——引用∩外层-参数（CPython cell 捕获语义·词法作用域）"
---

# 编译-闭包捕获分析（compiler-94b8d72d）

## When to use

任务「闭包捕获分析」；对照：闭包自由变量分析——引用∩外层-参数（CPython cell 捕获语义·词法作用域）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

闭包捕获分析：函数体引用 且 非参数 且 外层可见 = 自由变量；（词法作用域：内层函数用到的外层名字 → 需捕获为 cell；保持源码引用顺序）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-闭包捕获分析」
