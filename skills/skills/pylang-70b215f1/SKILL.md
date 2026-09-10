---
name: pylang-70b215f1
description: >-
  类装饰器 / 元编程-类装饰器 / Python 类 / 给类附加标记属性并返回标。用户提到这些词时使用本技能。
  场景：对照：Python 类装饰器——类对象增强（附加标记/注册语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 marker 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["类装饰器", "元编程-类装饰器", "Python 类", "给类附加标记属性并返回标"]
    when: "参数 marker 合法"
    sub: []
    execute: "类装饰器：给类附加标记属性并返回标记（类增强语义）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 类装饰器——类对象增强（附加标记/注册语义）"
---

# 元编程-类装饰器（pylang-70b215f1）

## When to use

任务「类装饰器」；对照：Python 类装饰器——类对象增强（附加标记/注册语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

类装饰器：给类附加标记属性并返回标记（类增强语义）

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「元编程-类装饰器」
