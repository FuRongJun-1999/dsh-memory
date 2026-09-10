---
name: os-f6ae6205
description: >-
  热插拔 / 设备-热插拔 / 设备热插拔——接入 / 移除 / 设备接入/移除。用户提到这些词时使用本技能。
  场景：对照：设备热插拔——接入/移除（运行中动态管理 USB 语义）。
  【不适用】Not for 以下场景：op 非 {list, plug, unplug} 时
license: MIT
compatibility: >-
  op ∈ {list, plug, unplug}；bus.discard 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["热插拔", "设备-热插拔", "设备热插拔——接入", "移除", "设备接入/移除"]
    when: "op ∈ {list, plug, unplug}；bus.discard 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {list, plug, unplug} 时"]
  calibration: "对照：设备热插拔——接入/移除（运行中动态管理 USB 语义）"
---

# 设备-热插拔（os-f6ae6205）

## When to use

任务「热插拔」；对照：设备热插拔——接入/移除（运行中动态管理 USB 语义）。

## 克制条款（不适用条件）

op 非 {list, plug, unplug} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「设备-热插拔」
