---
name: net-56dbd63f
description: >-
  Anycast / 网络-Anycast / Anycast——同。用户提到这些词时使用本技能。
  场景：对照：Anycast——同 IP 多节点就近接入（地理位置最近优先）。
  【不适用】Not for 以下场景：servers 为空/非法时
license: MIT
compatibility: >-
  参数 servers/client_loc 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["Anycast", "网络-Anycast", "Anycast——同"]
    when: "参数 servers/client_loc 合法"
    sub: ["① 调用 min；② 调用 abs"]
    execute: "顺序调用"
    not_applicable: ["servers 为空/非法时"]
  calibration: "对照：Anycast——同 IP 多节点就近接入（地理位置最近优先）"
---

# 网络-Anycast（net-56dbd63f）

## When to use

任务「Anycast」；对照：Anycast——同 IP 多节点就近接入（地理位置最近优先）。

## 克制条款（不适用条件）

servers 为空/非法时

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-Anycast」
