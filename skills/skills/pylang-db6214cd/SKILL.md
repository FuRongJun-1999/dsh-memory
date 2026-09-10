---
name: pylang-db6214cd
description: >-
  性能计时 / 工具-性能计时 / time.perf_co / 耗时计算。用户提到这些词时使用本技能。
  场景：对照：time.perf_counter——耗时计算（毫秒/秒）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 start/end/unit 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["性能计时", "工具-性能计时", "time.perf_co", "耗时计算"]
    when: "参数 start/end/unit 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "性能计时：耗时计算（start/end 时间戳——性能测量）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：time.perf_counter——耗时计算（毫秒/秒）"
---

# 工具-性能计时（pylang-db6214cd）

## When to use

任务「性能计时」；对照：time.perf_counter——耗时计算（毫秒/秒）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

性能计时：耗时计算（start/end 时间戳——性能测量）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-性能计时」
