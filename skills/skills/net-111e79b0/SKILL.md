---
name: net-111e79b0
description: >-
  链路加密 / 网络-链路加密 / MACsec 链 / 解密 / encrypt 帧。用户提到这些词时使用本技能。
  场景：对照：MACsec 链路加密——帧级加密/解密（链路层保护）。
  【不适用】Not for 以下场景：op 非 {decrypt, encrypt} 时
license: MIT
compatibility: >-
  op ∈ {decrypt, encrypt}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["链路加密", "网络-链路加密", "MACsec 链", "解密", "encrypt 帧"]
    when: "op ∈ {decrypt, encrypt}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {decrypt, encrypt} 时"]
  calibration: "对照：MACsec 链路加密——帧级加密/解密（链路层保护）"
---

# 网络-链路加密（net-111e79b0）

## When to use

任务「链路加密」；对照：MACsec 链路加密——帧级加密/解密（链路层保护）。

## 克制条款（不适用条件）

op 非 {decrypt, encrypt} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-链路加密」
