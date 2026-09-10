---
name: net-96c61a3c
description: >-
  IP分片 / 网络-IP分片 / IP 分。用户提到这些词时使用本技能。
  场景：对照：网络 IP——超过 MTU 需分片（每片 20B 头）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  math.ceil 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["IP分片", "网络-IP分片", "IP 分"]
    when: "math.ceil 可用"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "IP 分片：包大小 + MTU → 分片数（每片含 20B IP 头）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：网络 IP——超过 MTU 需分片（每片 20B 头）"
---

# 网络-IP分片（net-96c61a3c）

## When to use

任务「IP分片」；对照：网络 IP——超过 MTU 需分片（每片 20B 头）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

IP 分片：包大小 + MTU → 分片数（每片含 20B IP 头）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-IP分片」
