---
name: graph-1b707621
description: >-
  在线扩容 / 运维-在线扩容 / 数据库在线扩容——分片重 / 键按确定性哈希重分配到新。用户提到这些词时使用本技能。
  场景：对照：数据库在线扩容——分片重平衡（确定性哈希，迁移键计数）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 keys/old_count/new_count 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["在线扩容", "运维-在线扩容", "数据库在线扩容——分片重", "键按确定性哈希重分配到新"]
    when: "参数 keys/old_count/new_count 合法"
    sub: ["① 调用 sum；② 调用 ord；③ 调用 str"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：数据库在线扩容——分片重平衡（确定性哈希，迁移键计数）"
---

# 运维-在线扩容（graph-1b707621）

## When to use

任务「在线扩容」；对照：数据库在线扩容——分片重平衡（确定性哈希，迁移键计数）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「运维-在线扩容」
