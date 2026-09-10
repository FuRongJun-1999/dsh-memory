---
name: net-703559d0
description: >-
  加密握手 / 网络-加密握手 / TLS 握 / 加密传输 / TLS 简 / 防御式。用户提到这些词时使用本技能。
  场景：对照：TLS 握手——问候→密钥交换→完成（会话密钥协商）。
  【不适用】Not for 以下场景：op 非 {exchange, finish, hello} 时
license: MIT
compatibility: >-
  op ∈ {exchange, finish, hello}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["加密握手", "网络-加密握手", "TLS 握", "加密传输", "TLS 简", "防御式"]
    when: "op ∈ {exchange, finish, hello}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {exchange, finish, hello} 时"]
  calibration: "对照：TLS 握手——问候→密钥交换→完成（会话密钥协商）"
---

# 网络-加密握手（net-703559d0）

## When to use

任务「加密握手」；对照：TLS 握手——问候→密钥交换→完成（会话密钥协商）。

## 克制条款（不适用条件）

op 非 {exchange, finish, hello} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-加密握手」
