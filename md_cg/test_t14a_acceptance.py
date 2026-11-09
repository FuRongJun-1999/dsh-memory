# -*- coding: utf-8 -*-
r"""**E-T14a 验收判据端到端复现**（run t14a-20261011 · 收口任务 t3）。

本文件是 accept 原文的**逐条兑现**，不是又一套单元守卫（那两份已存在：
`test_t14a_retain_verdict.py` / `test_t14a_retain_promote.py`）。它与它们的分工：

    test_t14a_retain_verdict.py  —— 判定面逐分支（G1–G9，含坏形状与阈值可配）
    test_t14a_retain_promote.py  —— 写面三闸逐闸（G1–G7，含幂等与回滚）
    本文件（acceptance）         —— **一条链**：反复引用的 A 与从不引用的 B
                                    在同一次盘点、同一次提升、同一次沉底候选
                                    里的**差异**必须整体可复现，且这条差异链
                                    必须与 E-T13a 的 sink 候选语义**对得上**。

## accept 原文 → 本文件的断言映射

    accept ①「A retained=True（免疫沉底）、B retained=False（可沉底候选）」
        ⇒ G1（单点判定） + G2（批量盘点三桶）
    accept ②「promote(apply=True, writable=True)（档位 ALLOW 时）A 的
              importance≥floor=0.35 而 B 不变」
        ⇒ G3（真写盘差异） + G3b（盘面重开取证，防内存假象）
    accept ③「该差异链与 E-T13a 的 sink 候选语义一致：A 不进 sink 候选、
              B 进」
        ⇒ G4（**真调真源 sink.candidates**，非模拟）

## 为什么 G4 能直接调 `sink.candidates`（accept 原文留的那条让步没用上）

accept 原文给了退路：「若该函数签名复杂就按 retained/not_retained 的差异断言
并在测试注释里说明映射」。实测 `sink.candidates(cg, *, now=None, policy=None)`
（sink.py:337）签名只有两个**仅关键字**可选参，且只读、恒不抛异常——不复杂，
故**不做映射近似，直接调真源**：这才是「与 E-T13a 语义一致」的硬证据，
映射式近似只能证明「我认为它们一致」。

调用注意事项两条（否则 G4 会假红，且假红原因与 t14a 无关）：
  · **必须传 `now`**：`sink.candidates` 的判据②是
    `now - last_access > sink_days*86400`（缺省 `last_access=0`），用当前时间
    则 `now-0 ≈ 1.79e9` 秒远大于 90 天，B 才进得了候选。不传 now 不改变
    本仓行为，但传一个**显式的大 now** 让「陈旧」这条判据与挂钟无关，换台
    机器/换天跑结果同形。
  · **必须传 `policy`**：`sink.candidates` 在 `policy=None` 时恒调
    `load_policy()`（sink.py:360），**故意忽略** env `MDCG_LIFECYCLE_FILE`。
    若不显式传策略，一个并发的守卫进程把该 env 设上（本仓既有守卫确实会设，
    见 test_t14a_retain_verdict G8），本用例的判据②③就会用到第三方阈值而假红。
    故 G4 显式传 `sink.load_policy()` 的返回值——**仍走单点读取**，只是把
    读到的策略对象交给下游，来源仍是 `default_file`。

## 为什么 A 的引用要真走引擎路径（不是手改 fm）

A 的 `access_count=5` 由 `cg.fold_access_records(['A'], ts=...)` **真落盘**
五次得到——那是 E-T63a 修复后的唯一正路（mdcg.py:5050 `record_access` 的
即时折叠口径）。手改 frontmatter 也能造出 5，但那样钉住的只是「retain 会读
access_count」；走引擎路径才能同时证明「E-T63a 的计数面」与「E-T14a 的判据面」
**接得上**——这正是本条收口链要验的东西。`ts` 显式给一个固定基准，使
`last_access` 可复现、不随挂钟漂。

## 夹具为何必须让 importance 相等（0.15 / 0.15）

若 A、B 的 importance 不同（例如 A=0.8、B=0.1），A 判 retained 也可以解释成
「它重要性高」，B 判 not-retained 也可以解释成「它重要性低」——**access_count
这条差异轴就没被单独钉住**。两侧都取 0.15（< protected_importance=0.7 且
< floor=0.35）后，唯一的差异只剩「被引用过 5 次」：A 保留、B 不保留、A 被抬到
0.35 而 B 停在 0.15、A 不进 sink 候选而 B 进——四条结论共享同一条因。

## 零污染与纪律

全程影子根：`tempfile.TemporaryDirectory()` 为根（退出自动回收），真
`mdcos.MdCGOS` 造库，**不读不写任何真实数据根**；本用例不起子进程（与
CreatePipe 禁令无涉）、不开后台任务、不 git 操作。档位闸用
`mock.patch.object` 打 `autonomy_modes.e_gate` 的**返回值**（不改进程级 env
`MDCG_AUTONOMY`——那会污染并发守卫，见 test_t14a_retain_promote 文件头注记）。

运行（两路都必须能跑，退出码 0 = 全绿）：
    python -X utf8 D:\wook\lingshu-src\md_cg\test_t14a_acceptance.py
    python -m md_cg.run_tests md_cg -k t14a

退出码：0 全绿 ／ 1 有失败项。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

# 真引擎走 mdcos 的 MdCGOS（accept 原文：「真 MdCGOS 或桩 cg」——用真的一路，
# 桩在这里没有价值：本条验的正是端到端，桩会把「链」验成「两个孤立函数」）。
from md_cg import autonomy_modes as _am       # noqa: E402
from md_cg import retain as _retain           # noqa: E402
from md_cg import sink as _sink               # noqa: E402
from md_cg.mdcos import MdCGOS                # noqa: E402

#: 策略来源的单点 env 名从 sink 取（不在本文件里写第二遍字面量——两处写必然漂移）。
LIFECYCLE_ENV = _sink.SINK_ENV

#: 夹具阈值——写成具名常量，让四条断言里的算术一眼可读、且**同源**：
#: KEEP 取自生效策略（不是硬编码 3），两节点 importance 取同一个数（见文件头）。
FLOOR = _retain.RETAIN_FLOOR_IMPORTANCE      # 0.35（retained 的重要性地板）
SAME_IMPORTANCE = 0.15                       # A/B 相同，且 < floor < 保护线
A_ACCESS_COUNT = 5                           # ≥ keep_access_count(3) ⇒ 免疫沉底

#: 固定基准时间：让 last_access 与 sink.candidates 的 now 都可复现、不随挂钟漂。
BASE_TS = 1_700_000_000.0
#: 显式的大 now（基准 + 一年）：远大于 sink_days=90 天，使「陈旧」判据恒成立。
SCAN_NOW = BASE_TS + 365 * 86400.0


# 生效条件：恒返回「恒 ALLOW」的假 e_gate——不读运行时 env，故不与并发守卫抢
# 全局状态；签名与 autonomy_modes.e_gate 兼容（plan/environ 皆可省）。
def _allow_gate():
    """假 e_gate：档位裁决恒为 ALLOW（供 accept ② 的「档位 ALLOW 时」工况）。"""
    payload = {"action": _am.E_WEIGHT,
               "action_name": _am.ACTION_NAMES[_am.E_WEIGHT],
               "mode": _am.MODE_FULL, "decision": _am.ALLOW, "hint": ""}

    def _gate(plan=None, environ=None):
        return dict(payload)

    return _gate


class T14aAcceptanceTest(unittest.TestCase):
    """accept ①②③ 的端到端复现：同一夹具上四条命令（判定/盘点/提升/沉底候选）。"""

    # 生效条件：建独立临时影子根与真 MdCGOS 实例；按 accept 原文造 A（被反复引用）
    # 与 B（从不被引用）两个 knowledge 层节点——除 access_count 外**所有**取值相同
    # （同层、同 importance），使观察到的差异唯一地归因到「用过几次」。
    def setUp(self):
        # TemporaryDirectory 为根（accept 原文点名）；addCleanup 保证异常路径也回收。
        self.tmp = tempfile.TemporaryDirectory(prefix="t14a_accept_")
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "lib")
        # 用真 MdCGOS（唯一真源），actor 署名便于排查残留。
        self.cg = MdCGOS(root=self.root, actor="t14a-accept")

        # 生效策略：从唯一单点读取，回填给 sink.candidates 用（见文件头注记）。
        # 断言策略来源就是包内默认文件——若有人先把 env 设歪，这里立刻可见，
        # 而不是让下游四条断言各报一句莫名其妙的红。
        self.policy = _sink.load_policy()
        self.keep = float(self.policy["keep_access_count"])

        # A 与 B：**同层同 importance**（差异轴只剩 access_count）。
        self.a = self._make_node("A", "反复被引用的知识节点", "苹果 认知图 章节")
        self.b = self._make_node("B", "从未被引用的知识节点", "香蕉 摘要 附注")

        # A 真走引擎路径被引用 A_ACCESS_COUNT 次（E-T63a 的即时折叠正路）。
        for _ in range(A_ACCESS_COUNT):
            self.cg.fold_access_records([self.a], ts=BASE_TS)

    # 生效条件：在影子库内 cg.add 一个指定层与正文的节点，返回其 id；importance
    # 显式给 SAME_IMPORTANCE（A/B 取值必须相同，理由见文件头）。
    def _make_node(self, nid, content, body):
        self.cg.add(nid, body, layer="knowledge", importance=SAME_IMPORTANCE)
        return nid

    # 生效条件：返回节点 frontmatter 里 importance 的 float（节点/键缺失返回 None）
    # ——断言用它取盘面真值，不读索引条目（索引可能被内存假象蒙住）。
    def _importance(self, cg, nid):
        node = cg.get(nid)
        if not node:
            return None
        fm = node.get("frontmatter") or {}
        return float(fm.get("importance")) if fm.get("importance") is not None else None

    # 生效条件：返回节点 frontmatter 的 access_count（int；缺失按 0）。
    def _access_count(self, cg, nid):
        node = cg.get(nid)
        if not node:
            return None
        return int((node.get("frontmatter") or {}).get("access_count") or 0)

    # ---------- accept ①：判定与盘点 ----------

    # accept ①-a：A retain_verdict retained=True（免疫沉底）、B retained=False。
    # 成对断言是必须的：只断言 A=True 的话，一个恒 True 的桩能过；只断言
    # B=False 的话，恒 False 的桩能过。
    def test_g1_verdict_differs(self):
        """accept ①：A 免疫沉底（retained=True）、B 可沉底候选（retained=False）。"""
        # 前置取证：夹具确实造出了「反复引用 vs 从不引用」这条差异。
        self.assertEqual(self._access_count(self.cg, self.a), A_ACCESS_COUNT,
                         "验收判据（E-T14a ①）前置：A 应被引用 %d 次，实测 %r"
                         % (A_ACCESS_COUNT, self._access_count(self.cg, self.a)))
        self.assertEqual(self._access_count(self.cg, self.b), 0,
                         "验收判据（E-T14a ①）前置：B 应从未被引用，实测 %r"
                         % (self._access_count(self.cg, self.b),))
        self.assertGreaterEqual(self._access_count(self.cg, self.a), self.keep,
                                "验收判据（E-T14a ①）前置：A 的引用次数须达 "
                                "keep_access_count=%s" % self.keep)

        va = _retain.retain_verdict(self.cg, self.a)
        vb = _retain.retain_verdict(self.cg, self.b)

        self.assertTrue(
            va["retained"],
            "验收判据（E-T14a ①）：A 被反复引用（access_count=%d≥keep=%s），"
            "retain_verdict 应判 retained=True（免疫沉底），实得 %r"
            % (A_ACCESS_COUNT, self.keep, va))
        self.assertFalse(
            vb["retained"],
            "验收判据（E-T14a ①）：B 从未被引用（access_count=0<keep=%s）且未受"
            "保护，retain_verdict 应判 retained=False（可沉底候选），实得 %r"
            % (self.keep, vb))
        # 归因可读：A 的理由须落到 access_count 这条判据上（而不是碰巧被保护线
        # 拦下——B 的 same importance 已排除后者）。
        self.assertIn("access_count", va["why"],
                      "验收判据（E-T14a ①）：A 保留的理由须归因到 access_count：%r"
                      % (va,))
        # 两节点 importance 相同 ⇒ A 的 retained 不可能是「重要性达线」造成的。
        self.assertEqual(self._importance(self.cg, self.a),
                         self._importance(self.cg, self.b),
                         "验收判据（E-T14a ①）前置：A/B 的 importance 必须相同，"
                         "否则差异无法唯一归因到 access_count")
        # 策略来源可追溯（accept 要求返回体带 policy_source）。
        for got, tag in ((va, "A"), (vb, "B")):
            self.assertTrue(got.get("policy_source"),
                            "验收判据（E-T14a ①）：%s 的判定须带 policy_source：%r"
                            % (tag, got))

    # accept ①-b：批量盘点把这条差异**分桶**呈现——A 进 retained、B 进
    # not_retained，且盘点零写盘（跑前后全库 mtime 逐位一致）。
    def test_g2_scan_buckets_differ(self):
        """accept ①：retain_scan 把 A 分入 retained、B 分入 not_retained（只读）。"""
        before = self._tree_mtimes(self.root)
        scan = _retain.retain_scan(self.cg)
        after = self._tree_mtimes(self.root)

        retained_ids = [r["id"] for r in scan["retained"]]
        not_retained_ids = [r["id"] for r in scan["not_retained"]]

        self.assertIn(
            self.a, retained_ids,
            "验收判据（E-T14a ①）：A 应进 retained 桶，实得 %r" % (retained_ids,))
        self.assertNotIn(
            self.a, not_retained_ids,
            "验收判据（E-T14a ①）：A 不该进 not_retained 桶：%r" % (not_retained_ids,))
        self.assertIn(
            self.b, not_retained_ids,
            "验收判据（E-T14a ①）：B 应进 not_retained 桶（可沉底候选），实得 %r"
            % (not_retained_ids,))
        self.assertNotIn(
            self.b, retained_ids,
            "验收判据（E-T14a ①）：B 不该进 retained 桶：%r" % (retained_ids,))
        # 盘点面与判定面必须**同一结论**——两处不一致就是「同一语义两处实现」。
        self.assertEqual(_retain.retain_verdict(self.cg, self.a)["retained"],
                         self.a in retained_ids,
                         "验收判据（E-T14a ①）：盘点与单点判定对 A 的结论必须一致")
        self.assertEqual(_retain.retain_verdict(self.cg, self.b)["retained"],
                         self.b in retained_ids,
                         "验收判据（E-T14a ①）：盘点与单点判定对 B 的结论必须一致")
        # 零写盘：accept ① 的判据是**只读**的，盘点自己不许动盘面。
        self.assertEqual(before, after,
                         "验收判据（E-T14a ①）：retain_scan 必须零写盘"
                         "（跑前后全库文件与 mtime 逐位一致），差异 %r"
                         % (self._tree_diff(before, after),))
        self.assertTrue(scan.get("policy_source"),
                        "验收判据（E-T14a ①）：盘点须带 policy_source：%r"
                        % (scan.get("policy_source"),))
        self.assertIn("t", scan, "验收判据（E-T14a ①）：盘点须带基准时间 t")

    # ---------- accept ②：提升差异 ----------

    # accept ②：档位 ALLOW 时 promote(apply=True, writable=True) ⇒ A 被抬到
    # ≥floor=0.35，B **不变**。B 不变是关键：候选面若退化成「全库都算候选」，
    # B 会被一并抬到 0.35，本断言即红。
    def test_g3_promote_raises_only_a(self):
        """accept ②：全闸放开时 A 的 importance≥floor，而 B 保持不变。"""
        a_before = self._importance(self.cg, self.a)
        b_before = self._importance(self.cg, self.b)

        with mock.patch.object(_am, "e_gate", _allow_gate()):
            out = _retain.promote(self.cg, apply=True, writable=True)

        self.assertIs(out["dry_run"], False,
                      "验收判据（E-T14a ②）：三闸全过应是写盘态（非预演）：%r" % (out,))
        self.assertEqual(out["blocked_by"], "",
                         "验收判据（E-T14a ②）：写盘态不该有拦截理由：%r" % (out,))

        a_after = self._importance(self.cg, self.a)
        b_after = self._importance(self.cg, self.b)

        self.assertGreaterEqual(
            a_after, FLOOR - 1e-9,
            "验收判据（E-T14a ②）：A 的 importance 应被抬到 ≥floor=%.4g，"
            "实测 %.4g（提升前 %.4g）" % (FLOOR, a_after, a_before))
        self.assertEqual(
            b_after, b_before,
            "验收判据（E-T14a ②）：B 未 retained，importance 必须**一字不变**"
            "（%.4g），实测 %.4g" % (b_before, b_after))
        # 「不变」不只是数值相等：连来源标记都不该被写过。
        b_src = (self.cg.get(self.b)["frontmatter"] or {}).get("importance_source")
        self.assertNotEqual(
            b_src, "retain",
            "验收判据（E-T14a ②）：B 未被提升，不得留下 importance_source='retain'"
            "（那是一次写盘）：%r" % (b_src,))
        # 候选面确实走了 retain 判据：B 根本不在候选里。
        cand_ids = [s["id"] for s in out.get("samples") or []]
        self.assertNotIn(self.b, cand_ids,
                         "验收判据（E-T14a ②）：B 未 retained，不该进提升候选：%r"
                         % (out.get("samples"),))
        self.assertIn(self.a, cand_ids,
                      "验收判据（E-T14a ②）：A retained 且低于地板，应在候选里：%r"
                      % (out.get("samples"),))

    # accept ②-b：换一个新实例读盘，差异仍在（防「内存看起来对了、盘面没写」）。
    def test_g3b_promote_diff_survives_reopen(self):
        """accept ②：重开 MdCGOS 读盘，A≥floor 而 B 不变的差异仍成立（真落盘）。"""
        b_before = self._importance(self.cg, self.b)
        with mock.patch.object(_am, "e_gate", _allow_gate()):
            out = _retain.promote(self.cg, apply=True, writable=True)
        self.assertGreaterEqual(
            out["written"], 1,
            "验收判据（E-T14a ②）前置：A 低于地板，本轮应真写盘至少一条：%r" % (out,))

        fresh = MdCGOS(root=self.root, actor="t14a-accept")
        a_reopened = self._importance(fresh, self.a)
        b_reopened = self._importance(fresh, self.b)

        self.assertGreaterEqual(
            a_reopened, FLOOR - 1e-9,
            "验收判据（E-T14a ②）：重开实例读盘后 A 的 importance 仍应 ≥floor=%.4g，"
            "实测 %.4g（内存态与实际盘面分叉）" % (FLOOR, a_reopened))
        self.assertEqual(
            b_reopened, b_before,
            "验收判据（E-T14a ②）：重开读盘后 B 的 importance 仍应是被提升前的"
            "%.4g，实测 %.4g" % (b_before, b_reopened))

    # ---------- accept ③：与 E-T13a 的 sink 候选语义一致 ----------

    # accept ③：差异链与 E-T13a 的 sink 候选语义一致——A **不进** sink 候选、
    # B **进**。直接调真源 sink.candidates（签名不复杂，accept 留的映射式退路
    # 不启用，理由与两条传参注意事项见文件头）。
    def test_g4_sink_candidates_semantics_agree(self):
        """accept ③：A 不进 sink 候选、B 进——与 retain 的 retained 语义一致。"""
        cand = _sink.candidates(self.cg, now=SCAN_NOW, policy=self.policy)

        self.assertNotIn(
            self.a, cand["candidates"],
            "验收判据（E-T14a ③）：A 被反复引用（免疫沉底），不得进 E-T13a 的 "
            "sink 沉底候选，实得 candidates=%r" % (cand["candidates"],))
        self.assertIn(
            self.b, cand["candidates"],
            "验收判据（E-T14a ③）：B 从未被引用且未受保护，应进 E-T13a 的 sink "
            "沉底候选，实得 candidates=%r（skipped=%r）"
            % (cand["candidates"], cand["skipped"]))
        # A 被拦下的归因必须是 access_count 这条判据（与 retain 的 why 同源），
        # 而不是碰巧因为层/陈旧/重要性。
        blocked = {s["id"]: s["blocked_by"] for s in cand["skipped"]}
        self.assertEqual(
            blocked.get(self.a), "access_count",
            "验收判据（E-T14a ③）：A 被 sink 拦下的判据应是 access_count"
            "（与 retain_verdict 的 why 同一条语义轴），实得 %r" % (blocked,))
        # 语义对应：retained ⇔ 不进 sink 候选（在本夹具的相同取值下——A/B 层
        # 相同、protection 相同，sink 其余三条判据对两者同为真）。
        self.assertEqual(
            _retain.retain_verdict(self.cg, self.a)["retained"],
            self.a not in cand["candidates"],
            "验收判据（E-T14a ③）：A 的 retained 语义应与「不进 sink 候选」一致")
        self.assertEqual(
            _retain.retain_verdict(self.cg, self.b)["retained"],
            self.b not in cand["candidates"],
            "验收判据（E-T14a ③）：B 的 retained 语义应与「不进 sink 候选」一致")
        # 差异的**唯一**来源：两个节点除 access_count 外取值全同。
        self.assertEqual(self._access_count(self.cg, self.a), A_ACCESS_COUNT,
                         "验收判据（E-T14a ③）：A 的引用计数须保持在 %d"
                         % A_ACCESS_COUNT)
        self.assertEqual(self._access_count(self.cg, self.b), 0,
                         "验收判据（E-T14a ③）：B 的引用计数须保持 0")

    # ---------- 差异链的整体复现 ----------

    # 端到端：把 ①→②→③ 串成**一条链**在同一次 setup 里跑完，断言四段读数
    # 同时成立——任何一段与另一段矛盾（例如「判 retained 但进 sink 候选」），
    # 本用例即红。这是本文件存在的理由：三份独立守卫各自绿，不等于这条链自洽。
    def test_g5_full_chain_is_self_consistent(self):
        """accept ①②③：判定→盘点→提升→沉底候选四段读数在同一次运行里自洽。"""
        # 段 1：判定
        va = _retain.retain_verdict(self.cg, self.a)
        vb = _retain.retain_verdict(self.cg, self.b)
        # 段 2：盘点
        scan = _retain.retain_scan(self.cg)
        # 段 3：提升（档位 ALLOW）
        with mock.patch.object(_am, "e_gate", _allow_gate()):
            prom = _retain.promote(self.cg, apply=True, writable=True)
        # 段 4：E-T13a 的沉底候选（不传 now 之外的一切都取单点读取）
        cand_now = _sink.candidates(self.cg, now=SCAN_NOW, policy=self.policy)

        readings = {
            "verdict_A_retained": va["retained"],
            "verdict_B_retained": vb["retained"],
            "scan_A_in_retained": self.a in [r["id"] for r in scan["retained"]],
            "scan_B_in_not_retained": self.b in [r["id"] for r in scan["not_retained"]],
            "promote_written": prom["written"],
            "A_importance": self._importance(self.cg, self.a),
            "B_importance": self._importance(self.cg, self.b),
            "sink_A_in_candidates": self.a in cand_now["candidates"],
            "sink_B_in_candidates": self.b in cand_now["candidates"],
        }

        # 用一条断言把整链的四段结论一次说清——失败时 readings 直接可读。
        self.assertEqual(
            (va["retained"], vb["retained"],
             readings["scan_A_in_retained"], readings["scan_B_in_not_retained"],
             readings["sink_A_in_candidates"], readings["sink_B_in_candidates"]),
            (True, False, True, True, False, True),
            "验收判据（E-T14a ①②③）：完整差异链应为「A 保留/不进 sink 候选、"
            "B 不保留/进 sink 候选」，实测读数 %r" % (readings,))
        self.assertGreaterEqual(
            readings["A_importance"], FLOOR - 1e-9,
            "验收判据（E-T14a ①②③）：链末端 A 的 importance 应 ≥floor=%.4g，"
            "实测 %r（全链读数 %r）" % (FLOOR, readings["A_importance"], readings))
        self.assertLess(
            readings["B_importance"], FLOOR - 1e-9,
            "验收判据（E-T14a ①②③）：链末端 B 的 importance 应仍低于地板"
            "%.4g（未被提升），实测 %r（全链读数 %r）"
            % (FLOOR, readings["B_importance"], readings))
        # B 低于地板这件事本身与「B 不进候选」同源：B retained=False。
        self.assertGreater(readings["promote_written"], 0,
                           "验收判据（E-T14a ①②③）：链中提升段应真写盘（A 低于"
                           "地板）：%r" % (readings,))

    # ---------- 取证工具 ----------

    # 生效条件：os.walk 遍历 root 下**所有**文件，返回 {相对路径(/ 分隔): mtime_ns}；
    # mtime 用 st_mtime_ns 取整型纳秒，避免浮点比较的精度噪声把「没变」误判成「变了」。
    # 比 mtime 而不是只比内容哈希：前者抓得到「原地重写同样内容」的写。
    def _tree_mtimes(self, root):
        out = {}
        if not os.path.isdir(root):
            return out
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                rel = os.path.relpath(fp, root).replace("\\", "/")
                try:
                    out[rel] = os.stat(fp).st_mtime_ns
                except OSError as exc:                   # 读不到也如实记，不静默跳过
                    out[rel] = "stat_error:%s" % type(exc).__name__
        return out

    # 生效条件：恒返回 (新增键, 消失键, mtime 变化 dict)——断言失败时打印可读证据。
    def _tree_diff(self, before, after):
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = {k: (before[k], after[k]) for k in set(before) & set(after)
                   if before[k] != after[k]}
        return added, removed, changed


# 生效条件：unittest 入口——发现本模块全部用例并运行；退出码由 unittest 决定
# （0 全绿 / 1 有失败或错误）。用 -X utf8 运行，中文断言消息在 cp936 控制台不炸。
if __name__ == "__main__":
    unittest.main(verbosity=2)
