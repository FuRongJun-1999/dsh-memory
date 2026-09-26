# -*- coding: utf-8 -*-
"""FI-M06 · S6 LLM（静默改写：伪造「已验证成功」的回答冒充事实）。

判据：done≠verified（v0.1 蜂巢对齐 D-1，S6 源「自报成功当事实」）——LLM 输出
只能作候选，资格由独立判据裁；L2 的 hits/卡导航要求 = P4 判据冻结在回答面的
投影；拦截即 T8 fail-closed（无来源验证→落向拒绝而非放行）。判据面：
md_cg/whitebox_kb/wisdom/verify_answer.py:57-116（L1 结构/L2 来源/L3 边界三层
自校验；L2 hits 门 :92-96）。
注入（纯函数）：verify_answer("根据我的知识…彻底完成、全部验证通过…（这条知识
属于…）", {kind:'knowledge', hits:[]})——内容自洽、语气确定但从未走条件路由图；
对照组同函数喂合法 chitchat 短回答。

理论预期（登记 pass，回归守卫）：伪造组 ok=False 且拦截理由「✗ L2 knowledge
回答无 hits（未走条件路由图）」；对照组 ok=True——闸只拦无来源冒充不拦合法
出口（红场=防线有效）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness        # noqa: E402
import mdcg_support   # noqa: E402


def main() -> int:
    case = harness.Case("FI-M06", "LLM 伪造已验证成功回答：L2 判据拦截")
    try:
        d = case.tmpdir("m06")
        mdcg_support.apply_env(d)
        from md_cg.whitebox_kb.wisdom import verify_answer as va

        case.check("读码：L2 判据冻结在案（knowledge 类要求 hits 非空，缺即拒——"
                   "P4 在回答面的投影）",
                   "knowledge 回答无 hits" in harness.src(
                       "md_cg/whitebox_kb/wisdom/verify_answer.py"),
                   "verify_answer.py:92-96")

        # ═══ 主场：伪造「已验证成功」回答（hits=[]，从未走路由图）═══
        forged = ("根据我的知识，这项任务已经彻底完成、全部验证通过，没有任何"
                  "遗留问题，可以放心收尾。（这条知识属于核心工程经验）")
        ok_f, checks_f = va.verify_answer(forged, {"kind": "knowledge", "hits": []})
        case.check("红场①：伪造组 ok=False（done≠verified——自报成功不当事实）",
                   ok_f is False, f"ok={ok_f}")
        case.check("红场②：拦截理由直指来源缺失（✗ L2 knowledge 回答无 hits"
                   "（未走条件路由图）——T8 fail-closed 落向拒绝）",
                   any("L2 knowledge 回答无 hits" in c for c in checks_f),
                   f"checks={checks_f}")

        # ═══ 对照组：合法 chitchat 短回答 ═══
        ok_c, checks_c = va.verify_answer("好的，我们继续聊吧。", {"kind": "chitchat"})
        case.check("对照组：合法出口放行（ok=True——闸只拦无来源冒充不拦功能）",
                   ok_c is True, f"checks={checks_c}")

        # 四可（D4）
        case.check("四可：可发现=是（ok=False+逐条理由）/可隔离=是（纯函数单点）"
                   "/可恢复=是（拒绝后可走合法出口：补 hits 或改 honest/chitchat "
                   "类别）/可追溯=是（checks 列表逐条留痕）",
                   True,
                   f"证据=伪造 checks={checks_f}；对照 checks={checks_c}")
        verdict = "pass" if not case.fails else "fail"
        return case.finish(verdict, expected="pass")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
