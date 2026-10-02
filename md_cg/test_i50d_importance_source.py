# -*- coding: utf-8 -*-
"""md_cg · issue50-d 守卫：落盘=裁决值 + 保护位只认显式声明 + 文案分叉

缺陷（编排侧改前基线实测，非推断）
----------------------------------
遗忘闸门 `forgetting.assess` 的重要度一问存在一对同源缺陷：
  ① 审计面文案声称未发生的事——启发式路径（不传 hint）裁决走
     「imp≥0.70 → ACCEPT，reason=『重要度 0.84≥0.7（触发不可遗忘保护）』」，
     但落盘面 importance=0.5（默认）且无保护位（隔离沙箱直读 frontmatter
     实证：u_heur_new 裁决 0.837/落盘 0.5；t_heur 裁决 0.711/落盘 0.5）。
  ② 落盘重要度是常数——启发式路径全落 0.5、插件通道（hint=0.6 透传）全落
     0.6 ⇒ 落盘重要度不携带任何区分信息；门禁算出的 0.84/0.71/0.52 在落盘
     时全部丢弃。

本批修复（使用者裁定 2026-10-02，三件套一次收口）
--------------------------------------------------
  1. 落盘=裁决值：remember_gated ACCEPT 分支无条件落 `imp["score"]`（mdcos），
     并落 `importance_source`（"hint"|"heuristic"）进 fm 与索引条目（_node_entry
     与 add 的 _stage 两处同口径，免读文件可判）。
  2. 保护位只认显式声明：add 的自动保护（importance≥0.7 → protected 位）加
     source 闸——`importance_source != "heuristic"` 才打位；启发式过线只落分、
     不打位。add 缺省 None ⇒ 全部既有调用方（约 40 处生产点，逐一面核对均
     不传该键）保护行为逐位不变，零回归由构造保证。
  3. 文案分叉：assess 保护分支 reason 按 `imp["from"]` 分叉——hint 维持
     「触发不可遗忘保护」；heuristic 改「启发式 …（未落保护——保护须显式声明）」。

改前/改后对拍表（E 组；同一组用例两棵树各跑一遍的实测读数，2026-10-02）
------------------------------------------------------------------------
  本表是**实施期一次性实测的字面量**，不是 git HEAD 引用（基线绑提交即失效，
  本仓已有两次教训）——改前树用临时探针跑出，改后由本守卫的 E 组断言钉住。

  | 用例                       | verdict      | 裁决imp        | fm.importance      | importance_source | protected | reason                                    |
  |----------------------------|--------------|----------------|--------------------|-------------------|-----------|-------------------------------------------|
  | A role=tool-output 无hint  | ACCEPT→不变  | 0.775/heuristic→不变 | 0.5→0.775【变】| 无→heuristic【新增】| 无→无不变 | 「重要度…触发不可遗忘保护」→「启发式…未落保护」【变】|
  | A2 role=None 无hint        | ACCEPT→不变  | 0.88/heuristic→不变  | 0.5→0.88【变】 | 无→heuristic【新增】| 无→无不变 | 同上【变】                                 |
  | B hint=0.9                 | ACCEPT→不变  | 0.9/hint→不变        | 0.9→0.9【不变】| 无→hint【新增】    | True→True不变 | 「触发不可遗忘保护」不变                    |
  | C hint=0.6                 | ACCEPT→不变  | 0.6/hint→不变        | 0.6→0.6【不变】| 无→hint【新增】    | 无→无不变 | 「重要度 0.60≥0.3」不变                    |
  （source 列改前四行恒无——键不存在；「变」以 fm.importance/protected/reason 三列为判。）

F 组（待验证假设的只读验证，只取事实、不改检索面、不许诺改善）
--------------------------------------------------------------
  假设：重要度→排序→下游使用是一条功能链。事实结论（代码读数 + 隔离库实测）：
  · 代码读数：`MdCG._score` 的主分**不消费** importance（词法 sim + tag_bonus
    ± 语义 max / 池乘数 / freshness 乘子 / S4 层加成）；importance 的消费面在
    **排序的次级键**，共三处——`cut_by_relevance`（候选截断+排序，键=(-score,
    -importance,-created_at,nid)）、S3 扩散合并排序、`_emit` 终排（键=(-score,
    -importance,id)）。即：**排序消费落盘 importance，但只在相关度平分时作
    破缺**。改前落盘恒 0.5/0.6 ⇒ 平分破缺键全库常数、重要度轴死；改后启发式
    真分落盘 ⇒ 该轴带电。下游另有一个消费面：`protect.is_protected` 的读时
    「重要性保护」（importance≥0.7 → 覆写/遗忘闸拦），启发式节点落 0.7x 分后
    会被它按分拦截——这是「只落分」的直接后果，protect.py 本批未改。
  · 实测读数：隔离库同内容两节点（importance 0.3 vs 0.9）→ 主分同（1.0），
    两种写入序下 0.9 者都排前（F2/F3）——排序消费落盘 importance 成立。

定点变异自证（--mutate）
------------------------
每一处判据都配一个定点变异把它打红，且**恰好**命中预期红项数
（_SRC_MUTATIONS 的 expected 列；实测计数不符即判 FAIL——照
test_i50a_half_dup_defer.py / test_neg_condition_hits.py 同口径）。锚点漂移
（实现改了却没同步本表）→ 报 ANCHOR-MISS 并 **exit 2**（fail-closed）；默认
模式同样先做锚点自检。**不以 git HEAD 为基线源**——变异一律作用在当前盘的
实现上（inspect.getsource + 字面替换 + exec，不落盘不改源文件）。

运行：python -X utf8 -m md_cg.test_i50d_importance_source
      python -X utf8 -m md_cg.test_i50d_importance_source --mutate
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

from . import forgetting, mdcg, mdcos, nodefile
from .mdcg import MdCG
from .mdcos import MdCGOS

_PASS = []
_FAIL = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


# ---------------------------------------------------------------- 夹具
# 正文长度 >200 字 ⇒ lf=1：role=tool-output（internal_deterministic，权 0.25）
# 的启发式 = 0.5·1 + 0.3·0.25 + 0.2·1 = 0.775 —— 恰好过保护线（≥0.7）且落在
# 「0.7x 量级」；role=None（unknown，权 0.6）= 0.88。两路都走保护分支，
# 文案分叉与「只落分不打位」都在这条线上验。
BODY = ("写入闸门重要度轴守卫正文。" + "这是一段足够长的全新合成正文，" * 12
        + "结尾标记 i50dGUARD。")


def _doc(title, body):
    return ("# 功能名：%s\n# 生效条件：任意情境\n# 子功能：验收\n"
            "# 执行：直接调用\n# 验证方式：test\n# 不适用条件：无\n%s\n"
            % (title, body))


def _run_case(nid, **kw):
    """隔离临时根上真跑 remember_gated，返回 (返回体, fm, 盘面fm, 索引条目)。

    三层读数缺一不可：返回体（裁决面）/ 索引条目（免读判面）/ 盘面直读
    （单一真相源——防索引遮蔽）。临时根 finally 删除，绝不触在役数据根。
    """
    root = tempfile.mkdtemp(prefix="i50d_")
    try:
        cg = MdCGOS(root)
        out = cg.remember_gated(nid, _doc("守卫节点", BODY),
                                layer="contextual", **kw)
        gate = out.get("gate") or {}
        fm = (cg.get(nid) or {}).get("frontmatter") or {}
        entry = cg.index["nodes"].get(nid) or {}
        path = os.path.join(root, entry.get("path") or "")
        disk = None
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                disk, _c = nodefile.loads(f.read())
        return {"out": out, "gate": gate, "fm": fm, "disk": disk or {},
                "entry": entry}
    finally:
        try:
            cg.close()
        except Exception:
            pass
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- F0 夹具自检
def g_f0():
    print("== F0 夹具自检（用例确实落在保护分支上）==")
    r = _run_case("f0_a", role="tool-output")
    sc = (r["gate"].get("importance") or {}).get("score")
    ok(r["gate"].get("importance", {}).get("from") == "heuristic"
       and 0.7 <= (sc or 0) < 0.8,
       "F0-1 A 用例裁决 from=heuristic 且 0.7x 量级（%.4f，确实走保护分支）"
       % (sc or -1), r["gate"])
    r2 = _run_case("f0_b", importance_hint=0.9)
    ok((r2["gate"].get("importance") or {}).get("from") == "hint"
       and (r2["gate"].get("importance") or {}).get("score") == 0.9,
       "F0-2 B 用例裁决 from=hint 且 score=0.9", r2["gate"])


# ---------------------------------------------------------------- A 启发式面
def g_a():
    print("== A 启发式全新：落盘=裁决值、source=heuristic、无保护位、文案如实 ==")
    r = _run_case("a_heur", role="tool-output")
    sc = (r["gate"].get("importance") or {}).get("score")
    ok(r["out"].get("verdict") == "ACCEPT",
       "A1 全新启发式过保护线 → verdict ACCEPT（裁决面不变）",
       r["out"].get("verdict"))
    ok(r["fm"].get("importance") == sc,
       "A2 落盘 fm.importance == 裁决值 %s（改前恒 0.5）" % sc,
       r["fm"].get("importance"))
    ok(r["entry"].get("importance") == sc,
       "A3 索引条目 importance == 裁决值（免读文件可判）",
       r["entry"].get("importance"))
    ok(r["disk"].get("importance") == sc and r["disk"].get("importance_source") == "heuristic",
       "A4 盘面直读 importance==裁决值 且 source==heuristic（单一真相源）",
       (r["disk"].get("importance"), r["disk"].get("importance_source")))
    ok(r["fm"].get("importance_source") == "heuristic",
       "A5 fm.importance_source == 'heuristic'", r["fm"].get("importance_source"))
    ok(r["entry"].get("importance_source") == "heuristic",
       "A6 索引条目 importance_source == 'heuristic'",
       r["entry"].get("importance_source"))
    ok(r["fm"].get("protected") is None and r["disk"].get("protected") is None,
       "A7 启发式过线不打保护位（fm 与盘面均无 protected）",
       (r["fm"].get("protected"), r["disk"].get("protected")))
    why = r["gate"].get("reason") or ""
    ok("触发不可遗忘保护" not in why,
       "A8 文案不再声称「触发不可遗忘保护」（改前启发式也这么声称）", why)
    ok("启发式" in why and "未落保护" in why and "显式声明" in why,
       "A9 文案如实：启发式/未落保护/保护须显式声明", why)
    # 对照：role=None（unknown 来源）启发式 0.88 量级——同族第二路
    r2 = _run_case("a_heur_none")
    sc2 = (r2["gate"].get("importance") or {}).get("score")
    ok(r2["fm"].get("importance") == sc2
       and r2["fm"].get("importance_source") == "heuristic"
       and r2["fm"].get("protected") is None
       and "未落保护" in (r2["gate"].get("reason") or ""),
       "A10 对照 role=None：0.5→裁决值 %s、source=heuristic、无保护、文案如实"
       % sc2, (r2["fm"].get("importance"), r2["fm"].get("importance_source"),
               r2["fm"].get("protected"), r2["gate"].get("reason")))


# ---------------------------------------------------------------- B 显式面
def g_b():
    print("== B 显式 hint=0.9：保护位与文案零回归 ==")
    r = _run_case("b_hint09", importance_hint=0.9)
    ok(r["fm"].get("importance") == 0.9,
       "B1 落盘 importance == 0.9（显式面零回归）", r["fm"].get("importance"))
    ok(r["fm"].get("importance_source") == "hint",
       "B2 fm.importance_source == 'hint'", r["fm"].get("importance_source"))
    ok(r["fm"].get("protected") is True,
       "B3 显式声明过线 → protected=True（自动保护位保留）",
       r["fm"].get("protected"))
    ok("importance=0.90" in str(r["fm"].get("protection_reason") or ""),
       "B4 protection_reason 逐字维持（importance=0.90≥0.7）",
       r["fm"].get("protection_reason"))
    ok("触发不可遗忘保护" in (r["gate"].get("reason") or ""),
       "B5 保护文案维持（「触发不可遗忘保护」不因分叉而丢失）",
       r["gate"].get("reason"))
    ok(r["disk"].get("protected") is True
       and r["entry"].get("protected") is True,
       "B6 盘面与索引条目同步 protected=True",
       (r["disk"].get("protected"), r["entry"].get("protected")))


# ---------------------------------------------------------------- C 插件缺省面
def g_c():
    print("== C 插件缺省 hint=0.6：落盘值与无保护状态零回归 ==")
    r = _run_case("c_hint06", importance_hint=0.6)
    ok(r["fm"].get("importance") == 0.6,
       "C1 落盘 importance == 0.6（与改前一致）", r["fm"].get("importance"))
    ok(r["fm"].get("importance_source") == "hint",
       "C2 source == 'hint'（0.6 是插件显式缺省声明）",
       r["fm"].get("importance_source"))
    ok(r["fm"].get("protected") is None,
       "C3 0.6<0.7 无保护位（与改前一致）", r["fm"].get("protected"))
    ok((r["gate"].get("reason") or "") == "重要度 0.60≥0.3",
       "C4 reason 逐字同改前（走⑤重要度分支，不经保护分支）",
       r["gate"].get("reason"))


# ---------------------------------------------------------------- E 对拍锚
_BEFORE_TABLE = {
    # 改前树实测（2026-10-02 临时探针；docstring 对拍表的字面量形态）
    "A": {"verdict": "ACCEPT", "gate_score": 0.775, "gate_from": "heuristic",
          "fm_importance": 0.5, "fm_protected": None,
          "reason": "重要度 0.78≥0.7（触发不可遗忘保护）"},
    "B": {"fm_importance": 0.9, "fm_protected": True,
          "reason": "重要度 0.90≥0.7（触发不可遗忘保护）"},
    "C": {"fm_importance": 0.6, "fm_protected": None,
          "reason": "重要度 0.60≥0.3"},
}


def g_e():
    print("== E 改前/改后对拍锚（docstring 表的「不变」列逐列回归）==")
    r = _run_case("e_a", role="tool-output")
    b = _BEFORE_TABLE["A"]
    ok(r["out"].get("verdict") == b["verdict"]
       and (r["gate"].get("importance") or {}).get("score") == b["gate_score"]
       and r["fm"].get("protected") == b["fm_protected"],
       "E1 A 行不变列：verdict/裁决分/protected 与改前逐列相同",
       (r["out"].get("verdict"), (r["gate"].get("importance") or {}).get("score"),
        r["fm"].get("protected")))
    ok(r["fm"].get("importance") != b["fm_importance"],
       "E2 A 行变列：fm.importance 0.5→裁决值（确实变了，不是改前常数）",
       r["fm"].get("importance"))
    r2 = _run_case("e_b", importance_hint=0.9)
    b2 = _BEFORE_TABLE["B"]
    ok(r2["fm"].get("importance") == b2["fm_importance"]
       and r2["fm"].get("protected") == b2["fm_protected"]
       and (r2["gate"].get("reason") or "") == b2["reason"],
       "E3 B 行显式面逐列不变：importance/protected/reason 与改前相同",
       (r2["fm"].get("importance"), r2["fm"].get("protected"),
        r2["gate"].get("reason")))
    r3 = _run_case("e_c", importance_hint=0.6)
    b3 = _BEFORE_TABLE["C"]
    ok(r3["fm"].get("importance") == b3["fm_importance"]
       and r3["fm"].get("protected") == b3["fm_protected"]
       and (r3["gate"].get("reason") or "") == b3["reason"],
       "E4 C 行显式面逐列不变：importance/protected/reason 与改前相同",
       (r3["fm"].get("importance"), r3["fm"].get("protected"),
        r3["gate"].get("reason")))


# ---------------------------------------------------------------- F 假设链（只读）
def g_f():
    print("== F 假设链只读验证：排序是否消费落盘 importance（只取事实）==")
    # 代码读数①：主分面 _score 不消费 importance
    score_src = inspect.getsource(MdCG._score)
    ok("importance" not in score_src,
       "F1 代码读数：_score 主分不消费 importance（词法+标签±语义/乘子）")
    # 代码读数②：消费面在排序次级键（三处，钉两处代表 + 终排）
    cut_src = inspect.getsource(mdcg.cut_by_relevance)
    ok('frontmatter"].get("importance"' in cut_src,
       "F2 代码读数：cut_by_relevance 的排序键含 importance（次级破缺）")
    emit_src = inspect.getsource(MdCG._emit)
    ok('frontmatter"].get("importance"' in emit_src,
       "F3 代码读数：_emit 终排的排序键含 importance")
    # 实测读数：隔离库同内容 0.3 vs 0.9，两种写入序
    def _rank(low_first):
        root = tempfile.mkdtemp(prefix="i50d_rank_")
        try:
            cg = MdCGOS(root)
            doc = _doc("排序验证", "芙蓉峰下灵枢阁的排序消费面独特词 XQV700。")
            first_imp, second_imp = (0.3, 0.9) if low_first else (0.9, 0.3)
            with contextlib.redirect_stdout(io.StringIO()):
                cg.add("n_first", doc, layer="knowledge",
                       importance=first_imp, verification_basis="test")
                cg.add("n_second", doc, layer="knowledge",
                       importance=second_imp, verification_basis="test")
            results, stat = cg.search("排序消费面独特词 XQV700", k=5)
            rows = [(r[0]["id"], float(r[1]),
                     (r[0]["frontmatter"] or {}).get("importance"))
                    for r in results]
            return {"rows": rows, "tier": stat.get("tier"),
                    "cut": stat.get("cut_order")}
        finally:
            try:
                cg.close()
            except Exception:
                pass
            shutil.rmtree(root, ignore_errors=True)

    a = _rank(True)
    b = _rank(False)
    ok(len(a["rows"]) == 2 and a["rows"][0][1] == a["rows"][1][1],
       "F4 实测：同内容两节点主分相等（%.4f==%.4f，tier=%s cut=%s）"
       % (a["rows"][0][1], a["rows"][1][1], a["tier"], a["cut"]), a["rows"])
    ok(a["rows"][0][2] == 0.9 and b["rows"][0][2] == 0.9,
       "F5 实测：平分时 0.9 者排前（两种写入序一致——排除 id/写入序效应）",
       (a["rows"], b["rows"]))
    print("     （事实结论：排序消费落盘 importance，作同分破缺次级键；"
          "只取事实，不改检索面、不许诺改善。）")


# ---------------------------------------------------------------- D 既有守卫
def g_d():
    print("== D 既有守卫不改断言跑通（子进程实跑，退出码判据）==")
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "md_cg.test_p9_forget_protect"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, timeout=300)
    ok(proc.returncode == 0,
       "D1 test_p9_forget_protect 不改断言跑通（importance_hint≥0.7→ACCEPT"
       " 等既有用例 rc=0）", proc.stdout[-400:] + proc.stderr[-200:])


_GROUPS = (g_f0, g_a, g_b, g_c, g_e, g_f, g_d)


def _run_groups():
    """跑全部断言组（静默），返回失败数——供变异自证复用。"""
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        g()
    return len(_FAIL)


# ---------------------------------------------------------------- 定点变异自证
# 表内每项 = (说明, 目标, 锚点原文, 替换文, 预期红项数)。锚点必须**逐字**出现
# 在当前实现的对应函数源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。
#   目标 "remember_gated" → patch MdCGOS.remember_gated（类方法，exec 于
#   mdcos 模块 globals 副本）；"add" → patch MdCG.add；"assess" → 换
#   forgetting.assess（i50a 同款）。
_SRC_MUTATIONS = (
    # 契约 G①：去掉 source 落盘 → A 组 source 断言红。红 8：A4/A5/A6/A10
    # （source 面）+ A7/E1（source 缺席 ⇒ add 的保护闸看不见 heuristic ⇒
    # 启发式 0.775 也被打保护位——恰是缺陷形态的联动复现）+ B2/C2（显式面
    # 的 source 键同样消失）。
    ("source 落盘整条删除（m1）", "remember_gated",
     'kw["importance_source"] = verdict["importance"]["from"]',
     'pass',
     8),
    # 契约 G 之外的本批核心判据增强：落盘改回「hint 非 None 才透传」的缺陷
    # 形态 → 启发式 A 用例落盘回 0.5。红 5：A2/A3/A4/A10（importance 面）
    # + E2（A 行变列锚——「确实变了」被改回常数即红）。
    ("落盘改回 hint-only 透传（m2，缺陷形态）", "remember_gated",
     'kw["importance"] = verdict["importance"]["score"]',
     'kw["importance"] = (0.5 if hint is None else hint)',
     5),
    # 契约 G②：启发式也打保护（删掉 source 闸）→ A 组无保护位断言红。
    # 红 3：A7 + A10 + E1（改前对拍锚的 protected 不变列）。
    ("启发式也打保护位（m3）", "add",
     '                and importance_source != "heuristic"):',
     '                ):',
     3),
    # 契约 G③：文案不分叉（heuristic 分支换回旧声称）→ A 组文案断言红。
    # 红 3：A8 + A9 + A10（对照行文案半边）。
    ("文案不分叉（m4）", "assess",
     '（未落保护——保护须显式声明）',
     '（触发不可遗忘保护）',
     3),
)

# 静态锚点（默认模式也自检，fail-closed）：
#   · 改前缺陷形态**不得**回归出现在对应函数的可执行源码里
#   · 本批三个新判据的锚点必须在位
_ANCHORS_BANNED = (
    ("remember_gated", 'if hint is not None and "importance" not in kw'),
)
_ANCHORS_REQUIRED = (
    ("remember_gated", 'kw["importance"] = verdict["importance"]["score"]'),
    ("remember_gated", 'kw["importance_source"] = verdict["importance"]["from"]'),
    ("add", 'and importance_source != "heuristic"'),
    ("assess", '未落保护——保护须显式声明'),
)


def _fn_src(target):
    if target == "assess":
        return inspect.getsource(forgetting.assess)
    if target == "remember_gated":
        return inspect.getsource(MdCGOS.remember_gated)
    if target == "add":
        return inspect.getsource(MdCG.add)
    raise KeyError(target)


def _anchor_check():
    """返回 ANCHOR-MISS 说明列表（空 = 全部在位）。"""
    bad = []
    for _name, target, old, _new, _n in _SRC_MUTATIONS:
        if old not in _fn_src(target):
            bad.append("变异锚点缺失：%r @%s" % (old, target))
    for target, s in _ANCHORS_BANNED:
        if s in _fn_src(target):
            bad.append("缺陷形态回归：%s 可执行源码里仍有 %r" % (target, s))
    for target, s in _ANCHORS_REQUIRED:
        if s not in _fn_src(target):
            bad.append("新判据锚点缺失：%s 找不到 %r" % (target, s))
    return bad


def _patched(target, old, new):
    """把目标函数按字面替换变异后返回「安装/还原」对（不落盘不改源文件）。"""
    src = _fn_src(target)
    mutated = src.replace(old, new)
    if target == "assess":
        ns = dict(vars(forgetting))
        exec(compile(mutated, "i50d_mut.py", "exec"), ns)
        fn = ns["assess"]
        return ("forgetting.assess", fn)
    if target == "remember_gated":
        ns = dict(vars(mdcos))
        exec(compile(textwrap.dedent(mutated), "i50d_mut.py", "exec"), ns)
        return ("MdCGOS.remember_gated", ns["remember_gated"])
    ns = dict(vars(mdcg))
    exec(compile(textwrap.dedent(mutated), "i50d_mut.py", "exec"), ns)
    return ("MdCG.add", ns["add"])


@contextlib.contextmanager
def _patched_ctx(target, old, new):
    attr, fn = _patched(target, old, new)
    if attr == "forgetting.assess":
        live = forgetting.assess
        forgetting.assess = fn
        try:
            yield
        finally:
            forgetting.assess = live
    elif attr == "MdCGOS.remember_gated":
        live = MdCGOS.remember_gated
        MdCGOS.remember_gated = fn
        try:
            yield
        finally:
            MdCGOS.remember_gated = live
    else:
        live = MdCG.add
        MdCG.add = fn
        try:
            yield
        finally:
            MdCG.add = live


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
    for name, target, old, new, expect in _SRC_MUTATIONS:
        with _patched_ctx(target, old, new), \
                contextlib.redirect_stdout(io.StringIO()):
            fails = _run_groups()
        verdict = ("命中预期" if fails == expect
                   else "**红项数不符（预期 %d）**" % expect)
        print("  变异「%s」→ 红项=%d  %s" % (name, fails, verdict))
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
        return _mutate_mode()
    anchor_bad = _anchor_check()
    if anchor_bad:
        for b in anchor_bad:
            print("  ANCHOR-MISS " + b)
        print("\n锚点自检：FAIL（fail-closed，exit 2）——实现改了请同步变异表/文案")
        return 2
    print("锚点自检：PASS（%s；不以 git HEAD 为基线源）" % src)
    for g in _GROUPS:
        g()
    print("\nissue50-d 守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：" + "、".join(_FAIL))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
