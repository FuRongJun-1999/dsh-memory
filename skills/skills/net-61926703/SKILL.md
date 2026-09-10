---
name: net-61926703
description: >-
  RTO退避 / 网络-RTO退避 / TCP RTO——指 / RTO 重 / 指数退避。用户提到这些词时使用本技能。
  场景：对照：TCP RTO——指数退避（重传超时翻倍）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 rto/losses 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["RTO退避", "网络-RTO退避", "TCP RTO——指", "RTO 重", "指数退避"]
    when: "参数 rto/losses 合法"
    sub: []
    execute: "RTO 重传超时：指数退避（每次超时翻倍——避免拥塞加剧）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：TCP RTO——指数退避（重传超时翻倍）"
---

# 网络-RTO退避（net-61926703）

## When to use

任务「RTO退避」；对照：TCP RTO——指数退避（重传超时翻倍）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

RTO 重传超时：指数退避（每次超时翻倍——避免拥塞加剧）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-RTO退避」
