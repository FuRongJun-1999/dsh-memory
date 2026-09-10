---
name: pylang-d616eb28
description: >-
  捕获更新 / 闭包-捕获更新 / Python nonlo / nonlocal 语 / 闭包修改捕获变量 / 递增 / 修改外层捕获变量并返回新 / 演示。用户提到这些词时使用本技能。
  场景：对照：Python nonlocal——闭包内修改捕获变量（连续调用递增）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 输入 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["捕获更新", "闭包-捕获更新", "Python nonlo", "nonlocal 语", "闭包修改捕获变量", "递增", "修改外层捕获变量并返回新", "演示"]
    when: "参数 输入 合法"
    sub: []
    execute: "nonlocal 语义：闭包修改捕获变量（非只读）；递增：修改外层捕获变量并返回新值；演示：连续调用计数器（捕获变量持续累积）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python nonlocal——闭包内修改捕获变量（连续调用递增）"
---

# 闭包-捕获更新（pylang-d616eb28）

## When to use

任务「捕获更新」；对照：Python nonlocal——闭包内修改捕获变量（连续调用递增）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

nonlocal 语义：闭包修改捕获变量（非只读）；递增：修改外层捕获变量并返回新值；演示：连续调用计数器（捕获变量持续累积）

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「闭包-捕获更新」
