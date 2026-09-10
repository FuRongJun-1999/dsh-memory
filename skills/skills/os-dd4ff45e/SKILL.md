---
name: os-dd4ff45e
description: >-
  文件版本 / 文件-文件版本 / save 存。用户提到这些词时使用本技能。
  场景：对照：文件版本——版本历史保存/列表/取最新。
  【不适用】Not for 以下场景：op 非 {get, list, save} 时
license: MIT
compatibility: >-
  op ∈ {get, list, save}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件版本", "文件-文件版本", "save 存"]
    when: "op ∈ {get, list, save}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {get, list, save} 时"]
  calibration: "对照：文件版本——版本历史保存/列表/取最新"
---

# 文件-文件版本（os-dd4ff45e）

## When to use

任务「文件版本」；对照：文件版本——版本历史保存/列表/取最新。

## 克制条款（不适用条件）

op 非 {get, list, save} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-文件版本」
