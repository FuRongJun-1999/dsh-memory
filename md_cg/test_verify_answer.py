# -*- coding: utf-8 -*-
"""test_verify_answer.py —— 回答三层自校验专项测试（矩阵 v0.2 #22 · B→A）

背景（§2A-5）：verify_answer + chat_engine 强制闸代码齐备，但无专项测试、
无拒绝输出案例留痕；anchor 层 4 节点全部 vb=null（锚点自身无验证基底）。

本测试三部分：
  [1] 三层校验确定性用例矩阵（L1 结构 / L2 来源 / L3 边界：拦截 + 通过 + 边界值）
  [2] chat_engine 出口强制闸接线静态断言（所有回答出口必过 verify_answer，
      失败替换诚实声明——「写错会被拒绝」是机制非人肉）
  [3] 拒绝案例留痕：逐案例打印 ok + 校验明细（可复放），并以 anchor 规范
      锚点自指案例收尾（锚点描述的泄漏形态正是校验拦截的形态）
"""
import os
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_WISDOM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whitebox_kb", "wisdom")
sys.path.insert(0, _WISDOM)

from verify_answer import verify_answer, detect_card_format, LEGITIMATE_KINDS  # noqa: E402

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


# ------------------------------------------------------------------
# [1] 三层校验用例矩阵
# ------------------------------------------------------------------
print("\n[1] 三层校验用例矩阵（拦截 / 通过 / 边界值）\n")

# 每条：(名称, reply, meta, 期望ok, checks 必含关键词或 None)
CASES = [
    # ---- L1 结构：拦截 ----
    ("L1 空回答拦截", "", {"kind": "honest"}, False, "空/过短"),
    ("L1 过短拦截（1字）", "好", {"kind": "chitchat"}, False, "空/过短"),
    ("L1 矛盾句式拦截（整卡内部格式）",
     "自律是『即时奖励』vs『延迟满足』的矛盾——需要平衡短期与长期。",
     {"kind": "knowledge", "hits": [{"name": "自律"}]}, False, "内部格式泄漏"),
    ("L1 真相标记拦截", "延迟满足的真相：越能等待的孩子未来成就越高。",
     {"kind": "knowledge", "hits": [{"name": "延迟满足"}]}, False, "内部格式泄漏"),
    ("L1 括号密度拦截（6个且>8%）", "（甲）（乙）（丙）（丁）（戊）（己）",
     {"kind": "knowledge", "hits": [{"name": "卡"}]}, False, "内部格式泄漏"),
    ("L1 超长拦截（501字疑似整卡）", "字" * 501, {"kind": "knowledge", "hits": [{"name": "卡"}]},
     False, "超长"),
    # ---- L2 来源：拦截 ----
    ("L2 未知出口类别拦截", "正常回答内容。", {"kind": "hack"}, False, "未知出口类别"),
    ("L2 knowledge 无 hits 拦截", "这是一个带卡导航的正常回答，可以看「某卡」。",
     {"kind": "knowledge", "hits": []}, False, "无 hits"),
    ("L2 knowledge 缺卡导航拦截", "这是一个没有导航的知识性回答。",
     {"kind": "knowledge", "hits": [{"name": "某卡"}]}, False, "缺卡导航"),
    # ---- L3 边界：拦截 ----
    ("L3 多处省略号截断拦截", "第一部分...第二部分...第三部分...还有",
     {"kind": "chitchat"}, False, "疑似截断"),
    ("L3 TODO 占位拦截", "这个回答还没写完 TODO", {"kind": "chitchat"}, False, "占位残留"),
    ("L3 函数占位拦截", "计算结果见 {fn}", {"kind": "chitchat"}, False, "占位残留"),
    ("L3 占位字样拦截", "此处为占位内容，后续补充。", {"kind": "chitchat"}, False, "占位残留"),
    # ---- 通过面 ----
    ("通过：knowledge 带hits+卡导航",
     "常温下金属可以导电，细节可以看「金属导电卡」。",
     {"kind": "knowledge", "hits": [{"name": "金属导电卡"}]}, True, None),
    ("通过：knowledge 带hits+条件空间",
     "常温下金属可以导电（这条知识属于金属导电卡的条件空间：常温干燥）。",
     {"kind": "knowledge", "hits": [{"name": "金属导电卡"}]}, True, None),
    ("通过：honest 诚实边界", "我没有把握回答这个问题，需要先查证。",
     {"kind": "honest"}, True, None),
    ("通过：chitchat 闲聊", "今天过得不错，谢谢关心。", {"kind": "chitchat"}, True, None),
    ("通过：emotion 情感", "我理解你的感受，慢慢来。", {"kind": "emotion"}, True, None),
    ("通过：memory 回忆", "我们上次聊过类似的话题。", {"kind": "memory"}, True, None),
    ("通过：缺省 kind 视为 knowledge 且须合规",
     "答案如下，可以看「规则卡」。", {"hits": [{"name": "规则卡"}]}, True, None),
    # ---- 边界值（正确放行 / 正确拦截的临界）----
    ("边界：恰500字不超长", "答" * 500, {"kind": "chitchat"}, True, None),
    ("边界：恰2处省略号不拦", "第一...第二...", {"kind": "chitchat"}, True, None),
    ("边界：5个括号不触发密度（需>=6）", "（一）（二）（三）（四）（五）个要点总结",
     {"kind": "chitchat"}, True, None),
]

refusals = []  # 拒绝案例留痕
for name, reply, meta, want_ok, key in CASES:
    ok, checks = verify_answer(reply, meta)
    detail = "；".join(checks)
    if want_ok:
        check(f"{name} → ok=True", ok is True, detail)
    else:
        hit = (key in detail) if key else True
        check(f"{name} → ok=False 且命中「{key}」", (ok is False) and hit, detail)
        if ok is False:
            refusals.append({"case": name, "reply": reply[:40], "checks": checks})

# L1 检测函数直接断言（矛盾句式 / 真相标记特征源）
check("detect_card_format 矛盾句式特征名", detect_card_format(
    "这是『A』vs『B』的矛盾——说明") == "矛盾句式")
check("detect_card_format 正常人话返回 None", detect_card_format("正常的一句话回答。") is None)
check("LEGITIMATE_KINDS 出口类别表非空", len(LEGITIMATE_KINDS) >= 10,
      f"{len(LEGITIMATE_KINDS)} 类")

# ------------------------------------------------------------------
# [2] chat_engine 出口强制闸接线静态断言
# ------------------------------------------------------------------
print("\n[2] chat_engine 出口强制闸接线（静态断言，不拉起全家桶）\n")
eng = open(os.path.join(_WISDOM, "chat_engine.py"), encoding="utf-8").read()
check("接线：chat_engine 内 import verify_answer", "from verify_answer import verify_answer" in eng)
check("接线：失败替换为诚实声明（拒绝输出内部格式）", "未能通过白箱回答验证" in eng)
check("接线：失败处置记录 stderr 留痕", "[verify_answer] 拒绝输出内部格式" in eng)
spec = open(os.path.join(_WISDOM, "answer_spec_anchor.py"), encoding="utf-8").read()
check("规范锚点源：answer_spec_anchor 声明三层校验纪律",
      "verify_answer" in spec and "immutable" in spec)

# ------------------------------------------------------------------
# [3] 拒绝案例留痕汇总（可复放）+ 规范锚点自指案例
# ------------------------------------------------------------------
print(f"\n[3] 拒绝案例留痕（{len(refusals)} 条，全部拦截成功）")
for i, r in enumerate(refusals, 1):
    fails = "；".join(c for c in r["checks"] if c.startswith("✗"))
    print(f"  {i:>2}. {r['case']}  →  {fails}")

# 自指案例：规范锚点警告的泄漏形态（『A』vs『B』矛盾句式）被校验精准拦截
leak_demo = "自律是『即时奖励』vs『延迟满足』的矛盾——这是内部格式的样子。"
ok, checks = verify_answer(leak_demo, {"kind": "knowledge", "hits": [{"name": "卡"}]})
check("自指：规范锚点所述泄漏形态被校验拦截", ok is False,
      "；".join(c for c in checks if c.startswith("✗")))

# ------------------------------------------------------------------
print("\n" + "=" * 60)
print(f"verify_answer 专项测试：{PASS} 通过 / {FAIL} 失败"
      f"（拒绝案例留痕 {len(refusals)} 条）")
sys.exit(0 if FAIL == 0 else 1)
