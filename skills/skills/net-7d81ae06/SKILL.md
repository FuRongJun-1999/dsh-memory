---
name: net-7d81ae06
description: >-
  抓包分析 / 网络-抓包分析 / 抓包分析——包计数 / 协议分布 / 包计数/协议分布。用户提到这些词时使用本技能。
  场景：对照：抓包分析——包计数/协议分布（pcap 统计）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 captures 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["抓包分析", "网络-抓包分析", "抓包分析——包计数", "协议分布", "包计数/协议分布"]
    when: "参数 captures 合法"
    sub: ["① 调用 len"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：抓包分析——包计数/协议分布（pcap 统计）"
---

# 网络-抓包分析（net-7d81ae06）

## When to use

任务「抓包分析」；对照：抓包分析——包计数/协议分布（pcap 统计）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-抓包分析」
