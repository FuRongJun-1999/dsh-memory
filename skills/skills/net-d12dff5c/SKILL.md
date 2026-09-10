---
name: net-d12dff5c
description: >-
  Reno拥塞控制 / 网络-Reno拥塞控制 / Reno 拥 / ack 慢。用户提到这些词时使用本技能。
  场景：对照：TCP Reno——慢启动指数/拥塞避免线性/丢包阈值减半快速恢复。
  【不适用】Not for 以下场景：event 非 {ack, loss} 时
license: MIT
compatibility: >-
  event ∈ {ack, loss}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["Reno拥塞控制", "网络-Reno拥塞控制", "Reno 拥", "ack 慢"]
    when: "event ∈ {ack, loss}"
    sub: ["1 event 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["event 非 {ack, loss} 时"]
  calibration: "对照：TCP Reno——慢启动指数/拥塞避免线性/丢包阈值减半快速恢复"
---

# 网络-Reno拥塞控制（net-d12dff5c）

## When to use

任务「Reno拥塞控制」；对照：TCP Reno——慢启动指数/拥塞避免线性/丢包阈值减半快速恢复。

## 克制条款（不适用条件）

event 非 {ack, loss} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-Reno拥塞控制」
