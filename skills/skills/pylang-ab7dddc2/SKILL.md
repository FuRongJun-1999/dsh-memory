---
name: pylang-ab7dddc2
description: >-
  循环轮转 / 工具-循环轮转 / deque.rotate。用户提到这些词时使用本技能。
  场景：对照：deque.rotate——循环轮转（右移 k 位）。
  【不适用】Not for 以下场景：items 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）
license: MIT
compatibility: >-
  参数 items/k 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["循环轮转", "工具-循环轮转", "deque.rotate"]
    when: "参数 items/k 合法"
    sub: ["① 调用 len；② 调用 list"]
    execute: "顺序调用"
    not_applicable: ["items 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）"]
  calibration: "对照：deque.rotate——循环轮转（右移 k 位）"
---

# 工具-循环轮转（pylang-ab7dddc2）

## When to use

任务「循环轮转」；对照：deque.rotate——循环轮转（右移 k 位）。

## 克制条款（不适用条件）

items 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）

## How to execute

顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-循环轮转」
