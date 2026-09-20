# -*- coding: utf-8 -*-
"""智慧之书 md 真源存储测试：MdStore 对拍 + ConditionDex md 模式读写闭环。

口径（使用者裁定 2026-09-14）：智慧之书知识源=md 文档，sqlite 黑箱退役为
可重建派生物。 MdStore 不得悄悄分叉（字段/集合/边域/检索打分）
- 组B 写闭环：空语料根 → ConditionDex(md_root) → seed_base → md 落盘 →
  重开读回（读写同源）+ seed 幂等
- 组C 往返与留痕：知识卡+边+观测留痕 双模往返一致
- 组D 兼容回归：sqlite 形态（tmp 库）全链路不炸；read_conn duck

运行：python -m md_cg.test_wisdom_md_store
"""
import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE, os.path.join(_HERE, "whitebox_kb"),
           os.path.join(_HERE, "whitebox_kb", "wisdom")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from wisdom_book import (ConditionDex, DEFAULT_DB, DEFAULT_MD_ROOT,  # noqa: E402
                         BASE_ENTRIES, BASE_RELATIONS)
from md_access import MdConn, read_conn  # noqa: E402
from md_whitebox import corpus_ready  # noqa: E402
from md_store import MdStore  # noqa: E402
from aeis_core import ConditionSpace, MemoryLayer, STNode  # noqa: E402

_N = 0


def ok(cond, label):
    global _N
    _N += 1
    assert cond, f"FAIL #{_N}: {label}"
    print(f"  ok#{_N} {label}")


# ---------------------------------------------------------------------------
# 组A · 生产数据对拍（sqlite 派生库 ↔ md 语料根，两者都在时执行）
# ---------------------------------------------------------------------------

def group_a(tmp):
    # 语料就绪判据 = 「目录存在**且含 .md**」（2026-09-20 v14 缺陷 F）：空壳
    # 目录（兄弟测试经 MdCGOS(root) 的 makedirs 留下）不算就绪，否则组A 会
    # 以「md 语料行数 0 > 4000」的失败示人，而真实原因是真源根本不在位。
    if not (os.path.exists(DEFAULT_DB) and corpus_ready(DEFAULT_MD_ROOT)):
        print("组A SKIP：生产对拍数据不全（派生库缺失或语料根缺失/空壳）")
        return
    print("组A · 生产数据对拍（全量）")
    # sqlite 侧用副本隔离：search_content 的 increment_access 会落库，
    # 直连生产库等于测试污染运行库（access_count 漂移实证）——backup 到
    # 副本后权威实现在副本上跑，源库全程只读
    import sqlite3
    copy_db = os.path.join(tmp, "parity_copy.db")
    src = sqlite3.connect(DEFAULT_DB)
    dst = sqlite3.connect(copy_db)
    src.backup(dst)
    dst.close()
    src.close()
    sq = ConditionDex(db_path=copy_db)
    md = ConditionDex(md_root=DEFAULT_MD_ROOT)
    try:
        # sqlite 侧容错读：生产库存在 cs 含未知键的脏行（ConditionSpace.from_json
        # 严格构造会炸——黑箱脆弱性实证）；与 MdStore._ensure 同口径跳过，
        # 保证对拍集合=双侧干净集
        s_by_id = {}
        n_dirty = 0
        for row in sqlite3.connect(copy_db).execute("SELECT * FROM nodes"):
            try:
                n = STNode.from_row(tuple(row))
            except (TypeError, ValueError, KeyError):
                n_dirty += 1
                continue
            if n.layer.value == "knowledge":
                s_by_id[n.id] = n
        s_nodes = list(s_by_id.values())
        print(f"  （sqlite 侧脏行跳过 {n_dirty}）")
        m_conn = MdConn(DEFAULT_MD_ROOT)
        m_rows = m_conn._all_rows()
        ok(len(m_rows) > 4000, f"md 语料行数 {len(m_rows)} > 4000（导出快照在位）")
        m_ids = {r[0] for r in m_rows}
        s_ids = set(s_by_id)
        # md 是 sqlite 的导出快照：交集逐字段等价（sqlite 可能另有运行时新增）
        inter = m_ids & s_ids
        ok(len(inter) >= min(1000, int(len(m_ids) * 0.9)),
           f"md<->sqlite 知识层交集 {len(inter)}（md {len(m_ids)} / sq {len(s_ids)}）")

        # 字段级对拍（抽 40）——语义不变字段逐字节；豁免四个非知识字段：
        # spatial（空值 '{}'↔'[]'）/ temporal（转写进 cs.time_window）/
        # condition_space（时间窗归一注入）/ access_count（运行时统计，
        # sqlite 版尽力而为落库、md 版进程内统计，两侧都不承诺一致）
        m_store = md.store
        m_store._ensure()
        bad = 0
        for nid in sorted(inter)[:40]:
            sn, mn = s_by_id[nid], m_store.get_node(nid)
            if (sn.content != mn.content or sn.modality != mn.modality
                    or list(sn.tags) != list(mn.tags)
                    or sn.state_attributes != mn.state_attributes
                    or sn.semantic_coordinates != mn.semantic_coordinates
                    or sn.entity_id != mn.entity_id
                    or abs(sn.importance - mn.importance) > 1e-9
                    or abs(sn.confidence - mn.confidence) > 1e-9
                    or abs(sn.created_at - mn.created_at) > 1e-6):
                bad += 1
        ok(bad == 0, f"字段级对拍 40 节点零分叉·语义不变字段（bad={bad}）")

        # 全量集合对拍：两种存储物理序不同（sqlite 插入序 vs md 路径字典序），
        # 首屏 limit 截断集合必不同——对拍对象是全集（差≤1 = 双侧容错粒度差：
        # 脏行在 sqlite 侧被跳过、在 md 侧以归一形态装载成功）
        m_all = {n.id for n in m_store.query_nodes(
            layer=MemoryLayer.KNOWLEDGE, limit=1000000)}
        ok(set(s_by_id) <= m_all and len(m_all - set(s_by_id)) <= 1,
           f"query_nodes 全量集合（md {len(m_all)} >= sq {len(s_by_id)}，差<=1）")

        # 双向边对拍（抽 10 节点）
        bad_e = 0
        for nid in sorted(inter)[:10]:
            s_out = {(e.target_id, e.relation_type.value)
                     for e in sq.store.get_outgoing_edges(nid)}
            m_out = {(e.target_id, e.relation_type.value)
                     for e in m_store.get_outgoing_edges(nid)}
            if s_out != m_out:
                bad_e += 1
        ok(bad_e == 0, f"出边域对拍 10 节点零分叉（bad={bad_e}）")

        # 检索对拍：同查询 top5 序列一致（同义词扩展+bigram 打分同构）
        for q in ("存在论", "条件空间的适用边界", "反馈回路如何稳定系统"):
            s_top = [n.id for n, _ in sq.store.search_content(
                q, layers=[MemoryLayer.KNOWLEDGE], limit=5)]
            m_top = [n.id for n, _ in m_store.search_content(
                q, layers=[MemoryLayer.KNOWLEDGE], limit=5)]
            ok(s_top == m_top, f"search_content top5 一致：{q!r}")
    finally:
        sq.close()
        md.close()


# ---------------------------------------------------------------------------
# 组B · md 模式写闭环（tmp 语料根）
# ---------------------------------------------------------------------------

def group_b(tmp):
    print("组B · md 模式写闭环")
    root = os.path.join(tmp, "wb")
    os.makedirs(root, exist_ok=True)
    dex = ConditionDex(md_root=root)
    ok(dex._md_mode and dex.engine is None, "md 模式构造（engine=None）")
    r = dex.seed_base()
    ok(r["status"] == "seeded", f"seed_base 首播 {r['status']}")

    kdir = os.path.join(root, "knowledge")
    import hashlib
    ids_on_disk = set()
    if os.path.isdir(kdir):
        for dp, _dn, fs in os.walk(kdir):
            for f in fs:
                if f.endswith(".md"):
                    ids_on_disk.add(f[:-3])
    card_ids = {"wis_" + hashlib.sha1(n["name"].encode("utf-8")).hexdigest()[:12]
                for n in BASE_ENTRIES}
    missing = card_ids - ids_on_disk
    ok(not missing,
       f"26 张知识卡确定性 id 全部落盘（knowledge 层共 "
       f"{len(ids_on_disk)} 文件=卡+seed 留痕，缺 {len(missing)}）")

    # 重开读回：读写同源（新实例从 md 装载）
    dex.close()
    dex2 = ConditionDex(md_root=root)
    ok(dex2.seed_base()["status"] == "already_seeded", "seed 幂等（重开判重）")
    seeds = [n for n in dex2.store.query_nodes(
        layer=MemoryLayer.KNOWLEDGE, limit=300)
        if "domain:存在论" in (n.tags or [])]
    ok(len(seeds) >= 1, f"知识层从 md 读回（{len(seeds)} 张 domain:存在论 卡）")

    # add_relation → fm.edges 落盘（schema 与导出语料一致）
    eid = dex2.add_relation("存在论", "条件论", "causal",
                            note="条件论以存在论为前提", confidence=0.85)
    ok(eid.startswith("mde_"), "add_relation 返回确定性边 id")
    nid_a = dex2._by_name["存在论"]
    fm_txt = ""
    for dp, _dn, fs in os.walk(kdir):
        for f in fs:
            if not f.endswith(".md"):
                continue
            with open(os.path.join(dp, f), encoding="utf-8") as fh:
                txt = fh.read()
            if nid_a in txt:
                fm_txt = txt.split("---")[1]
                break
        if fm_txt:
            break
    ok(fm_txt and '"relation_type": "causal"' in fm_txt
       and '"verified": 1' in fm_txt,
       "fm.edges 落盘含 causal 边（verified=1）")

    # 读写同源：写入即可读（MdStore.reload 生效）
    edges = dex2.store.get_outgoing_edges(nid_a)
    ok(any(e.relation_type.value == "causal" and e.verified
           for e in edges), "写入后 MdStore 即时可读（verified 边）")
    return dex2


# ---------------------------------------------------------------------------
# 组C · 往返与留痕
# ---------------------------------------------------------------------------

def group_c(dex2):
    print("组C · 往返与留痕")
    cs = ConditionSpace(observation_position="测试台",
                        observation_tool="test_wisdom_md_store",
                        time_window=(0.0, 9999999999.0),
                        existence_constraint="测试用")
    nid = dex2.add_entry("测试学科X", "存在论", "测试断言：往返一致", cs,
                         level=2, status="verified")
    ok(nid.startswith("wis_"), "add_entry md 确定性 id")
    node = dex2.store.get_node(nid)
    ok(node is not None and node.state_attributes.get("name") == "测试学科X"
       and node.layer.value == "knowledge", "写入即可读（state_attributes 往返）")

    rec = dex2._perceive(json.dumps({"type": "测试留痕"}, ensure_ascii=False),
                         condition_space=cs, importance=0.6,
                         tags=["观测层", "测试"])
    ok(len(rec.id) >= 12, "留痕节点返回 id")
    found = False
    for dp, _dn, fs in os.walk(os.path.join(dex2.md_root, "knowledge")):
        if rec.id + ".md" in fs:
            found = True
            break
    ok(found, "留痕落 knowledge 层（对齐 sqlite add_perception 自动进知识层）")
    # 重开可读（留痕读回）
    dex2.close()
    dex3 = ConditionDex(md_root=dex2.md_root)
    got = dex3.store.get_node(rec.id)
    ok(got is not None and got.layer.value == "knowledge", "留痕重开可读")
    return dex3


# ---------------------------------------------------------------------------
# 组D · 兼容回归（sqlite 形态 + duck conn）
# ---------------------------------------------------------------------------

def group_d(tmp):
    print("组D · 兼容回归")
    db = os.path.join(tmp, "legacy.db")
    dex = ConditionDex(db_path=db)          # 显式 db_path → sqlite 形态
    ok(not dex._md_mode and dex.engine is not None, "显式 db_path → sqlite 形态")
    ok(dex.seed_base()["status"] == "seeded", "sqlite 形态 seed 正常")
    nid = dex.add_entry("旧路学科Y", "条件论", "旧路断言", None, level=2,
                        status="verified")
    ok(bool(nid), "sqlite 形态 add_entry 正常")
    ok(bool(dex.add_relation("旧路学科Y", "条件论", "similar")),
       "sqlite 形态建边正常")
    dex.close()

    dex2 = ConditionDex(fresh=True, db_path=os.path.join(tmp, "fresh.db"))
    ok(not dex2._md_mode, "fresh=True → sqlite 形态（兼容 api.py 兜底）")
    dex2.close()

    if corpus_ready(DEFAULT_MD_ROOT):
        dex3 = ConditionDex(md_root=DEFAULT_MD_ROOT)
        try:
            conn = read_conn(dex3)           # duck：MdStore.conn → MdConn
            ok(isinstance(conn, MdConn), "read_conn(dex) md 模式返回 MdConn")
            rows = conn._all_rows()
            ok(len(rows) > 0, f"duck conn 可查询（{len(rows)} 行）")
        finally:
            dex3.close()


def main():
    ok(len(BASE_ENTRIES) >= 20, f"BASE_ENTRIES {len(BASE_ENTRIES)} 在位")
    ok(len(BASE_RELATIONS) >= 20, f"BASE_RELATIONS {len(BASE_RELATIONS)} 在位")
    tmp = tempfile.mkdtemp(prefix="wb_md_test_")
    try:
        group_a(tmp)
        dex2 = group_b(tmp)
        dex3 = group_c(dex2)
        dex3.close()
        group_d(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nALL PASS · {_N} assertions")


if __name__ == "__main__":
    main()
