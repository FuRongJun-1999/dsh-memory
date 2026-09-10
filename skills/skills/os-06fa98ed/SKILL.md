---
name: os-06fa98ed
description: >-
  固件接口 / 系统-固件接口 / UEFI/BIOS 调。用户提到这些词时使用本技能。
  场景：对照：固件接口——UEFI 服务（时间/重启/启动设备）。
  【不适用】Not for 以下场景：call 非 {get_time, reboot, set_boot} 时
license: MIT
compatibility: >-
  call ∈ {get_time, reboot, set_boot}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["固件接口", "系统-固件接口", "UEFI/BIOS 调"]
    when: "call ∈ {get_time, reboot, set_boot}"
    sub: ["1 call 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["call 非 {get_time, reboot, set_boot} 时"]
  calibration: "对照：固件接口——UEFI 服务（时间/重启/启动设备）"
---

# 系统-固件接口（os-06fa98ed）

## When to use

任务「固件接口」；对照：固件接口——UEFI 服务（时间/重启/启动设备）。

## 克制条款（不适用条件）

call 非 {get_time, reboot, set_boot} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-固件接口」
