---
name: net-c685b788
description: >-
  停等协议 / 网络-停等协议 / 网络可靠传输——停等协议 / 发送→等确认→再发下一个。用户提到这些词时使用本技能。
  场景：对照：网络可靠传输——停等协议（逐包确认后再发下一包）。
  【不适用】Not for 以下场景：ack_all 为空/非法时
license: MIT
compatibility: >-
  参数 send_packets/ack_all 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["停等协议", "网络-停等协议", "网络可靠传输——停等协议", "发送→等确认→再发下一个"]
    when: "参数 send_packets/ack_all 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["ack_all 为空/非法时"]
  calibration: "对照：网络可靠传输——停等协议（逐包确认后再发下一包）"
---

# 网络-停等协议（net-c685b788）

## When to use

任务「停等协议」；对照：网络可靠传输——停等协议（逐包确认后再发下一包）。

## 克制条款（不适用条件）

ack_all 为空/非法时

## How to execute

循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-停等协议」
