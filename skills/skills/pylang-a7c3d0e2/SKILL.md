---
name: pylang-a7c3d0e2
description: >-
  字符串替换 / 工具-字符串替换。用户提到这些词时使用本技能。
  场景：对照：Python str.replace（全部/限次替换）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  text 为字符串；old/new 为替换对；count 为次数或 None（全部）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字符串替换", "工具-字符串替换"]
    when: "text 为字符串；old/new 为替换对；count 为次数或 None（全部）"
    sub: ["① 全部替换 ② 限量替换"]
    execute: "count 给定 → text.replace(old, new, count)，否则全替"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python str.replace（全部/限次替换）"
---

# 工具-字符串替换（pylang-a7c3d0e2）

## When to use

任务「字符串替换」；对照：Python str.replace（全部/限次替换）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

count 给定 → text.replace(old, new, count)，否则全替

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-字符串替换」
