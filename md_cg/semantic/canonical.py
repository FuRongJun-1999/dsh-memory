#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵枢 · 标准语义归一面（词表真源 + AI 写入侧归一 + 组合相遇判据）

使用者设想（2026-09-14）四要素与代码边界：
  ① 标准语义基准     = atoms.json（815 标准概念，词表唯一真源，本模块只读加载）；
  ② 同义体按基准翻译 = 归一主体是 **AI 写入侧**（AI 自带翻译，add(semantic=...)
    直接传标准原子序列；「荤油→猪油」类同义归一发生在 AI 理解里，
    代码不维护同义表——系统职责收缩为词表+校验）；
  ③ 归一产物作摘要   = fm.semantic 衍生层（可审查、可版本化）；
  ④ 真源+原始双保留 = semantic 是 frontmatter 衍生层，正文原文无损——
    归一错误传播仅限摘要层，词表更新后重归一可修复。

代码职责（最小三件，全部纯函数）：
  - atoms_zh()   词表加载（模块级缓存）；
  - oov_of()     OOV 审计（警告不拒绝：词表覆盖有限，拒绝会堵死合法写入；
                 OOV 列表落 fm.semantic_oov，同时是词表扩容的观测依据）；
  - pair_hits()  检索面组合窗口共现判据。窗口语义来自 L3 探针实证
                 （2026-09-14）：纯邻接只救 1/3（「羊 的 油」「鱼 里 提 取
                 的 油」距离 2/4），win=6 全救 3/3 且受控池零误配；
                 开放域「鱼和油分述」的误配风险由组合结构约束兜底
                 （与 P1 compositions 汇合，b2_comp 臂为共同验收器）。
"""
import functools
import json
import os
import re

from . import zh_en_atoms

WIN = 6          # 组合共现窗口（token 距离，探针实证口径）
_ATOMS_ZH = None


# 生效条件：模块级常量 `_ATOMS_ZH` 为 None 时按 `__file__` 所在目录的 atoms.json 取 `data.get("atoms", [])` 各项 `zh` 建集合并缓存，非 None 时直接返回 `_ATOMS_ZH`。
def atoms_zh():
    """标准语义基准词表（atoms.json 的 zh 概念集，模块级缓存）。"""
    global _ATOMS_ZH
    if _ATOMS_ZH is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "atoms.json")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        _ATOMS_ZH = {a["zh"] for a in data.get("atoms", [])}
    return _ATOMS_ZH


# 生效条件：`text` 为 None 或空串时 `(text or "").split()` 得空序列、返回空列表 out；否则按空白切分后逐段经 `zh_en_atoms.segment` 展开 extend 进 out 并返回。
def semantic_atoms(text):
    """semantic 字段容错切分：按空格分段逐段贪心匹配。

    兼容「鱼油」（AI 给了复合词）与「鱼 油」（AI 直接给原子序列）两种
    写入形态——代码不二次加工 AI 产物，只在读取面做无损容错解析。
    未映射字符原样保留（归一可逆可溯源）。
    """
    out = []
    for part in (text or "").split():
        out.extend(zh_en_atoms.segment(part))
    return out


# 生效条件：`text` 传入后，返回 `semantic_atoms(text)` 结果中不属于 `atoms_zh()` 词表集合的 token 列表（无匹配项时为空列表）。
def oov_of(text):
    """OOV 审计：切分产物中不在标准词表的 token 列表（空列表=全部合法）。"""
    zh = atoms_zh()
    return [a for a in semantic_atoms(text) if a not in zh]


@functools.lru_cache(maxsize=256)
def query_atoms(text):
    """query 侧归一（同 semantic_atoms，缓存——每轮检索全 doc 复用）。

    英文 query 汇入同一标准真源（2026-09-14）：含 [A-Za-z] 时先经
    en_normalizer 归一为中文语素（复合概念整词映射，beef→牛肉），中文
    语素再经 segment 展开为标准原子（「牛肉」→「牛 肉」，与 doc 侧
    fm.semantic 的原子形态同构），英文保留词（专名/未登录词）原样
    占位——是词表覆盖边界，非错误。纯中文 query 零变化（不触发英文
    分支）。归一失败静默保持原文本（与 en_zh_terms 同降级风格）。
    """
    t = text or ""
    if re.search(r"[A-Za-z]", t):
        try:
            from .en_normalizer import normalize_en_query
            terms, _detail = normalize_en_query(t)
            out = []
            for term in terms:
                if re.search(r"[A-Za-z]", term):
                    out.append(term)                        # 英文保留词原样
                else:
                    out.extend(zh_en_atoms.segment(term))   # 中文语素→标准原子
            return tuple(out)
        except Exception:
            pass
    return tuple(semantic_atoms(t))


# 生效条件：`doc_semantic` 经 `semantic_atoms` 切分后相邻原子对集合 pairs 为空（单原子或无原子）时返回 0.0；否则以 `query_atoms(qtext)` 建立 token→位置表，统计两原子位置差绝对值 ≤ `win`（默认形参 WIN）的命中对数 hit，返回 hit/len(pairs)。
def pair_hits(doc_semantic, qtext, win=WIN):
    """组合窗口共现命中率 ∈ [0,1]。

    doc 侧：fm.semantic 的相邻原子对集合（标准语义基准上的组合结构）；
    query 侧：query_atoms(qtext) 归一序列；
    命中：对内两原子在 query 序列中窗口 win 内共现。
    分数 = 命中对数 / doc 对数；doc 无相邻对（单原子摘要）→ 0.0（诚实）。
    """
    doc = semantic_atoms(doc_semantic)
    pairs = {(doc[i], doc[i + 1]) for i in range(len(doc) - 1)}
    if not pairs:
        return 0.0
    q = query_atoms(qtext)
    qset = set(q)
    idx = {}
    for i, t in enumerate(q):
        idx.setdefault(t, []).append(i)
    hit = 0
    for a, b in pairs:
        if a not in qset or b not in qset:
            continue
        if any(abs(i - j) <= win for i in idx[a] for j in idx[b]):
            hit += 1
    return hit / len(pairs)
