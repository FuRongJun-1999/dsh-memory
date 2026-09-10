---
name: net-6f96c190
description: >-
  QUIC握手 / 网络-QUIC握手 / QUIC——0-RTT  / QUIC / 0-RTT 快。用户提到这些词时使用本技能。
  场景：对照：QUIC——0-RTT 快速握手（缓存会话票据，二次连接免往返）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 cache/client 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["QUIC握手", "网络-QUIC握手", "QUIC——0-RTT ", "QUIC", "0-RTT 快"]
    when: "参数 cache/client 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "QUIC：0-RTT 快速握手（缓存会话 → 首次往返即发数据）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：QUIC——0-RTT 快速握手（缓存会话票据，二次连接免往返）"
---

# 网络-QUIC握手（net-6f96c190）

## When to use

任务「QUIC握手」；对照：QUIC——0-RTT 快速握手（缓存会话票据，二次连接免往返）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

QUIC：0-RTT 快速握手（缓存会话 → 首次往返即发数据）

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-QUIC握手」
