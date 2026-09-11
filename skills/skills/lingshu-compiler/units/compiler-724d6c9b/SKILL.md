---
name: compiler-724d6c9b
description: >-
  类型转换 / 编译-类型转换 / 类型系统——转换规则表 / 按规则隐式/显式转换。用户提到这些词时使用本技能。
  场景：对照：类型系统——转换规则表（隐式/显式，无规则拒绝）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 value/from_type/to_type/rules 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["类型转换", "编译-类型转换", "类型系统——转换规则表", "按规则隐式/显式转换"]
    when: "参数 value/from_type/to_type/rules 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "类型转换：按规则隐式/显式转换（数值↔文本——转换规则表）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：类型系统——转换规则表（隐式/显式，无规则拒绝）"
---

# 编译-类型转换（compiler-724d6c9b）

## When to use

任务「类型转换」；对照：类型系统——转换规则表（隐式/显式，无规则拒绝）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

类型转换：按规则隐式/显式转换（数值↔文本——转换规则表）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-类型转换」
