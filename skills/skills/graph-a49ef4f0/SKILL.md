---
name: graph-a49ef4f0
description: >-
  慢查询定位 / 运维-慢查询定位 / 数据库慢查询——耗时超阈 / 执行计划耗时 > 阈值 。用户提到这些词时使用本技能。
  场景：对照：数据库慢查询——耗时超阈值定位（降序，等于阈值不算）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  slow.sort 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["慢查询定位", "运维-慢查询定位", "数据库慢查询——耗时超阈", "执行计划耗时 > 阈值 "]
    when: "slow.sort 可用"
    sub: []
    execute: "慢查询定位：执行计划耗时 > 阈值 → 慢查询列表（耗时降序）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：数据库慢查询——耗时超阈值定位（降序，等于阈值不算）"
---

# 运维-慢查询定位（graph-a49ef4f0）

## When to use

任务「慢查询定位」；对照：数据库慢查询——耗时超阈值定位（降序，等于阈值不算）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

慢查询定位：执行计划耗时 > 阈值 → 慢查询列表（耗时降序）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「运维-慢查询定位」
