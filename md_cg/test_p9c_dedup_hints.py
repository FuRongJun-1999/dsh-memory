# -*- coding: utf-8 -*-
"""md_cg · P-9b 去重可见性守卫：直写 dup_of 提示 + gated 路径两处静默洞

背景（探针实测，2026-09-30）
---------------------------
① **直写**（`mdcg_remember(gated=false)` 与 `cg(op=write, gated=false)` 的链尾
   执行器）此前返回体**只有 id**——「同内容以异 id 再写一次」在盘面上变两个
   节点，而调用方拿不到任何提示（`add` 只回 id 字符串）。
   这是**文档化现状**（`writelimit.py` 模块头注 :9-12：限流/同构聚合只作用
   contextual 层，knowledge 等手动纪律写入不受限）⇒ **不许改写入语义**。
② gated 路径（默认路径）有两处**静默洞**：
   (a) 同 id 覆写：`redundancy(exclude=node_id)` 自排除 ⇒ 该层只此一节点时
       `compared=0`、`duplicate_with=None`、`duplicate_ratio=0.0`——「覆写」与
       「全新写入」在裁决里完全不可区分（审计面全 null）；
   (b) `importance≥PROTECT_IMPORTANCE(0.7)` 的「保护优先」分支**排在冗余判定
       之前** ⇒ 高重要度内容的重复写直接 ACCEPT，绕过 MERGE/DROP（实测：dup=1.0
       且节点数 +1），审计面只剩一句「触发不可遗忘保护」。

本批处置（依据见 `forgetting.assess` 的 docstring 与 `md_cg/mcp_server.py` 的
分支注释）：**只补可见性读数，不动任何落盘行为与 verdict**——
   · 直写：返回体附 `dup_of`/`dup_ratio`/`dup_compared`/`dup_hint` +
     `overwrite_of`/`overwrite_ratio`；
   · gated (a)：`gate.entropy.overwrite_of`/`overwrite_ratio` 非 null；
   · gated (b)：该分支返回 `gate.dedup_skipped`（reason=protect_importance +
     去重判据读数），reason 文案显式写出「因保护优先未走去重」。

为何 (b) 选「标注」而不是「把 PROTECT 挪到冗余判定之后」：挪位会削弱
「不可遗忘保护」（高重要度内容将可被 DROP/并入他节点），与 PROTECT_IMPORTANCE
及 `writelimit.py` 头注的跨模块「保护优先」口径分叉，且 DROP 不可逆——缺陷本体
是「静默」而非「保护」，标注即可消除且零回归面。本测 ⑤ **钉住这个决定**：
高重要度近重复的 verdict 必须仍是 ACCEPT（若被挪位 ⇒ 变 MERGE ⇒ 立刻红）。

判据来源：现成字段 `gate.entropy.duplicate_with/.duplicate_ratio/.compared` 与
`gate.redundancy.with/.max`（不新增重复度算法；新增读数复用 `forgetting` 的
同一实现 redundancy / prior_node / self_coverage）。

运行：python -m md_cg.test_p9c_dedup_hints
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import traceback

# 三档自治批次②（2026-10-02）**夹具隔离**：本守卫考的不是档位面（档位守卫 =
# md_cg/test_autonomy_modes.py），故显式置 full 档——回到改动前「动作直落」的
# 行为，使本文件的断言意图（合并/覆写/软删真的发生）逐条不变；env 键名从唯一
# 真源表取（本文件不构成第二处字面量）。
from . import autonomy_modes as _autonomy_modes          # noqa: E402
os.environ[_autonomy_modes.AUTONOMY_ENV_KEYS["mode"]] = "full"

from . import forgetting, writepipe
from .mdcos import MdCGOS, MdCGSecure
from .security import Principal

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def ccg(title, body):
    return (f"# 功能名：{title}\n# 生效条件：任意情境\n# 子功能：验收\n"
            f"# 执行：直接调用\n# 验证方式：test\n# 不适用条件：无\n{body}\n")


# 直写路径 A（mdcg_remember gated=false）用：无策略闸，正文无需 PASSED
BODY = ccg("编译缓存清理", "清理编译缓存目录释放磁盘空间，超过 2GB 时按 mtime 删除最旧分片")
# 直写路径 B（cg(op=write)）用：必须过 audit 闸（策略 required 含 PASSED）
BODY_PASSED = ccg("编译缓存清理", "PASSED 清理编译缓存目录释放磁盘空间，超过 2GB 时删除最旧分片")


def _mk_secure(root):
    p = Principal(tenant="default", actor="t_designer", role="designer",
                  can_write=True, can_admin=True)
    return MdCGSecure(root, principal=p)


def _policy(tmp, required=("PASSED",), forbidden=()):
    path = os.path.join(tmp, "policy_p9c.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"forbidden": list(forbidden), "required": list(required)}, f)
    return path


def _run(tmp):
    from . import mcp_server

    # ============ A. 直写路径：mdcg_remember(gated=false) ============
    print("\n[A] 直写路径 A（mdcg_remember gated=false）：同内容异 id 的提示")
    cg = _mk_secure(os.path.join(tmp, "a"))
    cg.add("k_base", BODY, layer="knowledge", importance=0.5)
    n_before = len(cg.index["nodes"])
    res = mcp_server._dispatch(cg, "mdcg_remember",
                               {"content": BODY, "node_id": "k_dup",
                                "gated": False, "layer": "knowledge",
                                "content_kind": "text"})
    check("A1 直写仍成功落盘（不改写入语义）",
          res.get("ok") is True and cg.get("k_dup") is not None, repr(res)[:160])
    check("A2 盘面仍新增节点（去重语义未被改动）",
          len(cg.index["nodes"]) == n_before + 1,
          f"{n_before} -> {len(cg.index['nodes'])}")
    check("A3 返回体带 dup_of 指向已存在节点（修复面）",
          res.get("dup_of") == "k_base", repr(res)[:200])
    check("A4 dup_ratio 为现成重复度读数（≥ DUP_MERGE）",
          isinstance(res.get("dup_ratio"), float)
          and res["dup_ratio"] >= forgetting.DUP_MERGE, repr(res.get("dup_ratio")))
    check("A5 dup_hint 如实说明「直写不去重」的文档化现状",
          isinstance(res.get("dup_hint"), str) and "直写" in res["dup_hint"]
          and "writelimit" in res["dup_hint"], repr(res.get("dup_hint"))[:160])

    # 无重复内容：不得凭空报 dup（判据要有判别力）
    res2 = mcp_server._dispatch(cg, "mdcg_remember",
                                {"content": ccg("奇点事故复盘", "首次观测到未知内存泄漏，与既有记忆无重叠"),
                                 "node_id": "k_fresh", "gated": False,
                                 "layer": "knowledge", "content_kind": "text"})
    check("A6 无重复时不报 dup_of（避免假提示）",
          res2.get("ok") is True and "dup_of" not in res2, repr(res2)[:160])

    # 同 id 覆写：overwrite_of / overwrite_ratio
    res3 = mcp_server._dispatch(cg, "mdcg_remember",
                                {"content": BODY, "node_id": "k_base",
                                 "gated": False, "layer": "knowledge",
                                 "content_kind": "text"})
    check("A7 同 id 覆写回 overwrite_of（原本无从区分覆写与新建）",
          res3.get("overwrite_of") == "k_base", repr(res3)[:200])
    check("A8 同 id 同内容覆写：overwrite_ratio ≈ 1.0（空写可见）",
          res3.get("overwrite_ratio") == 1.0, repr(res3.get("overwrite_ratio")))
    res4 = mcp_server._dispatch(cg, "mdcg_remember",
                                {"content": ccg("编译缓存清理", "清理编译缓存目录释放磁盘空间，超过 8GB 时按 mtime 删除最旧分片"),
                                 "node_id": "k_base", "gated": False,
                                 "layer": "knowledge", "content_kind": "text"})
    check("A9 同 id 改内容覆写：overwrite_ratio < 1.0（真改可见）",
          isinstance(res4.get("overwrite_ratio"), float)
          and res4["overwrite_ratio"] < 1.0, repr(res4.get("overwrite_ratio")))

    # ============ B. 直写路径：cg(op=write) 链尾执行器 ============
    print("\n[B] 直写路径 B（cg(op=write, gated=false) 链尾执行器）")
    old_policy = os.environ.get("MDCG_POLICY_FILE")
    os.environ["MDCG_POLICY_FILE"] = _policy(tmp)
    try:
        pipe = writepipe.install_default_gates(writepipe.WritePipeline())
        cgb = _mk_secure(os.path.join(tmp, "b"))
        cgb.add("w_base", BODY_PASSED, layer="knowledge", importance=0.5)
        out = pipe.execute(cgb, {"content_kind": "text", "content": BODY_PASSED,
                                 "gated": False, "layer": "knowledge"})
        check("B1 直写经链：committed + verdict 不变",
              out.get("committed") is True and out.get("verdict") is not None,
              repr(out)[:200])
        check("B2 经链直写也带 dup_of（第二处落盘点同样接线上）",
              out.get("dup_of") == "w_base", repr(out)[:200])
        check("B3 经链直写 dup_ratio 读数存在",
              isinstance(out.get("dup_ratio"), float)
              and out["dup_ratio"] >= forgetting.DUP_MERGE, repr(out.get("dup_ratio")))
        out2 = pipe.execute(cgb, {"content_kind": "text",
                                  "content": BODY_PASSED, "gated": False,
                                  "node_id": "w_base", "layer": "knowledge"})
        check("B4 经链直写覆写读数存在",
              out2.get("overwrite_of") == "w_base"
              and out2.get("overwrite_ratio") == 1.0, repr(out2)[:200])
        # 无重复不报 dup
        fresh = ccg("奇点事故复盘二", "PASSED 首次观测到未知泄漏，与既有记忆无重叠")
        out3 = pipe.execute(cgb, {"content_kind": "text", "content": fresh,
                                  "gated": False, "layer": "knowledge"})
        check("B5 经链直写无重复时不报 dup_of",
              out3.get("committed") is True and "dup_of" not in out3,
              repr(out3)[:160])
    finally:
        if old_policy is None:
            os.environ.pop("MDCG_POLICY_FILE", None)
        else:
            os.environ["MDCG_POLICY_FILE"] = old_policy

    # ============ C. gated 洞 (a)：同 id 覆写的裁决不再全 null ============
    print("\n[C] gated (a)：同 id 覆写 → entropy.overwrite_of（不再静默全 null）")
    cg3 = MdCGOS(os.path.join(tmp, "c"))
    cg3.add("k_ov", BODY, layer="knowledge", importance=0.5)
    r = cg3.remember_gated("k_ov", BODY, layer="knowledge", role="user")
    ent = r["gate"]["entropy"]
    check("C1 覆写情形 entropy.overwrite_of 指向既有 id",
          ent.get("overwrite_of") == "k_ov", repr(ent)[:220])
    check("C2 覆写情形 overwrite_ratio 有值（1.0＝逐字同构的重写）",
          ent.get("overwrite_ratio") == 1.0, repr(ent.get("overwrite_ratio")))
    check("C3 并未改动去重判据本身：自排除仍在（duplicate_with 依旧 None、compared 0）",
          ent.get("duplicate_with") is None and ent.get("compared") == 0,
          repr({k: ent.get(k) for k in ("duplicate_with", "compared")}))
    check("C4 verdict 不变（覆写语义未动）", r["verdict"] == "ACCEPT",
          f"{r['verdict']} · {r['gate']['reason']}")
    check("C5 同 id 异内容覆写：overwrite_ratio < 1.0",
          forgetting.assess(cg3, BODY.replace("2GB", "8GB"), layer="knowledge",
                            role="user", node_id="k_ov")["entropy"]["overwrite_ratio"] < 1.0,
          str(forgetting.assess(cg3, BODY.replace("2GB", "8GB"), layer="knowledge",
                                role="user", node_id="k_ov")["entropy"]["overwrite_ratio"]))

    # ============ D. gated 洞 (b)：保护优先不静默 ============
    print("\n[D] gated (b)：importance≥0.7 的近重复 → dedup_skipped 标注")
    cg4 = MdCGOS(os.path.join(tmp, "d"))
    cg4.add("c_dup", BODY, layer="contextual", importance=0.5)
    n_before = len(cg4.index["nodes"])
    r2 = cg4.remember_gated("c_new", BODY, layer="contextual", role="user",
                            importance_hint=0.9)
    g = r2["gate"]
    dk = g.get("dedup_skipped")
    check("D1 保护优先分支**仍** ACCEPT（保护语义不变——未被挪到冗余判定之后）",
          r2["verdict"] == "ACCEPT", f"{r2['verdict']} · {g['reason']}")
    check("D2 该分支不再静默：dedup_skipped 存在且 reason=protect_importance",
          isinstance(dk, dict) and dk.get("reason") == "protect_importance",
          repr(dk)[:220])
    check("D3 标注带现成去重读数（duplicate_with 指向既有节点）",
          isinstance(dk, dict) and dk.get("duplicate_with") == "c_dup"
          and dk.get("duplicate_ratio", 0) >= forgetting.DUP_MERGE,
          repr(dk)[:220])
    check("D4 reason 文案显式写出「因保护优先未走去重」",
          "保护优先" in g["reason"] and "未走去重" in g["reason"], g["reason"])
    check("D5 落盘行为不变：仍新建节点（保护优先本就不并入）",
          len(cg4.index["nodes"]) == n_before + 1,
          f"{n_before} -> {len(cg4.index['nodes'])}")

    # 保护优先 + 无近重复：仍标注（结构不变量），但如实说「无近重复」
    r3 = cg4.remember_gated("c_fresh", ccg("奇点事故复盘三", "PASSED 首次观测到未知泄漏，与既有记忆无重叠"),
                            layer="contextual", role="user", importance_hint=0.9)
    dk3 = r3["gate"].get("dedup_skipped")
    check("D6 保护优先 + 无近重复：仍带 dedup_skipped 且 duplicate_with 为 None",
          isinstance(dk3, dict) and dk3.get("duplicate_with") is None,
          repr(dk3)[:220])

    # ============ E. 结构不变量：dedup_skipped 只在 PROTECT 分支出现 ============
    print("\n[E] 结构不变量：dedup_skipped 仅 PROTECT 分支（不多不少）")
    cg5 = MdCGOS(os.path.join(tmp, "e"))
    cg5.add("p_dup", BODY, layer="contextual", importance=0.5)
    cases = [
        ("保护优先（0.9）+ 近重复", BODY, 0.9, True),
        ("保护优先（0.7 边界）+ 全新", ccg("边界探针", "PASSED 全新的边界用例内容"), 0.7, True),
        ("非保护（0.6）+ 近重复", BODY, 0.6, False),
        ("非保护（0.1）+ 近重复", BODY, 0.1, False),
    ]
    for name, content, hint, expect in cases:
        g5 = forgetting.assess(cg5, content, layer="contextual", role="user",
                               importance_hint=hint, node_id=None)
        got = g5.get("dedup_skipped") is not None
        check(f"E · {name}", got is expect,
              f"dedup_skipped={'有' if got else '无'}（期望 {'有' if expect else '无'}）"
              f" · verdict={g5['verdict']}")
    check("E · entropy 恒带 overwrite_of 键（无覆写时为 None，不新增缺键）",
          "overwrite_of" in g5["entropy"] and g5["entropy"]["overwrite_of"] is None,
          str(g5["entropy"].get("overwrite_of")))
    check("E · prior_node 单点：空 id / 不存在 id 一律 None",
          forgetting.prior_node(cg5, None) is None
          and forgetting.prior_node(cg5, "") is None
          and forgetting.prior_node(cg5, "不存在的_id") is None
          and forgetting.prior_node(cg5, "p_dup") == "p_dup")


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_p9c_")
    try:
        _run(tmp)
    except Exception:
        traceback.print_exc()
        globals()["FAIL"] += 1
        FAILS.append("未捕获异常")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n==== P9c 结果：{PASS} 通过 / {FAIL} 失败 ====")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
