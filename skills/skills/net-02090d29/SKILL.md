---
name: net-02090d29
description: >-
  NAT转换 / 网络-NAT / NAT / 内网地址→公网地址（端口。用户提到这些词时使用本技能。
  场景：对照：网络 NAT——内网→公网地址转换（端口映射表，复用已映射端口）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 table/src_ip/src_port/pub_ip 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["NAT转换", "网络-NAT", "NAT", "内网地址→公网地址（端口"]
    when: "参数 table/src_ip/src_port/pub_ip 合法"
    sub: ["① 调用 len"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：网络 NAT——内网→公网地址转换（端口映射表，复用已映射端口）"
---

# 网络-NAT（net-02090d29）

## When to use

任务「NAT转换」；对照：网络 NAT——内网→公网地址转换（端口映射表，复用已映射端口）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-NAT」
