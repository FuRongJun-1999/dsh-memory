---
name: net-998f3641
description: >-
  MQTT发布订阅 / 网络-MQTT发布订阅 / MQTT——发 / 订阅 / MQTT / 发布/订阅。用户提到这些词时使用本技能。
  场景：对照：MQTT——发布/订阅（主题路由，订阅者接收主题消息）。
  【不适用】Not for 以下场景：op 非 {publish, subscribe} 时
license: MIT
compatibility: >-
  op ∈ {publish, subscribe}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["MQTT发布订阅", "网络-MQTT发布订阅", "MQTT——发", "订阅", "MQTT", "发布/订阅"]
    when: "op ∈ {publish, subscribe}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {publish, subscribe} 时"]
  calibration: "对照：MQTT——发布/订阅（主题路由，订阅者接收主题消息）"
---

# 网络-MQTT发布订阅（net-998f3641）

## When to use

任务「MQTT发布订阅」；对照：MQTT——发布/订阅（主题路由，订阅者接收主题消息）。

## 克制条款（不适用条件）

op 非 {publish, subscribe} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-MQTT发布订阅」
