#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D 探针：《秤》v2.1 §5.2 退役纪律——登记项退役后的读面/时空面泄漏四读数。

出处：退役纪律缺口（`lifecycle.py:42` 宣称「archived 已归档：不再参与默认检索」，
而读面从未实现该过滤）。本探针是该宣称的**外部可复现读数**：把「退役」走完
合法迁移表（active→demoted→archived），再看读面与时空面是否仍把它带出来。

口径（写定，逐条可对拍）：
  ① 退役泄漏率   = 退役后查证步中 v2 仍出现在该面的面数 / 查证面数
     （查证面 = 读面 search∪recall、时空面 timeline∪anchors；**目标 0**）。
  ② 更新采纳率   = v2 写入后查证步中 v2 可见的面数 / 查证面数
     （**目标 1**——写了看不见 = 反向缺陷，与①互为对照，防「一刀切全滤」）。
  ③ 旧事实残留率 = 退役步之后 v1 仍在的面数 / 查证面数（**目标 1**——退役
     v2 不得连带抹掉 v1；这是「不误剔」的现场读数）。
  ④ 失效误判证伪率 = 退役节点被错误置 falsified/rejected 的条数 / 退役节点数
     （**目标 0**——退役 ≠ 证伪：`archived` 是生命周期态，`rejected` 是裁决层；
     判据 = 索引层仍为 rejected/unresolved，或 frontmatter 带 falsified 标记）。

序列（固定，不随机）：写 v1 → 查（应见）→ 写矛盾 v2 → 查（应见）→
退役 v2（active→demoted→archived，走 `lifecycle.set_state` 合法迁移表）→ 查。

边界（如实）：
  · 本探针只测**读面/时空面**（默认检索与 stg 扫描面）；`cg.get` 直读、`op=audit`
    审计面、`set_state` 恢复路径**不受退役限制**（「退役不删除、可显式恢复」的
    另一半），故**不在**①的查证面内——把它们算作泄漏是把守卫修过头。
  · `converged`/`demoted` 是**降权轴**，仍参与默认检索（设计内），本探针不测。
  · 只测单进程单库；跨进程他写场景不在本探针。

隐私与确定性（硬性）：
  · 脚本不内嵌任何本机路径字面量——输出只含固定字面量与计数，**无临时路径回显**；
  · `--out` 给定时必须落在仓外（脚本内 fail-closed 断言，与 probe_c 同款）；
  · 确定性：无随机、无时间戳、无 id 回显——**同一输入两次运行 stdout 字节一致**；
  · 零在役库写入：隔离 temp root（`tempfile.mkdtemp`）内建库、写节点、退役、查证，
    结束后整根删除；全程不触在役库。

用法（中性占位路径）：
  python -X utf8 scripts/probe_d_retirement_discipline.py [--out %TEMP%/probe_d_out]

stdout 末行：`PROBE_D_JSON {...}` 摘要（机器可读）；`--out` 时另落
`rates.json`（人读/对拍用）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import stg                       # noqa: E402
from md_cg.mdcos import MdCGOS              # noqa: E402

#: 查证用查询串（固定字面量——确定性要求；同时逐字出现在两个节点正文里）。
QUERY = "退役纪律探针槽位"

#: 两个节点 id 与正文（正文含 CCG 六要素：避免资格判 BLINDSPOT 影响可见性读数）。
NODE_V1 = "probe_d_v1"
NODE_V2 = "probe_d_v2"

V1_BODY = """# 功能名：探针 D 旧事实登记（v1）
# 生效条件：隔离 temp root 内执行退役纪律探针序列（写 v1 → 写矛盾 v2 → 退役 v2）
# 子功能：①旧事实登记 ②退役后残留率（读数③）的对照节点
# 执行：cg.add(probe_d_v1, ...) 一次
# 验证方式：读面 search/recall 与时空面 timeline/anchors 的可见性断言
# 不适用条件：在役真实记忆库内执行本序列
正文：退役纪律探针槽位 = 甲地（初始登记）"""

V2_BODY = """# 功能名：探针 D 新事实订正（v2，与 v1 矛盾）
# 生效条件：隔离 temp root 内执行退役纪律探针序列（v1 已写入后）
# 子功能：①新事实登记 ②退役后泄漏率（读数①）的被测节点
# 执行：cg.add(probe_d_v2, ...) 一次 + lifecycle.set_state 逐级降级到 archived
# 验证方式：读面 search/recall 与时空面 timeline/anchors 的不可见性断言
# 不适用条件：在役真实记忆库内执行本序列
正文：退役纪律探针槽位 = 乙地（订正：甲地登记作废）"""

#: 退役路径（走合法迁移表：active→demoted→archived，不跳级）。
RETIRE_PATH = ("demoted", "archived")

#: 时空面 anchors 的查询窗（全时窗哨兵：不因时间窗排除任何节点，只问「在不在候选面」）。
ANCHOR_WINDOW = [1.0, 10.0 ** 11]


# 生效条件：out_dir 为 CLI 给出的输出目录时——以本脚本上两级目录为仓根，判定其绝对路径是否落在仓内；仓内即 sys.exit 拒绝运行（fail-closed）；不同盘符（commonpath 抛 ValueError）按必在仓外处理。
def assert_outside_repo(out_dir):
    """--out 必须在仓外（fail-closed）：以本脚本上两级目录为仓根判定。"""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_abs = os.path.abspath(out_dir)
    try:
        common = os.path.commonpath([repo, out_abs])
    except ValueError:
        return  # 不同盘符 ⇒ 必在仓外
    if common == repo:
        sys.exit("拒绝运行（fail-closed）：--out 必须落在仓外，当前解析为仓内路径。"
                 "请改用仓外目录（如临时目录）。")


# 生效条件：cg、query 传入——把 cg.search（T0–T3 阶梯）与 cg.recall（预算装包 / RRF 融合）两入口的结果 id 取并集返回（集合，不含顺序；无命中即空集）。
def read_face_ids(cg, query):
    """读面：search ∪ recall 的命中 id 集合（默认检索的两条生产入口）。

    两条入口的返回形状不同且都取 id 键（不是节点字典）：`search` 是
    `[(node, score, qual)]` 三元组、`recall` 的 `pack` 项是
    `{"id": ..., "content": ...}` 平铺条目——两处都**只认 id**，
    用错键名会静默变成「该面恒空」，读数失真却看不出来。
    """
    ids = set()
    res, _meta = cg.search(query, k=20, record=False)
    for n, _s, _q in res:
        ids.add(str(n.get("id")))
    pack = cg.recall(query, budget_tokens=4000, k=20)
    for it in (pack.get("pack") or []):
        ids.add(str(it.get("id")))
    return ids


# 生效条件：cg 传入——把 stg.timeline（时间倒序全表视图）与 stg.anchors（全时窗）两 op 的 items id 取并集返回（集合；两 op 均经 stg._scan 候选面）。
def stg_face_ids(cg):
    """时空面：timeline ∪ anchors 的命中 id 集合（均经 `stg._scan` 候选面）。"""
    ids = set()
    tl = stg.timeline(cg, limit=10 ** 6, max_scan=10 ** 9)
    for it in (tl.get("items") or []):
        ids.add(str(it.get("id")))
    an = stg.anchors(cg, time_window=list(ANCHOR_WINDOW), limit=10 ** 6,
                     max_scan=10 ** 9)
    for it in (an.get("items") or []):
        ids.add(str(it.get("id")))
    return ids


# 生效条件：cg、nid 传入——nid 在索引中取不到条目时返回 True（视为「不在被证伪层」的保守侧）；否则当 layer 落在 ("rejected","unresolved") 或 frontmatter 的 verification_state 为 "falsified" 时返回 True，其余返回 False。
def wrongly_falsified(cg, nid):
    """退役被误判为「证伪」的判据：落 negative 层，或带 falsified 标记。"""
    e = (getattr(cg, "index", None) or {}).get("nodes", {}).get(nid) or {}
    if e.get("layer") in ("rejected", "unresolved"):
        return True
    node = cg.get(nid) or {}
    fm = node.get("frontmatter") or {}
    return str(fm.get("verification_state") or "").lower() == "falsified"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="《秤》5.2 退役纪律探针（隔离 temp root；确定性输出）")
    ap.add_argument("--out", default=None,
                    help="输出目录（可选；必须落在仓外）")
    a = ap.parse_args()

    if a.out:
        assert_outside_repo(a.out)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                   # noqa: BLE001
        pass

    root = tempfile.mkdtemp(prefix="probe_d_")
    steps = {}
    try:
        cg = MdCGOS(root)

        # ---- 步 1：写 v1 → 查（应见）----
        cg.add(NODE_V1, V1_BODY, layer="knowledge",
               verification_basis="test", importance=0.4)
        r1, s1 = read_face_ids(cg, QUERY), stg_face_ids(cg)
        steps["v1_after_write"] = {"read": NODE_V1 in r1, "stg": NODE_V1 in s1}

        # ---- 步 2：写矛盾 v2 → 查（应见）----
        cg.add(NODE_V2, V2_BODY, layer="knowledge",
               verification_basis="test", importance=0.4)
        r2, s2 = read_face_ids(cg, QUERY), stg_face_ids(cg)
        steps["v2_after_write"] = {"read": NODE_V2 in r2, "stg": NODE_V2 in s2}

        # ---- 步 3：退役 v2（active→demoted→archived，合法迁移表）----
        retire = []
        for dst in RETIRE_PATH:
            retire.append(cg.set_state(NODE_V2, dst, reason="探针 D 退役序列",
                                       actor="probe_d"))
        fm2 = ((cg.get(NODE_V2) or {}).get("frontmatter")) or {}
        steps["retire"] = [{"to": x.get("to"), "ok": bool(x.get("ok")),
                            "changed": bool(x.get("changed"))} for x in retire]

        # ---- 步 4：查（应不见 v2、仍见 v1）----
        r3, s3 = read_face_ids(cg, QUERY), stg_face_ids(cg)
        steps["v2_after_retire"] = {"read": NODE_V2 in r3, "stg": NODE_V2 in s3}
        steps["v1_after_retire"] = {"read": NODE_V1 in r3, "stg": NODE_V1 in s3}
        falsified = wrongly_falsified(cg, NODE_V2)
        state_after = str(fm2.get("lifecycle_state") or "")
        # 退役不删除：节点文件仍在、cg.get 直读仍可达（不计入泄漏面，见模块 docstring）
        direct_readable = bool(cg.get(NODE_V2))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    faces = ("read", "stg")

    def _count(step):
        return [sum(1 for f in faces if steps[step][f]), len(faces)]

    leak = _count("v2_after_retire")            # ① 目标 0
    adopt = _count("v2_after_write")            # ② 目标 1
    keep_v1 = _count("v1_after_retire")         # ③ 目标 1
    misjudged = [1 if falsified else 0, 1]      # ④ 目标 0

    # ---- 人读读数 ----
    print("退役序列（active→demoted→archived）：%s"
          % json.dumps(steps["retire"], ensure_ascii=False))
    print("节点终态：%s（退役后 cg.get 直读可达=%s——退役不删除，不计入泄漏面）"
          % (state_after or "(缺)", direct_readable))
    print("① 退役泄漏率：%d/%d（面=%s；目标 0）"
          % (leak[0], leak[1], "/".join(faces)))
    print("② 更新采纳率：%d/%d（v2 写入后可见面；目标 %d）"
          % (adopt[0], adopt[1], adopt[1]))
    print("③ 旧事实残留率：%d/%d（退役后 v1 仍在面；目标 %d）"
          % (keep_v1[0], keep_v1[1], keep_v1[1]))
    print("④ 失效误判证伪率：%d/%d（退役 ≠ 证伪；目标 0）"
          % (misjudged[0], misjudged[1]))

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        detail = {"query": QUERY, "steps": steps, "state_after_retire": state_after,
                  "direct_readable": direct_readable,
                  "leak": {"num": leak[0], "den": leak[1]},
                  "adoption": {"num": adopt[0], "den": adopt[1]},
                  "v1_residue": {"num": keep_v1[0], "den": keep_v1[1]},
                  "wrong_falsified": {"num": misjudged[0], "den": misjudged[1]}}
        with open(os.path.join(a.out, "rates.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump(detail, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")

    # ---- 机器可读摘要（末行；键序固定 ⇒ 同输入同字节）----
    summary = {"leak": leak, "adoption": adopt, "v1_residue": keep_v1,
               "wrong_falsified": misjudged}
    print("PROBE_D_JSON " + json.dumps(summary, ensure_ascii=False,
                                       sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
