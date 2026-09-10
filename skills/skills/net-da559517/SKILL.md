---
name: net-da559517
description: >-
  MAC学习 / 网络-MAC学习 / MAC 学。用户提到这些词时使用本技能。
  场景：对照：交换机 MAC 学习——源 MAC 记端口，未知目标泛洪，学习可更新端口。
  【不适用】Not for 以下场景：action 非 {learn, lookup} 时
license: MIT
compatibility: >-
  action ∈ {learn, lookup}；table 为 MAC→端口 映射
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["MAC学习", "网络-MAC学习", "MAC 学"]
    when: "action ∈ {learn, lookup}；table 为 MAC→端口 映射"
    sub: ["① learn 记录源 MAC 端口 ② lookup 查询转发端口 ③ 未知泛洪"]
    execute: "learn 写表；lookup 命中返端口、未命中返 flood"
    not_applicable: ["action 非 {learn, lookup} 时"]
  calibration: "对照：交换机 MAC 学习——源 MAC 记端口，未知目标泛洪，学习可更新端口"
---

# 网络-MAC学习（net-da559517）

## When to use

任务「MAC学习」；对照：交换机 MAC 学习——源 MAC 记端口，未知目标泛洪，学习可更新端口。

## 克制条款（不适用条件）

action 非 {learn, lookup} 时

## How to execute

learn 写表；lookup 命中返端口、未命中返 flood

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-MAC学习」
