#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出 en→zh 扁平映射（en_zh_map.json）——rust/mcdg-eval 统一归一层的词表源。

批次 15（2026-09-23 使用者口径：统一翻译为中文→归一化到标准中文集→检索）。

为何导出而非 Rust 移植：en_normalizer 的词表面（MORPHEME/COMPOUND_ZH/
CEDICT 链/IRREGULAR）若在 Rust 复刻，即出现第二份词典真源——词典版本
敏感（同词面不同版本映射不同 → 两侧分数漂移）正是当初弃用外部分词器的
原因。故词表真源单侧化：本脚本用 **normalize_en_query 自身** 算每个词面
的终态（生成即经全链：strip_tense→停用词→CEDICT 链→复合词），产物是
派生缓存——词表更新后重跑本脚本再生成，两侧永不漂移。

键覆盖：MORPHEME ∪ COMPOUND_ZH ∪ IRREGULAR 全部键（IRREGULAR 键经
strip_tense 展开到原形后再走链，如 ate→eat→吃）；值为该词面经完整归一
链的中文原子串（空格 join）。表外词两侧一致保留原词（unknown_keep）。

Rust 侧消费：MDCG_EN_ZH_MAP 指向本文件（rust/src/atoms.rs）。
用法：python -m md_cg.semantic.export_en_zh_map
"""
import json
import os

from .en_normalizer import (IRREGULAR, COMPOUND_ZH, EN_ZH, cedict_map,
                            normalize_en_query)
from .zh_en_atoms import ZH_EN

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "en_zh_map.json")


# 生效条件：无 required 形参；keys 取 MORPHEME_ZH、COMPOUND_ZH、IRREGULAR 三表键的并集（IRREGULAR 值原形并入 keys）；对每个 key 经 normalize_en_query 归一取首个非空中文词序列并以单空格 join，含字母的产物（unknown_keep）跳过不落表；返回排序后的 dict 并写入 OUT（encoding=utf-8，ensure_ascii=False，indent=1）。
def build():
    """生成扁平 word→zh 映射并写盘。返回映射 dict（供测试断言）。"""
    keys = set(EN_ZH) | set(COMPOUND_ZH)
    keys |= set(cedict_map())            # CEDICT 链命中词（compiler/test…）同权导出
    keys |= set(IRREGULAR.values())       # 原形（write）与屈折形（wrote）都要能查
    keys |= set(IRREGULAR.keys())
    out = {}
    for w in sorted(keys):
        try:
            terms, _d = normalize_en_query(w)
        except Exception:
            continue
        zh = " ".join(t for t in terms if t and not any(
            "a" <= c.lower() <= "z" for c in t)).strip()
        if zh and zh != w:
            out[w.lower()] = zh
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"meta": {"version": "b15", "entries": len(out),
                            "derived_from": "en_normalizer 全链",
                            "zh_atoms": len(ZH_EN)},
                   "map": out,
                   # segment 贪心匹配键源（zh_en_atoms.ZH_EN 键 = 标准原子集，
                   # 与 canonical.atoms_zh() 的 OOV 审计基准同源）
                   "zh_keys": sorted(ZH_EN.keys())}, f,
                  ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    m = build()
    print(f"en_zh_map.json: {len(m)} entries -> {OUT}")
    for k in ("wrote", "write", "tests", "beef", "soul hub"):
        print(f"  {k!r} -> {m.get(k)!r}")
