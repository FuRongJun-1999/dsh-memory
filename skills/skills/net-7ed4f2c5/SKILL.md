---
name: net-7ed4f2c5
description: >-
  多路复用 / 网络-多路复用 / HTTP / 2 多路复用——单连接多 / HTTP/2 多 / 多流帧交错。用户提到这些词时使用本技能。
  场景：对照：HTTP/2 多路复用——单连接多流帧交错（流 ID 区分）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 streams 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["多路复用", "网络-多路复用", "HTTP", "2 多路复用——单连接多", "HTTP/2 多", "多流帧交错"]
    when: "参数 streams 合法"
    sub: []
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：HTTP/2 多路复用——单连接多流帧交错（流 ID 区分）"
---

# 网络-多路复用（net-7ed4f2c5）

## When to use

任务「多路复用」；对照：HTTP/2 多路复用——单连接多流帧交错（流 ID 区分）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-多路复用」
