---
name: net-68643014
description: >-
  访问令牌 / 网络-访问令牌 / OAuth 访 / 校验 / issue 签。用户提到这些词时使用本技能。
  场景：对照：OAuth 访问令牌——签发/校验（过期与吊销）/吊销。
  【不适用】Not for 以下场景：op 非 {issue, revoke, verify} 时
license: MIT
compatibility: >-
  op ∈ {issue, revoke, verify}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["访问令牌", "网络-访问令牌", "OAuth 访", "校验", "issue 签"]
    when: "op ∈ {issue, revoke, verify}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {issue, revoke, verify} 时"]
  calibration: "对照：OAuth 访问令牌——签发/校验（过期与吊销）/吊销"
---

# 网络-访问令牌（net-68643014）

## When to use

任务「访问令牌」；对照：OAuth 访问令牌——签发/校验（过期与吊销）/吊销。

## 克制条款（不适用条件）

op 非 {issue, revoke, verify} 时

## How to execute

按 op 分派

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-访问令牌」
