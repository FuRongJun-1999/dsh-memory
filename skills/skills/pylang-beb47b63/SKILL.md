---
name: pylang-beb47b63
description: >-
  任务取消 / 异步-任务取消 / asyncio.Task.cancel / start 启。用户提到这些词时使用本技能。
  场景：对照：asyncio.Task.cancel（运行中可取消，已完成不可）。
  【不适用】Not for 以下场景：op 非 {cancel, check, start} 时
license: MIT
compatibility: >-
  op ∈ {cancel, check, start}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["任务取消", "异步-任务取消", "asyncio.Task.cancel", "start 启"]
    when: "op ∈ {cancel, check, start}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {cancel, check, start} 时"]
  calibration: "对照：asyncio.Task.cancel（运行中可取消，已完成不可）"
---

# 异步-任务取消（pylang-beb47b63）

## When to use

任务「任务取消」；对照：asyncio.Task.cancel（运行中可取消，已完成不可）。

## 克制条款（不适用条件）

op 非 {cancel, check, start} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「异步-任务取消」
