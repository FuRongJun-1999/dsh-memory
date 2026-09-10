---
name: os-34ad4b62
description: >-
  进程状态 / 进程-状态机 / 进程状态机 / 事件序列 → 最终状态。用户提到这些词时使用本技能。
  场景：对照：OS 进程状态机——就绪/运行/阻塞/终止 事件驱动转换。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  transitions 为事件序列（按状态转移表合法）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["进程状态", "进程-状态机", "进程状态机", "事件序列 → 最终状态"]
    when: "transitions 为事件序列（按状态转移表合法）"
    sub: ["① 初始就绪 ② 逐事件迁移 ③ 返回终态"]
    execute: "状态转移表逐事件推进"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 进程状态机——就绪/运行/阻塞/终止 事件驱动转换"
---

# 进程-状态机（os-34ad4b62）

## When to use

任务「进程状态」；对照：OS 进程状态机——就绪/运行/阻塞/终止 事件驱动转换。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

状态转移表逐事件推进

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「进程-状态机」
