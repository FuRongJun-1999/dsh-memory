---
name: browser-6e1c1158
description: >-
  应用清单 / PWA-应用清单 / PWA manifest / 图标 / 启动地址最小字段 / PWA 清 / 最小字段校验。用户提到这些词时使用本技能。
  场景：对照：PWA manifest——名称/图标/启动地址最小字段（安装条件）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 manifest 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["应用清单", "PWA-应用清单", "PWA manifest", "图标", "启动地址最小字段", "PWA 清", "最小字段校验"]
    when: "参数 manifest 合法"
    sub: []
    execute: "PWA 清单：最小字段校验（名称/图标/启动地址——可安装条件）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：PWA manifest——名称/图标/启动地址最小字段（安装条件）"
---

# PWA-应用清单（browser-6e1c1158）

## When to use

任务「应用清单」；对照：PWA manifest——名称/图标/启动地址最小字段（安装条件）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

PWA 清单：最小字段校验（名称/图标/启动地址——可安装条件）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「PWA-应用清单」
