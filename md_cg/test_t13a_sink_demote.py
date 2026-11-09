# -*- coding: utf-8 -*-
r"""守卫 · T13a 沉底候选盘点 + 降层实修（md_cg/sink.py 的 candidates / apply_demote）。

十一工况，全部在 **tempfile.mkdtemp() 造的独立 MdCGOS root** 上跑（绝不碰真实库）：

    G01 无策略注入时读真实 data/lifecycle_policy.json ⇒ source='default_file'
    G02 knowledge + last_access 很老 + access_count=0 + importance 低 ⇒ 进候选
    G03 access_count ≥ 3           ⇒ 不进，blocked_by='access_count' 可见
    G04 importance ≥ 0.7           ⇒ 不进，blocked_by='importance' 可见
    G05 layer=contextual           ⇒ 不进，blocked_by='layer' 可见
    G06 last_access 很新           ⇒ 不进，blocked_by='stale' 可见
    G07 dry_run=True ⇒ 层不变（仍 knowledge）、applied 为空、dry_run 为真
    G08 dry_run=False ⇒ 层变 contextual（**内存读回 + 磁盘文件读回两处都断言**）、
        fm['demotion'] 有 {t,from,to,reason}、access_count/last_access 搬迁后仍在
    G09 重复调用幂等 ⇒ 第二次 already_handled 计数可见、不重复处置
    G10 坏 id / 不存在 id ⇒ 该条 error 可见、其余条目照常处理、不抛异常
    G11 受保护节点（self 层 / 显式保护位 / 高 importance+hint）⇒
        skipped_protected 计数可见且层不变

判据为何不恒真：每个工况都造**真实节点**（cg.add 落盘 + 真实 frontmatter），
「老 last_access」用真实 epoch 回写（不是 mock 常量）；G08 的 N137 教训
（缺键 ⇒ 搬迁后静默不可达）只在**真正走过 _move_layer 的搬迁**后才暴露，
故必须实修而不能只读断言。

运行：python D:\wook\lingshu-src\md_cg\test_t13a_sink_demote.py
退出码：0 全绿 ／ 1 断言失败
"""
from __future__ import annotations

import glob
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

import importlib

_sink = importlib.import_module("md_cg.sink")
_mdcg = importlib.import_module("md_cg.mdcg")

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


# 生效条件：传入根与节点 id 时**递归**在 <root> 下找名为 <nid>.md 的文件（真实落点是 <layer>/<bucket>/<id>.md，如 knowledge/orphan/x.md——**带 bucket 段**，故不能只拼 <layer>/<id>.md）；命中**唯一**一个即返回其绝对路径，未命中或命中多个（形态异常）返回 None。
def disk_file(root, nid):
    """磁盘上节点文件的真实路径（递归，容忍 bucket 段）。"""
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        if ("%s.md" % nid) in files:
            hits.append(os.path.join(dirpath, "%s.md" % nid))
    return hits[0] if len(hits) == 1 else None


# 生效条件：传入根与节点 id 时读回磁盘上该节点文件的文本；disk_file 返回 None 或读失败返回 ""——用于断言「文件真的搬了层」而不只是内存索引变了。
def disk_text(root, nid):
    p = disk_file(root, nid)
    if not p:
        return ""
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# 生效条件：传入根与节点 id 时返回磁盘上该文件实际所在的**顶层层目录名**（取相对 root 路径的首段），未命中返回 None——「文件搬没搬层」的磁盘侧判据单点。
def disk_layer(root, nid):
    p = disk_file(root, nid)
    if not p:
        return None
    rel = os.path.relpath(p, root).replace("\\", "/")
    return rel.split("/")[0]


# 生效条件：传入节点 id 与该节点的 fm 时返回把 last_access 回写成「days 天前」后的 fm（原样修改并返回同一 dict）；epoch 数值形态（与 fold_access_records 同口径）。
def age_to(fm, days):
    fm["last_access"] = time.time() - days * DAY
    return fm


# 生效条件：传入 cg 与节点 id 时以 access_count=count / importance=imp / last_access=days 天前往盘面回写该节点（经 cg._write_node + 索引同步），返回 True；任一步抛异常返回 False——**造工况的唯一写入口**，避免各 case 各拼一份写盘逻辑。
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
        # 索引快照同步（免读盘判据读的是内存条目，不同步 ⇒ 工况造了但判据看不见）
        cg.index["nodes"][nid] = e
        return True
    except Exception:                                       # noqa: BLE001
        return False


# 生效条件：在给定 cg 上造一个 knowledge 层、importance 低的普通节点并把它做成「很老未访问」的沉底候选，返回该节点 id；cg.add 失败返回 None。importance_source 非 None 时一并落盘（G04 需要用 'heuristic' 绕开按分自动保护，才能真的走到 importance 判据）。
def make_stale(cg, nid, *, days=400.0, access_count=0, importance=0.2,
               layer="knowledge", importance_source=None):
    kw = {"layer": layer, "importance": importance}
    if importance_source is not None:
        kw["importance_source"] = importance_source
    out = cg.add(nid, "生效条件：守卫夹具正文，CCG 五要素占位。", **kw)
    if not out:
        return None
    if not seed(cg, nid, last_days=days, access_count=access_count,
                importance=importance):
        return None
    return nid


# ==========================================================================
# 各工况
# ==========================================================================

# 生效条件：G01 —— 在无任何 env 注入的前提下调 sink.load_policy()，断言 source=='default_file' 且路径指向包内 data/lifecycle_policy.json、五键等于真实文件值（90/3/['knowledge']/180/0.7）；恒不抛异常（断言失败计 FAIL）。
def case_G01_real_policy():
    for key in (sink_env(),):
        os.environ.pop(key, None)
    pol = _sink.load_policy()
    check("G01 无注入 ⇒ source=default_file", pol.get("source") == "default_file",
          "source=%r" % (pol.get("source"),))
    check("G01 路径指向包内 data/lifecycle_policy.json",
          os.path.normcase(pol.get("path", "")).endswith(
              os.path.normcase(os.path.join("data", "lifecycle_policy.json"))),
          "path=%r" % (pol.get("path"),))
    check("G01 五键等于真实文件值",
          (pol.get("sink_days") == 90 and pol.get("keep_access_count") == 3
           and pol.get("demote_layers") == ["knowledge"]
           and pol.get("trash_days") == 180
           and abs(float(pol.get("protected_importance")) - 0.7) < 1e-9),
          "policy=%s" % ({k: pol.get(k) for k in _sink.POLICY_KEYS},))


# 生效条件：返回 sink 模块声明的 env 名（供 G01 清理用）；模块无该常量时回落字面量 'MDCG_LIFECYCLE_FILE'。
def sink_env():
    return getattr(_sink, "SINK_ENV", "MDCG_LIFECYCLE_FILE")


# 生效条件：G02~G06 —— 在同一个临时库里造五个工况节点（候选 / 高访问 / 高重要 / contextual 层 / 很新），跑一次 candidates()，逐条断言「谁进候选、谁被哪条判据拦下、实测值与阈值可见」；恒不抛异常。
def case_G02_G06_criteria(root):
    cg = _mdcg.MdCG(root)
    pol = _sink.load_policy()

    ok_id = make_stale(cg, "g02-候选", days=400.0, access_count=0, importance=0.2)
    acc_id = make_stale(cg, "g03-高访问", days=400.0, access_count=5, importance=0.2)
    # G04 的夹具必须带 importance_source='heuristic'：**无来源**的 0.9 会先被
    # protect.is_protected 的按分自动保护接走（进 excluded_protected），那样
    # 就永远走不到 ④ importance 判据——工况形同虚设。显式非 hint 来源按
    # issue50-e 不触发按分保护，故能真正考到 ④ 这一条。
    imp_id = make_stale(cg, "g04-高重要", days=400.0, access_count=0,
                        importance=0.9, importance_source="heuristic")
    ctx_id = make_stale(cg, "g05-上下文层", days=400.0, access_count=0,
                        importance=0.2, layer="contextual")
    new_id = make_stale(cg, "g06-很新", days=1.0, access_count=0, importance=0.2)
    for tag, nid in (("G02", ok_id), ("G03", acc_id), ("G04", imp_id),
                     ("G05", ctx_id), ("G06", new_id)):
        check("%s 夹具已落盘 %s" % (tag, nid), bool(nid) and bool(fm_of(cg, nid)))

    rep = _sink.candidates(cg, policy=pol)
    cands = rep["candidates"]
    skips = {s["id"]: s for s in rep["skipped"]}

    # G02：四条全过 ⇒ 进候选
    check("G02 老 knowledge 低访问低重要 ⇒ 进 candidates", ok_id in cands,
          "candidates=%s" % cands)

    # G03：access_count 拦下
    check("G03 access_count≥3 ⇒ 不进 candidates", acc_id not in cands,
          "candidates=%s" % cands)
    check("G03 跳过原因可见=access_count",
          skips.get(acc_id, {}).get("blocked_by") == "access_count",
          "skip=%s" % (skips.get(acc_id),))
    check("G03 原因带回实测值与阈值",
          skips.get(acc_id, {}).get("value") == 5
          and skips.get(acc_id, {}).get("threshold") == 3,
          "skip=%s" % (skips.get(acc_id),))

    # G04：importance 拦下
    check("G04 importance≥0.7 ⇒ 不进 candidates", imp_id not in cands,
          "candidates=%s" % cands)
    check("G04 跳过原因可见=importance",
          skips.get(imp_id, {}).get("blocked_by") == "importance",
          "skip=%s" % (skips.get(imp_id),))
    check("G04 原因带回实测值",
          abs(float(skips.get(imp_id, {}).get("value") or -1) - 0.9) < 1e-9,
          "skip=%s" % (skips.get(imp_id),))

    # G05：层不在 demote_layers
    check("G05 contextual 层 ⇒ 不进 candidates", ctx_id not in cands,
          "candidates=%s" % cands)
    check("G05 跳过原因可见=layer",
          skips.get(ctx_id, {}).get("blocked_by") == "layer",
          "skip=%s" % (skips.get(ctx_id),))

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
          rep["by_criterion"].get("access_count") == 1
          and rep["by_criterion"].get("importance") == 1
          and rep["by_criterion"].get("layer") == 1
          and rep["by_criterion"].get("stale") == 1,
          "by_criterion=%s" % (rep["by_criterion"],))
    return cg


# 生效条件：G07/G08 —— 同一个候选先 dry_run=True 预演（层必须不变），再 dry_run=False 实修（层必须变 contextual）；两处读回：cg.get 的内存 fm 与磁盘文件文本；并断言 demotion 四键与 access_count/last_access 存活；恒不抛异常。
def case_G07_G08_dry_then_apply(root):
    cg = _mdcg.MdCG(root)
    pol = _sink.load_policy()
    nid = make_stale(cg, "g07-g08-实修目标", days=500.0, access_count=0,
                     importance=0.2)
    check("G07/G08 夹具已落盘", bool(nid))

    # ---- G07 预演 ----
    dry = _sink.apply_demote(cg, ids=[nid], dry_run=True, policy=pol)
    check("G07 dry_run 回显为真", dry.get("dry_run") is True,
          "dry_run=%r" % (dry.get("dry_run"),))
    check("G07 applied 为空", dry.get("applied") == [],
          "applied=%s" % (dry.get("applied"),))
    check("G07 预演后内存层仍 knowledge",
          (fm_of(cg, nid).get("layer")) == "knowledge",
          "layer=%r" % (fm_of(cg, nid).get("layer"),))
    check("G07 预演后磁盘层仍 knowledge",
          disk_layer(root, nid) == "knowledge",
          "disk_layer=%r" % (disk_layer(root, nid),))
    check("G07 预演不写账本",
          not os.path.exists(_sink.ledger_path(cg)),
          "ledger_exists=%s" % os.path.exists(_sink.ledger_path(cg)))

    # ---- G08 实修 ----
    real = _sink.apply_demote(cg, ids=[nid], dry_run=False, policy=pol,
                              actor="test")
    check("G08 dry_run 回显为假", real.get("dry_run") is False)
    check("G08 applied 含该节点", nid in real.get("applied", []),
          "applied=%s errors=%s" % (real.get("applied"), real.get("errors")))
    check("G08 实修无错误", real.get("errors") == [],
          "errors=%s" % (real.get("errors"),))

    fm_after = fm_of(cg, nid)
    check("G08 内存读回 layer==contextual",
          fm_after.get("layer") == "contextual",
          "layer=%r" % (fm_after.get("layer"),))
    check("G08 磁盘文件真的搬了层（disk_layer==contextual）",
          disk_layer(root, nid) == "contextual",
          "disk_layer=%r" % (disk_layer(root, nid),))
    # 旧盘面移除：真实路径带 bucket 段（knowledge/orphan/<id>.md），不能直接拼
    # <layer>/<id>.md 判存在，须递归 glob knowledge 整棵子树确认没有残留。
    old_files = glob.glob(os.path.join(root, "knowledge", "**", "%s.md" % nid),
                          recursive=True)
    check("G08 磁盘旧层文件已移除", old_files == [],
          "old=%s" % old_files)

    text = disk_text(root, nid)
    dem = fm_after.get("demotion") or {}
    check("G08 fm['demotion'] 有 t/from/to/reason",
          set(dem) >= {"t", "from", "to", "reason"},
          "demotion=%s" % (dem,))
    check("G08 demotion from/to 正确",
          dem.get("from") == "knowledge" and dem.get("to") == "contextual",
          "demotion=%s" % (dem,))
    check("G08 demotion.reason 带天数",
          "sink:last_access>" in str(dem.get("reason") or ""),
          "reason=%r" % (dem.get("reason"),))

    # N137：搬迁后 access_count / last_access 必须仍在（缺键 ⇒ 静默不可达）
    check("G08 内存 fm 搬迁后仍有 access_count",
          "access_count" in fm_after, "fm keys=%s" % sorted(fm_after))
    check("G08 内存 fm 搬迁后仍有 last_access",
          "last_access" in fm_after, "fm keys=%s" % sorted(fm_after))
    check("G08 磁盘文件文本里仍有 access_count",
          "access_count" in text, "disk head=%r" % text[:200])
    check("G08 磁盘文件文本里仍有 last_access",
          "last_access" in text, "disk head=%r" % text[:200])
    check("G08 索引条目搬迁后仍有 access_count/last_access",
          ("access_count" in (cg.index["nodes"].get(nid) or {})
           and "last_access" in (cg.index["nodes"].get(nid) or {})),
          "index keys=%s" % sorted(cg.index["nodes"].get(nid) or {}))
    check("G08 生命周期状态已推进为 demoted",
          fm_after.get("lifecycle_state") == "demoted",
          "lifecycle_state=%r" % (fm_after.get("lifecycle_state"),))
    return cg, nid


# 生效条件：G09 —— 对已实修过的节点再调一次 apply_demote(dry_run=False)，断言 already_handled 计数为 1、applied 为空（不重复处置）；恒不抛异常。
def case_G09_idempotent(cg, nid):
    pol = _sink.load_policy()
    again = _sink.apply_demote(cg, ids=[nid], dry_run=False, policy=pol)
    check("G09 二次调用 already_handled 计数可见",
          len(again.get("already_handled", [])) == 1,
          "already_handled=%s" % (again.get("already_handled"),))
    check("G09 二次调用不重复处置（applied 为空）",
          again.get("applied") == [], "applied=%s" % (again.get("applied"),))
    check("G09 二次调用无错误", again.get("errors") == [],
          "errors=%s" % (again.get("errors"),))
    # 盘点面同样不再把它算作候选（账本即状态）
    rep = _sink.candidates(cg, policy=pol)
    check("G09 盘点面把它归入 already_handled 而非 candidates",
          nid in rep["already_handled"] and nid not in rep["candidates"],
          "already=%s cands=%s" % (rep["already_handled"], rep["candidates"]))


# 生效条件：G10 —— 一批 ids 里混入一个不存在的 id，断言该条进 errors（可见）、同批的正当候选照常 applied、整体不抛异常；恒不抛异常。
def case_G10_bad_id(root):
    cg = _mdcg.MdCG(root)
    pol = _sink.load_policy()
    good = make_stale(cg, "g10-同批正当", days=500.0, access_count=0,
                      importance=0.2)
    check("G10 同批正当夹具已落盘", bool(good))
    bad = "g10-根本不存在的节点-xyz"

    rep = _sink.apply_demote(cg, ids=[bad, good], dry_run=False, policy=pol)
    errs = {e["id"]: e["error"] for e in rep.get("errors", [])}
    check("G10 坏 id 的 error 可见", bad in errs, "errors=%s" % (rep.get("errors"),))
    check("G10 坏 id 的 error 是 node_not_found",
          errs.get(bad) == "node_not_found", "errs=%s" % errs)
    check("G10 其余条目照常处置（good 在 applied）", good in rep.get("applied", []),
          "applied=%s" % (rep.get("applied"),))
    check("G10 整批不因坏 id 中断（good 层已变）",
          fm_of(cg, good).get("layer") == "contextual",
          "layer=%r" % (fm_of(cg, good).get("layer"),))
    check("G10 n_candidates 与传入 ids 一致", rep.get("n_candidates") == 2,
          "n_candidates=%r" % (rep.get("n_candidates"),))


# 生效条件：G11 —— 造三个受保护节点（self 层节点、显式 protected 位节点、高 importance+hint 节点），断言 apply_demote 把它们记入 skipped_protected、层一律不变、且它们连同盘点面也不进候选；恒不抛异常。
def case_G11_protected(root):
    cg = _mdcg.MdCG(root)
    pol = _sink.load_policy()

    # ① self 层：PROTECTED_LAYERS 之一（层保护）
    self_id = cg.add("g11-self层保护", "生效条件：自我认知节点。", layer="self",
                     importance=0.1)
    seed(cg, self_id, last_days=999.0, access_count=0, importance=0.1)
    # ② 显式保护位
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
    rep = _sink.candidates(cg, policy=pol)
    prot_ids = {r["id"] for r in rep["excluded_protected"]}
    check("G11 盘点面把三者归入 excluded_protected",
          {self_id, flag_id, hint_id} <= prot_ids,
          "excluded=%s" % sorted(prot_ids))
    check("G11 盘点面三者都不进 candidates",
          not ({self_id, flag_id, hint_id} & set(rep["candidates"])),
          "candidates=%s" % rep["candidates"])

    # 实修面：即使显式把受保护 id 塞进 ids，也必须 skipped_protected + 层不变
    before = {nid: fm_of(cg, nid).get("layer")
              for nid in (self_id, flag_id, hint_id)}
    real = _sink.apply_demote(cg, ids=[self_id, flag_id, hint_id],
                              dry_run=False, policy=pol)
    skip_ids = {r["id"] for r in real.get("skipped_protected", [])}
    check("G11 skipped_protected 计数可见（3 条）",
          len(real.get("skipped_protected", [])) == 3,
          "skipped_protected=%s" % (real.get("skipped_protected"),))
    check("G11 三个受保护 id 全在其中",
          {self_id, flag_id, hint_id} <= skip_ids, "skip_ids=%s" % sorted(skip_ids))
    check("G11 applied 为空（受保护一个都没动）",
          real.get("applied") == [], "applied=%s" % (real.get("applied"),))
    check("G11 无错误（受保护是跳过不是错误）",
          real.get("errors") == [], "errors=%s" % (real.get("errors"),))
    after = {nid: fm_of(cg, nid).get("layer")
             for nid in (self_id, flag_id, hint_id)}
    check("G11 层一律不变", before == after, "before=%s after=%s" % (before, after))
    check("G11 磁盘上层也没搬",
          disk_layer(root, self_id) == "self"
          and disk_layer(root, flag_id) == "knowledge"
          and disk_layer(root, hint_id) == "knowledge",
          "self=%r flag=%r hint=%r" % (disk_layer(root, self_id),
                                       disk_layer(root, flag_id),
                                       disk_layer(root, hint_id)))


# 生效条件：跑完全部十一工况（每个 case 在同一个临时 root 上顺序执行并共享 cg 状态），逐条断言；由 main 捕获异常保证退出码语义。
def run_cases():
    tmp = tempfile.mkdtemp(prefix="t13a-sink-demote-")
    print("临时 MdCGOS root：%s" % tmp)
    try:
        case_G01_real_policy()

        # G02~G06 独立子库：避免与后续实修工况互相污染
        root_a = os.path.join(tmp, "A")
        os.makedirs(root_a, exist_ok=True)
        case_G02_G06_criteria(root_a)

        # G07~G09 共享一条实修链（先预演、再实修、再幂等）
        root_b = os.path.join(tmp, "B")
        os.makedirs(root_b, exist_ok=True)
        cg_b, nid_b = case_G07_G08_dry_then_apply(root_b)
        case_G09_idempotent(cg_b, nid_b)

        # G10 坏 id 与 G11 受保护各自独立子库
        root_c = os.path.join(tmp, "C")
        os.makedirs(root_c, exist_ok=True)
        case_G10_bad_id(root_c)

        root_d = os.path.join(tmp, "D")
        os.makedirs(root_d, exist_ok=True)
        case_G11_protected(root_d)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# 生效条件：调用时跑完全部工况并打印形如「t13a sink demote：N 通过，0 失败」的汇总行（有失败则附失败项名），返回 0 当且仅当 FAIL==0；捕获 run_cases 抛出的任何异常并计一次失败。
def main():
    print("t13a sink demote：沉底候选盘点 + 降层实修守卫")
    print("-" * 64)
    try:
        run_cases()
    except Exception as exc:                                # noqa: BLE001
        check("运行期无未捕获异常", False,
              "%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()))
    print("-" * 64)
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("t13a sink demote：%d 通过，%d 失败" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
