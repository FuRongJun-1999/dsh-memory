---
name: compiler-d974e5d3
description: >-
  函数签名 / 语法-函数签名 / 语法——函数签名参数列表 / 函数签名解析 / 参数列表（逗号分隔。用户提到这些词时使用本技能。
  场景：对照：语法——函数签名参数列表（默认值剥离）。
  【不适用】Not for 以下场景：params_str 为空/非法时
license: MIT
compatibility: >-
  params_str.strip 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["函数签名", "语法-函数签名", "语法——函数签名参数列表", "函数签名解析", "参数列表（逗号分隔"]
    when: "params_str.strip 可用"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "函数签名解析：参数列表（逗号分隔，默认值剥离）→ 参数名列表"
    not_applicable: ["params_str 为空/非法时"]
  calibration: "对照：语法——函数签名参数列表（默认值剥离）"
---

# 语法-函数签名（compiler-d974e5d3）

## When to use

任务「函数签名」；对照：语法——函数签名参数列表（默认值剥离）。

## 克制条款（不适用条件）

params_str 为空/非法时

## How to execute

函数签名解析：参数列表（逗号分隔，默认值剥离）→ 参数名列表

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「语法-函数签名」
