---
name: net-1da1c695
description: >-
  CDN缓存 / 网络-CDN缓存 / CDN——边 / CDN / 边缘节点缓存。用户提到这些词时使用本技能。
  场景：对照：CDN——边缘缓存（命中/回源/缓存写入，内容就近分发）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 edges/content/url 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["CDN缓存", "网络-CDN缓存", "CDN——边", "CDN", "边缘节点缓存"]
    when: "参数 edges/content/url 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "CDN：边缘节点缓存（内容就近分发——回源/命中）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：CDN——边缘缓存（命中/回源/缓存写入，内容就近分发）"
---

# 网络-CDN缓存（net-1da1c695）

## When to use

任务「CDN缓存」；对照：CDN——边缘缓存（命中/回源/缓存写入，内容就近分发）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

CDN：边缘节点缓存（内容就近分发——回源/命中）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-CDN缓存」
