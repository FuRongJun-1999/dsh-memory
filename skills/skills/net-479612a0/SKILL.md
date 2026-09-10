---
name: net-479612a0
description: >-
  WebSocket握手 / 网络-WebSocket握手 / WebSocket——H / WebSocket 握 / HTTP Upgrade。用户提到这些词时使用本技能。
  场景：对照：WebSocket——HTTP Upgrade 握手（RFC 6455：101 切换协议/400 拒绝）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 headers 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["WebSocket握手", "网络-WebSocket握手", "WebSocket——H", "WebSocket 握", "HTTP Upgrade"]
    when: "参数 headers 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "WebSocket 握手：HTTP Upgrade: websocket → 101 切换协议"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：WebSocket——HTTP Upgrade 握手（RFC 6455：101 切换协议/400 拒绝）"
---

# 网络-WebSocket握手（net-479612a0）

## When to use

任务「WebSocket握手」；对照：WebSocket——HTTP Upgrade 握手（RFC 6455：101 切换协议/400 拒绝）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

WebSocket 握手：HTTP Upgrade: websocket → 101 切换协议

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-WebSocket握手」
