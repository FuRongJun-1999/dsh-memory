# -*- coding: utf-8 -*-
"""md_cg · t66a（T66 分池）守卫：三池定义完整互斥 / 层→池归类 / 跨池查询规则 /
与既有保护面联动 / 默认关回归。

判据结构（对应交办 ACCEPT 的 (A)~(E)）：
  (A) 三池定义完整互斥：POOLS 恰为 ('short','long','persona')；POOL_LAYERS
      并集==mdcg.LAYERS 全集、两两交集为空（≥4 断言）。
  (B) pool_of 对全部 8 层逐一归类正确（≥8 断言）。
  (C) 跨池查询规则：默认 query_layers() 返回 long 层集且不含
      self/anchor/rejected/unresolved/goals/contextual；显式 query_layers('persona')
      /('short') 返回对应层集；persona 不在默认召回（≥6 断言）。
  (D) 与既有保护面联动：persona 层集==protect.PROTECTED_LAYERS；short 层集
      ⊇mdcg.NEG_ROUTE_LAYERS；未知层抛 ValueError（≥4 断言）。
  (E) 默认关回归：import store_pools 不改 mdcg.LAYERS / protect.PROTECTED_LAYERS
      值（在 import 前先取前值，改前改后一致，≥2 断言）。

运行：python -X utf8 -m md_cg.test_t66a_store_pools
"""
from __future__ import annotations

import sys

from . import mdcg, protect

# ---- 默认关回归前值：先于 import store_pools 取快照（若 import 改了值，E 组即红）----
_LAYERS_BEFORE = tuple(mdcg.LAYERS)
_PROTECTED_BEFORE = tuple(protect.PROTECTED_LAYERS)

from . import store_pools  # noqa: E402

_PASS = []
_FAIL = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


# ---------------------------------------------------------------- (A) 三池完整互斥
def g_a():
    print("== A 三池定义完整互斥 ==")
    ok(tuple(store_pools.POOLS) == ("short", "long", "persona"),
       "A1 POOLS 恰为 ('short','long','persona')", store_pools.POOLS)
    union = frozenset().union(*[frozenset(v)
                                for v in store_pools.POOL_LAYERS.values()])
    ok(union == frozenset(mdcg.LAYERS),
       "A2 三池并集 == mdcg.LAYERS 全集（8 层全部落池）",
       sorted(union))
    short, long_, persona = (frozenset(store_pools.POOL_LAYERS[p])
                             for p in store_pools.POOLS)
    ok(not (short & long_), "A3 short∩long = ∅", sorted(short & long_))
    ok(not (short & persona), "A4 short∩persona = ∅", sorted(short & persona))
    ok(not (long_ & persona), "A5 long∩persona = ∅", sorted(long_ & persona))


# ---------------------------------------------------------------- (B) 层→池归类
_EXPECT_POOL = {
    "anchor": "persona", "self": "persona",
    "structural": "long", "knowledge": "long",
    "contextual": "short", "rejected": "short",
    "unresolved": "short", "goals": "short",
}


def g_b():
    print("== B pool_of 对全部 8 层逐一归类 ==")
    for i, layer in enumerate(mdcg.LAYERS, 1):
        got = store_pools.pool_of(layer)
        ok(got == _EXPECT_POOL[layer],
           "B%d pool_of(%r) == %r" % (i, layer, _EXPECT_POOL[layer]), got)


# ---------------------------------------------------------------- (C) 跨池查询规则
def g_c():
    print("== C 跨池查询规则 ==")
    default = store_pools.query_layers()
    ok(frozenset(default) == frozenset(store_pools.POOL_LAYERS["long"]),
       "C1 默认 query_layers() 返回 long 池层集", default)
    excluded = ("self", "anchor", "rejected", "unresolved", "goals", "contextual")
    ok(all(l not in default for l in excluded),
       "C2 默认召回不含 persona/short 层：self/anchor/rejected/unresolved/"
       "goals/contextual 均缺席")
    ok(frozenset(store_pools.query_layers("persona"))
       == frozenset(store_pools.POOL_LAYERS["persona"]),
       "C3 显式 query_layers('persona') 返回 persona 层集",
       store_pools.query_layers("persona"))
    ok(frozenset(store_pools.query_layers("short"))
       == frozenset(store_pools.POOL_LAYERS["short"]),
       "C4 显式 query_layers('short') 返回 short 层集",
       store_pools.query_layers("short"))
    ok(tuple(store_pools.DEFAULT_RECALL_POOLS) == ("long",),
       "C5 DEFAULT_RECALL_POOLS 恰为 ('long',)——默认召回只碰长期池",
       store_pools.DEFAULT_RECALL_POOLS)
    ok(all(l not in store_pools.query_layers()
           for l in store_pools.POOL_LAYERS["persona"]),
       "C6 persona 池不在默认召回（需显式跨池才取得到）")
    try:
        store_pools.query_layers("nope")
        ok(False, "C7 未知池名抛 ValueError")
    except ValueError:
        ok(True, "C7 未知池名抛 ValueError")


# ---------------------------------------------------------------- (D) 与既有保护面联动
def g_d():
    print("== D 与既有保护面联动 ==")
    ok(frozenset(store_pools.POOL_LAYERS["persona"])
       == frozenset(protect.PROTECTED_LAYERS),
       "D1 persona 层集 == protect.PROTECTED_LAYERS")
    ok(frozenset(store_pools.POOL_LAYERS["short"])
       >= frozenset(mdcg.NEG_ROUTE_LAYERS),
       "D2 short 层集 ⊇ mdcg.NEG_ROUTE_LAYERS（负路由三层全落 short）")
    ok(all(store_pools.pool_of(l) == "persona" for l in protect.PROTECTED_LAYERS),
       "D3 PROTECTED_LAYERS 各层 pool_of 均归 persona")
    ok(all(store_pools.pool_of(l) == "short" for l in mdcg.NEG_ROUTE_LAYERS),
       "D4 NEG_ROUTE_LAYERS 各层 pool_of 均归 short（不进正排的层都归 short）")
    try:
        store_pools.pool_of("not_a_layer")
        ok(False, "D5 未知层抛 ValueError")
    except ValueError:
        ok(True, "D5 未知层抛 ValueError")


# ---------------------------------------------------------------- (E) 默认关回归
def g_e():
    print("== E 默认关回归：import store_pools 不改既有常量 ==")
    ok(tuple(mdcg.LAYERS) == _LAYERS_BEFORE,
       "E1 import store_pools 前后 mdcg.LAYERS 逐位一致", mdcg.LAYERS)
    ok(tuple(protect.PROTECTED_LAYERS) == _PROTECTED_BEFORE,
       "E2 import store_pools 前后 protect.PROTECTED_LAYERS 逐位一致",
       protect.PROTECTED_LAYERS)


_GROUPS = (g_a, g_b, g_c, g_d, g_e)


def main() -> int:
    for g in _GROUPS:
        g()
    n_pass, n_fail = len(_PASS), len(_FAIL)
    print("\n===== t66a store pools：%d 通过，%d 失败 =====" % (n_pass, n_fail))
    if _FAIL:
        print("失败项：" + "、".join(_FAIL))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())