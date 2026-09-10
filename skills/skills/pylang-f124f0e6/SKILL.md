---
name: pylang-f124f0e6
description: >-
  闭包机制 / 求值-闭包 / Python 闭 / 闭包 / 调用 / 返回捕获值与参数之和 / 演示。用户提到这些词时使用本技能。
  场景：对照：Python 闭包语义——独立捕获（a(1)=4、b(1)=11 互不干扰）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 n 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["闭包机制", "求值-闭包", "Python 闭", "闭包", "调用", "返回捕获值与参数之和", "演示"]
    when: "参数 n 合法"
    sub: []
    execute: "闭包：内部函数捕获自由变量 n（定义环境）；调用：返回捕获值与参数之和；演示：不同闭包各自绑定 n（闭包隔离语义）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 闭包语义——独立捕获（a(1)=4、b(1)=11 互不干扰）"
---

# 求值-闭包（pylang-f124f0e6）

## When to use

任务「闭包机制」；对照：Python 闭包语义——独立捕获（a(1)=4、b(1)=11 互不干扰）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

闭包：内部函数捕获自由变量 n（定义环境）；调用：返回捕获值与参数之和；演示：不同闭包各自绑定 n（闭包隔离语义）

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「求值-闭包」
