# -*- coding: utf-8 -*-
r"""守卫 · E-T13a 交办验收判据端到端复现（时间维沉底：knowledge → contextual → trash）。

【E-T13a 验收判据】时间维沉底：长期未访问（超过 sink_days）的 knowledge 层
节点应被降层到 contextual；再闲置超过 trash_days 则应进入 trash。

本脚本在 **tempfile.mkdtemp() 造的独立库 root** 上跑（绝不碰真实库），
直接复现该判据的两段变化链：

    A01 造 knowledge 层节点，last_access 设为 400 天前（超过 sink_days=90）、
        access_count=0，跑一轮 sink 实修（auto_sink=True）
        ⇒ 断言变化链『layer: knowledge → contextual（降层）』
        （内存读回 + 磁盘读回双断言，外加 applied.demote 含该 id）
    A02 随后把 last_access 再推老（400 天前，超过 trash_days=180）跑第二轮
        ⇒ 断言节点进 trash（原层文件不存在 / trash/<id>.md 出现 /
        deletions_log 有该 id 记录）

判据为何不恒真：每个工况都造**真实节点**（cg.add 落盘 + 真实 frontmatter），
「老 last_access」用真实 epoch 回写（不是 mock 常量）；A01/A02 的搬迁只在
**真正走过 sink 实修路径**后才成立，故必须整链跑而不能只做静态断言。
A02 复用 A01 的根库与节点（先降层、再推老、再 trash）——与交办原文
「随后把 last_access 再推老（超过 trash_days）跑第二轮，断言节点进 trash」
的时序逐字一致。

【t1–t4 能力点覆盖】除上面的端到端判据外，本脚本另用**独立工况**逐点证明
t1–t4 已交付的能力（每条都真跑、可复跑、失败即非零退出）：

    B01（t1）策略文件阈值加载——把 MDCG_LIFECYCLE_FILE 指向自建临时策略文件，
        断言 load_policy() 的 sink_days/trash_days 取到**文件里的值**且
        source='env'（阈值来自策略文件，不是写死的常量）。
    B02（t2）按 last_access 判定候选——同一批里造「足够老」与「刚访问过」
        两个节点，断言只有老的那个进 candidates()，年轻的那个进 skipped 且
        blocked_by='stale'。证明判定真读 last_access 而非按 id/层瞎猜。
    B03（t2）降层复用既有 mdcg.MdCGOS._move_layer——用 spy 包住 cg._move_layer，
        断言 apply_demote 实修时**确实调用了它**，且目标层= DEMOTE_TO_LAYER。
        同时断言预演（dry_run=True，缺省）一次都不调它。
    B04（t3）进 trash 复用既有 mdcos.MdCGOS.forget/_forget_apply——用 spy 包住
        cg.forget，断言 apply_trash 实修路径确实调用它，且进 trash 的记录里
        tombstone/trash 字段由该正路产生（不自己搬文件）。
    B05（t4）受保护节点跳过——造显式 protected=True 的节点，断言它不进
        candidates（归 excluded_protected），且即使把它显式塞进 ids，
        apply_demote 也记入 skipped_protected、层**一动不动**。

运行：python D:\wook\lingshu-src\md_cg\test_t13a_acceptance.py
退出码：0 全绿 ／ 1 断言失败
"""
from __future__ import annotations

import importlib
import json
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
_scn = importlib.import_module("md_cg.sustain")
_protect = importlib.import_module("md_cg.protect")

PASS = 0
FAIL = 0
FAILS = []

DAY = 86400.0

#: 本脚本自建的确定性阈值——**经策略文件喂进去**（不是直接改常量），
#: 这样 B01 能证明「阈值确实来自策略文件」这一 t1 能力点。
POL = {"sink_days": 30, "keep_access_count": 1,
       "demote_layers": ["knowledge"], "trash_days": 60,
       "protected_importance": 0.95}


# 生效条件：name 对应的断言 cond 为真时 PASS 加一并打印 [PASS] 行；为假时 FAIL 加一并记入 FAILS、打印带 detail 的 [FAIL] 行；恒不抛异常。
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s%s" % (name, ("  · " + detail) if detail else ""))


# 生效条件：把 nid 的 frontmatter 回写成「last_days 天前未访问、access_count=importance 给定值」并落盘、同步索引——这是造「久未引用节点」判据的唯一真实入口；不抛异常。
def seed(cg, nid, last_days, access_count=0, importance=0.2):
    node = cg.get(nid)
    fm = dict(node["frontmatter"])
    fm["last_access"] = time.time() - last_days * DAY
    fm["access_count"] = access_count
    fm["importance"] = importance
    cg._write_node(nid, cg._node_disk_path(cg.index["nodes"][nid]), fm,
                   node.get("content") or "")


# 生效条件：递归找 nid.md 所在层目录名（相对 root 的首段）；找不到返回 None；不抛异常。
def disk_layer(root, nid):
    for dp, _dirs, fns in os.walk(root):
        if nid + ".md" in fns:
            return os.path.relpath(dp, root).split(os.sep)[0]
    return None


# 生效条件：读 trash 目录文件名列表；目录不存在返回空列表；不抛异常。
def trash_names(cg):
    td = _sink.trash_dir(cg)
    if not os.path.isdir(td):
        return []
    return os.listdir(td)


# 生效条件：进入时把 MDCG_LIFECYCLE_FILE 指向 tmp 下自建策略文件并 return 一个还原函数；退出还原成进入前的值（含原本未设的情形）——保证本脚本不污染调用方环境。
def pin_policy(tmp):
    path = os.path.join(tmp, "lifecycle_policy.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(POL, f)
    prev = os.environ.get(_sink.SINK_ENV)

    def restore():
        if prev is None:
            os.environ.pop(_sink.SINK_ENV, None)
        else:
            os.environ[_sink.SINK_ENV] = prev
    os.environ[_sink.SINK_ENV] = path
    return restore


def case_A01_demote():
    """【E-T13a 验收判据·第一段】长期未访问 ⇒ layer: knowledge → contextual（降层）。"""
    tmp = tempfile.mkdtemp(prefix="t13a-accept-")
    root = os.path.join(tmp, "R")
    os.makedirs(root, exist_ok=True)
    cg = _mdcg.MdCG(root)
    try:
        nid = cg.add("t13a-accept-长期未引用", "E-T13a 验收判据夹具。",
                     layer="knowledge", importance=0.2)
        seed(cg, nid, 400.0)                                  # 400 天前，超过 sink_days=90
        lp = _scn.SustainLoop(cg, d=os.path.join(tmp, "sust"),
                              sink_interval=21600.0, auto_sink=True)
        lp._tick_sink()
        ls = lp.last_sink
        check("A01 台账 confirms sink 实修（dry_run=False）",
              isinstance(ls, dict) and ls.get("dry_run") is False,
              "dry_run=%r" % (ls.get("dry_run"),))
        check("【E-T13a 验收判据】长期未访问节点进入降层候选（applied.demote 含该 id）",
              nid in (ls.get("applied") or {}).get("demote", []),
              "applied=%r" % (ls.get("applied"),))
        node = cg.get(nid)
        check("【E-T13a 验收判据】变化链『layer: knowledge → contextual（降层）』（内存层）",
              bool(node) and (node.get("frontmatter") or {}).get("layer") == "contextual",
              "layer=%r" % ((node.get("frontmatter") or {}).get("layer")))
        check("【E-T13a 验收判据】变化链『layer: knowledge → contextual（降层）』（磁盘层）",
              disk_layer(root, nid) == "contextual",
              "disk_layer=%r" % (disk_layer(root, nid),))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_A02_trash():
    """【E-T13a 验收判据·第二段】降层后再闲置超 trash_days ⇒ 节点进 trash。"""
    tmp = tempfile.mkdtemp(prefix="t13a-accept-")
    root = os.path.join(tmp, "R")
    os.makedirs(root, exist_ok=True)
    cg = _mdcos.MdCGOS(root)                  # trash 场景用审计视图（deletions() 只在其上）
    try:
        nid = cg.add("t13a-accept-进trash", "E-T13a 验收判据夹具。",
                     layer="knowledge", importance=0.2)
        seed(cg, nid, 200.0)                                  # 超过 sink_days=90（第一段前置）
        lp = _scn.SustainLoop(cg, d=os.path.join(tmp, "sust"),
                              sink_interval=21600.0, auto_sink=True)
        _sink.apply_demote(cg, ids=[nid], dry_run=False)      # 第一轮：knowledge → contextual
        check("【E-T13a 验收判据】变化链『layer: knowledge → contextual（降层）』（磁盘层）",
              disk_layer(root, nid) == "contextual",
              "disk_layer=%r" % (disk_layer(root, nid),))
        seed(cg, nid, 400.0, access_count=0)                  # 降层后再闲置超 trash_days=180
        lp._tick_sink()                                       # 第二轮：应进 trash
        ls = lp.last_sink
        check("【E-T13a 验收判据】第二轮节点进 trash（applied.trash 含该 id）",
              nid in (ls.get("applied") or {}).get("trash", []),
              "applied=%r" % (ls.get("applied"),))
        check("【E-T13a 验收判据】原层文件已不在（knowledge/contextual 均无此 id）",
              not any(disk_layer(os.path.join(root, lay), nid) is not None
                      for lay in ("knowledge", "contextual")),
              "disk_layer(trash)=%r"
              % (disk_layer(os.path.join(root, "trash"), nid),))
        check("【E-T13a 验收判据】trash/<id>.md 已出现（文件被搬走）",
              nid + ".md" in trash_names(cg),
              "trash=%r" % (trash_names(cg),))
        dels = cg.deletions()
        dels_ids = [d.get("id") for d in dels]
        check("【E-T13a 验收判据】deletions_log 有该节点记录",
              nid in dels_ids,
              "n_deletions=%d ids=%r" % (len(dels), dels_ids))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_B01_policy_thresholds():
    """（t1）策略文件阈值加载：阈值真的来自策略文件，且 source 标成 env。"""
    tmp = tempfile.mkdtemp(prefix="t13a-accept-")
    restore = pin_policy(tmp)
    try:
        pol = _sink.load_policy()
        check("B01（t1）策略来源标成 env（读到的是本脚本喂的文件）",
              pol.get("source") == "env",
              "source=%r path=%r" % (pol.get("source"), pol.get("path")))
        check("B01（t1）sink_days 取自策略文件（30，非内置 90）",
              abs(float(pol.get("sink_days")) - POL["sink_days"]) < 1e-9,
              "sink_days=%r" % (pol.get("sink_days"),))
        check("B01（t1）trash_days 取自策略文件（60，非内置 180）",
              abs(float(pol.get("trash_days")) - POL["trash_days"]) < 1e-9,
              "trash_days=%r" % (pol.get("trash_days"),))
        check("B01（t1）demote_layers 取自策略文件（['knowledge']）",
              list(pol.get("demote_layers") or []) == POL["demote_layers"],
              "demote_layers=%r" % (pol.get("demote_layers"),))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


def case_B02_last_access_candidates():
    """（t2）按 last_access 判定候选：只有真正久未访问的那个进候选。"""
    tmp = tempfile.mkdtemp(prefix="t13a-accept-")
    restore = pin_policy(tmp)
    root = os.path.join(tmp, "R")
    os.makedirs(root, exist_ok=True)
    cg = _mdcg.MdCG(root)
    try:
        old = cg.add("t13a-accept-久未访问", "老节点。", layer="knowledge", importance=0.2)
        fresh = cg.add("t13a-accept-刚访问", "新节点。", layer="knowledge", importance=0.2)
        seed(cg, old, 400.0)          # 远超 sink_days=30
        seed(cg, fresh, 1.0)          # 1 天前访问 —— 不该沉
        rep = _sink.candidates(cg)    # policy 走 env 里那份
        check("B02（t2）久未访问节点进 candidates（last_access 判定生效）",
              old in rep["candidates"],
              "candidates=%r" % (rep["candidates"],))
        check("B02（t2）刚访问过的节点**不**进 candidates",
              fresh not in rep["candidates"],
              "candidates=%r" % (rep["candidates"],))
        skipped = {r.get("id"): r.get("blocked_by") for r in rep["skipped"]}
        check("B02（t2）刚访问过的节点归 skipped 且 blocked_by='stale'（判据可追）",
              skipped.get(fresh) == "stale",
              "skipped=%r" % (skipped,))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


def case_B03_move_layer_reused():
    """（t2）降层复用既有 mdcg.MdCGOS._move_layer：实修调它、预演一次都不调。"""
    tmp = tempfile.mkdtemp(prefix="t13a-accept-")
    restore = pin_policy(tmp)
    root = os.path.join(tmp, "R")
    os.makedirs(root, exist_ok=True)
    cg = _mdcg.MdCG(root)
    try:
        nid = cg.add("t13a-accept-复用move", "夹具。", layer="knowledge", importance=0.2)
        seed(cg, nid, 400.0)
        calls = []
        real = cg._move_layer

        def spy(node_id, to_layer, **kw):
            calls.append({"id": node_id, "to_layer": to_layer})
            return real(node_id, to_layer, **kw)

        cg._move_layer = spy
        try:
            dry = _sink.apply_demote(cg, ids=[nid], dry_run=True)
            check("B03（t2）预演（dry_run=True 缺省）不调 _move_layer（防护性缺省）",
                  calls == [] and not (dry.get("applied")),
                  "calls=%r applied=%r" % (calls, dry.get("applied")))
            real_rep = _sink.apply_demote(cg, ids=[nid], dry_run=False)
            check("B03（t2）实修确实复用既有 cg._move_layer（被调用 ≥1 次）",
                  len(calls) >= 1,
                  "calls=%r" % (calls,))
            check("B03（t2）_move_layer 目标层 = sink.DEMOTE_TO_LAYER（contextual）",
                  bool(calls) and calls[0]["to_layer"] == _sink.DEMOTE_TO_LAYER,
                  "to_layer=%r 期望=%r" % (calls[0]["to_layer"] if calls else None,
                                           _sink.DEMOTE_TO_LAYER))
            check("B03（t2）实修返回 applied 含该 id 且层已变 contextual",
                  nid in (real_rep.get("applied") or [])
                  and (cg.get(nid)["frontmatter"] or {}).get("layer") == "contextual",
                  "applied=%r layer=%r"
                  % (real_rep.get("applied"),
                     (cg.get(nid)["frontmatter"] or {}).get("layer")))
        finally:
            cg._move_layer = real
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


def case_B04_forget_reused():
    """（t3）进 trash 复用既有 mdcos.MdCGOS.forget：实修确实走它、且产 tombstone。"""
    tmp = tempfile.mkdtemp(prefix="t13a-accept-")
    restore = pin_policy(tmp)
    root = os.path.join(tmp, "R")
    os.makedirs(root, exist_ok=True)
    cg = _mdcos.MdCGOS(root)
    try:
        nid = cg.add("t13a-accept-复用forget", "夹具。", layer="knowledge", importance=0.2)
        seed(cg, nid, 400.0, access_count=0)
        _sink.apply_demote(cg, ids=[nid], dry_run=False)      # 先降层（进 trash 的前置）
        seed(cg, nid, 400.0, access_count=0)
        calls = []
        real = cg.forget

        def spy(node_id, reason="", override=False):
            calls.append({"id": node_id, "override": override})
            return real(node_id, reason=reason, override=override)

        cg.forget = spy
        try:
            rep = _sink.apply_trash(cg, ids=[nid], dry_run=False)
            check("B04（t3）进 trash 确实复用既有 cg.forget（被调用 ≥1 次）",
                  len(calls) >= 1,
                  "calls=%r" % (calls,))
            check("B04（t3）applied 含该 id（搬迁真发生）",
                  nid in (rep.get("applied") or []),
                  "applied=%r" % (rep.get("applied"),))
            check("B04（t3）trash/<id>.md 出现在磁盘上（走 forget 正路而非自搬文件）",
                  nid + ".md" in trash_names(cg),
                  "trash=%r" % (trash_names(cg),))
            recs = rep.get("trashed") or []
            check("B04（t3）trashed 记录带 tombstone（_forget_apply 正路产物）",
                  bool(recs) and bool(recs[0].get("tombstone")),
                  "trashed=%r" % (recs,))
        finally:
            cg.forget = real
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


def case_B05_protected_skip():
    """（t4）受保护节点跳过：盘点不进候选，强塞进 ids 也不动层。"""
    tmp = tempfile.mkdtemp(prefix="t13a-accept-")
    restore = pin_policy(tmp)
    root = os.path.join(tmp, "R")
    os.makedirs(root, exist_ok=True)
    cg = _mdcg.MdCG(root)
    try:
        nid = cg.add("t13a-accept-受保护", "夹具。", layer="knowledge",
                     importance=0.1, protected=True, protection_reason="验收夹具显式保护")
        seed(cg, nid, 400.0, access_count=0, importance=0.1)
        check("B05（t4）夹具确实被判为受保护（前置成立）",
              _protect.is_protected(cg, nid)[0] is True,
              "is_protected=%r" % (_protect.is_protected(cg, nid),))
        rep = _sink.candidates(cg)
        prot_ids = {r.get("id") for r in rep["excluded_protected"]}
        check("B05（t4）受保护节点归 excluded_protected，不落后选",
              nid in prot_ids and nid not in rep["candidates"],
              "excluded=%r candidates=%r" % (prot_ids, rep["candidates"]))
        real = _sink.apply_demote(cg, ids=[nid], dry_run=False)   # 强塞进 ids
        skip_ids = {r.get("id") for r in real.get("skipped_protected", [])}
        check("B05（t4）强塞进 ids 时记入 skipped_protected",
              nid in skip_ids,
              "skipped_protected=%r" % (real.get("skipped_protected"),))
        check("B05（t4）受保护节点层**一动不动**（仍 knowledge）",
              (cg.get(nid)["frontmatter"] or {}).get("layer") == "knowledge",
              "layer=%r" % ((cg.get(nid)["frontmatter"] or {}).get("layer"),))
        check("B05（t4）受保护节点未进 applied.demote",
              nid not in (real.get("applied") or []),
              "applied=%r" % (real.get("applied"),))
    finally:
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


# 生效条件：按 A01..B05 顺序跑完全部工况；任一 case 抛异常即记为一次失败并带 traceback；恒不吞掉其余工况。
def run_cases():
    case_A01_demote()
    case_A02_trash()
    case_B01_policy_thresholds()
    case_B02_last_access_candidates()
    case_B03_move_layer_reused()
    case_B04_forget_reused()
    case_B05_protected_skip()


# 生效条件：调用时跑完全部工况并打印形如「t13a acceptance：N 通过，0 失败」的汇总行（有失败则附失败项名），返回 0 当且仅当 FAIL==0；捕获 run_cases 抛出的任何异常并计一次失败。
def main():
    print("t13a acceptance：E-T13a 交办验收判据端到端复现")
    print("-" * 64)
    try:
        run_cases()
    except Exception as exc:                                  # noqa: BLE001
        check("运行期无未捕获异常", False,
              "%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()))
    print("-" * 64)
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("t13a acceptance：%d 通过，%d 失败" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
