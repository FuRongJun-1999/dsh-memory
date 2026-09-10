---
name: os-0e87e997
description: >-
  磨损均衡 / 存储-磨损均衡 / OS 存 / 写块记录写入次数。用户提到这些词时使用本技能。
  场景：对照：OS 存储——磨损均衡（写入次数记录，选最少磨损块）。
  【不适用】Not for 以下场景：blocks 为空/非法时；op 非 {pick, write} 时
license: MIT
compatibility: >-
  op ∈ {pick, write}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["磨损均衡", "存储-磨损均衡", "OS 存", "写块记录写入次数"]
    when: "op ∈ {pick, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["blocks 为空/非法时；op 非 {pick, write} 时"]
  calibration: "对照：OS 存储——磨损均衡（写入次数记录，选最少磨损块）"
---

# 存储-磨损均衡（os-0e87e997）

## When to use

任务「磨损均衡」；对照：OS 存储——磨损均衡（写入次数记录，选最少磨损块）。

## 克制条款（不适用条件）

blocks 为空/非法时；op 非 {pick, write} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「存储-磨损均衡」
