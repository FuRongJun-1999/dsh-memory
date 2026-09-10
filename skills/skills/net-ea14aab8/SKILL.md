---
name: net-ea14aab8
description: >-
  快速重传 / 网络-快速重传 / TCP 快。用户提到这些词时使用本技能。
  场景：对照：TCP 快速重传——3 个重复 ACK 触发立即重传（不等超时）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 dup_acks/threshold 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["快速重传", "网络-快速重传", "TCP 快"]
    when: "参数 dup_acks/threshold 合法"
    sub: []
    execute: "快速重传：重复 ACK 达阈值立即重传（不等超时——快速恢复）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：TCP 快速重传——3 个重复 ACK 触发立即重传（不等超时）"
---

# 网络-快速重传（net-ea14aab8）

## When to use

任务「快速重传」；对照：TCP 快速重传——3 个重复 ACK 触发立即重传（不等超时）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

快速重传：重复 ACK 达阈值立即重传（不等超时——快速恢复）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-快速重传」
