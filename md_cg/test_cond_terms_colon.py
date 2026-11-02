# -*- coding: utf-8 -*-
"""条件短语切分：冒号只对已知槽标签分隔 + 空 terms 不 fail-open。

对应缺陷（实测于 0.9.16 与 0.9.21，两版行为一致）：

  ① 冒号误当槽分隔
     `condition_space_text()` 产出的槽标签是固定四项
     （CONDITION_SLOTS = 载体/位置、时间、方法、约束），
     而旧 `_cond_terms` 把「第一个冒号之前的一切」都当标签剥掉：
       「…必须按此处置：」        尾冒号   ⇒ 整条条件剥成空串
       「…判 ≥3:1」              正文冒号 ⇒ 前半句丢失
       「到了上午 9:00 开始开会」 正文冒号 ⇒ 只剩 "00 开始开会"，前缀被吞
  ② 空 terms 静默 fail-open
     `judge_qualification` 的旧守卫 `if cond_hit is None and terms_:`
     在 terms_ 为空时跳过整段，直落第 5 步 ACCEPT。
     ⇒ 「条件写坏了」被当成「没有条件」，对任何查询都授资格。

本文件锁的是修好之后的行为，同时保证既有正确行为不被改坏。

运行：python -m md_cg.test_cond_terms_colon
"""
from __future__ import annotations

from .mdcg import STATE_ACCEPT, STATE_DEFER, MdCG

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _doc(cond_line="# 生效条件：问浮力", neg_line="# 不适用条件：问完全无关主题"):
    return ("# 功能名：浮力计算\n" + cond_line + "\n# 子功能：按阿基米德原理算\n"
            "# 执行：代入公式\n# 验证方式：编译器/静态检查通过\n" + neg_line + "\n")


def _node(cond, neg=None):
    fm = {"verification_basis": "compiler"}
    if neg:
        fm["non_applicable_conditions"] = [neg]
    return {"frontmatter": fm,
            "content": _doc(cond_line="# 生效条件：" + cond)}


def _state(cond, query="今天天气怎么样", context=None):
    r = MdCG.judge_qualification(_node(cond), query, context)
    return r["state"], r["reason"]


def main():
    global PASS, FAIL

    # ---------- A 冒号：整条条件必须保住 ----------
    ok(MdCG._cond_terms("三个条件同时成立时必须按此处置：")
       == ["三个条件同时成立时必须按此处置"],
       "A1 全角冒号结尾：整条保住，首尾标点剥离")
    ok(MdCG._cond_terms("三个条件同时成立时必须按此处置:")
       == ["三个条件同时成立时必须按此处置"],
       "A2 半角冒号结尾：同上")
    ok(MdCG._cond_terms("到了上午 9:00 开始开会时")
       == ["到了上午 9:00 开始开会时"],
       "A3 正文含时间 9:00：前缀不被吞")
    ok(any("3:1" in t for t in
           MdCG._cond_terms("页面含承载信息的线条，需按 WCAG 判 ≥3:1")),
       "A4 正文含比值 3:1：内容保留")
    # ⚠ URL 里的 `//` 仍会被切（`/` 是槽内分隔符，上游原行为，本补丁**不涉及**）。
    #   这里如实断言现状，不假装已修。若要修，需另议「/ 何时算分隔符」。
    ok(MdCG._cond_terms("参考 http://example.com 时")
       == ["参考 http", "example.com 时"],
       "A5 URL 的 // 仍按 / 切开（已知未修，如实锁定现状）")

    # ---------- B 四槽标签仍被剥离（不能被 A 改坏） ----------
    cs = MdCG._cond_terms(
        "载体/位置：本机进程；时间：全时窗（任意时刻成立）；"
        "方法：代码走查；约束：仅测试库")
    ok("本机进程" in cs and "代码走查" in cs and "仅测试库" in cs,
       "B1 四槽实词保留")
    ok("载体/位置" not in cs and "时间" not in cs and "方法" not in cs,
       "B2 槽标签不进 terms")
    ok(all("全时窗" not in t and "任意时刻" not in t for t in cs),
       "B3 全时窗哨兵被过滤")

    # ---------- C 空 terms 不再 fail-open ----------
    for bad in ("k", "1", "{", "a", "：", "。"):
        st, rs = _state(bad)
        ok(st != STATE_ACCEPT,
           f"C1 不可用条件 {bad!r} 不再恒 ACCEPT（得 {st}）")
        ok("切不出可用短语" in rs,
           f"C2 不可用条件 {bad!r} 的 reason 说明原因")

    # ---------- D 既有正确行为不变 ----------
    st, rs = _state("换会话")
    ok(st == STATE_DEFER, "D1 条件无关 → DEFER")
    st, rs = _state("换会话", context={"topic": "换会话"})
    ok(st == STATE_ACCEPT and "生效条件已确认" in rs, "D2 context 命中 → ACCEPT")
    st, rs = _state("三个条件同时成立时必须按此处置：",
                    "现在三个条件同时成立时必须按此处置，怎么办")
    ok(st == STATE_ACCEPT and "生效条件已确认" in rs,
       "D3 冒号条件命中时仍 ACCEPT（首尾标点不挡匹配）")

    # ---------- E 文档例外仍成立 ----------
    st, rs = _state("无条件")
    ok(st == STATE_ACCEPT, "E1 显式『无条件』→ ACCEPT（设计豁免）")
    st, rs = _state("全时窗")
    ok(st == STATE_ACCEPT, "E2 只含全时窗 → 不降级（文档口径）")
    st, rs = _state("", "")
    ok(st == STATE_ACCEPT and "未做正条件确认" in rs,
       "E3 空条件 + 无情境 → ACCEPT 且如实标注未确认")
    st, rs = _state("")
    ok(st == STATE_ACCEPT and "切不出可用短语" not in rs,
       "E4 空条件不算『切不出』（不误报）")

    # ---------- F 负条件仍先于正条件 REJECT ----------
    r = MdCG.judge_qualification(_node("问浮力", "问ZXQ7"), "问ZXQ7",
                                 {"query": "问ZXQ7"})
    ok(r["state"] == "REJECT", "F1 负条件命中仍 REJECT")

    # ---------- G 引号 / 感叹号是代码字符，不是首尾标点 ----------
    # 旧口径把 ' " ! 放进首尾标点表：`''` 剥成空串被丢、`!v` 剥成 `v`
    # 再被 len<2 丢掉 —— 两者都是有效 token（空字符串字面量 / 逻辑非）。
    ok(MdCG._cond_terms("''") == ["''"],
       "G1 空字符串字面量 '' 保留（不是首尾标点）")
    ok(MdCG._cond_terms('""') == ['""'], 'G2 空字符串字面量 "" 保留')
    ok(MdCG._cond_terms("'!v'") == ["!v"],
       "G3 成对引号包裹时剥外层，内层 !v 保留")
    ok(MdCG._cond_terms("!v 是逻辑非") == ["!v 是逻辑非"],
       "G4 句中 ! 不被当标点剥")
    ok(MdCG._cond_terms("''与'!v'") == ["''与'!v'"],
       "G5 相邻两个字面量不被外层引号粘连（内层仍带引号 ⇒ 不剥）")

    # ---------- H 空值语义哨兵是合法声明，不是「切不出」 ----------
    # `约束：无` 里的「无」只有 1 字：旧实现靠 len<2 静默滤掉、恰好 ACCEPT。
    # 若补丁只用长度判定，会把它误判成 DEFER —— 必须在长度过滤前认出哨兵。
    ok(MdCG._cond_terms("约束：无") == [],
       "H1 「约束：无」terms 为空（1 字哨兵被过滤）")
    st, rs = _state("约束：无")
    ok(st == STATE_ACCEPT,
       "H2 「约束：无」仍 ACCEPT（合法空值声明，不降级）")
    ok("切不出可用短语" not in rs, "H3 「约束：无」不报『切不出』")
    ok(MdCG._cond_terms("约束：不适用") == ["不适用"],
       "H4 多字哨兵仍作为可匹配短语（口径未放宽）")
    ok(MdCG._cond_terms("约束：无依赖") == ["无依赖"],
       "H5 同上：无依赖 未被哨兵规则吞掉")

    # ---------- I 硬不可用桶仍不豁免 ----------
    for bad, label in (("载体/位置：。；方法：（）", "纯标点"),
                       ("1", "纯数字"),
                       ("a", "单字碎片")):
        st, rs = _state(bad)
        ok(st == STATE_DEFER and "切不出可用短语" in rs,
           f"I 硬不可用（{label}）仍 DEFER 且说明原因")

    # ---------- J 计数可归因（不是合成一个 short） ----------
    d = MdCG._cond_terms_diag("约束：无")
    ok(d["n_decl_sentinel"] == 1 and d["n_short"] == 0,
       "J1 合法的 1 字哨兵记进 n_decl_sentinel，不记 n_short")
    d = MdCG._cond_terms_diag("a")
    ok(d["n_short"] == 1 and d["n_decl_sentinel"] == 0,
       "J2 真正的 1 字碎片记进 n_short")
    d = MdCG._cond_terms_diag("时间：全时窗（任意时刻成立）")
    ok(d["n_time_sentinel"] >= 1, "J3 时间维哨兵单独计数")
    ok(MdCG._cond_terms_diag("")["n_empty"] == 0,
       "J4 空条件不记 n_empty（『没写条件』≠『写了纯标点』）")

    # ---------- K 切分单点：三处入口必须同一口径 ----------
    import md_cg.nodefile as _nf
    probe = ["约束：无", "''", "'!v'", "三个条件同时成立时必须按此处置：",
             "载体/位置：。；方法：（）", ""]
    same = all(
        MdCG._cond_terms(p) == _nf.cond_terms(p) == _nf.condition_terms_diag(p)["terms"]
        for p in probe)
    ok(same, "K1 MdCG._cond_terms / nodefile.cond_terms / condition_terms_diag 同口径")

    # ---------- L 标签真源守卫 ----------
    # L1 原本断言 `CONDITION_SLOTS 的标签列 == COND_SLOT_LABELS`。两者在
    # nodefile 里都由 CONDITION_SLOTS 派生（`COND_SLOT_LABELS = tuple(label for
    # _key, label in CONDITION_SLOTS)`），所以该断言**恒真**，且 `python -O`
    # 会把类体里那条同名 assert 整体剥离 —— 防护力为 0（2026-11-02 review）。
    # 换成真正会红的两条：
    #   L1 标签列必须是「每项非空、互不相同」的四元组 —— 手滑抄重复/抄空会红；
    #   L2 切片真源只能是 nodefile 一处 —— MdCG 不再挂同名别名（别名已删），
    #      一旦有人把标签又抄回 mdcg.py，这条会红。
    _labels = _nf.COND_SLOT_LABELS
    ok(len(_labels) == len(_nf.CONDITION_SLOTS),
       "L1a 标签列与槽数同长")
    ok(all(isinstance(x, str) and x.strip() for x in _labels),
       "L1b 标签列每项都是非空字符串")
    ok(len(set(_labels)) == len(_labels),
       "L1c 标签列无重复（抄重会红）")
    ok(not hasattr(MdCG, "_SLOT_LABELS") and not hasattr(MdCG, "_EDGE_PUNCT"),
       "L2 标签/标点真源只在 nodefile，MdCG 不挂可漂移的别名")

    # ---------- M legacy「观测位置：」单槽冒充要剥掉 ----------
    # 旧口径残留行 `观测位置：X` 是单槽冒充；`观测位置` 不在四槽标签里，
    # 若不显式剥，它会作为一个短语进入匹配面（维护者例4 指的就是这条）。
    legacy = MdCG._cond_terms("观测位置：PmWiki；时间：9:00；方法：浏览器；约束：只读")
    ok(legacy == ["PmWiki", "9:00", "浏览器", "只读"],
       "M5-legacy legacy 前缀被剥，不残留在 terms 里")
    ok(not any(t.startswith("观测位置") for t in legacy),
       "M6-legacy 无 terms 以「观测位置」开头")

    # ---------- N 括号产生的结构性空段不得计入 n_empty ----------
    # 2026-11-02 review 后补：维护者指出「5b 可观测性缺口」时，我按同一方向
    # 又查出一条**本 PR 自己的回归**：`re.split(r"[，,、/（）()]", s)` 在
    # `（…）` 处会产生**结构性空段**（括号本身被当分隔符切掉后留下的空串）。
    # 而原实现是「先 strip 再 if not seg: n_empty += 1」，把
    # 「split 出来的空串」与「真被剥成空的纯标点段」混为一谈，
    # 于是 `时间：全时窗（任意时刻成立）` 多出 n_empty=1，
    # unusable = n_empty+n_digit+n_short > 0 成立，
    # 把**本应豁免**的时间维哨兵误判成 DEFER —— 而源码注释明写
    # 「时间维哨兵……不因其未命中而降级」。
    # 修法：在**剥边之前**判结构性空段（`if not seg: continue`），
    # 剥边之后变空的才计入 n_empty。
    _paren = MdCG._cond_terms_diag("时间：全时窗（任意时刻成立）")
    ok(_paren["n_empty"] == 0,
       "N1 括号产生的结构性空段不计入 n_empty")
    ok(_paren["n_time_sentinel"] >= 1,
       "N2 时间维哨兵被识别（不计入不可用桶）")
    ok(_paren["terms"] == [],
       "N3 哨兵不进 terms（本就不该参与匹配）")
    _unusable = _paren["n_empty"] + _paren["n_digit"] + _paren["n_short"]
    ok(_unusable == 0,
       "N4 哨兵条件走豁免路径（unusable==0 才不会被判 DEFER）")

    _seg = MdCG._cond_terms_diag("载体/位置：页面（含线条）")
    ok(_seg["terms"] == ["页面", "含线条"],
       "N5 括号内内容仍被正常切出（修法不吞内容）")
    ok(_seg["n_empty"] == 0,
       "N6 有括号但无纯标点残段时 n_empty 为 0")

    # 反向：真纯标点段**必须**仍计入 n_empty，否则修法把「不可用」漏掉
    _punct = MdCG._cond_terms_diag("：。；、")
    ok(_punct["n_empty"] >= 1,
       "N7 真纯标点残段仍计入 n_empty（修法不放宽不可用判据）")

    # ---------- O 三种「跳过正条件比对」的原因必须可区分 ----------
    # review 5b：`约束：无`（空值声明）/ 全时窗哨兵 / 根本没写条件
    # 三者语义不同，但 ACCEPT 的 reason 曾完全相同 —— 日志上无法归因。
    _TPL = (
        "# 功能名：探测\n\n# 生效条件：{c}\n\n# 子功能：s\n\n"
        "# 执行：e\n\n# 验证方式：v\n\n# 不适用条件：情境不匹配时\n"
    )

    def _nd(c, cs=None):
        fm = {"non_applicable_conditions": ["情境不匹配时"],
              "verification_basis": "test"}
        if cs is not None:
            fm["condition_space"] = cs
        return {"frontmatter": fm, "content": _TPL.format(c=c)}

    _cs = {"observation_position": "本机进程",
           "time_window": [0, 9999999999],
           "observation_tool": "代码走查",
           "existence_constraint": "仅测试库"}
    _r_none = MdCG.judge_qualification(_nd(""), "本机进程", None)
    _r_decl = MdCG.judge_qualification(_nd("约束：无"), "随便", None)
    _r_time = MdCG.judge_qualification(
        _nd("时间：全时窗（任意时刻成立）"), "随便", None)
    ok(_r_none["state"] == "ACCEPT" and _r_decl["state"] == "ACCEPT"
       and _r_time["state"] == "ACCEPT",
       "O1 三种豁免都仍 ACCEPT（修的是可观测性，不改判定）")
    _reasons = {_r_none["reason"], _r_decl["reason"], _r_time["reason"]}
    ok(len(_reasons) == 3,
       "O2 三种豁免的 reason 互不相同（5b 可观测性缺口已堵）")
    ok("未声明生效条件" in _r_none["reason"],
       "O3 「没写条件」有显式标记")
    ok("空值声明" in _r_decl["reason"],
       "O4 「约束：无」有显式标记")
    ok("全时窗" in _r_time["reason"],
       "O5 时间维哨兵有显式标记")

    print(f"\ncond_terms_colon: {PASS} passed, {FAIL} failed")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
