# -*- coding: utf-8 -*-
"""守卫：`alternatives`（历史遗留候选）判定口径 —— 只读面，写侧一字未动。

背景：`state_slots` 模块头原写「alternatives/blindspots 结构在场、恒为空列表，
判定口径后置，不得臆造填充」。本批只落地 **alternatives**，`blindspots` 仍后置。

本守卫钉住：
  A 口径定义：曾被断言过、且**不等于当前值**的去重值（保持首次出现序）
  B 不臆造：无历史遗留 ⇒ 空；当前值绝不进 alternatives
  C 撤回/复位语义：retired 态被撤回值仍可回溯；复位后旧值仍在
  D 单遍快速路径（history=False）算不出 ⇒ 如实标注 `alternatives_partial=True`
  E 与既有行为不冲突：blindspots 仍恒空；单元键集只增不减
  F t/seq 不得当「同期」判据（口径备忘，防后人误用）
  G 写入侧零改动（写盘行字段集不变）
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from md_cg import mdcg, state_events, state_slots  # noqa: E402

_P, _F = [], []


def ok(cond, name, detail=""):
    (_P if cond else _F).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (("  | " + detail) if detail else ""))


SUBJ = "鲸娘"


def seed(cg):
    """住所：旧家 → 新家 → 撤回；身份：学徒（单值）。
    复用一个干净台账，供 C/G 组使用。"""
    state_events.append(cg, SUBJ, "住所", old=None, new="旧家",
                        kind="enablement", seq=1, evidence="r1")
    state_events.append(cg, SUBJ, "住所", old="旧家", new="新家",
                        kind="migration", seq=2, evidence="r2")
    state_events.append(cg, SUBJ, "身份", old=None, new="学徒",
                        kind="enablement", seq=3, evidence="r3")
    state_events.append(cg, SUBJ, "住所", old="新家", new=None,
                        kind="retraction", seq=4, evidence="r4")


def main():
    root = tempfile.mkdtemp(prefix="t_alt_")
    try:
        cg = mdcg.MdCG(root)
        seed(cg)

        # ---------- A 口径定义 ----------
        units = {(u["subject"], u["slot"]): u
                 for u in state_slots.project(cg, include_retired=True)}
        zs = units[(SUBJ, "住所")]
        ok(zs["alternatives"] == ["旧家", "新家"],
           "A1 历史两值（旧家/新家）均为备择，保持首次出现序", str(zs["alternatives"]))
        ok(isinstance(zs["alternatives"], list), "A2 alternatives 是 list 类型")

        # ---------- B 不臆造 ----------
        sf = units[(SUBJ, "身份")]
        ok(sf["alternatives"] == [], "B1 无历史遗留 ⇒ 空列表（不臆造）",
           str(sf["alternatives"]))
        ok(sf["value"] == "学徒" and "学徒" not in sf["alternatives"],
           "B2 当前值不进 alternatives")

        # ---------- C 撤回 / 复位 ----------
        ok(zs["state"] == "retired" and "新家" in zs["alternatives"],
           "C1 retired 态：被撤回的值仍进备择（可回溯）")
        state_events.append(cg, SUBJ, "住所", old=None, new="新家",
                            kind="enablement", seq=5, evidence="r5")
        units2 = {(u["subject"], u["slot"]): u
                  for u in state_slots.project(cg, include_retired=True)}
        zs2 = units2[(SUBJ, "住所")]
        ok(zs2["value"] == "新家", "C2 复位后当前值=新家", repr(zs2["value"]))
        ok(zs2["alternatives"] == ["旧家"],
           "C3 复位后：当前值新家不入备择，旧家仍在（去重无重复）",
           str(zs2["alternatives"]))

        # ---------- C4/C5 去重的真阳性样本 ----------
        # 前面「旧家」只出现过一次，M3（去掉去重）在那种样本上抓不到。
        # 这里让同一值「旧家」在历史上**再次出现**（且仍不是当前值）：
        #   旧家 → 新家 → 旧家 → 新家(当前)
        # 期望 alternatives 仍只有一条「旧家」，不得重复。
        state_events.append(cg, SUBJ, "住所", old="新家", new="旧家",
                            kind="migration", seq=6, evidence="r6")
        state_events.append(cg, SUBJ, "住所", old="旧家", new="新家",
                            kind="migration", seq=7, evidence="r7")
        units3 = {(u["subject"], u["slot"]): u
                  for u in state_slots.project(cg, include_retired=True)}
        zs3 = units3[(SUBJ, "住所")]
        ok(zs3["value"] == "新家", "C4 再次复位后当前值=新家", repr(zs3["value"]))
        ok(zs3["alternatives"] == ["旧家"],
           "C5 同一值历史重复出现 ⇒ 备择去重后仅一条", str(zs3["alternatives"]))
        ok(len(zs3["alternatives"]) == len(set(zs3["alternatives"])),
           "C6 alternatives 无重复项（去重不变量）", str(zs3["alternatives"]))

        # ---------- D 单遍快速路径必须如实标注 ----------
        fast = state_slots.project(cg, include_retired=True, history=False)
        fmap = {(u["subject"], u["slot"]): u for u in fast}
        fz = fmap[(SUBJ, "住所")]
        ok(fz.get("alternatives") == [] and fz.get("alternatives_partial") is True,
           "D1 history=False 快速路径：alternatives 空且标注 partial=True（不假绿）", repr(fz.get("alternatives_partial")))
        ok("alternatives_partial" not in zs2,
           "D2 完整路径不带 partial 标记（键只在不完整路径出现）")

        # ---------- E 既有行为不冲突 ----------
        ok(all(u["blindspots"] == [] for u in units2.values()),
           "E1 blindspots 仍恒空（口径后置，未被本批顺带改动）")
        expected = {"subject", "slot", "value", "state", "t_from", "t_to",
                    "seq_from", "seq_to", "tier", "alternatives",
                    "blindspots", "event_count"}
        ok(expected <= set(zs2), "E2 单元键集未减少", str(sorted(set(zs2) - expected)))
        ok(set(zs2) - expected <= {"history"}, "E3 无未经登记的新键",
           str(sorted(set(zs2) - expected)))

        # ---------- F 口径备忘：t/seq 不可当同期判据 ----------
        recs = state_events.read(cg)
        ok(all("t" in r for r in recs), "F1 台账 t 存在（记账时刻，非事件发生时刻）")
        ok(any(r.get("seq") is None for r in state_events.read(cg)) is False,
           "F2 本样本 seq 全非 None（但口径允许 None，不作判据）")

        # ---------- G 写入侧零改动 ----------
        keys_written = set()
        for r in state_events.read(cg):
            keys_written |= set(r)
        ok(keys_written <= {"t", "subject", "slot", "old", "new", "kind",
                            "seq", "evidence", "actor"},
           "G1 写盘行字段集与改前一致（本批只改读面）", str(sorted(keys_written)))

        # ---------- H 两个入口同口径（_project vs project_page）----------
        # 回归来源：本批曾让 _project(history=False) 走回放、project_page(history=False)
        # 走归约器，于是 alternatives 一条路径有真值、另一条恒空。
        # test_state_projection_streaming 抓到了；这里补一条**本守卫内**的断言。
        raw = state_events.read(cg)
        for retire in (False, True):
            a = state_slots._project(raw, include_retired=retire, history=False)
            b = state_slots.project_page(cg, include_retired=retire, history=False)[1]
            ok(a == b, "H1 _project 与 project_page(history=False) 逐位一致 retire=%s" % retire,
               "" if a == b else "分叉：%r vs %r" % (a[:1], b[:1]))
        # 且两处都必须标注 partial（口径一致而非都退化成空）
        a0 = state_slots._project(raw, history=False)[0]
        ok(a0.get("alternatives_partial") is True,
           "H2 _project(history=False) 同样标注 partial（两入口同口径）",
           repr(a0.get("alternatives_partial")))

    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    print("\nSUMMARY: 通过=%d 失败=%d" % (len(_P), len(_F)))
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
