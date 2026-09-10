---
name: browser-f5ffc6d9
description: >-
  Web Worker / 并行-Web Worker。用户提到这些词时使用本技能。
  场景：对照：浏览器并行——Web Worker（postMessage 传递数据，Worker 处理回传）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 main/worker/data 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["Web Worker", "并行-Web Worker"]
    when: "参数 main/worker/data 合法"
    sub: []
    execute: "Web Worker：主线程 postMessage → Worker 处理 → 回传（并行任务语义）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器并行——Web Worker（postMessage 传递数据，Worker 处理回传）"
---

# 并行-Web Worker（browser-f5ffc6d9）

## When to use

任务「Web Worker」；对照：浏览器并行——Web Worker（postMessage 传递数据，Worker 处理回传）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

Web Worker：主线程 postMessage → Worker 处理 → 回传（并行任务语义）

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「并行-Web Worker」
