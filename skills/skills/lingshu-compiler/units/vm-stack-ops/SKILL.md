---
name: vm-stack-ops
description: >-
  栈操作 / VM-栈操作 / VM 栈 / SWAP 交 / DUP 复。用户提到这些词时使用本技能。
  场景：对照：VM 栈指令——DUP 复制/SWAP 交换（栈机操作）。
  【不适用】Not for 以下场景：stack 为空/非法时；op 非 {DUP, SWAP} 时
license: MIT
compatibility: >-
  op ∈ {DUP, SWAP}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["栈操作", "VM-栈操作", "VM 栈", "SWAP 交", "DUP 复"]
    when: "op ∈ {DUP, SWAP}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["stack 为空/非法时；op 非 {DUP, SWAP} 时"]
  calibration: "对照：VM 栈指令——DUP 复制/SWAP 交换（栈机操作）"
---

# VM-栈操作（vm-stack-ops）

## When to use

任务「栈操作」；对照：VM 栈指令——DUP 复制/SWAP 交换（栈机操作）。

## 克制条款（不适用条件）

stack 为空/非法时；op 非 {DUP, SWAP} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-栈操作」
