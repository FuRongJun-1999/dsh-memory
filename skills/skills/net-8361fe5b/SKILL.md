---
name: net-8361fe5b
description: >-
  路径MTU发现 / 网络-路径MTU发现 / PMTUD——路 / probe 探。用户提到这些词时使用本技能。
  场景：对照：PMTUD——路径最大传输单元发现（过大减 8 重探）。
  【不适用】Not for 以下场景：op 非 {current, probe, result} 时
license: MIT
compatibility: >-
  op ∈ {current, probe, result}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["路径MTU发现", "网络-路径MTU发现", "PMTUD——路", "probe 探"]
    when: "op ∈ {current, probe, result}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {current, probe, result} 时"]
  calibration: "对照：PMTUD——路径最大传输单元发现（过大减 8 重探）"
---

# 网络-路径MTU发现（net-8361fe5b）

## When to use

任务「路径MTU发现」；对照：PMTUD——路径最大传输单元发现（过大减 8 重探）。

## 克制条款（不适用条件）

op 非 {current, probe, result} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-路径MTU发现」
