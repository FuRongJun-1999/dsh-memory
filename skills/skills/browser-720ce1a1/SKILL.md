---
name: browser-720ce1a1
description: >-
  本地存储 / 存储-本地存储。用户提到这些词时使用本技能。
  场景：对照：浏览器存储——localStorage（setItem/getItem/removeItem/clear）。
  【不适用】Not for 以下场景：op 非 {clear, get, remove, set} 时
license: MIT
compatibility: >-
  op ∈ {set, get, remove, clear}；key/value 按 op 提供
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["本地存储", "存储-本地存储"]
    when: "op ∈ {set, get, remove, clear}；key/value 按 op 提供"
    sub: ["① set 写键值 ② get 读值 ③ remove 删键 ④ clear 清空"]
    execute: "按 op 分派字典操作"
    not_applicable: ["op 非 {clear, get, remove, set} 时"]
  calibration: "对照：浏览器存储——localStorage（setItem/getItem/removeItem/clear）"
---

# 存储-本地存储（browser-720ce1a1）

## When to use

任务「本地存储」；对照：浏览器存储——localStorage（setItem/getItem/removeItem/clear）。

## 克制条款（不适用条件）

op 非 {clear, get, remove, set} 时

## How to execute

按 op 分派字典操作

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「存储-本地存储」
