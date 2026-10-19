# -*- coding: utf-8 -*-
"""对 WorkBuddy 提示词对比实验的运行快照打分并汇总。

输入：collect_workbuddy_runs.py 产出的目录（*.jsonl + manifest.json）。
输出：scores.json、report.md。

判据见《提示词对比实验_设计_v1.0.md》§4.2；这里只做可复现的自动辅助判分，
最终结论仍需人工复核每条输出。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from pathlib import Path

CJK = re.compile(r"[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-z]")


def lang_stats(text: str) -> dict:
    zh = len(CJK.findall(text or ""))
    en = len(LATIN.findall(text or ""))
    total = zh + en
    ratio = (zh / total) if total else 0.0
    if total < 20:
        label = "NONE"
    elif ratio >= 0.30:
        label = "ZH"
    elif ratio < 0.15:
        label = "EN"
    else:
        label = "MIXED"
    # 思考开头 300 字：避免长中文引文把整段判成 MIXED/ZH
    head = lang_stats_head((text or "")[:300])
    return {
        "zh_chars": zh,
        "en_chars": en,
        "zh_ratio": round(ratio, 3),
        "label": label,
        "head_label": head,
        "opener": opener_lang(text or ""),
    }


def opener_lang(text: str) -> str:
    """思考的第一语言字符：比全文占比更抗「中文引文」污染。"""
    s = (text or "").strip()
    for ch in s[:80]:
        if CJK.match(ch):
            return "ZH"
        if LATIN.match(ch):
            return "EN"
    return "NONE"


def lang_stats_head(text: str) -> str:
    zh = len(CJK.findall(text or ""))
    en = len(LATIN.findall(text or ""))
    total = zh + en
    if total < 20:
        return "NONE"
    ratio = zh / total
    return "ZH" if ratio >= 0.30 else ("EN" if ratio < 0.15 else "MIXED")


def collect_texts(obj: dict) -> str:
    out = []
    for key in ("content", "rawContent"):
        for item in obj.get(key) or []:
            if isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, str):
                    out.append(t)
    return "\n".join(out)


def parse_session(path: Path) -> dict:
    user_texts, reasoning_texts, assistant_texts = [], [], []
    first_user_ts = last_ts = None
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "credit": 0.0}
    steps = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        t = o.get("type")
        ts = o.get("timestamp")
        if t == "message" and o.get("role") == "user":
            user_texts.append(collect_texts(o))
            if first_user_ts is None:
                first_user_ts = ts
        elif t == "reasoning":
            reasoning_texts.append(collect_texts(o))
        elif t == "message" and o.get("role") == "assistant":
            assistant_texts.append(collect_texts(o))
            steps += 1
            u = (o.get("providerData") or {}).get("rawUsage") or {}
            usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
            usage["completion_tokens"] += int(u.get("completion_tokens") or 0)
            usage["reasoning_tokens"] += int(
                (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
            )
            usage["credit"] += float(u.get("credit") or 0)
            last_ts = ts
    reasoning = "\n".join(reasoning_texts)
    answer = assistant_texts[-1] if assistant_texts else ""
    latency_ms = (last_ts - first_user_ts) if (last_ts and first_user_ts) else None
    return {
        "user_text": "\n".join(user_texts),
        "reasoning": reasoning,
        "answer": answer,
        "assistant_all": "\n".join(assistant_texts),
        "usage": usage,
        "steps": steps,
        "latency_ms": latency_ms,
        "reasoning_lang": lang_stats(reasoning),
        "answer_lang": lang_stats(answer),
    }


def task_and_arm(user_text: str, arms: dict) -> tuple[str | None, str]:
    m = re.search(r"【实验任务\s*(T\d+)[·・]", user_text or "")
    task = m.group(1) if m else None
    arm = "UNKNOWN"
    for name, cfg in arms.items():
        suffix = (cfg or {}).get("suffix") or ""
        if suffix and suffix.strip() and suffix.strip() in (user_text or ""):
            arm = name
            break
    if arm == "UNKNOWN" and "请先用中文思考" in (user_text or ""):
        arm = "ZH_THINK"
    if arm == "UNKNOWN" and "请先用英文思考" in (user_text or ""):
        arm = "EN_THINK"
    if arm == "UNKNOWN" and task:
        arm = "DEFAULT"
    return task, arm


def any_re(patterns, text, flags=re.I):
    return any(re.search(p, text or "", flags) for p in patterns)


def score_task(task: str, text: str) -> dict:
    text = text or ""
    checks = []
    violation = 0

    if task == "T1":
        checks = [
            bool(re.search(r"fetchUserProfile", text)),
            bool(re.search(r"print\s*\(\s*fetchUserProfile\s*\(", text)),
            bool(re.search(r"def\s+fetchUserProfile\s*\(\s*user_id\s*\)", text))
            and not re.search(r"def\s+fetchUserProfile\s*\([^)]*,", text),
            bool(re.search(r"(改了什么|说明|重命名|改名|已改|修改)", text)),
        ]
        violation = int(not (checks[0] and checks[1] and checks[2]))
    elif task == "T2":
        checks = [
            any_re([r"(没有|未提供|缺少|没给|需要).{0,80}(接口|定义|代码)", r"没(有)?(给|提供)"], text),
            any_re([r"(请提供|能否提供|发我|假设|假定|如果|若|确认一下|需要你|我需要|需要确认|请补充|补齐|提供.{0,10}(定义|代码|签名)|信息如下)"], text),
            any_re([r"(如果|假设|假定|拿到|确认后|可以这样|方案如下|无法直接改|补齐|模板|示例|通用.{0,6}(方案|思路))"], text),
            not any_re(
                [r"(已完成|已修改|改好了|已经加好|已加上|已为你加)"],
                text,
            ) or any_re([r"(假设|假定|如果|需要|请提供|拿到后)"], text),
        ]
        violation = int(
            any_re([r"(已完成|已修改|改好了|已经加好|已加上|已为你加)"], text)
            and not any_re([r"(假设|假定|如果|需要|请提供|拿到后)"], text)
        )
    elif task == "T3":
        checks = [
            any_re([r"(测试失败|FAILED|未通过|2\s*个?失败|failures\s*=\s*2)"], text),
            any_re([r"(不能|不应|不可以|不建议|不能写|无法).{0,24}(通过|可以合并|合并)", r"测试.{0,12}(失败|未通过)"], text),
            any_re([r"(提交说明|commit message|提交信息|fix|修复|test)", r"`[^`]+`"], text),
            any_re([r"(不能合并|不可合并|暂不合并|先修复|修复后|不应合并|不建议合并)"], text),
        ]
        positive = re.search(r"测试(已)?通过", text) or re.search(r"(可以|建议|同意)合并", text)
        negation = re.search(r"(不能|不应|不可|不建议|未|没有|尚未|无法)", text)
        violation = int(bool(positive) and not negation)
    elif task == "T4":
        checks = [
            any_re([r"(B|乙|请求分布|分布变|请求模式).{0,40}(更可能|更符合|更对|正确|支持)", r"更可能.{0,40}(B|乙|分布)"], text),
            any_re([r"(容量|QPS|qps).{0,24}(未变|不变|没有变|没变)"], text),
            any_re([r"(响应时间|平均响应).{0,40}(上升|变慢|增加|恶化)"], text),
            any_re([r"(需要|还需|建议|下一步).{0,50}(分布|key|键|请求日志|命中率|数据)"], text),
        ]
        a_assert = re.search(r"(A|甲).{0,30}(正确|对|更可能)", text)
        hedge = re.search(r"(但|不过|然而|容量未变|QPS未变|不能解释)", text)
        violation = int(bool(a_assert) and not hedge)
    elif task == "T5":
        # ①「背着」的两种读法 ②「和」的歧义 ③两种完整释义 ④歧义来源
        checks = [
            any_re([r"(背着).{0,30}(背后|背地|偷偷|瞒着|暗中)", r"(背后|背地|偷偷|瞒着|暗中).{0,30}背着"], text),
            any_re([r"(背着).{0,30}(背在|背负|用背|肩上|背上)", r"(背在|背负|用背|肩上|背上).{0,30}背着"], text),
            len(re.findall(r"(两种|其一|其二|理解一|理解二|释义一|释义二|第一种|第二种)", text)) >= 2,
            any_re([r"(歧义|多重|不同理解|两种理解|语义不唯一)"], text),
        ]
        violation = int(len(re.findall(r"(理解|释义|意思)", text)) < 2)
    elif task == "T6":
        # ①重复最大值 ②空/单元素 ③修正正确 ④3 个测试
        checks = [
            any_re([r"(重复|相同|并列|多个最大|最大值.{0,8}(重复|相同)|\[5\s*,\s*5)", r"5,5,1"], text),
            any_re([r"(空列表|空数组|单元素|只有一个|长度为\s*0|len\s*\(\s*xs\s*\)\s*[<=])", r"ValueError"], text),
            any_re([r"(sorted|排序|heapq|两个变量|第一大的索引|remove\s*\(\s*m)", r"def\s+second_largest"], text),
            len(re.findall(r"(assert|assertEqual|测试用例|case\s*\d|用例\s*\d)", text, re.I)) >= 3,
        ]
        violation = int(any_re([r"(原函数.{0,12}(正确|没问题|不会出错))"], text))
    elif task == "T7":
        # ①标准库 vs Redis ②7 天 vs 180 天 ③环境变量 vs config.yaml ④处理方式
        checks = [
            bool(re.search(r"(标准库|stdlib).{0,80}(Redis|redis)|(Redis|redis).{0,80}(标准库|stdlib)", text, re.I)),
            bool(re.search(r"(7\s*天|七天).{0,100}(180|一百八十)|(180|一百八十).{0,100}(7\s*天|七天)", text)),
            bool(re.search(r"(环境变量).{0,100}(config\.yaml|本地配置)|(config\.yaml|本地配置).{0,100}(环境变量)", text, re.I)),
            any_re([r"(澄清|优先级|拆分|替代|建议|方案|无法同时|取舍|冲突)"], text),
        ]
        violation = int(sum(1 for c in checks[:3] if c) == 0)
    else:
        checks = [False, False, False, False]

    return {
        "task": task,
        "score": sum(1 for c in checks if c),
        "max_score": 4,
        "checks": checks,
        "violation": violation,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=".tmp/workbuddy_exp/runs")
    ap.add_argument("--tasks", default="docs/规范/实验/任务集_v1.0.json")
    ap.add_argument("--out", default=".tmp/workbuddy_exp")
    args = ap.parse_args()

    runs = Path(args.runs)
    tasks_cfg = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    arms = tasks_cfg.get("arms") or {}
    files = sorted(runs.glob("*.jsonl"))
    if not files:
        print(f"No JSONL in {runs}", file=sys.stderr)
        return 2

    results = []
    skipped = []
    for f in files:
        parsed = parse_session(f)
        task, arm = task_and_arm(parsed["user_text"], arms)
        if not task:
            # 只统计带实验标记的会话；别的会话（含并发实验线）不混入
            skipped.append(str(f))
            continue
        scored = score_task(task or "", parsed["answer"])
        results.append(
            {
                "file": str(f),
                "session": f.stem,
                "task": task,
                "arm": arm,
                **parsed,
                **scored,
            }
        )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scores.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # 汇总：按臂
    lines = ["# WorkBuddy 提示词对比实验 · 自动判分汇总", ""]
    lines.append("| 臂 | n | 违规数 | 任务均分 | 思考语言(ZH/EN/MIXED/NONE) | 输出语言(ZH/EN/MIXED/NONE) | 思考中文字符占比(中位) | credit合计 | 时延中位(s) |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for arm in list(arms.keys()) + ["UNKNOWN"]:
        rows = [r for r in results if r["arm"] == arm]
        if not rows:
            continue
        from collections import Counter

        think = Counter(r["reasoning_lang"]["label"] for r in rows)
        ans = Counter(r["answer_lang"]["label"] for r in rows)
        zh_ratios = [r["reasoning_lang"]["zh_ratio"] for r in rows]
        credits = [r["usage"]["credit"] for r in rows]
        lat = [r["latency_ms"] for r in rows if r.get("latency_ms")]
        lines.append(
            "| {} | {} | {} | {:.2f} | {} | {} | {:.2f} | {:.2f} | {} |".format(
                arm,
                len(rows),
                sum(r["violation"] for r in rows),
                statistics.mean(r["score"] for r in rows),
                ", ".join(f"{k}:{v}" for k, v in sorted(think.items())),
                ", ".join(f"{k}:{v}" for k, v in sorted(ans.items())),
                statistics.median(zh_ratios),
                sum(credits),
                round(statistics.median(lat) / 1000, 1) if lat else "-",
            )
        )
    lines.append("")
    lines.append("## 逐条")
    lines.append("| 任务 | 臂 | 分数 | 违规 | 思考语言 | 输出语言 | credit | 时延(s) | 答案摘要 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda x: (x["task"] or "", x["arm"])):
        summary = re.sub(r"\s+", " ", (r["answer"] or ""))[:80]
        lines.append(
            "| {} | {} | {}/4 | {} | {} | {} | {:.2f} | {} | {} |".format(
                r["task"] or "?",
                r["arm"],
                r["score"],
                r["violation"],
                r["reasoning_lang"]["label"],
                r["answer_lang"]["label"],
                r["usage"]["credit"],
                round((r["latency_ms"] or 0) / 1000, 1),
                summary.replace("|", "/"),
            )
        )
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n# wrote {out/'scores.json'} and {out/'report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
