---
name: os-abd48f17
description: >-
  环境变量 / 系统-环境变量 / 环境变量——设置 / 读取 / set 设。用户提到这些词时使用本技能。
  场景：对照：环境变量——设置/读取（默认值）/删除。
  【不适用】Not for 以下场景：op 非 {get, set, unset} 时
license: MIT
compatibility: >-
  op ∈ {get, set, unset}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["环境变量", "系统-环境变量", "环境变量——设置", "读取", "set 设"]
    when: "op ∈ {get, set, unset}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {get, set, unset} 时"]
  calibration: "对照：环境变量——设置/读取（默认值）/删除"
---

# 系统-环境变量（os-abd48f17）

## When to use

任务「环境变量」；对照：环境变量——设置/读取（默认值）/删除。

## 克制条款（不适用条件）

op 非 {get, set, unset} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-环境变量」
