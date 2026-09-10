# -*- coding: utf-8 -*-
"""灵枢 · 卡校验器 card_validator（自生长闭环第一步 · v1.16）

对 LLM 写的候选卡做机械五查（结构闸门）：
  1. 字段完整性：name/domain/level/response{trigger,action,counters}/
     condition_space 四要素/content 非空；学科卡必带 edu_level
  2. 条件空间四要素：observation_position/observation_tool/
     time_window/existence_constraint 全声明
  3. counters 冲突：新卡 counters 与现有卡 counters 交叉匹配
     （二元组交集 ≥4 视为潜在冲突 → 提示设计者）
  4. 学科域/教育层级归属：domain 可识别；edu_level ∈ E1-E5；学科卡必带层级
  5. 测试用例可执行性（★ 物理信息基底闸门的前置）：tests 字段存在且
     含可观测判据（observable/topic/expected 或 propositions+observable）

输出：{verdict: pass/needs_revision/fail, checks, pending_designer}
pass → pending_designer（人工终裁，方向闸门）
needs_revision → 打回 LLM 重写（带检查报告）
fail → 拒绝（结构致命缺失）

设计边界：校验器只做机械检查（结构/格式/冲突信号），不裁决知识真理性——
真理由物理信息基底裁决（测试用例实际执行），方向由设计者终裁。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 教育层级
EDU_LEVELS = {"E1", "E2", "E3", "E4", "E5"}
# 条件空间四要素
CS_FIELDS = ["observation_position", "observation_tool",
             "time_window", "existence_constraint"]
# 学科卡必带字段（response 三件套）
RESP_FIELDS = ["trigger", "action", "counters"]
# 卡必带 state_attributes
SA_REQUIRED = ["name", "domain", "level", "response"]


def _bigram_set(text):
    """二元组集合（去非中文/字母数字）。"""
    import re
    t = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def load_existing_counters(dex=None):
    """现有 138 卡 counters 文本集合（供冲突检测）。"""
    out = []
    if dex is None:
        return out
    try:
        from aeis_core import MemoryLayer
        for n in dex.store.query_nodes(layer=MemoryLayer.KNOWLEDGE, limit=500):
            sa = n.state_attributes
            if not sa.get("name"):
                continue
            c = (sa.get("response") or {}).get("counters", "") or ""
            if c:
                out.append((sa.get("name"), c))
    except Exception:
        pass
    return out


def validate(card, dex=None, existing_counters=None):
    """五查机械校验。card: dict（LLM 写的候选卡）或 ConditionDex 节点 dict。
    返回 {verdict, checks: [{check, passed, detail}], pending_designer}。"""
    checks = []
    # ---------- 1. 字段完整性 ----------
    missing = []
    for f in SA_REQUIRED:
        if not card.get(f):
            missing.append(f)
    resp = card.get("response") or {}
    for f in RESP_FIELDS:
        if not resp.get(f):
            missing.append(f"response.{f}")
    if not (card.get("content") or card.get("claim")):
        missing.append("content/claim")
    # 学科卡（domain 不是协议层）必带 edu_level
    is_protocol = card.get("domain") in (
        "智能论", "条件论", "存在论", "信息论", "负反馈系统", "认知双过程",
        "情感-信任连接", "自我增强回路", "自我意识", "决策论", "博弈论",
        "统计学", "概率论", "形式逻辑", "科学方法论", "控制论", "机制设计",
        "时空记忆图", "情感情绪仿真", "价值理论与AI对齐", "复杂系统与涌现",
        "自我实现预言", "智能推荐算法", "预测误差学习", "演化论与模因",
        "政治经济学", "热力学/耗散结构", "人类观察者")
    if not is_protocol and not card.get("edu_level"):
        missing.append("edu_level（学科卡必带教育层级）")
    checks.append({
        "check": "1.字段完整性", "passed": not missing,
        "detail": f"缺失: {missing}" if missing else "全部就位",
    })

    # ---------- 2. 条件空间四要素 ----------
    cs = card.get("condition_space") or card.get("cs") or {}
    if isinstance(cs, str):
        try:
            cs = json.loads(cs)
        except Exception:
            cs = {}
    cs_missing = [f for f in CS_FIELDS if not cs.get(f)]
    checks.append({
        "check": "2.条件空间四要素", "passed": not cs_missing,
        "detail": f"缺失: {cs_missing}" if cs_missing else "四要素齐备",
    })

    # ---------- 3. counters 冲突（与现有卡） ----------
    conflict = []
    new_counters = resp.get("counters", "") or ""
    if existing_counters is None:
        existing_counters = load_existing_counters(dex)
    new_cb = _bigram_set(new_counters)
    for name, c in existing_counters:
        if name == card.get("name"):
            continue
        inter = len(new_cb & _bigram_set(c))
        if inter >= 4:
            conflict.append(f"{name}(交集{inter})")
    checks.append({
        "check": "3.counters冲突", "passed": not conflict,
        "detail": f"潜在冲突: {conflict[:3]}" if conflict else "无冲突信号",
    })

    # ---------- 4. 学科域/教育层级归属 ----------
    dom = card.get("domain", "")
    edu = card.get("edu_level")
    dom_issues = []
    if not dom:
        dom_issues.append("domain 为空")
    if is_protocol and edu is not None and edu not in EDU_LEVELS:
        dom_issues.append(f"协议层卡不应带 edu_level={edu}")
    if not is_protocol:
        if edu not in EDU_LEVELS:
            dom_issues.append(f"edu_level={edu} 不在 E1-E5")
    checks.append({
        "check": "4.学科域/层级归属", "passed": not dom_issues,
        "detail": "; ".join(dom_issues) if dom_issues else f"domain={dom} edu={edu or '通用'}",
    })

    # ---------- 5. 测试用例可执行性（物理基底闸门 · v1.16 升级为真执行） ----------
    # 格式检查（可观测判据存在）是前置；tests.executable（lang/code）存在时
    # **真跑**——代码运行/编译结果 = 物理信息基底裁决（爸爸外部参照）。
    tests = card.get("tests") or card.get("test_cases")
    tests_ok = True
    tests_detail = "无 tests 字段"
    if tests:
        if isinstance(tests, dict):
            t_keys = [k for k in ("topic", "expected", "observable", "propositions") if tests.get(k)]
            tests_ok = bool(t_keys)
            tests_detail = f"tests 含: {t_keys}" if t_keys else "tests 字段缺可观测判据"
            # 真执行：tests.executable 存在 → 物理基底校准（代码类卡）
            ex = tests.get("executable")
            if ex and isinstance(ex, dict) and ex.get("lang") and ex.get("code"):
                try:
                    from code_test_runner import CodeTestRunner
                    run_r = CodeTestRunner().run_card({"name": card.get("name"), "tests": tests})
                    status = run_r.get("status", "error")
                    if status == "pass":
                        tests_ok = True
                        tests_detail = (f"物理基底真跑 PASS: {run_r.get('detail','')}"
                                        f"{' | out: '+run_r['output'][:40] if run_r.get('output') else ''}")
                    elif status == "env_missing":
                        tests_ok = True  # 环境缺失不判卡错（D-005 诚实降级），
                        # 但标记待环境——格式仍通过，设计者终裁时可见
                        tests_detail = f"物理基底：环境缺失（{run_r.get('detail','')[:50]}）——待环境"
                    else:
                        tests_ok = False
                        tests_detail = f"物理基底真跑 FAIL: {run_r.get('detail','')[:120]}"
                except Exception as e:
                    tests_ok = False
                    tests_detail = f"物理基底执行异常: {str(e)[:100]}"
        elif isinstance(tests, list) and tests:
            tests_ok = any(isinstance(t, dict) and ("observable" in t or "expected" in t)
                           for t in tests)
            tests_detail = "tests 列表含可观测判据" if tests_ok else "tests 列表缺可观测判据"
    else:
        tests_ok = False
    checks.append({
        "check": "5.测试用例可执行性", "passed": tests_ok,
        "detail": tests_detail,
    })

    # ---------- 汇总 ----------
    passed_all = all(c["passed"] for c in checks)
    fail_count = sum(1 for c in checks if not c["passed"])
    if fail_count == 0:
        verdict = "pass"
    elif fail_count <= 2 and not any(c["check"].startswith("1.") for c in checks if not c["passed"]):
        verdict = "needs_revision"
    else:
        verdict = "fail"
    return {
        "verdict": verdict,
        "checks": checks,
        "pending_designer": verdict == "pass",
        "summary": f"{verdict}: {sum(1 for c in checks if c['passed'])}/5 通过",
    }


# ---------------- 自测 ----------------
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    GOOD = {
        "name": "测试卡", "domain": "物理学", "level": 2, "edu_level": "E2",
        "response": {"trigger": "涉及测试议题", "action": "以测试知识回应",
                     "counters": "越级使用未学概念"},
        "condition_space": {"observation_position": "测试位",
                            "observation_tool": "测试工具",
                            "time_window": [0.0, 9999999999.0],
                            "existence_constraint": "测试约束"},
        "content": "测试内容",
        "tests": {"topic": "测试主题", "observable": "可观测判据"},
    }
    BAD = {"name": "残缺卡", "domain": "未知领域"}
    for label, c in [("GOOD", GOOD), ("BAD", BAD)]:
        r = validate(c)
        print(f"[{label}] {r['summary']}")
        for ch in r["checks"]:
            mark = "✓" if ch["passed"] else "✗"
            print(f"  {mark} {ch['check']}: {ch['detail']}")
        print(f"  pending_designer={r['pending_designer']}")
