---
name: net-c74a1b5d
description: >-
  会话亲和 / 网络-会话亲和 / 负载均衡——会话亲和 / bind 绑。用户提到这些词时使用本技能。
  场景：对照：负载均衡——会话亲和（sticky session 同会话同后端）。
  【不适用】Not for 以下场景：op 非 {bind, route} 时
license: MIT
compatibility: >-
  op ∈ {bind, route}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["会话亲和", "网络-会话亲和", "负载均衡——会话亲和", "bind 绑"]
    when: "op ∈ {bind, route}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {bind, route} 时"]
  calibration: "对照：负载均衡——会话亲和（sticky session 同会话同后端）"
---

# 网络-会话亲和（net-c74a1b5d）

## When to use

任务「会话亲和」；对照：负载均衡——会话亲和（sticky session 同会话同后端）。

## 克制条款（不适用条件）

op 非 {bind, route} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-会话亲和」
