# -*- coding: utf-8 -*-
"""C-3 守卫 · 瞬态读失败不得固化为「节点从检索面消失」（FI-M02 / N134）。

来源：设计者裁定的 C-3 契约（瞬态读失败被负缓存固化）。

缺陷（N134，docs/eval/缺陷挖掘_自主迭代_v16.md:86）：`MdCG._read` 把 OSError
（含**瞬态**失败：独占句柄 / 资源剥夺）与「文件不存在 / 越界」一律归成
`(None, None)`，而 `readcache._cached` 对任何返回值——含 `(None, None)`——一律
入缓存，且该 path 无写事件时 `_fresh` 判定恒真 ⇒ 一次瞬态 OS 失败被固化成
「该节点从检索面永久消失，直到进程重启或该 path 再写盘」（cache 条目字面
`(gen, (None, None))`）；而 `cg.get` 直读不走缓存照常可读 ⇒「get 能读、
search 搜不到」撕裂（P1 fail-closed 缺席 + T4 静默损伤）。

契约四项 ↔ 断言组：
  ① 读路径区分「瞬时/终态」且**判别点单点**（缓存层不得再猜一遍）
     —— G5（源码结构：判别函数唯一、缓存层不出现异常类型判别）
     + G1（三态标签实测：瞬时 → READ_FAIL_TRANSIENT；真缺 → 终态）
  ② 读失败不得以「新鲜」身份固化（本实现取**不入缓存**，见 readcache.install
     文档串的取舍论证）—— G1（cache 无条目 / 释放后**首次**查询即命中）
     + G2（无判别面载体的保守侧：宁可重读，不可固化可能是瞬时的缺失）
  ③ 不得静默：模块级计数 + 有界样本、该记账面可被守卫读取 —— G6
  ④ 成功路径对外返回值语义**逐位不变**（独立 oracle 对照，不靠推理）
     —— G3（缓存开 / 缓存关 / 变异体三路逐位一致）+ G4（盘上真值独立 oracle）

Windows 实测项：G7（与 chaos 用例 FI-M02 同款 ctypes.WinDLL 独占句柄置景：
持锁期 miss、释放后命中）。非 Windows 该组 SKIP 且**不计入断言数**（诚实声明：
本平台不可实测），缺口本体的跨平台判据由 G1 的 OSError 注入承担。

运行：
    python -X utf8 -m md_cg.test_c3_transient_read_negative                  # 正向
    python -X utf8 -m md_cg.test_c3_transient_read_negative --mutate          # 定点变异自证
    python -X utf8 -m md_cg.test_c3_transient_read_negative --mutate --list   # 只列变异表

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = **ANCHOR-MISS**（变异锚点在当前源码里找不到，说明实现改了却没同步本表——
本表就是判据，锚点漂移必须硬失败，不得静默跳过）。

**基线纪律**：本守卫**不以 git HEAD（或任何提交快照）为基线源**——所有
「修复前」形态都由**在当前工作区源码上做定点文本变异**得到（`_MUTATIONS`），
基线随代码一起走、不随提交漂移（本仓已有「基线绑提交即失效」的教训）。
变异表每条记 `expect_red`，实际红数不等即判失败。
"""
from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import types

# ── 隔离前置：必须在 import md_cg 子模块**之前**（tokens/theory 等在模块级把
# aux_root() 冻成常量）——否则会指到真实 ~/.mdcg 并在那里建密钥/令牌库。
# 与 md_cg/test_opt_batch1_md_cg.py 同款前置（同一纪律）。 ──
_TMP = tempfile.mkdtemp(prefix="c3trn_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "ab" * 32          # 哑主密钥（绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES"):
    os.environ.pop(_k, None)

from . import fsutil, mdcg as mdcg_mod, readcache                 # noqa: E402
from .mdcos import MdCGSecure                                     # noqa: E402
from .security import Principal                                   # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

# 被测模块的**可替换引用**：变异模式会把其中一项换成 exec 出来的变异副本，
# 断言组一律经本表取模块（不直接闭包捕获原模块），否则变异对断言不可见。
MOD = {"readcache": readcache}

_PASS: list = []
_FAIL: list = []
_SKIP: list = []
_OPEN: list = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))
    return bool(cond)


def skip(msg):
    _SKIP.append(msg)
    print("  SKIP " + msg)


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
    from . import tokens
    spec = tokens.role_spec(role)
    return Principal(tenant="default", actor="c3trn-" + role,
                     clearance=clearance, can_write=bool(spec["can_write"]),
                     can_admin=can_admin, role=role,
                     layers_allow=spec["layers_allow"],
                     ops_allow=spec["ops_allow"], auth_mode="test")


def _secured(tag: str):
    """建一个临时库 + designer 身份；返回 (cg, tmpdir)。"""
    d = tempfile.mkdtemp(prefix="c3trn_%s_" % tag)
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


class _OpenGate:
    """读闸门：接管 `md_cg.mdcg` 模块内的 `open`（模块全局名遮蔽内建），
    对指定 basename 抛注入异常，其余原样委托；并对每次 open 计数。

    为什么改模块全局而不是 builtins：`_read_status` / `get` 里的 `open` 是
    mdcg 模块内的全局名查找——改这一处只影响 mdcg 自己的文件打开面，不波及其他
    库（json/临时件）也不会漏到进程外。**注入面就是真实的 `except OSError`**：
    抛出的 PermissionError(13) 与 Windows 共享冲突（WinError 32）/ 权限剥夺
    在判别面上同类（均非 FileNotFoundError ⇒ 瞬时）。
    """

    def __init__(self, exc=None):
        self._real = builtins.open
        self._failing: set = set()
        self._exc = exc or PermissionError(13, "sharing violation")
        self.counts: dict = {}

    def install(self):
        mdcg_mod.open = self._gate

    def remove(self):
        if getattr(mdcg_mod, "open", None) is self._gate:
            del mdcg_mod.open

    def _gate(self, file, *a, **k):
        name = os.path.basename(str(file))
        self.counts[name] = self.counts.get(name, 0) + 1
        if name in self._failing:
            raise self._exc
        return self._real(file, *a, **k)

    def fail(self, *paths):
        self._failing = {os.path.basename(p) for p in paths}

    def release(self):
        self._failing = set()

    def md_opens(self) -> dict:
        return {k: v for k, v in self.counts.items() if k.endswith(".md")}


# ════════════════════════════════════════════════ 无故障路径的独立 oracle
# 标记词取**双字中文**：bigram 面下彼此零重叠（实测每个标记只命中自己的节点），
# 拉丁串（marker01zz 之类）会因 bigram 共享（"er"/"zz"）互串，不能当独立判据。
_NODES = (
    ("c3_n01", "镜湖 苹果 共用词"),
    ("c3_n02", "霜桥 香蕉 共用词"),
    ("c3_n03", "赤鲸 橘子 共用词"),
    ("c3_n04", "寒鸦 葡萄 共用词"),
    ("c3_n05", "碧玺 西瓜 共用词"),
    ("c3_n06", "苍梧 柠檬 共用词"),
    ("c3_n07", "丹枫 樱桃 共用词"),
    ("c3_n08", "青鸾 蜜桃 共用词"),
)
# 独立性：期望命中集合由**构造**给出（每个标记只出现在一个节点里），
# 不来自被测代码的任何输出——这就是本组 oracle 的「独立」处。
_EXPECT_HITS = {
    "镜湖": ["c3_n01"],
    "霜桥": ["c3_n02"],
    "碧玺": ["c3_n05"],
    "共用词": [n[0] for n in _NODES],
}
_BATTERY = tuple(_EXPECT_HITS)


def _build_lib(root):
    cg = MdCGSecure(root, principal=_princ())
    for nid, body in _NODES:
        cg.add(nid, "# 功能名：C-3 夹具 %s\n# 正文：%s\n" % (nid, body),
               layer="knowledge", importance=0.5)
    cg.flush()
    return cg


def _snap(cg):
    """无故障路径的可比快照：查询结果（id / 分数 / 资格态 / meta 关键项）
    + 每节点 get 全量。`record=False` 保证查询本身零写（三次对照纯读）。"""
    out = []
    for q in _BATTERY:
        res, meta = cg.search(q, record=False)
        out.append({
            "q": q,
            "ids": [r[0].get("id") for r in res],
            "scores": [repr(r[1]) for r in res],
            "states": [(r[2] or {}).get("state") if isinstance(r[2], dict)
                       else r[2] for r in res],
            "meta": {k: meta.get(k) for k in
                     ("tier", "scanned", "candidates", "covered_neg")},
        })
    for nid in sorted(cg.index["nodes"]):
        g = cg.get(nid)
        out.append({"id": nid,
                    "fm": g["frontmatter"] if g else None,
                    "content": g["content"] if g else None})
    return json.dumps(out, ensure_ascii=False, sort_keys=True, default=str)


# ================================================================ G0 前置自证
def g0():
    print("== G0 隔离与前置自证 ==")
    ok(readcache.enabled(),
       "G0a 读缓存默认开（C-3 的成立前提：未设 MDCG_READ_CACHE 时 enabled() 为真）")
    from . import tokens
    ok(os.path.abspath(tokens.token_file()).lower().startswith(_TMP.lower()),
       "G0b 令牌库落在守卫临时目录（绝不触真实凭据）",
       "tok=%s" % tokens.token_file())
    # 基线源自证（反「基线绑提交」）：变异加载器直接 open 当前工作区源文件，
    # 读到的就是它此刻在盘上的内容——不含任何提交快照读取面。
    _rel = os.path.join("md_cg", "readcache.py")
    _live = open(os.path.join(_REPO, _rel), encoding="utf-8").read()
    _mut, _src = _load_mutated(_rel, _MUT_ADMIT_OLD, _MUT_ADMIT_NEW)
    ok(_mut is not None and _src == _live,
       "G0c 变异基线源 = 当前工作区源码（非 git HEAD／提交快照）",
       "lead=%s" % (_mut is not None))


# =========================================== G1 主判据（跨平台 OSError 注入）
def g1():
    print("== G1 瞬态读失败：不入缓存 + 释放即命中（跨平台注入）==")
    cg, d = _secured("g1")
    gate = _OpenGate()
    try:
        for nid, body in _NODES[:3]:
            cg.add(nid, "# 功能名：C-3 主判据 %s\n# 正文：%s\n" % (nid, body),
                   layer="knowledge", importance=0.5)
        cg.flush()
        MOD["readcache"].install(cg)
        gate.install()

        e1 = cg.index["nodes"]["c3_n01"]
        p1 = cg._node_disk_path(e1)
        key1 = e1["path"]

        # 前置自证（防夹具空转）：无故障时冷缓存查询命中全部 3 条
        MOD["readcache"].clear(cg)
        pre = _ids(cg.search("共用词"))
        ok(sorted(pre) == ["c3_n01", "c3_n02", "c3_n03"],
           "G1a 前置：无故障时查询命中全部 3 节点（查询面本身有效）", pre)
        ok(cg._read_cache.get(key1) is not None,
           "G1a2 前置：成功结果已入缓存（该 path 有缓存条目）",
           "cache=%r" % (cg._read_cache.get(key1),))

        # ── 注入瞬态读失败（只对 c3_n01 的文件）──
        # 每次注入查询前 clear：确保真的走读路径（缓存命中会掩盖注入）
        fsutil.reset_transient_read_stats()
        gate.fail(p1)
        MOD["readcache"].clear(cg)
        ids_l1 = _ids(cg.search("共用词"))
        ids_l2 = _ids(cg.search("共用词"))
        gate.counts.clear()                    # 只看稳态：缓存已装齐
        ids_l3 = _ids(cg.search("共用词"))
        opens_steady = gate.md_opens()
        entry_l = cg._read_cache.get(key1)
        stat_l = fsutil.transient_read_stats()

        ok(ids_l1 == ["c3_n02", "c3_n03"] and ids_l2 == ["c3_n02", "c3_n03"]
           and ids_l3 == ["c3_n02", "c3_n03"],
           "G1b 读失败 fail-closed：不可读节点不参与检索（不泄漏半读内容），"
           "同池其余节点不受累（可隔离）",
           "locked_hits=%s/%s/%s" % (ids_l1, ids_l2, ids_l3))
        ok(entry_l is None,
           "G1c 【②】负结果**不入缓存**：该 path 无缓存条目（修前为字面 "
           "(gen,(None,None)) 的固化条目——本项即定点变异红项的靶心）",
           "cache[%r]=%r" % (key1, entry_l))
        ok(stat_l[0] >= 3 and any(os.path.basename(s[0]) == "c3_n01.md"
                                  and s[1] == "PermissionError"
                                  and s[2] == 13 for s in stat_l[1]),
           "G1d 【③】不得静默：瞬时读失败计入模块级计数且样本含 (path, 异常类型,"
           " errno)（守卫可读的记账面）",
           "stats=%r" % (stat_l,))
        ok(opens_steady == {"c3_n01.md": 1},
           "G1e 【②代价面】重试有界（稳态一次查询）：失败 path 恰 1 次 open，"
           "成功节点零重读（缓存仍命中）——不是整池重读的性能悬崖",
           "opens=%r" % (opens_steady,))

        # ── 三态标签直接实测（判别点的产物）──
        st = cg._read_status(e1)
        ok(st[0] is None and st[1] is None
           and st[2] == fsutil.READ_FAIL_TRANSIENT,
           "G1f 【①】三态标签实测：瞬时读失败 → 第三元素 = READ_FAIL_TRANSIENT"
           "（缓存层消费的就是这个标签，不看异常类型）",
           "status=%r" % (st,))

        # ── 释放：**首次**查询即命中 ──
        gate.release()
        ids_r1 = _ids(cg.search("共用词"))
        ids_r2 = _ids(cg.search("共用词"))
        ok(ids_r1 == ["c3_n01", "c3_n02", "c3_n03"]
           and ids_r2 == ["c3_n01", "c3_n02", "c3_n03"],
           "G1g 【②】释放后**首次**查询即命中（瞬态窗口为零：一次可重试失败不被"
           "固化成「节点从检索面消失」）",
           "after_release=%s/%s" % (ids_r1, ids_r2))

        g = cg.get("c3_n01")
        ok(g is not None and g["frontmatter"].get("importance") == 0.5
           and "c3_n01" in ids_r1,
           "G1h 撕裂消除：cg.get 直读与 search 同批可见（修前「get 能读、"
           "search 搜不到」）",
           "get=%s" % (g is not None))

        # ── 终态（真缺）仍照旧入缓存：不构成重读风暴 ──
        cg2, d2 = _secured("g1term")
        try:
            cg2.add("c3_t1", "# 功能名：真缺夹具\n# 正文：真缺标记 共用词\n",
                    layer="knowledge")
            cg2.flush()
            MOD["readcache"].install(cg2)
            e_t = cg2.index["nodes"]["c3_t1"]
            kt = e_t["path"]
            pt = cg2._node_disk_path(e_t)
            os.remove(pt)                      # 真删（非瞬态）→ FileNotFoundError
            gate.counts.clear()
            gate.fail()                        # 闸门不拦，交给 OS 真报 ENOENT
            _ids(cg2.search("真缺标记"))
            ent_t = cg2._read_cache.get(kt)
            ok(ent_t is not None and ent_t[1] == (None, None),
               "G1i 【②范围】终态「真缺」**仍入缓存**（(gen,(None,None))）——"
               "「不入缓存」只针对瞬时失败，缺文件节点不会被每查询重试",
               "cache[%r]=%r" % (kt, ent_t))
            ok(cg2._read_status(e_t)[2] is None,
               "G1j 【①】三态标签实测：FileNotFoundError → 终态（第三元素 None）",
               "status=%r" % (cg2._read_status(e_t),))
        finally:
            _close_all_of([cg2])
            _cleanup(d2)
    finally:
        gate.remove()
        _close_all()
        _cleanup(d)


def _ids(hits):
    return sorted(x[0].get("id") for x in hits[0]) if hits and hits[0] else []


def _close_all_of(cgs):
    for c in cgs:
        try:
            c.close()
        except Exception:                      # noqa: BLE001
            pass


# ========================================= G2 无判别面载体的保守侧（回落分支）
def g2():
    print("== G2 无三态面载体的保守侧（非 MdCG 载体的回落分支）==")

    class _Stub:
        """只有二态 `_read` 的载体（无 `_read_status`）——覆盖 install 的回落分支。"""

        def __init__(self, vals):
            self._dirty = {}
            self._vals = vals
            self.calls = []

        def _read(self, entry):
            self.calls.append(entry["path"])
            return self._vals[entry["path"]]

    stub = _Stub({"p/ok.md": ({"id": "ok"}, "正文"),
                  "p/miss.md": (None, None)})
    MOD["readcache"].install(stub)
    ok(stub._read_uncached({"path": "p/ok.md"}) == ({"id": "ok"}, "正文"),
       "G2a 回落分支在位：_read_uncached 仍是穿透缓存的原始二态读"
       "（direct_read 的真源形状不变）")
    e1 = {"path": "p/ok.md"}
    e2 = {"path": "p/miss.md"}
    stub.calls.clear()                  # G2a 的直读不计入计数面
    stub._read(e1)
    stub._read(e1)
    ok(stub.calls.count("p/ok.md") == 1,
       "G2b 成功结果照旧入缓存（二次读零重读）", stub.calls)
    stub._read(e2)
    stub._read(e2)
    ok(stub.calls.count("p/miss.md") == 2,
       "G2c 无判别面时**保守不接纳**空结果（宁可重读，不可固化可能是瞬时的"
       "缺失）——回落分支不得回缺陷形态", stub.calls)


# ============================================ G3 无故障路径逐位一致（三路对照）
def g3():
    print("== G3 无故障路径逐位一致（缓存开 / 缓存关 / 变异体 三路对照）==")
    d = tempfile.mkdtemp(prefix="c3trn_g3_")
    try:
        root = os.path.join(d, "root")
        cg0 = _build_lib(root)
        # 先把「构造期望」与盘上真值对齐（独立 oracle，见 G4）
        for q, want in _EXPECT_HITS.items():
            got = _ids(cg0.search(q, record=False))
            ok(got == sorted(want),
               "G3pre 构造期望命中：%s → %s（oracle 来自夹具构造而非被测输出）"
               % (q, want), "got=%s" % (got,))
        _close_all_of([cg0])

        # A：修复后 + 缓存开（生产默认态）
        cgA = MdCGSecure(root, principal=_princ())
        MOD["readcache"].install(cgA)
        snapA = _snap(cgA)
        _close_all_of([cgA])

        # B：修复后 + 缓存关（MDCG_READ_CACHE=0 —— 逐次读盘的既有口径）
        old = os.environ.get("MDCG_READ_CACHE")
        os.environ["MDCG_READ_CACHE"] = "0"
        try:
            cgB = MdCGSecure(root, principal=_princ())
        finally:
            if old is None:
                os.environ.pop("MDCG_READ_CACHE", None)
            else:
                os.environ["MDCG_READ_CACHE"] = old
        ok(not hasattr(cgB, "_read_cache"),
           "G3a 对照 B 确为「缓存关」形态（无 _read_cache 属性）")
        snapB = _snap(cgB)
        _close_all_of([cgB])

        # C：变异体（撤掉「瞬时读失败不入缓存」判据 = 修复前接纳口径）+ 缓存开
        mut, _src = _load_mutated(os.path.join("md_cg", "readcache.py"),
                                  _MUT_ADMIT_OLD, _MUT_ADMIT_NEW)
        live = MOD["readcache"]
        MOD["readcache"] = mut
        try:
            cgC = MdCGSecure(root, principal=_princ())
            mut.install(cgC)
            snapC = _snap(cgC)
            _close_all_of([cgC])
        finally:
            MOD["readcache"] = live

        ok(snapA == snapB,
           "G3b 【④】缓存开 == 缓存关：逐位一致（读缓存对无故障查询结果零影响）",
           "diffA/B=%s" % (_first_diff(snapA, snapB),))
        ok(snapA == snapC,
           "G3c 【④】修复后 == 修复前接纳口径（变异体）：无故障路径逐位一致"
           "（修复只动失败路径的接纳判据，成功路径语义不变）",
           "diffA/C=%s" % (_first_diff(snapA, snapC),))
    finally:
        _cleanup(d)


def _first_diff(a: str, b: str) -> str:
    if a == b:
        return "无"
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            lo = max(0, i - 60)
            return "首个差异 @%d：A…%r | B…%r" % (i, a[lo:i + 40], b[lo:i + 40])
    return "长度不同：A=%d B=%d" % (len(a), len(b))


# ================================================ G4 盘上真值独立 oracle
def g4():
    print("== G4 盘上真值独立 oracle（不依赖被测读路径）==")
    cg, d = _secured("g4")
    try:
        for nid, body in _NODES[:4]:
            cg.add(nid, "# 功能名：C-3 oracle %s\n# 正文：%s\n" % (nid, body),
                   layer="knowledge", importance=0.5)
        cg.flush()
        MOD["readcache"].install(cg)
        bad = []
        for nid, body in _NODES[:4]:
            g = cg.get(nid)
            raw = open(os.path.join(cg.root, g["path"]), encoding="utf-8").read()
            # 独立判据：正文（去尾换行）与关键 frontmatter 值必须**逐字**出现在
            # 原始文件字节里（不借用 md_cg 的解析器），且 marker 在正文中。
            if (g["content"].rstrip("\n") not in raw
                    or body not in raw
                    or str(g["frontmatter"].get("id")) not in raw
                    or str(g["frontmatter"].get("layer")) not in raw):
                bad.append(nid)
        ok(not bad,
           "G4a 【④】get 的 content/frontmatter 与盘上原始文件逐字一致"
           "（4 节点全过；oracle 只做文件字节比对，不经 _read/_read_status）",
           "mismatch=%s" % bad)
    finally:
        _close_all()
        _cleanup(d)


# ==================================================== G5 单点结构（防副本回归）
def g5():
    print("== G5 单点结构（判别唯一、缓存层不重判）==")
    fs = open(os.path.join(_HERE, "fsutil.py"), encoding="utf-8").read()
    rc = open(os.path.join(_HERE, "readcache.py"), encoding="utf-8").read()
    md = open(os.path.join(_HERE, "mdcg.py"), encoding="utf-8").read()

    def code(src):
        return "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))

    ok(code(fs).count("def classify_read_failure") == 1,
       "G5a 判别函数单点：fsutil.classify_read_failure 恰好一处定义",
       code(fs).count("def classify_read_failure"))
    ok(code(md).count("fsutil.classify_read_failure(exc)") == 1,
       "G5b 判别**调用**单点：mdcg 全文件仅一处调用（_note_read_oserror）——"
       "读路径不给第二份判据",
       code(md).count("fsutil.classify_read_failure(exc)"))
    ok("isinstance(exc" not in code(rc)
       and "except OSError" not in code(rc)
       and "classify_read_failure(" not in code(rc),
       "G5c 缓存层不重判：readcache.py 可执行行内既不捕获 OSError、也不做异常"
       "类型判别、更不调用判别函数（不猜第二遍），只消费 _read_status 的第三"
       "元素标签")
    ok("if val[2] is not None:" in code(rc),
       "G5d 接纳判据按**标签**（_read_status 第三元素）而非返回值形状")
    ok(code(md).count("def _read_status") == 1
       and "return self._read_status(entry)[:2]" in code(md),
       "G5e 二态对外面单点转发：_read 恰为 _read_status 的前两项投影"
       "（无第二份读实现）")
    ok(code(md).count("def _note_read_oserror") == 1,
       "G5f 记账口单点：mdcg 内 _note_read_oserror 恰好一处定义")
    # 对照先例在位（N225 同风格记账面仍在，防本批把旧面拆掉）
    ok("TRANSIENT_READ_FAILURES" in fs and "NONOBJECT_ROW_SKIPS" in fs,
       "G5g 记账面与 N225 坏行记账同模块同风格并存（未互相顶替）")


# ==================================================== G6 记账面（计数/样本/有界）
def g6():
    print("== G6 记账面（模块级计数 + 有界样本 + stderr 告警 + 基线可重置）==")
    fsutil.reset_transient_read_stats()
    ok(fsutil.transient_read_stats() == (0, ()),
       "G6a 记账面可重置（守卫/运维建基线用）",
       fsutil.transient_read_stats())
    exc = PermissionError(13, "sharing violation")
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        wrote = fsutil.note_transient_read_failure("knowledge/orphan/x.md", exc)
    err = buf.getvalue()
    n1, s1 = fsutil.transient_read_stats()
    ok(n1 == 1 and s1 and s1[0][0].endswith("x.md")
       and s1[0][1] == "PermissionError" and s1[0][2] == 13,
       "G6b 记账：计数累加 + 样本三元组 (path, 异常类型名, errno)", (n1, s1))
    ok(wrote and "[fsutil]" in err and "x.md" in err and "累计 1 次" in err,
       "G6b2 告警面：失败时向 stderr 写一行（含 path/异常/累计数）——T4 静默"
       "损伤不再复现", err.strip()[:120])
    buf2 = io.StringIO()
    with contextlib.redirect_stderr(buf2):
        for i in range(100):
            fsutil.note_transient_read_failure("knowledge/orphan/y%02d.md" % i,
                                               exc)
    n2, s2 = fsutil.transient_read_stats()
    ok(n2 == 101 and len(s2) == fsutil._TRANSIENT_READ_SAMPLE_CAP,
       "G6c 样本有界（不随失败次数线性涨）、计数不受限",
       "count=%d samples=%d" % (n2, len(s2)))
    ok(buf2.getvalue().count("[fsutil]")
       == fsutil._TRANSIENT_READ_WARN_CAP - 1,
       "G6d 告警限流：101 次失败只写 %d 行（首 %d 次各一行，其后静默但计数/样本"
       "持续更新）——热路径防刷屏，信息面不减"
       % (fsutil._TRANSIENT_READ_WARN_CAP - 1, fsutil._TRANSIENT_READ_WARN_CAP),
       buf2.getvalue().count("[fsutil]"))
    fsutil.reset_transient_read_stats()
    ok(fsutil.transient_read_stats() == (0, ()),
       "G6e 记账面复位（不留脏基线给后续用例）")


# ==================================================== G7 Windows 实测（非 Windows SKIP）
def g7():
    print("== G7 Windows 实测：ctypes.WinDLL 独占句柄（FI-M02 同款置景）==")
    if os.name != "nt":
        skip("G7 非 Windows：ctypes.WinDLL 独占句柄置景不可用（SKIP，不计入断言"
             "数）——缺口本体的跨平台判据由 G1 的 OSError 注入承担")
        return
    import ctypes
    GENERIC_RW = 0x80000000 | 0x40000000
    OPEN_EXISTING = 3
    INVALID = ctypes.c_void_p(-1).value
    cg, d = _secured("g7")
    try:
        cg.add("c3_w1", "# 功能名：持锁夹具\n# 正文：独占锁 共用词zz\n",
               layer="knowledge", importance=0.5)
        cg.flush()
        MOD["readcache"].install(cg)
        e = cg.index["nodes"]["c3_w1"]
        p = cg._node_disk_path(e)
        key = e["path"]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                    ctypes.c_uint32, ctypes.c_void_p,
                                    ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.c_void_p]
        h = k32.CreateFileW(p, GENERIC_RW, 0, None, OPEN_EXISTING, 0, None)
        held = h not in (None, INVALID)
        ok(held, "G7a 注入生效：CreateFileW(dwShareMode=0) 独占持住节点 md 文件",
           "handle=%s" % h)
        try:
            MOD["readcache"].clear(cg)         # 冷缓存：确保本次走读路径
            ids_lock = _ids(cg.search("独占锁")) if held else None
            entry_lock = cg._read_cache.get(key) if held else None
            stat_lock = fsutil.transient_read_stats() if held else None
        finally:
            if held:
                k32.CloseHandle(h)
        ok(ids_lock == [],
           "G7b 持锁期搜索 **miss**（fail-closed：不可读即不参与检索）",
           "hits=%s" % (ids_lock,))
        ok(entry_lock is None,
           "G7c 持锁期负结果**不入缓存**（修前此处为 (gen,(None,None)) 固化条目）",
           "cache=%r" % (entry_lock,))
        ids_r = _ids(cg.search("独占锁"))
        ok(ids_r == ["c3_w1"],
           "G7d 释放句柄后**首次**查询即命中（瞬态窗口为零）",
           "after=%s" % (ids_r,))
        ok(stat_lock is not None and stat_lock[0] >= 1,
           "G7e 持锁期记账可见（计数 ≥ 1）", stat_lock)
    finally:
        _close_all()
        _cleanup(d)


# ================================================================ 变异表
# 每条 = (名称, 模块键, 变异形态, 源码锚点, 替换文本, 预期转红条数)。
# 锚点必须逐字命中当前源码（找不到 → ANCHOR-MISS → 退出码 2，fail-closed）。
# 形态：swap = 整模块替换（断言组经 MOD 取）；attr = 把变异体的同名函数注入
# 活模块的同名属性（判别函数被 mdcg 以模块属性调用，换副本即生效）。
_MUT_ADMIT_OLD = ("            val = orig_status(entry)\n"
                  "            if val[2] is not None:\n"
                  "                # C-3：瞬时读失败**不入缓存**（本次即返回，"
                  "下次查询重试该 path）。\n"
                  "                return val\n")
_MUT_ADMIT_NEW = ("            val = orig_status(entry)\n"
                  "            if False:  # MUT：撤掉「瞬时读失败不入缓存」判据\n"
                  "                return val\n")
_MUT_CLS_OLD = ("    if isinstance(exc, FileNotFoundError):\n"
                "        return READ_FAIL_ABSENT\n"
                "    return READ_FAIL_TRANSIENT\n")
_MUT_CLS_NEW = ("    return READ_FAIL_ABSENT  # MUT：一律判终态（瞬时被当不存在）\n")

_MUTATIONS = (
    ("C-3a 撤掉「瞬时读失败不入缓存」的接纳判据（回缺陷形态）",
     "readcache", "swap", _MUT_ADMIT_OLD, _MUT_ADMIT_NEW, 8),
    ("C-3b 判别退化：一律判终态（瞬时失败被当「不存在」）",
     "fsutil", "attr", _MUT_CLS_OLD, _MUT_CLS_NEW, 9),
)

_RELPATH = {
    "readcache": os.path.join("md_cg", "readcache.py"),
    "fsutil": os.path.join("md_cg", "fsutil.py"),
}


def _load_mutated(relpath: str, old: str, new: str):
    """把 `relpath` 的源码做定点文本替换后 exec 成独立模块（不落盘、不改工作区）。"""
    path = os.path.join(_REPO, relpath)
    src = open(path, encoding="utf-8").read()
    if old not in src:
        return None, src
    mut_src = src.replace(old, new, 1)
    mod = types.ModuleType("md_cg._c3trn_mut")
    mod.__package__ = "md_cg"
    mod.__file__ = path
    exec(compile(mut_src, path, "exec"), mod.__dict__)      # noqa: S102 —— 定点变异
    return mod, src


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    _SKIP.clear()
    for g in (g0, g1, g2, g3, g4, g5, g6, g7):
        try:
            g()
        except Exception as exc:                            # noqa: BLE001
            import traceback
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            print(traceback.format_exc()[-800:])
    _close_all()
    return len(_FAIL)


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把修复点改回缺陷形态，套件必须按预期条数转红\n")
    if list_only:
        for name, key, kind, old, new, exp in _MUTATIONS:
            print("  %-46s %-10s %-5s expect_red=%d" % (name, key, kind, exp))
        return 0

    anchor_miss = []
    bad = []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, key, kind, old, new, expect in _MUTATIONS:
        mod, src = _load_mutated(_RELPATH[key], old, new)
        if mod is None:
            print("  ANCHOR-MISS %s —— 锚点在 %s 当前源码里找不到"
                  "（实现改了却没同步本表；基线不得静默漂移）"
                  % (name, _RELPATH[key]))
            anchor_miss.append(name)
            continue
        live_mod = MOD.get(key)
        live_attr = None
        if kind == "swap":
            MOD[key] = mod
        else:
            live_mod = sys.modules["md_cg." + key]
            live_attr = getattr(live_mod, _mut_func_name(old))
            setattr(live_mod, _mut_func_name(old), getattr(mod, _mut_func_name(old)))
        try:
            with contextlib.redirect_stdout(buf := io.StringIO()):
                fails_extra = _run_groups()
            detail = buf.getvalue()
        finally:
            if kind == "swap":
                MOD[key] = live_mod
            else:
                setattr(live_mod, _mut_func_name(old), live_attr)
        red = [l for l in detail.splitlines() if l.strip().startswith("FAIL ")]
        verdict = "红" if fails_extra else "**仍全绿 = 该判据空转**"
        mark = "OK  " if fails_extra == expect else "MISMATCH"
        print("  %s %-46s 红项=%d 预期=%d  %s"
              % (mark, name, fails_extra, expect, verdict))
        for l in red:
            print("        " + l.strip()[5:])
        if fails_extra != expect:
            bad.append("%s（红=%d 预期=%d）" % (name, fails_extra, expect))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都被打红且恰好命中预期项数）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def _mut_func_name(old: str) -> str:
    """attr 形态变异的目标函数名（按锚点文本判定，防两处锚点串味）。"""
    return "classify_read_failure" if "FileNotFoundError" in old else ""


def main() -> int:
    if "--mutate" in sys.argv:
        try:
            return _mutate_mode("--list" in sys.argv)
        finally:
            _cleanup(_TMP)
    try:
        n_fail = _run_groups()
        print("\nC-3 守卫（瞬态读失败不得固化）：%d 通过，%d 失败，%d 跳过"
              % (len(_PASS), n_fail, len(_SKIP)))
        return 0 if not n_fail else 1
    finally:
        _cleanup(_TMP)


if __name__ == "__main__":
    sys.exit(main())
