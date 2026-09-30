# -*- coding: utf-8 -*-
"""md_cg · 第 11 篇：节点间自动冲突检测（三级决策：情绪 → 反思 → 递归反思）

理论出处（本仓原文）：
  · 情绪 = 信息差二阶变化 d²D/dt²（`docs/theory/智能的公理化基石.md` §十一）
    —— L0，独立通道，**不参与信任计算**
  · 反题 = 预测与事实冲突（同文档 :529，条件论七操作）—— L1 条件级冲突检测
  · 递归受深度/节点数/循环/信息增益门槛约束（同文档 :273）—— L2 递归反思
  · 四态路由 ACCEPT/REJECT/DEFER/BLINDSPOT（同文档 :721）
  · 知识飞轮：误差 → 补条件 → 结构更新（同文档 :725）
  · 纪律四要素同构（`docs/工作纪律_认知图条目_v1.1.json`）

覆盖：
  A L0 情绪通道：三态 / 二阶差分 / 不参与信任计算
  B L1 反思四态：ACCEPT / 自否定 REJECT / 违反纪律 REJECT / 条件互斥 DEFER / BLINDSPOT
  C L2 递归反思：沿边收敛 / 增益门槛停搜 / 深度上限 / 循环不爆炸
  D 冲突自动触发飞轮（**只限真冲突 REJECT**，H11⑥ 2026-09-30；落 unresolved）
  E 写入接入：add(consistency) 抛错 / defer 不落盘 / record 放行 / 闸门叠加
  F 留痕 / 统计 / 自描述 / health 面
  G H8 结论同一性判据（CONCLUSION_SAME）：逐字/空白差异不判分歧，真分歧不放宽

运行：python -m md_cg.test_p11_consistency
"""
from __future__ import annotations

import tempfile

from .mdcos import MdCGOS
from . import consistency, protect

PASS = FAIL = 0
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


def main():
    root = tempfile.mkdtemp(prefix="mdcg_p11_")
    cg = MdCGOS(root)

    # 既有结构：条件节点 + 纪律节点 + 无条件节点
    cg.add("k_offline",
           "# 功能：离线批处理\n# 生效条件：离线环境\n# 不适用条件：生产环境\n",
           layer="knowledge", tags=["batch"],
           non_applicable_conditions=["生产环境"], importance=0.4)
    cg.add("discipline_prod", "# 功能：生产纪律\n# 执行：禁止删除生产数据\n",
           layer="self", tags=["discipline"],
           non_applicable_conditions=["删除生产数据"], importance=0.5)
    cg.add("k_plain", "普通笔记，没有任何条件声明。", layer="knowledge",
           importance=0.3)
    cg.add("c_plain", "情景笔记，也没有条件声明。", layer="contextual",
           importance=0.3)

    # ---------- A. L0 情绪通道 ----------
    print("\n[A] L0 情绪通道（信息差二阶变化 d²D/dt²，§十一）")
    em = consistency.emotional_bias(0.1)
    check("低冲突 → approaching（信息差收敛）",
          em["bias"] == "approaching", str(em))
    check("高冲突 → avoiding（信息差扩大）",
          consistency.emotional_bias(0.9)["bias"] == "avoiding")
    check("二阶差分：冲突强度上升 → avoiding",
          consistency.emotional_bias(0.5, 0.2)["bias"] == "avoiding",
          str(consistency.emotional_bias(0.5, 0.2)))
    check("二阶差分：冲突强度回落 → 非 avoiding",
          consistency.emotional_bias(0.5, 0.6)["bias"] != "avoiding")
    check("情绪通道独立，不参与信任计算（§十一 强制）",
          "不参与信任" in em["note"], em["note"])

    # ---------- B. L1 反思四态 ----------
    print("\n[B] L1 反思（反题检测 → 四态路由）")
    r = cg.check_consistency("这是一条全新的普通记录，与既有结构无关。",
                             layer="knowledge")
    check("B1 无冲突 → ACCEPT", r["verdict"] == "ACCEPT", r["reason"])

    r = cg.check_consistency("删除生产数据", layer="self")
    check("B2 违反纪律 → REJECT（正文命中 negative.reject）",
          r["verdict"] == "REJECT"
          and any(c["type"] == "discipline" for c in r["conflicts"]),
          r["reason"])

    r = cg.check_consistency("# 功能：X\n# 生效条件：删除生产数据\n",
                             non_applicable_conditions=["删除生产数据"],
                             layer="knowledge")
    check("B3 自否定 → REJECT（自己的负条件排除自己的正条件）",
          r["verdict"] == "REJECT"
          and any(c["type"] == "self_negation" for c in r["conflicts"]),
          r["reason"])

    r = cg.check_consistency("# 功能：生产批处理\n# 生效条件：生产环境\n",
                             layer="knowledge")
    check("B4 条件互斥 → DEFER（新适用条件落在既有不适用区）",
          r["verdict"] == "DEFER" and r["conflict_strength"] >= consistency.CLASH_LOW,
          f'{r["verdict"]}/{r["conflict_strength"]}')

    r = cg.check_consistency("# 功能：某情景\n# 生效条件：某个特殊条件\n",
                             layer="contextual")
    check("B5 无可比对条件 → BLINDSPOT（不假装确定）",
          r["verdict"] == "BLINDSPOT", r["reason"])

    # ---------- C. L2 递归反思 ----------
    print("\n[C] L2 递归反思（:273 深度/节点/循环/增益门槛）")
    cg.add("e_conf", "# 功能：冲突源\n# 生效条件：条件A\n", layer="contextual",
           edges=[{"to": "s_disc"}], importance=0.4, override=True)
    cg.add("s_disc", "# 功能：区分节点\n", layer="structural",
           non_applicable_conditions=["生产环境"], importance=0.4)
    r = cg.check_consistency(
        "# 功能：待检\n# 生效条件：生产环境\n",
        non_applicable_conditions=["条件A"], layer="contextual", depth=3)
    rec = r.get("recursion") or {}
    check("C1 沿关系边两跳找到区分条件 → resolved",
          rec.get("stopped_by") == "resolved" and bool(rec.get("resolved_by")),
          str(rec))

    cg.add("e_conf", "# 功能：冲突源\n# 生效条件：条件A\n", layer="contextual",
           edges=[], importance=0.4, override=True)
    r = cg.check_consistency(
        "# 功能：待检\n# 生效条件：某条件\n",
        non_applicable_conditions=["条件A"], layer="contextual", depth=3)
    rec = r.get("recursion") or {}
    check("C2 增益门槛：候选空间不减少即停搜（:273）",
          rec.get("stopped_by") in ("gain_below_threshold", "frontier_exhausted"),
          str(rec))

    cg.add("e_conf", "# 功能：冲突源\n# 生效条件：条件A\n", layer="contextual",
           edges=[{"to": "s_disc"}], importance=0.4, override=True)
    r = cg.check_consistency(
        "# 功能：待检\n# 生效条件：生产环境\n",
        non_applicable_conditions=["条件A"], layer="contextual", depth=1)
    rec = r.get("recursion") or {}
    check("C3 深度上限受约束（depth=1 不越界）",
          rec.get("depth", 99) <= 1, str(rec))

    cg.add("l1", "# 功能：环1\n# 生效条件：条件A\n", layer="contextual",
           edges=[{"to": "l2"}], importance=0.4)
    cg.add("l2", "# 功能：环2\n# 生效条件：条件A\n", layer="contextual",
           edges=[{"to": "l1"}], importance=0.4)
    r = cg.check_consistency("# 功能：待检\n",
                             non_applicable_conditions=["条件A"],
                             layer="contextual", depth=3)
    rec = r.get("recursion") or {}
    check("C4 循环检测：环不导致无限展开",
          0 < rec.get("nodes_visited", 0) <= consistency.MAX_NODES, str(rec))

    # ---------- D. 冲突自动触发飞轮（⑥ 2026-09-30 收窄：只限真冲突 REJECT） ----------
    print("\n[D] 飞轮建单收窄（误差 → 补条件 → 结构更新，:725）")

    def _unres():
        return [n for n, e in list((cg.index.get("nodes") or {}).items())
                if e.get("layer") == "unresolved"]

    # D1/D2 收窄后**唯一**的触发面（REJECT）必须仍在——否则「收窄」就变成了
    # 「静默关掉飞轮」，那是把缺陷挪到另一个位置。
    _n_before = len(_unres())
    r = cg.check_consistency("删除生产数据", layer="self", auto_flywheel=True)
    check("D1 真冲突 REJECT 仍自动投递飞轮并返回 unresolved_id",
          r["verdict"] == "REJECT" and bool(r.get("unresolved_id")),
          f'{r["verdict"]} / {r.get("unresolved_id")}')
    check("D2 飞轮落 unresolved 条目", len(_unres()) > _n_before,
          str(_unres()[:3]))

    # D3 收窄：DEFER 是「条件互斥/部分覆盖、**待确认**」，不是已判定的冲突
    # ——改前它自动建单（本轮 ⑧ 的误判 DEFER/strength=1.0 就是这样固化成
    # unr_9af4803381 的）。判定本身必须照旧如实返回，只是不再自动建单。
    _n0 = len(_unres())
    r = cg.check_consistency("# 功能：生产批处理\n# 生效条件：生产环境\n",
                             layer="knowledge", auto_flywheel=True)
    check("D3 DEFER 不再自动建单（判定仍如实返回 DEFER/≥CLASH_LOW）",
          r["verdict"] == "DEFER"
          and r["conflict_strength"] >= consistency.CLASH_LOW
          and not r.get("unresolved_id")
          and len(_unres()) == _n0,
          f'{r["verdict"]}/{r["conflict_strength"]}/'
          f'unr={r.get("unresolved_id")}/n={len(_unres())}')

    # D4 收窄：BLINDSPOT 是「既有节点全无声明 ⇒ 检测前提不存在」，空库上恒成立
    # ——改前每写一条就建一张工单（死胡同）。用独立空库测（本库已有可比对节点）。
    d_root = tempfile.mkdtemp(prefix="mdcg_p11_d4_")
    d = MdCGOS(d_root)
    r = d.check_consistency("# 功能：某情景\n# 生效条件：某个特殊条件\n",
                            layer="contextual", auto_flywheel=True)
    _du = [n for n, e in list((d.index.get("nodes") or {}).items())
           if e.get("layer") == "unresolved"]
    check("D4 BLINDSPOT 不再自动建单（空库不产工单，判定仍为 BLINDSPOT）",
          r["verdict"] == "BLINDSPOT" and not r.get("unresolved_id")
          and not _du,
          f'{r["verdict"]} / unr={r.get("unresolved_id")} / n={len(_du)}')
    d.close()

    # D5 自描述表与判据同源（不许「文档写 REJECT、代码仍建三种」）
    _cat_d = cg.consistency_catalog()
    check("D5 catalog 的 auto_flywheel.triggers_on 与判据单点同源",
          _cat_d["auto_flywheel"]["triggers_on"] == list(
              consistency.FLYWHEEL_TRIGGERS),
          str(_cat_d["auto_flywheel"]["triggers_on"]))

    # ---------- E. 写入接入 ----------
    print("\n[E] 写入接入（信息的修改必须与已有规则校验）")
    nid = cg.add("ok_1", "完全无关的一条新记录", layer="knowledge",
                 consistency=True)
    fm = (cg.get("ok_1") or {}).get("frontmatter") or {}
    check("E1 无冲突写入成功且留痕判定",
          bool(nid) and (fm.get("consistency") or {}).get("verdict") == "ACCEPT",
          str(fm.get("consistency")))

    try:
        cg.add("bad_1", "删除生产数据", layer="self", consistency=True)
        check("E2 违反纪律写入被拒（ConsistencyError）", False, "未抛错")
    except consistency.ConsistencyError as e:
        check("E2 违反纪律写入被拒（ConsistencyError）",
              e.verdict == "REJECT", e.reason)

    out = cg.add("bad_2", "删除生产数据", layer="self", consistency=True,
                 on_conflict="defer")
    check("E3 on_conflict=defer 不落盘",
          out is None and cg.get("bad_2") is None, str(out))

    cg.add("bad_3", "删除生产数据", layer="self", consistency=True,
           on_conflict="record")
    fm3 = (cg.get("bad_3") or {}).get("frontmatter") or {}
    check("E4 on_conflict=record 记录后放行",
          (fm3.get("consistency") or {}).get("verdict") == "REJECT",
          str(fm3.get("consistency")))

    # N214（2026-09-28，既有套件适配）：该调用的判据是 **MERGE**，落库目标就是
    # 上面的 **self 层纪律节点** `discipline_prod`——`forgetting.reinforce` 现在
    # 写盘前过 `protect.guard_overwrite`（层闸 + 保护闸，与 `cg.add` 同口径），
    # 受保护层节点不再被无 override 覆写，故此处**抛 `ProtectionError`**（fail-
    # closed，不是静默改写）。语义与断言不变：冲突内容一律不落盘（g_1 从不创建），
    # 另加一条「拒绝而非静默改写」的形态断言。
    _gated_denied = False
    try:
        cg.remember_gated("g_1", "删除生产数据", layer="self",
                          consistency=True)
    except protect.ProtectionError:
        _gated_denied = True
    check("E5 遗忘闸门叠加冲突检测：冲突内容不落盘（受保护层目标被写保护闸拒）",
          cg.get("g_1") is None and _gated_denied, str(cg.get("g_1")))

    # ---------- F. 留痕 / 统计 / 自描述 ----------
    print("\n[F] 留痕 / 统计 / 自描述")
    vs = {x.get("verdict") for x in cg.consistency_history(limit=200)}
    check("F1 留痕覆盖四态",
          {"ACCEPT", "REJECT", "DEFER", "BLINDSPOT"} <= vs, str(sorted(vs)))
    st = cg.consistency_stats()
    check("F2 统计按判定/情绪分布",
          st["records"] > 0 and st["by_verdict"].get("REJECT", 0) > 0,
          str(st["by_verdict"]))
    cat = cg.consistency_catalog()
    check("F3 自描述三级 + 四态",
          set(cat["levels"]) == {"L0_emotion", "L1_reflect",
                                 "L2_recursive_reflect"}
          and cat["levels"]["L1_reflect"]["verdicts"] == list(consistency.VERDICTS),
          str(list(cat["levels"])))
    check("F4 自描述标注情绪通道不参与信任",
          "不参与信任" in cat["levels"]["L0_emotion"]["constraint"])
    check("F5 诚实边界声明（非语义蕴含证明）",
          "非语义蕴含" in cat["honest_boundary"], cat["honest_boundary"])
    hh = cg.health_os()
    check("F6 health 报告 consistency 面",
          "consistency" in hh.get("os", {}),
          str(hh.get("os", {}).get("consistency"))[:90])

    # ---------- G. H8：结论同一性判据（CONCLUSION_SAME） ----------
    # 为什么单独立段：改前`CONCLUSION_SAME`这条判据**零测试覆盖**（编排侧全仓搜过，
    # 无任何断言触及）。而它是 L1-c（same_condition_divergence）唯一的分流门——
    # 门被误触就凭空多出「同条件分歧」工单，门被放宽就把真分歧吞掉。
    # 本段三件事一起钉死：
    #   ① 逐字重复 1.0 与**纯空白差异**（\r\n↔\n / 缩进（半角·全角）/ 空行 /
    #      行尾空格 / 词内插空白 / 词间多空格）一律**不判分歧**；
    #   ② 标定注释里的「同槽不同值」「同值异措辞」两类**仍判分歧**（不许放宽）；
    #   ③ 阈值常量本身仍是 0.95（防「为了让守卫变绿而调参」）。
    print("\n[G] H8 结论同一性判据（CONCLUSION_SAME）：逐字/空白差异不判分歧")
    g_root = tempfile.mkdtemp(prefix="mdcg_p11_h8_")
    g = MdCGOS(g_root)
    h = ("# 功能名：网关心跳端口与重连参数\n"
         "# 子功能：端口取值与退避次数\n"
         "# 生效条件：网关在线且心跳已启用\n")
    body = ("服务端心跳端口：9090。客户端使用长连接轮询，超时时间为 30 秒。\n"
            "故障处置：连接断开后由客户端指数退避重连，最多重试 5 次。")
    g.add("h8_old", h + "\n" + body + "\n", layer="knowledge",
          verification_basis="test", importance=0.5)

    def _concl(content, **kw):
        """(verdict, 同条件分歧条目列表, conclusion_overlap 或 None)。"""
        r = g.check_consistency(content, layer="knowledge", depth=0, **kw)
        d = [c for c in r["conflicts"]
             if c.get("type") == "same_condition_divergence"]
        return r, d, (d[0]["conclusion_overlap"] if d else None)

    check("G0 空白归一化契约：连续空白折叠为单空格，全角空格同归一",
          consistency._norm_ws("  甲\r\n乙\t\u3000丙  ") == "甲 乙 丙",
          repr(consistency._norm_ws("  甲\r\n乙\t\u3000丙  ")))
    check("G0b 去空白契约：去掉全部空白（含全角空格/换行/制表）",
          consistency._nows(" 甲\t乙\u3000丙 \n") == "甲乙丙",
          repr(consistency._nows(" 甲\t乙\u3000丙 \n")))
    check("G0c 判据未放宽：CONCLUSION_SAME 仍为标定值 0.95",
          consistency.CONCLUSION_SAME == 0.95,
          str(consistency.CONCLUSION_SAME))

    r, d, _c = _concl(h + "\n" + body + "\n")
    check("G1 标定①逐字重复（标定 concl=1.0）→ 不判分歧、ACCEPT、无工单缺口",
          not d and r["verdict"] == "ACCEPT" and r["conflict_strength"] == 0.0,
          f'{r["verdict"]}/{r["conflict_strength"]}/{len(d)}')

    # H8 现场 8 变体：正文逐字相同，只是空白不同（原样送检会在 0.95 门下假红）
    _h8_variants = [
        ("尾部多换行", h + "\n" + body + "\n\n"),
        ("行首缩进(半角)",
         h + "\n" + "\n".join("  " + x for x in body.split("\n")) + "\n"),
        ("行首缩进(全角)",
         h + "\n" + "\n".join("\u3000" + x for x in body.split("\n")) + "\n"),
        ("插空行", h + "\n" + body.replace("\n", "\n\n") + "\n"),
        ("行尾空格",
         h + "\n" + "\n".join(x + " " for x in body.split("\n")) + "\n"),
        ("词内插空白",
         h + "\n" + body.replace("指数退避重连", "指数 退避重连") + "\n"),
        ("词间多空格",
         h + "\n" + body.replace("超时时间为 30 秒", "超时时间为   30   秒")
         + "\n"),
        ("组合(缩进+尾换行+行尾空格)",
         h + "\n" + "\n".join("  " + x + "  " for x in body.split("\n"))
         + "\n\n"),
    ]
    for i, (vname, vcontent) in enumerate(_h8_variants, 1):
        r, d, _c = _concl(vcontent)
        check(f"H8-A{i} 空白差异「{vname}」不得判成分歧（须 ACCEPT / 0 分歧）",
              not d and r["verdict"] == "ACCEPT"
              and r["conflict_strength"] == 0.0,
              f'{r["verdict"]}/{len(d)}/{r["conflict_strength"]}')

    # 空白差异不得触发飞轮建单（判成 DEFER 就会各建一张 unresolved 工单）
    r, _d, _c = _concl(h + "\n" + body.replace("\n", "\n\n") + "\n",
                       auto_flywheel=True)
    check("H8-B 空白差异不建 unresolved 工单（飞轮不误触）",
          not r.get("unresolved_id") and r["verdict"] == "ACCEPT",
          str(r.get("unresolved_id")))

    # 反向：真分歧两类**必须仍判分歧**（否则就是靠放宽判据变绿）
    r, d, c = _concl("# 功能名：网关心跳端口与重连参数\n"
                     "# 子功能：端口取值与退避次数\n"
                     "# 生效条件：网关在线且心跳已启用\n\n"
                     "服务端心跳端口：8080。客户端使用长连接轮询，超时时间为 60 秒。\n"
                     "故障处置：连接断开后由客户端指数退避重连，最多重试 9 次。\n")
    check("G2 标定②同槽不同值仍判分歧（实测 concl=0.6928 < 0.95）",
          bool(d) and r["verdict"] == "DEFER" and 0.55 <= c < 0.95,
          f'{r["verdict"]}/{c}/{len(d)}')

    r, d, c = _concl("# 功能名：网关心跳端口与重连参数\n"
                     "# 子功能：端口取值与退避次数\n"
                     "# 生效条件：网关在线且心跳已启用\n\n"
                     "心跳所用服务端端口为 9090；客户端以长连接方式轮询，"
                     "超时设定 30 秒。\n"
                     "断开后的处理：客户端按指数退避重新连接，尝试上限 5 次。\n")
    check("G3 标定③同值异措辞仍判分歧（实测 concl=0.3385 < 0.95）",
          bool(d) and r["verdict"] == "DEFER" and 0.2 <= c < 0.8,
          f'{r["verdict"]}/{c}/{len(d)}')

    print(f"\n==== P11 结果：{PASS} 通过 / {FAIL} 失败 ====")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return FAIL == 0


if __name__ == "__main__":
    import sys
    # 用 reconfigure 而非「包一层 TextIOWrapper」：后者在 stdout 被重定向到文件时
    # 会在解释器退出阶段丢缓冲，CI 里会看不到失败原因。
    # 本用例原先缺这一步：Windows 默认 gbk 控制台下打印「d²D/dt²」的 ²(U+00B2)
    # 直接 UnicodeEncodeError，崩在**第一条断言之前**，输出只剩 725 字节——
    # 于是「P11 通过」这件事从未被真正执行过，也从未被任何人看见。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(0 if main() else 1)
