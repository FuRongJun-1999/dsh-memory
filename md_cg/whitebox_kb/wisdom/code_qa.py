# -*- coding: utf-8 -*-
"""code_qa.py · 代码问答（第五阶段·代码条件单元库进对话）
条件单元库 + 影响分析 → 白箱代码问答（零 LLM）：
  改 X 影响谁（影响面）/ X 依赖什么（条件）/ X 和 Y 能并行测试吗（独立性）/ 仓库统计
"""
import sys
import re
sys.stdout.reconfigure(encoding='utf-8')
try:
    from code_route_bridge import (build_code_route_units,
                                   code_jacobian_independence)
    from codegraph_white import impact_analysis_repo, repo_stats
except ImportError:
    from .code_route_bridge import (build_code_route_units,
                                    code_jacobian_independence)
    from .codegraph_white import impact_analysis_repo, repo_stats


def _extract_funcs(question, units):
    """从问题提取函数名（与单元库键匹配，取最长优先）
    短函数名（len<=2）用词边界匹配——防「a」误命中「base」里的 'a'"""
    hits = []
    for name in sorted(units.keys(), key=len, reverse=True):
        if len(name) <= 2:
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) +
                         r"(?![A-Za-z0-9_])", question):
                hits.append(name)
        elif name in question:
            hits.append(name)
    return hits


def _classify(q):
    """问题意图分类：按关键词命中分派问型（并行/影响/依赖等），决定 QA 检索的回答路径。"""
    if any(w in q for w in ("能并行", "同时测", "并行测试", "一起测")):
        return "并行"
    if any(w in q for w in ("改", "影响", "波及", "连累", "改动")):
        return "影响"
    if any(w in q for w in ("依赖", "调用", "需要", "用到")):
        return "依赖"
    if any(w in q for w in ("多少", "几个", "统计", "有多少")):
        return "统计"
    return None


def code_qa(question, repo):
    """代码问答：类型识别 → 函数名提取 → 对应分析 → 白箱回答"""
    units = build_code_route_units(repo)
    qtype = _classify(question)
    if qtype is None:
        return {"ok": False, "reply": "（非代码问答——不属代码理解域）", "type": None}
    funcs = _extract_funcs(question, units)
    if qtype == "统计":
        st = repo_stats(repo)
        return {"ok": True, "type": "统计",
                "reply": f"仓库共 {st['files']} 个文件、{st['functions']} 个函数、"
                         f"{st['classes']} 个类、{st['cross_calls']} 处跨文件调用。",
                "detail": st}
    if not funcs:
        return {"ok": False, "type": qtype,
                "reply": f"（问题中未识别到仓库内的函数名——诚实边界）"}
    name = funcs[0]
    if qtype == "影响":
        r = impact_analysis_repo(repo, name)
        if not r["callers"]:
            return {"ok": True, "type": "影响",
                    "reply": f"改「{name}」不影响任何其他函数（无人调用它）。",
                    "detail": r}
        names = ", ".join(f"{c['name']}({c['file']},深度{c['depth']})"
                          for c in r["callers"])
        return {"ok": True, "type": "影响",
                "reply": f"改「{name}」会影响到: {names}。",
                "detail": r}
    if qtype == "依赖":
        deps = units[name]["conditions"]
        if not deps:
            return {"ok": True, "type": "依赖",
                    "reply": f"「{name}」不依赖任何仓库内函数（无调用）。",
                    "detail": deps}
        return {"ok": True, "type": "依赖",
                "reply": f"「{name}」依赖: {', '.join(deps)}。",
                "detail": deps}
    if qtype == "并行" and len(funcs) >= 2:
        a, b = funcs[0], funcs[1]
        j = code_jacobian_independence(units)
        for f1, f2, indep, shared in j["pairs"]:
            if {f1, f2} == {a, b}:
                if indep:
                    return {"ok": True, "type": "并行",
                            "reply": f"「{a}」和「{b}」无共享依赖，可以并行测试。",
                            "detail": {"independent": True}}
                return {"ok": True, "type": "并行",
                        "reply": f"「{a}」和「{b}」共享依赖 {shared}，"
                                 f"建议串行测试（防 mock 冲突）。",
                        "detail": {"independent": False, "shared": shared}}
        return {"ok": True, "type": "并行",
                "reply": f"「{a}」和「{b}」无共享依赖，可以并行测试。",
                "detail": {"independent": True}}
    return {"ok": False, "type": qtype,
            "reply": f"（「{name}」的{ { '并行': '并行', '影响': '影响', '依赖': '依赖' }[qtype] }分析不可用——诚实边界）"}


if __name__ == "__main__":
    print("=== 代码问答：代码条件单元库进对话（零 LLM）===\n")
    import os, tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="code_qa_")
    with open(os.path.join(tmp, "lib.py"), "w", encoding="utf-8") as f:
        f.write("def base(x):\n    return x\n\ndef a():\n    return base(1)\n"
                "\ndef b():\n    return base(2)\n\ndef c():\n    return a()\n"
                "\ndef d():\n    return 42\n")
    from codegraph_white import analyze_repository
    repo = analyze_repository(tmp)
    for q in ["改 base 会影响哪些函数？", "base 依赖什么？",
              "a 和 d 能并行测试吗？", "仓库里有多少函数？", "什么是碳中和？"]:
        r = code_qa(q, repo)
        mark = "✔" if r.get("ok") else "✘"
        print(f"[{mark}] Q: {q}")
        print(f"     A: {r.get('reply', '')}")
    shutil.rmtree(tmp, ignore_errors=True)
