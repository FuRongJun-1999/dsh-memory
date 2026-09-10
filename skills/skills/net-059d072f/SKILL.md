---
name: net-059d072f
description: >-
  TCP握手 / 网络-TCP握手 / TCP 三。用户提到这些词时使用本技能。
  场景：对照：网络 TCP——三次握手状态机（CLOSED→SYN_SENT→ESTABLISHED）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  states 为事件序列（SYN/SYN-ACK/ACK 等）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["TCP握手", "网络-TCP握手", "TCP 三"]
    when: "states 为事件序列（SYN/SYN-ACK/ACK 等）"
    sub: ["① 状态机迁移 ② 非法事件忽略 ③ 到达 ESTABLISHED 判定"]
    execute: "状态转移表逐事件推进"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：网络 TCP——三次握手状态机（CLOSED→SYN_SENT→ESTABLISHED）"
---

# 网络-TCP握手（net-059d072f）

## When to use

任务「TCP握手」；对照：网络 TCP——三次握手状态机（CLOSED→SYN_SENT→ESTABLISHED）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

状态转移表逐事件推进

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-TCP握手」
