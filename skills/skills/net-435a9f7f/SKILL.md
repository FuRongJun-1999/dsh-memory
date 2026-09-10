---
name: net-435a9f7f
description: >-
  压缩传输 / 网络-压缩传输 / compress 行。用户提到这些词时使用本技能。
  场景：对照：压缩传输——RLE 行程编码（重复段压缩/还原）。
  【不适用】Not for 以下场景：mode 非 {compress, decompress} 时
license: MIT
compatibility: >-
  mode ∈ {compress, decompress}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["压缩传输", "网络-压缩传输", "compress 行"]
    when: "mode ∈ {compress, decompress}"
    sub: ["1 mode 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["mode 非 {compress, decompress} 时"]
  calibration: "对照：压缩传输——RLE 行程编码（重复段压缩/还原）"
---

# 网络-压缩传输（net-435a9f7f）

## When to use

任务「压缩传输」；对照：压缩传输——RLE 行程编码（重复段压缩/还原）。

## 克制条款（不适用条件）

mode 非 {compress, decompress} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-压缩传输」
