---
name: pylang-961e9e43
description: >-
  异步协程 / 异步-async await / await / 挂起等待 / 演示 / 运行协程并取回结果。用户提到这些词时使用本技能。
  场景：对照：Python async/await（协程挂起等待，异步 I/O）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  asyncio.run 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["异步协程", "异步-async await", "await", "挂起等待", "演示", "运行协程并取回结果"]
    when: "asyncio.run 可用"
    sub: ["① 调用 fetch"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python async/await（协程挂起等待，异步 I/O）"
---

# 异步-async await（pylang-961e9e43）

## When to use

任务「异步协程」；对照：Python async/await（协程挂起等待，异步 I/O）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「异步-async await」
