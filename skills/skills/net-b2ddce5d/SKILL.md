---
name: net-b2ddce5d
description: >-
  DNS解析 / 网络-DNS解析 / DNS——域 / DNS 解。用户提到这些词时使用本技能。
  场景：对照：DNS——域名解析（缓存命中直返/未命中查询，缓存加速语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 cache/domain 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["DNS解析", "网络-DNS解析", "DNS——域", "DNS 解"]
    when: "参数 cache/domain 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "DNS 解析：域名→IP（缓存命中直返；未命中模拟查询 8.8.8.8）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：DNS——域名解析（缓存命中直返/未命中查询，缓存加速语义）"
---

# 网络-DNS解析（net-b2ddce5d）

## When to use

任务「DNS解析」；对照：DNS——域名解析（缓存命中直返/未命中查询，缓存加速语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

DNS 解析：域名→IP（缓存命中直返；未命中模拟查询 8.8.8.8）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-DNS解析」
