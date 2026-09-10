---
name: net-80b56cd6
description: >-
  证书校验 / 网络-证书校验 / 有效期时间窗检查。用户提到这些词时使用本技能。
  场景：对照：X.509 证书有效期校验——not_before/not_after 时间窗判定。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  cert 含 not_before/not_after；now 为当前时间戳
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["证书校验", "网络-证书校验", "有效期时间窗检查"]
    when: "cert 含 not_before/not_after；now 为当前时间戳"
    sub: ["① 时间窗边界比较 ② 越界判过期 ③ 窗内判有效"]
    execute: "now < not_before 或 now > not_after → expired（fail-closed）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：X.509 证书有效期校验——not_before/not_after 时间窗判定"
---

# 网络-证书校验（net-80b56cd6）

## When to use

任务「证书校验」；对照：X.509 证书有效期校验——not_before/not_after 时间窗判定。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

now < not_before 或 now > not_after → expired（fail-closed）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-证书校验」
