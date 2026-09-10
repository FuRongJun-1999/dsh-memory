---
name: net-14e9ad0d
description: >-
  滑动窗口限流 / 网络-滑动窗口限流 / 滑动窗口限流——窗口内请 / 窗口内请求数 ≤ 上限。用户提到这些词时使用本技能。
  场景：对照：滑动窗口限流——窗口内请求计数（超限拒绝）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 requests/window/limit 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["滑动窗口限流", "网络-滑动窗口限流", "滑动窗口限流——窗口内请", "窗口内请求数 ≤ 上限"]
    when: "参数 requests/window/limit 合法"
    sub: ["① 调用 enumerate；② 调用 sum"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：滑动窗口限流——窗口内请求计数（超限拒绝）"
---

# 网络-滑动窗口限流（net-14e9ad0d）

## When to use

任务「滑动窗口限流」；对照：滑动窗口限流——窗口内请求计数（超限拒绝）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-滑动窗口限流」
