---
name: net-5fa6c13b
description: >-
  帧封装 / 网络-帧封装 / WebSocket 帧 / 首字节 + 长度 + 负。用户提到这些词时使用本技能。
  场景：对照：WebSocket 帧——FIN+opcode+长度+负载（RFC 6455 帧格式）。
  【不适用】Not for 以下场景：n 越界（Lt）时
license: MIT
compatibility: >-
  参数 opcode/payload 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["帧封装", "网络-帧封装", "WebSocket 帧", "首字节 + 长度 + 负"]
    when: "参数 opcode/payload 合法"
    sub: ["① 调用 len；② 调用 bytes"]
    execute: "顺序调用"
    not_applicable: ["n 越界（Lt）时"]
  calibration: "对照：WebSocket 帧——FIN+opcode+长度+负载（RFC 6455 帧格式）"
---

# 网络-帧封装（net-5fa6c13b）

## When to use

任务「帧封装」；对照：WebSocket 帧——FIN+opcode+长度+负载（RFC 6455 帧格式）。

## 克制条款（不适用条件）

n 越界（Lt）时

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-帧封装」
