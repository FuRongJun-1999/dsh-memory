---
name: pylang-642cd625
description: >-
  排序键控 / 工具-排序键控。用户提到这些词时使用本技能。
  场景：对照：Python sorted(key=)（按键函数稳定排序）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  items 可迭代；key_fn 为取键函数（可调用）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["排序键控", "工具-排序键控"]
    when: "items 可迭代；key_fn 为取键函数（可调用）"
    sub: ["① 对每项取键 ② 按键稳定排序"]
    execute: "sorted(items, key=key_fn)（稳定排序语义）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python sorted(key=)（按键函数稳定排序）"
---

# 工具-排序键控（pylang-642cd625）

## When to use

任务「排序键控」；对照：Python sorted(key=)（按键函数稳定排序）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

sorted(items, key=key_fn)（稳定排序语义）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-排序键控」
