---
name: pylang-afaf67c0
description: >-
  自定义异常 / 异常-自定义异常 / Python 自 / 异常类层级（父→子继承。用户提到这些词时使用本技能。
  场景：对照：Python 自定义异常——类层级继承（子类捕获父类）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 names/child/ancestor 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["自定义异常", "异常-自定义异常", "Python 自", "异常类层级（父→子继承"]
    when: "参数 names/child/ancestor 合法"
    sub: ["① 调用 dict；② 调用 set"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 自定义异常——类层级继承（子类捕获父类）"
---

# 异常-自定义异常（pylang-afaf67c0）

## When to use

任务「自定义异常」；对照：Python 自定义异常——类层级继承（子类捕获父类）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「异常-自定义异常」
