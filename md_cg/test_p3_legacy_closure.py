# -*- coding: utf-8 -*-
"""P3 遗留四条闭环守卫（A 融合口径披露 / B S3 不变量读数 / C 缺省路集分叉 / D ④部分满足）。

来源：设计稿 §5.4 / §6.2 / §6.3 与交接单「P3 遗留四条·必须在本批闭环」。
四条各缺一条即不得收口，故**每条一个断言组**：

  A **默认 recall 的融合口径由 sum 变 max**（`use_causal` 缺省 True）——
      A1 判据单点 `mcp_server.recall_fusion_default` 的取值断言（缺省态 == "max"，
         显式关因果 == None；`use_temporal` **不入判据**）；
      A2 同一确定性库上「默认 vs 显式 sum」的 top-k 读数**逐条不同**（分数与名次）；
      A3 默认调用点确实走该单点（源码断言：`fusion = a.get("fusion") or
         recall_fusion_default(...)`）。
  B **S3 不变量 ① 与 ⑥ 的读数缺口**——
      B1 ①「种子取自过 S1/S2 门控的命中」：因果路**种子** ⊆ 已过门控的候选面
         （`entries`），且因果路**输出** ⊆ 候选面（两条断言，实跑）。
      B2 ⑥「不走全表」实测不成立 ⇒ 如实降级声明：`chain.adjacency` **不读正文**
         （读盘调用计数 == 0），但邻接构建为 **O(N) 索引条目级**——给代价读数
         （N 条目的冷建耗时），并断言文档/注释里**不再**把「不走全表」当作
         对 `adjacency` 成立的表述。
  C **Rust 侧缺省路集分叉**（如实披露，**不得**声称对拍通过）——
      Rust `EngineConfig::default{paths:None}` 字面量 == 四路；
      Python `search_rrf` 缺省 == 六路；两者**不相等**（分叉登记）。
  D **S3 ④ 只部分满足**——类型集可配（`MDCG_CHAIN_TYPES`）、权重沿用唯一表
      `EDGE_WEIGHTS`、方向固定为依赖方向（出边）——逐条断言，并断言措辞已改准。

运行：
    python -X utf8 -m md_cg.test_p3_legacy_closure
    python -X utf8 -m md_cg.test_p3_legacy_closure --mutate
    python -X utf8 -m md_cg.test_p3_legacy_closure --mutate --list

退出码：0 全绿；1 有失败 / 变异未按预期转红；2 ANCHOR-MISS。
"""
from __future__ import annotations

import inspect
import os
import re
import statistics
import sys
import tempfile
import time

_TMP0 = tempfile.mkdtemp(prefix="p3_legacy_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP0, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "34" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP0, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP0, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "MDCG_RETRIEVAL_PIPELINE", "MDCG_POOLING", "MDCG_FRESHNESS",
           "MDCG_CHAIN_TYPES"):
    os.environ.pop(_k, None)

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from md_cg import chain                                        # noqa: E402
from md_cg import mcp_server as MS                             # noqa: E402
from md_cg import mdcg as M                                    # noqa: E402
from md_cg import subgraph as SG                               # noqa: E402
from md_cg.mdcos import MdCGOS                                 # noqa: E402

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")
    return bool(cond)


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


_CCG = ("# 功能名：{n}\n# 生效条件：无条件\n# 子功能：无\n# 执行：占位\n"
        "# 验证方式：compiler 复现\n# 不适用条件：其它会话\n\n{t}\n")


def _fusion_lib():
    """受控库：两路共识 vs 单路更好名次——sum 与 max 的 top-k 序列在此分开。"""
    root = tempfile.mkdtemp(prefix="p3_fuse_")
    cg = MdCGOS(root)
    cg.add("m_aa", _CCG.format(n="m_aa", t="苹果 别的内容 章节 分离"),
           layer="knowledge", tags=["苹果"], importance=0.5)
    cg.add("m_zz", _CCG.format(n="m_zz", t="苹果 别的内容 章节 分离"),
           layer="knowledge", tags=["苹果"], importance=0.9)
    cg.add("m_lex", _CCG.format(n="m_lex", t="苹果章节 同构"),
           layer="knowledge", importance=0.5)
    cg.add("m_other", _CCG.format(n="m_other", t="苹果 别的内容 章节 分离 更多"),
           layer="knowledge", importance=0.5)
    cg.flush()
    return root, cg


def _chain_lib(n_seed=3, n_other=6):
    root = tempfile.mkdtemp(prefix="p3_chain_")
    cg = MdCGOS(root)
    for i in range(n_seed):
        cg.add(f"s{i}", _CCG.format(n=f"s{i}", t="苹果 章节 种子"),
               layer="knowledge", importance=0.5,
               edges=[{"target": f"t{i}", "relation_type": "causal",
                       "confidence": 0.9}])
        cg.add(f"t{i}", _CCG.format(n=f"t{i}", t="下游 结论"),
               layer="knowledge", importance=0.5)
    for i in range(n_other):
        cg.add(f"o{i}", _CCG.format(n=f"o{i}", t="无关 其它"),
               layer="knowledge", importance=0.5)
    # 负记忆层节点：**不在** `_candidates` 的候选面（NEG_ROUTE_LAYERS）——
    # 有它，不变量①「种子 ⊆ 已过门控的候选面」才有判别力
    cg.add("rj1", _CCG.format(n="rj1", t="苹果 章节 被否决的假设"),
           layer="rejected", importance=0.0)
    cg.flush()
    return root, cg


def ga_fusion():
    print("== A 默认 recall 融合口径 sum→max（披露 + 判据 + 读数）==")
    check("A1 判据单点：缺省（use_causal=True）→ max",
          MS.recall_fusion_default(False, False, False, True) == "max",
          str(MS.recall_fusion_default(False, False, False, True)))
    check("A1 显式关因果且其余全关 → None（回到 search_rrf 的 sum 缺省）",
          MS.recall_fusion_default(False, False, False, False) is None)
    check("A1 use_temporal 不入判据（时间路是排名项，非单路独有召回型）",
          MS.recall_fusion_default(False, False, False, False, True) is None
          and MS.recall_fusion_default(False, False, False, True, True) == "max")
    src = _src(os.path.join("md_cg", "mcp_server.py"))
    check("A3 默认调用点走判据单点",
          "fusion = a.get(\"fusion\") or recall_fusion_default(" in src)
    check("A3 use_causal 缺省 True（披露的根因）",
          "use_causal = True if use_causal is None else bool(use_causal)" in src)
    root, cg = _fusion_lib()
    try:
        def top(**kw):
            pack = MS._dispatch(cg, "mdcg_recall",
                                dict({"query": "苹果 章节", "k": 5}, **kw))
            return [[it.get("id"), it.get("score")]
                    for it in (pack.get("pack") or [])]
        d = top()
        s = top(fusion="sum")
        mx = top(fusion="max")
        print(f"     default={d}")
        print(f"     sum    ={s}")
        print(f"     max    ={mx}")
        check("A2 默认口径 == max（逐条相同）", d == mx, f"{d} vs {mx}")
        check("A2 默认口径 ≠ sum（逐条不同：分数或名次）", d != s, f"{d} vs {s}")
        check("A2 top-1 名次在 sum/max 下不同（口径差可观测）",
              bool(d) and bool(s) and d[0][0] != s[0][0],
              f"{d[:1]} vs {s[:1]}")
    finally:
        cg.close()


def gb_s3_invariants():
    print("== B S3 不变量 ①⑥ 读数（种子 ⊆ 门控面 / 邻接代价）==")
    root, cg = _chain_lib()
    try:
        # ① 因果路种子 ⊆ 已过 S1/S2 门控的候选面（entries）
        seen = {}
        orig = chain.expand_from_seeds

        def spy(cg_, seeds, **kw):
            seen["seeds"] = list(seeds.items()) if isinstance(seeds, dict) \
                else list(seeds or [])
            return orig(cg_, seeds, **kw)

        chain.expand_from_seeds = spy
        try:
            res, meta = cg.search_rrf("苹果 章节", k=8, record=False,
                                      paths=("lexical", "chain"))
        finally:
            chain.expand_from_seeds = orig
        ent_ids = {e["path"].split("/")[-1][:-3] for e in cg._candidates()}
        seed_ids = {nid for nid, _s in (seen.get("seeds") or [])}
        check("① 因果路种子非空（夹具前提）", bool(seed_ids), str(seen))
        check("① 种子 ⊆ 已过门控的候选面（entries）",
              seed_ids <= ent_ids, f"{seed_ids - ent_ids}")
        out_ids = {r[0]["id"] for r in res}
        check("① 因果路输出 ⊆ 候选面（不得引入未过门控的节点）",
              out_ids <= ent_ids, f"{out_ids - ent_ids}")
        check("① 因果路确实产出（下游 t* 被召回）",
              any(i.startswith("t") for i in out_ids), str(sorted(out_ids)))

        # ⑥ 邻接：不读正文（读盘计数 == 0）+ O(N) 索引条目级代价读数
        calls = {"n": 0}
        orig_read, orig_get = M.MdCG._read, M.MdCG.get

        def rd(self, *a, **kw):
            calls["n"] += 1
            return orig_read(self, *a, **kw)

        def gt(self, *a, **kw):
            calls["n"] += 1
            return orig_get(self, *a, **kw)

        M.MdCG._read, M.MdCG.get = rd, gt
        try:
            cg._chain_adj = None
            adj = chain.adjacency(cg)
        finally:
            M.MdCG._read, M.MdCG.get = orig_read, orig_get
        check("⑥ 邻接构建不读正文/不读盘（读盘调用计数 == 0）",
              calls["n"] == 0, f"reads={calls['n']}")
        # 代价读数：N 条目冷建耗时（夹具 N=9；再取一个 400 条目的规模读）
        big = tempfile.mkdtemp(prefix="p3_adj_")
        cg2 = MdCGOS(big)
        N = 400
        for i in range(N):
            cg2.add(f"n{i:04d}", _CCG.format(n=f"n{i:04d}", t="苹果 章节"),
                    layer="knowledge", importance=0.5,
                    edges=[{"target": f"n{(i + 1) % N:04d}",
                            "relation_type": "causal"}])
        cg2.flush()
        cg2._chain_adj = None
        t0 = time.perf_counter()
        adj2 = chain.adjacency(cg2)
        dt = time.perf_counter() - t0
        print(f"     代价读数：N={N} 条目，cold adjacency = {dt * 1000:.3f} ms"
              f"（邻接源数 {len(adj2)}）")
        check("⑥ O(N) 条目级代价（400 条目冷建 < 200ms，宽松上界）",
              dt < 0.2, f"{dt:.4f}s")
        cg2.close()
        # 文档/注释措辞：不得把「不走全表」当作对 adjacency 成立的表述
        ch = _src(os.path.join("md_cg", "chain.py"))
        check("⑥ chain.adjacency 注释已改为「不读正文；O(N) 索引条目级」",
              "邻接构建为 O(N) 索引条目级" in ch)
        ct = _src(os.path.join("docs", "hive", "检索路径与认知结构契约_v0.1.md"))
        check("⑥ 契约文档已改正（含代价读数与可选硬化路径）",
              "不读正文；\n  邻接构建为 O(N) 索引条目级" in ct
              or "邻接构建为 O(N) 索引条目级" in ct)
        check("⑥ 契约文档不再出现无条件的「不走全表」断言",
              "扩散 N 跳、按跳数衰减；不走全表" not in ct)
    finally:
        cg.close()


def gc_lang_divergence():
    print("== C 缺省路集分叉：Rust 四路 vs Python 六路（登记，非对拍通过）==")
    eng = _src(os.path.join("rust", "src", "engine.rs"))
    m = re.search(r"cfg\.paths\.clone\(\)\.unwrap_or_else\(\|\|\s*\{(.*?)\}\)",
                  eng, re.S)
    check("C Rust 缺省 paths 字面量可解析", m is not None)
    rust_paths = re.findall(r'"([a-z_]+)"\.to_string\(\)', m.group(1)) if m else []
    check("C Rust 缺省 == 四路（lexical/bucket/entity/graph）",
          rust_paths == ["lexical", "bucket", "entity", "graph"],
          str(rust_paths))
    py_default = inspect.signature(MdCGOS.search_rrf).parameters["paths"].default
    check("C Python search_rrf 缺省 == 六路",
          tuple(py_default) == ("lexical", "bucket", "entity", "graph",
                                "chain", "temporal"), str(py_default))
    check("C 两侧缺省**不相等**（分叉为已知边界，不得声称对拍通过）",
          set(rust_paths) != set(py_default), f"{rust_paths} vs {list(py_default)}")
    check("C 契约文档已登记该分叉（§4.2）",
          "读侧**语言面**分叉" in _src(os.path.join(
              "docs", "hive", "检索路径与认知结构契约_v0.1.md")))
    # mdcg_recall 缺省构造：paths=None（交给 mdcos 六路缺省）
    ms = _src(os.path.join("md_cg", "mcp_server.py"))
    check("C mdcg_recall 缺省把 paths 交给 mdcos（paths = None）",
          "paths = None          # 缺省六路" in ms)


def gd_s3_partial():
    print("== D S3 ④ 部分满足：类型集可配 / 权重唯一表 / 方向固定 ==")
    ch = _src(os.path.join("md_cg", "chain.py"))
    check("D 类型集可配（env MDCG_CHAIN_TYPES）",
          'CHAIN_TYPES_ENV = "MDCG_CHAIN_TYPES"' in ch
          and callable(chain.chain_types_from_env))
    os.environ["MDCG_CHAIN_TYPES"] = "reference,causal"
    try:
        check("D 类型集生效且只含已登记类型",
              chain.chain_types_from_env() == ("reference", "causal"),
              str(chain.chain_types_from_env()))
    finally:
        os.environ.pop("MDCG_CHAIN_TYPES", None)
    os.environ["MDCG_CHAIN_TYPES"] = "不存在的类型"
    try:
        check("D 非法类型集回落缺省（剔除即回落，不静默走未知边）",
              chain.chain_types_from_env() == chain.CHAIN_TYPES_DEFAULT)
    finally:
        os.environ.pop("MDCG_CHAIN_TYPES", None)
    check("D 权重沿用**唯一表** EDGE_WEIGHTS（无第二份边权表）",
          "EDGE_WEIGHTS = {" in ch
          and ch.count("EDGE_WEIGHTS.get(") >= 1
          and "def edge_weight(edge)" in ch)
    check("D 类型集只从 EDGE_WEIGHTS 里挑子集（t in EDGE_WEIGHTS）",
          "if t in EDGE_WEIGHTS" in ch)
    sig = inspect.signature(chain.walk).parameters
    check("D 方向固定为依赖方向（出边）：walk 缺省 direction == 'out'",
          sig["direction"].default == "out", str(sig["direction"].default))
    check("D 措辞已改准（docstring 写明「部分满足」与三件口径）",
          "可配面边界" in ch and "**部分满足**" in ch
          and "**方向**：固定为**依赖方向（出边）**" in ch
          and "沿用**唯一表** `EDGE_WEIGHTS`" in ch)
    ct = _src(os.path.join("docs", "hive", "检索路径与认知结构契约_v0.1.md"))
    check("D 契约文档已把 S3 ④ 标为部分满足",
          "**部分满足**" in ct and "边权数值" in ct)


# --------------------------------------------------------------------------
# 定点变异（只改本进程内存对象/临时输入，绝不改仓库文件）
# --------------------------------------------------------------------------

def _mut_fusion_causal_dropped():
    orig = MS.recall_fusion_default

    def no_causal(use_fuzzy, use_semantic, use_goal, use_causal,
                  use_temporal=False):
        return "max" if (use_fuzzy or use_semantic or use_goal) else None
    MS.recall_fusion_default = no_causal

    def restore():
        MS.recall_fusion_default = orig
    return restore


def _mut_chain_seed_all():
    """把因果路种子改成「全库节点」——不变量 ① 应当立刻变红。"""
    orig = MdCGOS._path_chain

    def polluted(self, query, entries, seeds, context=None, **kw):
        # 未过门控的节点**排在前 8**（`_path_chain` 只取 seeds[:8]）——
        # 这正是「种子引入了未过 S1/S2 门控的节点」这一违规形态
        ent = {id(e) for e in entries}
        nodes = list((self.index.get("nodes") or {}).items())
        allseeds = [({"id": nid}, 1.0) for nid, e in nodes
                    if id(e) not in ent]
        allseeds += [({"id": nid}, 1.0) for nid, e in nodes if id(e) in ent]
        return orig(self, query, entries, allseeds, context, **kw)
    MdCGOS._path_chain = polluted

    def restore():
        MdCGOS._path_chain = orig
    return restore


def _mut_adjacency_reads():
    """让邻接构建读正文（走 cg.get）——「不读正文」断言应当变红。"""
    orig = SG._fm

    def slow(cg_, nid):
        node = cg_.get(nid)
        return (node or {}).get("frontmatter") or {}
    SG._fm = slow

    def restore():
        SG._fm = orig
    return restore


def _mut_py_default_paths():
    """把 mdcos.search_rrf 的 paths 缺省改成四路（源码复制体上验证）。"""
    orig = MdCGOS.search_rrf.__defaults__

    def restore():
        MdCGOS.search_rrf.__defaults__ = orig
    args = list(orig)
    for i, a in enumerate(args):
        if isinstance(a, tuple) and "chain" in a:
            args[i] = ("lexical", "bucket", "entity", "graph")
    MdCGOS.search_rrf.__defaults__ = tuple(args)
    return restore


_MUTATIONS = [
    ("fusion_drop_causal", "融合判据丢掉 use_causal（缺省退化为 sum）",
     _mut_fusion_causal_dropped),
    ("chain_seeds_all", "因果路种子改成全库节点且未过门控者排前（不变量①应红）",
     _mut_chain_seed_all),
    ("adjacency_reads_body", "邻接构建改成读正文（不变量⑥应红）",
     _mut_adjacency_reads),
    ("py_default_four_paths", "Python 缺省路集改成四路（分叉登记应红）",
     _mut_py_default_paths),
]


def _collect():
    global PASS, FAIL, FAILS
    PASS, FAIL, FAILS = 0, 0, []
    ga_fusion()
    gb_s3_invariants()
    gc_lang_divergence()
    gd_s3_partial()
    return list(FAILS)


def main(argv):
    if "--mutate" in argv:
        if "--list" in argv:
            for name, desc, _fn in _MUTATIONS:
                print(f"  {name:24s} {desc}")
            return 0
        base = _collect()
        if base:
            print(f"\n!! 基线不绿（{len(base)} 条）：{base}")
            return 1
        bad = []
        for name, desc, fn in _MUTATIONS:
            try:
                restore = fn()
            except (AttributeError, StopIteration) as exc:
                print(f"  ANCHOR-MISS {name}: {exc}")
                return 2
            got = _collect()
            restore()
            if got:
                print(f"  MUTATE-OK {name}（{desc}）→ 转红 {len(got)} 条：{got[:3]}")
            else:
                bad.append(name)
                print(f"  MUTATE-FAIL {name}（{desc}）→ 仍全绿")
        print(f"\ntest_p3_legacy_closure --mutate: "
              f"{len(_MUTATIONS) - len(bad)}/{len(_MUTATIONS)} 变异按预期转红")
        return 0 if not bad else 1
    fails = _collect()
    print(f"\ntest_p3_legacy_closure: {PASS} 通过 / {FAIL} 失败")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
