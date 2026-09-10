---
name: browser-ea9b2b8e
description: >-
  地理位置 / 浏览器-地理位置 / Geolocation  / 坐标获取 / request 请。用户提到这些词时使用本技能。
  场景：对照：Geolocation API——权限请求/坐标获取（权限门控）。
  【不适用】Not for 以下场景：op 非 {get, request} 时
license: MIT
compatibility: >-
  op ∈ {get, request}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["地理位置", "浏览器-地理位置", "Geolocation ", "坐标获取", "request 请"]
    when: "op ∈ {get, request}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {get, request} 时"]
  calibration: "对照：Geolocation API——权限请求/坐标获取（权限门控）"
---

# 浏览器-地理位置（browser-ea9b2b8e）

## When to use

任务「地理位置」；对照：Geolocation API——权限请求/坐标获取（权限门控）。

## 克制条款（不适用条件）

op 非 {get, request} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-地理位置」
