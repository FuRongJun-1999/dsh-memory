---
name: os-3e0aff42
description: >-
  页表映射 / 内存-页表映射 / OS 虚。用户提到这些词时使用本技能。
  场景：对照：OS 虚拟内存——页表映射（VPN→物理帧；present=0 或缺项=缺页）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  page_table 为 VPN→页表项 映射；vpn 为虚拟页号
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["页表映射", "内存-页表映射", "OS 虚"]
    when: "page_table 为 VPN→页表项 映射；vpn 为虚拟页号"
    sub: ["① 查页表项 ② present 位判定 ③ 缺页/命中返回"]
    execute: "无条目或 present≠1 → None（缺页）；否则返 frame"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 虚拟内存——页表映射（VPN→物理帧；present=0 或缺项=缺页）"
---

# 内存-页表映射（os-3e0aff42）

## When to use

任务「页表映射」；对照：OS 虚拟内存——页表映射（VPN→物理帧；present=0 或缺项=缺页）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

无条目或 present≠1 → None（缺页）；否则返 frame

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「内存-页表映射」
