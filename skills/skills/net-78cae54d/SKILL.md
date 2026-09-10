---
name: net-78cae54d
description: >-
  滑动窗口 / 网络-滑动窗口 / TCP 可 / TCP 滑 / base=已。用户提到这些词时使用本技能。
  场景：对照：TCP 可靠传输——滑动窗口（ACK 确认后窗口前移，窗口内可发送）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  base=已确认序号；next_seq=下一待发；ack=收到的确认
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["滑动窗口", "网络-滑动窗口", "TCP 可", "TCP 滑", "base=已"]
    when: "base=已确认序号；next_seq=下一待发；ack=收到的确认"
    sub: ["① ack 前进基准 ② 待发序号同步 ③ 返回可发送窗口"]
    execute: "ack > base 则前移；next_seq 落后则推进（滑动窗口语义）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：TCP 可靠传输——滑动窗口（ACK 确认后窗口前移，窗口内可发送）"
---

# 网络-滑动窗口（net-78cae54d）

## When to use

任务「滑动窗口」；对照：TCP 可靠传输——滑动窗口（ACK 确认后窗口前移，窗口内可发送）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

ack > base 则前移；next_seq 落后则推进（滑动窗口语义）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-滑动窗口」
