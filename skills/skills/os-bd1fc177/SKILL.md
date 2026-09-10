---
name: os-bd1fc177
description: >-
  共享内存 / IPC-共享内存 / OS IPC 共 / write / read / detach / attach 挂 / （多进程映射同一物理页。用户提到这些词时使用本技能。
  场景：对照：OS IPC 共享内存——attach/write/read/detach（物理页共享，引用计数）。
  【不适用】Not for 以下场景：op 非 {attach, detach, read, write} 时
license: MIT
compatibility: >-
  op ∈ {attach, detach, read, write}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["共享内存", "IPC-共享内存", "OS IPC 共", "write", "read", "detach", "attach 挂", "（多进程映射同一物理页"]
    when: "op ∈ {attach, detach, read, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {attach, detach, read, write} 时"]
  calibration: "对照：OS IPC 共享内存——attach/write/read/detach（物理页共享，引用计数）"
---

# IPC-共享内存（os-bd1fc177）

## When to use

任务「共享内存」；对照：OS IPC 共享内存——attach/write/read/detach（物理页共享，引用计数）。

## 克制条款（不适用条件）

op 非 {attach, detach, read, write} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「IPC-共享内存」
