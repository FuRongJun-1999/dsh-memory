---
name: browser-5a455aeb
description: >-
  摄像头 / 浏览器-摄像头 / request 请。用户提到这些词时使用本技能。
  场景：对照：getUserMedia——摄像头权限与媒体流启停。
  【不适用】Not for 以下场景：op 非 {request, start, stop} 时
license: MIT
compatibility: >-
  op ∈ {request, start, stop}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["摄像头", "浏览器-摄像头", "request 请"]
    when: "op ∈ {request, start, stop}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {request, start, stop} 时"]
  calibration: "对照：getUserMedia——摄像头权限与媒体流启停"
---

# 浏览器-摄像头（browser-5a455aeb）

## When to use

任务「摄像头」；对照：getUserMedia——摄像头权限与媒体流启停。

## 克制条款（不适用条件）

op 非 {request, start, stop} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-摄像头」
