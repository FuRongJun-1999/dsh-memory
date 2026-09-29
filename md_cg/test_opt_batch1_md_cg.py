# -*- coding: utf-8 -*-
"""opt-batch1 守卫 · md_cg 侧（C-1 三处写盘标脏 + C-7 升格门槛接真源）。

来源：外部双路调研（Codex 实测 + ZCode 工作流）确认、并经编排侧抽核实的
opt-batch1 批次。本文件只覆盖 md_cg 侧两条；rust 侧（R-1/R-2/R-3/R-6）的
守卫是 crate 内单测（`rust/src/*.rs` 的 `#[cfg(test)]` 与 `rust/tests/`）。

覆盖与判据：

  C-1（三处「写后读」永久陈旧）——`forgetting.reinforce`（reinforce 落库）、
      `insight.verify`（洞见裁决）、`scrub._apply_offset`（置信度校准）三处
      调 `cg._write_node` 后只改内存 index entry（scrub 连条目都不改），
      **不标 `_dirty`**。读缓存默认开（`MDCG_READ_CACHE=1`，见 `readcache.enabled`），
      其新鲜度按 `_DirtyDict.path_gen` 判；不标脏 ⇒ 同进程「写后读」永久拿到
      旧 fm。对照先例：`md_cg/mdcg.py` 的 `update_tags` / verify 直写分支
      `self._dirty[node_id] = e`。
      每处三条断言：①写盘确实发生（正对照，防夹具空转）②`nid in cg._dirty`
      ③同实例 `cg._read(e)` 与 `readcache.direct_read`（穿透缓存读盘上真值）
      逐位一致——②③即「标脏」的可观测判据。

  C-7（升格门槛自带第二份要素常量）——`consolidate.py` 原先自带
      `CCG_REQUIRED = ("生效条件","子功能","执行","不适用条件")`（4 元素），
      与真源 `nodefile.CCG_REQUIRED`（6 元素，多「功能名」「验证方式」）不一致
      ⇒ 缺「验证方式」的弱证据节点判 complete，可被 `promote_memories` 升格进
      knowledge 层（`predict` 亦按同一常量判 node_ready）。
      断言：转发真源（`is` 同一对象）/ 缺「验证方式」者被拒 / 六要素齐全者不被误伤。

运行：
    python -X utf8 -m md_cg.test_opt_batch1_md_cg                  # 正向
    python -X utf8 -m md_cg.test_opt_batch1_md_cg --mutate          # 定点变异自证
    python -X utf8 -m md_cg.test_opt_batch1_md_cg --mutate --list   # 只列变异表

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = **ANCHOR-MISS**（变异锚点在当前源码里找不到，说明实现改了却没同步本表——
本表就是判据，锚点漂移必须硬失败，不得静默跳过）。

**基线纪律**：本守卫**不以 git HEAD（或任何提交快照）为基线源**——所有
「修复前」形态都由**在当前工作区源码上做定点文本变异**得到（`_MUTATIONS`），
基线随代码一起走、不随提交漂移（本仓已有两次「基线绑提交即失效」的教训）。
变异表每条都记 `expect_red`（预期转红条数），实际红数不等即判失败——这条
同时钉住「有判别力」（红数 > 0）与「无过度杀伤」（红数恰好命中预期）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import types

# ── 隔离前置：必须在 import md_cg 子模块**之前**（tokens/theory 等在模块级把
# aux_root() 冻成常量）——否则会指到真实 ~/.mdcg 并在那里建密钥/令牌库。
# 与 md_cg/test_n197_n208_write_face_gates.py 同款前置（同一纪律）。 ──
_TMP = tempfile.mkdtemp(prefix="optb1_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "ab" * 32          # 哑主密钥（绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES"):
    os.environ.pop(_k, None)

from . import consolidate, forgetting, insight, nodefile, readcache, scrub, tokens  # noqa: E402
from .mdcos import MdCGSecure                                                        # noqa: E402
from .security import Principal                                                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SELF = os.path.abspath(__file__)

# 被测模块的**可替换引用**：变异模式会把其中一项换成 exec 出来的变异副本，
# 断言组一律经本表取模块（不直接闭包捕获原模块），否则变异对断言不可见。
MOD = {
    "forgetting": forgetting,
    "insight": insight,
    "scrub": scrub,
    "consolidate": consolidate,
}

_PASS: list = []
_FAIL: list = []
_OPEN: list = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))
    return bool(cond)


def _cleanup(path) -> bool:
    import gc
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        gc.collect()
        time.sleep(0.2)
    return not os.path.exists(path)


def _princ(role="designer", clearance="secret", can_admin=True):
    spec = tokens.role_spec(role)
    return Principal(tenant="default", actor="optb1-" + role,
                     clearance=clearance, can_write=bool(spec["can_write"]),
                     can_admin=can_admin, role=role,
                     layers_allow=spec["layers_allow"],
                     ops_allow=spec["ops_allow"], auth_mode="test")


def _secured(tag: str):
    """建一个临时库 + designer 身份；返回 (cg, tmpdir)。"""
    d = tempfile.mkdtemp(prefix="optb1_%s_" % tag)
    cg = MdCGSecure(os.path.join(d, "root"), principal=_princ())
    _OPEN.append(cg)
    return cg, d


def _close_all():
    for cg in _OPEN:
        try:
            cg.close()
        except Exception:                      # noqa: BLE001 —— 清理面不得再抛
            pass
    _OPEN.clear()


def _prime_cache(cg, nid):
    """把读缓存填成「写前旧值」（模拟真实的「先读过、再写」时序）。"""
    e = cg.index["nodes"][nid]
    cg._read(e)                                # 装缓存（写前快照）
    return e


def _cache_matches_disk(cg, e) -> bool:
    """同实例 `_read`（走读缓存）是否与穿透缓存的盘上真值一致。"""
    cached = cg._read(e)
    direct = readcache.direct_read(cg, e)
    return (cached[0] or {}) == (direct[0] or {}) and \
        (cached[1] or "") == (direct[1] or "")


# ================================================================ G0 前置自证
def g0():
    print("== G0 隔离与前置自证 ==")
    ok(readcache.enabled(), "G0a 读缓存默认开（C-1 的成立前提：未设 MDCG_READ_CACHE 时 enabled() 为真）")
    ok(os.path.abspath(tokens.token_file()).lower().startswith(_TMP.lower()),
       "G0b 令牌库落在守卫临时目录（绝不触真实凭据）",
       "tok=%s" % tokens.token_file())
    # 基线源自证（反「基线绑提交」）：变异加载器直接 open 当前工作区源文件，
    # 读到的就是它此刻在盘上的内容——不含任何提交快照读取面。
    _rel = os.path.join("md_cg", "consolidate.py")
    _live = open(os.path.join(_REPO, _rel), encoding="utf-8").read()
    _mut, _src = _load_mutated(_rel, "CCG_REQUIRED = nodefile.CCG_REQUIRED",
                               "CCG_REQUIRED = ()")
    ok(_mut is not None and _src == _live,
       "G0c 变异基线源 = 当前工作区源码（非 git HEAD／提交快照）",
       "lead=%s" % (_mut is not None))


# ================================================================ G1 C-1a reinforce
def g1():
    print("== G1 C-1a forgetting.reinforce：写盘后标脏（写后读可见）==")
    cg, d = _secured("reinforce")
    try:
        cg.add("n_re", "香蕉 optb1unique 强化正文", layer="knowledge",
               importance=0.5)
        cg.flush()
        readcache.install(cg)
        e = _prime_cache(cg, "n_re")
        before = cg._read(e)[0].get("importance")
        ok(before == 0.5, "G1a 前置：写前缓存快照 importance=0.5", before)
        r = MOD["forgetting"].reinforce(cg, "n_re", delta=0.3)
        ok(r is not None and r.get("importance") == 0.8,
           "G1b 正对照：reinforce 写盘成功（返回值自认 0.8）", r)
        ok("n_re" in cg._dirty,
           "G1c 标脏：写盘后 cg._dirty 含该节点（不标脏则 path_gen 不推进）",
           "dirty=%s" % list(cg._dirty))
        ok(_cache_matches_disk(cg, e),
           "G1d 同实例写后读与盘上真值逐位一致（读缓存已失效）",
           "cached=%s direct=%s" % (cg._read(e)[0].get("importance"),
                                    readcache.direct_read(cg, e)[0].get("importance")))
    finally:
        _close_all()
        _cleanup(d)


# ================================================================ G2 C-1b insight.verify
def g2():
    print("== G2 C-1b insight.verify：裁决写盘后标脏 ==")
    cg, d = _secured("insight")
    try:
        cond = {"retrievability": 0.8, "outside_observer": True,
                "cross_domain": ["存储", "网络"], "premise_questioned": True,
                "pressure": "low", "continuity_turns": 3, "externalized": True,
                "tone": "curious"}
        ev = cg.insight(action="record",
                        statement="optb1 探针事件：写后读判据（zzins）",
                        conditions=cond)
        nid = ev["node_id"]
        cg.flush()
        readcache.install(cg)
        e = _prime_cache(cg, nid)
        ok(cg._read(e)[0].get("insight_state") == "pending",
           "G2a 前置：写前缓存快照 insight_state=pending",
           cg._read(e)[0].get("insight_state"))
        out = MOD["insight"].verify(
            cg, node_id=nid, actor="designer", verdict="verified",
            note="optb1 守卫",
            evidence=[{"type": "v3", "ref": "optb1", "note": "n"}])
        ok(bool(out.get("ok")) and out.get("state") == "verified",
           "G2b 正对照：verify 裁决写盘成功（state=verified）", out)
        ok(nid in cg._dirty,
           "G2c 标脏：写盘后 cg._dirty 含该节点", "dirty=%s" % list(cg._dirty))
        ok(_cache_matches_disk(cg, e),
           "G2d 同实例写后读与盘上真值逐位一致（insight_state/importance/tags 同批可见）",
           "cached=%s direct=%s" % (cg._read(e)[0].get("insight_state"),
                                    readcache.direct_read(cg, e)[0].get("insight_state")))
    finally:
        _close_all()
        _cleanup(d)


# ================================================================ G3 C-1c scrub._apply_offset
def g3():
    print("== G3 C-1c scrub._apply_offset：校准写盘后标脏 ==")
    cg, d = _secured("scrub")
    try:
        cg.add("n_cal", "# 功能名：校准探针\n# 正文：香蕉 校准 optb1\n",
               layer="knowledge", importance=0.5, confidence=0.6)
        cg.flush()
        readcache.install(cg)
        e = _prime_cache(cg, "n_cal")
        ok(cg._read(e)[0].get("confidence") == 0.6,
           "G3a 前置：写前缓存快照 confidence=0.6")
        adj, skipped = MOD["scrub"]._apply_offset(cg, 0.2, min_evidence=0,
                                                  actor="designer")
        ok(adj == 1, "G3b 正对照：校准写盘成功（adjusted=1）",
           "adjusted=%s skipped=%s" % (adj, skipped))
        ok("n_cal" in cg._dirty,
           "G3c 标脏：写盘后 cg._dirty 含该节点（本处原先连条目都不改、更不标脏）",
           "dirty=%s" % list(cg._dirty))
        ok(_cache_matches_disk(cg, e),
           "G3d 同实例写后读与盘上真值逐位一致（confidence=0.8 可见）",
           "cached=%s direct=%s" % (cg._read(e)[0].get("confidence"),
                                    readcache.direct_read(cg, e)[0].get("confidence")))
    finally:
        _close_all()
        _cleanup(d)


# ================================================================ G4 C-7 升格门槛
def g4():
    print("== G4 C-7 consolidate.promote_memories：升格门槛接六要素真源 ==")
    cg, d = _secured("c7")
    try:
        root = cg.root
        weak = ("# 功能名：弱证据候选\n# 生效条件：问弱证据候选时\n# 子功能：x\n"
                "# 执行：y\n# 不适用条件：无\n")          # 缺「验证方式」
        strong = weak + "# 验证方式：编译器/静态检查通过\n"
        cg.add("cand_weak", "# 源\n" + weak, layer="contextual",
               merge_count=3, importance=0.8)
        cg.add("cand_strong", "# 源\n" + strong, layer="contextual",
               merge_count=3, importance=0.8)
        cg.flush()

        ccg_req = MOD["consolidate"].CCG_REQUIRED
        ok(ccg_req is nodefile.CCG_REQUIRED,
           "G4a 转发真源：consolidate.CCG_REQUIRED is nodefile.CCG_REQUIRED（非本地副本）",
           "consolidate=%r nodefile=%r" % (ccg_req, nodefile.CCG_REQUIRED))
        ok(set(ccg_req) == set(nodefile.CCG_MARKS) and len(ccg_req) == 6
           and "验证方式" in ccg_req,
           "G4b 要素集=六要素（含「验证方式」——缺它即弱证据）",
           ccg_req)

        rep = MOD["consolidate"].promote_memories(root, apply=False)
        ids = [s["id"] for s in rep.get("samples") or []]
        ok("cand_weak" not in ids and rep.get("skipped_incomplete") == 1,
           "G4c 缺「验证方式」的候选被拒（不计入升格候选，计入 skipped_incomplete）",
           "targeted=%s skipped_incomplete=%s samples=%s"
           % (rep.get("targeted"), rep.get("skipped_incomplete"), ids))
        ok("cand_strong" in ids,
           "G4d 正对照：六要素齐全者仍被升格候选（门槛收紧不得误伤合格节点）",
           "targeted=%s samples=%s" % (rep.get("targeted"), ids))
    finally:
        _close_all()
        _cleanup(d)


# ================================================================ G5 单点结构
def g5():
    print("== G5 单点结构（防副本回归）==")
    p = os.path.join(_HERE, "consolidate.py")
    src = open(p, encoding="utf-8").read()
    ok("CCG_REQUIRED = nodefile.CCG_REQUIRED" in src,
       "G5a consolidate.py 以转发形态接线真源（源码可见）")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    ok('CCG_REQUIRED = ("生效条件"' not in code
       and "CCG_REQUIRED = ('生效条件'" not in code,
       "G5b 可执行行内不再有本地 4 元素字面量副本（副本回归即红）")
    # 三处 C-1 写点的标脏在同源先例处也在位（对照面：证明修复方向是本仓既有范式）
    mdsrc = open(os.path.join(_HERE, "mdcg.py"), encoding="utf-8").read()
    ok(mdsrc.count("self._dirty[node_id] = e") >= 2,
       "G5c 对照先例在位：mdcg.py 的 update_tags / verify 直写分支显式标脏",
       mdsrc.count("self._dirty[node_id] = e"))


# ================================================================ 变异表
# 每条 = (名称, MOD 键, 源码锚点, 替换文本, 预期转红条数)。
# 锚点必须逐字命中当前源码（找不到 → ANCHOR-MISS → 退出码 2，fail-closed）。
_MUTATIONS = (
    ("C-1a 删 forgetting.reinforce 的标脏",
     "forgetting",
     "        _dirty = getattr(cg, \"_dirty\", None)\n"
     "        if isinstance(_dirty, dict):\n"
     "            _dirty[node_id] = e\n",
     "        pass  # MUT\n",
     2),
    ("C-1b 删 insight.verify 的标脏",
     "insight",
     "        _dirty = getattr(cg, \"_dirty\", None)\n"
     "        if isinstance(_dirty, dict):\n"
     "            _dirty[node_id] = ent\n",
     "        pass  # MUT\n",
     2),
    ("C-1c 删 scrub._apply_offset 的标脏",
     "scrub",
     "            _dirty = getattr(cg, \"_dirty\", None)\n"
     "            if isinstance(_dirty, dict):\n"
     "                _dirty[nid] = e\n",
     "            pass  # MUT\n",
     2),
    ("C-7 恢复本地 4 元素副本（撤掉转发）",
     "consolidate",
     "CCG_REQUIRED = nodefile.CCG_REQUIRED",
     "CCG_REQUIRED = (\"生效条件\", \"子功能\", \"执行\", \"不适用条件\")",
     3),
)


def _load_mutated(relpath: str, old: str, new: str):
    """把 `relpath` 的源码做定点文本替换后 exec 成独立模块（不落盘、不改工作区）。"""
    path = os.path.join(_REPO, relpath)
    src = open(path, encoding="utf-8").read()
    if old not in src:
        return None, src
    mut_src = src.replace(old, new, 1)
    mod = types.ModuleType("md_cg._optb1_mut")
    mod.__package__ = "md_cg"
    mod.__file__ = path
    exec(compile(mut_src, path, "exec"), mod.__dict__)      # noqa: S102 —— 定点变异
    return mod, src


_RELPATH = {
    "forgetting": os.path.join("md_cg", "forgetting.py"),
    "insight": os.path.join("md_cg", "insight.py"),
    "scrub": os.path.join("md_cg", "scrub.py"),
    "consolidate": os.path.join("md_cg", "consolidate.py"),
}


def _run_groups() -> int:
    """跑全部断言组，返回失败数（变异核验复用）。"""
    _PASS.clear()
    _FAIL.clear()
    for g in (g0, g1, g2, g3, g4, g5):
        try:
            g()
        except Exception as exc:                            # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
    _close_all()
    return len(_FAIL)


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把修复点改回缺陷形态，套件必须按预期条数转红\n")
    if list_only:
        for name, key, old, new, exp in _MUTATIONS:
            print("  %-40s %-12s expect_red=%d" % (name, key, exp))
        return 0

    import contextlib
    import io
    anchor_miss = []
    bad = []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, key, old, new, expect in _MUTATIONS:
        mod, src = _load_mutated(_RELPATH[key], old, new)
        if mod is None:
            print("  ANCHOR-MISS %s —— 锚点在 %s 当前源码里找不到"
                  "（实现改了却没同步本表；基线不得静默漂移）"
                  % (name, _RELPATH[key]))
            anchor_miss.append(name)
            continue
        live = MOD[key]
        MOD[key] = mod
        try:
            with contextlib.redirect_stdout(buf := io.StringIO()):
                fails_extra = _run_groups()
            detail = buf.getvalue()
        finally:
            MOD[key] = live
        red = [l for l in detail.splitlines() if l.strip().startswith("FAIL ")]
        verdict = "红" if fails_extra else "**仍全绿 = 该判据空转**"
        mark = "OK  " if fails_extra == expect else "MISMATCH"
        print("  %s %-40s 红项=%d 预期=%d  %s" % (mark, name, fails_extra, expect, verdict))
        for l in red:
            print("        " + l.strip()[5:])
        if fails_extra != expect:
            bad.append("%s（红=%d 预期=%d）" % (name, fails_extra, expect))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s" % ("PASS（每处判据都被打红且恰好命中预期项数）"
                                   if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    if "--mutate" in sys.argv:
        try:
            return _mutate_mode("--list" in sys.argv)
        finally:
            _cleanup(_TMP)
    try:
        n_fail = _run_groups()
        print("\nopt-batch1 守卫（md_cg 侧）：%d 通过，%d 失败" % (len(_PASS), n_fail))
        return 0 if not n_fail else 1
    finally:
        _cleanup(_TMP)


if __name__ == "__main__":
    sys.exit(main())
