# -*- coding: utf-8 -*-
"""issue #192：_move_layer 搬迁条目索引键端到端守卫（G1/G2/G3）。

背景与本件口径
==============
PR #316 旧分支提交 0758e39 给 `_move_layer` 的手写搬迁条目表补 7 键
（role/content_kind/session/branch_id/branched_from/derived_from/
lifecycle_state）。值守审阅指出该件只有静态 diff 核验、未跑端到端、全 PR
无守卫。返工核实：**main 已由 0a30c0c（fix(#192)，2026-10-14）以更彻底的
形态吸收该修法**——搬迁条目改由 `_node_entry` 单点构造，手写表整体删除，
0758e39 的 7 键是其覆盖 14 键的真子集。故本件对 `mdcg.py` **零代码改动**，
补齐审阅要求缺失的端到端守卫：

  · 既有 G9g（test_time_core_lint）只钉归因三键（role/content_kind/
    session），其余 4 键（branch_id/branched_from/derived_from/
    lifecycle_state）此前无端到端守卫——本件 G1 逐键钉满 7 键；
  · G2 把「防半搬」从内存扩到落盘快照（半搬形态跨重启存活的读数见
    0a30c0c 实测记录，本件变异验证复现）；
  · G3 钉既有搬迁行为零回归（防过修）。

变异验证协议（两向读数，人工执行记录于 PR 正文）
================================================
把 `md_cg/mdcg.py` 的 `_move_layer` 回退到 0a30c0c^ 形态（手写 29 键表，
`git show 0a30c0c^:md_cg/mdcg.py > md_cg/mdcg.py`）后本文件：
  G1（g1/g1b/g1c/g1d 全红——7 键 `<键缺失>`）、G2 红（落盘快照里键缺失，
  重开不愈）、G3 绿（既有 path/layer/tags/统计计数等搬迁行为不回归）；
恢复后（`git checkout -- md_cg/mdcg.py`）全绿。

逐键「不搬会发生什么」（消费方读数，md_cg 内 grep 可证）
======================================================
  role           roleviews.matches 的 include_work 否决面（roleviews.py:87）
                 与 receipt 白名单（:79）失效——tool-output/command/edit
                 工作节点搬层后重回视图候选池；
  content_kind   roleviews.py:80-82 `(ck or "text")`——缺键按 "text" 对待，
                 work_wip 草稿进入 verifier 视图；
  session        search 的会话过滤（mdcg.py 候选环 `e.get("session")==session`）
                 ——按会话过滤漏节点；
  branch_id      候选环 `e.get("branch_id") in (None, branch)`——缺键成 None，
                 分支实验副本在默认检索现身；branches._iter_branch_nodes
                 （branches.py:66）把搬过的节点丢出分支清单/合并面；
  branched_from  branches.py:246-247/401——分支清单丢溯源、merge 改写漏节点；
  derived_from   _node_entry 的 G8 派生溯源快照面（mdcg.py:2282-2283 注释）
                 ——悬空派生巡检对搬过的节点免读盘不可见；
  lifecycle_state lifecycle.is_archived 缺键 fail-open 成 active
                 （lifecycle.state_of 回落）——archived 节点搬层后重回
                 默认检索候选（本件 g1b 实测读数）。
"""

import json
import os
import shutil

from . import lifecycle, roleviews
from .mdcg import MdCG

# issue #192 指派的 7 键（0758e39 diff 原文；lifecycle 键以真源常量取名，
# 防 lifecycle.STATE_FIELD 改名后守卫静默漂移）。
KEYS = ("role", "content_kind", "session", "branch_id",
        "branched_from", "derived_from", lifecycle.STATE_FIELD)

# G3 零回归面：0a30c0c^ 手写表**本就携带**的键（变异形态下也必须搬对——
# 这是「防过修」锚，不许把旧有的搬迁行为改坏）。
CARRIED = ("path", "layer", "tags", "importance", "created_at",
           "evidence_count", "access_count", "last_access",
           "verification_basis", "temporal", "spatial", "time_window",
           "edges", "subgraph", "content_hash", "has_neg_conditions")

_BODY = "# 功能名：搬迁目标\n\n工作会话产出的草稿结论"


def _fixture(root, archived=False):
    """最小记忆图：主支来源节点 + 带满 7 键的待搬迁节点，返回就绪实例。

    archived=True 时按合法迁移链 active→demoted→archived 把 lifecycle_state
    推成 "archived"（add 的迁移闸不允许跨级直写）。
    """
    cg = MdCG(str(root), autoflush=0)
    cg.add("p192", "# 功能名：来源节点\n\n主支知识正文")
    cg.add("mv192", _BODY, importance=0.3, confidence=0.3,
           derived_from=["p192"],
           role="tool-output", content_kind="work_wip",
           session="sess-192", branch_id="exp-192", branched_from="p192")
    if archived:
        assert cg.set_state("mv192", "demoted", reason="issue192 夹具")["ok"]
        assert cg.set_state("mv192", "archived", reason="issue192 夹具")["ok"]
    cg.flush()
    cg.close()
    return MdCG(str(root), autoflush=0)


# ------------------------------------------------------------------ G1
def test_g1_move_carries_all_seven_keys(tmp_path):
    """G1：搬迁后 7 键在新层条目就位（逐键，非抽样）＋公开读面读数。"""
    cg = _fixture(tmp_path)
    before = dict(cg.index["nodes"]["mv192"])
    ret = cg._move_layer("mv192", "contextual", reason="issue192-G1")
    assert ret and ret["to"] == "contextual"
    after = cg.index["nodes"]["mv192"]
    for k in KEYS:
        # lifecycle_state 在本夹具为 None（archived 变体见 g1b）——
        # 键级断言用 `in`（缺键 vs 值为 None 是两种形态，不允许静默混同）。
        assert k in after, "搬迁后条目缺键 %s（issue #192 半搬形态）" % k
        assert after[k] == before[k], "键 %s 搬迁失值：%r → %r" % (
            k, before[k], after[k])
    # 6 个非退化夹具值额外钉非 None（防「键在、值空」的假绿）。
    for k in KEYS:
        if k != lifecycle.STATE_FIELD:
            assert after[k] is not None, "键 %s 夹具值不得为 None" % k
    # 公开读面（候选取数全部走索引条目，缺键即读数翻转）：
    # 注意候选环是各维度 AND——按 session 检索须同时带 branch（该节点
    # branch_id='exp-192'，默认 branch=None 本就应把它挡在默认检索外）。
    ids_default = [h[0]["id"] for h in
                   cg.search("草稿", record=False)[0]]
    assert "mv192" not in ids_default, "branch_id 丢失：分支副本出现在默认检索"
    ids_branch = [h[0]["id"] for h in
                  cg.search("草稿", branch="exp-192", record=False)[0]]
    assert "mv192" in ids_branch, "branch_id 丢失：本分支检索反而漏节点"
    ids_sess = [h[0]["id"] for h in cg.search(
        "草稿", branch="exp-192", session="sess-192", record=False)[0]]
    assert "mv192" in ids_sess, "session 丢失：按会话过滤漏节点"
    assert roleviews.matches(after, "verifier") is False, (
        "role/content_kind 丢失：tool-output+work_wip 工作节点进入 verifier 视图")
    cg.close()


def test_g1b_archived_lifecycle_key_survives(tmp_path):
    """G1b：lifecycle_state='archived' 随搬迁存活——退役纪律不 fail-open。"""
    cg = _fixture(tmp_path, archived=True)
    before = dict(cg.index["nodes"]["mv192"])
    assert before[lifecycle.STATE_FIELD] == "archived"
    assert lifecycle.is_archived(before) is True
    cg._move_layer("mv192", "contextual", reason="issue192-G1b")
    after = cg.index["nodes"]["mv192"]
    assert lifecycle.STATE_FIELD in after, "搬迁后缺 lifecycle_state 键"
    assert after[lifecycle.STATE_FIELD] == "archived"
    assert lifecycle.is_archived(after) is True, (
        "lifecycle_state 丢失：is_archived fail-open 成 active")
    ids_default = [h[0]["id"] for h in cg.search("草稿", record=False)[0]]
    assert "mv192" not in ids_default, (
        "lifecycle_state 丢失：archived 节点搬层后重回默认检索候选")
    cg.close()


def test_g1c_moved_entry_form_equals_rescan(tmp_path):
    """G1c：搬迁条目与全量重扫条目同形态（_node_entry 单点，字段集零漂移）。"""
    root = str(tmp_path)
    cg = _fixture(root)
    cg._move_layer("mv192", "contextual", reason="issue192-G1c")
    moved = dict(cg.index["nodes"]["mv192"])
    cg.close()
    # 抹掉快照与分片日志，强制重开走 _scan_nodes 全库扫描（真源重建路径）。
    os.remove(os.path.join(root, "_index.json"))
    shutil.rmtree(os.path.join(root, "_index_log"), ignore_errors=True)
    cg2 = MdCG(root, autoflush=0)
    scan = dict(cg2.index["nodes"]["mv192"])
    assert set(scan) == set(moved), (
        "搬迁条目与重扫条目键集漂移：仅搬迁有 %s / 仅重扫有 %s"
        % (sorted(set(moved) - set(scan)), sorted(set(scan) - set(moved))))
    for k in KEYS:
        assert scan[k] == moved[k], "键 %s 搬迁/重扫两路取值分叉" % k
    cg2.close()


def test_g1d_upstream_verify_face(tmp_path):
    """G1d：上游公开面 verify(weakened)→降级搬迁，7 键端到端。

    lifecycle_state 例外：demote 链在 _move_layer 之后由 set_state("demoted")
    就地补写索引（lifecycle._sync_index 单键 patch），故经该公开面恒为
    "demoted"——单键本体由 g1b 直调面钉住，此处钉其余 6 键不被上游改写。
    """
    cg = _fixture(tmp_path)
    before = dict(cg.index["nodes"]["mv192"])
    out = cg.verify("mv192", "反例证据", "weakened")
    assert out and out.get("demoted") and out["demoted"]["to"] == "contextual"
    after = cg.index["nodes"]["mv192"]
    for k in KEYS:
        if k == lifecycle.STATE_FIELD:
            assert after.get(k) == "demoted"
            continue
        assert k in after and after[k] == before[k], (
            "verify 降级搬迁丢键 %s（issue #192）" % k)
    cg.close()


# ------------------------------------------------------------------ G2
def test_g2_no_old_layer_residue(tmp_path):
    """G2：旧层残留清零（防半搬）——盘面/索引/落盘快照/重开四层全查。"""
    root = str(tmp_path)
    cg = _fixture(root)
    n_before = len(cg.index["nodes"])
    old_rel = cg.index["nodes"]["mv192"]["path"]   # add() 落 knowledge/orphan/
    cg._move_layer("mv192", "contextual", reason="issue192-G2")
    after = cg.index["nodes"]["mv192"]
    # 盘面：旧层文件删除、新层文件就位。
    assert not os.path.exists(os.path.join(root, old_rel)), \
        "旧层文件残留（半搬）：%s" % old_rel
    assert os.path.exists(os.path.join(root, "contextual", "mv192.md"))
    # 索引：唯一条目、指向新层，全库无任何条目再指旧路径。
    assert after["path"] == "contextual/mv192.md"
    assert after["layer"] == "contextual"
    assert len(cg.index["nodes"]) == n_before, "搬迁不得增删节点计数"
    # test_h4_sustain_snapshot 的 G1a 不变式：凡从 cg.index 取回的 nodes 均先取快照，
    # 不得对 cg.index["nodes"] 直接可见迭代（裸迭代点会被 G1a 计为违规）。
    _nodes_snap = list(cg.index["nodes"].values())
    assert not [e for e in _nodes_snap
                if e.get("path") == old_rel], "旧路径条目残留"
    assert MdCG._count_buckets(cg.index["nodes"]) == cg.index["buckets"], \
        "桶计数未随搬迁重算"
    # 落盘快照：半搬形态不得跨 close 存活（0a30c0c 前的实测病灶）。
    cg.close()
    with open(os.path.join(root, "_index.json"), encoding="utf-8") as f:
        snap = json.load(f)
    sent = snap["nodes"]["mv192"]
    for k in KEYS:
        assert k in sent, "落盘快照缺键 %s（半搬跨重启存活）" % k
        assert sent[k] == after[k]
    # 重开（快照路径）：无重扫自愈的假绿——快照里是什么就读到什么。
    cg2 = MdCG(root, autoflush=0)
    for k in KEYS:
        assert cg2.index["nodes"]["mv192"].get(k) == after.get(k), (
            "重开后键 %s 与搬迁时不一致（快照半搬）" % k)
    cg2.close()


# ------------------------------------------------------------------ G3
def test_g3_existing_move_behavior_zero_regression(tmp_path):
    """G3：既有搬迁行为零回归（防过修）——内容/其余索引/统计计数前后一致。"""
    cg = _fixture(tmp_path)
    before_entry = dict(cg.index["nodes"]["mv192"])
    before_node = cg.get("mv192")
    buckets_before = dict(cg.index["buckets"])
    n_before = len(cg.index["nodes"])
    ret = cg._move_layer("mv192", "contextual", reason="issue192-G3")
    after_entry = cg.index["nodes"]["mv192"]
    after_node = cg.get("mv192")
    # 返回体形态（上游 verify/scrub/freshness/evolution 都消费它）。
    assert ret == {"id": "mv192", "from": "knowledge", "to": "contextual",
                   "path": "contextual/mv192.md", "reason": "issue192-G3"}
    # 正文逐字不变；frontmatter 除 layer/demotion 外逐键不变。
    assert after_node["content"] == before_node["content"]
    fm_d = after_node["frontmatter"]
    demotion = fm_d.pop("demotion")
    assert demotion["from"] == "knowledge" and demotion["to"] == "contextual"
    assert fm_d == dict(before_node["frontmatter"], layer="contextual")
    # 旧手写表本就携带的键：值随搬迁保持（变异形态下这些也必须绿）。
    for k in CARRIED:
        expect = ("contextual/mv192.md" if k == "path"
                  else "contextual" if k == "layer" else before_entry[k])
        assert after_entry.get(k) == expect, "既有搬迁键 %s 回归" % k
    # 统计计数：节点数不变、桶计数与重算一致、mv192 恰好退出原桶一票
    # （add() 落 knowledge/orphan/ ⇒ bucket="orphan"；搬迁写 contextual/
    # 根 ⇒ bucket=None——桶总额因此 -1 是**既有行为**，不是回归）。
    assert len(cg.index["nodes"]) == n_before
    assert MdCG._count_buckets(cg.index["nodes"]) == cg.index["buckets"]
    assert cg.index["buckets"].get("orphan", 0) \
        == buckets_before.get("orphan", 0) - 1, "桶归属迁移票数不符"
    assert lifecycle.state_of(after_entry) == lifecycle.state_of(before_entry)
    cg.close()
