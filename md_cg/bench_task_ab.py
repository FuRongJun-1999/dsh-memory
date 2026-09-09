# -*- coding: utf-8 -*-
"""任务级 A/B 对照实验：无记忆 vs 有记忆（白箱第 5 篇第 9 章「验证方法」）

评测问题：**把「已写入的失败教训」装进记忆后，AI 在同类任务上是否少犯错？**

两臂唯一差异 = 记忆库：
  arm_none  空库：面对错误只能靠字面猜测下一步动作，选错就试错重来
  arm_mem   有库：Phase A 用 mine_fix_pairs 把「错误 → 修复」写进知识 + 负记忆；
            Phase B 先 recall(错误) 再决策，命中修复知识则一次到位

指标（确定性模拟，不调用 LLM）：
  first_try_rate     首次决策就选对的比例（最不受试错上限影响的指标）
  success_rate       在 max_turns 内选中正确修复的比例（越高越好）
  repeat_error_rate  至少踩过一次已知陷阱的比例（越高越糟 = 重复犯错）
  avg_turns          达成正确决策所需轮数（无记忆臂靠试错，越多越差）
  avg_tokens         每次决策的召回上下文 token（记忆的代价，诚实计入）
  hit_rate           Phase B 中 recall 直接命中修复知识的比例

诚实边界（不夸大结论）：
  1) 这是确定性模拟器，不是 LLM 端到端评测。它测的是「记忆机制能否把已写入的
     教训在下次同类任务里用起来」，不测「LLM 会不会变聪明」。
  2) 陷阱与修复都是 Phase A 写入的，实验验证的是复用能力，不是凭空学习能力。
  3) 两臂的候选动作池完全相同，差别只有记忆库——这是 A/B 的唯一变量。
  4) 无记忆臂的策略是「按字面覆盖选 top-1，选错则排除重试」，这是对无历史
     agent 的合理建模，但它仍是一个建模选择，不是真实 agent 的行为分布。

跑法：
    python -m md_cg.bench_task_ab
    python -m md_cg.bench_task_ab --cases 6 --max-turns 3
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile

from md_cg.mdcg import expand_query_terms_weighted
from md_cg.mdcos import MdCGOS, _weighted_coverage

# 12 个工程常见坑：trap 与 error 的字面重叠刻意高于 fix，用来模拟
# 「没有记忆时，最像对症的动作往往正是坑」。
CASES = [
    {"id": "c01", "error": "ModuleNotFoundError: No module named 'requests'",
     "fix": "pip install requests",
     "trap": "ModuleNotFoundError 时跳过 requests 相关功能",
     "decoy": "重启开发机"},
    {"id": "c02", "error": "PermissionError: [Errno 13] Permission denied: '/var/log/app.log'",
     "fix": "chmod 640 /var/log/app.log 并以具备写权限的用户运行",
     "trap": "PermissionError 时忽略日志写入失败",
     "decoy": "格式化磁盘"},
    {"id": "c03", "error": "SyntaxError: invalid syntax 在 f-string 里的引号冲突",
     "fix": "把外层引号换成双引号并转义内层引号",
     "trap": "SyntaxError 时删除整段代码",
     "decoy": "重装 Python"},
    {"id": "c04", "error": "ConnectionRefusedError: 端口 5432 连接被拒绝",
     "fix": "启动 postgres 服务并确认监听 5432",
     "trap": "ConnectionRefusedError 时改用本地 sqlite",
     "decoy": "更换网线"},
    {"id": "c05", "error": "KeyError: 'user_id' 在请求体里缺失",
     "fix": "用 payload.get('user_id') 并返回 400",
     "trap": "KeyError 时给 user_id 赋默认空字符串",
     "decoy": "重启 API 服务"},
    {"id": "c06", "error": "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
     "fix": "显式 int(x) 转换后再相加",
     "trap": "TypeError 时把整个表达式改成字符串拼接",
     "decoy": "升级 numpy"},
    {"id": "c07", "error": "TimeoutError: 请求 30s 未响应",
     "fix": "给请求加 5s 超时并重试 2 次",
     "trap": "TimeoutError 时无限重试",
     "decoy": "更换 DNS"},
    {"id": "c08", "error": "FileNotFoundError: 'config.yaml' 不存在",
     "fix": "检查工作目录并用绝对路径读取 config.yaml",
     "trap": "FileNotFoundError 时跳过配置加载",
     "decoy": "重装操作系统"},
    {"id": "c09", "error": "UnicodeDecodeError: 'gbk' codec can't decode byte 0xa3",
     "fix": "以 encoding='utf-8' 打开文件",
     "trap": "UnicodeDecodeError 时用 errors='ignore' 丢掉数据",
     "decoy": "换一台电脑"},
    {"id": "c10", "error": "IndexError: list index out of range 在分页第 2 页",
     "fix": "先判断 len(items) 再取下标",
     "trap": "IndexError 时直接把分页关掉",
     "decoy": "增加内存"},
    {"id": "c11", "error": "MemoryError: 一次加载 10GB csv 到内存",
     "fix": "改用 pandas chunksize 分块读取",
     "trap": "MemoryError 时无限增大 swap",
     "decoy": "换 CPU"},
    {"id": "c12", "error": "AssertionError: 断言 user.name == 'admin' 失败",
     "fix": "检查测试夹具里的用户角色并修正期望值",
     "trap": "AssertionError 时直接删掉这条断言",
     "decoy": "重跑 CI"},
]


def _terms(text):
    tw = expand_query_terms_weighted(text) or {}
    tw.pop("__source__", None)
    return {str(k): float(v) for k, v in tw.items()
            if not str(k).startswith("__")}


def _pick_lexical(error, candidates):
    """无记忆臂的确定性策略：按字面覆盖选 top-1（字面平局时按候选顺序）。"""
    tw = _terms(error)
    best, best_s = candidates[0], -1.0
    for c in candidates:
        s = _weighted_coverage(tw, c)
        if s > best_s:
            best, best_s = c, s
    return best


def _trial(error, candidates, fix, max_turns):
    """无记忆臂：选错就排除该动作、下一轮重选（模拟试错）。"""
    pool = list(candidates)
    touched, turns = [], 0
    last = None
    while pool and turns < max_turns:
        turns += 1
        last = _pick_lexical(error, pool)
        touched.append(last)
        if last == fix:
            return {"success": True, "turns": turns, "pick": last,
                    "touched": touched}
        pool.remove(last)
    return {"success": False, "turns": turns, "pick": last,
            "touched": touched}


def _decide_mem(cg, query, case, candidates, max_turns, budget):
    """有记忆臂：先召回，命中修复知识则一次到位；否则回退到试错。"""
    res = cg.recall(query, budget_tokens=budget, k=20)
    tokens = int(res.get("tokens_used") or 0)
    text = " ".join((p.get("content") or "") for p in res.get("pack") or [])
    if case["fix"] and case["fix"] in text:
        return {"success": True, "turns": 1, "pick": case["fix"],
                "touched": [], "tokens": tokens, "hit": True}
    fb = _trial(case["error"], candidates, case["fix"], max_turns)
    fb.update({"tokens": tokens, "hit": False, "turns": 1 + fb["turns"]})
    return fb


def _pct(x):
    return f"{100.0 * x:.1f}%"


def _report(rows, mined, max_turns):
    n = len(rows)
    print("\n" + "=" * 74)
    print("任务级 A/B 对照（白箱智能系列·第五篇 第 9 章「验证方法」）")
    print("=" * 74)
    print(f"样本 {n} 条 · 两臂候选动作池完全相同，唯一差异是记忆库 · "
          f"试错上限 {max_turns} 轮（已对无记忆臂放宽：允许排除刚试过的动作）")
    print(f"Phase A 写入：{len(mined['pairs'])} 组修复对"
          f"（知识 {len(mined['knowledge_ids'])} + 负记忆 {len(mined['rejected_ids'])}）\n")

    ns = sum(1 for _c, rn, _rm in rows if rn["success"]) / n
    ms = sum(1 for _c, _rn, rm in rows if rm["success"]) / n
    nf = sum(1 for _c, rn, _rm in rows if rn["success"] and rn["turns"] == 1) / n
    mf = sum(1 for _c, _rn, rm in rows if rm["success"] and rm["turns"] == 1) / n
    nr = sum(1 for c, _rn, _rm in rows if c["trap"] in _rn["touched"]) / n
    mr = sum(1 for c, _rn, rm in rows if c["trap"] in rm["touched"]) / n
    nt = sum(rn["turns"] for _c, rn, _rm in rows) / n
    mt = sum(rm["turns"] for _c, _rn, rm in rows) / n
    nk = sum(rn.get("tokens") or 0 for _c, rn, _rm in rows) / n
    mk = sum(rm.get("tokens") or 0 for _c, _rn, rm in rows) / n
    hit = sum(1 for _c, _rn, rm in rows if rm.get("hit")) / n

    print(f"{'指标':<20}{'arm_none':>14}{'arm_mem':>14}{'差值':>16}")
    print("-" * 74)
    print(f"{'first_try_rate':<20}{_pct(nf):>14}{_pct(mf):>14}"
          f"{f'+{100 * (mf - nf):.1f}pp':>16}")
    print(f"{'success_rate':<20}{_pct(ns):>14}{_pct(ms):>14}"
          f"{f'+{100 * (ms - ns):.1f}pp':>16}")
    print(f"{'repeat_error_rate':<20}{_pct(nr):>14}{_pct(mr):>14}"
          f"{f'{100 * (mr - nr):.1f}pp':>16}")
    print(f"{'avg_turns':<20}{nt:>14.2f}{mt:>14.2f}{f'{mt - nt:+.2f}':>16}")
    print(f"{'avg_tokens':<20}{nk:>14.1f}{mk:>14.1f}{f'{mk - nk:+.1f}':>16}")
    print(f"{'recall_hit_rate':<20}{'-':>14}{_pct(hit):>14}{'-':>16}")

    print("\n逐例（pick = 最终决策动作；hit = 召回直接命中修复知识）：")
    for c, rn, rm in rows:
        mark_n = "OK " if rn["success"] else "X  "
        mark_m = "OK " if rm["success"] else "X  "
        print(f"  {c['id']}  none[{mark_n}t={rn['turns']}]  "
              f"mem[{mark_m}t={rm['turns']} hit={int(bool(rm.get('hit')))}]  {c['error'][:44]}")

    print("\n结论口径：")
    print(f"  · 无记忆臂的 success_rate={_pct(ns)} 是「排除法试错」的产物"
          f"（{max_turns} 轮内排除错项后总能收敛），因此看首次决策正确率："
          f"{_pct(nf)} → {_pct(mf)}。")
    if mf > nf and mr < nr:
        print(f"  · 有记忆臂首次决策正确率 +{100 * (mf - nf):.1f}pp，"
              f"重复犯错率 {100 * (mr - nr):.1f}pp（{_pct(nr)} → {_pct(mr)}），"
              f"平均轮数 {mt - nt:+.2f}，代价是每次多 {mk - nk:.0f} token。")
        print("  · 即：把「错误→修复」写进记忆后，同类任务不再重复踩坑——"
              "但这是确定性模拟器结论，真实 LLM 端到端仍需实测。")
    elif mf == nf:
        print("  · 两臂首次决策正确率相同：记忆未带来增益"
              "（可能是召回未命中或数据不敏感），如实报告，不粉饰。")
    else:
        print(f"  · 记忆臂首次正确率 {_pct(mf)} vs 无记忆 {_pct(nf)}，未达预期，如实报告。")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description="任务级 A/B：无记忆 vs 有记忆")
    ap.add_argument("--cases", type=int, default=0, help="只用前 N 个用例（0=全部）")
    ap.add_argument("--max-turns", type=int, default=2,
                    help="试错上限（默认 2 = 一次尝试 + 一次重试）")
    ap.add_argument("--budget", type=int, default=2000, help="召回 token 预算")
    a = ap.parse_args(argv)
    cases = CASES[:a.cases] if a.cases else CASES

    root = tempfile.mkdtemp(prefix="mdcg_ab_")
    try:
        none_arm = MdCGOS(os.path.join(root, "none"))
        mem_arm = MdCGOS(os.path.join(root, "mem"))
        mined = mem_arm.mine_fix_pairs(
            [{"error": c["error"], "fix": c["fix"]} for c in cases])
        rows = []
        for c in cases:
            q = "再次遇到： " + c["error"]
            cands = [c["fix"], c["trap"], c["decoy"]]
            rn = _trial(c["error"], cands, c["fix"], a.max_turns)
            rm = _decide_mem(mem_arm, q, c, cands, a.max_turns, a.budget)
            rows.append((c, rn, rm))
        _report(rows, mined, a.max_turns)
        _ = none_arm  # 空库臂不召回，故不产生 token；保留以便对照可扩展
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
