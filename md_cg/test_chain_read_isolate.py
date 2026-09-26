# -*- coding: utf-8 -*-
"""读隔离守卫：因果链面（causal_chain / explain_chain / causal_path / 检索
chain 路 provenance）不得泄漏不可见节点。

缺陷形态（2026-09-25 检索域新发现，报告编号 N130 与他域冲突，以 where 定位，
high）：MdCGOS.causal_chain / explain_chain（mdcos.py:3491-3506）裸转调
chain.walk / chain.explain，causal_path（mdcos.py:3544→predict.py:1020）BFS
直用 chain.adjacency——而 chain.adjacency（chain.py:127-159）以 cg.index 全量
节点 frontmatter 建出边表，全程不经 cg.get / MdCGSecure._readable。任何持
read op 的低权令牌（ROLE_SPECS 全表 ops_allow 均含 read；mdcg_causal 的
_MDCG_OP_REQUIRE 即为 "read"）可：①对不可见节点起链；②看到链上不可见节点
id、边条件文本与下游拓扑；③检索 chain 路 provenance（_path_chain→
expand_from_seeds，同走 adjacency）把全链与秘密条件文本附带在可见节点条目上。

修复：在 chain.adjacency 单点接可见性闸——cg 提供 `_chain_visible(nid)` 谓词
（MdCGSecure 注入 = 索引有条目 ∧ _readable(e)；基类不注入行为零变化）时，
不可见节点的出边整体不入表、可见节点指向不可见目标的边截断、层级合成边同
闸；缓存键带上闸存在位。单点覆盖 walk / explain / causal_path /
expand_from_seeds（检索 chain 路 provenance）全部消费者——比三方法各自覆盖
多堵住 provenance 面，且预测器其余 adjacency 消费者（causal roadmap /
共同父节点等）一并隔离。_readable 的绑定档判定恒用 principal.session
（mdcos.py:3901-3906），实例身份稳定，adjacency 缓存无跨身份串台面。

红项 = R1-R5（链/路径/解释/检索 provenance 四面泄漏复现）；
G 项锁语义不变（designer/admin 可见性不变、可见-可见边链照常展开、get 隔离
基线）。
运行：python -m md_cg.test_chain_read_isolate
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

try:
    from .mdcos import MdCGSecure
    from .security import Principal
except ImportError:                                  # 直接脚本运行
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

PASS = FAIL = 0
FAILS = []

_SECRET_COND = "Y侧秘密条件文本YY"
_SECRET_ID = "Y秘密"


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _body(name):
    return (f"# 功能名：{name}\n# 生效条件：无条件\n# 子功能：无\n"
            f"# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n正文。")


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_chain_iso_")
    try:
        root = os.path.join(tmp, "kg")
        # 写者：designer（can_admin → private 档可见），建链 X→Y→Z
        dw = Principal(actor="designer-1", role="designer", can_write=True,
                       can_admin=True, clearance="secret")
        cg = MdCGSecure(root, principal=dw, master_key=bytes(range(32)))
        cg.add("X苹果", _body("X苹果"), layer="knowledge", sensitivity="internal",
               edges=[{"target": _SECRET_ID, "relation_type": "causal",
                       "condition": _SECRET_COND, "confidence": 0.9}])
        cg.add(_SECRET_ID, _body("Y秘密"), layer="knowledge", sensitivity="private",
               edges=[{"target": "Z结论", "relation_type": "causal",
                       "condition": "到Z的显性条件", "confidence": 0.9}])
        cg.add("Z结论", _body("Z结论"), layer="knowledge", sensitivity="internal")
        # 可见-可见对照链：A内→B内（reader 应照常展开）
        cg.add("A内", _body("A内"), layer="knowledge", sensitivity="internal",
               edges=[{"target": "B内", "relation_type": "causal",
                       "condition": "显性条件AB", "confidence": 0.8}])
        cg.add("B内", _body("B内"), layer="knowledge", sensitivity="internal")
        cg.close()

        # 读者：record 角色，clearance=internal（低于 private），异会话
        rd = Principal(actor="reader-1", role="record", can_write=True,
                       can_admin=False, clearance="internal",
                       layers_allow=["knowledge"], ops_allow=["read"])
        r = MdCGSecure(root, principal=rd, master_key=bytes(range(32)))

        # R0 基线：get 读隔离本就生效（旧码即过，锁语义）
        ok(r.get(_SECRET_ID) is None, "R0 基线：reader.get(Y秘密) 隔离生效")

        # R1 链展开：不可见中转节点 id + 边条件文本不得出现在链输出
        chains = r.causal_chain("X苹果")
        blob = repr(chains)
        ok(_SECRET_ID not in blob,
           "R1a causal_chain(X苹果) 输出不含不可见节点 id")
        ok(_SECRET_COND not in blob,
           "R1b causal_chain(X苹果) 输出不含秘密边条件文本")

        # R2 不可见节点起链：应与节点不存在同形（空链）
        ok(r.causal_chain(_SECRET_ID) == [],
           "R2 causal_chain(Y秘密) 不可见起点返回空链")

        # R3 解释面：同源 walk，渲染输出不得带秘密
        ex = r.explain_chain("X苹果")
        ok(_SECRET_ID not in repr(ex) and _SECRET_COND not in repr(ex),
           "R3 explain_chain(X苹果) 渲染输出零泄漏")

        # R4 因果路径：经不可见中转的路径不可达
        cp = r.causal_path("X苹果", "Z结论")
        ok(not cp.get("reachable") and _SECRET_ID not in repr(cp)
           and _SECRET_COND not in repr(cp),
           "R4 causal_path(X苹果→Z结论) 不可达且零泄漏")

        # R5 检索 chain 路：provenance/chain 字段（evidence ⑤ 所指）不得携带
        # 不可见全链。注意范围：可读节点**自身 frontmatter 的 edges 元数据**
        # 随节点视图返回是另一回事（读者本就可读该节点的 md 原文），不在
        # 本缺陷（链展开面）范围。prov 形态：nid → [{"path","rank",
        # "chain"?,"conditions"?}, …]；结果 4 元组第 4 位同源。
        res, meta = r.search_rrf("苹果", paths=("lexical", "chain"), record=False)
        chain_fields = []
        for entries in ((meta or {}).get("provenance") or {}).values():
            chain_fields.extend(en for en in entries
                                if isinstance(en, dict) and en.get("chain"))
        for t in res:
            if isinstance(t, tuple) and len(t) >= 4 and isinstance(t[3], list):
                chain_fields.extend(en for en in t[3]
                                    if isinstance(en, dict) and en.get("chain"))
        ok(all(_SECRET_ID not in repr(en.get("chain")) for en in chain_fields),
           "R5a search_rrf provenance 链不含不可见节点 id")
        ok(all(_SECRET_COND not in repr(en.get("conditions"))
               for en in chain_fields),
           "R5b search_rrf provenance 条件不含秘密文本")

        # G1 可见-可见链照常展开（闸不误伤本职语义）
        ok(r.causal_chain("A内") != [],
           "G1a reader 对可见链 A内→B内 照常展开")
        ok("显性条件AB" in repr(r.causal_chain("A内")),
           "G1b 可见边条件文本照常返回")

        # G2 designer/admin 可见性不变（private 档链对设计者完整可见）
        cg2 = MdCGSecure(root, principal=dw, master_key=bytes(range(32)))
        dch = cg2.causal_chain("X苹果")
        ok(any(_SECRET_ID in c.get("nodes", []) for c in dch),
           "G2a designer causal_chain 照常含 private 节点（admin 可见性不变）")
        ok(any(_SECRET_COND in c.get("conditions", []) for c in dch),
           "G2b designer 照常见到边条件文本")
        cg2.close()
        r.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
