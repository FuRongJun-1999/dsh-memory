---
name: browser-4d6c0788
description: >-
  媒体播放 / 浏览器-媒体播放 / HTML5 媒 / pause / seek / volume / play 播。用户提到这些词时使用本技能。
  场景：对照：HTML5 媒体——play/pause/seek/volume（音量夹紧）。
  【不适用】Not for 以下场景：op 非 {pause, play, seek, volume} 时
license: MIT
compatibility: >-
  op ∈ {pause, play, seek, volume}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["媒体播放", "浏览器-媒体播放", "HTML5 媒", "pause", "seek", "volume", "play 播"]
    when: "op ∈ {pause, play, seek, volume}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {pause, play, seek, volume} 时"]
  calibration: "对照：HTML5 媒体——play/pause/seek/volume（音量夹紧）"
---

# 浏览器-媒体播放（browser-4d6c0788）

## When to use

任务「媒体播放」；对照：HTML5 媒体——play/pause/seek/volume（音量夹紧）。

## 克制条款（不适用条件）

op 非 {pause, play, seek, volume} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-媒体播放」
