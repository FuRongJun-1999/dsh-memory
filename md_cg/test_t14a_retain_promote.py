# -*- coding: utf-8 -*-
r"""t14a 守卫 · 保留规则第二块（md_cg/retain.py 的 promote —— 重要性提升）。

钉住七组断言，缺一条这个写面就不可信：

    G1 预演零写盘：promote(apply=False) ⇒ 全库文件列表 + mtime 逐位未动、
       written=0、A 的 sample after=0.35、blocked_by 含 '未放行'
    G2 窗口闸：promote(apply=True, writable=False) ⇒ 仍零写盘、blocked_by 含 '窗口'
    G3 档位闸：e_gate 判非 allow 时 promote(apply=True, writable=True) ⇒
       零写盘、blocked_by 含 '档位闸'
    G4 真写盘：三闸全过 ⇒ A 的 importance==0.35、B unchanged（0.50>0.35 不动）、
       C 不在候选（retained=False）、_maintain.jsonl 新增 action=='retain_promote'
       且 id==A、索引条目 importance==0.35
    G5 幂等：再 promote(apply=True) 一次 ⇒ A unchanged 不重复写
    G6 真落盘：重启一个新 MdCG(root=tmp) 读盘 ⇒ A 的 importance 仍 0.35
    G7 退出码 0（全绿）

## 三闸为何必须**分别**取证
`apply`（意图）/ `writable`（环境窗口）/ `e_gate()`（放权裁决）是三条**独立**的
拦截面。若只测「apply=False 不写」的话，一个把 `allow_apply` 写成 `bool(apply)`
的实现能全过——它就悄悄绕过了窗口与档位两闸。G2 与 G3 各自**只**松开一闸、
卡住另一闸，才排得掉「拿 apply 当唯一闸」的蒙混。

## 档位闸为何推荐 mock 而非改 env
改全局 `MDCG_AUTONOMY` 会**污染并发运行的其它守卫**（env 是进程级），且本仓
`.py` 里带引号的档位 env 名只许出现在 `autonomy_modes.AUTONOMY_ENV_KEYS`
（守卫 test_autonomy_modes.py 把这条钉死）——本文件因此**一个字面量都不写**，
mock 的是 `md_cg.autonomy_modes.e_gate` 的**返回值**。G4 同样用 mock 让
e_gate 返回 allow，使「真写盘」不依赖运行时的实际档位（换台机器跑也同结果）。

## 零写盘为何要比 mtime
只比内容哈希抓不到「原地重写同样内容」的写——那仍是一次写盘，且会把 mtime
推新。故 G1–G3 一律比**文件列表 + st_mtime_ns**。

## 候选 C 为何必须在场
C（access_count=0、importance 低）是 retained=False 的对照。若候选面退化成
「全库都算候选」，G4 的 C 断言会红——它同时钉住了「候选面真的走了 retain 判据」。

沙箱注记：本套不起子进程，与 CreatePipe 禁令无涉；临时目录建在系统临时区、
用后 rmtree 回收，不读不写任何真实数据根。

运行：python D:\wook\lingshu-src\md_cg\test_t14a_retain_promote.py
退出码：0 全绿 ／ 1 有失败项
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import autonomy_modes as _am       # noqa: E402
from md_cg import retain as _retain           # noqa: E402
from md_cg import sink as _sink               # noqa: E402
from md_cg import weights as _weights         # noqa: E402
from md_cg.fsutil import read_jsonl           # noqa: E402
from md_cg.mdcg import MdCG                   # noqa: E402

#: 环境变量名从 sink 取（不在本文件里写第二遍字面量——两处写必然漂移）。
LIFECYCLE_ENV = _sink.SINK_ENV
#: 档位 env 名从 autonomy_modes 取（同上：唯一字面量落点在 AUTONOMY_ENV_KEYS）。
AUTONOMY_ENV = _am.AUTONOMY_ENV_KEYS["mode"]

#: 夹具的三条阈值取值——写成具名常量，让「A 该抬、B 不该动」的算术一眼可读。
FLOOR = _retain.RETAIN_FLOOR_IMPORTANCE      # 0.35
A_BEFORE = 0.20                              # < floor ⇒ 该被抬到 0.35
B_BEFORE = 0.50                              # > floor ⇒ unchanged 不动


# 生效条件：恒返回一个新造的临时目录绝对路径（调用方负责 rmtree）；前缀便于
# 排查时一眼看出是 t14a-promote 的残留。
def _mk_tmp(prefix="t14a_retain_promote_"):
    return tempfile.mkdtemp(prefix=prefix)


# 生效条件：传入已建的 cg、节点 id、正文与 fm 覆盖键时，先 cg.add 建节点，再把
# 覆盖键逐个写进该节点 frontmatter 并经 cg._write_node 落盘，最后 rebuild_index
# 使内存索引与盘面一致；返回该节点 id。走引擎唯一正路（不自己拼文件、不手改 _index.json）。
def _make_node(cg, nid, content, access_count=None, importance=None,
               protected=None, layer="knowledge"):
    """造一个带指定 frontmatter 的**真实落盘**节点（临时库内）。"""
    cg.add(nid, content, layer=layer)
    node = cg.get(nid)
    fm = node["frontmatter"]
    if access_count is not None:
        fm["access_count"] = access_count
    if importance is not None:
        fm["importance"] = importance
    if protected is not None:
        fm["protected"] = protected
    path = os.path.join(cg.root, (cg.index.get("nodes") or {}).get(nid, {})
                        .get("path") or "%s.md" % nid)
    cg._write_node(nid, path, fm, node.get("content") or "")
    cg.rebuild_index()
    return nid


# 生效条件：os.walk 遍历 root 下**所有**文件，返回 {相对路径（/ 分隔）: mtime_ns}；
# mtime 用 st_mtime_ns 取整型纳秒，避免浮点比较的精度噪声把「没变」误判成「变了」。
def _tree_mtimes(root):
    """影子根盘面指纹：全库文件列表 + 每个文件的 mtime（纳秒）。"""
    out = {}
    if not os.path.isdir(root):
        return out
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root).replace("\\", "/")
            try:
                out[rel] = os.stat(fp).st_mtime_ns
            except OSError as exc:                       # 读不到也如实记，不静默跳过
                out[rel] = "stat_error:%s" % type(exc).__name__
    return out


# 生效条件：恒返回 (新增键, 消失键, mtime 变化 dict)——断言失败时打印可读证据，
# 直接看出「哪个文件出现了/消失了/时间变了」。
def _tree_diff(before, after):
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = {k: (before[k], after[k]) for k in set(before) & set(after)
               if before[k] != after[k]}
    return added, removed, changed


# 生效条件：dec 为 None 时返回「恒 ALLOW」的假 e_gate（G4 用）；否则返回**恒返回
# 该 dec** 的假 e_gate（G3 用——decision 传非 allow 值即可考到档位闸）。
def _fake_gate(dec=None):
    """假 e_gate：不在运行时读 env，故不与并发守卫抢全局状态。"""
    payload = dec if dec is not None else {
        "action": _am.E_WEIGHT, "action_name": _am.ACTION_NAMES[_am.E_WEIGHT],
        "mode": _am.MODE_FULL, "decision": _am.ALLOW, "hint": ""}

    def _gate(plan=None, environ=None):
        return dict(payload)

    return _gate


class RetainPromoteTest(unittest.TestCase):
    """七组断言共享同一套夹具建法，但**每组各自建库**（互不污染）。"""

    def setUp(self):
        self.tmp = _mk_tmp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "lib")
        self.cg = MdCG(root=self.root)
        # A：access_count=5 ≥ keep=3 ⇒ retained；importance 0.20 < floor ⇒ 该抬到 0.35
        self.a = _make_node(self.cg, "A", "高频使用但重要性偏低", access_count=5,
                            importance=A_BEFORE)
        # B：同样 retained，但 importance 0.50 > floor ⇒ unchanged，不许被压低
        self.b = _make_node(self.cg, "B", "高频且重要性已够", access_count=5,
                            importance=B_BEFORE)
        # C：无引用、importance 低 ⇒ retained=False，根本不该进候选
        self.c = _make_node(self.cg, "C", "没人用过的节点", access_count=0,
                            importance=0.10)

    # ---------- 只读/拦截面取证工具 ----------

    # 生效条件：恒返回 (before 指纹, after 指纹, 差异三元组)——调用 fn() 前后各取一次
    # 全库指纹；断言由调用方做（本助手只负责取证）。
    def _around(self, fn):
        before = _tree_mtimes(self.root)
        result = fn()
        after = _tree_mtimes(self.root)
        return before, after, _tree_diff(before, after), result

    # 生效条件：断言「全库逐位未动」（无新增、无消失、无 mtime 变化），失败时
    # 打印差异三元组作为证据；恒不抛异常（断言失败由 unittest 计错误）。
    def _assert_frozen(self, diff, tag=""):
        added, removed, changed = diff
        self.assertEqual(added, [], "%s 不得新建文件：%r" % (tag, added))
        self.assertEqual(removed, [], "%s 不得删除文件：%r" % (tag, removed))
        self.assertEqual(changed, {},
                         "%s 不得改动任何文件（含 mtime）：%r" % (tag, changed))

    # 生效条件：返回磁盘上 action=='retain_promote' 的记账行列表；账本不存在返回 []。
    def _promote_records(self):
        path = os.path.join(self.root, _weights.MAINTAIN_LOG)
        if not os.path.exists(path):
            return []
        return [r for r in read_jsonl(path)
                if r.get("action") == _retain.ACTION_PROMOTE]

    # 生效条件：返回 sample 列表里 id==nid 的那条；找不到返回 {}。
    def _sample(self, out, nid):
        for s in out.get("samples") or []:
            if s.get("id") == nid:
                return s
        return {}

    # ---------- ① 预演零写盘 ----------

    # G1：promote(apply=False) 只预演——全库逐位未动、written=0、A 的 sample
    # after=0.35、blocked_by 含 '未放行'。
    def test_g1_dry_run_writes_nothing(self):
        before, after, diff, out = self._around(
            lambda: _retain.promote(self.cg, apply=False))
        self._assert_frozen(diff, "G1 预演")

        self.assertTrue(out["ok"], "返回体须 ok：%r" % (out,))
        self.assertIs(out["dry_run"], True, "未放行时 dry_run 应为真：%r" % (out,))
        self.assertEqual(out["written"], 0, "零写盘时 written 必须为 0：%r" % (out,))
        self.assertIn("未放行", out["blocked_by"],
                      "apply=False 的拦截理由须含 '未放行'：%r" % (out.get("blocked_by"),))

        sample_a = self._sample(out, self.a)
        self.assertTrue(sample_a, "样本里须有 A 的真读数：%r" % (out.get("samples"),))
        self.assertAlmostEqual(sample_a["after"], FLOOR, places=6,
                               msg="A 的 after 应是地板上读数 %.4g：%r" % (FLOOR, sample_a))
        self.assertAlmostEqual(sample_a["before"], A_BEFORE, places=6,
                               msg="A 的 before 应是实测值：%r" % (sample_a,))
        self.assertIn("未放行", sample_a.get("blocked_by", ""),
                      "每条样本也要如实记被哪一闸拦：%r" % (sample_a,))

        # B 已在 floor 之上：样本读数必须 after==before（unchanged 口径），
        # 且 after **绝不低于** before —— 一个「提升」动作报出 after<before 就是
        # 把升级写成了降级。（这条同时钉住 ⑥：若实现把 after 恒写成 floor，
        # B 的样本会变成 0.35<0.50，本断言即红。）
        sample_b = self._sample(out, self.b)
        self.assertTrue(sample_b, "样本里须有 B 的读数：%r" % (out.get("samples"),))
        self.assertAlmostEqual(sample_b["after"], B_BEFORE, places=6,
                               msg="B 已高于地板，after 应保持原值：%r" % (sample_b,))
        for s in out.get("samples") or []:
            self.assertGreaterEqual(
                float(s["after"]) + 1e-9, float(s["before"]),
                "提升动作不得报出 after<before（那是降级）：%r" % (s,))

        # 盘面真值：A 的 importance 仍是 0.20（预演不改内存，也不改盘面）。
        self.assertAlmostEqual(
            float(self.cg.get(self.a)["frontmatter"]["importance"]), A_BEFORE,
            places=6, msg="预演不得改内存中的 importance")
        # 账本一行都不许出（连记账都不算「预演」）。
        self.assertEqual(self._promote_records(), [],
                         "预演不得写 _maintain.jsonl：%r" % (self._promote_records(),))

    # ---------- ② 写窗口闸 ----------

    # G2：promote(apply=True, writable=False) —— 只差窗口这一闸，仍须零写盘，
    # 且 blocked_by 含 '窗口'（证明拦下它的确实是窗口闸、不是其它两条）。
    def test_g2_window_gate_blocks_write(self):
        before, after, diff, out = self._around(
            lambda: _retain.promote(self.cg, apply=True, writable=False))
        self._assert_frozen(diff, "G2 窗口闸")

        self.assertEqual(out["written"], 0, "窗口未开时不得写盘：%r" % (out,))
        self.assertIn("窗口", out["blocked_by"],
                      "拦截理由须含 '窗口'：%r" % (out.get("blocked_by"),))
        self.assertNotIn("未放行", out["blocked_by"],
                         "apply=True 时不该报「未放行」——本轮意图是放行的：%r"
                         % (out.get("blocked_by"),))
        self.assertEqual(self._promote_records(), [], "窗口未开不得写账本")
        self.assertAlmostEqual(
            float(self.cg.get(self.a)["frontmatter"]["importance"]), A_BEFORE,
            places=6, msg="窗口未开时 A 的 importance 不得变")

    # ---------- ③ 自治档位闸 ----------

    # G3：apply=True 且 writable=True，但 e_gate 判非 ALLOW ⇒ 零写盘、
    # blocked_by 含 '档位闸'。mock 的是返回值，不动全局 env。
    def test_g3_autonomy_gate_blocks_write(self):
        denial = {"action": _am.E_WEIGHT,
                  "action_name": _am.ACTION_NAMES[_am.E_WEIGHT],
                  "mode": "plan", "decision": _am.FORBID, "hint": "计划模式无计划"}
        with mock.patch.object(_am, "e_gate", _fake_gate(denial)):
            before, after, diff, out = self._around(
                lambda: _retain.promote(self.cg, apply=True, writable=True))
        self._assert_frozen(diff, "G3 档位闸")

        self.assertEqual(out["written"], 0, "档位未放行时不得写盘：%r" % (out,))
        self.assertIn("档位闸", out["blocked_by"],
                      "拦截理由须含 '档位闸'：%r" % (out.get("blocked_by"),))
        self.assertIn(_am.FORBID, out["blocked_by"],
                      "须如实带上判决策略值：%r" % (out.get("blocked_by"),))
        self.assertEqual(self._promote_records(), [], "档位未放行不得写账本")
        self.assertAlmostEqual(
            float(self.cg.get(self.a)["frontmatter"]["importance"]), A_BEFORE,
            places=6, msg="档位未放行时 A 的 importance 不得变")

        # 反例方向：同一个 mock 换成 ALLOW 后必须真写盘——否则「档位闸拦下」
        # 与「这个实现压根不会写」在结果上同形，本断言就判不了闸。
        with mock.patch.object(_am, "e_gate", _fake_gate()):
            ok = _retain.promote(self.cg, apply=True, writable=True)
        self.assertGreater(ok["written"], 0,
                           "同一实现换成 ALLOW 后必须真写盘：%r" % (ok,))

    # ---------- ④ 三闸全过：真写盘 ----------

    # G4：A 抬到 0.35、B unchanged（0.50>0.35 不动）、C 不在候选、账本新增一条
    # action=='retain_promote' 且 id==A、索引条目 importance==0.35。
    def test_g4_all_gates_open_writes_once(self):
        with mock.patch.object(_am, "e_gate", _fake_gate()):
            out = _retain.promote(self.cg, apply=True, writable=True)

        self.assertIs(out["dry_run"], False, "三闸全过应是写盘态：%r" % (out,))
        self.assertEqual(out["blocked_by"], "", "写盘态不该再有拦截理由：%r" % (out,))
        self.assertEqual(out["written"], 1,
                         "只该写 A 一个（B ≥ floor 不动）：%r" % (out,))

        fm_a = self.cg.get(self.a)["frontmatter"]
        self.assertAlmostEqual(float(fm_a["importance"]), FLOOR, places=6,
                               msg="A 应被抬到 floor：%r" % (fm_a,))
        self.assertEqual(fm_a.get("importance_source"), "retain",
                         "来源须标 retain：%r" % (fm_a,))
        self.assertIn("retained_since", fm_a,
                      "须记提升时点 retained_since：%r" % (fm_a,))

        # B：> floor ⇒ unchanged、**不写盘**（绝不能被压低）
        fm_b = self.cg.get(self.b)["frontmatter"]
        self.assertAlmostEqual(float(fm_b["importance"]), B_BEFORE, places=6,
                               msg="B 高于地板，不该被抬高、更不该被压低：%r" % (fm_b,))
        self.assertEqual(out["unchanged"], 1,
                         "B 应记 unchanged：%r" % (out,))
        self.assertNotEqual(fm_b.get("importance_source"), "retain",
                            "B 未被写盘，来源不该被改：%r" % (fm_b,))

        # C：retained=False ⇒ 根本不在候选里
        cands = [s["id"] for s in out["samples"]]
        self.assertNotIn(self.c, cands,
                         "C 未 retained，不该进候选：%r" % (out.get("samples"),))
        self.assertEqual(out["n_candidates"], 2,
                         "候选应恰为 A/B 两条：%r" % (out,))
        self.assertEqual(out["candidate_source"], "scan",
                         "未显式给 ids ⇒ 候选来自 retain_scan：%r" % (out,))

        # 索引条目同步（内存条目与 fm 同值，防内存/磁盘分叉）
        entry = (self.cg.index.get("nodes") or {}).get(self.a) or {}
        self.assertAlmostEqual(float(entry.get("importance") or -1), FLOOR,
                               places=6,
                               msg="索引条目 importance 须同步为 floor：%r" % (entry,))

        # 账本：新增一条 retain_promote 且 id==A，键面含 before/after/floor/actor
        recs = self._promote_records()
        self.assertEqual(len(recs), 1, "应恰有一条 retain_promote 记账：%r" % (recs,))
        rec = recs[0]
        self.assertEqual(rec["id"], self.a, "记账须指向 A：%r" % (rec,))
        self.assertAlmostEqual(float(rec["before"]), A_BEFORE, places=6,
                               msg="记账须留前像 before：%r" % (rec,))
        self.assertAlmostEqual(float(rec["after"]), FLOOR, places=6,
                               msg="记账须留后像 after：%r" % (rec,))
        self.assertAlmostEqual(float(rec["floor"]), FLOOR, places=6,
                               msg="记账须留 floor：%r" % (rec,))
        self.assertEqual(rec.get("actor"), "retain", "记账须留 actor：%r" % (rec,))
        for key in ("t", "action", "batch", "id", "before", "after", "floor",
                    "actor"):
            self.assertIn(key, rec, "记账键面缺 %s：%r" % (key, rec))

    # ---------- ⑤ 幂等 ----------

    # G5：再 promote(apply=True) 一次 —— A 已在 floor 上 ⇒ unchanged、不重复写
    # （连账本都不多一行）。幂等的根源是 after=max(before,floor)，不是去重表。
    def test_g5_second_apply_is_idempotent(self):
        with mock.patch.object(_am, "e_gate", _fake_gate()):
            first = _retain.promote(self.cg, apply=True, writable=True)
            second = _retain.promote(self.cg, apply=True, writable=True)
        self.assertEqual(first["written"], 1, "首次应写一条：%r" % (first,))
        self.assertEqual(second["written"], 0,
                         "二次不得重复写（A 已在 floor 上）：%r" % (second,))
        self.assertEqual(second["unchanged"], 2,
                         "A/B 都应记 unchanged：%r" % (second,))
        self.assertEqual(len(self._promote_records()), 1,
                         "二次不得多出记账行：%r" % (self._promote_records(),))
        self.assertAlmostEqual(
            float(self.cg.get(self.a)["frontmatter"]["importance"]), FLOOR,
            places=6, msg="二次后 A 仍应稳定在 floor")

    # ---------- ⑥ 真落盘（换实例读盘） ----------

    # G6：写完后新建一个 MdCG(root=tmp) 读盘 ⇒ A 的 importance 仍 0.35。
    # 为什么必须换实例：同一实例的内存索引可能「看起来对了」而盘面没写。
    def test_g6_survives_reopen(self):
        with mock.patch.object(_am, "e_gate", _fake_gate()):
            out = _retain.promote(self.cg, apply=True, writable=True)
        self.assertEqual(out["written"], 1, "前置：首次须真写一条：%r" % (out,))

        fresh = MdCG(root=self.root)
        fm = fresh.get(self.a)["frontmatter"]
        self.assertAlmostEqual(float(fm["importance"]), FLOOR, places=6,
                               msg="重开实例读盘须仍是 floor（真落盘）：%r" % (fm,))
        self.assertEqual(fm.get("importance_source"), "retain",
                         "重开后来源仍应是 retain：%r" % (fm,))
        # B 重开后仍是 0.50——写盘面没顺手牵羊改别的节点
        fm_b = fresh.get(self.b)["frontmatter"]
        self.assertAlmostEqual(float(fm_b["importance"]), B_BEFORE, places=6,
                               msg="B 重开后不该被动过：%r" % (fm_b,))

    # ---------- ⑦ 回滚兑现 ----------

    # G7：promote 的账本带 before ⇒ 本模块 rollback 能写回 before 并记
    # 'retain_rollback'。accept 点名「可被反向应用」，不给这条断言的话
    # 「记账留 before」就只是一句注释。
    def test_g7_rollback_restores_before(self):
        with mock.patch.object(_am, "e_gate", _fake_gate()):
            _retain.promote(self.cg, apply=True, writable=True)
        back = _retain.rollback(self.cg, actor="test")
        self.assertTrue(back["ok"], "回滚应成功：%r" % (back,))
        self.assertEqual(back["reverted"], 1, "应回滚一条：%r" % (back,))
        self.assertIn(self.a, back["ids"], "回滚的应是 A：%r" % (back,))
        self.assertAlmostEqual(
            float(self.cg.get(self.a)["frontmatter"]["importance"]), A_BEFORE,
            places=6, msg="回滚须写回 before")
        path = os.path.join(self.root, _weights.MAINTAIN_LOG)
        acts = [r.get("action") for r in read_jsonl(path)]
        self.assertIn(_retain.ACTION_ROLLBACK, acts,
                      "回滚须留下 retain_rollback 记账：%r" % (acts,))


# 生效条件：unittest 入口——发现本模块全部用例并运行，退出码由 unittest
# 决定（0 全绿 / 1 有失败或错误）。
if __name__ == "__main__":
    unittest.main(verbosity=2)
