# -*- coding: utf-8 -*-
"""任务级 A/B 真实端到端评测（先验陷阱版）：无记忆 vs 有记忆

为什么要重做成「先验陷阱」：
  上一版用 12 个教科书级报错（缺依赖、权限、超时…）。实测发现：这类题的正确答案
  就在模型先验里——9B 小模型无记忆也有 94.4%，强模型 98.6%。也就是说**题目本身
  低于模型能力下限，天花板效应把记忆的价值全遮住了**。用户判断成立。

本版的设计原则（用户提出）：
  「所有的知识都有隐形的条件。只有具有完整的记忆，才能发现哪些是当前不适用的知识。」
  因此每个用例都是一个**先验陷阱**：
    · trap  = 通用最佳实践 / 教科书答案（模型会自信地选它）
    · fix   = 本项目规范下的正确做法（与最佳实践相反，只有记忆里的隐性条件能推出）
    · decoy = 明显错误的做法
  无记忆臂只能靠先验，会掉进 trap；有记忆臂能读到「项目规范 + 历史事故」这条隐性
  条件，从而发现最佳实践在当前项目里**不适用**，改选 fix。

唯一变量 = 记忆库；其余全同（同一模型、temperature=0、同一系统提示）。

防作弊设计：
  1) 措辞不同：记忆写「项目规范/原因」，候选写「具体动作」，模型须自行映射，不能照抄。
  2) 多排列去位置偏差：每例跑 3 种**循环排列**（rotations），使每个候选在 3 个位置上
     各出现一次——只有「按内容选」才能 3/3 全中；纯位置偏差只能 1/3。位置分布单列。

指标（以 (用例 × 排列) 为单位）：
  content_acc     按内容选对的比例（主指标）
  trap_rate       选中「最佳实践陷阱」的比例（无记忆臂应显著 >0）
  invalid_rate    输出无法解析为候选编号的比例（不剔除，如实计入）
  pos_dist        选中位置分布（1/2/3），偏离均匀 = 位置偏差
  avg_tokens      每次调用总 token（记忆的代价）
  recall_hit_rate 记忆臂中 recall 确实召回该项目规范的比例

诚实边界：
  · 5 用例 × 3 排列 = 15 次/臂，样本很小，只作方向性验证。
  · 陷阱是否真的骗到模型，由 trap_rate 实测决定；骗不到就如实报告「该题不成立」。
  · 记忆能召回 ≠ 模型会用；hit 与 content_acc 分开统计正是为暴露这个差异。

跑法：
    python -m md_cg.bench_task_ab_llm                 # deepseek-v4-flash（默认）
    python -m md_cg.bench_task_ab_llm --local         # 追加本地小模型
    python -m md_cg.bench_task_ab_llm --perms 6       # 全 6 种排列
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from md_cg.mdcos import MdCGOS

# ---- 系统提示（两臂完全相同）---------------------------------------------
SYS_PROMPT = (
    "你是本项目的资深工程师。用户给出一个工程场景和若干候选做法，"
    "你选一个最符合本项目既定规范的做法。\n"
    "只输出一行 JSON，不要解释、不要代码围栏，格式：\n"
    '{"pick": 2, "reason": "本项目规范要求..."}'
)

# ---- 5 个先验陷阱用例 ------------------------------------------------------
# task   ：场景（模型据此决策）
# lesson ：写入记忆的「项目规范 + 历史事故」（隐性条件，候选里不出现）
# query  ：召回用检索词
# fix/trap/decoy：候选做法；trap 是通用最佳实践（模型先验），fix 才是本项目正解
CASES = [
    {
        "id": "p01",
        "task": "API 的参数校验失败了，应该怎么给客户端返回？",
        "query": "API 参数校验失败 业务错误 返回 HTTP 状态码",
        "lesson": "本项目 API 契约：所有业务错误（含参数校验失败）必须返回 HTTP 200，"
                  "在 body 的 code 字段带业务错误码，禁止用 HTTP 4xx/5xx。"
                  "原因：老旧移动端 SDK 把任何非 200 都当成网络故障无限重试。",
        "trap": "返回 HTTP 400，body 里写清楚校验失败详情",
        "fix": "返回 HTTP 200，body 的 code 字段带业务错误码",
        "decoy": "返回 HTTP 500，让客户端稍后重试",
    },
    {
        "id": "p02",
        "task": "API 响应里要返回一个时间戳，用什么格式？",
        "query": "API 时间戳 格式 ISO 毫秒 时区",
        "lesson": "本项目 API 契约：所有时间戳统一返回 Unix 毫秒整数（int64），"
                  "禁止 ISO 8601 字符串和本地时间字符串。"
                  "原因：跨语言客户端解析不一致，历史事故是时区偏移导致订单时间错乱 8 小时。",
        "trap": "返回 ISO 8601 字符串，如 2026-09-09T12:00:00Z",
        "fix": "返回 Unix 毫秒整数（int64）",
        "decoy": "返回本地时间字符串，如 '2026/9/9 12:00'",
    },
    {
        "id": "p03",
        "task": "校验请求参数 x 必须是整数，怎么写这个判断？",
        "query": "校验 参数 整数 布尔 bool isinstance 精确类型",
        "lesson": "本项目校验规范：需要精确类型时必须用 type(x) is int，禁止 isinstance。"
                  "原因：bool 是 int 的子类，isinstance(True, int) 为真，"
                  "历史事故是布尔值被当成整数接受，写进了金额字段。",
        "trap": "用 isinstance(x, int) 判断",
        "fix": "用 type(x) is int 判断",
        "decoy": "用 x == int 判断",
    },
    {
        "id": "p04",
        "task": "从配置字典 cfg 里读一个可选字段的值，怎么写？",
        "query": "配置 字典 可选字段 缺失 None get 默认值",
        "lesson": "本项目配置规范：可选字段必须用 'key' in cfg 判断后再取值，禁止 .get()。"
                  "原因：.get() 把「显式 None」和「未配置」混为一谈，"
                  "历史事故是默认值覆盖了用户显式设置的空值。",
        "trap": "用 cfg.get('key', default) 取值",
        "fix": "用 'key' in cfg 判断后再取值",
        "decoy": "用 cfg['key'] 直接索引",
    },
    {
        "id": "p05",
        "task": "线上要记录一条警告信息（比如缓存 miss），用哪个日志级别？",
        "query": "日志 级别 警告 缓存 miss warning info 告警",
        "lesson": "本项目日志规范：warning 及以上级别会触发 PagerDuty 告警；"
                  "非故障类的警告必须用 info 级别并在消息里加 [WARN] 前缀，禁止直接用 warning。"
                  "原因：历史事故是缓存 miss 的 warning 半夜触发全组告警。",
        "trap": "用 logger.warning(...) 记录",
        "fix": "用 logger.info(...) 并在消息里加 [WARN] 前缀",
        "decoy": "用 logger.error(...) 记录",
    },
]

for _c in CASES:
    _c["marker"] = _c["lesson"][:12]


# ---- LLM 客户端（OpenAI 兼容，零第三方依赖）-------------------------------
def llm_chat(model, base, key, messages, timeout=180, max_tokens=200,
             temperature=0.0):
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    dt = time.time() - t0
    content = data["choices"][0]["message"].get("content") or ""
    return content, (data.get("usage") or {}), dt


def _parse_pick(raw, n):
    """从模型输出里抠出候选编号（1..n）；解析失败返回 None。"""
    s = raw or ""
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            obj = json.loads(s[i:j + 1])
            p = obj.get("pick")
            if isinstance(p, str) and p.strip().isdigit():
                p = int(p.strip())
            if isinstance(p, (int, float)) and 1 <= int(p) <= n:
                return int(p)
        except ValueError:
            pass
    m = re.search(r"\b([1-9])\b", s)
    if m and 1 <= int(m.group(1)) <= n:
        return int(m.group(1))
    return None


def _orders(case, n):
    """候选顺序。默认取 3 种循环排列（每个候选在 3 个位置各出现一次，天然去位置偏差）；
    n>3 时退回全 6 种排列。基准顺序由 case id 播种打乱，避免跨用例雷同。"""
    base = [("fix", case["fix"]), ("trap", case["trap"]),
            ("decoy", case["decoy"])]
    random.Random(case["id"]).shuffle(base)
    rots = [tuple(base[i:] + base[:i]) for i in range(3)]
    if n <= 3:
        return rots[:n]
    return list(itertools.permutations(base))[:n]


def _user_prompt(case, opts, memory=None):
    lines = []
    if memory:
        lines.append("【本项目规范 / 历史经验（来自记忆库，请自行判断相关性）】")
        lines.append(memory.strip())
        lines.append("")
    lines.append("场景：")
    lines.append(case["task"])
    lines.append("")
    lines.append("候选做法：")
    for idx, (_kind, txt) in enumerate(opts, 1):
        lines.append(f"{idx}. {txt}")
    lines.append("")
    lines.append("请选择最符合本项目规范的做法。")
    return "\n".join(lines)


def _build_memory(cg):
    """Phase A：把 5 条「项目规范」写进记忆（真实 mine_fix_pairs）。"""
    return cg.mine_fix_pairs(
        [{"error": c["task"], "fix": c["lesson"]} for c in CASES])


def _recall_memory(cg, case, budget):
    res = cg.recall("本项目规范：" + case["query"],
                    budget_tokens=budget, k=10)
    text = " ".join((p.get("content") or "") for p in res.get("pack") or [])
    return text[:1500], (case["marker"] in text)


def _run_one(cfg, case, opts, correct_pos, memory):
    messages = [{"role": "system", "content": SYS_PROMPT},
                {"role": "user", "content": _user_prompt(case, opts, memory)}]
    tokens, turns, pick, raw, dt = 0, 0, None, "", 0.0
    while turns < cfg["max_turns"]:
        turns += 1
        raw, usage, dt = llm_chat(cfg["model"], cfg["base"], cfg["key"],
                                  messages, timeout=cfg["timeout"],
                                  max_tokens=cfg["max_tokens"])
        tokens += int(usage.get("total_tokens") or 0)
        pick = _parse_pick(raw, len(opts))
        if pick == correct_pos or pick is None:
            break
        if turns < cfg["max_turns"]:
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user",
                             "content": f"第 {pick} 个做法执行后问题依旧。"
                                        f"请在剩余候选中重新选择，仍然只输出 JSON。"})
    kind = "invalid" if pick is None else opts[pick - 1][0]
    return {"pick": pick, "kind": kind, "correct": pick == correct_pos,
            "turns": turns, "tokens": tokens, "latency": dt}


def _run_model(label, cfg, cases, cg, n_perms, workers):
    # 记忆召回先串行算好（MdCGOS 非线程安全），LLM 调用再并发。
    mems = {}
    for case in cases:
        mems[case["id"]] = (_recall_memory(cg, case, cfg["budget"])
                            if cfg["use_mem"] else (None, False))

    tasks = []
    for case in cases:
        for oi, opts in enumerate(_orders(case, n_perms)):
            correct_pos = next(i for i, (k, _t) in enumerate(opts, 1)
                               if k == "fix")
            for arm in ("none", "mem"):
                tasks.append((case, oi, opts, correct_pos, arm))

    def work(t):
        case, oi, opts, correct_pos, arm = t
        memory, hit = mems[case["id"]] if arm == "mem" else (None, False)
        try:
            r = _run_one(cfg, case, opts, correct_pos, memory)
        except Exception as exc:                    # noqa: BLE001
            r = {"pick": None, "kind": "error", "correct": False,
                 "turns": 0, "tokens": 0, "latency": 0.0,
                 "raw": f"{type(exc).__name__}: {exc}"}
        r.update({"case": case["id"], "arm": arm, "hit": hit})
        print(f"  [{label}] {case['id']} {arm:<4} rot={oi} "
              f"-> pick={r['pick']} {r['kind']:<6} tok={r['tokens']:>4} "
              f"({r['latency']:.1f}s)", flush=True)
        return r

    rows = {"none": [], "mem": []}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(work, tasks):
            rows[r["arm"]].append(r)
    return rows


def _pct(x, n):
    return f"{100.0 * x / n:.1f}%" if n else "-"


def _report(label, rows, n_perms):
    n = len(rows["none"])
    print(f"\n{'-' * 78}")
    print(f"模型：{label}   样本 {n} 次（用例 × 排列）· 每例 {n_perms} 种排列")
    print(f"{'指标':<18}{'arm_none':>14}{'arm_mem':>14}{'差值':>16}")
    print("-" * 78)
    agg = {}
    for arm in ("none", "mem"):
        rs = rows[arm]
        agg[arm] = {
            "acc": sum(1 for r in rs if r["correct"]),
            "trap": sum(1 for r in rs if r["kind"] == "trap"),
            "invalid": sum(1 for r in rs if r["kind"] in ("invalid", "error")),
            "tokens": sum(r["tokens"] for r in rs),
            "latency": sum(r["latency"] for r in rs),
            "hit": sum(1 for r in rs if r["hit"]),
            "pos": [sum(1 for r in rs if r["pick"] == p) for p in (1, 2, 3)],
        }
    a, b = agg["none"], agg["mem"]
    d_acc = f"+{100.0 * (b['acc'] - a['acc']) / n:.1f}pp"
    d_trap = f"{100.0 * (b['trap'] - a['trap']) / n:.1f}pp"
    d_inv = f"{100.0 * (b['invalid'] - a['invalid']) / n:.1f}pp"
    d_tok = f"{(b['tokens'] - a['tokens']) / n:+.1f}"
    d_lat = f"{(b['latency'] - a['latency']) / n:+.2f}"
    print(f"{'content_acc':<18}{_pct(a['acc'], n):>14}{_pct(b['acc'], n):>14}"
          f"{d_acc:>16}")
    print(f"{'trap_rate':<18}{_pct(a['trap'], n):>14}{_pct(b['trap'], n):>14}"
          f"{d_trap:>16}")
    print(f"{'invalid_rate':<18}{_pct(a['invalid'], n):>14}"
          f"{_pct(b['invalid'], n):>14}{d_inv:>16}")
    print(f"{'avg_tokens':<18}{a['tokens'] / n:>14.1f}{b['tokens'] / n:>14.1f}"
          f"{d_tok:>16}")
    print(f"{'avg_latency_s':<18}{a['latency'] / n:>14.2f}"
          f"{b['latency'] / n:>14.2f}{d_lat:>16}")
    print(f"{'recall_hit_rate':<18}{'-':>14}{_pct(b['hit'], n):>14}{'-':>16}")
    print(f"{'pos_dist(1/2/3)':<18}"
          f"{'/'.join(str(x) for x in a['pos']):>14}"
          f"{'/'.join(str(x) for x in b['pos']):>14}{'—':>16}")

    print("\n逐用例 content_acc（按内容选对次数 / 该例排列数）：")
    for case in CASES:
        if not any(r["case"] == case["id"] for r in rows["none"]):
            continue
        an = [r for r in rows["none"] if r["case"] == case["id"]]
        am = [r for r in rows["mem"] if r["case"] == case["id"]]
        na = sum(1 for r in an if r["correct"])
        ma = sum(1 for r in am if r["correct"])
        hits = sum(1 for r in am if r["hit"])
        print(f"  {case['id']}  none {na}/{len(an)}   mem {ma}/{len(am)}  "
              f"hit {hits}/{len(am)}   {case['task'][:38]}")
    return agg


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="先验陷阱 A/B：无记忆 vs 有记忆（真实 LLM）")
    ap.add_argument("--model", default="deepseek-v4.1-flash-expires-on-0910")
    ap.add_argument("--base", default="https://api.deepseek.com/v1")
    ap.add_argument("--key", default="")
    ap.add_argument("--local", action="store_true",
                    help="追加本地小模型做对照")
    ap.add_argument("--local-model", default="smegmma-deluxe-9b-v1")
    ap.add_argument("--local-base", default="http://localhost:1234/v1")
    ap.add_argument("--cases", type=int, default=0, help="只用前 N 个用例")
    ap.add_argument("--only", default="", help="只用指定 id，逗号分隔，如 p01,p02")
    ap.add_argument("--perms", type=int, default=3, help="每例候选排列数（默认 3）")
    ap.add_argument("--budget", type=int, default=3000, help="召回 token 预算")
    ap.add_argument("--max-tokens", type=int, default=2000)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--workers", type=int, default=4, help="并发调用数")
    ap.add_argument("--max-turns", type=int, default=1,
                    help="最大轮数（1=单发；>1 则在选错后反馈重选）")
    a = ap.parse_args(argv)

    cases = CASES
    if a.only:
        want = {x.strip() for x in a.only.split(",") if x.strip()}
        cases = [c for c in cases if c["id"] in want]
    if a.cases:
        cases = cases[:a.cases]
    n_perms = max(1, min(6, a.perms))

    key = a.key or os.environ.get("DEEPSEEK_API_KEY") or ""
    if not key:
        print("[error] 需要 DEEPSEEK_API_KEY 或 --key")
        return 2

    root = tempfile.mkdtemp(prefix="mdcg_ab_prior_")
    try:
        cg = MdCGOS(os.path.join(root, "mem"))
        mined = _build_memory(cg)
        print(f"Phase A 写入记忆：{len(mined['pairs'])} 组"
              f"（知识 {len(mined['knowledge_ids'])} + 负记忆 {len(mined['rejected_ids'])}）")
        print(f"用例 {len(cases)} × 排列 {n_perms} × 2 臂 = "
              f"{len(cases) * n_perms * 2} 次调用")

        targets = [(a.model, a.model, a.base, key)]
        if a.local:
            targets.append(("local:" + a.local_model, a.local_model,
                            a.local_base, "lm-studio"))

        for label, model, base, mkey in targets:
            cfg = {"model": model, "base": base, "key": mkey,
                   "budget": a.budget, "timeout": a.timeout,
                   "max_tokens": a.max_tokens, "max_turns": a.max_turns,
                   "use_mem": True}
            rows = _run_model(label, cfg, cases, cg, n_perms, a.workers)
            _report(label, rows, n_perms)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
