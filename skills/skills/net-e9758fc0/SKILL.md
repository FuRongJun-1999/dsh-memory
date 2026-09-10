---
name: net-e9758fc0
description: >-
  流量镜像 / 网络-流量镜像 / SPAN 端 / mirror 镜。用户提到这些词时使用本技能。
  场景：对照：SPAN 端口镜像——流量复制到监控口（抓包）。
  【不适用】Not for 以下场景：op 非 {capture, mirror, route} 时
license: MIT
compatibility: >-
  op ∈ {capture, mirror, route}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["流量镜像", "网络-流量镜像", "SPAN 端", "mirror 镜"]
    when: "op ∈ {capture, mirror, route}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {capture, mirror, route} 时"]
  calibration: "对照：SPAN 端口镜像——流量复制到监控口（抓包）"
---

# 网络-流量镜像（net-e9758fc0）

## When to use

任务「流量镜像」；对照：SPAN 端口镜像——流量复制到监控口（抓包）。

## 克制条款（不适用条件）

op 非 {capture, mirror, route} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-流量镜像」
