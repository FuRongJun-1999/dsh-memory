---
name: net-0935edf1
description: >-
  拓扑发现 / 网络-拓扑发现 / 拓扑发现——链路探测与邻 / probe 探。用户提到这些词时使用本技能。
  场景：对照：拓扑发现——链路探测与邻居表（LLDP）。
  【不适用】Not for 以下场景：op 非 {link, neighbors, probe} 时
license: MIT
compatibility: >-
  op ∈ {link, neighbors, probe}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["拓扑发现", "网络-拓扑发现", "拓扑发现——链路探测与邻", "probe 探"]
    when: "op ∈ {link, neighbors, probe}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {link, neighbors, probe} 时"]
  calibration: "对照：拓扑发现——链路探测与邻居表（LLDP）"
---

# 网络-拓扑发现（net-0935edf1）

## When to use

任务「拓扑发现」；对照：拓扑发现——链路探测与邻居表（LLDP）。

## 克制条款（不适用条件）

op 非 {link, neighbors, probe} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-拓扑发现」
