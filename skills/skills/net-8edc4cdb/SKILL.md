---
name: net-8edc4cdb
description: >-
  分块传输 / 网络-分块传输 / HTTP 分 / encode 分。用户提到这些词时使用本技能。
  场景：对照：HTTP 分块传输——每块十六进制长度（chunked 编码）。
  【不适用】Not for 以下场景：op 非 {decode, encode} 时
license: MIT
compatibility: >-
  op ∈ {decode, encode}；data.index 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["分块传输", "网络-分块传输", "HTTP 分", "encode 分"]
    when: "op ∈ {decode, encode}；data.index 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {decode, encode} 时"]
  calibration: "对照：HTTP 分块传输——每块十六进制长度（chunked 编码）"
---

# 网络-分块传输（net-8edc4cdb）

## When to use

任务「分块传输」；对照：HTTP 分块传输——每块十六进制长度（chunked 编码）。

## 克制条款（不适用条件）

op 非 {decode, encode} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-分块传输」
