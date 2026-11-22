# -*- coding: utf-8 -*-
"""LongMemEval-S cleaned JSON -> 仓库评测台格式（eval_common 认的两个 jsonl）。

输入：longmemeval_s_cleaned.json（xiaowu0162/longmemeval-cleaned，官方 cleaned 版）
输出：data/external/longmemeval/lme_s_questions.jsonl / lme_s_haystack.jsonl

为什么需要它：仓库里 bench_longmem / bench_zh_mad / eval_common 都直接读这两个
jsonl，但转换器此前不在仓库内（只有消费端）——本脚本把「原始 json → 评测格式」
这一步固化成可重放的最小实现。

口径（与 issue #999 引用的官方 retrieval 口径对齐）：
  * 只索引 **user** turn（assistant turn 不作为候选）；
  * GT = 同一 session 内 has_answer 为真的 user turn（官方 run_retrieval 也按 id 派生）；
  * 跳过 `_abs` 题与无 GT 题；
  * qtype 保留原 question_type 字段原值。

跑法：
    python -X utf8 scripts/gen_longmemeval_eval_data.py \
        --src D:/program/AEIS/data/external/longmemeval_s_cleaned.json
"""
import argparse
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "data", "external", "longmemeval")


clean_re = None


def tid_of(sid, ti):
    """session id + turn 序号 -> 合法 node_id。

    node_id 会拼进落盘路径，仓库只认 ^[A-Za-z0-9_.@\u4e00-\u9fff,-]{1,128}$（且不含 '..'），
    所以非法字符一律折成 '-'，再截到 120 字符留出 '_t<序号>' 的余量。
    """
    global clean_re
    if clean_re is None:
        import re
        clean_re = re.compile(r"[^0-9A-Za-z_.@,\u4e00-\u9fff-]")
    base = clean_re.sub("-", str(sid))[:120]
    return "%s_t%d" % (base, ti)


def turn_text(t):
    """turn -> 入库文本（日期/说话人内联，供词法路召回）。"""
    return t.get("content") or ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--limit", type=int, default=0, help="只转前 N 题（0=全部，调试用）")
    args = ap.parse_args()

    with io.open(args.src, encoding="utf-8") as f:
        data = json.load(f)
    print("原始题数：%d" % len(data))
    if args.limit:
        data = data[: args.limit]

    os.makedirs(args.out, exist_ok=True)
    corpus = {}      # turn_id -> row
    questions = []
    skipped_abs = skipped_nogt = 0
    for item in data:
        qid = item.get("question_id") or ""
        if str(qid).endswith("_abs"):
            skipped_abs += 1
            continue
        sess_ids = item.get("haystack_session_ids") or []
        sessions = item.get("haystack_sessions") or []
        dates = item.get("haystack_dates") or []
        ans_sess = set(item.get("answer_session_ids") or [])
        evidence = []
        for si, sess in enumerate(sessions):
            sid = sess_ids[si] if si < len(sess_ids) else "s%d" % si
            date = dates[si] if si < len(dates) else ""
            for ti, t in enumerate(sess or []):
                if (t.get("role") or "") != "user":
                    continue
                tid = tid_of(sid, ti)
                if tid not in corpus:
                    corpus[tid] = {"id": tid, "text": turn_text(t), "session": sid,
                                   "date": date, "qtype_hint": item.get("question_type")}
                if sid in ans_sess and t.get("has_answer"):
                    evidence.append(tid)
        if not evidence:
            skipped_nogt += 1
            continue
        questions.append({"qid": qid, "qtype": item.get("question_type"),
                          "question": item.get("question"), "answer": item.get("answer"),
                          "evidence_turns": evidence,
                          "haystack_sessions": [sess_ids[i] if i < len(sess_ids) else "" 
                                                  for i in range(len(sessions))]})

    qp = os.path.join(args.out, "lme_s_questions.jsonl")
    hp = os.path.join(args.out, "lme_s_haystack.jsonl")
    with io.open(qp, "w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    with io.open(hp, "w", encoding="utf-8") as f:
        for row in corpus.values():
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("题 %d（跳过 _abs %d / 无 GT %d）｜语料 user turn %d"
          % (len(questions), skipped_abs, skipped_nogt, len(corpus)))
    print("写出：%s / %s" % (qp, hp))
    return 0


if __name__ == "__main__":
    sys.exit(main())