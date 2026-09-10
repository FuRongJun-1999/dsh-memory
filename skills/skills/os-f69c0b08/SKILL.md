---
name: os-f69c0b08
description: >-
  守护进程 / 系统-守护进程 / OS 守 / 启动→运行→停止。用户提到这些词时使用本技能。
  场景：对照：OS 守护进程——生命周期（start/stop/status 状态机）。
  【不适用】Not for 以下场景：op 非 {start, status, stop} 时（隐式盲区：返回默认值 unknown = 未知行为——不适用）
license: MIT
compatibility: >-
  op ∈ {start, status, stop}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["守护进程", "系统-守护进程", "OS 守", "启动→运行→停止"]
    when: "op ∈ {start, status, stop}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {start, status, stop} 时（隐式盲区：返回默认值 unknown = 未知行为——不适用）"]
  calibration: "对照：OS 守护进程——生命周期（start/stop/status 状态机）"
---

# 系统-守护进程（os-f69c0b08）

## When to use

任务「守护进程」；对照：OS 守护进程——生命周期（start/stop/status 状态机）。

## 克制条款（不适用条件）

op 非 {start, status, stop} 时（隐式盲区：返回默认值 unknown = 未知行为——不适用）

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-守护进程」
