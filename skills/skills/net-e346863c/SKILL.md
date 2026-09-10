---
name: net-e346863c
description: >-
  配对信任 / 蜂群-配对信任 / 蓝牙配对——信任建立 / 撤销 / 查询三操作 / 配对即信任=1 / device_id 配。用户提到这些词时使用本技能。
  场景：对照：蓝牙配对——信任建立/撤销/查询三操作，配对即信任=1（蜂群信任链基例）。
  【不适用】Not for 以下场景：重复配对已配对设备返回原状态（幂等）
license: MIT
compatibility: >-
  devices 为设备 dict（id → {'paired': bool, 'trust': int}）；
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["配对信任", "蜂群-配对信任", "蓝牙配对——信任建立", "撤销", "查询三操作", "配对即信任=1", "device_id 配"]
    when: "devices 为设备 dict（id → {'paired': bool, 'trust': int}）；"
    sub: ["① pair 信任建立（trust=1）② unpair 撤销 ③ check 查询"]
    execute: "状态机分派（配对信任链：未配对→已配对，撤销反向）"
    not_applicable: ["重复配对已配对设备返回原状态（幂等）"]
  calibration: "对照：蓝牙配对——信任建立/撤销/查询三操作，配对即信任=1（蜂群信任链基例）"
---

# 蜂群-配对信任（net-e346863c）

## When to use

任务「配对信任」；对照：蓝牙配对——信任建立/撤销/查询三操作，配对即信任=1（蜂群信任链基例）。

## 克制条款（不适用条件）

重复配对已配对设备返回原状态（幂等）

## How to execute

状态机分派（配对信任链：未配对→已配对，撤销反向）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「蜂群-配对信任」
