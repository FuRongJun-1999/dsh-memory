# -*- coding: utf-8 -*-
"""治理写面读-改-写直读守卫（缺陷：读缓存默认开 × 治理 RMW 读点未走 direct_read）。

缺陷形态（缺陷报告 2026-09-25 复现证实，high）：读缓存默认开
（readcache.py:36-38 install 默认装配，mdcos.py:366-368 构造即装）后，
`cg._read` 是进程内脏代际快照——**只对本实例写路径失效**。治理面的
读-改-写（ccgc.link/recalibrate、crosscheck 主流程/回滚、
vision_evidence 执行/回滚）若在写前用 `cg._read` 重查节点，
则「A 常驻实例检索装载缓存 → B 另一实例以统一写口 `_write_node`
落盘修正 → A 同实例执行治理写」时，A 读到的是**装载时的旧快照**，
写回后 B 的修正被静默覆盖丢失（默认开组幸存=False；
MDCG_READ_CACHE=0 对照组幸存=True）。

修复口径（与第 7 轮 backfill 15 处 / mreview.govern 3 处一致）：
治理文件写前重查/回滚比对读点改走 `readcache.direct_read`
（穿透缓存读盘上真值）。本守卫先证旧代码红（G1-G6），再由修复转绿。

断言分两类：
  G1-G6  红守卫（cg/x 参数传入常驻实例 → 陈旧形态真实可达）：
         G1/G2 ccgc.recalibrate / link；G3/G4 crosscheck 主流程 / 回滚；
         G5/G6 vision_evidence.apply / rollback。
  G7-G12 口径守卫（consolidate 六读点为 root 入口内部自建**新实例**，
         单次调用内首触即盘上真值，先写 B 修正并不丢失——断言改为
         「direct_read 改动不破坏这些流程」，非红证明）。

运行：python -m md_cg.test_govern_directread
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

from . import ccgc, consolidate, crosscheck, vision_evidence
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []

MARK = "B实例的重要修正v1"
MARK2 = "B实例的重要修正v2"

CS_FULL = {
    "observation_position": "此功能在本地文件系统中生效",
    "observation_tool": "该方法使用扩展名映射表进行路由",
    "time_window": [0.0, 9999999999.0],
    "existence_constraint": "仅对本地可读文件生效",
}


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _disk(root, nid):
    """盘上真值直读：新实例首触（构造后未读该路径）即磁盘当前内容。"""
    cg = MdCGOS(root)
    e = (cg.index.get("nodes") or {}).get(nid)
    if not e:
        return None, None
    fn = getattr(cg, "_read_uncached", None) or cg._read
    return fn(e)


def _b_write(root, nid, marker):
    """B = 另一实例（全合作写者）：读盘上真值 → 加 fm 标记 → 统一写口落盘。"""
    b = MdCGOS(root)
    e = b.index["nodes"][nid]
    fm, content = b._read(e)              # B 新实例首触 = 盘上真值
    fm["owner_note"] = marker
    b._write_node(nid, os.path.join(root, e["path"]), fm, content,
                  durable=True)
    return marker


def _warm(a, nid):
    """A 常驻实例检索装载缓存（生产形态：search/_read 装配后常驻）。"""
    return a._read(a.index["nodes"][nid])


def _doc(fn, cond, sub, exe, va="", neg="问完全无关主题"):
    lines = [f"# 功能名：{fn}", f"# 生效条件：{cond}",
             f"# 子功能：{sub}", f"# 执行：{exe}"]
    if va:
        lines.append(f"# 验证方式：{va}")
    lines.append(f"# 不适用条件：{neg}")
    return "\n".join(lines) + "\n"


# ---- G1 ccgc.recalibrate（缺陷报告原样复现：ccgc.py:841 读 → :860 写）----

def g1_recalibrate(tmp):
    print("== G1 ccgc.recalibrate（缺陷原样复现） ==")
    root = os.path.join(tmp, "g1")
    os.makedirs(root)
    a = MdCGOS(root)
    a.add("gd_recal", "# 功能名：直读守卫节点\n\n正文。\n", layer="knowledge",
          condition_space=dict(CS_FULL))
    a.flush()
    _warm(a, "gd_recal")                    # A 装载缓存
    _b_write(root, "gd_recal", MARK)        # B 统一写口落盘重要修正
    fm_a, _ = _warm(a, "gd_recal")
    ok(fm_a.get("owner_note") is None,
       "G1a A 进程内缓存陈旧（治理写前重查命中旧代际）")
    rc = ccgc.recalibrate("gd_recal",
                          {"existence_constraint": "修正后的存在约束GD"},
                          "designer", "agent:a1", evidence="守卫复核",
                          cg=a, apply=True)
    ok(rc.ok and rc.written == 1, "G1b recalibrate 执行成功（含写入）")
    fm, _content = _disk(root, "gd_recal")
    ok(fm.get("owner_note") == MARK,
       "G1c B 修正幸存（写前重查走盘上真值，不被陈旧缓存覆盖）")
    ok((fm.get("condition_space") or {}).get("existence_constraint")
       == "修正后的存在约束GD", "G1d A 的治理写入仍生效")

    # 对照组：MDCG_READ_CACHE=0（退出阀）同流程 → 无陈旧，恒幸存
    os.environ["MDCG_READ_CACHE"] = "0"
    try:
        root0 = os.path.join(tmp, "g1_ctl")
        os.makedirs(root0)
        a0 = MdCGOS(root0)
        a0.add("gd_recal", "# 功能名：直读守卫节点\n\n正文。\n",
               layer="knowledge", condition_space=dict(CS_FULL))
        a0.flush()
        _warm(a0, "gd_recal")
        _b_write(root0, "gd_recal", MARK)
        rc0 = ccgc.recalibrate("gd_recal",
                               {"existence_constraint": "修正后的存在约束GD"},
                               "designer", "agent:a1", cg=a0, apply=True)
        fm0, _ = _disk(root0, "gd_recal")
        ok(rc0.ok and fm0.get("owner_note") == MARK,
           "G1e 对照组（缓存关）B 修正幸存——丢失由默认开缓存引入")
    finally:
        os.environ.pop("MDCG_READ_CACHE", None)


# ---- G2 ccgc.link（ccgc.py:757 读 → :784 写）----

DIALOG = ("文件摄取分派：按扩展名把文件路由到对应摄取器"
          "。该方法使用扩展名映射表进行路由"
          "。此功能在本地文件系统中生效"
          "。仅对本地可读文件生效"
          "。2026-09-16"
          "。通过回放测试验证"
          "。二进制文件不适用")

SLOTS = {
    "observation_position": {"value": "此功能在本地文件系统中生效"},
    "observation_tool": {"value": "该方法使用扩展名映射表进行路由"},
    "time_window": {"value": [0.0, 9999999999.0]},
    "existence_constraint": {"value": "仅对本地可读文件生效"},
}

MARKS = {
    "功能名": {"value": "文件摄取分派：按扩展名把文件路由到对应摄取器"},
    "子功能": {"value": "按扩展名把文件路由到对应摄取器"},
    "执行": {"value": "使用扩展名映射表进行路由"},
    "验证方式": {"value": "回放测试", "basis": "test"},
    "不适用条件": {"value": "二进制文件不适用"},
}


def g2_link(tmp):
    print("== G2 ccgc.link ==")
    root = os.path.join(tmp, "g2")
    os.makedirs(root)
    a = MdCGOS(root)
    a.add("gd_link", "# 功能名：待编译节点\n\n占位正文。\n", layer="knowledge")
    a.flush()
    _warm(a, "gd_link")
    _b_write(root, "gd_link", MARK)
    r = ccgc.compile_dialog(DIALOG, "gd_link", "agent:a1",
                            slots=SLOTS, marks=MARKS, cg=a)
    ok(r.success, "G2a 编译成功")
    a_ok = ccgc.attest("gd_link", ccgc.ACCEPT, "designer", "agent:a1",
                       evidence="守卫：候选与对话原文一致", cg=a)
    ok(a_ok.ok, "G2b 编外验证方签章")
    l = ccgc.link(r, a_ok, cg=a, apply=True)
    ok(l.ok and l.written == 6, "G2c link 写入六行")
    fm, _c = _disk(root, "gd_link")
    ok(fm.get("owner_note") == MARK, "G2d B 修正幸存（link 写前重查走直读）")
    ok(fm.get("condition_space") == {k: v["value"] for k, v in SLOTS.items()},
       "G2e link 自身写入仍生效（condition_space 落盘）")


# ---- G3/G4 crosscheck 主流程（:344/:786 读 → :674 写）与回滚（:941 读 → :970 写）----

SRC_MEASURE = ["《函数单调性基准集》v1 第 3 节"]
SCI_NAME = "数学·函数单调性判定"


def _verdict_rows(nid, value):
    return [
        {"id": nid, "unit": "reflect", "field": "验证方式", "value": value,
         "basis": "measurement", "source": SRC_MEASURE, "verdict": "accept"},
        {"id": nid, "unit": "verify", "field": "验证方式", "value": value,
         "verdict": "accept"},
    ]


def g3_crosscheck(tmp):
    print("== G3 crosscheck 主流程（写前重查） ==")
    root = os.path.join(tmp, "g3")
    os.makedirs(root)
    a = MdCGOS(root)
    a.add("gd_cc", _doc("函数单调性判定", "问单调性", "判定单调区间", "取导数定号"),
          layer="knowledge", state_attributes={"name": SCI_NAME})
    a.flush()
    _warm(a, "gd_cc")
    _b_write(root, "gd_cc", MARK)
    rep = crosscheck.crosscheck(a, ids=["gd_cc"],
                                verdicts=_verdict_rows("gd_cc",
                                                       "以基准函数集实测判定单调区间"),
                                apply=True, batch="gdxb", actor="guard")
    ok(rep["written"] == 1, f"G3a crosscheck 写入 1（实测 {rep['written']}）")
    fm, c = _disk(root, "gd_cc")
    ok(fm.get("owner_note") == MARK, "G3b B 修正幸存（:786 写前重查走直读）")
    ok(fm.get("verification_basis") == "measurement"
       and "# 验证方式：以基准函数集实测判定单调区间" in c,
       "G3c crosscheck 自身写入仍生效")
    return root


def g4_crosscheck_rollback(root):
    print("== G4 crosscheck.rollback（回滚比对） ==")
    a2 = MdCGOS(root)
    _warm(a2, "gd_cc")                       # A2 装载（含上一步 evidence 现场）
    _b_write(root, "gd_cc", MARK2)           # B 再落一笔修正
    rep2 = crosscheck.rollback(a2, batch="gdxb")
    ok(rep2["reverted"] == 1, f"G4a 回滚 1（实测 {rep2['reverted']}）")
    fm, c = _disk(root, "gd_cc")
    ok(fm.get("owner_note") == MARK2,
       "G4b B 修正幸存（:941 回滚比对走直读，write_id 防护所验 fm 为盘上真值）")
    ok(fm.get("verification_basis") is None
       and "# 验证方式：" not in c,
       "G4c 回滚自身仍生效（验证方式行/基底还原）")


# ---- G5/G6 vision_evidence.apply（:296/:495 读 → :522 写）与 rollback（:579 读 → :591 写）----

def g5_vision_apply(tmp):
    print("== G5 vision_evidence.apply ==")
    root = os.path.join(tmp, "g5")
    os.makedirs(root)
    aeis = os.path.join(tmp, "g5_aeis")      # 空归档目录（不触真实数据目录）
    os.makedirs(aeis)
    a = MdCGOS(root)
    a.add("imgpart_gd",
          "img9 部件 torso: bbox=[1, 1, 2, 2] cond_hash=eeee555566667777 "
          "verdict=ACCEPT reason=x fg=0.5\n",
          layer="contextual", tags=["vision", "img9", "part", "torso"])
    a.flush()
    _warm(a, "imgpart_gd")
    _b_write(root, "imgpart_gd", MARK)
    rep = vision_evidence.apply(a, aeis_root_=aeis)
    ok(rep["written"] >= 1, f"G5a 盲区落盘 ≥1（实测 {rep['written']}）")
    fm, _c = _disk(root, "imgpart_gd")
    ok(fm.get("owner_note") == MARK,
       "G5b B 修正幸存（:495 写前重查走直读）")
    ok(fm.get("evidence_status") is not None,
       "G5c 证据面写入仍生效")
    return root, rep["batch"]


def g6_vision_rollback(root, batch):
    print("== G6 vision_evidence.rollback ==")
    a2 = MdCGOS(root)
    _warm(a2, "imgpart_gd")
    _b_write(root, "imgpart_gd", MARK2)
    rep2 = vision_evidence.rollback(a2, batch=batch)
    ok(rep2["reverted"] >= 1, f"G6a 回滚 ≥1（实测 {rep2['reverted']}）")
    fm, _c = _disk(root, "imgpart_gd")
    ok(fm.get("owner_note") == MARK2, "G6b B 修正幸存（:579 回滚读走直读）")
    ok(fm.get("evidence_status") is None, "G6c 回滚自身仍生效（证据键清除）")


# ---- G7-G12 consolidate（口径守卫：root 入口内部自建新实例，非红证明）----

def g7_fill_verification_basis(tmp):
    print("== G7 consolidate.fill_verification_basis（口径） ==")
    root = os.path.join(tmp, "g7")
    os.makedirs(root)
    a = MdCGOS(root)
    a.add("gd_fvb", _doc("函数单调性判定", "问单调性", "判定单调区间", "取导数定号"),
          layer="knowledge")
    a.flush()
    _b_write(root, "gd_fvb", MARK)           # 先于调用的 B 写：新实例首触可见
    rep = consolidate.fill_verification_basis(root, "编译器/静态检查通过",
                                               apply=True)
    ok(rep["written"] == 1, f"G7a 补写 1（实测 {rep['written']}）")
    fm, c = _disk(root, "gd_fvb")
    ok(fm.get("owner_note") == MARK, "G7b B 修正幸存")
    ok("# 验证方式：编译器/静态检查通过" in c, "G7c 补写自身生效")


def _g89_root(tmp):
    root = os.path.join(tmp, "g8")
    os.makedirs(root)
    a = MdCGOS(root)
    a.add("gd_pro",
          "# 功能名：待提升节点\n# 生效条件：问提升\n# 子功能：说明提升\n"
          "# 执行：按热度\n# 不适用条件：问无关\n",
          layer="contextual", merge_count=2)
    a.flush()
    return root


def g8_promote(tmp):
    print("== G8/G9 consolidate.promote / rollback_promotion（口径） ==")
    root = _g89_root(tmp)
    _b_write(root, "gd_pro", MARK)
    rep = consolidate.promote_memories(root, min_merge=1, apply=True)
    ok(rep["written"] == 1, f"G8a 提升 1（实测 {rep['written']}）")
    fm, _c = _disk(root, "gd_pro")
    ok(fm.get("layer") == "knowledge", "G8b 已迁 knowledge")
    ok(fm.get("owner_note") == MARK, "G8c B 修正幸存")
    rep2 = consolidate.rollback_promotion(root)
    ok(rep2.get("ok") and rep2["reverted"] == 1,
       f"G9a 回滚 1（实测 {rep2})")
    fm2, _c2 = _disk(root, "gd_pro")
    ok(fm2.get("layer") == "contextual", "G9b 迁回 contextual")
    ok(fm2.get("owner_note") == MARK, "G9c B 修正幸存（回滚读走直读口径）")


def g10_contextualize(tmp):
    print("== G10/G11 consolidate.contextualize / rollback（口径） ==")
    root = os.path.join(tmp, "g10")
    os.makedirs(root)
    a = MdCGOS(root)
    a.add("note_gd", "# 功能名：批次流水账\n\n正文。\n", layer="knowledge")
    a.flush()
    _b_write(root, "note_gd", MARK)
    rep = consolidate.contextualize_prefixes(root, prefixes=["note_"],
                                             apply=True)
    ok(rep["written"] == 1, f"G10a 归位 1（实测 {rep['written']}）")
    fm, _c = _disk(root, "note_gd")
    ok(fm.get("layer") == "contextual", "G10b 已归位 contextual")
    ok(fm.get("owner_note") == MARK, "G10c B 修正幸存")
    rep2 = consolidate.rollback_contextualize(root)
    ok(rep2.get("ok") and rep2["reverted"] == 1, "G11a 回滚 1")
    fm2, _c2 = _disk(root, "note_gd")
    ok(fm2.get("layer") == "knowledge", "G11b 迁回 knowledge")
    ok(fm2.get("owner_note") == MARK, "G11c B 修正幸存（回滚读走直读口径）")


BODY = ("# 功能名：微分方程应用\n"
        "微分方程应用：建模与求解，使用数值方法迭代求解，需给定边界条件\n")
CAND = {
    "生效条件": ["微分方程", "数值方法"],
    "子功能": ["建模", "求解"],
    "执行": "使用数值方法迭代求解",
    "不适用条件": ["边界条件缺失"],
}


def _fake_reflect(prompt):
    return "```json\n" + json.dumps(CAND, ensure_ascii=False) + "\n```"


def _fake_verify(prompt):
    out = {f: {"keep": (v if isinstance(v, list) else [v]), "drop": [],
               "reason": "逐条核验"}
           for f, v in CAND.items()}
    return json.dumps(out, ensure_ascii=False)


def g12_consolidate(tmp):
    print("== G12 consolidate.consolidate（LLM 固化流，口径） ==")
    root = os.path.join(tmp, "g12")
    os.makedirs(root)
    a = MdCGOS(root)
    a.add("gd_llm", BODY, layer="knowledge")
    a.flush()
    _b_write(root, "gd_llm", MARK)
    rep = consolidate.consolidate(root, apply=True, reflect_fn=_fake_reflect,
                                  verify_fn=_fake_verify,
                                  verification_basis="回放测试核验（守卫）")
    ok(rep["written"] == 1, f"G12a 固化 1（实测 {rep['written']}）")
    fm, c = _disk(root, "gd_llm")
    ok(fm.get("owner_note") == MARK, "G12b B 修正幸存（:678 读走直读口径）")
    ok("# 生效条件：" in c and "# 验证方式：回放测试核验（守卫）" in c,
       "G12c 固化自身生效")


def main():
    os.environ.pop("MDCG_READ_CACHE", None)
    tmp = tempfile.mkdtemp(prefix="mdcg_gov_directread_")
    try:
        g1_recalibrate(tmp)
        g2_link(tmp)
        g3root = g3_crosscheck(tmp)
        g4_crosscheck_rollback(g3root)
        g5root, g5batch = g5_vision_apply(tmp)
        g6_vision_rollback(g5root, g5batch)
        g7_fill_verification_basis(tmp)
        g8_promote(tmp)
        g10_contextualize(tmp)
        g12_consolidate(tmp)
    finally:
        os.environ.pop("MDCG_READ_CACHE", None)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
