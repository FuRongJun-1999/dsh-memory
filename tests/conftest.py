# -*- coding: utf-8 -*-
"""测试夹具默认声明复核单元（2026-11-17）。

写入闸默认 enforce：知识层需 reflect 复核。测试里大量夹具直接写 knowledge 层
（验证标签/检索/一致性等），若不声明复核，闸会把夹具本身拦掉——那不是被测行为。

这里等价于「复核已通过」：真实写入（MCP/代理/外部模型）仍必须自带复核结论，
本文件只影响测试进程，不改变生产行为。
"""
import os

os.environ.setdefault('MDCG_REVIEWERS', 'reflect')