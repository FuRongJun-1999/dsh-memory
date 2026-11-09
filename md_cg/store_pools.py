# -*- coding: utf-8 -*-
"""md_cg · 三池规则面（T66 分池）：short / long / persona 的层归属与跨池查询规则。

本模块是**规则面**：只做层→池的登记与跨池查询的层集取数。**不装机进检索、
不扫库、无任何全局副作用**——import 它唯一触发的动作是内存内的同源自检
（``_self_check``，见文件尾部），不写盘、不改检索面、不注册任何钩子。

三池语义
--------
  ``POOLS = ('short', 'long', 'persona')``
    · short   短期（用完即弃）：contextual / rejected / unresolved / goals
    · long    长期（留住）：knowledge / structural
    · persona 人格原料（单独一档）：self / anchor

映射来源（只读复用既有常量，不复制层清单，防漂移）
--------------------------------------------------
  · persona 直接取自 ``protect.PROTECTED_LAYERS``（('self','anchor')）——单一事实源；
  · short   由 ``mdcg.NEG_ROUTE_LAYERS``（rejected/unresolved/goals）∪ contextual 推导；
  · long    由 ``mdcg.LAYERS`` 全集减去 persona 与 short 的**补集**推导
    （knowledge/structural 随上游变动自动跟随，不写死层名清单）。
  三池并集 == ``mdcg.LAYERS`` 全集、两两交集为空——池靠层目录物理分开，
  映射可确定性验证（见 ``_self_check`` 与 test_t66a_store_pools.py）。

跨池查询规则
------------
  1. ``DEFAULT_RECALL_POOLS = ('long',)``：**默认召回只碰长期池**
     （knowledge+structural）；普通检索不混入 persona / short。
  2. ``query_layers(pool=None)``：None 时返回默认召回层集（仅 long 池各层）；
     **显式跨池 = 调用方显式传 pool 参数**（'short' / 'long' / 'persona'）取对应层集。
  3. persona 池（self/anchor）**仅身份/自我面显式访问**——对齐
     ``protect.PROTECTED_LAYERS`` 的保护语义（受保护层不被被动混进普通召回）。
  4. short 池（rejected/unresolved/goals）**不进正排**——对齐
     ``mdcg.NEG_ROUTE_LAYERS``（负记忆只作覆盖标记、goals 只作定向偏置，
     见 mdcg.py:42-46 注释口径）。
"""
from __future__ import annotations

from itertools import chain

from . import mdcg, protect

#: 三池名序固定（short→long→persona；各自语义见模块 docstring）
POOLS = ("short", "long", "persona")

# 只读复用既有常量——不复制层清单，防止与上游漂移
_PERSONA_SET = frozenset(protect.PROTECTED_LAYERS)
_SHORT_SET = frozenset(mdcg.NEG_ROUTE_LAYERS) | frozenset(("contextual",))
_LONG_SET = frozenset(mdcg.LAYERS) - _PERSONA_SET - _SHORT_SET


def _ordered(seq):
    """按 ``mdcg.LAYERS`` 顺序稳定排序：交集推导结果可复现、不依赖 set 迭代序。"""
    order = {layer: i for i, layer in enumerate(mdcg.LAYERS)}
    return tuple(sorted(seq, key=order.__getitem__))


#: 层 → 池 的映射。值为「按 LAYERS 序排列的层元组」；三池并集==LAYERS 全集、
#: 两两交集为空（同源自检于模块加载时兜底，见 _self_check）。
POOL_LAYERS = {
    "short": _ordered(_SHORT_SET),
    "long": _ordered(_LONG_SET),
    "persona": _ordered(_PERSONA_SET),
}

#: 默认召回只碰的池（默认查询层集 = 这些池的层并集）
DEFAULT_RECALL_POOLS = ("long",)


def pool_of(layer):
    """返回 ``layer`` 所属的池名；未知层抛 ``ValueError``。"""
    for pool in POOLS:
        if layer in POOL_LAYERS[pool]:
            return pool
    raise ValueError("未知层 %r（不在 mdcg.LAYERS 内）" % (layer,))


def query_layers(pool=None):
    """跨池查询的层集取数（规则见模块 docstring）。

    ``pool=None`` → 默认召回层集（``DEFAULT_RECALL_POOLS`` 各池层并集，仅 long 池）；
    显式传 ``'short'`` / ``'long'`` / ``'persona'`` → 该池对应层集（显式跨池）。
    """
    if pool is None:
        wanted = frozenset(chain.from_iterable(
            POOL_LAYERS[p] for p in DEFAULT_RECALL_POOLS))
        return _ordered(wanted)
    if pool not in POOLS:
        raise ValueError("未知池 %r（可用：%s）" % (pool, POOLS))
    return POOL_LAYERS[pool]


def _self_check():
    """同源自检（模块加载时执行，fail-closed）。

    只读复用 ``mdcg.LAYERS`` / ``protect.PROTECTED_LAYERS`` / ``mdcg.NEG_ROUTE_LAYERS``：
    三池并集==LAYERS 全集、两两交集为空、persona==PROTECTED_LAYERS、
    short⊇NEG_ROUTE_LAYERS。任一不成立 → AssertionError，import 即红。
    """
    assert frozenset(chain.from_iterable(POOL_LAYERS.values())) \
        == frozenset(mdcg.LAYERS), "三池并集 != mdcg.LAYERS 全集"
    for _a, _b in (("short", "long"), ("short", "persona"), ("long", "persona")):
        assert not (frozenset(POOL_LAYERS[_a]) & frozenset(POOL_LAYERS[_b])), \
            "%s 与 %s 池层集相交（三池须物理可分）" % (_a, _b)
    assert _PERSONA_SET == frozenset(protect.PROTECTED_LAYERS), \
        "persona 层集 != protect.PROTECTED_LAYERS"
    assert _SHORT_SET >= frozenset(mdcg.NEG_ROUTE_LAYERS), \
        "short 层集不包含 mdcg.NEG_ROUTE_LAYERS 全集"


_self_check()

__all__ = ["POOLS", "POOL_LAYERS", "DEFAULT_RECALL_POOLS", "pool_of",
           "query_layers"]