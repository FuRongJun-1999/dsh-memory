---
name: net-e2d185de
description: >-
  物联网遥测 / 网络-物联网遥测 / 物联网——传感器遥测上报 / IoT 遥 / 传感器读数上报。用户提到这些词时使用本技能。
  场景：对照：物联网——传感器遥测上报（设备读数持续流）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 devices/device/reading 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["物联网遥测", "网络-物联网遥测", "物联网——传感器遥测上报", "IoT 遥", "传感器读数上报"]
    when: "参数 devices/device/reading 合法"
    sub: ["① 调用 len"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：物联网——传感器遥测上报（设备读数持续流）"
---

# 网络-物联网遥测（net-e2d185de）

## When to use

任务「物联网遥测」；对照：物联网——传感器遥测上报（设备读数持续流）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-物联网遥测」
