---
name: pylang-8182681d
description: >-
  滑动均值 / 工具-滑动均值 / 滑动平均——窗口均值平滑 / 窗口内平均。用户提到这些词时使用本技能。
  场景：对照：滑动平均——窗口均值平滑（时间序列）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  seq 为数值序列；window > 0
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["滑动均值", "工具-滑动均值", "滑动平均——窗口均值平滑", "窗口内平均"]
    when: "seq 为数值序列；window > 0"
    sub: ["① 非法窗口/空序列直返空 ② 逐窗口求均值 ③ 两位小数归整"]
    execute: "滑窗求和取平均，round 2 位"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：滑动平均——窗口均值平滑（时间序列）"
---

# 工具-滑动均值（pylang-8182681d）

## When to use

任务「滑动均值」；对照：滑动平均——窗口均值平滑（时间序列）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

滑窗求和取平均，round 2 位

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-滑动均值」
