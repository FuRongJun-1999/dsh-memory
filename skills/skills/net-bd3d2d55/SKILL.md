---
name: net-bd3d2d55
description: >-
  服务发现 / 网络-服务发现 / 服务发现——注册 / 心跳续期 / 健康发现 / 注册 / 心跳续期 / 。用户提到这些词时使用本技能。
  场景：对照：服务发现——注册/心跳续期/健康发现（过期剔除）。
  【不适用】Not for 以下场景：op 非 {discover, heartbeat, register} 时
license: MIT
compatibility: >-
  op ∈ {discover, heartbeat, register}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["服务发现", "网络-服务发现", "服务发现——注册", "心跳续期", "健康发现", "注册 / 心跳续期 / "]
    when: "op ∈ {discover, heartbeat, register}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {discover, heartbeat, register} 时"]
  calibration: "对照：服务发现——注册/心跳续期/健康发现（过期剔除）"
---

# 网络-服务发现（net-bd3d2d55）

## When to use

任务「服务发现」；对照：服务发现——注册/心跳续期/健康发现（过期剔除）。

## 克制条款（不适用条件）

op 非 {discover, heartbeat, register} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-服务发现」
