---
name: net-3bbc6afb
description: >-
  ARP解析 / 网络-ARP解析 / ARP 协 / ARP / lookup IP→MA。用户提到这些词时使用本技能。
  场景：对照：ARP 协议——IP→MAC 地址解析（查询/学习/清空缓存）。
  【不适用】Not for 以下场景：op 非 {flush, learn, lookup} 时
license: MIT
compatibility: >-
  op ∈ {flush, learn, lookup}；table.clear 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["ARP解析", "网络-ARP解析", "ARP 协", "ARP", "lookup IP→MA"]
    when: "op ∈ {flush, learn, lookup}；table.clear 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {flush, learn, lookup} 时"]
  calibration: "对照：ARP 协议——IP→MAC 地址解析（查询/学习/清空缓存）"
---

# 网络-ARP解析（net-3bbc6afb）

## When to use

任务「ARP解析」；对照：ARP 协议——IP→MAC 地址解析（查询/学习/清空缓存）。

## 克制条款（不适用条件）

op 非 {flush, learn, lookup} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-ARP解析」
