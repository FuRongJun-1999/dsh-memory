---
name: os-de0556c5
description: >-
  邮箱 / IPC-邮箱 / OS IPC 邮 / put 投 / （异步消息槽 / 收发进程解耦）。用户提到这些词时使用本技能。
  场景：对照：OS IPC 邮箱——异步消息槽（put 投递/get FIFO 取，进程解耦）。
  【不适用】Not for 以下场景：op 非 {get, put} 时
license: MIT
compatibility: >-
  op ∈ {get, put}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["邮箱", "IPC-邮箱", "OS IPC 邮", "put 投", "（异步消息槽", "收发进程解耦）"]
    when: "op ∈ {get, put}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {get, put} 时"]
  calibration: "对照：OS IPC 邮箱——异步消息槽（put 投递/get FIFO 取，进程解耦）"
---

# IPC-邮箱（os-de0556c5）

## When to use

任务「邮箱」；对照：OS IPC 邮箱——异步消息槽（put 投递/get FIFO 取，进程解耦）。

## 克制条款（不适用条件）

op 非 {get, put} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「IPC-邮箱」
