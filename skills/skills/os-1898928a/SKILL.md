---
name: os-1898928a
description: >-
  系统监控 / 系统-监控指标 / OS 系 / CPU/内。用户提到这些词时使用本技能。
  场景：对照：OS 系统监控——CPU 使用率采样统计（平均/峰值）。
  【不适用】Not for 以下场景：usage_samples 为空/非法时（隐式盲区：返回默认值 {'avg': 0.0, 'peak': 0.0} = 未知行为——不适用）
license: MIT
compatibility: >-
  参数 usage_samples 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["系统监控", "系统-监控指标", "OS 系", "CPU/内"]
    when: "参数 usage_samples 合法"
    sub: ["① 调用 round；② 调用 max；③ 调用 sum"]
    execute: "顺序调用"
    not_applicable: ["usage_samples 为空/非法时（隐式盲区：返回默认值 {'avg': 0.0, 'peak': 0.0} = 未知行为——不适用）"]
  calibration: "对照：OS 系统监控——CPU 使用率采样统计（平均/峰值）"
---

# 系统-监控指标（os-1898928a）

## When to use

任务「系统监控」；对照：OS 系统监控——CPU 使用率采样统计（平均/峰值）。

## 克制条款（不适用条件）

usage_samples 为空/非法时（隐式盲区：返回默认值 {'avg': 0.0, 'peak': 0.0} = 未知行为——不适用）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-监控指标」
