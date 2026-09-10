---
name: net-a74da501
description: >-
  端口转发 / 网络-端口转发 / NAT 端 / add 映。用户提到这些词时使用本技能。
  场景：对照：NAT 端口转发——外网端口→内网主机端口映射（增删查）。
  【不适用】Not for 以下场景：op 非 {add, lookup, remove} 时
license: MIT
compatibility: >-
  op ∈ {add, lookup, remove}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["端口转发", "网络-端口转发", "NAT 端", "add 映"]
    when: "op ∈ {add, lookup, remove}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {add, lookup, remove} 时"]
  calibration: "对照：NAT 端口转发——外网端口→内网主机端口映射（增删查）"
---

# 网络-端口转发（net-a74da501）

## When to use

任务「端口转发」；对照：NAT 端口转发——外网端口→内网主机端口映射（增删查）。

## 克制条款（不适用条件）

op 非 {add, lookup, remove} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-端口转发」
