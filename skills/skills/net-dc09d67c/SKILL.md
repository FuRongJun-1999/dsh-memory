---
name: net-dc09d67c
description: >-
  VLAN划分 / 网络-VLAN划分 / VLAN——802.1Q / VLAN / 802.1Q 标。用户提到这些词时使用本技能。
  场景：对照：VLAN——802.1Q 标签（TPID 0x8100 + VID 12bit）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 frame/vlan_id 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["VLAN划分", "网络-VLAN划分", "VLAN——802.1Q", "VLAN", "802.1Q 标"]
    when: "参数 frame/vlan_id 合法"
    sub: []
    execute: "VLAN：802.1Q 标签（4 字节——TPID+TCI 含 VID 12bit）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：VLAN——802.1Q 标签（TPID 0x8100 + VID 12bit）"
---

# 网络-VLAN划分（net-dc09d67c）

## When to use

任务「VLAN划分」；对照：VLAN——802.1Q 标签（TPID 0x8100 + VID 12bit）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

VLAN：802.1Q 标签（4 字节——TPID+TCI 含 VID 12bit）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-VLAN划分」
