---
name: pylang-521b1bf8
description: >-
  事件循环 / 异步-事件循环 / Python 事 / 任务队列调度。用户提到这些词时使用本技能。
  场景：对照：Python 事件循环——任务队列依次调度（单线程并发）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  tasks 为可调用任务列表（无参函数）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["事件循环", "异步-事件循环", "Python 事", "任务队列调度"]
    when: "tasks 为可调用任务列表（无参函数）"
    sub: ["① 依序取任务 ② 逐个执行 ③ 收集结果"]
    execute: "for 循环调用并收集返回值"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 事件循环——任务队列依次调度（单线程并发）"
---

# 异步-事件循环（pylang-521b1bf8）

## When to use

任务「事件循环」；对照：Python 事件循环——任务队列依次调度（单线程并发）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

for 循环调用并收集返回值

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「异步-事件循环」
