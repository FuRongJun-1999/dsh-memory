---
name: pylang-3a659480
description: >-
  超时控制 / 异步-超时控制 / asyncio.wait_for / 用时 ≤ 超时返回结果。用户提到这些词时使用本技能。
  场景：对照：asyncio.wait_for（超时取消/按时完成）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 task_fn/timeout/time_used 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["超时控制", "异步-超时控制", "asyncio.wait_for", "用时 ≤ 超时返回结果"]
    when: "参数 task_fn/timeout/time_used 合法"
    sub: ["① 调用 task_fn"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：asyncio.wait_for（超时取消/按时完成）"
---

# 异步-超时控制（pylang-3a659480）

## When to use

任务「超时控制」；对照：asyncio.wait_for（超时取消/按时完成）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「异步-超时控制」
