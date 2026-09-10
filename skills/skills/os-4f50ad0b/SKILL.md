---
name: os-4f50ad0b
description: >-
  信号处理 / 信号-信号处理 / OS 信 / 发送 / 默认 / 信号。用户提到这些词时使用本技能。
  场景：对照：OS 信号——注册/发送/默认（SIGINT=2 默认终止，SIGUSR=10 默认忽略）。
  【不适用】Not for 以下场景：op 非 {register, send} 时
license: MIT
compatibility: >-
  op ∈ {register, send}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["信号处理", "信号-信号处理", "OS 信", "发送", "默认", "信号"]
    when: "op ∈ {register, send}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {register, send} 时"]
  calibration: "对照：OS 信号——注册/发送/默认（SIGINT=2 默认终止，SIGUSR=10 默认忽略）"
---

# 信号-信号处理（os-4f50ad0b）

## When to use

任务「信号处理」；对照：OS 信号——注册/发送/默认（SIGINT=2 默认终止，SIGUSR=10 默认忽略）。

## 克制条款（不适用条件）

op 非 {register, send} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「信号-信号处理」
