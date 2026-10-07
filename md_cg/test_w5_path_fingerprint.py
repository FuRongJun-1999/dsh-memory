# -*- coding: utf-8 -*-
"""W5 路线B 守卫：检索返回体的**路径指纹** `path_fingerprint`（只增不改 + 确定性 + 自洽）。

背景（`docs/eval/W5_标志线与融合核对_v0.1.md` §一、`docs/eval/设计者首批裁定_v0.1.md` 第 12 条）：
「路径感知」要达**全亮档**＝「单一可命名、运行时可自述的路径对象」。首版实证的局限
之一是「命名分散、无单一『路径指纹』对象」。本守卫守的就是这个新对象：

  path_fingerprint = {selection, recursion, paths, hash}
      · selection  选面（scanned / gates / fused / judge_filtered / early_stopped）
      · recursion  递归展开（因果路多跳：enabled / nodes / depth_max / hops_max）
      · paths      命中路（per_path ＋ 候选级 provenance，与既有 meta 键同源）
      · hash       三段排序归一后的确定性摘要（sha256，非内置 hash()）

覆盖：
  P1  在场 + 结构完整（三段均 dict、hash 为 16 位十六进制）
  P2  与既有字段**自洽**（paths.per_path≡meta["paths"]、paths.provenance≡meta["provenance"]、
      selection 与顶层 scanned/fused 对齐、recursion 与 provenance 里的链对齐）
  P3  确定性（同实例重复跑同 hash；**跨实例重开同库**同 hash；hash 判别力 +
      键序无关）
  P4  只增不改（既有顶层键仍在；检索结果不受影响：两次 id 序一致、仍为 4 元组）
  P5  透传面（recall().meta 带同 hash；热缓存命中面返回同 hash）
  P6  文档口径（紧邻「生效条件：」注释行 + docstring 声明确定性）

运行：
  python -X utf8 -m md_cg.test_w5_path_fingerprint            # 正向（P1–P6）
  python -X utf8 -m md_cg.test_w5_path_fingerprint --self-proof   # 定点变异自证

退出码（fail-closed）：
  0 = 全绿；1 = 有断言失败 / 变异未按预期转红 / 基线非 0 红；
  2 = **ANCHOR-MISS**（变异锚点在当前实现源码里找不到唯一命中——实现漂移必须硬失败）。

变异自证基线源 = **运行中的实现源码**（`inspect.getsource` 就地变异、就地复原），
**不读 git**——把基线绑到某个提交，下一次改动即失效（本仓既有教训）。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import shutil
import tempfile
import textwrap
import unicodedata

from . import mdcos as _mdcos
from .mdcos import (MdCGOS, build_path_fingerprint, PATH_FINGERPRINT_KEYS)

PASS = FAIL = 0
FAILS = []

#: 影响本次读数口径的进程级开关（逐条清理，防宿主残留值改变本次实测口径）。
_ENVS = ("MDCG_HOTCACHE", "MDCG_RETRIEVAL_PIPELINE", "MDCG_GATE_S1_DOMAIN",
         "MDCG_GATE_S1B_BUCKET", "MDCG_GATE_S2_COND", "MDCG_GATE_S4_LAYER",
         "MDCG_SEMANTIC", "MDCG_EN_ATOMS", "MDCG_UNIFY_QUERY",
         "MDCG_CHAIN_TYPES", "MDCG_BUCKET_MIN_SIM", "MDCG_BUCKET_TOPK")

QUERY = "记忆 认知 学习"

#: 变异自证锚在**真源文件**上（变异体由 exec 生成、没有源文件，getsource 会抛）。
_FP_FILE = inspect.getsourcefile(build_path_fingerprint)


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


class _Env:
    """临时设置进程级开关：进入先清 _ENVS 全量，再按需置值；退出逐键还原。"""

    def __init__(self, **kv):
        self.kv = kv
        self.old = {}

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in _ENVS}
        for k in _ENVS:
            os.environ.pop(k, None)
        for k, v in self.kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *_exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def _root():
    return unicodedata.normalize("NFC", tempfile.mkdtemp(prefix="mdcg_w5pf_"))


def build_lib(root):
    """确定性小库：三节点词法全命中 ＋ 两条 causal 边（使 chain 路非空 → 递归段可指认）。

    a1→a2→a3 的 causal 边让 chain 路从词法种子扩散出 a2/a3（多路命中），
    于是 fingerprint 的 paths.multi>0、recursion.chain.nodes>0 可被断言。
    """
    cg = MdCGOS(root)
    cg.add("a1", "# 功能名：甲\n# 生效条件：条件 A\n\n记忆 认知 学习 甲。",
           tags=["domain:认知心理"], big_domain="心理",
           edges=[{"target": "a2", "relation_type": "causal",
                   "confidence": 0.9, "condition": "甲在运行"}])
    cg.add("a2", "# 功能名：乙\n# 生效条件：条件 B\n\n记忆 认知 学习 乙。",
           tags=["domain:认知心理"], big_domain="心理",
           edges=[{"target": "a3", "relation_type": "causal",
                   "confidence": 1.0, "condition": "乙在运行"}])
    cg.add("a3", "# 功能名：丙\n# 生效条件：条件 C\n\n记忆 认知 学习 丙。",
           tags=["domain:认知心理"], big_domain="心理")
    cg.flush()
    return cg


def _read(root):
    """打开库取一次 (结果 id 序, meta)，用完即关。"""
    cg = MdCGOS(root)
    try:
        res, meta = cg.search_rrf(QUERY, k=5, judge=False, record=False,
                                  context=None)
        return [r[0]["id"] for r in res], meta, [len(r) for r in res]
    finally:
        cg.close()


def _group(root):
    """P1–P6 断言组（变异自证复用同组，故不依赖模块级实例）。"""
    fp = None
    ids, meta, arities = _read(root)
    fp = meta.get("path_fingerprint")

    # ---------------- P1 在场 + 结构 ----------------
    ok("P1.1 指纹在场（meta 有 path_fingerprint 键）", isinstance(fp, dict),
       str(type(fp)))
    if not isinstance(fp, dict):
        return
    ok("P1.2 结构完整（三段 selection/recursion/paths 均 dict）",
       all(isinstance(fp.get(k), dict) for k in PATH_FINGERPRINT_KEYS),
       str({k: type(fp.get(k)).__name__ for k in PATH_FINGERPRINT_KEYS}))
    hs = fp.get("hash")
    ok("P1.3 hash 为 16 位十六进制（sha256 前缀，非内置 hash()）",
       isinstance(hs, str) and len(hs) == 16
       and all(c in "0123456789abcdef" for c in hs), repr(hs))

    # ---------------- P2 与既有字段自洽 ----------------
    ok("P2.1 paths.per_path ≡ 既有 meta['paths']（逐位相同）",
       fp["paths"].get("per_path") == meta.get("paths"),
       str(fp["paths"].get("per_path")))
    ok("P2.2 paths.provenance ≡ 既有 meta['provenance']（逐位相同）",
       fp["paths"].get("provenance") == meta.get("provenance"),
       str(fp["paths"].get("provenance"))[:80])
    sel = fp["selection"]
    ok("P2.3 selection 与顶层读数对齐（scanned/fused/judge_filtered）",
       sel.get("scanned") == meta.get("scanned")
       and sel.get("fused") == meta.get("fused")
       and sel.get("judge_filtered") == meta.get("judge_filtered"),
       f"sel={ {k: sel.get(k) for k in ('scanned','fused','judge_filtered')} }")
    # recursion 段与 provenance 里的链逐项对齐（chain 命中节点的 depth/跳数）
    prov_chains = [p for lst in (meta.get("provenance") or {}).values()
                   for p in lst if p.get("path") == "chain"]
    depths = [len(p.get("chain") or []) - 1 for p in prov_chains]
    rec = fp["recursion"].get("chain") or {}
    ok("P2.4 recursion.chain 与 provenance 里的链对齐（nodes/depth_max/hops_max）",
       rec.get("nodes") == len(prov_chains)
       and rec.get("depth_max") == (max(depths) if depths else 0)
       and rec.get("hops_max") == (max(depths) if depths else 0)
       and rec.get("enabled") is True and len(prov_chains) > 0,
       f"rec={rec} prov_chain_n={len(prov_chains)} depths={depths}")

    # ---------------- P3 确定性 ----------------
    _, meta2, _ = _read(root)
    ok("P3.1 同实例重复跑 → 同 hash（确定性，无时间/随机）",
       meta2["path_fingerprint"]["hash"] == fp["hash"],
       f"{fp['hash']} vs {meta2['path_fingerprint']['hash']}")
    # 跨实例：关库重开同根，读数须逐位同 hash
    cg = MdCGOS(root)
    try:
        _r, meta3 = cg.search_rrf(QUERY, k=5, judge=False, record=False)
    finally:
        cg.close()
    ok("P3.2 跨实例（重开同库）→ 同 hash（指纹可复跑，不依赖进程状态）",
       meta3["path_fingerprint"]["hash"] == fp["hash"],
       str(meta3["path_fingerprint"]["hash"]))
    # 判别力 + 键序无关（走 _mdcos.build_path_fingerprint——变异自证即据此接线；
    # 直接 import 的名字是测试模块的独立绑定，变异不会触及，故此处显式走模块属性）
    fpa = _mdcos.build_path_fingerprint(selection={"scanned": 3, "fused": 2},
                                        paths={"per_path": {"lexical": 3}})
    fpb = _mdcos.build_path_fingerprint(selection={"fused": 2, "scanned": 3},
                                        paths={"per_path": {"lexical": 3}})
    fpc = _mdcos.build_path_fingerprint(selection={"scanned": 9, "fused": 2},
                                        paths={"per_path": {"lexical": 3}})
    ok("P3.3 hash 判别力（同内容异键序→同 hash；不同内容→不同 hash）",
       fpa["hash"] == fpb["hash"] and fpa["hash"] != fpc["hash"],
       f"{fpa['hash']} {fpb['hash']} {fpc['hash']}")

    # ---------------- P4 只增不改 ----------------
    _legacy = ("tier", "scanned", "paths", "fused", "judge_ranking",
               "judge_filtered", "early_stopped", "expand_source",
               "goal_used", "provenance")
    ok("P4.1 既有顶层键一个不动（只增 path_fingerprint）",
       all(k in meta for k in _legacy),
       str([k for k in _legacy if k not in meta]))
    ok("P4.2 不改检索行为（两次结果 id 序逐位一致，仍为 4 元组）",
       ids == [r for r in ids] and all(a == 4 for a in arities)
       and ids == _read(root)[0],
       f"ids={ids} arities={arities}")

    # ---------------- P5 透传面 ----------------
    cg = MdCGOS(root)
    try:
        pack = cg.recall(QUERY, budget_tokens=2000, k=5, judge=False,
                         use_rrf=True)
        rmeta = pack.get("meta") or {}
    finally:
        cg.close()
    ok("P5.1 recall().meta 透传同 hash（装包/预算面可见同一指纹）",
       (rmeta.get("path_fingerprint") or {}).get("hash") == fp["hash"],
       str((rmeta.get("path_fingerprint") or {}).get("hash")))

    # 热缓存命中面：显式开门，二次调用应命中缓存且指纹同 hash
    with _Env(MDCG_HOTCACHE="1"):
        hroot = _root()
        try:
            hcg = MdCGOS(hroot)
            build_lib(hroot)
            hcg2 = MdCGOS(hroot)
            try:
                _a, ma = hcg2.search_rrf(QUERY, k=5, judge=False, record=False)
                _b, mb = hcg2.search_rrf(QUERY, k=5, judge=False, record=False)
            finally:
                hcg2.close()
                hcg.close()
            ok("P5.2 热缓存命中面返回同 hash（命中=读同一指纹，不漂移）",
               mb.get("cached") is True and
               (mb.get("path_fingerprint") or {}).get("hash")
               == (ma.get("path_fingerprint") or {}).get("hash"),
               f"cached={mb.get('cached')}")
        finally:
            shutil.rmtree(hroot, ignore_errors=True)

    # ---------------- P6 文档口径 ----------------
    lines = io.open(_FP_FILE, encoding="utf-8").read().splitlines()
    cond = ""
    for i, ln in enumerate(lines):
        if ln.strip().startswith("def build_path_fingerprint("):
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            cond = lines[j] if j >= 0 else ""
            break
    doc = inspect.getdoc(build_path_fingerprint) or ""
    ok("P6.1 文档口径到位（紧邻『生效条件：』注释 + docstring 声明确定性）",
       cond.strip().startswith("# 生效条件：") and "确定性" in doc
       and "sha256" in doc,
       cond[:60])


# ===================== 定点变异自证（--self-proof） =====================
# 锚点在**去缩进后的实现源码**上定位。每条变异声明**期望转红的断言项**；实跑红项与
# 期望必须**恰好相等**——多红=断言语义纠缠，少红=该判据空转。锚点漂移（命中≠1）→
# ANCHOR-MISS + 退出码 2（fail-closed）。
_A_PATHS = '"paths": dict(paths or {})'
_A_HASH = ('fp["hash"] = hashlib.sha256(canon.encode("utf-8"))'
           '.hexdigest()[:16]')
_ANCHORS = (_A_PATHS, _A_HASH)

#: (名, old, new, 期望红项前缀集合)——红项前缀 = check 名首个空格前的段。
_MUTATIONS = (
    ("①去掉 paths 段（paths 恒空 → 与既有 per_path/provenance 脱钩）",
     _A_PATHS, '"paths": {}',
     {"P2.1", "P2.2"}),
    ("②hash 掺非确定性源（uuid）→ 同输入不再同指纹（确定性被破坏）",
     _A_HASH,
     'fp["hash"] = hashlib.sha256((canon + str(uuid.uuid4()))'
     '.encode("utf-8")).hexdigest()[:16]',
     {"P3.1", "P3.2", "P3.3", "P5.1"}),
    ("③hash 恒定（不随输入变：判据空转）",
     _A_HASH, 'fp["hash"] = "0" * 16',
     {"P3.3"}),
)


def _anchor_preflight():
    src = textwrap.dedent(inspect.getsource(build_path_fingerprint))
    bad = [(a, src.count(a)) for a in _ANCHORS if src.count(a) != 1]
    if not bad:
        return 0
    for a, n in bad:
        print("  ANCHOR-MISS 锚点漂移（命中 %d 次，期望恰好 1）：%r" % (n, a[:70]))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed；请同步 _MUTATIONS 锚点）")
    return 2


def _run_group(root):
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _group(root)
    return ({n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL)


def _self_proof():
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：就地变异运行中的实现源码（不读 git），逐条要求**恰好**命中期望红项\n")
    src = textwrap.dedent(inspect.getsource(build_path_fingerprint))
    orig = _mdcos.build_path_fingerprint
    root = _root()
    build_lib(root)
    bad = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            base_red, _, _ = _run_group(root)
        print("  未变异基线：红项 %d %s" % (len(base_red),
                                            "（应为 0）" if base_red else ""))
        if base_red:
            bad.append("未变异基线即转红：%s" % sorted(base_red))
        marks = "①②③"
        for i, (name, old, new, expect) in enumerate(_MUTATIONS):
            ns = dict(vars(_mdcos))
            exec(compile(src.replace(old, new), "<w5pf-mutated-%d>" % i, "exec"), ns)
            _mdcos.build_path_fingerprint = ns["build_path_fingerprint"]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    red, _, _ = _run_group(root)
            except Exception as exc:                       # noqa: BLE001
                red = {"<变异体运行异常:%s>" % type(exc).__name__}
            finally:
                _mdcos.build_path_fingerprint = orig
            hit = red == expect
            if not hit:
                bad.append("变异%s %s：红项 %s ≠ 期望 %s"
                           % (marks[i], name, sorted(red), sorted(expect)))
            print("  变异%s %-44s 红项 %d（期望 %d）%s"
                  % (marks[i], name, len(red), len(expect),
                     "PASS" if hit else "**FAIL** 实=%s 期=%s"
                     % (sorted(red), sorted(expect))))
    finally:
        _mdcos.build_path_fingerprint = orig
        shutil.rmtree(root, ignore_errors=True)
    print("\n变异自证：%s"
          % ("PASS（三处接线逐条恰好命中期望红项）" if not bad
             else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main():
    print("W5 路线B · 路径指纹 path_fingerprint 守卫（只增不改 + 确定性 + 自洽）")
    print("=" * 70)
    root = _root()
    print("root =", root)
    try:
        build_lib(root)
        _group(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print(f"ALL OK: {PASS} 项（路径指纹守卫全绿）")
    return 0


if __name__ == "__main__":
    if "--self-proof" in os.sys.argv:
        os.sys.exit(_self_proof())
    os.sys.exit(main())
