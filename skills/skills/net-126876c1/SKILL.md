---
name: net-126876c1
description: >-
  报文解析 / 网络-报文解析 / 头部字段。用户提到这些词时使用本技能。
  场景：对照：网络分析——IP 报文解析（版本/协议/源/目的）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  packet 为 IP 报文字节（≥20 字节头部）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["报文解析", "网络-报文解析", "头部字段"]
    when: "packet 为 IP 报文字节（≥20 字节头部）"
    sub: ["① 版本/协议提取 ② 源地址提取 ③ 目的地址提取"]
    execute: "按字节偏移位运算 + 点分十进制拼接"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：网络分析——IP 报文解析（版本/协议/源/目的）"
---

# 网络-报文解析（net-126876c1）

## When to use

任务「报文解析」；对照：网络分析——IP 报文解析（版本/协议/源/目的）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

按字节偏移位运算 + 点分十进制拼接

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-报文解析」
