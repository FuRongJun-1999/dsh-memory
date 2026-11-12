# -*- coding: utf-8 -*-
"""派发留痕对账——蜂巢 job（spec/status/result）与认知图卡片按 derived_from 对账。

# 功能名：派发留痕对账（灵枢协作架构 v0.1 · P0 接线第 3 项）
# 生效条件：凡要核对「派发出去的每个 job 是否留有可反查的认知图卡片」时；凡要排查断链/悬空/产物缺失时；
#           凡工作纪律第 17 条「派发留痕」需要机器判据时。触发语=派发留痕、对账、断链、悬空、derived_from。
# 子功能：①扫 job 终态与产物完整性 ②扫卡片 derived_from 与内容提及（两者严格分开）
#         ③三分类对账（正式链接 / 仅提及 / 断链）+ 悬空卡 + 产物缺失 ④verify_link 反查（能红判据）
# 执行：scan_jobs → scan_cards → reconcile → 报表或 --json
# 验证方式：hive/test_reconcile.py（8 断言 + 5 定点变异；--mutate 出反面证明）
# 不适用条件：不适用于把「内容提及」当正式溯源（两者必须分开计，混则判据失效）；
#             不适用于把非终态 job 判为断链（未完成不是留痕缺失）；
#             不适用于未传 --brain 时声称脑库侧已核对（此时脑库侧为「未核对」，不是「通过」）。
"""

import argparse
import io
import json
import os
import re
import sys

TERMINAL = ("done", "error", "timeout", "killed")
JOB_ID_RE = re.compile(r"^h(?:\d{9,}_|_)")
TOKEN_RE = re.compile(r"h[0-9A-Za-z_\u4e00-\u9fff]{4,}")


def read_text(path):
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def load_json(path):
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except Exception:
        return None


def parse_fm_list(text, key):
    """取 frontmatter 里 key 的列表值。支持 inline [a, b] 与 YAML 块列表两种写法。"""
    # 注意：此处必须用 [ \t]* 而非 \s* —— \s 含换行，会跨行吞掉块列表的换行与缩进，
    # 使 (.*) 抓到「- item」而误走 inline 分支（返回带 "- " 前缀的假值）。
    m = re.search(r"^" + re.escape(key) + r":[ \t]*(.*)$", text, re.M)
    if not m:
        return []
    inline = m.group(1).strip()
    if inline.startswith("["):
        body = inline[1:].split("]")[0]
        return [x.strip().strip("\"'") for x in body.split(",") if x.strip()]
    if inline and inline not in ("null", "~", "[]"):
        return [inline.strip("\"'")]
    out = []
    for line in text[m.end():].splitlines():
        if re.match(r"^\s+-\s+", line):
            out.append(re.sub(r"^\s+-\s+", "", line).strip().strip("\"'"))
        elif line.strip():
            break
    return out


def scan_jobs(jobs_dir):
    """扫 job 目录：终态与产物完整性。"""
    out = []
    if not jobs_dir or not os.path.isdir(jobs_dir):
        return out
    for name in sorted(os.listdir(jobs_dir)):
        d = os.path.join(jobs_dir, name)
        if not os.path.isdir(d):
            continue
        st = load_json(os.path.join(d, "status.json")) or {}
        status = str(st.get("status") or st.get("state") or "").strip() or "unknown"
        res = os.path.join(d, "result.json")
        out.append({
            "job_id": name,
            "status": status,
            "terminal": status in TERMINAL,
            "has_spec": os.path.isfile(os.path.join(d, "spec.json")),
            "has_result": os.path.isfile(res),
            "result_path": res if os.path.isfile(res) else None,
        })
    return out


def scan_cards(brain_root, job_ids):
    """扫脑库卡片：取 derived_from 声明 + 内容里出现的 job_id 令牌。严格分开两件事。"""
    cards = []
    if not brain_root or not os.path.isdir(brain_root):
        return cards
    for dp, _dn, fn in os.walk(brain_root):
        for f in fn:
            if not f.endswith(".md"):
                continue
            p = os.path.join(dp, f)
            text = read_text(p)
            if not text:
                continue
            declared = parse_fm_list(text, "derived_from")
            tokens = set(TOKEN_RE.findall(text))
            cards.append({
                "node_id": f[:-3],
                "path": os.path.relpath(p, brain_root).replace(os.sep, "/"),
                "declared": declared,
                "mentions": sorted(tokens & job_ids),
            })
    return cards


def reconcile(jobs_dir, brain_root):
    """三分类对账。linked=正式溯源；mention_only=仅内容提及（弱链）；unlinked=终态无痕（断链）。"""
    jobs = scan_jobs(jobs_dir)
    job_ids = set(j["job_id"] for j in jobs)
    brain_scanned = bool(brain_root) and os.path.isdir(brain_root)
    cards = scan_cards(brain_root, job_ids) if brain_scanned else []

    linked, mention_only, dangling = {}, {}, []
    for c in cards:
        for jid in c["declared"]:
            if jid in job_ids:
                linked.setdefault(jid, []).append(c["path"])
            elif JOB_ID_RE.match(jid):
                dangling.append({"job_id": jid, "card": c["path"]})
        for jid in c["mentions"]:
            if jid not in c["declared"]:
                mention_only.setdefault(jid, []).append(c["path"])

    unlinked = [j["job_id"] for j in jobs
                if j["terminal"] and j["job_id"] not in linked]
    incomplete = [j["job_id"] for j in jobs if j["terminal"] and not j["has_result"]]
    dangling.sort(key=lambda r: (r["job_id"], r["card"]))
    return {
        "ok": True,
        "brain_scanned": brain_scanned,
        "brain_root": brain_root or None,
        "counts": {
            "jobs": len(jobs),
            "terminal": sum(1 for j in jobs if j["terminal"]),
            "cards": len(cards),
            "linked": len(linked),
            "mention_only": len(mention_only),
            "unlinked": len(unlinked),
            "dangling": len(dangling),
            "incomplete": len(incomplete),
        },
        "linked": sorted(linked),
        "mention_only": sorted(mention_only),
        "unlinked": unlinked,
        "dangling": dangling,
        "incomplete": incomplete,
        "jobs": jobs,
    }


def verify_link(jobs_dir, brain_root, job_id):
    """能红判据：抽一条 job → 其卡片必须能反查到 result.json 与 job_id。查不到即断链。"""
    jobs = {j["job_id"]: j for j in scan_jobs(jobs_dir)}
    job = jobs.get(job_id)
    if job is None:
        return {"ok": False, "job_id": job_id, "reason": "job_not_found"}
    rep = reconcile(jobs_dir, brain_root)
    cards = []
    if rep["brain_scanned"]:
        for c in scan_cards(brain_root, {job_id}):
            if job_id in c["declared"]:
                cards.append(c["path"])
    ok = bool(cards) and job["has_result"]
    return {
        "ok": ok,
        "job_id": job_id,
        "status": job["status"],
        "result_path": job["result_path"],
        "cards": cards,
        "reason": None if ok else ("no_card_declares_it" if not cards else "result_json_missing"),
    }


def render(rep, limit=10):
    c = rep["counts"]
    L = []
    L.append("派发留痕对账")
    L.append("  脑库侧: %s" % ("已核对 %s" % rep["brain_root"] if rep["brain_scanned"]
                              else "未核对（未传 --brain）"))
    L.append("  job 共 %d（终态 %d）· 卡片 %d" % (c["jobs"], c["terminal"], c["cards"]))
    L.append("  正式链接 %d · 仅提及 %d · 断链 %d · 悬空 %d · 产物缺失 %d"
             % (c["linked"], c["mention_only"], c["unlinked"], c["dangling"], c["incomplete"]))
    if not rep["brain_scanned"]:
        L.append("  注：脑库侧未核对 ⇒ 断链/悬空/仅提及三项不成立（不是「通过」）")
        return "\n".join(L)
    if rep["unlinked"]:
        L.append("  断链（终态 job 无卡片声明）前 %d 条:" % min(limit, len(rep["unlinked"])))
        for j in rep["unlinked"][:limit]:
            L.append("    - %s" % j)
    if rep["dangling"]:
        L.append("  悬空（卡片声明了不存在的 job）前 %d 条:" % min(limit, len(rep["dangling"])))
        for r in rep["dangling"][:limit]:
            L.append("    - %s <- %s" % (r["job_id"], r["card"]))
    if rep["incomplete"]:
        L.append("  产物缺失（终态无 result.json）:")
        for j in rep["incomplete"][:limit]:
            L.append("    - %s" % j)
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="派发留痕对账（蜂巢 job <-> 认知图卡片）")
    ap.add_argument("--jobs", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs"))
    ap.add_argument("--brain", default=os.environ.get("MDCG_ROOT", ""))
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--verify", default="", help="抽一条 job_id 反查（能红判据）")
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args(argv)
    if a.verify:
        r = verify_link(a.jobs, a.brain, a.verify)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["ok"] else 1
    rep = reconcile(a.jobs, a.brain)
    print(render(rep, a.limit))
    if a.json_out:
        with io.open(a.json_out, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
        print("  JSON -> %s" % a.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
