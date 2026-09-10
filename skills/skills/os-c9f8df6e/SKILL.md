---
name: os-c9f8df6e
description: >-
  服务管理 / 系统-服务管理 / systemd 服 / stop / status / start 启。用户提到这些词时使用本技能。
  场景：对照：systemd 服务——start/stop/status（服务生命周期）。
  【不适用】Not for 以下场景：op 非 {start, status, stop} 时
license: MIT
compatibility: >-
  op ∈ {start, status, stop}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["服务管理", "系统-服务管理", "systemd 服", "stop", "status", "start 启"]
    when: "op ∈ {start, status, stop}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {start, status, stop} 时"]
  calibration: "对照：systemd 服务——start/stop/status（服务生命周期）"
---

# 系统-服务管理（os-c9f8df6e）

## When to use

任务「服务管理」；对照：systemd 服务——start/stop/status（服务生命周期）。

## 克制条款（不适用条件）

op 非 {start, status, stop} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-服务管理」
