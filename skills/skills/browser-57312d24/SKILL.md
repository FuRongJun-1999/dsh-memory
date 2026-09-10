---
name: browser-57312d24
description: >-
  离线队列 / 浏览器-离线队列 / 离线优先——离线请求队列 / enqueue 离。用户提到这些词时使用本技能。
  场景：对照：离线优先——离线请求队列（上线重发）。
  【不适用】Not for 以下场景：op 非 {count, enqueue, flush} 时
license: MIT
compatibility: >-
  op ∈ {count, enqueue, flush}；queue.clear 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["离线队列", "浏览器-离线队列", "离线优先——离线请求队列", "enqueue 离"]
    when: "op ∈ {count, enqueue, flush}；queue.clear 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {count, enqueue, flush} 时"]
  calibration: "对照：离线优先——离线请求队列（上线重发）"
---

# 浏览器-离线队列（browser-57312d24）

## When to use

任务「离线队列」；对照：离线优先——离线请求队列（上线重发）。

## 克制条款（不适用条件）

op 非 {count, enqueue, flush} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-离线队列」
