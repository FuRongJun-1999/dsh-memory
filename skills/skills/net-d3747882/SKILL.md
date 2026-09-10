---
name: net-d3747882
description: >-
  流式传输 / 网络-流式传输 / HTTP 流 / 流式分块传输 / 数据切块 + 长度前缀。用户提到这些词时使用本技能。
  场景：对照：HTTP 流式传输——chunked 编码（分块+长度前缀+终止块）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  chunk.decode 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["流式传输", "网络-流式传输", "HTTP 流", "流式分块传输", "数据切块 + 长度前缀"]
    when: "chunk.decode 可用"
    sub: ["① 调用 range；② 调用 len"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：HTTP 流式传输——chunked 编码（分块+长度前缀+终止块）"
---

# 网络-流式传输（net-d3747882）

## When to use

任务「流式传输」；对照：HTTP 流式传输——chunked 编码（分块+长度前缀+终止块）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-流式传输」
