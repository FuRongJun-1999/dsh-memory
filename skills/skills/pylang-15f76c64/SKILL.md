---
name: pylang-15f76c64
description: >-
  计数器 / 工具-计数器 / collections.Counter / 元素频次统计。用户提到这些词时使用本技能。
  场景：对照：collections.Counter（元素频次统计）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  items 为可迭代对象
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["计数器", "工具-计数器", "collections.Counter", "元素频次统计"]
    when: "items 为可迭代对象"
    sub: ["① 逐元素计数 ② 缺失键初始化"]
    execute: "freq.get(x, 0) + 1 累积"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：collections.Counter（元素频次统计）"
---

# 工具-计数器（pylang-15f76c64）

## When to use

任务「计数器」；对照：collections.Counter（元素频次统计）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

freq.get(x, 0) + 1 累积

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-计数器」
