# -*- coding: utf-8 -*-
"""Exact prefix-filter + dynamic upper-bound B&B tests for md_cg.forgetting.redundancy.

Verifies:
  1. Randomized bit-for-bit parity against brute-force full-layer scan across 2,200+ nodes
     (near-duplicates >=0.85, semi-duplicates 0.60-0.85, novel texts, exact ties,
     exclude, empty/template payloads, layer isolation, all-layer layer=None).
  2. Discriminator guards proving:
     - Prefix-filter early termination and dynamic upper-bound pruning actually activate
       and reduce scanned posting lists / evaluated docs.
     - No truncation occurs on 2,200+ nodes under default operation (finds duplicates
       beyond MAX_COMPARE_CAP=1200).
     - Exact tie-breaking matches linear scan order even at the boundary remaining == best_ov
       and after in-place node updates.
     - Incremental O(delta) sync only reads modified/added nodes (0 disk reads on warm hit).
     - Strict invalidation on update, reinforce, deletion, layer move, rebuild_index,
       readcache.clear, cross-instance reload, DEK lock/unlock, and principal scope change.
     - Transient read failures (C-3) are never negatively cached.
     - Explicit limit / MDCG_MAX_COMPARE_CAP / MDCG_READ_CACHE=0 / stub / patched cg.get
       honor existing bounded linear fallback contracts.
"""
from __future__ import annotations

import builtins
import os
import random
import shutil
import tempfile
import unittest
from unittest import mock

from md_cg import forgetting, fsutil, readcache
from md_cg.mdcg import bigrams
from md_cg.mdcos import MdCGOS, MdCGSecure
from md_cg.security import Principal


def _brute_force_redundancy(cg, content, layer="contextual", exclude=None):
    """Independent exhaustive full-layer oracle (no cap, no cache index)."""
    new = bigrams(forgetting.payload(content))
    best = {"max": 0.0, "with": None, "jaccard": 0.0, "compared": 0}
    if not new:
        return best
    nodes = dict(((getattr(cg, "index", None) or {}).get("nodes") or {}))
    cands = [
        nid for nid in nodes
        if nid != exclude
        and (not layer or str((nodes[nid] or {}).get("layer") or "") == layer)
    ]
    n = 0
    for nid in cands:
        try:
            node = cg.get(nid, probe=False)
        except Exception:
            node = None
        if not node:
            continue
        body = bigrams(forgetting.payload(node.get("content") or ""))
        if not body:
            continue
        n += 1
        cov = len(new & body) / float(len(new))
        if cov > best["max"]:
            best = {
                "max": cov,
                "with": nid,
                "jaccard": len(new & body) / float(len(new | body) or 1),
                "compared": n,
            }
    best["compared"] = n
    best["candidate_total"] = len(cands)
    return best


def _ccg_doc(title, body):
    return (
        f"# 功能名：{title}\n"
        f"# 生效条件：测试场景\n"
        f"# 子功能：精确前缀过滤对拍\n"
        f"# 执行：直接运行\n"
        f"# 验证方式：test\n"
        f"# 不适用条件：无\n\n"
        f"{body}\n"
    )


class ForgettingPrefixExactTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="forget_prefix_exact_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.master_key = os.urandom(32).hex()
        clean = {k: v for k, v in os.environ.items() if not k.startswith("MDCG_")}
        clean.update({
            "MDCG_AUX_ROOT": self.tmpdir,
            "MDCG_ROOT": os.path.join(self.tmpdir, "default_root"),
            "MDCG_MASTER_KEY": self.master_key,
            "MDCG_READ_CACHE": "1",
            "MDCG_HOTCACHE": "0",
            "MDCG_ASYNC_FLUSH": "0",
            "MDCG_REVIEW_CHANNELS": "hive",
            "MDCG_REVIEWERS": "reflect",
        })
        self.env_patch = mock.patch.dict(os.environ, clean, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _make_os(self, name="store", **kwargs):
        root = os.path.join(self.tmpdir, name)
        cg = MdCGOS(root, autoflush=10000, **kwargs)
        self.addCleanup(cg.close)
        return cg

    def _make_secure(self, root, principal, master_key=None):
        cg = MdCGSecure(root, principal=principal,
                        master_key=master_key or self.master_key,
                        autoflush=10000)
        self.addCleanup(cg.close)
        return cg

    def test_randomized_bit_for_bit_parity_2200_nodes(self):
        """2,200-node randomized parity vs exhaustive full-layer oracle + no truncation."""
        rng = random.Random(20261122)
        cg = self._make_os("large_2200")

        # Shared pool of realistic domain phrases + rare unique phrases.
        common_chunks = [
            "缓存失效策略", "增量索引同步", "向量检索路径", "权限隔离边界",
            "事务回滚日志", "节点生命周期", "内存占用阈值", "查询延迟预算",
            "分布式锁竞争", "前缀过滤剪枝", "并发快照读取", "密钥轮换审计",
            "pipeline_stage", "bucket_scope", "write_generation", "path_guard",
        ]
        rare_vocab = [f"稀有词元{i:04d}特异片段" for i in range(600)]

        n_ctx = 2200
        bodies = {}
        for i in range(n_ctx):
            nid = f"ctx_{i:04d}"
            if i == 17:
                # Empty payload (template-only) edge case
                content = _ccg_doc("", "")
            elif i == 19:
                # Single-char payload edge case
                content = "甲"
            elif i in (50, 1300, 2199):
                # Plant distinct high-signal targets across early/mid/tail positions
                # (2199 is far past MAX_COMPARE_CAP=1200 to verify zero truncation!)
                content = _ccg_doc(
                    f"目标节点{i}",
                    f"专属锚定序列{i}号：蓝鲸脉冲星折射率校准参数 alpha_{i} beta_{i} gamma_{i}",
                )
            else:
                k_common = rng.randint(1, 3)
                k_rare = rng.randint(1, 3)
                parts = rng.sample(common_chunks, k_common) + rng.sample(rare_vocab, k_rare)
                content = _ccg_doc(f"条目{i}", "，".join(parts) + f"，编号{i}")
            bodies[nid] = content
            cg.add(nid, content, layer="contextual")

        # Plant 40 decoy nodes in knowledge layer with exact copies of tail targets
        # to verify strict layer isolation.
        for j in range(40):
            cg.add(
                f"kn_{j:03d}",
                _ccg_doc(f"异层目标{j}", "专属锚定序列2199号：蓝鲸脉冲星折射率校准参数 alpha_2199 beta_2199 gamma_2199"),
                layer="knowledge",
            )
        cg.flush()

        # Build diverse test queries: near-dups (>=0.85), semi-dups (0.60-0.85),
        # low-overlap, disjoint novel, empty/template, single-char, with/without exclude.
        queries = []
        # 1) Exact and near-duplicates at early, mid, and tail (>1200) positions
        for idx in (50, 1300, 2199):
            base = bodies[f"ctx_{idx:04d}"]
            queries.append((base, "contextual", None))
            queries.append((base + " 微调一字", "contextual", None))
            queries.append((base, "contextual", f"ctx_{idx:04d}"))
        # 2) Semi-duplicates (~0.60 - 0.85)
        for idx in rng.sample(range(100, 2100), 15):
            raw = forgetting.payload(bodies[f"ctx_{idx:04d}"])
            cut = max(4, int(len(raw) * 0.72))
            semi = raw[:cut] + "新增尾部变体内容XYZ"
            queries.append((semi, "contextual", None))
        # 3) Random near-dups from random positions
        for idx in rng.sample(range(20, 2190), 15):
            queries.append((bodies[f"ctx_{idx:04d}"], "contextual", None))
        # 4) Novel / low-overlap / completely disjoint texts
        for k in range(10):
            queries.append((
                f"全新未知主题{k}：量子纠缠超导谐振腔低温噪声谱分析_{k * 97}",
                "contextual",
                None,
            ))
        for k in range(5):
            queries.append((
                "；".join(rng.sample(common_chunks, 2)) + f" 新词{k * 131}",
                "contextual",
                None,
            ))
        # 5) Edge cases: template-only, single-char, all-layer (layer=None / ""), other layer
        queries.append((_ccg_doc("", ""), "contextual", None))
        queries.append(("甲", "contextual", None))
        queries.append((bodies["ctx_2199"], None, None))
        queries.append((bodies["ctx_2199"], "", "ctx_2199"))
        queries.append((bodies["ctx_2199"], "knowledge", None))

        for qi, (qtext, layer, excl) in enumerate(queries):
            got = forgetting.redundancy(cg, qtext, layer=layer, exclude=excl)
            want = _brute_force_redundancy(cg, qtext, layer=layer, exclude=excl)
            self.assertEqual(
                got, want,
                f"parity mismatch on query #{qi} (layer={layer!r}, exclude={excl!r}):\n"
                f"  got={got}\n  want={want}",
            )
            self.assertNotIn("truncated", got)

        # Discriminator: tail node #2199 (beyond MAX_COMPARE_CAP=1200) MUST be found
        tail_res = forgetting.redundancy(cg, bodies["ctx_2199"], layer="contextual")
        self.assertEqual(tail_res["with"], "ctx_2199")
        self.assertEqual(tail_res["max"], 1.0)
        self.assertEqual(tail_res["candidate_total"], n_ctx)
        self.assertEqual(tail_res["compared"], n_ctx)
        self.assertNotIn("truncated", tail_res)

    def test_prefix_filter_pruning_and_incremental_sync_discriminator(self):
        """Verify prefix-filter early stop, dynamic UB pruning, and O(delta) sync."""
        cg = self._make_os("prune_guard")
        common = "公共背景段落用于构造高频倒排链测试动态剪枝效果"
        for i in range(600):
            cg.add(f"bg_{i:04d}", f"{common} 分支差异编号{i:04d}尾标", layer="contextual")
        # Short doc sharing ONE rare bigram with query so dynamic UB `min(R, |B_d|) < best_ov` prunes it
        cg.add("short_doc", "稀罕", layer="contextual")
        target_body = (
            "稀罕独特核心命题：跨层缓存一致性与单调写代际证明细则，"
            "附加校验因子一二三四五六七八九十甲乙丙丁"
        )
        cg.add("target_late", target_body, layer="contextual")
        cg.flush()

        # First call builds index
        r1 = forgetting.redundancy(cg, target_body, layer="contextual")
        self.assertEqual(r1["with"], "target_late")
        self.assertEqual(r1["max"], 1.0)
        stats = cg._forgetting_bigram_index.last_stats
        self.assertTrue(stats["early_stopped"], f"expected prefix-filter early stop: {stats}")
        self.assertLess(
            stats["posting_lists_scanned"], stats["posting_lists_total"],
            f"prefix-filter should scan strictly fewer posting lists: {stats}",
        )
        self.assertLess(stats["docs_scored"], 50, f"expected heavy doc pruning: {stats}")

        # Construct a deterministic dynamic upper-bound pruning case:
        #   - "!0" has posting len 1 (only in ub_win) and sorts first (j=0),
        #     discovering ub_win and setting best_ov = |B(ub_win)| = k - 1 >> 1.
        #   - "!1" has posting len 1 (only in short_ub, |B(short_ub)| = 1) and
        #     sorts second (j=1, since "!0" < "!1" < "0专") while remaining == best_ov.
        #   - Dynamic upper bound U(short_ub) = min(remaining, 1) = 1 < best_ov
        #     MUST prune short_ub without computing a set intersection.
        cg.add("short_ub", "!1", layer="contextual")
        ub_target = "!0专属长正文校验动态上界剪枝一二三四五六七八九十甲乙丙丁"
        cg.add("ub_win", ub_target, layer="contextual")
        cg.flush()
        r_ub = forgetting.redundancy(cg, ub_target + "!1", layer="contextual")
        self.assertEqual(r_ub["with"], "ub_win")
        ub_stats = cg._forgetting_bigram_index.last_stats
        self.assertGreaterEqual(
            ub_stats["docs_pruned"], 1,
            f"expected dynamic upper-bound B&B to prune short doc: {ub_stats}",
        )

        # Warm hit MUST do 0 cg.get() reads; adding 1 node MUST do exactly 1 cg.get() read
        # (Patch a real descriptor function on the class so `self` binds properly and
        # instance __dict__ stays clean so the bigram cache remains eligible.)
        orig_cls_get = type(cg).get
        get_calls = {"n": 0}

        def _spy_cls_get(self_cg, *args, **kwargs):
            if self_cg is cg:
                get_calls["n"] += 1
            return orig_cls_get(self_cg, *args, **kwargs)

        with mock.patch.object(type(cg), "get", _spy_cls_get):
            r_warm = forgetting.redundancy(cg, target_body, layer="contextual")
            self.assertEqual(r_warm["with"], "target_late")
            self.assertEqual(r_warm["max"], 1.0)
            self.assertEqual(r_warm["compared"], 604)
            self.assertEqual(get_calls["n"], 0, "warm hit must not re-read disk")

            cg.add("inc_new_1", "增量新增节点独立正文九九八十一", layer="contextual")
            cg.flush()
            get_calls["n"] = 0  # count only reads made inside redundancy() itself
            r_inc = forgetting.redundancy(cg, "增量新增节点独立正文九九八十一", layer="contextual")
            self.assertEqual(r_inc["with"], "inc_new_1")
            self.assertEqual(r_inc["max"], 1.0)
            self.assertEqual(
                get_calls["n"], 1,
                f"incremental sync after 1 add should read exactly 1 node, got {get_calls['n']}",
            )

    def test_exact_tie_breaking_boundary_and_inplace_update(self):
        """Strict index-order tie-breaking, including remaining==best_ov boundary & updates."""
        cg = self._make_os("tie_guard")

        # Query bigrams: Q = {"aa", "ab", "bc", "cd", "de"} (from "aabcde", 5 bigrams)
        # Wait: let's construct clean non-overlapping 2-char chunks via distinct chars!
        # Let query = "甲乙丙丁戊己庚" -> bigrams = {"甲乙","乙丙","丙丁","丁戊","戊己","己庚"} (6 bigrams).
        # Make "甲乙" VERY rare (only in t_late), while "丙丁","丁戊","戊己","己庚" are common!
        # Add 30 fillers containing "丙丁","丁戊","戊己","己庚" (so those 4 have posting len >= 31).
        # Put t_early BEFORE t_late, with:
        #   t_early = "丙丁戊己庚" -> matches {"丙丁","丁戊","戊己","己庚"} (ov = 4, only in common lists!)
        #   t_late  = "甲乙丙丁戊" -> matches {"甲乙","乙丙","丙丁","丁戊"} (ov = 4, in RARE list "甲乙"!)
        # When scanning sorted posting lists:
        #   j=0 ("甲乙", len=1): discovers t_late -> best_ov = 4!
        #   j=1 ("乙丙", len=1): t_late already seen.
        #   j=2 ("丙丁", len=32): remaining = 6 - 2 = 4 == best_ov!
        #   If stopping condition erroneously used `remaining <= best_ov`, t_early would be MISSED!
        cg.add("t_early", "丙丁戊己庚", layer="contextual")
        for i in range(30):
            # Each filler shares only 1 common bigram (no tie with 4)
            cg.add(f"f_a_{i}", f"丙丁{i:02d}", layer="contextual")
            cg.add(f"f_b_{i}", f"丁戊{i:02d}", layer="contextual")
            cg.add(f"f_c_{i}", f"戊己{i:02d}", layer="contextual")
            cg.add(f"f_d_{i}", f"己庚{i:02d}", layer="contextual")
        cg.add("t_late", "甲乙丙丁戊", layer="contextual")
        cg.flush()

        q = "甲乙丙丁戊己庚"
        got = forgetting.redundancy(cg, q, layer="contextual")
        want = _brute_force_redundancy(cg, q, layer="contextual")
        self.assertEqual(got, want)
        self.assertEqual(got["with"], "t_early", "must break exact tie at remaining==best_ov in index order")

        # Exclude t_early -> must fall back to t_late
        got_ex = forgetting.redundancy(cg, q, layer="contextual", exclude="t_early")
        want_ex = _brute_force_redundancy(cg, q, layer="contextual", exclude="t_early")
        self.assertEqual(got_ex, want_ex)
        self.assertEqual(got_ex["with"], "t_late")

        # In-place update of t_early with brand-new text that ties t_late on a new bigram:
        # Even though t_early's posting is re-inserted after t_late, t_early retains pos=0
        # in cg.index["nodes"] and MUST still win the tie!
        cg.add("t_late", "子丑寅卯辰巳午未申", layer="contextual")
        cg.flush()
        forgetting.redundancy(cg, "子丑寅卯辰", layer="contextual")  # warm index
        cg.add("t_early", "子丑寅卯辰", layer="contextual")
        cg.flush()
        got_upd = forgetting.redundancy(cg, "子丑寅卯辰", layer="contextual")
        want_upd = _brute_force_redundancy(cg, "子丑寅卯辰", layer="contextual")
        self.assertEqual(got_upd, want_upd)
        self.assertEqual(got_upd["with"], "t_early")

    def test_invalidation_update_reinforce_delete_move_rebuild_reload(self):
        """Index must NEVER serve stale bigrams after any mutation path."""
        cg = self._make_os("inval_guard")
        # Completely disjoint character sets so stale postings are immediately detectable
        old_text = "星云引擎配置号一零二三四五"
        new_text = "海豚声纳频谱滤波算法九八七六"
        cg.add("m1", old_text, layer="contextual")
        cg.add("m2", "秋风落叶山谷溪水", layer="contextual")
        cg.flush()

        # Warm
        self.assertEqual(forgetting.redundancy(cg, old_text, layer="contextual")["with"], "m1")

        # 1) In-place update
        cg.add("m1", new_text, layer="contextual")
        cg.flush()
        r_old = forgetting.redundancy(cg, old_text, layer="contextual")
        r_new = forgetting.redundancy(cg, new_text, layer="contextual")
        self.assertEqual(r_old, _brute_force_redundancy(cg, old_text, layer="contextual"))
        self.assertIsNone(r_old["with"])
        self.assertEqual(r_old["max"], 0.0)
        self.assertEqual(r_new["with"], "m1")
        self.assertEqual(r_new["max"], 1.0)

        # 2) forgetting.reinforce() appends aggregate line -> must invalidate path_gen
        extra_line = "聚合追加的独有事实：北极光磁暴观测索引七七七"
        forgetting.reinforce(cg, "m1", content=extra_line)
        r_reinf = forgetting.redundancy(cg, extra_line, layer="contextual")
        self.assertEqual(r_reinf, _brute_force_redundancy(cg, extra_line, layer="contextual"))
        self.assertEqual(r_reinf["with"], "m1")
        self.assertGreaterEqual(r_reinf["max"], 0.9)

        # 3) Layer move: contextual -> knowledge
        forgetting.redundancy(cg, new_text, layer="knowledge")  # warm knowledge layer too
        cg._move_layer("m1", "knowledge", reason="test move")
        r_ctx_after = forgetting.redundancy(cg, new_text, layer="contextual")
        r_kn_after = forgetting.redundancy(cg, new_text, layer="knowledge")
        self.assertEqual(r_ctx_after, _brute_force_redundancy(cg, new_text, layer="contextual"))
        self.assertEqual(r_kn_after, _brute_force_redundancy(cg, new_text, layer="knowledge"))
        self.assertNotEqual(r_ctx_after["with"], "m1")
        self.assertEqual(r_ctx_after["candidate_total"], 1)
        self.assertEqual(r_kn_after["with"], "m1")
        self.assertEqual(r_kn_after["candidate_total"], 1)

        # 4) Deletion (cg.forget)
        cg.forget("m1", reason="test delete")
        r_del = forgetting.redundancy(cg, new_text, layer="knowledge")
        self.assertEqual(r_del, _brute_force_redundancy(cg, new_text, layer="knowledge"))
        self.assertIsNone(r_del["with"])
        self.assertEqual(r_del["candidate_total"], 0)
        self.assertEqual(r_del["compared"], 0)

        # 5) External direct file edit + rebuild_index() / readcache.clear()
        cg.add("m3", "磁盘原始正文：青铜器铭文拓片研究", layer="contextual")
        cg.flush()
        self.assertEqual(
            forgetting.redundancy(cg, "磁盘原始正文：青铜器铭文拓片研究", layer="contextual")["with"],
            "m3",
        )
        m3_path = os.path.join(cg.root, cg.index["nodes"]["m3"]["path"])
        raw_file = open(m3_path, encoding="utf-8").read()
        with open(m3_path, "w", encoding="utf-8") as f:
            f.write(raw_file.replace("青铜器铭文拓片研究", "宋代瓷器釉色考据"))
        cg.rebuild_index()
        self.assertEqual(
            forgetting.redundancy(cg, "宋代瓷器釉色考据", layer="contextual")["with"],
            "m3",
        )
        self.assertNotEqual(
            forgetting.redundancy(cg, "青铜器铭文拓片研究", layer="contextual")["with"],
            "m3",
        )

        # Direct file edit + explicit readcache.clear(cg)
        raw_file2 = open(m3_path, encoding="utf-8").read()
        with open(m3_path, "w", encoding="utf-8") as f:
            f.write(raw_file2.replace("宋代瓷器釉色考据", "明清木雕纹样图谱"))
        readcache.clear(cg)
        self.assertEqual(
            forgetting.redundancy(cg, "明清木雕纹样图谱", layer="contextual")["with"],
            "m3",
        )

        # 6) Cross-instance write -> _maybe_reload_index invalidates stale cache
        cg2 = MdCGOS(cg.root, autoflush=1)
        self.addCleanup(cg2.close)
        peer_text = "跨进程写入独占正文：天文学红移光谱测定实验"
        cg2.add("m_peer", peer_text, layer="contextual")
        cg2.flush()
        r_peer = forgetting.redundancy(cg, peer_text, layer="contextual")
        self.assertEqual(r_peer, _brute_force_redundancy(cg, peer_text, layer="contextual"))
        self.assertEqual(r_peer["with"], "m_peer")
        self.assertEqual(r_peer["max"], 1.0)

    def test_encrypted_access_scope_and_dek_invalidation(self):
        """Encrypted/inaccessible nodes must never leak across lock, unlock, or scope changes."""
        root = os.path.join(self.tmpdir, "secure_store")
        p_s1 = Principal(
            tenant="t1", actor="alice", session="sess_1",
            clearance="secret", role="worker", can_write=True, can_admin=False,
        )
        p_s2 = Principal(
            tenant="t1", actor="alice", session="sess_2",
            clearance="secret", role="worker", can_write=True, can_admin=False,
        )
        p_bob = Principal(
            tenant="t1", actor="bob", session="sess_1",
            clearance="secret", role="worker", can_write=True, can_admin=False,
        )

        cg_s1 = self._make_secure(root, p_s1)
        cg_s2 = self._make_secure(root, p_s2)
        cg_bob = self._make_secure(root, p_bob)

        pub_txt = "公开共享正文：标准气象站风速观测规范"
        priv_s1_txt = "会话一加密私密正文：个人密钥备份助记词测试样本"
        priv_s2_txt = "会话二加密私密正文：另一会话独立机密备忘录样本"
        bob_priv_txt = "鲍勃独立加密正文：他人加密信封绝对不可见内容"

        cg_s1.add("n_pub", pub_txt, layer="contextual", sensitivity="public")
        cg_s1.add("n_priv_s1", priv_s1_txt, layer="contextual", sensitivity="private")
        cg_s1.flush()

        cg_s2.add("n_priv_s2", priv_s2_txt, layer="contextual", sensitivity="private")
        cg_s2.flush()

        cg_bob.add("n_bob_priv", bob_priv_txt, layer="contextual", sensitivity="private")
        cg_bob.flush()

        # Alice in sess_1: sees n_pub and n_priv_s1; MUST NOT see n_priv_s2 or n_bob_priv
        r_pub = forgetting.redundancy(cg_s1, pub_txt, layer="contextual")
        r_s1 = forgetting.redundancy(cg_s1, priv_s1_txt, layer="contextual")
        r_s2 = forgetting.redundancy(cg_s1, priv_s2_txt, layer="contextual")
        r_bob = forgetting.redundancy(cg_s1, bob_priv_txt, layer="contextual")

        self.assertEqual(r_pub, _brute_force_redundancy(cg_s1, pub_txt, layer="contextual"))
        self.assertEqual(r_s1, _brute_force_redundancy(cg_s1, priv_s1_txt, layer="contextual"))
        self.assertEqual(r_s2, _brute_force_redundancy(cg_s1, priv_s2_txt, layer="contextual"))
        self.assertEqual(r_bob, _brute_force_redundancy(cg_s1, bob_priv_txt, layer="contextual"))

        self.assertEqual(r_s1["with"], "n_priv_s1")
        self.assertEqual(r_s1["compared"], 2)          # only n_pub + n_priv_s1 readable
        self.assertEqual(r_s1["candidate_total"], 4)   # all 4 contextual nodes exist in index
        self.assertNotEqual(r_s2["with"], "n_priv_s2")
        self.assertNotEqual(r_bob["with"], "n_bob_priv")

        # Lock DEK: decrypted bigrams MUST be purged immediately and private node invisible
        cg_s1.lock()
        self.assertEqual(
            cg_s1._forgetting_bigram_index.layers, {},
            "lock() must purge cached decrypted bigrams from RAM immediately",
        )
        r_locked = forgetting.redundancy(cg_s1, priv_s1_txt, layer="contextual")
        self.assertEqual(r_locked, _brute_force_redundancy(cg_s1, priv_s1_txt, layer="contextual"))
        self.assertNotEqual(r_locked["with"], "n_priv_s1")
        self.assertEqual(r_locked["compared"], 1)  # only n_pub readable while locked

        # Unlock DEK: private node immediately visible again
        cg_s1.unlock(self.master_key)
        r_unlocked = forgetting.redundancy(cg_s1, priv_s1_txt, layer="contextual")
        self.assertEqual(r_unlocked, _brute_force_redundancy(cg_s1, priv_s1_txt, layer="contextual"))
        self.assertEqual(r_unlocked["with"], "n_priv_s1")
        self.assertEqual(r_unlocked["compared"], 2)

        # Principal scope change on the same engine (sess_1 -> sess_2):
        # Must invalidate immediately so sess_1 private node disappears and sess_2 appears
        cg_s1.principal = p_s2
        r_sw_s1 = forgetting.redundancy(cg_s1, priv_s1_txt, layer="contextual")
        r_sw_s2 = forgetting.redundancy(cg_s1, priv_s2_txt, layer="contextual")
        self.assertEqual(r_sw_s1, _brute_force_redundancy(cg_s1, priv_s1_txt, layer="contextual"))
        self.assertEqual(r_sw_s2, _brute_force_redundancy(cg_s1, priv_s2_txt, layer="contextual"))
        self.assertNotEqual(r_sw_s1["with"], "n_priv_s1")
        self.assertEqual(r_sw_s2["with"], "n_priv_s2")

        # Lowering clearance on same principal object in place -> must invalidate
        cg_s1.principal = Principal(
            tenant="t1", actor="alice", session="sess_2",
            clearance="internal", role="worker", can_write=True, can_admin=False,
        )
        r_low = forgetting.redundancy(cg_s1, priv_s2_txt, layer="contextual")
        self.assertEqual(r_low, _brute_force_redundancy(cg_s1, priv_s2_txt, layer="contextual"))
        self.assertNotEqual(r_low["with"], "n_priv_s2")
        self.assertEqual(r_low["compared"], 1)

    def test_transient_read_failure_is_not_negatively_cached(self):
        """C-3: transient OSError during index build must be retried on next query."""
        cg = self._make_os("transient_guard")
        target = "瞬时故障恢复校验正文：深海热液喷口矿床成因研究"
        cg.add("ok_node", "常驻可读节点：高原湖泊水文观测", layer="contextual")
        cg.add("flaky_node", target, layer="contextual")
        cg.flush()

        flaky_path = os.path.normcase(os.path.abspath(
            os.path.join(cg.root, cg.index["nodes"]["flaky_node"]["path"])
        ))
        real_open = builtins.open
        fail_once = {"active": True}

        def flaky_open(file, *args, **kwargs):
            try:
                norm = os.path.normcase(os.path.abspath(os.fspath(file)))
            except TypeError:
                norm = ""
            if fail_once["active"] and norm == flaky_path:
                raise PermissionError(13, "simulated sharing violation", file)
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=flaky_open):
            r_fail = forgetting.redundancy(cg, target, layer="contextual")
        self.assertNotEqual(r_fail["with"], "flaky_node")
        self.assertEqual(r_fail["compared"], 1)
        self.assertEqual(r_fail["candidate_total"], 2)

        # Transient failure clears (NO write_gen bump!) -> next query MUST retry and hit
        fail_once["active"] = False
        r_ok = forgetting.redundancy(cg, target, layer="contextual")
        self.assertEqual(r_ok["with"], "flaky_node")
        self.assertEqual(r_ok["max"], 1.0)
        self.assertEqual(r_ok["compared"], 2)

    def test_fallback_contracts_limit_cap_optout_and_stubs(self):
        """Verify explicit limit, MDCG_MAX_COMPARE_CAP, MDCG_READ_CACHE=0, stubs & patched get."""
        cg = self._make_os("fallback_guard")
        for i in range(300):
            cg.add(f"n_{i:04d}", f"节点内容样本编号{i:04d}用于回落测试", layer="contextual")
        cg.flush()

        # 1) Explicit limit -> linear bounded path with truncated=True
        r_lim = forgetting.redundancy(cg, "节点内容样本编号0299用于回落测试", layer="contextual", limit=10)
        self.assertEqual(r_lim["compared"], 10)
        self.assertTrue(r_lim.get("truncated"))
        self.assertEqual(r_lim["candidate_total"], 300)
        self.assertNotEqual(r_lim["with"], "n_0299")

        # 2) Explicit limit=0 -> legacy semantics (1 comparison, truncated=True)
        r_lim0 = forgetting.redundancy(cg, "节点内容样本编号0299用于回落测试", layer="contextual", limit=0)
        self.assertEqual(r_lim0["compared"], 1)
        self.assertTrue(r_lim0.get("truncated"))

        # 3) Explicit MDCG_MAX_COMPARE_CAP=240 -> honors #358/#929 rollback truncation contract
        with mock.patch.dict(os.environ, {"MDCG_MAX_COMPARE_CAP": "240"}):
            r_cap = forgetting.redundancy(cg, "节点内容样本编号0299用于回落测试", layer="contextual")
        self.assertEqual(r_cap["compared"], 240)
        self.assertTrue(r_cap.get("truncated"))
        self.assertEqual(r_cap["candidate_total"], 300)

        # 4) MDCG_READ_CACHE=0 -> disables bigram cache cleanly
        with mock.patch.dict(os.environ, {"MDCG_READ_CACHE": "0"}):
            cg_nocache = self._make_os("nocache_store")
            cg_nocache.add("x1", "无缓存路径校验正文测试", layer="contextual")
            cg_nocache.flush()
            self.assertFalse(forgetting._can_use_bigram_index(cg_nocache))
            r_nc = forgetting.redundancy(cg_nocache, "无缓存路径校验正文测试", layer="contextual")
            self.assertEqual(r_nc["with"], "x1")
            self.assertFalse(hasattr(cg_nocache, "_forgetting_bigram_index"))

        # 5) Stub object without _dirty / _read_cache -> linear fallback
        class _Stub:
            def __init__(self):
                self.index = {"nodes": {"s1": {"layer": "contextual"}}}

            def get(self, nid):
                return {"id": nid, "content": "测试桩正文内容", "frontmatter": {}}

        stub = _Stub()
        self.assertFalse(forgetting._can_use_bigram_index(stub))
        r_stub = forgetting.redundancy(stub, "测试桩正文内容", layer="contextual")
        self.assertEqual(r_stub["with"], "s1")
        self.assertEqual(r_stub["max"], 1.0)

        # 6) Instance-level monkey-patched cg.get -> linear fallback (never bypassed)
        sentinel_calls = {"n": 0}
        orig_get = cg.get

        def patched_get(nid, probe=True):
            sentinel_calls["n"] += 1
            return orig_get(nid, probe=probe)

        cg.get = patched_get
        try:
            self.assertFalse(forgetting._can_use_bigram_index(cg))
            r_p = forgetting.redundancy(cg, "节点内容样本编号0000用于回落测试", layer="contextual")
            self.assertGreater(sentinel_calls["n"], 0)
            self.assertEqual(r_p["with"], "n_0000")
        finally:
            del cg.get


if __name__ == "__main__":
    unittest.main()
