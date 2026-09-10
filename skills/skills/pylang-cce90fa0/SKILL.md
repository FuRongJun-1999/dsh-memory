---
name: pylang-cce90fa0
description: >-
  生成器 / 生成器-yield / Python 生 / yield 暂 / 演示 / 收集生成器全部产出。用户提到这些词时使用本技能。
  场景：对照：Python 生成器——yield 逐个产出（list(gen_count(3))=[0,1,2] 惰性求值）。
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
    trigger_words: ["生成器", "生成器-yield", "Python 生", "yield 暂", "演示", "收集生成器全部产出"]
    when: "参数 n 合法"
    sub: []
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 生成器——yield 逐个产出（list(gen_count(3))=[0,1,2] 惰性求值）"
---

# 生成器-yield（pylang-cce90fa0）

## When to use

任务「生成器」；对照：Python 生成器——yield 逐个产出（list(gen_count(3))=[0,1,2] 惰性求值）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「生成器-yield」
