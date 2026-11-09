# -*- coding: utf-8 -*-
"""P2 自我画像：把「空仪表盘」改成「内容画像」的守卫。

功能名：test_self_portrait —— 自我状态诚实化 + 内容画像的判据。
生效条件：`PYTHONPATH=<root> python -m md_cg.test_self_portrait`。
子功能：断言面——
  A1 无可信 P_trust 时 dimensions.trust 不得沿用历史档（写入时残留 ["high"]）；
  A2 prediction 无样本时 basis=prior、beta_mean/ci95 为 None、beta_prior 保留先验；
  A4 portrait.goals 带在办目标标题；
  A5 portrait.knows 带 knowledge 层节点标题；
  A6 portrait.open 带未解问题；
  A7 portrait.gap 在检索饥饿时指向「缺语料」而非「缺算法」；
  A8 无「功能名/主题」标签的节点，兜底取最长散文行作标题，不把「验证方式」当标题；
  A9 information_gap 带 d_state（不只用 trend 掩盖「一直全盲」）；
  B1 空库 portrait 不抛异常且 text 仍有「缺口」一段；
  B2 _render 正文含「# 我是谁：」一行。
执行：`python -m md_cg.test_self_portrait`。
验证方式：test。
不适用条件：活库（一切读写都在 tempfile.mkdtemp 内）。
"""
from __future__ import annotations

import shutil
import tempfile

from . import self_state
from .mdcos import MdCGOS

PASS = 0
FAIL = 0
FAILS = []

UNTITLED_BODY = (
    "# 验证方式：同模型自验\n"
    "# 生效条件：随时\n"
    "安卓客户端实测结论：13 个开源客户端里只有 3 个满足后台常驻。\n"
)


def _ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS", label)
    else:
        FAIL += 1
        FAILS.append(label)
        print("  FAIL", label)


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_self_portrait_")
    try:
        cg = MdCGOS(tmp)
        cg.add_goal("把自我认知从仪表盘改成内容画像", priority=0.8,
                    conditions="有画像判据时", tags=["probe"])
        cg.add("kn_p2_probe", "# 功能名：先验不等于观测\n正文\n",
               layer="knowledge", tags=["probe"], importance=0.9)
        cg.add_unresolved("自我认知里哪些字段是空壳？", topic="self")

        print("[A1] 无验证留痕：信任档不得沿用历史 high")
        self_state.refresh(cg, dimensions={"trust": ["high"]}, force=True)
        st = self_state.snapshot(cg)
        _ok((st.get("dimensions") or {}).get("trust") == ["unknown"],
            "dimensions.trust == ['unknown']（实际 %r）"
            % ((st.get("dimensions") or {}).get("trust"),))

        print("[A2] 无样本：先验不等于后验")
        pd = st.get("prediction") or {}
        _ok(pd.get("basis") == "prior", "basis=prior（实际 %r）" % (pd.get("basis"),))
        _ok(pd.get("beta_mean") is None, "beta_mean=None")
        _ok((pd.get("beta_prior") or {}).get("mean") is not None,
            "beta_prior 保留先验均值")

        print("[A4][A5][A6] 内容画像取真内容")
        po = st.get("portrait") or {}
        _ok(any("内容画像" in (g.get("title") or "") for g in po.get("goals") or []),
            "goals 带目标标题")
        _ok(any("先验不等于观测" in (k.get("title") or "") for k in po.get("knows") or []),
            "knows 带知识标题")
        _ok(any("空壳" in (o.get("question") or "") for o in po.get("open") or []),
            "open 带未解问题")
        _ok("缺口" in (po.get("text") or ""), "text 含缺口一段")

        print("[A7] 检索饥饿时缺口指向语料")
        try:
            from . import metacognition as _meta
            ds = (_meta.trace(cg, window=6) or {}).get("d_state")
        except Exception:                                   # noqa: BLE001
            ds = None
        if ds == "starved":
            _ok("可被检索到的语料" in (po.get("gap") or ""), "starved → 缺语料文案")
        else:
            _ok(bool(po.get("gap")), "d_state=%r 时仍有缺口说明" % (ds,))

        print("[A8] 无标题标签的节点：兜底取最长散文行")
        cg.add("kn_p2_untitled", UNTITLED_BODY,
               layer="knowledge", tags=["probe2"], importance=0.95)
        po1 = self_state.portrait(cg, limit=2)
        titles = [k.get("title") or "" for k in po1.get("knows") or []]
        _ok(any("安卓客户端实测结论" in x for x in titles),
            "兜底标题取到散文行（实际 %r）" % (titles,))
        _ok(not any(x.startswith("验证方式") for x in titles),
            "不把「验证方式」当标题（实际 %r）" % (titles,))

        print("[A9] 信息差带 d_state（不只用 trend）")
        _ok("d_state" in (st.get("information_gap") or {}),
            "information_gap.d_state 存在（实际 %r）"
            % (sorted((st.get("information_gap") or {}).keys()),))

        print("[B1] 空库不炸")
        empty_root = tempfile.mkdtemp(prefix="mdcg_self_empty_")
        try:
            empty = MdCGOS(empty_root)
            po0 = self_state.portrait(empty)
            _ok(isinstance(po0.get("text"), str) and "缺口" in po0["text"],
                "空库 portrait 仍有缺口句")
            _ok(po0.get("goals") == [] and po0.get("knows") == [], "空库列表为空")
        finally:
            shutil.rmtree(empty_root, ignore_errors=True)

        print("[B2] 状态卡正文含内容画像")
        body = self_state._render(st)
        _ok("# 我是谁：" in body, "正文含「# 我是谁：」")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n=== test_self_portrait: PASS {PASS} / FAIL {FAIL} ===")
    if FAILS:
        for f in FAILS:
            print("  FAILED:", f)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
