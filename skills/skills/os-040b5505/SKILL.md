---
name: os-040b5505
description: >-
  消息队列 / IPC-消息队列 / OS IPC 消 / send 按 / （SysV msg 语 / 消息带类型。用户提到这些词时使用本技能。
  场景：对照：OS IPC 消息队列——SysV msg（类型投递/按类型取最早）。
  【不适用】Not for 以下场景：op 非 {count, recv, send} 时
license: MIT
compatibility: >-
  op ∈ {count, recv, send}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["消息队列", "IPC-消息队列", "OS IPC 消", "send 按", "（SysV msg 语", "消息带类型"]
    when: "op ∈ {count, recv, send}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {count, recv, send} 时"]
  calibration: "对照：OS IPC 消息队列——SysV msg（类型投递/按类型取最早）"
---

# IPC-消息队列（os-040b5505）

## When to use

任务「消息队列」；对照：OS IPC 消息队列——SysV msg（类型投递/按类型取最早）。

## 克制条款（不适用条件）

op 非 {count, recv, send} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「IPC-消息队列」
