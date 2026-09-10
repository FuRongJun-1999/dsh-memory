---
name: net-3dcb84d3
description: >-
  连接池 / 网络-连接池 / 网络连接池——获取复用 / 归还 / 获取复用/归还/新建（上。用户提到这些词时使用本技能。
  场景：对照：网络连接池——获取复用/归还（空闲复用，避免重复建连）。
  【不适用】Not for 以下场景：op 非 {get, put} 时
license: MIT
compatibility: >-
  op ∈ {get, put}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["连接池", "网络-连接池", "网络连接池——获取复用", "归还", "获取复用/归还/新建（上"]
    when: "op ∈ {get, put}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {get, put} 时"]
  calibration: "对照：网络连接池——获取复用/归还（空闲复用，避免重复建连）"
---

# 网络-连接池（net-3dcb84d3）

## When to use

任务「连接池」；对照：网络连接池——获取复用/归还（空闲复用，避免重复建连）。

## 克制条款（不适用条件）

op 非 {get, put} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-连接池」
