---
name: net-78ec0324
description: >-
  IPv6地址 / 网络-IPv6地址 / IPv6 地 / IPv6 解 / 压缩形式展开 + 分组。用户提到这些词时使用本技能。
  场景：对照：IPv6 地址——:: 零压缩展开为 8 组（RFC 4291）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 addr 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["IPv6地址", "网络-IPv6地址", "IPv6 地", "IPv6 解", "压缩形式展开 + 分组"]
    when: "参数 addr 合法"
    sub: ["① 调用 len"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：IPv6 地址——:: 零压缩展开为 8 组（RFC 4291）"
---

# 网络-IPv6地址（net-78ec0324）

## When to use

任务「IPv6地址」；对照：IPv6 地址——:: 零压缩展开为 8 组（RFC 4291）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-IPv6地址」
