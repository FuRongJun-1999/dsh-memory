# -*- coding: utf-8 -*-
r"""守卫 · T13a 进 trash 候选盘点 + 实修（md_cg/sink.py 的 trash_candidates / apply_trash）。

十二组工况，全部在 **tempfile.mkdtemp() 造的独立 MdCGOS root** 上跑（绝不碰真实库）：

    G01 **源码扫描断言**：sink.py 全文**不含** `os.remove(` / `os.unlink(`
        —— 进 trash 必须走 cg.forget（os.replace 搬进 trash/ + 写 deletions_log，
        可 restore），**绝不物理 unlink**
    G02 已降层 + last_access 很老 + access_count=0 + importance 低 ⇒ 进候选
    G03 **没降过层**的 knowledge 老节点 ⇒ 不进候选，blocked_by='demoted' 可见
    G04 access_count ≥ 3 ⇒ 不进，blocked_by='access_count' 可见
    G05 importance ≥ 0.7 ⇒ 不进，blocked_by='importance' 可见
    G06 last_access 很新 ⇒ 不进，blocked_by='stale' 可见
    G07 dry_run=True ⇒ 节点仍在原层、trash 目录为空、cg.get 还能取到（零写盘）
    G08 dry_run=False 实修 ⇒ 原层文件不在 / trash/<id>.md 出现 / cg.get 取不到 /
        deletions_log 新增含 {id, reason, trash} 的记录 / 返回体带 tombstone
    G09 幂等 ⇒ 第二次调用 already_handled 可见、不重复处置
    G10 单条坏 id ⇒ 该条 error 可见、其余照常、不抛异常
    G11 受保护节点 ⇒ skipped_protected 可见且**没被搬进 trash**

    时间窗边界（trash_days 真的生效，且在**降层后**的语义上生效）：
    G12a 刚降层 + last_access=179 天前 ⇒ 不进（未过 180 天窗）
    G12b 刚降层 + last_access=181 天前 ⇒ 进

判据为何不恒真：每个工况都造**真实节点**（cg.add 落盘 + 真实 frontmatter），
「已降层」经**真实 `apply_demote`**（走 `cg._move_layer`）造出、「老 last_access」
用真实 epoch 回写（不是 mock 常量）；G08 的四条断言（文件搬走 / trash 里出现 /
索引摘除 / 删除清单新增）只在**真正走过 cg.forget** 后才可能同时成立，
故必须实修而不能只做只读断言。

运行：python D:\wook\lingshu-src\md_cg\test_t13a_sink_trash.py
退出码：0 全绿 ／ 1 断言失败
"""
from __future__ import annotations

import glob
import importlib
import os
import shutil
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

_sink = importlib.import_module("md_cg.sink")
_mdcg = importlib.import_module("md_cg.mdcg")
_mdcos = importlib.import_module("md_cg.mdcos")

PASS = 0
FAIL = 0
FAILS = []

DAY = 86400.0


# 生效条件：name 对应的断言 cond 为真时 PASS 加一并打印 [PASS] 行；为假时 FAIL 加一并记入 FAILS、打印带 detail 的 [FAIL] 行；恒不抛异常。
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


# 生效条件：传入一个真实的 MdCG 根与节点 id 时返回该节点 frontmatter（cg.get 取不到返回 {}）；恒不抛异常（读失败按空 fm 处理）。
def fm_of(cg, nid):
    try:
        return (cg.get(nid) or {}).get("frontmatter") or {}
    except Exception:                                       # noqa: BLE001
        return {}


# 生效条件：传入根与节点 id 时**递归**在 <root> 下找名为 <nid>.md 的文件（真实落点是 <layer>/<bucket>/<id>.md，**带 bucket 段**）；命中唯一一个即返回其绝对路径，未命中或命中多个（形态异常）返回 None。
def disk_file(root, nid):
    """磁盘上节点文件的真实路径（递归，容忍 bucket 段）。"""
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        if ("%s.md" % nid) in files:
            hits.append(os.path.join(dirpath, "%s.md" % nid))
    return hits[0] if len(hits) == 1 else None


# 生效条件：在 <root>/**/<nid>.md 下递归收集该 id 的**全部**磁盘落点并返回其相对根路径列表（posix 分隔）——用于断言「原层文件没了 / trash 里出现了 / 只出现一次」这些需要看见**同一 id 的所有副本**的场合。
def disk_hits(root, nid):
    out = []
    for dirpath, _dirs, files in os.walk(root):
        if ("%s.md" % nid) in files:
            full = os.path.join(dirpath, "%s.md" % nid)
            out.append(os.path.relpath(full, root).replace("\\", "/"))
    return sorted(out)


# 生效条件：传入根与节点 id 时返回磁盘上该文件实际所在的**顶层层目录名**（取相对 root 路径首段），未命中返回 None——「文件搬没搬层」的磁盘侧判据单点。
def disk_layer(root, nid):
    p = disk_file(root, nid)
    if not p:
        return None
    rel = os.path.relpath(p, root).replace("\\", "/")
    return rel.split("/")[0]


# 生效条件：传入 cg 与 trash 目录路径时返回该目录下的条目名集合；目录不存在返回空集合；恒不抛异常。
def trash_names(cg):
    d = _sink.trash_dir(cg)
    try:
        return set(os.listdir(d))
    except OSError:
        return set()


# 生效条件：传入 cg 与节点 id 时返回该库 deletions_log 里 id 匹配的全部记录（保持写入顺序）；读失败返回 []——**删除清单的读取单点**，避免各 case 各拼一份。
def deletions_for(cg, nid):
    try:
        return [r for r in cg.deletions() if r.get("id") == nid]
    except Exception:                                       # noqa: BLE001
        return []


# 生效条件：传入 cg 与节点 id 时以 last_days 天前的 epoch 回写 last_access、以 access_count 回写访问计数（经 cg._write_node + 索引同步），返回 True；任一步抛异常返回 False——**造时间/计数工况的唯一写入口**。
def seed(cg, nid, *, last_days=None, access_count=None, importance=None):
    try:
        node = cg.get(nid)
        if not node:
            return False
        fm = dict(node.get("frontmatter") or {})
        if last_days is not None:
            fm["last_access"] = time.time() - last_days * DAY
        if access_count is not None:
            fm["access_count"] = access_count
        if importance is not None:
            fm["importance"] = importance
        e = cg.index["nodes"].get(nid) or {}
        cg._write_node(nid, cg._node_disk_path(e), fm, node.get("content") or "")
        e["last_access"] = fm.get("last_access")
        e["access_count"] = fm.get("access_count")
        e["importance"] = fm.get("importance")
        # 索引快照同步（免读盘判据读的是内存条目，不同步 ⇒ 工况造了但判据看不见）
        cg.index["nodes"][nid] = e
        return True
    except Exception:                                       # noqa: BLE001
        return False


# 生效条件：在给定 cg 上造一个 knowledge 层普通节点并把它**降层**到 contextual（走 sink.apply_demote ⇒ cg._move_layer ⇒ 真实 demotion 字段），随后按 last_days/access_count/importance 回写；返回该节点 id，任一环节失败返回 None——「已降层」工况的**真实构造**单点（不用手写 demotion 字典伪造）。
def make_demoted_then_aged(cg, nid, *, last_days=400.0, access_count=0,
                           importance=0.2, importance_source=None,
                           demoted=True):
    kw = {"layer": "knowledge", "importance": importance}
    if importance_source is not None:
        kw["importance_source"] = importance_source
    out = cg.add(nid, "生效条件：守卫夹具正文，CCG 五要素占位。", **kw)
    if not out:
        return None
    if demoted:
        rep = _sink.apply_demote(cg, ids=[nid], dry_run=False)
        if nid not in rep.get("applied", []):
            return None
        if not (fm_of(cg, nid).get("demotion") or {}):
            return None                                     # 没真降层 ⇒ 夹具作废
    if not seed(cg, nid, last_days=last_days, access_count=access_count,
                importance=importance):
        return None
    return nid


# ==========================================================================
# 各工况
# ==========================================================================

# 生效条件：G01 —— 读 sink.py 全文并以**去空白后的子串**判定其不含 os.remove( / os.unlink(；恒不抛异常（读不到文件时计 FAIL 而非抛）。
def case_G01_no_physical_unlink():
    path = os.path.join(HERE, "sink.py")
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except OSError as exc:                                  # noqa: BLE001
        check("G01 能读到 sink.py 全文", False, "%s" % exc)
        return
    flat = "".join(src.split())                             # 去空白：os . remove( 也挡
    check("G01 sink.py 不含 os.remove(", "os.remove(" not in flat,
          "命中处=%s" % _lines_with(src, "os.remove"))
    check("G01 sink.py 不含 os.unlink(", "os.unlink(" not in flat,
          "命中处=%s" % _lines_with(src, "os.unlink"))
    check("G01 sink.py 声明进 trash 走 cg.forget",
          "cg.forget(" in flat, "未找到 cg.forget( 调用")


# 生效条件：传入源码全文与待查子串时返回命中处的**行号列表**（1 起），供失败信息定位；恒不抛异常。
def _lines_with(src, needle):
    return [i + 1 for i, ln in enumerate(src.splitlines()) if needle in ln]


# 生效条件：G02~G06 —— 在同一个临时库里造五个工况节点（全过 / 没降过层 / 高访问 / 高重要 / 很新），跑一次 trash_candidates()，逐条断言「谁进候选、谁被哪条判据拦下、实测值与阈值可见」；恒不抛异常。
def case_G02_G06_criteria(root):
    cg = _mdcos.MdCGOS(root)
    pol = _sink.load_policy()

    ok_id = make_demoted_then_aged(cg, "g02-候选", last_days=400.0)
    # G03：**没降过层**的老节点（层=knowledge、很老、零访问、低重要）——
    # 它该被 sink.candidates 接走，绝不是 trash 候选
    raw_id = make_demoted_then_aged(cg, "g03-未降层", last_days=400.0,
                                    demoted=False)
    acc_id = make_demoted_then_aged(cg, "g04-高访问", last_days=400.0,
                                    access_count=5)
    imp_id = make_demoted_then_aged(cg, "g05-高重要", last_days=400.0,
                                    importance=0.9,
                                    importance_source="heuristic")
    new_id = make_demoted_then_aged(cg, "g06-很新", last_days=1.0)

    for tag, nid in (("G02", ok_id), ("G03", raw_id), ("G04", acc_id),
                     ("G05", imp_id), ("G06", new_id)):
        check("%s 夹具已落盘 %s" % (tag, nid), bool(nid) and bool(fm_of(cg, nid)))

    # 前置形态核实：G02/G04/G05/G06 真的降过层（走的是 _move_layer），G03 没有
    check("G02 夹具真的带 demotion 记录",
          bool(fm_of(cg, ok_id).get("demotion")),
          "demotion=%s（层=%r）" % (fm_of(cg, ok_id).get("demotion"),
                                    fm_of(cg, ok_id).get("layer")))
    check("G03 夹具确实**没有**降过层",
          not fm_of(cg, raw_id).get("demotion")
          and fm_of(cg, raw_id).get("layer") == "knowledge",
          "fm=%s" % ({k: fm_of(cg, raw_id).get(k)
                      for k in ("layer", "demotion")},))

    rep = _sink.trash_candidates(cg, policy=pol)
    cands = rep["candidates"]
    skips = {s["id"]: s for s in rep["skipped"]}

    # G02：五条全过 ⇒ 进候选
    check("G02 已降层+很老+零访问+低重要 ⇒ 进 candidates", ok_id in cands,
          "candidates=%s" % cands)

    # G03：判据① 拦下
    check("G03 没降过层 ⇒ 不进 candidates", raw_id not in cands,
          "candidates=%s" % cands)
    check("G03 跳过原因可见=demoted",
          skips.get(raw_id, {}).get("blocked_by") == "demoted",
          "skip=%s" % (skips.get(raw_id),))
    check("G03 原因文本点明「应先走 sink/candidates」",
          "先走" in str(skips.get(raw_id, {}).get("detail") or ""),
          "detail=%r" % (skips.get(raw_id, {}).get("detail"),))

    # G04：access_count 拦下
    check("G04 access_count≥3 ⇒ 不进 candidates", acc_id not in cands,
          "candidates=%s" % cands)
    check("G04 跳过原因可见=access_count",
          skips.get(acc_id, {}).get("blocked_by") == "access_count",
          "skip=%s" % (skips.get(acc_id),))
    check("G04 原因带回实测值与阈值",
          skips.get(acc_id, {}).get("value") == 5
          and skips.get(acc_id, {}).get("threshold") == 3,
          "skip=%s" % (skips.get(acc_id),))

    # G05：importance 拦下
    check("G05 importance≥0.7 ⇒ 不进 candidates", imp_id not in cands,
          "candidates=%s" % cands)
    check("G05 跳过原因可见=importance",
          skips.get(imp_id, {}).get("blocked_by") == "importance",
          "skip=%s" % (skips.get(imp_id),))
    check("G05 原因带回实测值",
          abs(float(skips.get(imp_id, {}).get("value") or -1) - 0.9) < 1e-9,
          "skip=%s" % (skips.get(imp_id),))

    # G06：时间不够
    check("G06 last_access 很新 ⇒ 不进 candidates", new_id not in cands,
          "candidates=%s" % cands)
    check("G06 跳过原因可见=stale",
          skips.get(new_id, {}).get("blocked_by") == "stale",
          "skip=%s" % (skips.get(new_id),))

    # 可分辨性：候选为空 vs 全被拦，必须不同形
    check("G02 返回体各桶计数齐全",
          set(rep["counts"]) >= {"nodes", "candidates", "skipped",
                                 "excluded_protected", "already_handled"},
          "counts=%s" % (rep["counts"],))
    check("G02 by_criterion 逐判据归因可见",
          rep["by_criterion"].get("demoted") == 1
          and rep["by_criterion"].get("access_count") == 1
          and rep["by_criterion"].get("importance") == 1
          and rep["by_criterion"].get("stale") == 1,
          "by_criterion=%s" % (rep["by_criterion"],))
    check("G02 判据名与 sink 链**不同**（trash 首闸是 demoted 而非 layer）",
          rep.get("criteria", [None])[0] == "demoted",
          "criteria=%s" % (rep.get("criteria"),))
    return cg


# 生效条件：G07/G08 —— 同一个候选先 dry_run=True 预演（节点仍在原层、trash 为空、cg.get 取得到），再 dry_run=False 实修（原层文件不在 / trash 里出现 / cg.get 取不到 / deletions_log 新增 / 返回体带 tombstone）；恒不抛异常。
def case_G07_G08_dry_then_apply(root):
    cg = _mdcos.MdCGOS(root)
    pol = _sink.load_policy()
    nid = make_demoted_then_aged(cg, "g07-g08-实修目标", last_days=500.0)
    check("G07/G08 夹具已降层并落盘", bool(nid) and bool(fm_of(cg, nid).get("demotion")))
    before_hits = disk_hits(root, nid)
    ledger_before = _read_ledger(cg)

    # ---- G07 预演 ----
    dry = _sink.apply_trash(cg, ids=[nid], dry_run=True, policy=pol)
    check("G07 dry_run 回显为真", dry.get("dry_run") is True,
          "dry_run=%r" % (dry.get("dry_run"),))
    check("G07 trashed 为空", dry.get("trashed") == [],
          "trashed=%s" % (dry.get("trashed"),))
    check("G07 applied 为空", dry.get("applied") == [],
          "applied=%s" % (dry.get("applied"),))
    check("G07 预演后内存层仍 contextual",
          fm_of(cg, nid).get("layer") == "contextual",
          "layer=%r" % (fm_of(cg, nid).get("layer"),))
    check("G07 预演后磁盘层仍 contextual",
          disk_layer(root, nid) == "contextual",
          "disk_layer=%r" % (disk_layer(root, nid),))
    check("G07 预演后 cg.get 仍能取到节点", bool(cg.get(nid)))
    check("G07 预演后 trash 目录为空", trash_names(cg) == set(),
          "trash=%s" % sorted(trash_names(cg)))
    # 账本口径：夹具的**真实降层**（apply_demote(dry_run=False)）已经写过一条
    # op='demote'，故这里不能断言「账本文件不存在」——要断言的是**预演没有
    # 新增任何记录**（条数与内容逐字节不变），包括没有 op='trash'。
    check("G07 预演不新增账本记录",
          _read_ledger(cg) == ledger_before,
          "before=%s after=%s" % (ledger_before, _read_ledger(cg)))
    check("G07 预演没有写任何 op=trash 记录",
          not any(r.get("op") == "trash" for r in _read_ledger(cg)),
          "ledger=%s" % _read_ledger(cg))
    check("G07 预演不写删除清单", deletions_for(cg, nid) == [],
          "deletions=%s" % (deletions_for(cg, nid),))
    check("G07 预演后磁盘落点未变", disk_hits(root, nid) == before_hits,
          "before=%s after=%s" % (before_hits, disk_hits(root, nid)))

    # ---- G08 实修 ----
    real = _sink.apply_trash(cg, ids=[nid], dry_run=False, policy=pol,
                             actor="test")
    check("G08 dry_run 回显为假", real.get("dry_run") is False)
    check("G08 无错误", real.get("errors") == [],
          "errors=%s" % (real.get("errors"),))
    check("G08 applied 含该节点", nid in real.get("applied", []),
          "applied=%s blocked=%s" % (real.get("applied"),
                                     real.get("blocked_by_guard")))

    # ① 原层文件不在了（递归 glob contextual 子树，不能直接拼 <layer>/<id>.md）
    old_files = glob.glob(os.path.join(root, "contextual", "**", "%s.md" % nid),
                          recursive=True)
    check("G08 ①原层文件已不在", old_files == [], "old=%s" % old_files)
    check("G08 ①整个库里该 id 只剩 trash 一份",
          disk_hits(root, nid) == ["trash/%s.md" % nid],
          "hits=%s" % disk_hits(root, nid))

    # ② trash 目录下出现 <id>.md
    tpath = os.path.join(_sink.trash_dir(cg), "%s.md" % nid)
    check("G08 ②trash 目录下出现 <id>.md", os.path.exists(tpath),
          "trash=%s" % sorted(trash_names(cg)))

    # ③ cg.get 取不到（索引已摘）
    check("G08 ③cg.get 取不到（索引已摘）", cg.get(nid) is None,
          "get=%r" % (cg.get(nid),))
    check("G08 ③索引条目已摘除", nid not in (cg.index["nodes"] or {}))

    # ④ deletions_log 新增一条含 {id, reason, trash} 的记录
    dels = deletions_for(cg, nid)
    check("G08 ④deletions_log 新增一条记录", len(dels) == 1,
          "deletions=%s" % dels)
    if dels:
        rec = dels[0]
        check("G08 ④记录含 id/reason/trash 三键",
              {"id", "reason", "trash"} <= set(rec),
              "rec=%s" % (rec,))
        check("G08 ④reason 是 sink:降层后 <天数>d 仍未被引用",
              str(rec.get("reason") or "").startswith("sink:降层后 ")
              and "仍未被引用" in str(rec.get("reason") or ""),
              "reason=%r" % (rec.get("reason"),))
        check("G08 ④trash 字段指向 trash/<id>.md",
              str(rec.get("trash") or "") == "trash/%s.md" % nid,
              "trash=%r" % (rec.get("trash"),))
        check("G08 ④记录带 hash（tombstone 凭据）", bool(rec.get("hash")),
              "hash=%r" % (rec.get("hash"),))

    # ⑤ 返回体 trashed 里有 tombstone
    tr = {r["id"]: r for r in real.get("trashed", [])}
    check("G08 ⑤返回体 trashed 含该节点", nid in tr, "trashed=%s" % (real.get("trashed"),))
    check("G08 ⑤trashed 条目带非空 tombstone",
          bool((tr.get(nid) or {}).get("tombstone")),
          "entry=%s" % (tr.get(nid),))
    check("G08 ⑤tombstone 与删除清单 hash 一致",
          bool(dels) and (tr.get(nid) or {}).get("tombstone") == dels[0].get("hash"),
          "tomb=%r hash=%r" % ((tr.get(nid) or {}).get("tombstone"),
                               dels[0].get("hash") if dels else None))
    return cg, nid


# 生效条件：G09 —— 对已实修过的节点再调一次 apply_trash(dry_run=False)，断言 already_handled 计数为 1、trashed/applied 为空（不重复处置）、无 errors；并断言盘点面同样把它归入 already_handled 而非 candidates；恒不抛异常。
def case_G09_idempotent(cg, nid):
    pol = _sink.load_policy()
    again = _sink.apply_trash(cg, ids=[nid], dry_run=False, policy=pol)
    check("G09 二次调用 already_handled 计数可见",
          len(again.get("already_handled", [])) == 1,
          "already_handled=%s" % (again.get("already_handled"),))
    check("G09 二次调用不重复处置（trashed 为空）",
          again.get("trashed") == [], "trashed=%s" % (again.get("trashed"),))
    check("G09 二次调用无错误", again.get("errors") == [],
          "errors=%s" % (again.get("errors"),))
    check("G09 删除清单没有第二条重复记录",
          len(deletions_for(cg, nid)) == 1,
          "deletions=%s" % (deletions_for(cg, nid),))

    # 盘点面：账本即状态 ⇒ 归入 already_handled
    # 注意：节点已不在索引里，故盘点面看不见它——这里断言的是「不重复处置」
    # 这条链的账本口径：账本里 op='trash' 且 ok 为真 ⇒ _handled_trash 认账。
    check("G09 账本里能看到 op=trash 的成功记录",
          any(r.get("op") == "trash" and r.get("ok")
              and r.get("node_id") == nid
              for r in _read_ledger(cg)),
          "ledger=%s" % _read_ledger(cg))
    check("G09 该条账本记录带 tombstone",
          any(r.get("op") == "trash" and r.get("node_id") == nid
              and r.get("tombstone") for r in _read_ledger(cg)),
          "ledger=%s" % _read_ledger(cg))


# 生效条件：传入 cg 时读回 _sink.jsonl 的全部记录（文件不存在返回 []）；恒不抛异常。
def _read_ledger(cg):
    try:
        from md_cg.fsutil import read_jsonl
        return list(read_jsonl(_sink.ledger_path(cg)))
    except Exception:                                       # noqa: BLE001
        return []


# 生效条件：G10 —— 一批 ids 里混入一个不存在的 id，断言该条进 errors（可见）、同批的正当候选照常进 trash、整体不抛异常；恒不抛异常。
def case_G10_bad_id(root):
    cg = _mdcos.MdCGOS(root)
    pol = _sink.load_policy()
    good = make_demoted_then_aged(cg, "g10-同批正当", last_days=500.0)
    check("G10 同批正当夹具已降层", bool(good))
    bad = "g10-根本不存在的节点-xyz"

    rep = _sink.apply_trash(cg, ids=[bad, good], dry_run=False, policy=pol)
    errs = {e["id"]: e["error"] for e in rep.get("errors", [])}
    check("G10 坏 id 的 error 可见", bad in errs, "errors=%s" % (rep.get("errors"),))
    check("G10 坏 id 的 error 是 node_not_found",
          errs.get(bad) == "node_not_found", "errs=%s" % errs)
    check("G10 其余条目照常处置（good 在 trashed）",
          good in [r["id"] for r in rep.get("trashed", [])],
          "trashed=%s" % (rep.get("trashed"),))
    check("G10 整批不因坏 id 中断（good 已不可取回）", cg.get(good) is None,
          "get=%r" % (cg.get(good),))
    check("G10 n_candidates 与传入 ids 一致", rep.get("n_candidates") == 2,
          "n_candidates=%r" % (rep.get("n_candidates"),))


# 生效条件：G11 —— 造三个受保护节点（self 层节点 / 显式 protected 位节点 / 高 importance+hint 节点），断言 apply_trash 把它们记入 skipped_protected、**trash 目录里没有它们**、磁盘文件仍在原处、cg.get 仍取得到；恒不抛异常。
def case_G11_protected(root):
    cg = _mdcos.MdCGOS(root)
    pol = _sink.load_policy()

    # ① self 层：PROTECTED_LAYERS 之一（层保护）
    self_id = cg.add("g11-self层保护", "生效条件：自我认知节点。", layer="self",
                     importance=0.1)
    seed(cg, self_id, last_days=999.0, access_count=0, importance=0.1)
    # ② 显式保护位（knowledge 层，但打了 protected 位）
    flag_id = cg.add("g11-显式保护位", "生效条件：显式打位。", layer="knowledge",
                     importance=0.1, protected=True,
                     protection_reason="守卫夹具显式保护")
    seed(cg, flag_id, last_days=999.0, access_count=0, importance=0.1)
    # ③ 按分自动保护（importance ≥ AUTO_PROTECT_IMPORTANCE 且来源 hint）
    hint_id = cg.add("g11-按分保护", "生效条件：hint 高分。", layer="knowledge",
                     importance=0.95, importance_source="hint")
    seed(cg, hint_id, last_days=999.0, access_count=0)

    for tag, nid in (("self 层", self_id), ("显式保护位", flag_id),
                     ("按分保护", hint_id)):
        check("G11 夹具已落盘（%s）" % tag, bool(nid) and bool(fm_of(cg, nid)))

    # 盘点面：三者都不该进候选
    rep = _sink.trash_candidates(cg, policy=pol)
    prot_ids = {r["id"] for r in rep["excluded_protected"]}
    check("G11 盘点面三者都不进 candidates",
          not ({self_id, flag_id, hint_id} & set(rep["candidates"])),
          "candidates=%s" % rep["candidates"])
    # 三者都**过不了 ①**（没降过层）——判据短路即停，故它们在盘点面落 skipped
    # 而不是 excluded_protected：保护复核在**全部判据通过之后**才做（与
    # sink.candidates 同序，且更省一次保护判定）。excluded_protected 这一桶
    # 由下一个子工况造「已降层的受保护节点」来考。
    check("G11 盘点面三者落 skipped 且 blocked_by='demoted'",
          {self_id, flag_id, hint_id}
          <= {s["id"] for s in rep["skipped"] if s["blocked_by"] == "demoted"},
          "skipped=%s" % {s["id"]: s["blocked_by"] for s in rep["skipped"]})

    # 实修面：即使显式把受保护 id 塞进 ids，也必须 skipped_protected + 原地不动
    before_hits = {nid: disk_hits(root, nid)
                   for nid in (self_id, flag_id, hint_id)}
    real = _sink.apply_trash(cg, ids=[self_id, flag_id, hint_id],
                             dry_run=False, policy=pol)
    skip_ids = {r["id"] for r in real.get("skipped_protected", [])}
    check("G11 skipped_protected 计数可见（3 条）",
          len(real.get("skipped_protected", [])) == 3,
          "skipped_protected=%s" % (real.get("skipped_protected"),))
    check("G11 三个受保护 id 全在其中",
          {self_id, flag_id, hint_id} <= skip_ids, "skip_ids=%s" % sorted(skip_ids))
    check("G11 trashed 为空（受保护一个都没搬）",
          real.get("trashed") == [], "trashed=%s" % (real.get("trashed"),))
    check("G11 无错误（受保护是跳过不是错误）",
          real.get("errors") == [], "errors=%s" % (real.get("errors"),))

    # **没被搬进 trash**：目录里一个都没有 + 磁盘落点逐个未变 + 仍可取回
    tnames = trash_names(cg)
    check("G11 trash 目录里没有这三个节点",
          not ({"%s.md" % n for n in (self_id, flag_id, hint_id)} & tnames),
          "trash=%s" % sorted(tnames))
    after_hits = {nid: disk_hits(root, nid)
                  for nid in (self_id, flag_id, hint_id)}
    check("G11 磁盘落点逐个未变", before_hits == after_hits,
          "before=%s after=%s" % (before_hits, after_hits))
    check("G11 cg.get 仍取得到三者",
          all(cg.get(nid) for nid in (self_id, flag_id, hint_id)))
    check("G11 删除清单里没有这三条",
          all(deletions_for(cg, nid) == []
              for nid in (self_id, flag_id, hint_id)))

    # ---- excluded_protected 的**正向**工况 ----
    # 上三者在盘点面先被 ①「没降过层」短路拦下（判据次序使然），要考到
    # excluded_protected 这一桶，得造一个**真降过层、且之后被打上保护位**的节点：
    # 先降层（低重要度时守卫放行），再打 protected 位 + 回写很老的 last_access
    # ——这正是「盘点与实修之间节点可能已被打上保护位」的真实形态。
    late_id = make_demoted_then_aged(cg, "g11-降层后才打位", last_days=500.0,
                                     importance=0.2)
    check("G11 降层后才打位的夹具已就位", bool(late_id))
    if late_id:
        node = cg.get(late_id) or {}
        fm = dict(node.get("frontmatter") or {})
        fm["protected"] = True
        fm["protection_reason"] = "守卫夹具：降层之后才打位"
        e = cg.index["nodes"].get(late_id) or {}
        cg._write_node(late_id, cg._node_disk_path(e), fm,
                       node.get("content") or "")
        rep2 = _sink.trash_candidates(cg, policy=pol)
        prot_ids2 = {r["id"] for r in rep2["excluded_protected"]}
        check("G11 已降层的受保护节点 ⇒ 盘点面归入 excluded_protected",
              late_id in prot_ids2, "excluded=%s" % sorted(prot_ids2))
        check("G11 该节点不进 candidates（受保护优先于候选）",
              late_id not in set(rep2["candidates"]),
              "candidates=%s" % rep2["candidates"])
        check("G11 该节点也不在 skipped 里（受保护不是「判据没过」）",
              late_id not in {s["id"] for s in rep2["skipped"]},
              "skipped=%s" % {s["id"]: s["blocked_by"] for s in rep2["skipped"]})
        real2 = _sink.apply_trash(cg, ids=[late_id], dry_run=False, policy=pol)
        check("G11 实修面同样 skipped_protected（且没搬）",
              late_id in {r["id"] for r in real2.get("skipped_protected", [])}
              and real2.get("trashed") == [],
              "skip=%s trashed=%s" % (real2.get("skipped_protected"),
                                      real2.get("trashed")))
        check("G11 该节点文件仍在原处、trash 里没有",
              bool(cg.get(late_id))
              and disk_layer(root, late_id) == "contextual"
              and "%s.md" % late_id not in trash_names(cg),
              "layer=%r trash=%s" % (disk_layer(root, late_id),
                                     sorted(trash_names(cg))))


# 生效条件：G12 —— 在同一个临时库里造两个**都刚降层**的节点，一个 last_access=179 天前、一个 181 天前，断言 179 被 stale 拦下（blocked_by='stale' 且实测值可见）、181 进候选——trash_days=180 的窗口在降层后语义上确实生效；恒不抛异常。
def case_G12_trash_days_boundary(root):
    cg = _mdcos.MdCGOS(root)
    pol = _sink.load_policy()
    near = make_demoted_then_aged(cg, "g12-179天", last_days=179.0)
    far = make_demoted_then_aged(cg, "g12-181天", last_days=181.0)
    check("G12 两个边界夹具都已降层",
          bool(near) and bool(far)
          and bool(fm_of(cg, near).get("demotion"))
          and bool(fm_of(cg, far).get("demotion")))

    rep = _sink.trash_candidates(cg, policy=pol)
    cands = set(rep["candidates"])
    skips = {s["id"]: s for s in rep["skipped"]}

    check("G12 刚降层+179 天前 ⇒ 不进 candidates（未过 180 天窗）",
          near not in cands, "candidates=%s" % rep["candidates"])
    check("G12 179 天的跳过原因可见=stale",
          skips.get(near, {}).get("blocked_by") == "stale",
          "skip=%s" % (skips.get(near),))
    check("G12 179 天的实测闲置天数与阈值可见",
          skips.get(near, {}).get("threshold") == 180
          and 178.0 < float(skips.get(near, {}).get("value") or -1) < 180.0,
          "skip=%s" % (skips.get(near),))
    check("G12 刚降层+181 天前 ⇒ 进 candidates（过了 180 天窗）",
          far in cands, "candidates=%s" % rep["candidates"])
    check("G12 阈值确实取政策里的 trash_days",
          rep["policy"].get("trash_days") == 180,
          "trash_days=%r" % (rep["policy"].get("trash_days"),))

    # 边界对照：把 179 天那条改成 181 天，它必须转而进候选（证明拦下它的**就是**
    # 时间窗本身，而不是别的判据顺带把它挡了）——这是本工况「判据不恒真」的证明。
    seed(cg, near, last_days=181.0)
    rep2 = _sink.trash_candidates(cg, policy=pol)
    check("G12 同一条改成 181 天后转而进候选（时间窗即拦它的判据）",
          near in set(rep2["candidates"]),
          "candidates=%s skips=%s" % (rep2["candidates"],
                                       {s["id"]: s["blocked_by"]
                                        for s in rep2["skipped"]}))


# 生效条件：跑完全部十二组工况（每个 case 在同一个临时 root 下的独立子库上顺序执行），逐条断言；由 main 捕获异常保证退出码语义。
def run_cases():
    tmp = tempfile.mkdtemp(prefix="t13a-sink-trash-")
    print("临时 MdCGOS root：%s" % tmp)
    try:
        case_G01_no_physical_unlink()

        root_a = os.path.join(tmp, "A")
        os.makedirs(root_a, exist_ok=True)
        case_G02_G06_criteria(root_a)

        # G07~G09 共享一条实修链（先预演、再实修、再幂等）
        root_b = os.path.join(tmp, "B")
        os.makedirs(root_b, exist_ok=True)
        cg_b, nid_b = case_G07_G08_dry_then_apply(root_b)
        case_G09_idempotent(cg_b, nid_b)

        root_c = os.path.join(tmp, "C")
        os.makedirs(root_c, exist_ok=True)
        case_G10_bad_id(root_c)

        root_d = os.path.join(tmp, "D")
        os.makedirs(root_d, exist_ok=True)
        case_G11_protected(root_d)

        root_e = os.path.join(tmp, "E")
        os.makedirs(root_e, exist_ok=True)
        case_G12_trash_days_boundary(root_e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# 生效条件：调用时跑完全部工况并打印形如「t13a sink trash：N 通过，0 失败」的汇总行（有失败则附失败项名），返回 0 当且仅当 FAIL==0；捕获 run_cases 抛出的任何异常并计一次失败。
def main():
    print("t13a sink trash：进 trash 候选盘点 + 实修守卫")
    print("-" * 64)
    try:
        run_cases()
    except Exception as exc:                                # noqa: BLE001
        check("运行期无未捕获异常", False,
              "%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()))
    print("-" * 64)
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("t13a sink trash：%d 通过，%d 失败" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
