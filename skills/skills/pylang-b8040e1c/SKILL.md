---
name: pylang-b8040e1c
description: >-
  日期时间 / 工具-日期时间 / 日期加减天数。用户提到这些词时使用本技能。
  场景：对照：CPython datetime（日期加减进位；简化 30 天月模型——1/1+30=2/1 按模型校准）。
  【不适用】Not for 以下场景：month 越界（Gt）时；month 越界（Lt）时（隐式盲区：返回默认值 (-1, 12, 30) = 未知行为——不适用）
license: MIT
compatibility: >-
  参数 year/month/day/days 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["日期时间", "工具-日期时间", "日期加减天数"]
    when: "参数 year/month/day/days 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["month 越界（Gt）时；month 越界（Lt）时（隐式盲区：返回默认值 (-1, 12, 30) = 未知行为——不适用）"]
  calibration: "对照：CPython datetime（日期加减进位；简化 30 天月模型——1/1+30=2/1 按模型校准）"
---

# 工具-日期时间（pylang-b8040e1c）

## When to use

任务「日期时间」；对照：CPython datetime（日期加减进位；简化 30 天月模型——1/1+30=2/1 按模型校准）。

## 克制条款（不适用条件）

month 越界（Gt）时；month 越界（Lt）时（隐式盲区：返回默认值 (-1, 12, 30) = 未知行为——不适用）

## How to execute

循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-日期时间」
