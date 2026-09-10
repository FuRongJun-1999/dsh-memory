---
name: browser-7008e942
description: >-
  IndexedDB / 存储-IndexedDB / IndexedDB——对 / 对象存储事务。用户提到这些词时使用本技能。
  场景：对照：IndexedDB——对象存储事务（put/get/delete 键值事务）。
  【不适用】Not for 以下场景：op 非 {delete, get, put} 时
license: MIT
compatibility: >-
  op ∈ {delete, get, put}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["IndexedDB", "存储-IndexedDB", "IndexedDB——对", "对象存储事务"]
    when: "op ∈ {delete, get, put}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {delete, get, put} 时"]
  calibration: "对照：IndexedDB——对象存储事务（put/get/delete 键值事务）"
---

# 存储-IndexedDB（browser-7008e942）

## When to use

任务「IndexedDB」；对照：IndexedDB——对象存储事务（put/get/delete 键值事务）。

## 克制条款（不适用条件）

op 非 {delete, get, put} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「存储-IndexedDB」
