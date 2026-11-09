# -*- coding: utf-8 -*-
r"""守卫 · T13a 第七档 sink tick 端到端（md_cg/sustain.py 的 auto_sink / _tick_sink）。

六条断言，全部在 **tempfile.mkdtemp() 造的独立库 root** 上跑（绝不碰真实库）：

    G01 默认构造（不开开关、不设 env/args）⇒ auto_sink=False、
        `_tick_sink()` 跑完**零写盘**（真实 knowledge 老节点层不变、
        trash 目录不出现、_sink.jsonl 不出现），但 `last_sink` 台账**存在**
        且 `dry_run=True`、`policy_source='default_file'`、
        `n_candidates/n_trash` 数值正确（n_trash=0：未降层不构成 trash 候选）
    G02 `auto_sink=True`（构造时传参）⇒ 跑完该节点**确实降层到 contextual**
        （内存读回 + 磁盘读回双断言）、台账 `dry_run=False`、applied 含该 id
    G03 `auto_sink=True` 且节点已降层、闲置超 trash_days ⇒ 确实**进 trash**
        （原层文件不再存在 / trash/<id>.md 出现 / deletions_log 有该 id 记录）
    G04 env `MDCG_LIFECYCLE_FILE` 指向**不存在路径** ⇒ 不抛异常、照常盘点、
        `policy_source='builtin'`、五键用 `BUILTIN_DEFAULTS` 内置默认
    G05 既有六档（tidy/conformance/sleep/evolve/scrub/heal）**读数形状不变**：
        跑一轮 `_tick_scrub` 断言 last_scrub 十一键仍在，
        `TICK_INTERVAL_ATTRS` 前六项名字/顺序一字未动
    G06 `_wrap_ticks` 名单含新增档名（sink 是第七项）、包完仍可跑通

判据为何不恒真：每个工况都造**真实节点**（cg.add 落盘 + 真实 frontmatter），
「老 last_access」用真实 epoch 回写（不是 mock 常量）；G02/G03 的搬迁只在
**真正走过 `_tick_sink` 的 auto_sink=True 实修路径**后才成立，故必须整档跑
而不能只做静态断言。

运行：python D:\wook\lingshu-src\md_cg\test_t13a_sink_e2e.py
退出码：0 全绿 ／ 1 断言失败
"""
from __future__ import annotations

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
_scn = importlib.import_module("md_cg.sustain")

PASS = 0
FAIL = 0
FAILS = []

DAY = 86400.0
SINK_ENV = _sink.SINK_ENV


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


# 生效条件：把 nid 的 frontmatter 回写成「last_days 天前未访问、access_count=importance 给定值」并落盘、同步索引——这是造「老节点」判据的唯一真实入口；不抛异常。
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


# 生效条件：造一个「沉底候选」根库——knowledge 低 importance 节点 + 400 天前 last_access；返回 (tmp, root, cg, nid)；调用方负责清理。
def make_candidate_root():
    tmp = tempfile.mkdtemp(prefix="t13a-e2e-")
    root = os.path.join(tmp, "R")
    os.makedirs(root, exist_ok=True)
    cg = _mdcg.MdCG(root)
    nid = cg.add("t13a-e2e-老节点", "生效条件：端到端夹具。", layer="knowledge",
                 importance=0.2)
    seed(cg, nid, 400.0)
    return tmp, root, cg, nid


def case_G01_default_readonly():
    """默认构造 ⇒ auto_sink=False、零写盘、台账存在且 dry_run=True。"""
    tmp, root, cg, nid = make_candidate_root()
    try:
        lp = _scn.SustainLoop(cg, d=os.path.join(tmp, "sust"),
                              sink_interval=21600.0)          # 不开开关
        check("G01 默认构造 auto_sink 为 False",
              lp.auto_sink is False,
              "auto_sink=%r" % (lp.auto_sink,))
        lp._tick_sink()
        ls = lp.last_sink
        check("G01 跑完 last_sink 台账存在",
              isinstance(ls, dict) and "t" in ls,
              "keys=%s" % (sorted(ls.keys()) if isinstance(ls, dict) else None,))
        check("G01 台账 dry_run=True（开关取反派生）",
              ls.get("dry_run") is True and ls.get("auto_sink") is False,
              "dry_run=%r auto_sink=%r" % (ls.get("dry_run"), ls.get("auto_sink")))
        check("G01 policy_source='default_file'（无 env/arg 注入）",
              ls.get("policy_source") == "default_file",
              "policy_source=%r" % (ls.get("policy_source"),))
        check("G01 n_candidates/n_trash 数值正确（1 沉底 0 trash）",
              ls.get("n_candidates") == 1 and ls.get("n_trash") == 0,
              "n_candidates=%r n_trash=%r" % (ls.get("n_candidates"),
                                              ls.get("n_trash")))
        # 零写盘：层不变 + trash 目录不出现 + _sink.jsonl 不出现（只读盘点）
        node = cg.get(nid)
        check("G01 节点内存层仍 knowledge",
              bool(node) and (node.get("frontmatter") or {}).get("layer") == "knowledge",
              "layer=%r" % (node.get("frontmatter") or {}).get("layer"))
        check("G01 节点磁盘层仍 knowledge（未搬迁）",
              disk_layer(root, nid) == "knowledge",
              "disk_layer=%r" % (disk_layer(root, nid),))
        check("G01 trash 目录未出现（零写盘）",
              trash_names(cg) == [],
              "trash=%r" % (trash_names(cg),))
        check("G01 _sink.jsonl 未出现（账本只在实修时写）",
              not os.path.exists(_sink.ledger_path(cg)),
              "ledger=%r" % (_sink.ledger_path(cg),))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_G02_auto_demote():
    """auto_sink=True ⇒ 节点确实降层到 contextual、台账 dry_run=False。"""
    tmp, root, cg, nid = make_candidate_root()
    try:
        lp = _scn.SustainLoop(cg, d=os.path.join(tmp, "sust"),
                              sink_interval=21600.0, auto_sink=True)
        check("G02 构造时传参 auto_sink 为 True",
              lp.auto_sink is True, "auto_sink=%r" % (lp.auto_sink,))
        lp._tick_sink()
        ls = lp.last_sink
        check("G02 台账 dry_run=False（实修轮）",
              ls.get("dry_run") is False and ls.get("auto_sink") is True,
              "dry_run=%r" % (ls.get("dry_run"),))
        check("G02 applied.demote 含该节点",
              nid in (ls.get("applied") or {}).get("demote", []),
              "applied=%r" % (ls.get("applied"),))
        node = cg.get(nid)
        check("G02 内存层降到 contextual",
              bool(node) and (node.get("frontmatter") or {}).get("layer") == "contextual",
              "layer=%r" % ((node.get("frontmatter") or {}).get("layer")))
        check("G02 磁盘层降到 contextual（文件真搬迁）",
              disk_layer(root, nid) == "contextual",
              "disk_layer=%r" % (disk_layer(root, nid),))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_G03_auto_trash():
    """auto_sink=True 且已降层、闲置超 trash_days ⇒ 进 trash + deletions_log。"""
    tmp = tempfile.mkdtemp(prefix="t13a-e2e-")
    root = os.path.join(tmp, "R")
    os.makedirs(root, exist_ok=True)
    cg = _mdcos.MdCGOS(root)
    try:
        nid = cg.add("t13a-e2e-进trash", "生效条件：端到端夹具。", layer="knowledge",
                     importance=0.2)
        seed(cg, nid, 200.0)                                  # 先沉底
        _sink.apply_demote(cg, ids=[nid], dry_run=False)      # 真实降层
        seed(cg, nid, 400.0, access_count=0)                  # 降层后再闲置超 180d
        lp = _scn.SustainLoop(cg, d=os.path.join(tmp, "sust"),
                              sink_interval=21600.0, auto_sink=True)
        lp._tick_sink()
        ls = lp.last_sink
        check("G03 applied.trash 含该节点",
              nid in (ls.get("applied") or {}).get("trash", []),
              "applied=%r" % (ls.get("applied"),))
        check("G03 原层文件已不在（knowledge/contextual 都无此 id 的 .md）",
              not any(disk_layer(os.path.join(root, lay), nid) is not None
                      for lay in ("knowledge", "contextual")),
              "disk_layer(trash)=%r"
              % (disk_layer(os.path.join(root, "trash"), nid),))
        check("G03 trash/<id>.md 已出现（文件被搬走）",
              nid + ".md" in trash_names(cg),
              "trash=%r" % (trash_names(cg),))
        dels = cg.deletions()
        dels_ids = [d.get("id") for d in dels]
        check("G03 deletions_log 有该节点记录",
              nid in dels_ids,
              "n_deletions=%d ids=%r" % (len(dels), dels_ids))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_G04_env_broken_policy():
    """env MDCG_LIFECYCLE_FILE 指向不存在路径 ⇒ 不抛、照常盘点、builtin 默认。"""
    tmp, root, cg, nid = make_candidate_root()
    old_env = os.environ.get(SINK_ENV)
    try:
        os.environ[SINK_ENV] = os.path.join(tmp, "no-such-policy.json")
        lp = _scn.SustainLoop(cg, d=os.path.join(tmp, "sust"),
                              sink_interval=21600.0)
        try:
            lp._tick_sink()
            no_throw = True
        except Exception as exc:                              # noqa: BLE001
            no_throw = False
            print("        env 坏策略路径下 _tick_sink 抛出：%s: %s"
                  % (type(exc).__name__, exc))
        check("G04 坏策略 env 下不抛异常",
              no_throw, "")
        ls = lp.last_sink
        check("G04 照常盘点出候选（n_candidates=1）",
              isinstance(ls, dict) and ls.get("n_candidates") == 1,
              "n_candidates=%r" % (ls.get("n_candidates"),) if isinstance(ls, dict) else "last_sink=%r" % (ls,))
        check("G04 policy_source='builtin'（文件失效回落内置）",
              ls.get("policy_source") == "builtin",
              "policy_source=%r" % (ls.get("policy_source"),))
        pol = _sink.load_policy()
        bd = _sink.BUILTIN_DEFAULTS
        check("G04 五键用内置默认（与 BUILTIN_DEFAULTS 一致）",
              all(pol.get(k) == bd.get(k)
                  for k in ("sink_days", "keep_access_count", "demote_layers",
                            "trash_days", "protected_importance")),
              "pol=%r" % ({k: pol.get(k) for k in
                           ("sink_days", "keep_access_count", "demote_layers",
                            "trash_days", "protected_importance")},))
    finally:
        if old_env is None:
            os.environ.pop(SINK_ENV, None)
        else:
            os.environ[SINK_ENV] = old_env
        shutil.rmtree(tmp, ignore_errors=True)


def case_G05_six_ticks_shape_intact():
    """既有六档读数形状不变：_tick_scrub 十一键仍在、六档名单顺序未动。"""
    tmp, root, cg, nid = make_candidate_root()
    try:
        lp = _scn.SustainLoop(cg, d=os.path.join(tmp, "sust"),
                              sink_interval=21600.0)
        lp._tick_scrub()                                      # 跑一轮既有档
        ls = lp.last_scrub
        need = ("t", "ok", "n_issues", "n_high_medium", "applied",
                "already_handled", "planned_dry_run", "checked_breakdown",
                "seed", "dry_run", "auto_scrub")
        check("G05 last_scrub 十一键形状未变",
              isinstance(ls, dict) and all(k in ls for k in need),
              "keys=%s" % (sorted(ls.keys()) if isinstance(ls, dict) else None,))
        names = [n for n, _ in _scn.TICK_INTERVAL_ATTRS]
        check("G05 TICK_INTERVAL_ATTRS 前六项名字/顺序一字未动",
              names[:6] == ["beat", "heal", "scrub", "evolve", "tidy", "sleep"],
              "前六=%r" % (names[:6],))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_G06_wrap_ticks_contains_sink():
    """_wrap_ticks 名单含新增档名 sink，包完仍可跑通。"""
    tmp, root, cg, nid = make_candidate_root()
    try:
        names = [n for n, _ in _scn.TICK_INTERVAL_ATTRS]
        check("G06 _wrap_ticks 名单含新增档名 sink",
              "sink" in names,
              "names=%r" % (names,))
        lp = _scn.SustainLoop(cg, d=os.path.join(tmp, "sust"),
                              sink_interval=21600.0, auto_sink=False)
        lp._wrap_ticks()
        check("G06 包装幂等标记已置位",
              getattr(lp, "_ticks_wrapped", False) is True,
              "wrapped=%r" % (getattr(lp, "_ticks_wrapped", None),))
        try:
            lp._tick_sink()                                   # 包装后的第七档
            sink_ok = True
        except Exception as exc:                              # noqa: BLE001
            sink_ok = False
            print("        包装后 _tick_sink 抛出：%s: %s"
                  % (type(exc).__name__, exc))
        check("G06 包装后的第七档仍可跑通并写台账",
              sink_ok and isinstance(lp.last_sink, dict)
              and lp.last_sink.get("n_candidates") == 1,
              "n_candidates=%r" % (lp.last_sink.get("n_candidates"),)
              if isinstance(lp.last_sink, dict) else "last_sink=%r" % (lp.last_sink,))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# 生效条件：按 G01..G06 顺序跑完全部工况；任一 case 抛异常即记为一次失败并带 traceback；恒不吞掉其余工况。
def run_cases():
    case_G01_default_readonly()
    case_G02_auto_demote()
    case_G03_auto_trash()
    case_G04_env_broken_policy()
    case_G05_six_ticks_shape_intact()
    case_G06_wrap_ticks_contains_sink()


# 生效条件：调用时跑完全部工况并打印形如「t13a sink e2e：N 通过，0 失败」的汇总行（有失败则附失败项名），返回 0 当且仅当 FAIL==0；捕获 run_cases 抛出的任何异常并计一次失败。
def main():
    print("t13a sink e2e：第七档 sink tick 端到端守卫")
    print("-" * 64)
    try:
        run_cases()
    except Exception as exc:                                  # noqa: BLE001
        check("运行期无未捕获异常", False,
              "%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()))
    print("-" * 64)
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("t13a sink e2e：%d 通过，%d 失败" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())