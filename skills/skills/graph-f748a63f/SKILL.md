---
name: graph-f748a63f
description: >-
  一致性哈希 / 图分布式-一致性哈希 / 分布式哈希环——一致性哈 / add 节。用户提到这些词时使用本技能。
  场景：对照：分布式哈希环——一致性哈希（键定位，最小迁移）。
  【不适用】Not for 以下场景：ring 为空/非法时；op 非 {add, locate} 时
license: MIT
compatibility: >-
  op ∈ {add, locate}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["一致性哈希", "图分布式-一致性哈希", "分布式哈希环——一致性哈", "add 节"]
    when: "op ∈ {add, locate}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["ring 为空/非法时；op 非 {add, locate} 时"]
  calibration: "对照：分布式哈希环——一致性哈希（键定位，最小迁移）"
---

# 图分布式-一致性哈希（graph-f748a63f）

## When to use

任务「一致性哈希」；对照：分布式哈希环——一致性哈希（键定位，最小迁移）。

## 克制条款（不适用条件）

ring 为空/非法时；op 非 {add, locate} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图分布式-一致性哈希」
