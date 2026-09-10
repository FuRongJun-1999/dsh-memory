---
name: net-7998097c
description: >-
  延迟测量 / 网络-延迟测量 / RTT 测 / 延迟样本 → 平均/最小。用户提到这些词时使用本技能。
  场景：对照：网络监控——RTT 延迟测量（平均/最小/最大）。
  【不适用】Not for 以下场景：samples 为空/非法时（隐式盲区：返回默认值 {'avg': 0.0, 'min': 0, 'max':  = 未知行为——不适用）
license: MIT
compatibility: >-
  参数 samples 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["延迟测量", "网络-延迟测量", "RTT 测", "延迟样本 → 平均/最小"]
    when: "参数 samples 合法"
    sub: ["① 调用 round；② 调用 min；③ 调用 max"]
    execute: "顺序调用"
    not_applicable: ["samples 为空/非法时（隐式盲区：返回默认值 {'avg': 0.0, 'min': 0, 'max':  = 未知行为——不适用）"]
  calibration: "对照：网络监控——RTT 延迟测量（平均/最小/最大）"
---

# 网络-延迟测量（net-7998097c）

## When to use

任务「延迟测量」；对照：网络监控——RTT 延迟测量（平均/最小/最大）。

## 克制条款（不适用条件）

samples 为空/非法时（隐式盲区：返回默认值 {'avg': 0.0, 'min': 0, 'max':  = 未知行为——不适用）

## How to execute

顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-延迟测量」
