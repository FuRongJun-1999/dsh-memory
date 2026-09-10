---
name: net-db4f414e
description: >-
  负载均衡 / 网络-负载均衡 / 网络负载均衡——轮询调度 / 轮询调度。用户提到这些词时使用本技能。
  场景：对照：网络负载均衡——轮询调度（请求均匀分布到服务器）。
  【不适用】Not for 以下场景：servers 为空/非法时
license: MIT
compatibility: >-
  参数 servers/request_id 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["负载均衡", "网络-负载均衡", "网络负载均衡——轮询调度", "轮询调度"]
    when: "参数 servers/request_id 合法"
    sub: ["① 调用 len"]
    execute: "顺序调用"
    not_applicable: ["servers 为空/非法时"]
  calibration: "对照：网络负载均衡——轮询调度（请求均匀分布到服务器）"
---

# 网络-负载均衡（net-db4f414e）

## When to use

任务「负载均衡」；对照：网络负载均衡——轮询调度（请求均匀分布到服务器）。

## 克制条款（不适用条件）

servers 为空/非法时

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-负载均衡」
