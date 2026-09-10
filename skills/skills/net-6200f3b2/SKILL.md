---
name: net-6200f3b2
description: >-
  隧道封装 / 网络-隧道封装 / 解封装 / 隧道 / 内层包 + 外层头 / 剥离外层头 → 内层包。用户提到这些词时使用本技能。
  场景：对照：隧道——IP-in-IP 封装/解封装（外层头包裹内层包）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 inner/outer_src/outer_dst 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["隧道封装", "网络-隧道封装", "解封装", "隧道", "内层包 + 外层头", "剥离外层头 → 内层包"]
    when: "参数 inner/outer_src/outer_dst 合法"
    sub: []
    execute: "隧道：内层包 + 外层头（IP-in-IP 封装——跨网络传输）；解封装：剥离外层头 → 内层包"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：隧道——IP-in-IP 封装/解封装（外层头包裹内层包）"
---

# 网络-隧道封装（net-6200f3b2）

## When to use

任务「隧道封装」；对照：隧道——IP-in-IP 封装/解封装（外层头包裹内层包）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

隧道：内层包 + 外层头（IP-in-IP 封装——跨网络传输）；解封装：剥离外层头 → 内层包

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-隧道封装」
