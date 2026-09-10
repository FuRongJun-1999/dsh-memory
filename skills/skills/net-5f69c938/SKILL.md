---
name: net-5f69c938
description: >-
  累积确认 / 网络-累积确认 / TCP 接 / TCP 累 / 收到乱序包不确认。用户提到这些词时使用本技能。
  场景：对照：TCP 接收端——累积确认（连续序号推进 ACK；乱序只确认连续前缀）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 received/seq 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["累积确认", "网络-累积确认", "TCP 接", "TCP 累", "收到乱序包不确认"]
    when: "参数 received/seq 合法"
    sub: []
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：TCP 接收端——累积确认（连续序号推进 ACK；乱序只确认连续前缀）"
---

# 网络-累积确认（net-5f69c938）

## When to use

任务「累积确认」；对照：TCP 接收端——累积确认（连续序号推进 ACK；乱序只确认连续前缀）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-累积确认」
