---
name: os-3d84e0c9
description: >-
  引导加载 / 启动-引导加载 / OS 启 / bootloader / MBR→内。用户提到这些词时使用本技能。
  场景：对照：OS 启动——bootloader（MBR→内核→initrd 加载）。
  【不适用】Not for 以下场景：stage 非 {initrd, mbr} 时（隐式盲区：返回默认值 unknown = 未知行为——不适用）
license: MIT
compatibility: >-
  stage ∈ {initrd, mbr}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["引导加载", "启动-引导加载", "OS 启", "bootloader", "MBR→内"]
    when: "stage ∈ {initrd, mbr}"
    sub: ["1 stage 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["stage 非 {initrd, mbr} 时（隐式盲区：返回默认值 unknown = 未知行为——不适用）"]
  calibration: "对照：OS 启动——bootloader（MBR→内核→initrd 加载）"
---

# 启动-引导加载（os-3d84e0c9）

## When to use

任务「引导加载」；对照：OS 启动——bootloader（MBR→内核→initrd 加载）。

## 克制条款（不适用条件）

stage 非 {initrd, mbr} 时（隐式盲区：返回默认值 unknown = 未知行为——不适用）

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「启动-引导加载」
