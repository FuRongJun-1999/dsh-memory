---
name: graph-299f4a32
description: >-
  分区分片 / 图存储-分区分片 / 分布式图——哈希分片 / 图分区 / 节点确定性哈希 → 分片。用户提到这些词时使用本技能。
  场景：对照：分布式图——哈希分片（节点分布到分片，水平扩展）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 nodes/shards 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["分区分片", "图存储-分区分片", "分布式图——哈希分片", "图分区", "节点确定性哈希 → 分片"]
    when: "参数 nodes/shards 合法"
    sub: ["① 调用 sorted；② 调用 range；③ 调用 sum"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：分布式图——哈希分片（节点分布到分片，水平扩展）"
---

# 图存储-分区分片（graph-299f4a32）

## When to use

任务「分区分片」；对照：分布式图——哈希分片（节点分布到分片，水平扩展）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图存储-分区分片」
