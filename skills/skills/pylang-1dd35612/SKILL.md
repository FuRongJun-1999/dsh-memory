---
name: pylang-1dd35612
description: >-
  字节编解码 / 工具-字节编解码 / bytes——UTF-8 / 解码 / encode 文。用户提到这些词时使用本技能。
  场景：对照：bytes——UTF-8 编码/解码（文本↔字节）。
  【不适用】Not for 以下场景：op 非 {decode, encode} 时
license: MIT
compatibility: >-
  op ∈ {decode, encode}；data.encode 可用；data.decode 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字节编解码", "工具-字节编解码", "bytes——UTF-8", "解码", "encode 文"]
    when: "op ∈ {decode, encode}；data.encode 可用；data.decode 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {decode, encode} 时"]
  calibration: "对照：bytes——UTF-8 编码/解码（文本↔字节）"
---

# 工具-字节编解码（pylang-1dd35612）

## When to use

任务「字节编解码」；对照：bytes——UTF-8 编码/解码（文本↔字节）。

## 克制条款（不适用条件）

op 非 {decode, encode} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-字节编解码」
