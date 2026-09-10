---
name: pylang-4af9140e
description: >-
  完整程序 / 程序-完整执行 / 完整程序执行（组装 / 简化管线。用户提到这些词时使用本技能。
  场景：对照：mini_python.py run_program（词法→语法→语句执行全链路；组装白箱生成单元）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  src.splitlines 可用；raw.strip 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["完整程序", "程序-完整执行", "完整程序执行（组装", "简化管线"]
    when: "src.splitlines 可用；raw.strip 可用"
    sub: ["① 调用 fn_run_stmts；② 调用 int"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：mini_python.py run_program（词法→语法→语句执行全链路；组装白箱生成单元）"
---

# 程序-完整执行（pylang-4af9140e）

## When to use

任务「完整程序」；对照：mini_python.py run_program（词法→语法→语句执行全链路；组装白箱生成单元）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「程序-完整执行」
