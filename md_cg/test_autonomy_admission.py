# -*- coding: utf-8 -*-
"""md_cg · 三档自治「准入读数 R1–R4 与准入闸」守卫（设计 v0.2 §六/§七/§十一 · 批次④）。

覆盖（设计 §十一「R1–R4 各有独立断言与一组门槛刚过/刚不过的边界用例，
含窗口边界 3 天/30 天」在本批的落点）：

  A 组 **R1 判断非退化**（30 天窗）：三态齐 + 单一占比 <90% 的满足判据；
     门槛边界——恰 90%（刚不过）/ 89.9%（刚过）/ 三态缺失 / **30 天窗口
     边界 ±60s**（窗外不计入）/ 缺数据面；
  B 组 **R2 会说「不」**（短期 3 天 + 长期 30 天）：3 天内各 ≥1（刚过=恰好 1）
     / 3 天外 30 天内（短期刚不过，同时钉长期读数照记）/ **3 天窗口边界
     ±60s** / 无 created_at 不计窗（如实）；短期满足 ⇒ 长期自动满足
     （窗口嵌套——长期判据的独立判别力在「短期不足」侧，见 B2）；
  C 组 **R3 破坏可逆且「回过」**（30 天窗，状态推断见 admission docstring）：
     D 面真跑 forget→restore（刚过=1 次）/ 只删不回（刚不过）/ 只有 restore
     无更早 forget 不计（证据链要成对）/ C 面真跑 出单→accept→回滚
     （盘面逐字节==执行时点前像）/ 执行不回滚（盘面≠前像，刚不过）/
     **30 天窗口边界 ±60s**（窗外 restore 不计）；
  D 组 **R4 判断收敛**（3×10 天子窗）：0.40/0.30/0.10 严格下降且最近 <20%
     （刚过）/ 恰 20%（刚不过）/ 持平（非严格下降，刚不过）/ 样本不足 ⇒
     不可判（ok=None，不假装）/ **10 天子窗归属边界** / edit 与 reject 同权；
  E 组 **准入闸**（`autonomy_modes.settle`/`mode`）：full+不满足 ⇒ 实际生效
     档位回落 confirm 且 alerts 报「缺哪条读数」（不静默）/ full+满足 ⇒ full
     （与改动前逐位一致）/ plan·confirm 不受读数影响（零 IO 零告警）/ 非法
     env fail-closed / 未结算=旧行为（对拍）/ 缓存频度（TTL 内不重扫——
     「不得让每次 decide 都全库扫描」的机械证明）/ decide 端到端看回落 /
     只读（结算前后库指纹不变）；
  F 组 **结构单点与只读**：数据面常量与真源同值 / 显式 root 不调 default_root
     / CLI 形态（够格 rc=0、不够格 rc=1、--json 可读）/ check 幂等且零写入；
  G 组 **补强批次（v1.1）**：数值容错——`_ts`/`_fm_ts` 逐型（400 位整数 /
     `1e400`(=inf) / -inf / NaN / 字符串数字 / 负数 / None ⇒ None 不抛；
     合法浮点/整数/可表示大数逐位不变）+ 四条读数与 `check()` 对含溢出行的
     数据面不崩、`undated` 计数正确 + 含溢出行库的 `settle` 容错生效（回落
     confirm 而非结算失败态）；结算异常 fail-closed——从未结算 + 异常 ⇒
     失败态（error 非空、alerts 报「读数不可得」）+ `mode()` 回落 confirm
     （收口 fail-open）/ 已成功结算 + 异常 ⇒ 不升不降（保持上次 effective）
     且失败态可观测 / 失败态与「未调用过 settle」可区分 / 「未调用过 settle
     ⇒ mode()=env」对拍保持 / 失败态路径零写入。

**定点变异自证**（`--mutate`，与 `md_cg/test_neg_condition_hits.py` /
`md_cg/test_autonomy_modes.py` 同口径）：表内每项 = (说明, 目标, 锚点原文,
替换文, 预期红项数)。锚点须**逐字**出现在目标函数源码里；漂移即
ANCHOR-MISS（fail-closed，exit 2）。红项数与实测**逐一相符**才算通过。
补强批次新增 4 处（容错摘除 / 失败态放行 full / 失败态总是 confirm /
结算异常不捕获），并校准既有 ⑫/⑭ 的红项数（G 组判据并入）。

沙箱（硬约束）：一切读写都在 tempfile.mkdtemp 内（含 MDCG_AUX_ROOT / 主密钥
——crypto 在导入期求值 MASTER_FILE，故必须在任何 md_cg 子模块 import **之前**
设好）；跑完 rmtree。**绝不碰在役数据根**：本守卫所有读数/结算都传显式合成
root；F2 另钉「显式 root 不触 default_root」。档位 env 由夹具按需设置并在
finally 还原；结算态（settle）每组用完即 reset_settlement。

运行：
    python -X utf8 -m md_cg.test_autonomy_admission              # 正常跑
    python -X utf8 -m md_cg.test_autonomy_admission --mutate     # 定点变异自证
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

# ---- 沙箱：必须在任何 md_cg 子模块 import 之前 ------------------------------
_SANDBOX = tempfile.mkdtemp(prefix="autonomy_admission_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SANDBOX
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)
_OLD_POLICY = os.environ.pop("MDCG_POLICY_FILE", None)

from . import admission as adm                                    # noqa: E402
from . import autonomy_modes as am                                # noqa: E402
from . import forgetting, mdcos, nodefile, protect                # noqa: E402
from . import rollback as rb                                      # noqa: E402
from .mdcos import MdCGOS                                         # noqa: E402

_ENV_MODE = am.AUTONOMY_ENV_KEYS["mode"]
DAY = 86400.0   # 字面量：用例数据不引用被测常量（否则常量变异会带着数据一起漂移、判别力流失）
NOW = time.time()

_PASS = []
_FAIL = []
_RUN = [0]

BODY = ("# 功能名：部署面端口约定\n"
        "# 生效条件：载体/位置：prod 集群；时间：2026-09-30 起；方法：部署清单核对；约束：无\n"
        "# 子功能：登记各服务监听端口\n"
        "# 执行：核对 manifest 的 ports 段\n"
        "# 验证方式：test\n"
        "# 不适用条件：无\n"
        "\n网关监听端口 8080/HTTP；管理面监听端口 8081/HTTP；"
        "指标面监听端口 %s/HTTP；日志面监听端口 9091/HTTP\n")


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _root(tag="lib"):
    """独立合成库根（每轮独立子根：变异模式连跑多轮，共用目录会读到旧盘面）。"""
    p = os.path.join(_SANDBOX, "%s_r%d" % (tag, _RUN[0]))
    os.makedirs(p, exist_ok=True)
    return p


def _wr_jsonl(root, rel, rows):
    """写 JSONL 数据面（合成库内；只被守卫调用，生产码不写）。"""
    p = os.path.join(root, rel)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def _mk_layer(root, layer, nid, created_at=None):
    """造一个层节点 md（fm 含 id/layer/created_at——R2 的判窗面）。"""
    p = os.path.join(root, layer, nid + ".md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fm = {"id": nid, "layer": layer}
    if created_at is not None:
        fm["created_at"] = created_at
    with open(p, "w", encoding="utf-8") as f:
        f.write(nodefile.dumps(fm, "# 探针节点\n"))
    return p


def _rows_r4(windows):
    """windows = [(n_reject, n_accept)] 按 W1(最近)/W2/W3 顺序 → decisions 行。"""
    rows = []
    for k, (n_rej, n_acc) in enumerate(windows, start=1):
        mid = NOW - (k - 0.5) * 10 * DAY
        rows += [{"t": mid, "decision": "reject"} for _ in range(n_rej)]
        rows += [{"t": mid, "decision": "accept"} for _ in range(n_acc)]
    return rows


def _satisfying(tag):
    """四条读数全满足的合成库（E 组「full+满足 ⇒ full」用；F1 也复用它）。"""
    r = _root(tag)
    _wr_jsonl(r, adm.FORGETTING_LOG, [
        {"t": NOW - 3600, "verdict": "DROP"},
        {"t": NOW - 3600, "verdict": "MERGE"},
        {"t": NOW - 3600, "verdict": "DEFER"}])
    _mk_layer(r, "rejected", "rej_ok", NOW - 3600)
    _mk_layer(r, "unresolved", "unr_ok", NOW - 3600)
    _wr_jsonl(r, adm.DEVICE_AUDIT, [
        {"t": NOW - 7200, "op": "forget", "id": "z_1"},
        {"t": NOW - 3600, "op": "restore", "id": "z_1", "forced": True}])
    _wr_jsonl(r, adm.DECISIONS_LOG, _rows_r4([(1, 9), (3, 7), (4, 6)]))
    return r


@contextlib.contextmanager
def _mode(m):
    """按需设档位，退出还原（夹具专用；不在生产码里读/写档位）。"""
    old = os.environ.get(_ENV_MODE)
    os.environ[_ENV_MODE] = m
    try:
        yield m
    finally:
        if old is None:
            os.environ.pop(_ENV_MODE, None)
        else:
            os.environ[_ENV_MODE] = old


def _mk_cg(root):
    return MdCGOS(root, autoflush=1)


# =============================================================== A 组：R1
def g_a():
    print("== A 组：R1 判断非退化（30 天窗 · 门槛刚过/刚不过/窗口边界）==")
    r = _root("r1_ok")
    _wr_jsonl(r, adm.FORGETTING_LOG, [
        {"t": NOW - 3600, "verdict": "DROP"},
        {"t": NOW - 3600, "verdict": "MERGE"},
        {"t": NOW - 3600, "verdict": "DEFER"}])
    d = adm.r1_non_degenerate(r, now=NOW)
    ok(d["ok"] is True and d["total"] == 3 and d["missing_verdicts"] == []
       and d["top_share"] < 0.90,
       "A1 三态齐且单一占比 33%% → 满足（门槛刚过侧）", d["detail"])

    r = _root("r1_edge90")
    _wr_jsonl(r, adm.FORGETTING_LOG,
              [{"t": NOW - 3600, "verdict": "DROP"}] * 18
              + [{"t": NOW - 3600, "verdict": "MERGE"}]
              + [{"t": NOW - 3600, "verdict": "DEFER"}])
    d = adm.r1_non_degenerate(r, now=NOW)
    ok(d["ok"] is False and abs((d["top_share"] or 0) - 0.90) < 1e-9,
       "A2 单一 verdict 恰 90%% → 不满足（阈值严格小于，刚不过）", d["detail"])

    r = _root("r1_edge899")
    _wr_jsonl(r, adm.FORGETTING_LOG,
              [{"t": NOW - 3600, "verdict": "DROP"}] * 899
              + [{"t": NOW - 3600, "verdict": "MERGE"}] * 51
              + [{"t": NOW - 3600, "verdict": "DEFER"}] * 50)
    d = adm.r1_non_degenerate(r, now=NOW)
    ok(d["ok"] is True and abs((d["top_share"] or 0) - 0.899) < 1e-9,
       "A3 单一 verdict 89.9%% → 满足（刚过）", d["detail"])

    r = _root("r1_short3")
    _wr_jsonl(r, adm.FORGETTING_LOG,
              [{"t": NOW - 3600, "verdict": "DROP"}] * 5
              + [{"t": NOW - 3600, "verdict": "MERGE"}] * 5)
    d = adm.r1_non_degenerate(r, now=NOW)
    ok(d["ok"] is False and d["missing_verdicts"] == ["DEFER"],
       "A4 三态不全（缺 DEFER）→ 不满足（占比再低也不行）", d["detail"])

    r = _root("r1_border")
    _wr_jsonl(r, adm.FORGETTING_LOG, [
        {"t": NOW - 30 * DAY - 60, "verdict": "DROP"},   # 窗外
        {"t": NOW - 30 * DAY + 60, "verdict": "MERGE"},  # 窗内
        {"t": NOW - 30 * DAY + 120, "verdict": "DEFER"}])  # 窗内
    d = adm.r1_non_degenerate(r, now=NOW)
    ok(d["total"] == 2 and "DROP" not in d["by_verdict"]
       and d["summary_all"]["total"] == 3,
       "A5 30 天窗口边界 ±60s：窗外一条不计入窗口、窗内两条计入（全量仍 3）",
       {"win": d["by_verdict"], "all": d["summary_all"]})

    r = _root("r1_missing")
    d = adm.r1_non_degenerate(r, now=NOW)
    ok(d["ok"] is False and adm.FORGETTING_LOG in d["detail"],
       "A6 缺数据面（无 _forgetting.jsonl）→ 不满足且 detail 指名缺哪个文件",
       d["detail"])


# =============================================================== B 组：R2
def g_b():
    print("== B 组：R2 会说「不」（3 天/30 天 · 门槛刚过/刚不过/窗口边界）==")
    r = _root("r2_ok")
    _mk_layer(r, "rejected", "rej_1", NOW - 3600)
    _mk_layer(r, "unresolved", "unr_1", NOW - 3600)
    d = adm.r2_says_no(r, now=NOW)
    ok(d["ok"] is True and d["layers"]["rejected"]["recent"] == 1
       and d["layers"]["unresolved"]["recent"] == 1,
       "B1 两层 3 天内各恰好 1 条 → 满足（门槛刚过侧）", d["detail"])

    r = _root("r2_short_no")
    _mk_layer(r, "rejected", "rej_1", NOW - 4 * DAY)
    _mk_layer(r, "unresolved", "unr_1", NOW - 3600)
    d = adm.r2_says_no(r, now=NOW)
    ok(d["ok"] is False and d["short_missing"] == ["rejected"]
       and d["layers"]["rejected"]["total_30d"] == 1,
       "B2 短期刚不过：rejected 最近一条在 3 天外（30 天内）→ 不满足；"
       "长期读数照记（=1，长期判据的独立判别面）", d["detail"])

    r = _root("r2_border")
    _mk_layer(r, "rejected", "rej_in", NOW - 3 * DAY + 60)
    _mk_layer(r, "rejected", "rej_out", NOW - 3 * DAY - 60)
    _mk_layer(r, "unresolved", "unr_1", NOW - 3600)
    d = adm.r2_says_no(r, now=NOW)
    ok(d["layers"]["rejected"]["recent"] == 1
       and d["layers"]["rejected"]["total_30d"] == 2 and d["ok"] is True,
       "B3 3 天窗口边界 ±60s：窗外一条不计入短期、窗内一条计入（30 天总量仍 2）",
       d["layers"]["rejected"])

    r = _root("r2_border_no")
    _mk_layer(r, "rejected", "rej_out", NOW - 3 * DAY - 60)
    _mk_layer(r, "unresolved", "unr_1", NOW - 3600)
    d = adm.r2_says_no(r, now=NOW)
    ok(d["ok"] is False and d["layers"]["rejected"]["recent"] == 0,
       "B4 3 天窗口边界刚不过：唯一 rejected 在窗外（60s）→ 短期 0 条不满足",
       d["layers"]["rejected"])

    r = _root("r2_undated")
    _mk_layer(r, "rejected", "rej_nodate", None)
    _mk_layer(r, "unresolved", "unr_1", NOW - 3600)
    d = adm.r2_says_no(r, now=NOW)
    ok(d["ok"] is False and d["layers"]["rejected"]["undated"] == 1
       and d["layers"]["rejected"]["recent"] == 0,
       "B5 无 created_at 的节点不计窗（如实计入 undated；不猜文件 mtime）",
       d["layers"]["rejected"])

    r = _root("r2_long_old")
    _mk_layer(r, "rejected", "rej_old", NOW - 40 * DAY)
    _mk_layer(r, "unresolved", "unr_1", NOW - 3600)
    d = adm.r2_says_no(r, now=NOW)
    ok(d["ok"] is False and d["layers"]["rejected"]["total_30d"] == 0,
       "B6 40 天前的节点不计入 30 天总量（长期窗边界外）",
       d["layers"]["rejected"])


# =============================================================== C 组：R3
def g_c():
    print("== C 组：R3 破坏可逆且「回过」（D 面/C 面真跑 · 30 天窗口边界）==")
    # C1 D 面正向：真跑 forget→restore（1 次真实回滚 = 门槛刚过）
    r = _root("r3_d_ok")
    cg = _mk_cg(r)
    cg.add("d_1", BODY % "D1", layer="knowledge", verification_basis="test")
    cg.flush()
    cg.forget("d_1", reason="探针删除")
    cg.restore("d_1", force=True)
    cg.flush()
    res = cg.close()
    # 真跑的时间戳 = 执行时刻（略晚于模块加载时的 NOW）——窗口「现在」取
    # NOW+3600（未来一点），使真跑记录确定落在 30 天窗内。
    d = adm.r3_reversible(r, now=NOW + 3600)
    ok(d["ok"] is True and d["d_restores"] >= 1 and d["count"] >= 1,
       "C1 D 面：forget→restore 实测 ⇒ 30 天内 ≥1 次真实回滚（门槛刚过侧）",
       d["detail"])

    # C2 D 面刚不过：只删不回
    r = _root("r3_d_no")
    cg = _mk_cg(r)
    cg.add("d_2", BODY % "D2", layer="knowledge", verification_basis="test")
    cg.flush()
    cg.forget("d_2", reason="探针删除")
    cg.flush()
    cg.close()
    d = adm.r3_reversible(r, now=NOW)
    ok(d["ok"] is False and d["d_restores"] == 0,
       "C2 D 面刚不过：只删不回（无 restore）→ 0 次证据、不满足", d["detail"])

    # C3 证据链成对：只有 restore、无更早 forget → 不计
    r = _root("r3_restore_only")
    _wr_jsonl(r, adm.DEVICE_AUDIT,
              [{"t": NOW - 3600, "op": "restore", "id": "x_9",
                "forced": True}])
    d = adm.r3_reversible(r, now=NOW)
    ok(d["ok"] is False and d["count"] == 0,
       "C3 只有 restore 无更早 forget → 不计（「回过」须成对：删过才谈得上回）",
       d["detail"])

    # C4 C 面正向：出单 → accept 执行 → 回滚（盘面逐字节回到执行时点前像）
    r = _root("r3_c_ok")
    cg = _mk_cg(r)
    cg.add("c_1", BODY % "C1", layer="knowledge", verification_basis="test")
    cg.flush()
    pay = am.mutation_payload(am.C_REWRITE, "c_1", after=BODY % "C1b",
                              reason="探针改写")
    pid = am.propose_mutation(cg, am.C_REWRITE, "c_1", payload=pay)
    cg.flush()
    res = cg.review_decide(pid, "accept")
    recs = [x for x in cg.decisions()
            if x.get("pid") == pid and x.get("decision") == "accept"]
    rbout = rb.rollback_mutation(cg, recs[-1]["mutation"], reason="探针回滚")
    cg.flush()
    cg.close()
    d = adm.r3_reversible(r, now=NOW + 3600)
    ok(res.get("ok") is True and rbout.get("ok") is True
       and rbout.get("bytes_equal_preimage") is True
       and d["ok"] is True and d["cb_pairs"] >= 1,
       "C4 C 面：accept 执行后回滚（逐字节==执行时点前像）⇒ 证据成立、满足",
       d["detail"])

    # C5 C 面刚不过：执行不回滚（盘面 ≠ 前像）
    r = _root("r3_c_no")
    cg = _mk_cg(r)
    cg.add("c_2", BODY % "C2", layer="knowledge", verification_basis="test")
    cg.flush()
    pay = am.mutation_payload(am.C_REWRITE, "c_2", after=BODY % "C2b",
                              reason="探针改写")
    pid = am.propose_mutation(cg, am.C_REWRITE, "c_2", payload=pay)
    cg.flush()
    cg.review_decide(pid, "accept")
    cg.flush()
    cg.close()
    d = adm.r3_reversible(r, now=NOW + 3600)
    ok(d["ok"] is False and d["cb_pairs"] == 0 and d["candidates"] >= 1,
       "C5 C 面刚不过：执行后未回滚（盘面≠前像）→ 0 次证据、不满足", d["detail"])

    # C6 30 天窗口边界：窗外 restore 不计、窗内成对计入
    r = _root("r3_border")
    _wr_jsonl(r, adm.DEVICE_AUDIT, [
        {"t": NOW - 31 * DAY, "op": "forget", "id": "old_1"},
        {"t": NOW - 30 * DAY - 60, "op": "restore",
         "id": "old_1", "forced": True},                      # 窗外
        {"t": NOW - 7200, "op": "forget", "id": "new_1"},
        {"t": NOW - 3600, "op": "restore", "id": "new_1",
         "forced": True}])                                    # 窗内
    d = adm.r3_reversible(r, now=NOW)
    ok(d["count"] == 1 and d["evidence"][0]["node_id"] == "new_1",
       "C6 30 天窗口边界 ±60s：窗外 restore 不计、窗内成对计入（恰 1 条）",
       d["evidence"])


# =============================================================== D 组：R4
def g_d():
    print("== D 组：R4 判断收敛（3×10 天子窗 · 门槛刚过/刚不过/不可判）==")
    r = _root("r4_ok")
    _wr_jsonl(r, adm.DECISIONS_LOG, _rows_r4([(1, 9), (3, 7), (4, 6)]))
    d = adm.r4_converging(r, now=NOW)
    ok(d["ok"] is True and d["rates_asc"][0] > d["rates_asc"][1] > d["rates_asc"][2]
       and d["rates_asc"][2] == 0.10,
       "D1 0.40/0.30/0.10 严格下降且最近 <20%% → 满足（门槛刚过侧）", d["detail"])

    r = _root("r4_edge20")
    _wr_jsonl(r, adm.DECISIONS_LOG, _rows_r4([(2, 8), (4, 6), (5, 5)]))
    d = adm.r4_converging(r, now=NOW)
    ok(d["ok"] is False and d["rates_asc"][2] == 0.20,
       "D2 最近子窗恰 20%% → 不满足（阈值严格小于，刚不过）", d["detail"])

    r = _root("r4_flat")
    _wr_jsonl(r, adm.DECISIONS_LOG, _rows_r4([(1, 9), (1, 9), (3, 7)]))
    d = adm.r4_converging(r, now=NOW)
    ok(d["ok"] is False and d["rates_asc"][1] == d["rates_asc"][2] == 0.10,
       "D3 子窗持平（0.30/0.10/0.10，最近 <20% 但不严格递减）→ 不满足"
       "（「逐窗下降」= 严格递减，平坦不算下降）", d["detail"])

    r = _root("r4_indet")
    _wr_jsonl(r, adm.DECISIONS_LOG, _rows_r4([(0, 0), (3, 7), (4, 6)]))
    d = adm.r4_converging(r, now=NOW)
    ok(d["ok"] is None,
       "D4 最近子窗无裁定样本 → 不可判（ok=None，如实；不假装收敛/不收敛）",
       d["detail"])

    r = _root("r4_border")
    _wr_jsonl(r, adm.DECISIONS_LOG, [
        {"t": NOW - 10 * DAY - 60, "decision": "reject"},  # W2
        {"t": NOW - 10 * DAY, "decision": "accept"},       # W2 边界
        {"t": NOW - 10 * DAY + 60, "decision": "reject"},  # W1
    ])
    d = adm.r4_converging(r, now=NOW)
    ok(d["windows"][1]["total"] == 2 and d["windows"][0]["total"] == 1,
       "D5 10 天子窗归属边界：恰在边界线上的记录归远窗（lo< t ≤ hi），"
       "±60s 分属两窗", {"W1": d["windows"][0], "W2": d["windows"][1]})

    r = _root("r4_edit")
    rows = _rows_r4([(0, 9), (3, 7), (4, 6)])
    rows.append({"t": NOW - 5 * DAY, "decision": "edit"})
    _wr_jsonl(r, adm.DECISIONS_LOG, rows)
    d = adm.r4_converging(r, now=NOW)
    ok(d["ok"] is True and abs(d["rates_asc"][2] - 0.10) < 1e-9,
       "D6 edit 与 reject 同权计入驳回率（最近窗 1 edit/10 = 10%）",
       d["rates_asc"])


# =============================================================== E 组：准入闸
def g_e():
    print("== E 组：准入闸（settle/mode：full 走读数、plan/confirm 不受影响）==")
    try:
        # E1 full + 读数满足 ⇒ 实际生效 full（与改动前逐位一致）
        sat = _satisfying("adm_sat")
        chk = adm.check(sat, now=NOW)
        with _mode("full"):
            am.reset_settlement()
            st = am.settle(root=sat, force=True)
            ok(chk["ok"] is True and st["effective"] == "full"
               and st["settled"] is True and st["alerts"] == []
               and am.mode() == "full",
               "E1 full+读数满足 ⇒ 生效档位 full、零告警（与改动前逐位一致）",
               {"chk_ok": chk["ok"], "eff": st["effective"],
                "alerts": st["alerts"][:2]})

        # E2 full + 读数不满足 ⇒ 回落 confirm + alerts 报缺哪条（不静默）
        empty = _root("adm_empty")
        am.reset_settlement()
        with _mode("full"):
            st = am.settle(root=empty, force=True)
            missing = st["admission"]["missing"]
            ok(st["effective"] == "confirm" and st["settled"] is True
               and st["configured"] == "full",
               "E2 full+读数不满足 ⇒ 实际生效档位回落 confirm（配置仍记 full）",
               {"eff": st["effective"], "missing": missing})
            ok([a["reading"] for a in st["alerts"]] == missing and missing,
               "E2a 告警可观测：alerts 逐条报「缺哪条读数」（与读数 missing 逐一相同，"
               "不静默降级）", st["alerts"])
            ok(am.mode() == "confirm",
               "E2b 生效面贯通：回落后 mode() 返回 confirm（同一入口全出口一致）",
               am.mode())
            ok(all(a.get("detail") for a in st["alerts"]),
               "E2c alerts 每条带可读 detail（报缺口而非只报编号）",
               st["alerts"][:1])
            ok(am.admission_state()["alerts"] == st["alerts"]
               and am.admission_state()["effective"] == "confirm",
               "E2d 结算态可查：admission_state() 返回同一结算体（含 alerts）")

        # E3 confirm 不受读数影响（零 IO、零告警）
        am.reset_settlement()
        before = adm.cache_stats()["checks"]
        with _mode("confirm"):
            st = am.settle(root=empty, force=True)
            ok(st["effective"] == "confirm" and st["admission"] is None
               and st["alerts"] == [] and st["settled"] is False
               and am.mode() == "confirm",
               "E3 confirm 档不受读数影响（admission=None、零告警、零读数扫描）",
               st)
        ok(adm.cache_stats()["checks"] == before,
           "E3a confirm 结算零 IO（读数扫描计数不变）",
           adm.cache_stats())

        # E4 plan 不受读数影响
        am.reset_settlement()
        with _mode("plan"):
            st = am.settle(root=empty, force=True)
            ok(st["effective"] == "plan" and st["admission"] is None
               and st["alerts"] == [] and am.mode() == "plan",
               "E4 plan 档不受读数影响（零告警、零读数扫描）", st)

        # E5 非法 env 仍 fail-closed
        with _mode("bogus-garbage"):
            try:
                am.settle(root=empty, force=True)
                ok(False, "E5 非法 env settle 未报错")
            except am.AutonomyModeError as e:
                ok("bogus-garbage" in str(e) and "full" in str(e),
                   "E5 非法 env fail-closed：settle 抛 AutonomyModeError"
                   "（hint 列合法值）", str(e)[:50])

        # E6 未结算 = 旧行为（对拍）
        am.reset_settlement()
        with _mode("full"):
            ok(am.mode() == "full" and am.admission_state()["settled"] is False,
               "E6 未结算时 mode() 返回配置档位（生效面未启用 = 改动前逐位一致）",
               am.mode())

        # E7 缓存频度：TTL 内不重扫（「不得让每次 decide 都全库扫描」）
        am.reset_settlement()
        adm.reset_cache()
        with _mode("full"):
            am.settle(root=empty, force=True, ttl=60)
            am.settle(root=empty, ttl=60)
            am.settle(root=empty, ttl=60)
            c1 = adm.cache_stats()["checks"]
            # 确定过期（ttl=-1；不用 0——Windows time.time() 刻度 ~15.6ms，
            # 连续调用可能同刻度，差为 0 时 0<=0 仍命中缓存，判据会含糊）
            am.settle(root=empty, ttl=-1)
            c2 = adm.cache_stats()["checks"]
            ok(c1 == 1 and c2 == 2,
               "E7 读数缓存：TTL=60s 内三次结算只扫一次；确定过期（ttl=-1）才重扫"
               "（热路径 mode()/decide() 零 IO）", {"checks": c1, "after_exp": c2})

        # E8 decide 端到端：回落在判定链上可见
        am.reset_settlement()
        with _mode("full"):
            am.settle(root=empty, force=True)
            dec = am.decide("D")
            ok(dec["decision"] == "confirm" and dec["mode"] == "confirm",
               "E8 full+不满足：decide(D) 判 confirm（回落在判定链上生效）", dec)
        am.reset_settlement()
        with _mode("full"):
            am.settle(root=sat, force=True)
            dec = am.decide("D")
            ok(dec["decision"] == "allow" and dec["mode"] == "full",
               "E8a full+满足：decide(D) 判 allow（与改动前一致）", dec)

        # E9 只读：结算前后库指纹不变（「只告警不改数据」）
        fp0 = adm._fingerprint(sat)
        am.reset_settlement()
        with _mode("full"):
            am.settle(root=sat, force=True)
        fp1 = adm._fingerprint(sat)
        ok(fp0 == fp1 and len(fp0) > 0,
           "E9 只告警不改数据：settle（含读数扫描）前后库指纹逐位相同", len(fp0))
    finally:
        am.reset_settlement()


# =============================================================== F 组：结构
def g_f():
    print("== F 组：结构单点与只读（常量同源 / 不触 default_root / CLI）==")
    ok(adm.R1_MAX_SHARE == 0.90 and adm.R4_MAX_RATE == 0.20
       and adm.WINDOW_SHORT_D == 3 and adm.WINDOW_LONG_D == 30
       and adm.R4_SUBWINDOW_D == 10 and adm.R4_SUBWINDOWS == 3
       and adm.R3_MIN_ROLLBACKS == 1 and adm.R2_MIN_RECENT == 1
       and adm.R2_MIN_TOTAL == 1,
       "F0 门槛/窗口常量与设计 §七 表同值（0.90 / 0.20 / 3 天 / 30 天 / "
       "3×10 天 / 各 1 次——守卫钉规格的字面量面）",
       {"share": adm.R1_MAX_SHARE, "rate": adm.R4_MAX_RATE,
        "short_d": adm.WINDOW_SHORT_D, "long_d": adm.WINDOW_LONG_D})
    ok(adm.FORGETTING_LOG == forgetting.LOG_FILE
       and adm.PROTECT_AUDIT == protect.AUDIT_FILE
       and adm.HISTORY_DIR == protect.HISTORY_DIR
       and adm.DECISIONS_LOG == os.path.join(mdcos.MdCGOS.HIPPOCAMPUS,
                                             "decisions.jsonl")
       and adm.AUDIT_ARCHIVE == mdcos.MdCGOS.AUDIT_ARCHIVE,
       "F1 数据面常量与真源同值（forgetting/protect/mdcos 单点）",
       {"adm": adm.FORGETTING_LOG, "src": forgetting.LOG_FILE})

    r = _root("f_no_default")
    live = adm.default_root
    adm.default_root = lambda: (_ for _ in ()).throw(
        AssertionError("显式 root 路径不应触发 default_root()"))
    try:
        d1 = adm.check(r, now=NOW)
        d2 = adm.gate(r, now=NOW, force=True)
        am.reset_settlement()
        with _mode("full"):
            st = am.settle(root=r, force=True)
        ok(d1["ok"] is False and d2["ok"] is False
           and st["effective"] == "confirm",
           "F2 显式 root 的读数/结算不触 default_root（沙箱隔离：不碰在役根）",
           None)
    finally:
        adm.default_root = live
        am.reset_settlement()

    empty = _root("f_cli_no")
    r = _root("f_cli_ok")
    _wr_jsonl(r, adm.FORGETTING_LOG, [
        {"t": NOW - 3600, "verdict": "DROP"},
        {"t": NOW - 3600, "verdict": "MERGE"},
        {"t": NOW - 3600, "verdict": "DEFER"}])
    _mk_layer(r, "rejected", "rej_1", NOW - 3600)
    _mk_layer(r, "unresolved", "unr_1", NOW - 3600)
    _wr_jsonl(r, adm.DEVICE_AUDIT, [
        {"t": NOW - 7200, "op": "forget", "id": "z_1"},
        {"t": NOW - 3600, "op": "restore", "id": "z_1", "forced": True}])
    _wr_jsonl(r, adm.DECISIONS_LOG, _rows_r4([(1, 9), (3, 7), (4, 6)]))
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_out = os.path.join(_SANDBOX, "cli_out_r%d.json" % _RUN[0])

    def _cli(root):
        p = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "md_cg.admission",
             "--root", root, "--json", json_out],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=repo, env=dict(os.environ, PYTHONUTF8="1"))
        return p

    p_no = _cli(empty)
    p_ok = _cli(r)
    ok(p_no.returncode == 1 and "不够格" in (p_no.stdout or ""),
       "F3 CLI：不满足库 rc=1 且打印「不够格」（全入口可答「它今天够格吗」）",
       (p_no.stdout or "")[:80])
    ok(p_ok.returncode == 0 and "够格" in (p_ok.stdout or ""),
       "F4 CLI：满足库 rc=0 且打印「够格」", (p_ok.stdout or "")[:80])
    try:
        with open(json_out, encoding="utf-8") as f:
            rep = json.load(f)
        ok(len(rep.get("readings") or []) == 4 and rep.get("ok") is True,
           "F4a CLI --json 落盘完整读数体（四条读数齐备）",
           list(rep.keys())[:8])
    except (OSError, ValueError) as e:
        ok(False, "F4a CLI --json 输出不可读：%r" % e)


# =============================================================== G 组：补强批次
def g_g():
    """补强批次（v1.1）：数值容错（不可表示 ⇒ 缺时间戳）+ 结算异常 fail-closed。

    语义出处：`admission.py` 模块 docstring「补强批次」段（口径与 `_stream_jsonl`
    「坏行跳过不抛」一致）＋ `autonomy_modes.settle` docstring（失败态两格：
    从未结算 ⇒ 回落 confirm；已结算 ⇒ 不升不降）。跑完必 reset_settlement。
    """
    print("== G 组：补强批次（溢出/坏值容错 · settle 异常 fail-closed）==")
    BIG = int("9" * 400)        # 400 位十进制整数：float() 溢出（复核 uncovered 原形态）

    def _safe(fn):
        """可崩调用包装：返回 (结果, 异常串)——异常由断言判红，不让整组中断。"""
        try:
            return fn(), None
        except Exception as e:                                  # noqa: BLE001
            return None, "%s: %s" % (type(e).__name__, e)

    # G1 逐型读数：不可表示值一律 None（不抛）；合法值逐位不变（独立 oracle）
    ts_bad = []
    for name, v, want in (
            ("400 位整数", BIG, None),
            ("1e400(=inf)", float("1e400"), None),
            ("-inf", float("-inf"), None),
            ("NaN", float("nan"), None),
            ("字符串数字", "1700000000", None),
            ("负数", -5, None),
            ("None", None, None),
            ("合法浮点", 1700000000.5, 1700000000.5),
            ("合法整数", 1700000000, 1700000000.0),
            ("10**300（可表示）", 10 ** 300, 1e300)):
        got, err = _safe(lambda v=v: adm._ts({"t": v}))
        if err is not None or got != want:
            ts_bad.append("%s: %r（want %r）" % (name, err or got, want))
    ok(not ts_bad,
       "G1 `_ts` 逐型：400 位整数/±inf/NaN 视同缺时间戳（None，不抛）；"
       "字符串数字/负数/None 同；合法浮点/整数/可表示大数逐位不变", ts_bad)

    fm_bad = []
    for name, v, want in (
            ("400 位整数", BIG, None),
            ("1e400(=inf)", float("1e400"), None),
            ("NaN", float("nan"), None),
            ("字符串数字", "1700000000", None),
            ("负数", -5, None),
            ("None", None, None),
            ("合法浮点", 1700000000.5, 1700000000.5)):
        got, err = _safe(lambda v=v: adm._fm_ts({"created_at": v}))
        if err is not None or got != want:
            fm_bad.append("%s: %r（want %r）" % (name, err or got, want))
    ok(not fm_bad,
       "G1a `_fm_ts` 逐型：同一数值闸（不可表示 ⇒ None 不抛；合法值逐位不变）",
       fm_bad)

    # G2 四条读数 + check：含溢出/±inf 行的数据面不崩、undated 计数正确
    r = _root("g_ovf")
    _wr_jsonl(r, adm.FORGETTING_LOG, [
        {"t": BIG, "verdict": "DROP"},               # 不可表示 ⇒ 视同缺时间戳
        {"t": float("inf"), "verdict": "MERGE"},     # ±inf 同归缺
        {"t": NOW - 3600, "verdict": "DEFER"}])      # 合法一条照常计窗
    d1, e1 = _safe(lambda: adm.r1_non_degenerate(r, now=NOW))
    ok(e1 is None and d1 is not None,
       "G2 R1 对含溢出/±inf 行的数据面不崩（补强前：OverflowError 直接抛出）", e1)
    ok(e1 is None and d1 is not None and d1["undated"] == 2 and d1["total"] == 1,
       "G2a R1 undated 计数正确：两条坏行视同缺时间戳（undated=2）、仅合法一条计窗",
       {"undated": (d1 or {}).get("undated"), "total": (d1 or {}).get("total")})

    r2 = _root("g_ovf_r2")
    _mk_layer(r2, "rejected", "rej_big", BIG)    # frontmatter 大整数（nodefile 往返为 int）
    _mk_layer(r2, "rejected", "rej_ok", NOW - 3600)
    _mk_layer(r2, "unresolved", "unr_ok", NOW - 3600)
    d2, e2 = _safe(lambda: adm.r2_says_no(r2, now=NOW))
    ok(e2 is None and d2 is not None,
       "G2b R2 对 created_at 为大整数的节点不崩（同一溢出点 `_fm_ts`）", e2)
    ok(e2 is None and d2 is not None
       and d2["layers"]["rejected"]["undated"] == 1
       and d2["layers"]["rejected"]["recent"] == 1,
       "G2c R2 undated 正确：大整数 created_at 计入 undated、合法一条照常计窗",
       (d2 or {}).get("layers", {}).get("rejected"))

    r3 = _root("g_ovf_r3")
    _wr_jsonl(r3, adm.DEVICE_AUDIT, [
        {"t": NOW - 7200, "op": "forget", "id": "g_1"},          # 合法删行
        {"t": BIG, "op": "restore", "id": "g_1",
         "forced": True}])                                       # 坏行 ⇒ 缺时间戳
    d3, e3 = _safe(lambda: adm.r3_reversible(r3, now=NOW))
    ok(e3 is None and d3 is not None and d3["ok"] is False and d3["count"] == 0,
       "G2d R3 对含溢出 t 的 _audit 行不崩：坏行视同缺时间戳 ⇒ 不成对、不计证据",
       e3)

    r4 = _root("g_ovf_r4")
    _wr_jsonl(r4, adm.DECISIONS_LOG,
              _rows_r4([(1, 9), (3, 7), (4, 6)]) + [{"t": BIG, "decision": "accept"}])
    d4, e4 = _safe(lambda: adm.r4_converging(r4, now=NOW))
    ok(e4 is None and d4 is not None and d4["ok"] is True,
       "G2e R4 对含溢出 t 的裁定行不崩：坏行不计窗（三子窗样本与收敛判定不受扰）",
       e4)

    dc, ec = _safe(lambda: adm.check(r, now=NOW))
    ok(ec is None and dc is not None and len(dc["readings"]) == 4
       and "R1" in dc["missing"],
       "G2f check() 对含溢出行的数据面不崩：四条读数齐备、缺口如实列出", ec)

    # G3 settle 异常语义：失败态 + fail-closed（两格）+ 不静默 + 可区分
    sat = _satisfying("g_sat")

    def _boom(*_a, **_k):
        raise RuntimeError("探针注入：读数不可得")

    live_gate = adm.gate
    try:
        # G3 从未结算 + 异常 ⇒ 回落 confirm（收口 fail-open）
        am.reset_settlement()
        adm.gate = _boom
        with _mode("full"):
            st, e3 = _safe(lambda: am.settle(root=sat, force=True))
        adm.gate = live_gate
        ok(e3 is None and st is not None and st["effective"] == "confirm"
           and st["configured"] == "full" and st["settled"] is True,
           "G3 从未结算 + settle 异常 ⇒ 写失败态：effective 回落 confirm（非 full）"
           "——收口「未结算 + 崩溃 ⇒ full 照常生效」的 fail-open",
           {"eff": (st or {}).get("effective"), "err": e3})
        ok(st is not None and bool(st.get("error")) and st["alerts"]
           and st["alerts"][0].get("reading") == "settle_error"
           and "读数不可得" in (st["alerts"][0].get("detail") or ""),
           "G3a 失败态不静默：error 非空 + alerts 报「读数不可得」（不静默降级）",
           {"error": (st or {}).get("error"), "alerts": (st or {}).get("alerts")})
        with _mode("full"):
            ok(am.mode() == "confirm",
               "G3b 生效面贯通：异常回落后 mode()=confirm（full 不照常生效）",
               am.mode())
        st_a = am.admission_state()
        ok(bool(st_a.get("error")) and st_a.get("configured") == "full"
           and st_a.get("settled") is True,
           "G3c 失败态与「未调用过 settle」可区分（configured=full + error 非空）",
           {k: st_a.get(k) for k in ("configured", "settled", "error")})

        # G3d 已成功结算（full+满足）后异常 ⇒ 不升不降（保持上次 effective）
        am.reset_settlement()
        with _mode("full"):
            st0, e0 = _safe(lambda: am.settle(root=sat, force=True))
        ok(e0 is None and st0 is not None and st0["effective"] == "full"
           and st0["error"] is None,
           "G3d0 前置：合法面成功结算 ⇒ full、零错误（合法数据面结算逐位不变）",
           (st0 or {}).get("effective"))
        adm.gate = _boom
        with _mode("full"):
            st1, e1b = _safe(lambda: am.settle(root=sat, force=True))
        adm.gate = live_gate
        ok(e1b is None and st1 is not None
           and (st1 or {}).get("effective") == (st0 or {}).get("effective") == "full"
           and bool((st1 or {}).get("error")),
           "G3d 已成功结算后异常 ⇒ 不升不降：effective 保持上次成功结算值（full）"
           "且失败态仍可观测（error 非空）",
           {"eff0": (st0 or {}).get("effective"),
            "eff1": (st1 or {}).get("effective"),
            "error": (st1 or {}).get("error")})
        with _mode("full"):
            ok(am.mode() == "full" and bool(am.admission_state().get("error")),
               "G3e 不升不降贯通：mode() 仍 full，失败态可查（无静默）",
               {"mode": am.mode(), "error": am.admission_state().get("error")})

        # G4 未调用过 settle 的进程：mode()=env（既有对拍锚，不得破）
        am.reset_settlement()
        with _mode("full"):
            st_u = am.admission_state()
            ok(am.mode() == "full" and st_u["configured"] is None
               and st_u["settled"] is False,
               "G4 未调用过 settle：mode()=env（full）逐位不变、结算态为空"
               "（对拍锚，不得破）", am.mode())

        # G5 失败态路径零写入（只告警不改数据）
        fp0 = adm._fingerprint(sat)
        am.reset_settlement()
        adm.gate = _boom
        with _mode("full"):
            _safe(lambda: am.settle(root=sat, force=True))
        adm.gate = live_gate
        ok(adm._fingerprint(sat) == fp0 and len(fp0) > 0,
           "G5 失败态路径只告警不改数据：结算异常前后库指纹逐位相同", len(fp0))

        # G6 含溢出行的库拿真 gate 结算：容错生效 ⇒ 读数正常判不满足（回落
        # confirm、非结算失败态）；补强前该库 settle 直接崩（fail-open）
        r6 = _root("g_ovf_settle")
        _wr_jsonl(r6, adm.FORGETTING_LOG, [{"t": BIG, "verdict": "DROP"}])
        am.reset_settlement()
        with _mode("full"):
            st6, e6 = _safe(lambda: am.settle(root=r6, force=True))
        ok(e6 is None and st6 is not None and st6["effective"] == "confirm"
           and st6.get("error") is None,
           "G6 含溢出行的库 settle：容错生效（读数正常判不满足 ⇒ 回落 confirm、"
           "非结算失败态；补强前直接崩）",
           {"eff": (st6 or {}).get("effective"), "err": e6})
    finally:
        adm.gate = live_gate
        am.reset_settlement()


_GROUPS = (g_a, g_b, g_c, g_d, g_e, g_f, g_g)


def _run_groups() -> int:
    """跑全部断言组（静默），返回失败数——供变异自证复用。"""
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        g()
    return len(_FAIL)


# =============================================================== 定点变异自证
# 表内每项 = (说明, 目标, 锚点原文, 替换文, 预期红项数)。锚点须**逐字**出现在
# 目标函数源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。
# 目标 = ("mod", 模块对象, 函数名) 或 ("attr", 模块对象, 属性名)（常量型变异，
# 与 test_autonomy_modes.py 同口径）。
_SRC_MUTATIONS = (
    # ① R1 占比阈值放宽——「恰 90% 不满足」的判据失去判别力。
    # 红 2：A2（恰 90% 转满足）+ F0（常量与设计规格同值断言——阈值声明被改）。
    ("R1 占比阈值放宽（0.90→1.01）", "attr", adm, "R1_MAX_SHARE",
     "R1_MAX_SHARE = 0.90", "1.01", 2),
    # ② R1 三态判据摘除——「缺 DEFER」仍判满足。
    ("R1 三态判据摘除（missing_verdicts 恒空）", "mod", adm,
     "r1_non_degenerate",
     '    missing_verdicts = [v for v, n in seen.items() if n < R1_MIN_ONE]',
     '    missing_verdicts = []', 1),
    # ③ R1 窗口失效——窗外记录混入窗口统计。
    ("R1 30 天窗失效（窗外记录混入）", "mod", adm, "r1_non_degenerate",
     '            if 0 <= (now - t) <= WINDOW_LONG_D * DAY:',
     '            if True:', 1),
    # ④ R2 组合判据只剩长期——「3 天外 30 天内」被误判满足。
    # 红 2：B2 与 B4 都在钉「短期不足 ⇒ 不满足」（长期满足不能救）。
    ("R2 组合判据只剩长期（short_ok 摘除）", "mod", adm, "r2_says_no",
     '    ok = bool(short_ok and long_ok)', '    ok = bool(long_ok)', 2),
    # ⑤ R2 短期窗口缩短——3 天窗边界的窗外记录混入。
    # 红 2：B3（3 天边界用例：边界数据是字面量，不随常量漂移）+ F0。
    ("R2 短期窗口缩短（3 天→1 天）", "attr", adm, "WINDOW_SHORT_D",
     "WINDOW_SHORT_D = 3", "1", 2),
    # ⑥ R3 D 面「更早 forget」判据摘除——只有 restore 也被当「回过」。
    ("R3 D 面成对判据摘除（无更早 forget 也计入）", "mod", adm,
     "r3_reversible",
     '                if ft is not None and ft < t and lo <= t <= now:',
     '                ft = ft if ft is not None else t\n'
     '                if lo <= t <= now:', 1),
    # ⑦ R3 C/B 面「盘面==前像」判据摘除——执行未回滚也被当「回过」。
    ("R3 C/B 面盘面判据摘除（未回滚也计入）", "mod", adm, "r3_reversible",
     '        if a != b:\n            continue',
     '        if False:\n            continue', 1),
    # ⑧ R3 30 天窗失效——窗外 restore 混入。
    ("R3 30 天窗失效（窗外 restore 混入）", "mod", adm, "r3_reversible",
     '                if ft is not None and ft < t and lo <= t <= now:',
     '                if ft is not None and ft < t:', 1),
    # ⑨ R4 严格下降放宽为不增——持平被误判收敛。
    ("R4 严格下降放宽为不增（持平也判下降）", "mod", adm, "r4_converging",
     '        strictly_down = rates_asc[0] > rates_asc[1] > rates_asc[2]',
     '        strictly_down = rates_asc[0] >= rates_asc[1] >= rates_asc[2]', 1),
    # ⑩ R4 最近窗阈值放宽——「恰 20%」被误判满足。
    # 红 2：D2（恰 20% 转满足）+ F0（常量与设计规格同值断言）。
    ("R4 最近窗阈值放宽（0.20→1.01）", "attr", adm, "R4_MAX_RATE",
     "R4_MAX_RATE = 0.20", "1.01", 2),
    # ⑪ R4 不可判分支摘除——样本不足被当成「不收敛」（非如实）。
    ("R4 不可判分支摘除（样本不足判 False）", "mod", adm, "r4_converging",
     '        ok = None\n        detail = ("30 天内子窗样本不足',
     '        ok = False\n        detail = ("30 天内子窗样本不足', 1),
    # ⑫ 准入闸恒放行——full+不满足仍报 full（放权失控形态）。
    # 红 7（补强批次校准 6→7）：E2/E2a/E2b/E2d（回落与告警整组失效）+ E8
    # （decide 判 allow 而非 confirm）+ F2（显式 root 结算不再回落）+ G6
    # （含溢出行的库在恒放行下报 full 而非 confirm）。E2c（alerts detail 非空）
    # 在 alerts=[] 时空列表全真、语义相符不红。
    ("准入闸恒放行（settle 不查读数）", "mod", am, "settle",
     '    if r["ok"]:', '    if True:', 7),
    # ⑬ 准入闸告警静默——回落但 alerts 为空（静默降级形态）。
    ("准入闸告警静默（alerts 恒空）", "mod", am, "settle",
     '        alerts = [{"reading": rd["id"], "ok": rd["ok"], "detail": rd["detail"]}\n'
     '                  for rd in r["readings"] if rd["ok"] is not True]',
     '        alerts = []', 1),
    # ⑭ 生效档位折算摘除——mode() 恒返回配置档位（回落不可见）。
    # 红 3（补强批次校准 2→3）：E2b + E8 + G3b（异常回落后 mode() 应 confirm，
    # 折算摘除后恒返回配置档位 full）。
    ("生效档位折算摘除（mode 不读结算态）", "mod", am, "mode",
     '    if (m == MODE_FULL and environ is None\n'
     '            and _SETTLEMENT["configured"] == MODE_FULL\n'
     '            and _SETTLEMENT["effective"]):',
     '    if False:', 3),
    # ⑮ 读数缓存失效——每次结算都全扫（「不得每次 decide 全库扫描」被破坏）。
    ("读数缓存失效（gate 每次重算）", "mod", adm, "gate",
     '    if ent is not None and not force and (t - ent["t"]) <= ttl:',
     '    if False:', 1),
    # ⑯ 补强批次：数值容错摘除（`_as_ts` 不再兜 float(v) 的溢出/非有限值）
    # ——含 400 位整数 t 的数据面回到「读数抛 OverflowError」的旧形态。
    # 红 10（补强批次实测）：G1/G1a（逐型）+ G2/G2a/G2b/G2c/G2d/G2e/G2f
    # （四条读数与 check 不崩/undated）+ G6（溢出库 settle 转失败态）。
    ("数值容错摘除（_as_ts 不再兜溢出/非有限值）", "mod", adm, "_as_ts",
     '    try:\n'
     '        f = float(v)\n'
     '    except (OverflowError, ValueError, TypeError):\n'
     '        return None',
     '    f = float(v)', 10),
    # ⑰ 补强批次：结算失败态放行为 full（异常当满足，fail-open 新形态）。
    # 红 2（补强批次实测）：G3（未结算格 effective 非 confirm）+ G3b
    # （mode() 非 confirm）。
    ("结算失败态放行为 full（异常当满足）", "mod", am, "settle",
     '        eff = prev or MODE_CONFIRM', '        eff = MODE_FULL', 2),
    # ⑱ 补强批次：结算失败态总是回落 confirm——「已成功结算 ⇒ 不升不降」
    # 被破（已结算 full 的进程被无据降档）。
    # 红 2（补强批次实测）：G3d（effective 不再保持 full）+ G3e（mode() 不再 full）。
    ("结算失败态总是回落 confirm（不升不降被破）", "mod", am, "settle",
     '        eff = prev or MODE_CONFIRM', '        eff = MODE_CONFIRM', 2),
    # ⑲ 补强批次：结算异常不捕获（回到旧 fail-open 形态：异常传播、结算态不
    # 更新 ⇒ 未结算进程 mode() 照常 full）。
    # 红 6（补强批次实测）：G3/G3a/G3b/G3c（未结算格失败态整组缺）+ G3d/G3e
    # （已结算格失败态缺；G3d0/G4/G5/G6 语义相符仍绿）。
    ("结算异常不捕获（旧 fail-open 形态）", "mod", am, "settle",
     '    except Exception as exc:', '    except () as exc:', 6),
)


def _fn_src(target):
    """变异锚点所在源码：`mod` = 目标函数源码；`attr` = 属主源码（模块整体）。"""
    kind, owner, name = target
    if kind == "attr":
        return inspect.getsource(owner)
    return inspect.getsource(getattr(owner, name))


def _strip_indent(text: str, n: int) -> str:
    """按 n 列去缩进（首 n 列全空白的行才截，其余行 lstrip）。"""
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
    """返回 ANCHOR-MISS 说明列表（空 = 全部在位）。"""
    bad = []
    for name, kind, owner, name_or_f, old, _new, _n in _SRC_MUTATIONS:
        if old not in _fn_src((kind, owner, name_or_f)):
            bad.append("变异锚点缺失：%r @%s.%s"
                       % (old[:40], owner.__name__, name_or_f))
    return bad


@contextlib.contextmanager
def _patched(target, old, new):
    """把目标函数按字面替换变异后安装/还原（不落盘、不改源文件）。"""
    kind, owner, name = target
    if kind == "attr":
        live = getattr(owner, name)
        setattr(owner, name, eval(new, dict(vars(owner))))    # noqa: S307
        try:
            yield
        finally:
            setattr(owner, name, live)
        return
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
    exec(compile(src, "adm_mut.py", "exec"), ns)
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
    _RUN[0] = 10 ** 6      # 变异轮用独立子根（防读到上一轮盘面）
    for name, kind, owner, name_or_f, old, new, expect in _SRC_MUTATIONS:
        _RUN[0] += 1
        try:
            with _patched((kind, owner, name_or_f), old, new), \
                    contextlib.redirect_stdout(io.StringIO()):
                fails = _run_groups()
        except Exception as exc:        # noqa: BLE001 —— 变异把路径打断也算「红」
            fails = -1
            print("  变异「%s」→ 断言链抛异常 %s: %s（判 FAIL）"
                  % (name, type(exc).__name__, str(exc)[:80]))
        verdict = ("命中预期" if fails == expect
                   else "**红项数不符（预期 %d）**" % expect)
        print("  变异「%s」→ 红项=%d  %s" % (name, fails, verdict))
        for f in _FAIL[:8]:
            print("      红:", f)
        if len(_FAIL) > 8:
            print("      …（余 %d 项）" % (len(_FAIL) - 8))
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
    print("\n准入读数与准入闸守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("    红:", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
        os.environ.pop(_ENV_MODE, None)
        if _OLD_POLICY is not None:
            os.environ["MDCG_POLICY_FILE"] = _OLD_POLICY
    sys.exit(rc)
