# -*- coding: utf-8 -*-
"""M4 落库治理自测（确定性部分）：rule 驱动靶子 + 来源链 + 五纪律 + CLI。

真源：docs/记忆评审系统_立项设计与施工交接_20260915.md §3 第 4 级 + §6 验收 + §7 负面清单。

纪律（同 test_mr_m1/m2/m3）：
  · **自备数据源**——合成节点 + tempfile 合成库，零依赖真源库（外部 clone 全绿）。
  · **零删除实锤**——全相位跑完节点集合只增不减（M4 只写 frontmatter 一个字段）。
  · **不猜**——无来源记 `unfillable` + 原因分布；域外值**停止降级**；工作角色不被推断。
  · **可回滚**——写入值即回滚锚点；当前值被人工改动 → `conflict` 不覆盖。

覆盖：A 靶子定位（rule 驱动，引擎不写死）  B 取值推导（只搬运已声明证据）
      C 预演（零写入）  D 执行（写前重查 / 留痕 / 幂等 / 零删除）
      E 回滚（还原 / 删键 / 冲突）  F CLI（fail-closed）
      G 对照口径（复用 conformance，不复刻判据）
运行：python -m md_cg.test_mr_m4
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile

from . import conformance as CF
from . import crypto
from . import nodefile as NF
from .mdcos import MdCGOS
from .mreview import govern as GV

PASS = FAIL = SKIP = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print("  FAIL %s" % label)


def skip(label):
    global SKIP
    SKIP += 1
    print("  SKIP %s" % label)


# ---------------------------- 合成库 ----------------------------

BODY = ("# 功能名：示例能力\n# 生效条件：载体/位置：本地仓；时间：全时窗（任意时刻成立）；"
        "方法：test；约束：无\n# 子功能：a/b\n# 执行：python -m md_cg.demo\n"
        "# 验证方式：test\n# 不适用条件：无\n正文。")
LOCKED = crypto.ENC_PREFIX + "QUJDREVG" + crypto.ENC_SUFFIX


def mkroot(root, nodes):
    """合成认知图根：`_index.json` + 节点盘文件（与 test_mr_m3 同范式）。"""
    os.makedirs(root, exist_ok=True)
    idx = {}
    for nid, spec in nodes.items():
        fm = dict(spec.get("fm") or {})
        fm.setdefault("id", nid)
        content = spec.get("content")
        content = BODY if content is None else content
        rel = spec.get("path") or ("%s/%s.md" % (spec.get("layer") or "knowledge", nid))
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(NF.dumps(fm, content))
        meta = dict(spec.get("meta") or {})
        meta.update({"id": nid, "path": rel,
                     "layer": spec.get("layer") or "knowledge"})
        if "role" in fm:
            meta["role"] = fm["role"]
        idx[nid] = meta
    with open(os.path.join(root, CF.INDEX_FILE), "w", encoding="utf-8") as f:
        json.dump({"nodes": idx}, f, ensure_ascii=False)
    return root


def snapshot(root):
    out = {}
    for dp, _dns, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = hashlib.md5(f.read()).hexdigest()
    return out


def disk_role(root, nid, layer="knowledge"):
    p = os.path.join(root, layer, "%s.md" % nid)
    with open(p, encoding="utf-8") as f:
        fm, _c = NF.loads(f.read())
    return fm


def base_nodes():
    """六类靶面各一条：成文标签 / writer / 无声明 / 已有值 / 域外 / 密文 + 域外层。"""
    return {
        "k1": {"fm": {"tags": ["role:knowledge", "主题"]}},
        "k2": {"fm": {"writer": "dsh-memory"}},
        "k3": {"fm": {"tags": ["无声明"]}},
        "k4": {"fm": {"role": "user", "tags": ["role:knowledge"]}},
        "k5": {"fm": {"tags": ["role:工具"]}},
        "k6": {"content": LOCKED},
        "c1": {"fm": {"tags": ["role:knowledge"]}, "layer": "contextual"},
    }


def rm(path):
    shutil.rmtree(path, ignore_errors=True)


# ---------------------------- A 组：靶子定位（rule 驱动）----------------------------

def phase_a(tmp):
    print("[A] 靶子定位（规则库是靶子唯一真源，引擎不写死）")
    rule = GV.role_rule()
    ok(rule["rule_id"] == "R-ROLE-MISSING" and rule["field"] == "role",
       "A1 从真规则库取到靶规则（field=%s）" % rule["field"])
    ok(rule["layers"] == ["knowledge"], "A2 作用域取自 matcher.layer（%s）" % rule["layers"])
    ok(rule["field"] == "role",
       "A3 字段名取自 mechanical[%s].field（不写死）" % GV.CHECK_FIELD_ABSENT)

    # 规则库可替换：换成临时规则库（field=其他字段）→ 引擎随之改靶，零代码改动
    d = os.path.join(tmp, "rules")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "x.json"), "w", encoding="utf-8") as f:
        json.dump({"rules": [{"id": "R-ROLE-MISSING", "title": "改靶", "severity": "INFO",
                              "matcher": {"layer": ["contextual"]},
                              "mechanical": [{"check": "field_absent", "field": "owner"}]}]}, f)
    r2 = GV.role_rule(rules_dir=d)
    ok(r2["field"] == "owner" and r2["layers"] == ["contextual"],
       "A4 改数据即改靶（field=%s layers=%s），引擎零改动" % (r2["field"], r2["layers"]))

    for bad, label in (({"rules": []}, "A5 规则库无该规则 → ValueError（靶子失效必须红灯）"),
                       ({"rules": [{"id": "R-ROLE-MISSING", "severity": "INFO",
                                    "mechanical": [{"check": "field_absent", "field": "role"}]}]},
                        "A6 规则缺 matcher.layer → ValueError"),
                       ({"rules": [{"id": "R-ROLE-MISSING", "severity": "INFO",
                                    "matcher": {"layer": ["knowledge"]}, "mechanical": []}]},
                        "A7 规则缺 field_absent.field → ValueError")):
        try:
            GV.role_rule(rules=bad)
            ok(False, label + "（未抛错）")
        except ValueError:
            ok(True, label)

    root = mkroot(os.path.join(tmp, "a"), base_nodes())
    try:
        GV.role_plan(root, layer="contextual")
        ok(False, "A8 跨层收窄应抛错（绝不跨层套用）")
    except ValueError:
        ok(True, "A8 跨层收窄抛错（绝不跨层套用）")
    rep = GV.role_plan(root, layer="knowledge")
    ok(rep["rule_layers"] == ["knowledge"] and rep["skipped_out_of_scope"] == 1,
       "A9 层内收窄不抛错，域外条数如实上报（%d）" % rep["skipped_out_of_scope"])


# ---------------------------- B 组：取值推导 ----------------------------

def phase_b(tmp):
    print("[B] 取值推导（只搬运已声明证据，绝不编造）")
    root = mkroot(os.path.join(tmp, "b"), base_nodes())

    # 默认档（tags + map），map 需显式补表（WRITER_ROLE_MAP 故意为空）
    p = GV.role_plan(root)
    ok(GV.SOURCE_LAYER not in p["sources"],
       "B1 默认档不含 layer_default（%s）——不得用常量填满指标" % (p["sources"],))
    ok(p["by_source"] == {"tags": 1}, "B2 默认档只认成文标签（%s）" % p["by_source"])
    ok(p["unfillable_by_reason"].get(GV.REASON_NO_SOURCE) == 1,
       "B3 无任何声明 → no_source_declared（不猜）")
    ok(p["unfillable_by_reason"].get(GV.REASON_WRITER_NO_MAP + ":dsh-memory") == 1,
       "B4 writer 有值但映射表空 → writer_no_mapping:<writer>（待终裁补表）")
    ok(p["unfillable_by_reason"].get(GV.REASON_TAG_OOD + ":工具") == 1,
       "B5 域外标签值如实上报（%s）" % p["unfillable_by_reason"])
    ok(p["skipped_present"] == 1, "B6 已有 role 值者不重复回填")
    ok(p["skipped_locked"] == 1, "B7 密文节点跳过（绝不解密回写）")

    # ① tags 成文声明优先且直取
    p2 = GV.role_plan(root, ids=["k1"], sources=("tags", "map", "layer_default"))
    it = p2["items"][0]
    ok(it["role"] == "knowledge" and it["source"] == "tags",
       "B8 tags 声明直取（%s / %s）" % (it["role"], it["source"]))
    ok(it["basis"] == GV.BASIS_TAG, "B9 依据落在 basis（可审计，%s）" % it["basis"])

    # ② map 档：显式补表才生效
    p3 = GV.role_plan(root, role_map={"dsh-memory": "knowledge"})
    ok(p3["by_source"] == {"tags": 1, "map": 1},
       "B10 映射表补声明后 map 档生效（%s）" % p3["by_source"])
    ok(p3["unfillable_by_reason"].get(GV.REASON_WRITER_NO_MAP + ":dsh-memory") is None,
       "B11 补表后原 writer_no_mapping 消失（原因分布随声明变化）")

    # ② OOD：映射表写域外值 → 停止降级
    p4 = GV.role_plan(root, role_map={"dsh-memory": "不存在的角色"})
    ok(p4["unfillable_by_reason"].get(GV.REASON_MAP_OOD + ":不存在的角色") == 1,
       "B13 映射表域外值 → map_role_out_of_domain（%s）" % p4["unfillable_by_reason"])

    # ② 工作角色：映射表写 tool-output → 拒绝（不许把知识节点摘出默认召回）
    p5 = GV.role_plan(root, role_map={"dsh-memory": "tool-output"})
    ok(p5["unfillable_by_reason"].get(GV.REASON_MAP_WORK + ":tool-output") == 1,
       "B14 映射表推成工作角色 → 拒绝（%s）" % p5["unfillable_by_reason"])
    ok(p5["targeted"] == 1 and p5["by_source"] == {"tags": 1},
       "B15 工作角色被拒后**不**回退到其它档（拒绝即终态）")

    # ③ layer_default：显式开启才可用
    p6 = GV.role_plan(root, sources=("tags", "map", "layer_default"))
    ok(p6["by_source"].get("layer_default") == 2,
       "B16 layer_default 档显式开启后生效（%s）" % p6["by_source"])
    ok(p6["targeted"] > p["targeted"], "B17 开启后靶面扩大（%d → %d）"
       % (p["targeted"], p6["targeted"]))

    # tags 域外值不因开启更多档而降级
    p7 = GV.role_plan(root, ids=["k5"], sources=("tags", "map", "layer_default"))
    ok(p7["targeted"] == 0 and p7["unfillable_by_reason"].get(GV.REASON_TAG_OOD + ":工具") == 1,
       "B18 标签域外值在最强档下仍不降级（显式声明 ≠ 无声明）")


# ---------------------------- C 组：预演（零写入）----------------------------

def phase_c(tmp):
    print("[C] 预演（零写入）")
    root = mkroot(os.path.join(tmp, "c"), base_nodes())
    GV.role_plan(root)                       # 预热（首建实例可能补索引）
    before = snapshot(root)
    GV.role_plan(root, sources=GV.ALL_SOURCES)
    GV.role_stats(root)
    GV.history(root)
    ok(snapshot(root) == before, "C1 预演 / 统计 / 留痕读全程零写入（指纹不变）")

    p = GV.role_plan(root, sources=GV.ALL_SOURCES)
    ok(p["dry_run"] is True and p["action"] == GV.ACTION_ROLE, "C2 预演自报只读")
    ok(p["nodes_scanned"] == 6 and p["skipped_out_of_scope"] == 1,
       "C3 扫描面=层内 6 / 域外 1（%d/%d）" % (p["nodes_scanned"], p["skipped_out_of_scope"]))
    ok(p["targeted"] == 3, "C4 最强档靶面 3 条（%d）" % p["targeted"])

    p2 = GV.role_plan(root, sources=GV.ALL_SOURCES, limit=2)
    ok(len(p2["items"]) == 2 and p2["targeted"] == 3,
       "C5 limit 只截清单不动靶面（items=%d targeted=%d）" % (len(p2["items"]), p2["targeted"]))

    p3 = GV.role_plan(root, ids=["k3"])
    ok(p3["nodes_scanned"] == 1 and p3["skipped_out_of_scope"] == 0,
       "C6 ids 收窄同时收窄扫描面与域外计数")
    p4 = GV.role_plan(root, prefix="k1")
    ok(p4["nodes_scanned"] == 1, "C7 prefix 收窄（%d）" % p4["nodes_scanned"])
    p5 = GV.role_plan(root, sources=GV.ALL_SOURCES, sample=2)
    ok(len(p5.get("sample") or []) == 2, "C8 sample 抽样（%s）" % p5.get("sample"))
    ok(p5["planned_ids"] == [i["id"] for i in p5["items"]],
       "C9 planned_ids 与清单同源（%s）" % p5["planned_ids"])


# ---------------------------- D 组：执行 ----------------------------

def write_node(root, nid, fm, layer="knowledge", content=None):
    p = os.path.join(root, layer, "%s.md" % nid)
    with open(p, encoding="utf-8") as f:
        _fm, c = NF.loads(f.read())
    with open(p, "w", encoding="utf-8") as f:
        f.write(NF.dumps(fm, c if content is None else content))


def idx_role(root, nid):
    with open(os.path.join(root, CF.INDEX_FILE), encoding="utf-8") as f:
        return (json.load(f)["nodes"].get(nid) or {}).get("role")


def phase_d(tmp):
    print("[D] 执行（写前重查 / 留痕 / 幂等 / 零删除）")
    root = mkroot(os.path.join(tmp, "d"), base_nodes())
    files0 = set(snapshot(root))
    c1_0 = snapshot(root).get("contextual/c1.md")

    rep = GV.role_apply(root, role_map={"dsh-memory": "knowledge"},
                        batch="b1", actor="tester")
    ok(rep["written"] == 2 and rep["by_source"] == {"tags": 1, "map": 1},
       "D1 写入 2 条（%s）" % rep["by_source"])
    ok(disk_role(root, "k1")["role"] == "knowledge", "D2 tags 档写盘生效")
    ok(disk_role(root, "k2")["role"] == "knowledge", "D3 map 档写盘生效")
    ok("role" not in disk_role(root, "k3"), "D4 无来源者不写（宁可缺失不猜）")
    ok("role" not in disk_role(root, "k6"), "D5 密文节点不写")
    ok(idx_role(root, "k1") == "knowledge",
       "D6 role 进索引（覆盖率判据据此可算）")
    ok(idx_role(root, "k3") is None, "D7 未回填者索引也无值（盘/索引一致）")

    h = GV.history(root, action=GV.ACTION_ROLE)
    rec = [r for r in h["records"] if r["node"] == "k1"][0]
    ok(all(k in rec for k in ("batch", "actor", "write_id", "entry_id", "value",
                              "source", "basis", "fm_before", "layer", "rule_id")),
       "D8 留痕字段完整（回滚凭据齐备）")
    ok(rec["fm_before"] == {"role": None, "had_key": False},
       "D9 留痕记下写前态（原本无键）")
    ok(bool(rec["write_id"]) and len(rec["entry_id"]) == 12,
       "D10 write_id / entry_id 齐备（回滚去重与对账凭据）")

    rep2 = GV.role_apply(root, role_map={"dsh-memory": "knowledge"}, batch="b1")
    ok(rep2["written"] == 0 and rep2["skipped_drift"] == 0,
       "D11 幂等：重跑零写入（已有值在预演面即被 present 拦截）")

    orig = GV.role_plan

    def patched(x, **kw):
        r = orig(x, **kw)
        for it in r["items"]:                     # 预演→执行之间模拟他人改动
            if it["id"] == "k3":
                fm = disk_role(root, "k3")
                fm["role"] = "assistant"
                write_node(root, "k3", fm)
        return r

    GV.role_plan = patched
    try:
        rep3 = GV.role_apply(root, ids=["k3"], sources=GV.ALL_SOURCES, batch="b2")
    finally:
        GV.role_plan = orig
    ok(rep3["written"] == 0 and rep3["skipped_drift"] == 1,
       "D12 写前重查：预演后被人改动 → 不覆盖（written=%d drift=%d）"
       % (rep3["written"], rep3["skipped_drift"]))
    ok(disk_role(root, "k3")["role"] == "assistant", "D13 漂移节点保持他人值")

    ok(set(snapshot(root)) >= files0 and snapshot(root).get("contextual/c1.md") == c1_0,
       "D14 零删除：文件集合只增不减、域外节点零触碰")
    with open(os.path.join(root, CF.INDEX_FILE), encoding="utf-8") as f:
        ok(len(json.load(f)["nodes"]) == 7, "D15 治理后节点总数不变（7）")

    r2 = mkroot(os.path.join(tmp, "d2"), {
        "a1": {"fm": {"tags": ["role:user"]}},
        "a2": {"fm": {"tags": ["role:knowledge"]}},
        "a3": {"fm": {"tags": ["role:developer"]}}})
    p = GV.role_plan(r2)
    eid = [i for i in p["items"] if i["id"] == "a2"][0]["entry_id"]
    rep4 = GV.role_apply(r2, entry_ids=[eid], batch="b3")
    ok(rep4["written"] == 1 and disk_role(r2, "a2")["role"] == "knowledge",
       "D16 entry_ids 工单式精确执行（只写 1 条）")
    ok("role" not in disk_role(r2, "a1") and "role" not in disk_role(r2, "a3"),
       "D17 工单外节点零触碰")
    ok(rep4["plan_remaining"] == 2, "D18 余量如实上报（%d）" % rep4["plan_remaining"])
    ok(rep4["entry_ids"] == [eid], "D19 留痕回执带 entry_id（可对账）")


# ---------------------------- E 组：回滚 ----------------------------

def phase_e(tmp):
    print("[E] 回滚（还原 / 删键 / 冲突）")
    root = mkroot(os.path.join(tmp, "e"), {
        "a1": {"fm": {"tags": ["role:user"]}},
        "a2": {"fm": {"tags": ["role:knowledge"], "role": ""}},
        "a3": {"fm": {"tags": ["role:developer"]}}})
    had = disk_role(root, "a2")
    ok("role" in had and GV._blank(had.get("role")),
       "E1 空串 role：键在值空 → 视为缺失（键存在性也要还原，%r）" % had.get("role"))
    p0 = GV.role_plan(root)
    ok(p0["targeted"] == 3 and p0["skipped_present"] == 0,
       "E2 空串节点仍入靶面（targeted=%d）" % p0["targeted"])
    base = GV.role_stats(root)["role_ratio_kn"]

    rep = GV.role_apply(root, batch="e1", actor="t")
    ok(rep["written"] == 3, "E3 三条写入（%d）" % rep["written"])
    ratios_after = GV.role_stats(root)["role_ratio_kn"]
    ok(ratios_after > base, "E4 覆盖率上升（%.4f → %.4f）" % (base, ratios_after))
    ok(GV.role_stats(root)["by_value"] == {"user": 1, "knowledge": 1, "developer": 1},
       "E5 逐值分布正确（%s）" % GV.role_stats(root)["by_value"])

    fm = disk_role(root, "a1")                     # 人工覆盖 → 回滚必须让路
    fm["role"] = "assistant"
    write_node(root, "a1", fm)
    rb = GV.role_rollback(root, batch="e1", actor="t")
    ok(rb["reverted"] == 2 and rb["conflict"] == 1,
       "E6 人工改动者计 conflict 不覆盖（reverted=%d conflict=%d）"
       % (rb["reverted"], rb["conflict"]))
    ok(disk_role(root, "a1")["role"] == "assistant", "E7 冲突节点保持人工值")
    ok("role" not in disk_role(root, "a3"), "E8 原本无键 → 删键还原（不写空串）")
    ok("role" in disk_role(root, "a2") and GV._blank(disk_role(root, "a2").get("role")),
       "E9 原本空值 → 还原空值且键仍在（%r）" % disk_role(root, "a2").get("role"))
    ok(idx_role(root, "a3") is None, "E10 索引随回滚同步（role 清空）")

    rb2 = GV.role_rollback(root, batch="e1", actor="t")
    ok(rb2["reverted"] == 0 and rb2["skipped_done"] == 2 and rb2["conflict"] == 1,
       "E11 重复回滚凭 write_id 去重（skipped_done=%d）" % rb2["skipped_done"])
    ok(GV.role_stats(root)["by_value"] == {"assistant": 1},
       "E12 回滚后仅剩人工值（%s）" % GV.role_stats(root)["by_value"])


# ---------------------------- F 组：CLI（fail-closed）----------------------------

def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = GV.main(argv)
    return rc, out.getvalue(), err.getvalue()


def phase_f(tmp):
    print("[F] CLI（fail-closed）")
    root = mkroot(os.path.join(tmp, "f"), base_nodes())
    env_bak = os.environ.pop("MDCG_ROOT", None)
    try:
        ok(run_cli(["plan", "--root", root])[0] == 0, "F1 plan 退出码 0")
        ok(run_cli(["plan"])[0] == 2, "F2 无 root → 2（fail-closed）")
        ok(run_cli([])[0] == 2, "F3 无子命令 → 2（print_help）")
        ok(run_cli(["apply", "--root", root])[0] == 2,
           "F4 apply 无 --yes → 2（写盘须显式确认）")
        ok(run_cli(["rollback", "--root", root])[0] == 2,
           "F5 rollback 无范围 → 2（防全量误回滚）")
        ok(run_cli(["plan", "--root", root, "--sources", "tags,bogus"])[0] == 2,
           "F6 来源档域外 → 2（不静默降级）")
        ok(run_cli(["plan", "--root", root, "--layer", "contextual"])[0] == 2,
           "F7 跨层收窄 → 2（异常不得裸奔）")

        rc, out, err = run_cli(["apply", "--root", root, "--yes", "--batch", "cli1",
                                "--sources", "tags,map,layer_default"])
        ok(rc == 0 and GV.LAYER_DEFAULT_WARNING[:14] in err,
           "F8 layer_default 开启时 stderr 透出终裁提示")
        ok(disk_role(root, "k3")["role"] == "knowledge", "F9 CLI apply 生效")
        ok(GV.history(root, batch="cli1")["total"] == 3,
           "F10 CLI 留痕按批次可查（%d）" % GV.history(root, batch="cli1")["total"])

        rc, out, _e = run_cli(["plan", "--root", root, "--ids", "k1", "--json"])
        ok(rc == 0 and json.loads(out)["nodes_scanned"] == 1,
           "F11 plan --json 可机读（M4 报告引用面）")
        rc, out, _e = run_cli(["history", "--root", root, "--json"])
        ok(rc == 0 and json.loads(out)["total"] >= 3, "F12 history --json 可机读")
        rc, out, _e = run_cli(["rollback", "--root", root, "--batch", "cli1"])
        ok(rc == 0 and "还原" in out, "F13 CLI rollback 人读摘要可读（%s）" % out.split("\n")[0])
        ok("role" not in disk_role(root, "k3"), "F14 CLI 回滚生效（键被删除）")
    finally:
        if env_bak is not None:
            os.environ["MDCG_ROOT"] = env_bak


# ---------------------------- G 组：对照口径 ----------------------------

def phase_g(tmp):
    print("[G] 对照口径（复用 conformance，不复刻判据）")
    root = mkroot(os.path.join(tmp, "g"), base_nodes())
    st = GV.role_stats(root)
    ok(st["threshold"] == float(CF.THRESHOLDS["role_coverage_min"]),
       "G1 阈值直接取自 conformance（%s）" % st["threshold"])
    mine = CF._coverage_metrics(CF.load_index(root)).get("role_ratio_kn")
    ok(st["role_ratio_kn"] == mine, "G2 覆盖率与 conformance 逐位一致（%s）" % mine)
    ok(st["target_met"] is False and st["gap_to_target"] > 0,
       "G3 未达标时如实上报缺口（%.4f）" % st["gap_to_target"])

    GV.role_apply(root, role_map={"dsh-memory": "knowledge"}, batch="g1")
    st2 = GV.role_stats(root)
    ok(st2["role_ratio_kn"] > st["role_ratio_kn"],
       "G4 治理后覆盖率变化可量化（%.4f → %.4f）"
       % (st["role_ratio_kn"], st2["role_ratio_kn"]))
    ok(st2["by_layer"].get("knowledge") == 6,
       "G5 逐层分布（knowledge=%s）" % st2["by_layer"].get("knowledge"))

    try:
        GV.run(root, "role_bogus")
        ok(False, "G6 未知 action → ValueError")
    except ValueError:
        ok(True, "G6 未知 action → ValueError（入口防呆）")
    ok(GV.run(root, "role", apply=False)["dry_run"] is True,
       "G7 run(apply=False) 走预演（默认不写）")
    ok(GV.run(root, "role_stats")["action"] == "role_stats", "G8 run 分发到对照")


# ---------------------------- 入口 ----------------------------

def main():
    tmp = tempfile.mkdtemp(prefix="m4_govern_")
    try:
        for fn in (phase_a, phase_b, phase_c, phase_d, phase_e, phase_f, phase_g):
            fn(tmp)
    finally:
        rm(tmp)
    print("\nPASS %d  FAIL %d  SKIP %d" % (PASS, FAIL, SKIP))
    for f in FAILS:
        print("  - %s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
