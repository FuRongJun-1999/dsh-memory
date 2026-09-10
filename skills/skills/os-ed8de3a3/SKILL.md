---
name: os-ed8de3a3
description: >-
  配置管理 / 系统-配置管理 / 系统配置——键值设置 / 读取 / set 设。用户提到这些词时使用本技能。
  场景：对照：系统配置——键值设置/读取（默认值兜底）。
  【不适用】Not for 以下场景：op 非 {get, list, set} 时
license: MIT
compatibility: >-
  op ∈ {get, list, set}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["配置管理", "系统-配置管理", "系统配置——键值设置", "读取", "set 设"]
    when: "op ∈ {get, list, set}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {get, list, set} 时"]
  calibration: "对照：系统配置——键值设置/读取（默认值兜底）"
---

# 系统-配置管理（os-ed8de3a3）

## When to use

任务「配置管理」；对照：系统配置——键值设置/读取（默认值兜底）。

## 克制条款（不适用条件）

op 非 {get, list, set} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-配置管理」
