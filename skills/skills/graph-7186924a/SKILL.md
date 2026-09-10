---
name: graph-7186924a
description: >-
  标签计数 / 图查询-标签计数 / 图查询——边标签统计计数 / 按边标签统计数量。用户提到这些词时使用本技能。
  场景：对照：图查询——边标签统计计数（标签聚合）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 adj/labels 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["标签计数", "图查询-标签计数", "图查询——边标签统计计数", "按边标签统计数量"]
    when: "参数 adj/labels 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图查询——边标签统计计数（标签聚合）"
---

# 图查询-标签计数（graph-7186924a）

## When to use

任务「标签计数」；对照：图查询——边标签统计计数（标签聚合）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-标签计数」
