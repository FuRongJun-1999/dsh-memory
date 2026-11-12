# -*- coding: utf-8 -*-
"""D_out 测量器（工作纪律第 19 条 / issue #663 之二）。

D_out 衡量「对外解释」与「体系自述」之间的偏差：
读入 N 份受试者复述（人或模型，分档记录），与体系自述逐项比对，
输出四档分布（一致 / 部分 / 错位 / 空白），D_out = 1 - 一致率，并分列错位率与空白率。

不做：说服率 / 好感度 / 传播效果预测。

用法：
  python scripts/d_out.py --responses <复述.json> --self <自述.json> --out <读数.json>
  python scripts/d_out.py --proxy --echo <echo页> --source <真源> --out <读数.json>
  python scripts/d_out.py --report <读数.json>

输入约定（真实测量）：
  复述.json  {"anchors": {"理论","架构","本投影"}, "subjects": [
      {"id": "s1", "model": "gpt-x", "items": [{"qid": "q1", "restates": ["..."]}]}]}
  自述.json  {"items": [{"qid": "q1", "claims": ["..."]}]}

比对口径（诚实声明）：只用**词面覆盖**判定一致/部分/错位/空白；
语义级错位（说反了）无法机械判别，故输出里保留 judge 覆盖位（受试项可带 verdict 字段人工裁定）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time

CN_RE = re.compile(r"[\u4e00-\u9fff]")
WORD_RE = re.compile(r"[A-Za-z0-9_]+")


def tokens(text):
    """中英混排的粗粒度词项：中文二元组 + 英文/数字词。"""
    s = str(text or "")
    zh = "".join(CN_RE.findall(s))
    bigrams = {zh[i:i + 2] for i in range(len(zh) - 1)} if len(zh) > 1 else set()
    words = {w.lower() for w in WORD_RE.findall(s) if len(w) > 1}
    return bigrams | words


def bucket(claims, restates, verdict=None):
    """单条判定：一致 / 部分 / 错位 / 空白（verdict 可人工覆盖）。"""
    if verdict in ("一致", "部分", "错位", "空白"):
        return verdict
    want = set()
    for c in claims:
        want |= tokens(c)
    if not want:
        return "空白"
    got = set()
    for r in restates:
        got |= tokens(r)
    if not got:
        return "空白"
    hit = len(want & got) / float(len(want))
    if hit >= 0.8:
        return "一致"
    if hit >= 0.4:
        return "部分"
    return "错位"


def measure(resp, selfd):
    by_q = {it["qid"]: it.get("claims") or [] for it in selfd.get("items") or []}
    rows = []
    counts = {"一致": 0, "部分": 0, "错位": 0, "空白": 0}
    for subj in resp.get("subjects") or []:
        for it in subj.get("items") or []:
            qid = it.get("qid")
            claims = by_q.get(qid)
            if claims is None:
                rows.append({"subject": subj.get("id"), "qid": qid, "bucket": "空白",
                             "note": "自述里没有这个 qid"})
                counts["空白"] += 1
                continue
            b = bucket(claims, it.get("restates") or [], it.get("verdict"))
            counts[b] += 1
            rows.append({"subject": subj.get("id"), "model": subj.get("model"),
                         "qid": qid, "bucket": b})
    total = sum(counts.values()) or 1
    rates = {k: round(v / float(total), 4) for k, v in counts.items()}
    return {
        "counts": counts,
        "rates": rates,
        "D_out": round(1.0 - rates["一致"], 4),
        "misplaced_rate": rates["错位"],
        "blank_rate": rates["空白"],
        "rows": rows,
        "subjects": len(resp.get("subjects") or []),
        "items": total,
    }


def proxy(echo_text, source_text):
    """代理基线：检验「一页解释里点名的可指认项」是否都能在真源里找到。

    口径：抽出 echo 页里的**可指认项**（文件/脚本/配置/判据 id/百分比读数），
    逐项在真源里查找。全在 → 一致；过半 → 部分；有过半缺 → 错位；一个都没有 → 空白。
    这不是人/模型受试，读数**不可当 D_out 对外引用**，只作为「解释有没有凭空编」的起点读数。
    """
    # 只查「材料类可指认项」（文件 / 脚本 / 配置）。判据名（check_*/gate_*）与版本号
    # 是外部判据与锚，本就不该在真源文档里出现；混进来会把基线做成噪声。
    item_re = re.compile(r"[A-Za-z0-9_./\-]+\.(?:py|json|md|ps1|js|yml|yaml|ts)")
    echo_body = "\n".join(ln for ln in echo_text.splitlines()
                          if not ln.strip().startswith("版本锚"))
    items = []
    for m in item_re.finditer(echo_body):
        tok = m.group(0).strip()
        if tok and tok not in items:
            items.append(tok)
    src = source_text.replace("\\", "/")
    if not items:
        b = "空白"
        found, miss = [], []
    else:
        found = [t for t in items if t.replace("\\", "/") in src or t in source_text]
        miss = [t for t in items if t not in found]
        ratio = len(found) / float(len(items))
        b = "一致" if ratio >= 0.99 else ("部分" if ratio >= 0.5 else "错位")
    counts = {"一致": 0, "部分": 0, "错位": 0, "空白": 0}
    counts[b] = 1
    return {
        "counts": counts, "rates": {k: float(v) for k, v in counts.items()},
        "D_out": {"一致": 0.0, "部分": 0.5, "错位": 1.0, "空白": 1.0}[b],
        "misplaced_rate": float(counts["错位"]), "blank_rate": float(counts["空白"]),
        "rows": [{"subject": "proxy:echo-items-vs-source", "qid": "all",
                  "bucket": b, "items": items, "unsupported": miss}],
        "subjects": 0, "items": len(items) or 1,
        "proxy": True,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="D_out 测量器（第 19 条）")
    ap.add_argument("--responses")
    ap.add_argument("--self", dest="selfd")
    ap.add_argument("--proxy", action="store_true", help="代理基线（echo 页 vs 真源），不可对外引用")
    ap.add_argument("--echo")
    ap.add_argument("--source")
    ap.add_argument("--out")
    ap.add_argument("--report")
    args = ap.parse_args(argv)

    if args.report:
        d = json.load(io.open(args.report, encoding="utf-8"))
        print("D_out=%s | 一致 %s | 部分 %s | 错位 %s | 空白 %s | 受试者 %s | 项 %s"
              % (d.get("D_out"), d.get("rates", {}).get("一致"),
                 d.get("rates", {}).get("部分"), d.get("misplaced_rate"),
                 d.get("blank_rate"), d.get("subjects"), d.get("items")))
        if d.get("proxy"):
            print("注：这是 proxy 基线（echo 页 vs 真源），不是受试者 D_out，不可对外引用")
        return 0

    if args.proxy:
        for k in ("echo", "source"):
            if not getattr(args, k):
                print("--proxy 需要 --echo 与 --source", file=sys.stderr)
                return 2
        res = proxy(io.open(args.echo, encoding="utf-8").read(),
                    io.open(args.source, encoding="utf-8").read())
        anchors = {"理论": "unknown", "架构": "unknown", "本投影": "unknown"}
        m = re.search(r"版本锚\s*[:：]\s*理论\s*=\s*(\S+)\s*[,，]\s*架构\s*=\s*(\S+)\s*[,，]\s*本投影\s*=\s*(\S+)",
                      io.open(args.echo, encoding="utf-8").read())
        if m:
            anchors = {"理论": m.group(1), "架构": m.group(2), "本投影": m.group(3)}
        res.update({"anchors": anchors, "material": {"echo": args.echo, "source": args.source},
                    "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    else:
        if not (args.responses and args.selfd):
            ap.print_help()
            return 2
        resp = json.load(io.open(args.responses, encoding="utf-8"))
        selfd = json.load(io.open(args.selfd, encoding="utf-8"))
        res = measure(resp, selfd)
        res.update({"anchors": resp.get("anchors") or {},
                    "material": {"responses": args.responses, "self": args.selfd},
                    "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        res["proxy"] = False

    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        if d:
            os.makedirs(d, exist_ok=True)
        io.open(args.out, "w", encoding="utf-8", newline="").write(
            json.dumps(res, ensure_ascii=False, indent=1) + "\n")
        print("读数已写入: " + args.out)
    print("D_out=%s | 一致 %s | 部分 %s | 错位 %s | 空白 %s"
          % (res["D_out"], res["rates"].get("一致"), res["rates"].get("部分"),
             res["misplaced_rate"], res["blank_rate"]))
    if res.get("proxy"):
        print("注：proxy 基线，不可对外引用（需 >=3 份外部受试者复述才是真 D_out）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
