---
name: pylang-399b317e
description: >-
  in 成员判断 / 运算符-in 成员判断 / not in 运。用户提到这些词时使用本技能。
  场景：对照：mini_python.py in/not in 运算符（V-P4 第一批 6a5e964，comparison+_compare+VM 三处对齐，CPython in 语义）。
  【不适用】Not for 以下场景：自定义 __contains__ 不在本单元范围（str 为 CPython 子串语义特例）
license: MIT
compatibility: >-
  container 为 str/list/tuple/dict；item 为可比较值
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["in 成员判断", "运算符-in 成员判断", "not in 运"]
    when: "container 为 str/list/tuple/dict；item 为可比较值"
    sub: ["① dict 按键判定；② 序列按相等扫描；③ not in 为取反"]
    execute: "条件分派；循环迭代"
    not_applicable: ["自定义 __contains__ 不在本单元范围（str 为 CPython 子串语义特例）"]
  calibration: "对照：mini_python.py in/not in 运算符（V-P4 第一批 6a5e964，comparison+_compare+VM 三处对齐，CPython in 语义）"
---

# 运算符-in 成员判断（pylang-399b317e）

## When to use

任务「in 成员判断」；对照：mini_python.py in/not in 运算符（V-P4 第一批 6a5e964，comparison+_compare+VM 三处对齐，CPython in 语义）。

## 克制条款（不适用条件）

自定义 __contains__ 不在本单元范围（str 为 CPython 子串语义特例）

## How to execute

条件分派；循环迭代

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「运算符-in 成员判断」
