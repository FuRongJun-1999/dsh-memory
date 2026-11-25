# -*- coding: utf-8 -*-
"""守卫 · search_rrf HotCache 安全隔离 + recall 预算/过滤 + mdcos _dirty_lock（Refs #1005）。

覆盖三组回归与安全不变量：
  A (A1-04) HotCache 身份/密钥态/strict_conditions 隔离与 bm25.access_key can_admin：
    - A1 Admin → Guest 在默认非-bm25 路径不命中缓存，不经 meta.provenance /
         path_fingerprint 泄漏 secret 节点 ID 或因果边条件明文；
    - A2 Guest → Admin 反向投毒阻断（Admin 不命中 Guest 缓存，完整读回 secret 节点，
         且同身份重复查询仍正常命中 HotCache）；
    - A3 DEK 变化/锁库态隔离（换/清 DEK 后非-bm25 路径不复用旧缓存）；
    - A4 bm25.access_key 纳入 can_admin，仅 can_admin 不同的双身份在 BM25 路不撞键；
    - A5 strict_conditions 入键（strict_conditions=True/False 切换不串缓存）；
    - A6 MdCGSecure.search_rrf 纵深防线：纵使底层 provenance 含不可读条目，返回前
         按只读副本剔除且不原地污染缓存字典。

  B (A1-05) recall() #1005 预算守恒 / 去重 / 作用域过滤 / 日期与时间线一致性：
    - B1 raw_min 补位严守 budget_tokens 硬上限（不 4× 爆仓），同时为补位条目一致
         填充 created_at_date / content_dated（支持 ISO received_at）并进入 timeline；
    - B2 max_item_tokens=0 时超长 raw 条目不破坏预算且原子回滚已腾派生条目；
    - B3 _prof_cap 裁剪 profile 卡同步扣减 tokens_used（含 MDCG_PROFILE_CARDS=0）；
    - B4 非法 MDCG_RAW_MIN 环境变量不抹掉 reading_policy / coverage_gaps；
    - B5 _profile_source_nodes 与 _selfstmt_nodes 重合节点在 pack 内零重复（_seen.add）；
    - B6 _profile_candidates / _profile_source_nodes / _selfstmt_nodes / _slot_cards
         一致执行 layer / session / branch / validity / retired / include_work 过滤；
    - B7 card_of 对 epoch 浮点与 ISO received_at 均格式化为 YYYY-MM-DD（不截原始 epoch）。

  C (A1-06) mdcos.py 全部 self._dirty 访问站点的 _dirty_lock 守卫：
    - C1 静态 AST 审计：mdcos.py 内零锁外 self._dirty 访问，且 _dirty_lock 内零
         flush()/open()/FileLock()（严格叶锁，零锁序倒置）；
    - C2 运行时持锁深度观测：MdCGOS.add / MdCGSecure._index_sensitivity /
         MdCGOS.review_decide(merge) / MdCGSecure.verify 均在 _dirty_lock 内访问 _dirty；
    - C3 真线程并发压测：高并发 MdCGSecure.add（命中 add + _index_sensitivity）与
         flush() 碰撞，零 RuntimeError 且重开后节点完整可读。

运行：python -X utf8 -m md_cg.test_search_rrf_cache_and_recall_guards
"""
from __future__ import annotations

import ast
import os
import shutil
import sys
import tempfile
import threading
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# 模块级沙箱隔离：在导入 md_cg 子模块前固定辅助根目录并清理外部会话/令牌变量。
_BOOT_TMP = tempfile.mkdtemp(prefix="mdcg_rrf_guard_boot_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_BOOT_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "ab" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_BOOT_TMP, "tokens.json")
os.environ["MDCG_WRITE_GATE"] = "warn"
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
for _env_k in ("MDCG_TOKEN", "MDCG_SESSION", "DSH_SESSION_ID",
               "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_LEGACY_ENV_AUTH",
               "MDCG_LEGACY_ENV_ADMIN", "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE"):
    os.environ.pop(_env_k, None)

from md_cg import bm25 as _bm25  # noqa: E402
from md_cg import hotcache as _hc  # noqa: E402
from md_cg.mdcg import _DirtyDict  # noqa: E402
from md_cg.mdcos import MdCGOS, MdCGSecure, est_tokens  # noqa: E402
from md_cg.security import Principal  # noqa: E402

_PASS = []
_FAIL = []

_CCG = (
    "# 功能名：{name}\n"
    "# 生效条件：{cond}\n"
    "# 子功能：s\n"
    "# 执行：{body}\n"
    "# 验证方式：test\n"
    "# 不适用条件：无\n"
)


def ok(cond, label, detail=""):
    (_PASS if cond else _FAIL).append(label)
    suffix = ("  <- " + str(detail)[:240]) if (detail and not cond) else ""
    print(("  PASS " if cond else "  FAIL ") + label + suffix)
    return bool(cond)


class _EnvGuard:
    """临时设置/恢复环境变量，保证用例之间零残留。"""

    def __init__(self, updates):
        self._updates = dict(updates)
        self._saved = {}

    def __enter__(self):
        for k, v in self._updates.items():
            self._saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        return self

    def __exit__(self, *exc):
        for k, prev in self._saved.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev
        return False


class _TrackingRLock:
    """包装 RLock，按线程精确追踪持锁深度。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._tls = threading.local()

    @property
    def depth(self) -> int:
        return getattr(self._tls, "depth", 0)

    def acquire(self, *a, **kw):
        got = self._lock.acquire(*a, **kw)
        if got:
            self._tls.depth = self.depth + 1
        return got

    def release(self):
        self._tls.depth = max(0, self.depth - 1)
        return self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


class _ObservingDirty(_DirtyDict):
    """记录 _dirty 访问发生时的 _dirty_lock 深度。"""

    def __init__(self, lock: _TrackingRLock, log: list, src: _DirtyDict):
        super().__init__()
        self._obs_lock = lock
        self._obs_log = log
        self._obs_on = False
        self.root = src.root
        self.write_gen = src.write_gen
        self.broad_gen = src.broad_gen
        self.path_gen = dict(src.path_gen)
        self.staged_stat = dict(src.staged_stat)
        self.superseded_ids = set(src.superseded_ids)
        dict.update(self, src)
        self._obs_on = True

    def _note(self, op: str):
        if object.__getattribute__(self, "_obs_on"):
            lk = object.__getattribute__(self, "_obs_lock")
            lg = object.__getattribute__(self, "_obs_log")
            lg.append((op, lk.depth))

    def __setitem__(self, k, v):
        self._note("__setitem__")
        return super().__setitem__(k, v)

    def get(self, k, default=None):
        self._note("get")
        return super().get(k, default)


# ================================================================ Group A (A1-04)
def test_group_a_hotcache_security(tmp_root: str):
    print("== Group A (A1-04): search_rrf HotCache principal/DEK/strict_conditions/can_admin ==")
    master = bytes.fromhex("cd" * 32)
    admin = Principal(tenant="t1", actor="admin_user", clearance="secret",
                      can_write=True, can_admin=True, role="designer",
                      session="sess_admin", auth_mode="test")
    guest = Principal(tenant="t1", actor="guest_user", clearance="public",
                      can_write=False, can_admin=False, role="guest",
                      session="sess_guest", auth_mode="test")

    r1 = os.path.join(tmp_root, "a_chain")
    with _EnvGuard({"MDCG_HOTCACHE": "1"}):
        cg = MdCGSecure(r1, principal=admin, master_key=master)
        try:
            cg.add(
                "n_pub",
                _CCG.format(name="公开入口", cond="全时窗",
                            body="量子检索 测试公开条目 链式起点"),
                layer="knowledge", sensitivity="public",
                tags=["量子检索"],
                edges=[{"target": "n_sec", "type": "causal",
                        "condition": "DUMMY_SECRET_EDGE_COND_4433"}],
            )
            cg.add(
                "n_sec",
                _CCG.format(name="机密节点", cond="全时窗",
                            body="绝密目标 DUMMY_SECRET_BODY_4433"),
                layer="knowledge", sensitivity="secret",
                tags=["机密"],
            )
            cg.flush()

            # A1: Admin -> Guest on default non-bm25 paths
            res_a, meta_a = cg.search_rrf("量子检索", k=10)
            ids_a = [r[0]["id"] for r in res_a]
            prov_a_str = str(meta_a.get("provenance") or "")
            ok("n_sec" in ids_a and "DUMMY_SECRET_EDGE_COND_4433" in prov_a_str,
               "A1a 前置：Admin 默认非-bm25 路径命中 n_sec 且 provenance 含边条件",
               (ids_a, prov_a_str[:160]))

            with cg.scoped_scope(principal=guest):
                res_g, meta_g = cg.search_rrf("量子检索", k=10)
            ids_g = [r[0]["id"] for r in res_g]
            prov_g = meta_g.get("provenance") or {}
            fp_g = str(meta_g.get("path_fingerprint") or "")
            ok(meta_g.get("cached") is not True
               and "n_sec" not in ids_g
               and "n_sec" not in prov_g
               and "DUMMY_SECRET_EDGE_COND_4433" not in str(prov_g)
               and "DUMMY_SECRET_EDGE_COND_4433" not in fp_g,
               "A1b Admin→Guest 非-bm25 路径不撞缓存且零 secret ID/边条件明文泄漏",
               {"cached": meta_g.get("cached"), "ids": ids_g,
                "prov": str(prov_g)[:180]})

            # A2: Guest -> Admin reverse cache poisoning on non-bm25 paths
            hc = _hc.get(cg)
            if hc is not None:
                hc.clear()
            with cg.scoped_scope(principal=guest):
                res_g2, meta_g2 = cg.search_rrf("量子检索 公开", k=10)
            res_a2, meta_a2 = cg.search_rrf("量子检索 公开", k=10)
            ids_a2 = [r[0]["id"] for r in res_a2]
            ok(meta_a2.get("cached") is not True and "n_sec" in ids_a2,
               "A2a Guest→Admin 非-bm25 路径不发生缓存投毒（Admin 完整取回 n_sec）",
               {"g_ids": [r[0]["id"] for r in res_g2], "a_ids": ids_a2,
                "a_cached": meta_a2.get("cached")})

            # 同身份重查必须继续命中缓存（不能把缓存打废）
            res_a3, meta_a3 = cg.search_rrf("量子检索 公开", k=10)
            ok(meta_a3.get("cached") is True and "n_sec" in [r[0]["id"] for r in res_a3],
               "A2b 同身份重复查询仍正常命中 HotCache",
               {"cached": meta_a3.get("cached")})

            # A3: DEK 变动（锁库/换密钥态）在非-bm25 路径不得命中旧缓存
            _saved_dek = cg.dek
            try:
                cg.dek = None
                res_locked, meta_locked = cg.search_rrf("量子检索 公开", k=10)
            finally:
                cg.dek = _saved_dek
            ok(meta_locked.get("cached") is not True
               and "n_sec" not in [r[0]["id"] for r in res_locked],
               "A3 DEK 置空后非-bm25 路径不命中解锁态缓存且不回 n_sec",
               {"cached": meta_locked.get("cached"),
                "ids": [r[0]["id"] for r in res_locked]})

            # A6: 纵深防线——即便强制向 HotCache 注入含不可读节点的 provenance，
            # MdCGSecure.search_rrf 返回体不得泄漏，且不原地污染缓存源对象
            orig_prov = dict(meta_a.get("provenance") or {})
            poisoned_meta = dict(meta_a)
            poisoned_meta["provenance"] = orig_prov
            orig_super = MdCGOS.search_rrf

            def _fake_super(self_cg, *a, **kw):
                return list(res_a), poisoned_meta

            MdCGOS.search_rrf = _fake_super
            try:
                with cg.scoped_scope(principal=guest):
                    res_def, meta_def = cg.search_rrf("量子检索", k=10)
            finally:
                MdCGOS.search_rrf = orig_super
            ok("n_sec" not in [r[0]["id"] for r in res_def]
               and "n_sec" not in (meta_def.get("provenance") or {})
               and "DUMMY_SECRET_EDGE_COND_4433" not in str(meta_def.get("provenance") or "")
               and "n_sec" in orig_prov,
               "A6 MdCGSecure.search_rrf 纵深剔除不可读 provenance 且不原地修改源字典",
               {"def_prov": str(meta_def.get("provenance"))[:160],
                "orig_kept": "n_sec" in orig_prov})
        finally:
            cg.close()

    # A4: bm25.access_key 纳入 can_admin + BM25 HotCache 跨 can_admin 隔离
    r2 = os.path.join(tmp_root, "a_can_admin")
    p_no = Principal(tenant="t1", actor="same_actor", clearance="private",
                     can_write=True, can_admin=False, role="designer",
                     session="sess_a", auth_mode="test")
    p_yes = Principal(tenant="t1", actor="same_actor", clearance="private",
                      can_write=True, can_admin=True, role="designer",
                      session="sess_a", auth_mode="test")
    with _EnvGuard({"MDCG_HOTCACHE": "1"}):
        cg2 = MdCGSecure(r2, principal=p_yes, master_key=master)
        try:
            cg2.add("n_pub_b",
                    _CCG.format(name="公开基线", cond="全时窗",
                                body="alpha_token_bm25 public item"),
                    layer="knowledge", sensitivity="public")
            cg2.add("n_priv_other",
                    _CCG.format(name="异会话私有", cond="全时窗",
                                body="alpha_token_bm25 private other session"),
                    layer="knowledge", sensitivity="private",
                    session="sess_b")
            cg2.flush()

            with cg2.scoped_scope(principal=p_no):
                k_no = _bm25.access_key(cg2)
                res_no, meta_no = cg2.search_rrf("alpha_token_bm25", k=10, paths=("bm25",))
            with cg2.scoped_scope(principal=p_yes):
                k_yes = _bm25.access_key(cg2)
                res_yes, meta_yes = cg2.search_rrf("alpha_token_bm25", k=10, paths=("bm25",))
            ok(k_no != k_yes,
               "A4a bm25.access_key 区分仅 can_admin 不同的双身份",
               (k_no, k_yes))
            ids_no = [r[0]["id"] for r in res_no]
            ids_yes = [r[0]["id"] for r in res_yes]
            ok("n_priv_other" not in ids_no
               and "n_priv_other" in ids_yes
               and meta_yes.get("cached") is not True,
               "A4b BM25 路 can_admin=False 不再投毒压制 can_admin=True 的跨会话 private 节点",
               {"no": ids_no, "yes": ids_yes, "yes_cached": meta_yes.get("cached")})
        finally:
            cg2.close()

    # A5: strict_conditions 进入 HotCache 键
    r3 = os.path.join(tmp_root, "a_strict_cond")
    with _EnvGuard({"MDCG_HOTCACHE": "1"}):
        cg3 = MdCGOS(r3, autoflush=100)
        try:
            cg3.add(
                "n_cond",
                "# 功能名：严格条件测试\n"
                "# 生效条件：仅在生产环境且开启灰度开关时生效\n"
                "# 子功能：s\n"
                "# 执行：strictcond_probe 具体执行步骤\n"
                "# 验证方式：test\n"
                "# 不适用条件：无\n",
                layer="knowledge",
                verification_basis="data",
            )
            cg3.flush()
            res_t, meta_t = cg3.search_rrf(
                "strictcond_probe", k=5, paths=("lexical",),
                context="开发环境", judge=True, strict_conditions=True)
            res_f, meta_f = cg3.search_rrf(
                "strictcond_probe", k=5, paths=("lexical",),
                context="开发环境", judge=True, strict_conditions=False)
            q_t = res_t[0][2] if res_t else {}
            q_f = res_f[0][2] if res_f else {}
            ok(meta_f.get("cached") is not True
               and q_t.get("relaxed") is not True
               and q_f.get("relaxed") is True
               and q_f.get("usable") is True,
               "A5 strict_conditions=False 不命中 strict_conditions=True 的缓存且放宽态区分",
               {"cached_f": meta_f.get("cached"), "q_t": q_t, "q_f": q_f})
        finally:
            cg3.close()


# ================================================================ Group B (A1-05)
def test_group_b_recall_budget_and_filters(tmp_root: str):
    print("== Group B (A1-05): recall() raw_min 预算 / _prof_cap / _seen 去重 / 作用域过滤 ==")
    # B1 + B2 + B3 + B4: raw_min 预算守恒、日期/reldate/timeline、_prof_cap 记账、非法 env
    r1 = os.path.join(tmp_root, "b_budget")
    cg = MdCGOS(r1, autoflush=100)
    try:
        for i in range(6):
            cg.add(
                "profile-role-%02d" % i,
                _CCG.format(name="档案%d" % i, cond="全时窗",
                            body="预算回归探针 档案概要 编号%d" % i),
                layer="knowledge", tags=["profile", "档案"], importance=0.95,
            )
        long_body_1 = ("预算回归探针 昨天完成了全套联调验收，"
                       + "详细现场记录与步骤核对内容。" * 40)
        long_body_2 = ("预算回归探针 前天复核了配置项，"
                       + "补充细节与对照参数说明。" * 30)
        cg.add(
            "turn_big_01",
            "# 对话\n" + long_body_1 + "\n",
            layer="contextual", tags=["对话"], importance=0.05,
            received_at="2026-11-24T10:00:00",
        )
        cg.add(
            "turn_big_02",
            "# 对话\n" + long_body_2 + "\n",
            layer="contextual", tags=["对话"], importance=0.05,
            received_at=1795488442.29,
        )
        cg.flush()

        # B1: raw_min 严守 budget_tokens=220，且 created_at_date / content_dated / timeline 完整
        out = cg.recall("预算回归探针", budget_tokens=220, k=20)
        pack = out.get("pack") or []
        pol_tok = est_tokens(out.get("reading_policy") or "")
        pack_tok = sum(int(e.get("tokens") or 0) for e in pack)
        recent_tok = sum(int(r.get("tokens") or 0) for r in (out.get("recent") or []))
        used = int(out.get("tokens_used") or 0)
        raw_items = [e for e in pack if not str(e.get("id") or "").startswith("profile-")]
        tl_ids = {row.get("id") for row in (out.get("timeline") or [])}
        tlg_ids = {it.get("id") for g in (out.get("timeline_groups") or [])
                   for it in (g.get("items") or [])}

        ok(used <= 220 and used == pack_tok + recent_tok + pol_tok,
           "B1a raw_min 补位严守 budget_tokens=220 且 tokens_used 精确对账",
           {"used": used, "pack_tok": pack_tok, "pol_tok": pol_tok})
        ok(len(raw_items) >= 1 and (out.get("meta") or {}).get("raw_min_applied", 0) >= 1,
           "B1b raw_min 成功以截断摘录救回至少 1 条超长原话",
           {"raw_ids": [e.get("id") for e in raw_items],
            "applied": (out.get("meta") or {}).get("raw_min_applied")})
        all_dated = all(e.get("created_at_date") and e.get("content_dated") for e in pack)
        iso_hit = [e for e in raw_items if e.get("id") == "turn_big_01"]
        iso_ok = (not iso_hit) or (
            iso_hit[0].get("created_at_date") == "2026-11-24"
            and "2026-11-23" in str(iso_hit[0].get("content_dated") or "")
        )
        ok(all_dated and iso_ok,
           "B1c 补位条目具备 created_at_date 与 content_dated（兼容 ISO received_at）",
           [(e.get("id"), e.get("created_at_date"), str(e.get("content_dated"))[:40])
            for e in raw_items])
        ok(all(e.get("id") in tl_ids and e.get("id") in tlg_ids for e in raw_items),
           "B1d 补位条目同步进入 timeline 与 timeline_groups",
           {"raw_ids": [e.get("id") for e in raw_items], "tl": tl_ids})

        # B2: max_item_tokens=0 时超长 raw 原子回滚、不破坏派生条目也不超预算
        cg.add(
            "turn_small_03",
            "# 对话\n预算回归探针 短原话核对通过\n",
            layer="contextual", tags=["对话"], importance=0.04,
            received_at=1795488442.29,
        )
        cg.flush()
        out_notrunc = cg.recall("预算回归探针", budget_tokens=220, k=20, max_item_tokens=0)
        p_nt = out_notrunc.get("pack") or []
        u_nt = int(out_notrunc.get("tokens_used") or 0)
        pol_nt = est_tokens(out_notrunc.get("reading_policy") or "")
        ok(u_nt <= 220 and u_nt == sum(int(e.get("tokens") or 0) for e in p_nt) + pol_nt
           and len(p_nt) >= 1,
           "B2 max_item_tokens=0 时超长 raw 原子回滚且总预算严守 <= 220",
           {"used": u_nt, "ids": [e.get("id") for e in p_nt]})

        # B3: _prof_cap 裁剪后 tokens_used 精确扣减（含 cap=2 与 cap=0）
        with _EnvGuard({"MDCG_RAW_MIN": "0", "MDCG_PROFILE_CARDS": "2"}):
            o_cap2 = cg.recall("预算回归探针", budget_tokens=500, k=20)
        p2 = o_cap2.get("pack") or []
        profs2 = [e for e in p2 if str(e.get("id") or "").startswith("profile-")]
        u2 = int(o_cap2.get("tokens_used") or 0)
        pol2 = est_tokens(o_cap2.get("reading_policy") or "")
        ok(len(profs2) == 2 and u2 == sum(int(e.get("tokens") or 0) for e in p2) + pol2,
           "B3a MDCG_PROFILE_CARDS=2 裁剪后 tokens_used 精确扣减",
           {"profs": len(profs2), "used": u2,
            "expected": sum(int(e.get("tokens") or 0) for e in p2) + pol2})

        with _EnvGuard({"MDCG_RAW_MIN": "0", "MDCG_PROFILE_CARDS": "0"}):
            o_cap0 = cg.recall("预算回归探针", budget_tokens=500, k=20)
        p0 = o_cap0.get("pack") or []
        profs0 = [e for e in p0 if str(e.get("id") or "").startswith("profile-")]
        u0 = int(o_cap0.get("tokens_used") or 0)
        pol0 = est_tokens(o_cap0.get("reading_policy") or "")
        ok(len(profs0) == 0 and u0 == sum(int(e.get("tokens") or 0) for e in p0) + pol0,
           "B3b MDCG_PROFILE_CARDS=0 时 profile 清零且 tokens_used 精确对账",
           {"profs": len(profs0), "used": u0})

        # B4: 非法 MDCG_RAW_MIN 不抹掉 reading_policy / coverage
        with _EnvGuard({"MDCG_RAW_MIN": "invalid_num"}):
            o_bad_env = cg.recall("预算回归探针", budget_tokens=400, k=20)
        ok(bool(o_bad_env.get("reading_policy")) and int(o_bad_env.get("tokens_used") or 0) <= 400,
           "B4 非法 MDCG_RAW_MIN 回落默认且不抹掉 reading_policy",
           {"has_policy": bool(o_bad_env.get("reading_policy")),
            "used": o_bad_env.get("tokens_used")})

        # B7: card_of 格式化 epoch / ISO received_at 为 YYYY-MM-DD
        n_iso = cg.get("turn_big_01")
        n_ep = cg.get("turn_big_02")
        c_iso = cg.card_of(n_iso)
        c_ep = cg.card_of(n_ep)
        ok("日期: 2026-11-24" in c_iso and "日期: 2026-11-24" in c_ep and "1795488442" not in c_ep,
           "B7 card_of 正确格式化 ISO 与 epoch received_at（不截原始 epoch 串）",
           (c_iso, c_ep))
    finally:
        cg.close()

    # B5 + B6: _seen 去重 + 全部作用域过滤器一致性
    r2 = os.path.join(tmp_root, "b_scope_dedup")
    cg2 = MdCGOS(r2, autoflush=100)
    try:
        # 构造一条同时命中 _selfstmt_nodes 和 _profile_source_nodes 的自述节点
        cg2.add(
            "turn_self_01",
            "我叫角色甲，今年30岁，住在杭州，是一名软件工程师，平时喜欢爬山。",
            layer="knowledge", session="sess_main", tags=["自述"],
        )
        cg2.add(
            "profile-role-角色甲",
            "# 功能名：角色甲资料\n# 生效条件：全时窗\n# 子功能：s\n# 执行：档案\n"
            "# 验证方式：test\n# 不适用条件：无\n"
            "- 2026-11-01 | 角色甲在杭州做工程师（来源 turn_self_01）\n"
            "- 2026-11-01 | 过期源记录（来源 n_exp）\n"
            "- 2026-11-01 | 归档源记录（来源 n_arch）\n",
            layer="knowledge", session="sess_main",
            tags=["profile", "role:角色甲"],
        )
        # B5 检查：同节点在 _profile_source_nodes 与 _selfstmt_nodes 同时出现时 pack 零重复
        cg2.flush()
        out_dedup = cg2.recall("角色甲", budget_tokens=1200, k=20,
                               layer="knowledge", session="sess_main")
        ids_dedup = [e.get("id") for e in (out_dedup.get("pack") or [])]
        ok(len(ids_dedup) == len(set(ids_dedup)) and "turn_self_01" in ids_dedup,
           "B5 _profile_source_nodes 与 _selfstmt_nodes 重合节点在 pack 内零重复",
           ids_dedup)

        # B6: 注入各类应被过滤器挡住的越界节点（全含自述句式，强制进入 selfstmt 索引）
        cg2.add(
            "n_exp",
            "我叫角色甲，住在上海，过期测试自述内容。",
            layer="knowledge", session="sess_main",
            valid_until=time.time() - 3600,
        )
        cg2.add(
            "n_arch",
            "我叫角色甲，住在广州，已归档测试自述内容。",
            layer="knowledge", session="sess_main",
        )
        cg2.set_state("n_arch", "demoted", reason="test")
        _arch_res = cg2.set_state("n_arch", "archived", reason="test")
        ok(_arch_res.get("ok") is True, "B6-前置：n_arch 成功推进至 archived 状态", _arch_res)
        cg2.add(
            "n_branch",
            "我叫角色甲，住在成都，实验分支测试自述内容。",
            layer="knowledge", session="sess_main",
            branch_id="exp_b",
        )
        cg2.add(
            "n_work",
            "我叫角色甲，住在武汉，工具输出工作角色自述内容。",
            layer="knowledge", session="sess_main",
            role="tool-output",
        )
        cg2.add(
            "n_other_sess",
            "我叫角色甲，住在西安，他会话自述内容。",
            layer="knowledge", session="sess_other",
        )
        cg2.add(
            "n_other_layer",
            "我叫角色甲，住在南京，contextual 层自述内容。",
            layer="contextual", session="sess_main",
        )
        cg2.add(
            "profile-role-角色乙",
            "# 角色乙档案\n- 基本信息：姓名 角色乙；学历 本科；城市 深圳\n",
            layer="contextual", session="sess_other",
            tags=["profile", "role:角色乙"],
        )
        cg2.flush()

        out_strict = cg2.recall(
            "我叫角色甲 我的全名和学历 住哪个城市",
            budget_tokens=1500, k=20,
            layer="knowledge", session="sess_main",
            validity=True, branch=None, include_work=False,
        )
        ids_strict = [e.get("id") for e in (out_strict.get("pack") or [])]
        forbidden = {"n_exp", "n_arch", "n_branch", "n_work",
                     "n_other_sess", "n_other_layer", "profile-role-角色乙"}
        leaked = sorted(forbidden.intersection(ids_strict))
        ok(not leaked and len(ids_strict) == len(set(ids_strict)),
           "B6 post-search 注入一致执行 layer/session/branch/validity/retired/include_work 过滤",
           {"leaked": leaked, "ids": ids_strict})
    finally:
        cg2.close()


# ================================================================ Group C (A1-06)
def _audit_mdcos_dirty_ast():
    """静态 AST 审计 md_cg/mdcos.py 的全部 self._dirty 访问与叶锁纪律。"""
    src_path = os.path.join(_REPO, "md_cg", "mdcos.py")
    with open(src_path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=src_path)
    unlocked = []
    bad_inside_lock = []

    class _V(ast.NodeVisitor):
        def __init__(self):
            self.fn = []
            self.in_dl = 0

        def visit_FunctionDef(self, node):
            self.fn.append(node.name)
            self.generic_visit(node)
            self.fn.pop()

        def visit_With(self, node):
            is_dl = any("_dirty_lock" in ast.unparse(i.context_expr) for i in node.items)
            if is_dl:
                self.in_dl += 1
            self.generic_visit(node)
            if is_dl:
                self.in_dl -= 1

        def visit_Attribute(self, node):
            if (node.attr == "_dirty"
                    and isinstance(node.value, ast.Name) and node.value.id == "self"):
                if self.in_dl == 0:
                    unlocked.append((".".join(self.fn), node.lineno))
            self.generic_visit(node)

        def visit_Call(self, node):
            if self.in_dl > 0:
                fname = ""
                if isinstance(node.func, ast.Attribute):
                    fname = node.func.attr
                elif isinstance(node.func, ast.Name):
                    fname = node.func.id
                if fname in ("flush", "_flush_locked", "open", "FileLock",
                             "atomic_write", "publish", "rebuild_index"):
                    bad_inside_lock.append((".".join(self.fn), fname, node.lineno))
            self.generic_visit(node)

    _V().visit(tree)
    return unlocked, bad_inside_lock


def test_group_c_dirty_lock_sites(tmp_root: str):
    print("== Group C (A1-06): mdcos.py _dirty_lock 静态审计 + 运行时观测 + 并发压测 ==")
    unlocked, bad_in_lock = _audit_mdcos_dirty_ast()
    ok(not unlocked, "C1a 静态 AST 审计：mdcos.py 零锁外 self._dirty 访问", unlocked)
    ok(not bad_in_lock, "C1b 静态 AST 审计：mdcos.py _dirty_lock 内零 flush/IO/FileLock（叶锁）",
       bad_in_lock)

    # C2: 运行时锁深度观测（add / _index_sensitivity / review_decide(merge) / verify）
    r_obs = os.path.join(tmp_root, "c_obs")
    master = bytes.fromhex("ef" * 32)
    admin = Principal(tenant="t1", actor="admin_c", clearance="secret",
                      can_write=True, can_admin=True, role="designer",
                      session="sess_c", auth_mode="test")
    cg = MdCGSecure(r_obs, principal=admin, master_key=master,
                    autoflush=1000, async_flush=False)
    try:
        lock = _TrackingRLock()
        log = []
        cg._dirty_lock = lock
        cg._dirty = _ObservingDirty(lock, log, cg._dirty)

        # C2a: MdCGSecure.add -> MdCGOS.add(1429) + MdCGSecure._index_sensitivity(8308)
        log.clear()
        cg.add("c_n1", _CCG.format(name="锁测1", cond="全时窗", body="正文1"),
               layer="knowledge", role="note", session="sess_c", sensitivity="internal")
        set_depths = [d for op, d in log if op == "__setitem__"]
        ok(len(set_depths) >= 2 and all(d >= 1 for d in set_depths),
           "C2a MdCGSecure.add（含 MdCGOS.add + _index_sensitivity）全部在 _dirty_lock 内写 _dirty",
           log)

        # C2b: MdCGSecure.verify 在索引未含条目时回落 _dirty.get 持锁
        log.clear()
        saved_entry = cg.index["nodes"].pop("c_n1", None)
        try:
            cg.verify("c_n1", "证据核对", "confirmed")
        except Exception:
            pass
        finally:
            if saved_entry is not None:
                cg.index["nodes"]["c_n1"] = saved_entry
        get_depths = [d for op, d in log if op == "get"]
        ok(bool(get_depths) and all(d >= 1 for d in get_depths),
           "C2b MdCGSecure.verify 回落 _dirty.get 在 _dirty_lock 内执行",
           log)

        # C2c: review_decide(merge) 写 _dirty 在 _dirty_lock 内，且 flush 严格在锁外
        cg.flush()
        pid = cg.propose(
            "c_n1_merge",
            _CCG.format(name="合并增量", cond="全时窗", body="新增补充事实"),
            layer="knowledge", tags=["t"], extra={"merge_into": "c_n1"},
        )
        flush_depths = []
        orig_flush = cg.flush

        def _obs_flush():
            flush_depths.append(lock.depth)
            return orig_flush()

        cg.flush = _obs_flush
        log.clear()
        try:
            dec = cg.review_decide(pid, "merge", reason="合并验证",
                                   merge_into="c_n1",
                                   redteam={"verdict": "pass", "issues": []})
        finally:
            cg.flush = orig_flush
        merge_sets = [d for op, d in log if op == "__setitem__"]
        ok(dec.get("ok") is True and bool(merge_sets)
           and all(d >= 1 for d in merge_sets)
           and all(d == 0 for d in flush_depths),
           "C2c review_decide(merge) 在 _dirty_lock 内更新 _dirty 且 flush 在锁外",
           {"dec": dec, "log": log, "flush_depths": flush_depths})
    finally:
        cg.close()

    # C3: 真线程并发压测（MdCGSecure.add + _index_sensitivity vs flush）
    r_race = os.path.join(tmp_root, "c_race")
    cg_r = MdCGSecure(r_race, principal=admin, master_key=master,
                      autoflush=5, async_flush=True)
    errors = []
    stop = threading.Event()
    written = []
    wlock = threading.Lock()
    prev_sw = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)
    try:
        def _writer(tid):
            try:
                for i in range(40):
                    nid = "race_%d_%03d" % (tid, i)
                    cg_r.add(
                        nid,
                        _CCG.format(name=nid, cond="全时窗", body="并发写入体 " + nid),
                        layer="knowledge", role="note", session="sess_c",
                        sensitivity="internal",
                    )
                    with wlock:
                        written.append(nid)
            except BaseException as exc:
                errors.append(("writer_%d" % tid, type(exc).__name__, str(exc)))

        def _flusher():
            try:
                while not stop.is_set():
                    cg_r.flush()
            except BaseException as exc:
                errors.append(("flusher", type(exc).__name__, str(exc)))

        tf = threading.Thread(target=_flusher, daemon=True)
        writers = [threading.Thread(target=_writer, args=(t,)) for t in range(3)]
        tf.start()
        for tw in writers:
            tw.start()
        for tw in writers:
            tw.join(timeout=30)
        stop.set()
        tf.join(timeout=10)
        cg_r.flush()
    finally:
        sys.setswitchinterval(prev_sw)
        cg_r.close()

    cg_reopen = MdCGSecure(r_race, principal=admin, master_key=master, async_flush=False)
    try:
        missing = [nid for nid in written if cg_reopen.get(nid) is None]
    finally:
        cg_reopen.close()
    ok(not errors and len(written) == 120 and not missing,
       "C3 并发 MdCGSecure.add（add + _index_sensitivity）与 flush() 碰撞零 RuntimeError 且零丢节点",
       {"errors": errors[:5], "written": len(written), "missing": missing[:5]})


def main():
    tmp_root = tempfile.mkdtemp(prefix="mdcg_pr3_guards_")
    try:
        test_group_a_hotcache_security(tmp_root)
        test_group_b_recall_budget_and_filters(tmp_root)
        test_group_c_dirty_lock_sites(tmp_root)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
        shutil.rmtree(_BOOT_TMP, ignore_errors=True)

    print()
    print("PR-3 守卫汇总：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：" + "；".join(_FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
