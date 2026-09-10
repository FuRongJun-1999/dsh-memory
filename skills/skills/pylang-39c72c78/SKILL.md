---
name: pylang-39c72c78
description: >-
  数值统计 / 工具-数值统计 / min / max / mean 平。用户提到这些词时使用本技能。
  场景：对照：Python statistics——mean/min/max（统计族）。
  【不适用】Not for 以下场景：nums 为空/非法时；op 非 {max, mean, min} 时
license: MIT
compatibility: >-
  op ∈ {max, mean, min}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["数值统计", "工具-数值统计", "min", "max", "mean 平"]
    when: "op ∈ {max, mean, min}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["nums 为空/非法时；op 非 {max, mean, min} 时"]
  calibration: "对照：Python statistics——mean/min/max（统计族）"
---

# 工具-数值统计（pylang-39c72c78）

## When to use

任务「数值统计」；对照：Python statistics——mean/min/max（统计族）。

## 克制条款（不适用条件）

nums 为空/非法时；op 非 {max, mean, min} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-数值统计」
