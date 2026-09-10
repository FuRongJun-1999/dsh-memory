---
name: pylang-36d178bc
description: >-
  数据结构 / 数据结构-列表字典 / dict 语 / list/dict 语 / 索引读取/写入。用户提到这些词时使用本技能。
  场景：对照：Python list/dict 语义（索引读写/长度）。
  【不适用】Not for 以下场景：op 非 {get, len, set} 时
license: MIT
compatibility: >-
  op ∈ {get, len, set}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["数据结构", "数据结构-列表字典", "dict 语", "list/dict 语", "索引读取/写入"]
    when: "op ∈ {get, len, set}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {get, len, set} 时"]
  calibration: "对照：Python list/dict 语义（索引读写/长度）"
---

# 数据结构-列表字典（pylang-36d178bc）

## When to use

任务「数据结构」；对照：Python list/dict 语义（索引读写/长度）。

## 克制条款（不适用条件）

op 非 {get, len, set} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「数据结构-列表字典」
