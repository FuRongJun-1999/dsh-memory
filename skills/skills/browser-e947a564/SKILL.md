---
name: browser-e947a564
description: >-
  HTTP缓存 / 网络-HTTP缓存 / HTTP 缓 / ETag 条。用户提到这些词时使用本技能。
  场景：对照：浏览器网络——HTTP 缓存（ETag 条件请求 304/200 语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 cache/url/etag 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["HTTP缓存", "网络-HTTP缓存", "HTTP 缓", "ETag 条"]
    when: "参数 cache/url/etag 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "HTTP 缓存：ETag 条件请求（未变更 304 → 用缓存；变更 → 更新）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器网络——HTTP 缓存（ETag 条件请求 304/200 语义）"
---

# 网络-HTTP缓存（browser-e947a564）

## When to use

任务「HTTP缓存」；对照：浏览器网络——HTTP 缓存（ETag 条件请求 304/200 语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

HTTP 缓存：ETag 条件请求（未变更 304 → 用缓存；变更 → 更新）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-HTTP缓存」
