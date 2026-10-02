# -*- coding: utf-8 -*-
"""md_cg · 变更单回滚面守卫（三档自治 · 设计 v0.2 §四/§十一 · 批次③）

覆盖（设计 §十一 验收判据在本批的落点）：
  · **回滚实测**（§十一 明文「每种破坏性动作各演一次『落 → 回滚 → 逐字节比对
    前像』」）：C 改写（含「目标被覆写后回滚」——第三方改动被保留）· B 合并
    （聚合行定向剥离）· D 删除（trash + 删除清单 restore）三条各一演，全部
    经**回滚命令串实测演练**（subprocess 执行字段里的命令串，不是进程内直调）；
  · **红项面**（§十一）：回滚后不得残留——索引条目 / 边 / 聚合行三面与前像
    时点影响面逐位对拍（`residual` 三键 + 逐字节比对）；
  · **前像=执行时点**（§四 明文）：C 场景把「提议→accept 之间目标被第三方
    覆写」演出来——回滚后盘面 == 执行前一刻（第三方版本），**不是**提议时点
    版本；T 组另有「最旧快照」判别场景（预置一张提议时点旧快照，实现若取最旧
    即转红）；
  · **受保护节点既有快照行为一字不变**（约束）：P 组把 `protect.snapshot()` /
    `guard_write|guard_forget` 的既有读数（快照数、审计 action、命名形态）钉死，
    并以定点变异（把前像挂钩塞进 `_allow`）证明这组判据有判别力；
  · 结构性单点：前像拍摄入口（`protect.snapshot_preimage`）、执行时点补全
    （`autonomy_modes.mutation_executed`）、回滚命令构造（`rollback.command_for`）
    全仓唯一；
  · 边界 fail-closed：非 dict 载荷 / 缺前像 / 未知动作类 / 前像文件缺失 /
    未执行（reject）变更单，一律拒绝回滚（不猜一个前像）。

**定点变异自证（`--mutate`，与 `md_cg/test_neg_condition_hits.py` 同口径）**：
表内每项 = (说明, 目标, 锚点原文, 替换文, 预期红项数)。锚点须**逐字**出现在
目标源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。红项数与实测**逐一相符**
才算通过——不符即 FAIL（多红=断言越界、少红=该判据无判别力）。
**基线源＝工作区源码 + 本表，绝不取 `git HEAD`**（本仓已有两次教训：基线绑
提交即失效）。

沙箱（硬约束）：一切读写都在 tempfile.mkdtemp 内（含 MDCG_AUX_ROOT / 主密钥 /
policy——crypto 在导入期求值 MASTER_FILE，故必须在任何 md_cg 子模块 import
**之前**设好）；跑完 rmtree。**绝不碰在役数据根**。回滚命令串实测演练走
subprocess（shlex 切分命令串、`python` 令牌换成本进程解释器、shell=False、
显式 UTF-8）——演练的是**字段里的那条命令串本身**。

运行：
  python -X utf8 -m md_cg.test_mutation_rollback          # 正常跑
  python -X utf8 -m md_cg.test_mutation_rollback --mutate # 定点变异自证
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

# ---- 沙箱：必须在任何 md_cg 子模块 import 之前 ------------------------------
_SANDBOX = tempfile.mkdtemp(prefix="mutation_rollback_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SANDBOX
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)
_OLD_POLICY = os.environ.pop("MDCG_POLICY_FILE", None)

from . import autonomy_modes, forgetting, nodefile, protect, rollback  # noqa: E402
from . import writepipe                                             # noqa: E402
from . import mdcos                                                 # noqa: E402
from .mdcos import MdCGOS                                           # noqa: E402

_ENV_MODE = autonomy_modes.AUTONOMY_ENV_KEYS["mode"]

_PASS = []
_FAIL = []
_RUN = [0]


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _policy():
    path = os.path.join(_SANDBOX, "policy.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"forbidden": ["FORBIDDEN_WORD"], "required": ["PASSED"]}, f)
    os.environ["MDCG_POLICY_FILE"] = path
    return path


def _lib(tag="lib"):
    """独立合成库（每轮独立子根：变异模式连跑多轮，共用目录会读到上一轮盘面）。"""
    return MdCGOS(os.path.join(_SANDBOX, "%s_r%d" % (tag, _RUN[0])), autoflush=0)


@contextlib.contextmanager
def _mode(m):
    old = os.environ.get(_ENV_MODE)
    os.environ[_ENV_MODE] = m
    try:
        yield m
    finally:
        if old is None:
            os.environ.pop(_ENV_MODE, None)
        else:
            os.environ[_ENV_MODE] = old


def _pipe():
    return writepipe.install_default_gates(writepipe.WritePipeline())


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pre_path(cg, rel):
    return os.path.join(cg.root, str(rel).replace("/", os.sep))


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _disk_path(cg, nid):
    return os.path.join(cg.root, cg.index["nodes"][nid]["path"])


def _audit_rows(cg):
    p = os.path.join(cg.root, protect.AUDIT_FILE)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _run_command(cmd):
    """**实测演练回滚命令串**：切分命令串 → `python` 换本进程解释器 → subprocess。

    shlex 用 posix=False：Windows 路径里的反斜杠在 posix 模式会被当转义字符
    （把 `C:\\Users\\...` 拆坏）；posix=False 下引号原样保留，故手工剥引号。
    只替换首令牌 `python`（守卫进程内的解释器才可靠——与命令串里写的 `python`
    同义）；其余令牌逐字来自字段，不重写（演练的是字段里的那条串本身）。
    """
    argv = shlex.split(cmd, posix=False)
    argv = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] == '"' else a for a in argv]
    if not argv:
        # 命令串为空（载荷缺 rollback——变异/未执行场景）：如实报失败体，
        # 由断言判红（不抛异常打断链条）。
        return {"rc": -1, "out": "", "err": "empty rollback command", "json": None}
    if argv[0] == "python":
        argv[0] = sys.executable
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_repo_root(),
                       env=dict(os.environ, PYTHONUTF8="1"))
    out_json = None
    try:
        out_json = json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception:
        out_json = None
    return {"rc": p.returncode, "out": p.stdout or "", "err": p.stderr or "",
            "json": out_json}


def _refresh(cg):
    """CLI 子进程回滚后刷新父进程索引（读面代际感知：子进程经 _index_log
    增量日志落盘，重载后父进程才看见「节点回来了/条目换了」）。"""
    cg._maybe_reload_index()


BODY = ("# 功能名：部署面端口约定\n"
        "# 生效条件：载体/位置：prod 集群；时间：2026-09-30 起；方法：部署清单核对；约束：无\n"
        "# 子功能：登记各服务监听端口\n"
        "# 执行：核对 manifest 的 ports 段\n"
        "# 验证方式：test\n"
        "# 不适用条件：无\n"
        "\n网关监听端口 8080/HTTP；管理面监听端口 8081/HTTP；"
        "指标面监听端口 %s/HTTP；日志面监听端口 9091/HTTP\n")
PLAIN = "PASSED 探针正文 %s"


def _snapshot_entry(cg, nid, rel):
    """按快照文件重算索引条目（与 _node_entry 同源）——回滚后索引对拍的基准。

    path 用**节点自身的盘面路径**：`_node_entry` 的 path/bucket 从文件位置派生
    （与 fm/content 无关），快照文件在 `_protected_history/` 下、派生出的
    path/bucket 是快照自己的——对拍两边的 path 必须同为节点盘面位置，其余
    字段（tags/importance/edges/created_at…）才由 fm/content 决定。
    rel 为空（前像缺失——变异场景）时返回 None，由调用方判 False（不抛）。
    """
    if not rel:
        return None
    p = _disk_path(cg, nid)
    with open(_pre_path(cg, rel), encoding="utf-8") as f:
        fm, c = nodefile.loads(f.read())
    return cg._node_entry(p, str(fm.get("layer") or "knowledge"), fm, c)


# =============================================================== P 组：前像面
def g_p():
    print("== P 组：执行时点前像面（同面推广 · 受保护既有行为一字不变）==")
    _policy()
    cg = _lib("pre")
    cg.add("p_1", PLAIN % "甲", layer="knowledge", verification_basis="test")
    cg.flush()
    snap1 = protect.snapshot_preimage(cg, "p_1", action="C", pid="prop_probe")
    ok(bool(snap1)
       and re.match(r"^_protected_history/p_1/\d{8}-\d{6}-\d{6}\.md$", snap1),
       "P snapshot_preimage 返回同面路径（_protected_history/<id>/<ts>-<微秒>.md）",
       snap1)
    sp = _pre_path(cg, snap1)
    dp = _disk_path(cg, "p_1")
    ok(os.path.isfile(sp) and _bytes(sp) == _bytes(dp),
       "P 前像与节点盘面逐字节相同（拍的就是执行前一刻）")
    fm_s, c_s = nodefile.loads(open(sp, encoding="utf-8").read())
    ok(fm_s.get("id") == "p_1" and c_s == cg.get("p_1")["content"],
       "P 前像与 snapshot 同格式（nodefile 可解析、正文可读回）")
    rows = [r for r in _audit_rows(cg)
            if r.get("action") == "preimage" and r.get("node_id") == "p_1"]
    ok(len(rows) == 1 and "C" in str(rows[0].get("reason"))
       and "prop_probe" in str(rows[0].get("reason")),
       "P 前像审计 action=preimage 且 reason 交代动作类/pid", rows[:1])
    # 同秒两次前像不互踩（微秒后缀）
    cg.add("p_1", PLAIN % "乙", layer="knowledge", verification_basis="test")
    snap2 = protect.snapshot_preimage(cg, "p_1", action="C", pid="prop_probe2")
    ok(bool(snap1) and bool(snap2) and snap1 != snap2
       and os.path.isfile(_pre_path(cg, snap1)) and os.path.isfile(_pre_path(cg, snap2)),
       "P 同一节点同秒两次前像=两个文件（不互踩，早先的回滚句柄不被覆盖）",
       (snap1, snap2))
    ok(_bytes(_pre_path(cg, snap2)) != _bytes(_pre_path(cg, snap1)),
       "P 两张前像各自拍住各自时点的盘面（中间那次写入进了第二张）")
    # 既有 snapshot() 形态钉（普通节点）
    s0 = protect.snapshot(cg, "p_1")
    ok(bool(s0) and re.match(r"^_protected_history/p_1/\d{8}-\d{6}\.md$", s0),
       "P 既有 protect.snapshot 命名形态不变（秒级名，无微秒后缀）", s0)
    rows_s = [r for r in _audit_rows(cg)
              if r.get("action") == "snapshot" and r.get("node_id") == "p_1"]
    ok(len(rows_s) == 1 and str(rows_s[0].get("reason")).startswith("显式快照（"),
       "P 既有 snapshot 审计形态不变（action=snapshot、reason「显式快照（…）」）",
       rows_s[:1])
    cg.close()

    # 受保护节点：guard 路径既有行为（不经执行桥）逐条钉死
    cg = _lib("prot")
    cg.add("p_s", PLAIN % "自我版", layer="self", verification_basis="test")
    cg.flush()
    protect.guard_write(cg, "p_s", override=True, actor="guard-probe")
    hist = protect.history(cg, "p_s")
    acts = sorted(r.get("action") for r in _audit_rows(cg)
                  if r.get("node_id") == "p_s")
    ok(len(hist) == 1, "P guard_write override：快照恰好 1 张（既有行为一字不变）",
       hist)
    ok(acts == ["override_write", "snapshot"],
       "P guard_write override：审计面 snapshot+override_write 各一条", acts)
    try:
        protect.guard_forget(cg, "p_s", override=True, actor="guard-probe")
        got_f = True
    except Exception as exc:                            # noqa: BLE001
        got_f = "exc=%s" % type(exc).__name__
    acts2 = sorted(r.get("action") for r in _audit_rows(cg)
                   if r.get("node_id") == "p_s")
    # 文件数上限 2、下限 1：guard 的秒级名在**同秒**两次看守间会互相覆盖
    # （探针实测：同秒二次 snapshot 返回同一路径）——这是既有行为，判据按
    # 审计面钉（两次 snapshot 各留一条，确定性），文件数只钉区间。
    ok(got_f is True and 1 <= len(protect.history(cg, "p_s")) <= 2
       and acts2 == ["override_forget", "override_write", "snapshot", "snapshot"],
       "P guard_forget override：快照 + override_forget 留痕（既有口径，"
       "同秒覆盖属既有行为）", (got_f, protect.history(cg, "p_s"), acts2))
    cg.close()

    # 执行桥对受保护节点（override 载荷）：前像另拍 + guard 快照仍在
    with _mode("confirm"):
        cg = _lib("bridge_prot")
        cg.add("p_b", PLAIN % "自我版", layer="self", verification_basis="test")
        cg.flush()
        pay = autonomy_modes.mutation_payload(
            "C", "p_b", after=PLAIN % "新自我版", reason="守卫：执行桥+受保护",
            primitive="add", meta={"override": True})
        pr = autonomy_modes.propose_mutation(cg, "C", "p_b", payload=pay,
                                             layer="self", info=True)
        r = cg.review_decide(pr["pid"], "accept", reason="守卫")
        m = r.get("mutation") or {}
        ok(r.get("ok") is True and bool(m.get("before")),
           "P 执行桥 accept（受保护+override）成功且前像在案",
           {k: r.get(k) for k in ("ok", "error")})
        hist2 = protect.history(cg, "p_b")
        micro = [h for h in hist2 if re.search(r"\d{8}-\d{6}-\d{6}\.md$", h)]
        plain = [h for h in hist2 if re.search(r"\d{8}-\d{6}\.md$", h)]
        ok(len(hist2) == 2 and len(micro) == 1 and len(plain) == 1,
           "P 执行桥对受保护节点：前像（微秒名）另拍、guard 快照（秒级名）原样"
           "仍在（推广不破坏既有）", hist2)
        rows_p = [rr for rr in _audit_rows(cg) if rr.get("node_id") == "p_b"]
        ok(sorted(set(str(rr.get("action")) for rr in rows_p))
           == ["override_write", "preimage", "snapshot"],
           "P 审计面并存 preimage + snapshot + override_write（三类各司其职）",
           sorted(r.get("action") for r in rows_p))
        cg.close()


# =============================================================== Q 组：C 改写
def g_q():
    print("== Q 组：C 改写回滚（目标被覆写后回滚 → 执行时点前像）==")
    _policy()
    with _mode("confirm"):
        cg = _lib("c")
        cg.add("q_1", PLAIN % "初版", layer="knowledge",
               verification_basis="test",
               edges=[{"target": "q_p", "relation_type": "part_of"}])
        cg.add("q_p", PLAIN % "父", layer="knowledge",
               verification_basis="test")
        cg.flush()
        pipe = _pipe()
        o1 = pipe.execute(cg, {"content_kind": "text", "content": PLAIN % "改写版",
                               "layer": "knowledge", "node_id": "q_1"})
        ok(o1.get("moved_to") == "review_queue" and bool(o1.get("pid")),
           "Q 写链出单（C 改写）", {k: o1.get(k) for k in ("moved_to", "pid")})
        # 提议→accept 之间：第三方覆写（带同一条边）——前像必须=此刻
        cg.add("q_1", PLAIN % "第三方版", layer="knowledge",
               verification_basis="test",
               edges=[{"target": "q_p", "relation_type": "part_of"}])
        third_bytes = _bytes(_disk_path(cg, "q_1"))
        d = cg.review_decide(o1["pid"], "accept", reason="守卫")
        m = d.get("mutation") or {}
        ok(d.get("ok") is True and bool(m.get("before")),
           "Q accept 执行且执行记录带前像", {k: d.get(k) for k in ("ok", "error")})
        pre_p = _pre_path(cg, m.get("before")) if m.get("before") else None
        ok(bool(pre_p) and os.path.isfile(pre_p) and _bytes(pre_p) == third_bytes,
           "Q 前像=**执行时点**（=第三方覆写后的盘面，逐字节）")
        ok((((m.get("impact") or {}).get("edges") or {}).get("parents")
            == ["q_p"]),
           "Q 影响面·边 = 执行时点读数（part_of 父边在案）",
           (m.get("impact") or {}).get("edges"))
        # —— 落 ——：执行后正文=改写版、边被 add 全量重建清空（既有行为）
        ok("改写版" in cg.get("q_1")["content"]
           and "第三方版" not in cg.get("q_1")["content"],
           "Q 落：accept 覆写生效（正文已换）")
        ok((((rollback.collect_impact(cg, "q_1").get("edges")) or {})
            .get("parents") or []) == [],
           "Q 落：C 覆写的 add 全量重建把声明式边清空（既有行为，回滚须恢复）")
        # —— 回滚（进程内统一入口；父进程内的变异可打红本段判据）——
        rr = rollback.rollback_mutation(cg, m, reason="Q")
        ok(rr.get("ok") is True, "Q 回滚：统一入口 ok",
           {k: rr.get(k) for k in ("ok", "error")})
        ok(rr.get("bytes_equal_preimage") is True,
           "Q 回滚：逐字节比对前像 = True", rr.get("bytes_equal_preimage"))
        res = rr.get("residual") or {}
        ok(res.get("agg_lines_restored") is True
           and res.get("edges_restored") is True
           and res.get("index_restored") is True,
           "Q 回滚：残留核对三面全回（索引/边/聚合行）", res)
        ok(_bytes(_disk_path(cg, "q_1")) == third_bytes,
           "Q 回滚后盘面逐字节 == 前像（第三方版本字节）")
        ok("初版" not in cg.get("q_1")["content"],
           "Q 撤销的是本变更（未一并抹掉第三方改动，也没回到提议时点初版）")
        e_now = cg.index["nodes"]["q_1"]
        e_ref = _snapshot_entry(cg, "q_1", m.get("before"))
        ok(e_now == e_ref,
           "Q 索引不残留：回滚后条目 == 前像重算条目（逐位）", (e_now, e_ref))
        ok(rollback.collect_impact(cg, "q_1")["edges"]["parents"] == ["q_p"],
           "Q 边恢复：回滚后 part_of 父边回案（边面无本变更残留）")
        # —— 命令串实测演练（CLI subprocess；此刻为幂等重放）——
        got = _run_command(m.get("rollback") or "")
        _refresh(cg)
        out = got.get("json") or {}
        ok(got["rc"] == 0 and out.get("ok") is True
           and out.get("bytes_equal_preimage") is True,
           "Q 回滚命令串实测演练：rc=0、ok=True、逐字节比对前像=True",
           {"rc": got["rc"], "err": (got.get("err") or "")[-160:]})
        ok(_bytes(_disk_path(cg, "q_1")) == third_bytes,
           "Q 命令串演练后盘面仍 == 前像（独立进程回滚一致）")
        cg.close()


# =============================================================== R 组：B 合并
def g_r():
    print("== R 组：B 合并回滚（聚合行定向剥离）==")
    _policy()
    with _mode("confirm"):
        cg = _lib("m")
        cg.add("r_t", BODY % "8081", layer="knowledge",
               verification_basis="test")
        cg.flush()
        pre_bytes = _bytes(_disk_path(cg, "r_t"))
        r1 = cg.remember_gated("r_n", BODY % "9595", layer="knowledge")
        ok(r1.get("verdict") == "CONFIRM" and bool(r1.get("pid")),
           "R 出单（B 合并）", r1.get("verdict"))
        d = cg.review_decide(r1["pid"], "accept", reason="守卫")
        m = d.get("mutation") or {}
        ok(d.get("ok") is True, "R accept 执行")
        cur = cg.get("r_t")
        fm1 = cur["frontmatter"]
        ok(forgetting.AGG_MARK in cur["content"]
           and fm1.get("merge_count") == 1,
           "R 落：聚合行已追加、merge_count=1（既有原语落盘）")
        ok((m.get("impact") or {}).get("agg_lines") == [],
           "R 影响面：执行时点无聚合行（agg_lines=[]）",
           (m.get("impact") or {}).get("agg_lines"))
        # —— 回滚（进程内统一入口：定向剥离）——
        rr = rollback.rollback_mutation(cg, m, reason="R")
        ok(rr.get("ok") is True and rr.get("method") == "strip_aggregate_lines"
           and rr.get("stripped_ok") is True and bool(rr.get("removed_lines")),
           "R 回滚走**定向剥离**且剥离精确（stripped_ok、removed 非空）",
           {k: rr.get(k) for k in ("ok", "method", "stripped_ok",
                                   "removed_lines")})
        ok(rr.get("bytes_equal_preimage") is True,
           "R 回滚：逐字节比对前像 = True")
        ok(_bytes(_disk_path(cg, "r_t")) == pre_bytes,
           "R 回滚后盘面逐字节 == 前像（合并前正文）")
        cur2 = cg.get("r_t")
        ok(forgetting.AGG_MARK not in cur2["content"],
           "R 聚合行不残留（本次合并的聚合行已剥净）")
        ok(cur2["frontmatter"].get("merge_count") in (None, 0)
           and float(cur2["frontmatter"].get("importance") or 0) == 0.5,
           "R fm 回退：merge_count/importance 回前像值（全量取前像）",
           {k: cur2["frontmatter"].get(k) for k in ("merge_count", "importance")})
        ok((rr.get("residual") or {}).get("agg_lines_restored") is True,
           "R 残留核对：聚合行面对齐前像时点读数",
           (rr.get("residual") or {}))
        # —— 命令串实测演练（CLI；幂等重放）——
        got = _run_command(m.get("rollback") or "")
        _refresh(cg)
        out = got.get("json") or {}
        ok(got["rc"] == 0 and out.get("ok") is True
           and out.get("bytes_equal_preimage") is True
           and _bytes(_disk_path(cg, "r_t")) == pre_bytes,
           "R 回滚命令串实测演练：rc=0、ok=True、盘面仍 == 前像",
           {"rc": got["rc"], "err": (got.get("err") or "")[-160:]})
        cg.close()


# =============================================================== S 组：D 删除
def g_s():
    print("== S 组：D 删除回滚（trash + 删除清单 restore 接进统一口径）==")
    _policy()
    with _mode("confirm"):
        cg = _lib("d")
        cg.add("s_1", PLAIN % "初版", layer="knowledge",
               verification_basis="test", tags=["t1"], importance=0.62)
        cg.flush()
        pre_bytes = _bytes(_disk_path(cg, "s_1"))
        r1 = cg.forget_gated("s_1", reason="守卫删除")
        ok(r1.get("moved_to") == "review_queue" and bool(r1.get("pid")),
           "S 出单（D 删除）", {k: r1.get(k) for k in ("moved_to", "pid")})
        d = cg.review_decide(r1["pid"], "accept", reason="守卫")
        m = d.get("mutation") or {}
        ok(d.get("ok") is True and cg.get("s_1") is None
           and cg.is_tombstoned("s_1"),
           "S 落：软删生效（节点离位 + 删除清单在案）")
        ok(os.path.isfile(os.path.join(cg.root, "trash", "s_1.md")),
           "S trash 原件在案（软删=移动，非销毁）")
        # —— 回滚（进程内统一入口：restore + 前像校准）——
        rr = rollback.rollback_mutation(cg, m, reason="S")
        ok(rr.get("ok") is True, "S 回滚：统一入口 ok",
           {k: rr.get(k) for k in ("ok", "error")})
        ok(rr.get("calibrated") is True
           and rr.get("restore_bytes_equal") is False,
           "S 读数如实：restore 原样输出与快照有字节差（探针实测多 "
           "sensitivity:null 键）→ 已按前像校准（不假装 restore 逐字节）",
           {k: rr.get(k) for k in ("calibrated", "restore_bytes_equal")})
        ok(rr.get("bytes_equal_preimage") is True
           and _bytes(_disk_path(cg, "s_1")) == pre_bytes,
           "S 回滚后盘面逐字节 == 前像")
        ok(cg.get("s_1") is not None
           and (PLAIN % "初版") in (cg.get("s_1")["content"] or ""),
           "S 节点复位（读面可见、正文回前像；盘面逐字节已由上一断言钉死）")
        res = rr.get("residual") or {}
        ok(res.get("index_restored") is True
           and res.get("edges_restored") is True
           and res.get("agg_lines_restored") is True,
           "S 残留核对：索引/边/聚合行三面全回（索引条目 present/path 复位）", res)
        # —— 命令串实测演练（CLI；幂等重放走 replayed 分支）——
        got = _run_command(m.get("rollback") or "")
        _refresh(cg)
        out = got.get("json") or {}
        ok(got["rc"] == 0 and out.get("ok") is True
           and out.get("replayed") is True
           and _bytes(_disk_path(cg, "s_1")) == pre_bytes,
           "S 回滚命令串实测演练：rc=0、幂等重放（replayed=True）、盘面仍 == 前像",
           {"rc": got["rc"], "err": (got.get("err") or "")[-160:]})
        cg.close()


# =============================================================== T 组：单点/边界/时点
def g_t():
    print("== T 组：单点结构 · 边界 fail-closed · 时点判别 ==")
    # 单点：前像拍摄入口全仓唯一（protect 定义 + rollback 调用）
    hits = []
    for dirpath, dirnames, filenames in os.walk(_repo_root()):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", "node_modules",
                                    ".venv", "target", "lib")]
        for fn in filenames:
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue          # 生产码单点：测试/守卫自身的调用与字面量不算第二实现
            p = os.path.join(dirpath, fn)
            src = open(p, encoding="utf-8", errors="replace").read()
            if "snapshot_preimage(" in src:
                hits.append(os.path.relpath(p, _repo_root()).replace("\\", "/"))
    ok(sorted(hits) == ["md_cg/protect.py", "md_cg/rollback.py"],
       "T 前像拍摄入口单点（snapshot_preimage 只出现在 protect 定义 + rollback 调用）",
       hits)
    hits2 = []
    for dirpath, dirnames, filenames in os.walk(_repo_root()):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", "node_modules",
                                    ".venv", "target", "lib")]
        for fn in filenames:
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue          # 同上：只看生产码
            p = os.path.join(dirpath, fn)
            src = open(p, encoding="utf-8", errors="replace").read()
            if "mutation_executed(" in src:
                hits2.append(os.path.relpath(p, _repo_root()).replace("\\", "/"))
    ok(sorted(hits2) == ["md_cg/autonomy_modes.py", "md_cg/mdcos.py"],
       "T 执行时点补全单点（mutation_executed 只在 autonomy_modes 定义 + mdcos 调用）",
       hits2)
    cmd = rollback.command_for("/tmp/x root", "prop_abc")
    ok(isinstance(cmd, str) and "md_cg.rollback_cli" in cmd and "utf8" in cmd
       and '--root "/tmp/x root"' in cmd and "--pid prop_abc" in cmd,
       "T 回滚命令构造单点（形态含 rollback_cli/utf8/引号包 root/pid）", cmd)
    # 边界 fail-closed
    r = rollback.rollback_mutation(None, None)
    ok(r.get("ok") is False and r.get("error") == "mutation_missing",
       "T 非 dict 载荷 fail-closed（mutation_missing）", r)
    r = rollback.rollback_mutation(None, {"action": "C", "target": "x"})
    ok(r.get("ok") is False and r.get("error") == "rollback_gap"
       and bool(r.get("hint")),
       "T 缺前像 fail-closed（rollback_gap：不许凭猜测出来源）", r)
    r = rollback.rollback_mutation(None, {"action": "E", "target": "x",
                                          "before": "_protected_history/x/1.md"})
    ok(r.get("ok") is False and r.get("error") == "rollback_action_unknown",
       "T 未知动作类 fail-closed（E 分数类不属本批）", r)
    # 时点判别场景：预置一张「提议时点」旧快照（手工写：初版字节），
    # 实现若取最旧快照（=提议时点）即回滚到初版 → 本组断言转红。
    with _mode("confirm"):
        cg = _lib("point")
        cg.add("t_1", PLAIN % "初版", layer="knowledge",
               verification_basis="test")
        cg.flush()
        old_dir = os.path.join(cg.root, protect.HISTORY_DIR, "t_1")
        os.makedirs(old_dir, exist_ok=True)
        old_rel = "_protected_history/t_1/20000101-000000.md"
        with open(_pre_path(cg, old_rel), "wb") as f:
            f.write(_bytes(_disk_path(cg, "t_1")))      # 提议时点版本（初版）
        pay = autonomy_modes.mutation_payload("C", "t_1",
                                              after=PLAIN % "改写版",
                                              reason="时点判别", primitive="add")
        pr = autonomy_modes.propose_mutation(cg, "C", "t_1", payload=pay,
                                             layer="knowledge", info=True)
        cg.add("t_1", PLAIN % "第三方版", layer="knowledge",
               verification_basis="test")
        third_bytes = _bytes(_disk_path(cg, "t_1"))
        d = cg.review_decide(pr["pid"], "accept", reason="守卫")
        m = d.get("mutation") or {}
        ok((m.get("before") or "") != old_rel,
           "T 执行记录前像**不是**最旧的那张（新拍的执行时点快照）",
           m.get("before"))
        rr = rollback.rollback_mutation(cg, m, reason="T 时点判别")
        ok(rr.get("ok") is True and rr.get("bytes_equal_preimage") is True,
           "T 时点判别场景回滚成功且逐字节==执行时点前像",
           {k: rr.get(k) for k in ("ok", "bytes_equal_preimage")})
        ok(_bytes(_disk_path(cg, "t_1")) == third_bytes
           and _bytes(_disk_path(cg, "t_1"))
           != _bytes(_pre_path(cg, old_rel)),
           "T 回滚到**执行时点**（第三方版）而非最旧快照（初版）——"
           "「前像=执行时点」有判别力")
        cg.close()
    # 未执行的变更单不可回滚（reject 后 CLI fail-closed）
    with _mode("confirm"):
        cg = _lib("unexec")
        cg.add("u_1", PLAIN % "甲", layer="knowledge",
               verification_basis="test")
        cg.flush()
        pay = autonomy_modes.mutation_payload("C", "u_1", after=PLAIN % "乙",
                                              reason="未执行", primitive="add")
        pr = autonomy_modes.propose_mutation(cg, "C", "u_1", payload=pay,
                                             layer="knowledge", info=True)
        cg.review_decide(pr["pid"], "reject", reason="守卫：不执行")
        got = _run_command(rollback.command_for(cg.root, pr["pid"]))
        out = got.get("json") or {}
        ok(got["rc"] == 1 and out.get("ok") is False
           and out.get("error") == "decision_not_found",
           "T 未执行（reject）的变更单：回滚命令 fail-closed（无前像可依）",
           {"rc": got["rc"], "json": out})
        cg.close()


_GROUPS = (g_p, g_q, g_r, g_s, g_t)


def _run_groups():
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        g()
    return len(_FAIL)


# =============================================================== 定点变异自证
# 表内每项 = (说明, 目标, 锚点原文, 替换文, 预期红项数)。锚点须**逐字**出现在
# 目标函数源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。基线源＝**工作区
# 源码 + 本表**（绝不取 git HEAD——基线绑提交即失效，本仓已有两次教训）。
_SRC_MUTATIONS = (
    # ① 执行桥不拍前像——回滚句柄不存在（回滚命令 read 不到 before、回滚
    #   gap；影响面/命令串亦缺）。红 30（实测 2026-10-02）：P 组 3 条（受保护
    #   面执行桥判据）+ Q 组 12 条 + R 组 7 条 + S 组 6 条 + T 组 2 条——三条
    #   动作的「前像在案/回滚成功/逐字节/残留/命令串演练」判据整体转红。
    ("执行桥不拍前像（执行时点前像整支失效）", "cls", mdcos.MdCGOS,
     "_mutation_execute",
     '            pre = _rb.preimage(self, act, tgt, pid=item.get("pid"),\n'
     '                               reason="变更单执行时点前像（%s→%s，pid=%s）"\n'
     '                                      % (act, tgt, item.get("pid") or "?"))',
     '            pre = None', 30),
    # ② 前像取最旧快照（=「提议时点」错误形态）——T 组时点判别场景须转红。
    #   红 2（实测）：T「前像不是最旧那张」+ T「回滚到执行时点（非最旧）」；
    #   其余场景无预置旧快照（_hist 空 → 照旧新拍），语义相符。
    ("前像取最旧快照（提议时点语义回归）", "mod", rollback, "preimage",
     '    rel = protect.snapshot_preimage(cg, target, action=act, pid=pid,\n'
     '                                    reason=reason)',
     '    _hist = protect.history(cg, target)\n'
     '    rel = _hist[0] if _hist else protect.snapshot_preimage(\n'
     '        cg, target, action=act, pid=pid, reason=reason)', 2),
    # ③ 定向剥离恒等空转——聚合行剥离失效（回滚仍以快照正文兜底，故逐字节
    #   不断；剥离读数与 fm 回退判据须红）。红 1（实测）：R「走定向剥离且剥离
    #   精确」——stripped_ok False/method=preimage/removed 空 三条件同挂一条判据。
    ("定向剥离恒等空转（strip_aggregate_lines 不剥）", "mod", rollback,
     "strip_aggregate_lines",
     '    if not ref or not text.startswith(ref):\n        return text, []',
     '    return text, []', 1),
    # ④ 回滚不落盘（_land 空转）——回滚「报成功了」但盘面没回（汇报不实）。
    #   红 13（实测）：Q 5 条（逐字节/残留/盘面/索引对拍/边恢复）+ R 4 条
    #   + S 4 条（逐字节/复位/残留/命令串演练后盘面）。
    ("回滚不落盘（_land 空转）", "mod", rollback, "_land",
     '    cg._write_node(node_id, path, fm, content)', '    return', 13),
    # ⑤ D 回滚不做前像校准——restore 的字节差（sensitivity:null）留在盘面。
    #   红 2（实测）：S「读数如实（calibrated/restore_bytes_equal）」+ S
    #   「回滚后盘面逐字节==前像」。
    ("D 回滚不做前像校准（restore 字节差残留）", "mod", rollback,
     "_rollback_delete",
     '    if not restore_bytes_equal:', '    if False:', 2),
    # ⑥ 前像挂钩被塞进受保护路径（_allow 多拍一张）——受保护节点既有快照行为
    #   被污染。红 4（实测）：P「guard_write 快照恰好 1 张」+ P「审计面各一条」
    #   + P「guard_forget 同款口径」+ P「执行桥场景 history 恰 2 条（微秒/秒级
    #   各一）」——四条的读数都被多出的一张打乱。
    ("受保护路径被污染（_allow 多拍前像）", "mod", protect, "_allow",
     '    snap = snapshot(cg, node_id)',
     '    snap = snapshot(cg, node_id)\n'
     '    snapshot_preimage(cg, node_id, action="guard", pid=action)', 4),
    # ⑦ 前像文件名去微秒（同秒互踩）——同一节点同秒两次前像互相覆盖，
    #   早先的回滚句柄被踩掉。红 4（实测）：P「同秒两次=两个文件」+ P「两张
    #   各拍各自时点」+ P「既有 snapshot 命名形态不变」（微秒名与秒级名的
    #   判别被打乱）+ P「执行桥场景微秒/秒级各一条」。
    ("前像名去微秒（同秒互踩）", "mod", protect, "snapshot_preimage",
     '    ts = (time.strftime("%Y%m%d-%H%M%S", time.localtime())\n'
     '          + "-%06d" % (time.time_ns() // 1000 % 1000000))',
     '    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())', 4),
    # ⑧ 执行记录不落 mutation（_record_decision 摘除）——回滚 CLI 读不到载荷
    #   （「回滚命令」的读取源断链）。红 3（实测）：Q/R/S 三条「命令串实测
    #   演练」——CLI 报 decision_not_found 非零退出；进程内入口不受影响
    #   （直接持有载荷），语义相符。
    ("执行记录不落 mutation（rec['mutation'] 摘除）", "cls", mdcos.MdCGOS,
     "_record_decision",
     '        _mut = result.get("mutation")\n'
     '        if isinstance(_mut, dict):\n'
     '            rec["mutation"] = _mut',
     '        _mut = result.get("mutation")\n'
     '        if False:\n'
     '            rec["mutation"] = _mut', 3),
)


def _fn_src(target):
    kind, owner, name = target
    if kind == "attr":
        return inspect.getsource(owner)
    return inspect.getsource(getattr(owner, name))


def _strip_indent(text, n):
    if not n:
        return text
    out = []
    for line in text.split("\n"):
        if line[:n].strip() == "":
            out.append(line[n:])
        else:
            out.append(line.lstrip())
    return "\n".join(out)


def _anchor_check():
    bad = []
    for name, _kind, owner, fname, old, _new, _n in _SRC_MUTATIONS:
        if old not in _fn_src((_kind, owner, fname)):
            bad.append("变异锚点缺失：%r @%s.%s" % (old[:40], owner.__name__, fname))
    return bad


@contextlib.contextmanager
def _patched(target, old, new):
    kind, owner, name = target
    src = _fn_src(target)
    cut = len(src) - len(src.lstrip(" "))
    src2 = _strip_indent(src, cut)
    old2 = _strip_indent(old, cut)
    new2 = _strip_indent(new, cut)
    if old2 not in src2:
        raise AssertionError("变异锚点在去缩进后仍不匹配：%r" % old[:40])
    src = src2.replace(old2, new2)
    if kind == "mod":
        ns = dict(vars(owner))
        ns["__name__"] = owner.__name__
    else:
        ns = dict(vars(sys.modules[owner.__module__]))
        ns["__name__"] = owner.__module__
    exec(compile(src, "mr_mut.py", "exec"), ns)
    live = getattr(owner, name)
    setattr(owner, name, ns[name])
    try:
        yield
    finally:
        setattr(owner, name, live)


def _mutate_mode():
    bad = []
    anchor_bad = _anchor_check()
    if anchor_bad:
        for b in anchor_bad:
            print("  ANCHOR-MISS " + b)
        print("\n锚点自检：FAIL（fail-closed，exit 2）")
        return 2
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：红项=%d%s"
          % (clean, "" if clean == 0 else "  ← 基线即红，变异核验无意义"))
    if clean:
        bad.append("未变异基线即失败")
    _RUN[0] = 10 ** 6
    for name, kind, owner, fname, old, new, expect in _SRC_MUTATIONS:
        _RUN[0] += 1
        try:
            with _patched((kind, owner, fname), old, new), \
                    contextlib.redirect_stdout(io.StringIO()):
                fails = _run_groups()
        except Exception as exc:        # noqa: BLE001 —— 变异把路径打断也算「红」
            fails = -1
            print("  变异「%s」→ 断言链抛异常 %s: %s（判 FAIL）"
                  % (name, type(exc).__name__, str(exc)[:80]))
        verdict = ("命中预期" if fails == expect
                   else "**红项数不符（预期 %d）**" % expect)
        print("  变异「%s」→ 红项=%d  %s" % (name, fails, verdict))
        for f in _FAIL[:6]:
            print("      红:", f)
        if len(_FAIL) > 6:
            print("      …（余 %d 项）" % (len(_FAIL) - 6))
        if fails != expect:
            bad.append(name)
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都有变异钉死，且红项数逐处吻合）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    src = os.path.basename(os.path.abspath(__file__))
    if "--mutate" in sys.argv:
        print("!! 定点变异模式：逐个变异判据，套件应转红且红项数吻合\n")
        try:
            return _mutate_mode()
        finally:
            shutil.rmtree(_SANDBOX, ignore_errors=True)
    anchor_bad = _anchor_check()
    if anchor_bad:
        for b in anchor_bad:
            print("  ANCHOR-MISS " + b)
        print("\n锚点自检：FAIL（fail-closed，exit 2）——实现改了请同步变异表")
        return 2
    print("锚点自检：PASS（%s；不以 git HEAD 为基线源）" % src)
    try:
        for g in _GROUPS:
            g()
    finally:
        _RUN[0] += 1
    print("\n变更单回滚面守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("    红:", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
        os.environ.pop("MDCG_POLICY_FILE", None)
        if _OLD_POLICY is not None:
            os.environ["MDCG_POLICY_FILE"] = _OLD_POLICY
        os.environ.pop(_ENV_MODE, None)
    sys.exit(rc)
