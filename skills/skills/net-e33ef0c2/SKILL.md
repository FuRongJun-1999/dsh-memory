---
name: net-e33ef0c2
description: >-
  协议解码 / 网络-协议解码 / 协议解码——十六进制转字 / 十六进制 → 字节串。用户提到这些词时使用本技能。
  场景：对照：协议解码——十六进制转字节（抓包数据）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  bytes.fromhex 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["协议解码", "网络-协议解码", "协议解码——十六进制转字", "十六进制 → 字节串"]
    when: "bytes.fromhex 可用"
    sub: []
    execute: "协议解码：十六进制 → 字节串（抓包数据解码）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：协议解码——十六进制转字节（抓包数据）"
---

# 网络-协议解码（net-e33ef0c2）

## When to use

任务「协议解码」；对照：协议解码——十六进制转字节（抓包数据）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

协议解码：十六进制 → 字节串（抓包数据解码）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-协议解码」
