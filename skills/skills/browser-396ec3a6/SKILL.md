---
name: browser-396ec3a6
description: >-
  书签管理 / 浏览器-书签管理 / 浏览器书签——增删查列 / 书签 / add 添。用户提到这些词时使用本技能。
  场景：对照：浏览器书签——增删查列（名称排序管理）。
  【不适用】Not for 以下场景：op 非 {add, get, list, remove} 时
license: MIT
compatibility: >-
  op ∈ {add, get, list, remove}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["书签管理", "浏览器-书签管理", "浏览器书签——增删查列", "书签", "add 添"]
    when: "op ∈ {add, get, list, remove}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {add, get, list, remove} 时"]
  calibration: "对照：浏览器书签——增删查列（名称排序管理）"
---

# 浏览器-书签管理（browser-396ec3a6）

## When to use

任务「书签管理」；对照：浏览器书签——增删查列（名称排序管理）。

## 克制条款（不适用条件）

op 非 {add, get, list, remove} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-书签管理」
