---
name: graph-7becedf0
description: >-
  分布式查询 / 图查询-分布式查询 / 分布式查询——分片并行处 / 各分片并行查 → 合并结。用户提到这些词时使用本技能。
  场景：对照：分布式查询——分片并行处理合并（Map 归约语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 shards/query_fn 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["分布式查询", "图查询-分布式查询", "分布式查询——分片并行处", "各分片并行查 → 合并结"]
    when: "参数 shards/query_fn 合法"
    sub: ["① 调用 sorted；② 调用 query_fn"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：分布式查询——分片并行处理合并（Map 归约语义）"
---

# 图查询-分布式查询（graph-7becedf0）

## When to use

任务「分布式查询」；对照：分布式查询——分片并行处理合并（Map 归约语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-分布式查询」
