# -*- coding: utf-8 -*-
"""按会话打「用途:」标签（LLM 判定，标签可改，原文不动）。

使用者方案（2026-11-14）：用 LLM 读一个会话的记忆内容，判它属于哪个用途，打标签；
标签本身可改（重跑即覆盖旧用途标签），节点正文永不改写。

判据来源：md_cg/identity_names.py 的 UNIT_PURPOSE 值域（闭集）；
判不出 ⇒ 不写标签（未登记），绝不猜。

用法：
  python -X utf8 scripts/tag_purpose_llm.py --root <库根> [--limit 20] [--write]
  缺省 dry-run（只打印判定，不写库）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGOS                     # noqa: E402
from md_cg.identity_names import UNIT_PURPOSE, purpose_of  # noqa: E402
from md_cg.bench_e2e_judge import llm_chat         # noqa: E402

ALLOWED = sorted(set(UNIT_PURPOSE.values()) | {"做实验"})
PURPOSE_PREFIX = "用途:"
EXCERPT_CHARS = 600
# 思考/输出预算统一为 200000（使用者 2026-11-14 定：与蜂巢默认口径一致）
LLM_MAX_TOKENS = 200000


def first_user_message(sid, root=None, limit_bytes=1_500_000):
    """从会话日志取首条用户消息（早停：最多解压 limit_bytes）。取不到返回空串。"""
    if not root:
        root = __import__("os").environ.get("DSH_HOME", "") or __import__("os").path.expanduser("~/dsh-home" + "/sessions")
    try:
        import glob
        import json as _json
        import zstandard
    except Exception:
        return ""
    pats = glob.glob(os.path.join(root, "*", sid, "session.v4.jsonl.zstd"))
    if not pats:
        return ""
    try:
        with open(pats[0], "rb") as fh:
            reader = zstandard.ZstdDecompressor().stream_reader(fh)
            buf = b""
            while len(buf) < limit_bytes:
                chunk = reader.read(1 << 20)
                if not chunk:
                    break
                buf += chunk
    except Exception:
        return ""
    for line in buf.decode("utf-8", "replace").splitlines():
        if '"user/message"' not in line:
            continue
        try:
            rec = _json.loads(line)
        except Exception:
            continue
        data = rec.get("data") or {}
        if (data.get("source") or {}).get("kind") != "user":
            continue
        blocks = data.get("content") or []
        txt = " ".join(str(b.get("text") or "") for b in blocks if isinstance(b, dict)).strip()
        if txt:
            return txt[:300]
    return ""


def session_samples(cg, limit_sessions):
    """按会话聚合节点摘要：{session: [preview, ...]}（只取有正文的前几条）。"""
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    groups = {}
    for nid, rec in nodes.items():
        sid = str((rec or {}).get("session") or "").strip()
        if not sid or sid in ("unattributed",) or sid.startswith("sess_"):
            continue
        groups.setdefault(sid, []).append(nid)
    out = []
    for sid, nids in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:limit_sessions]:
        body = []
        for nid in nids[:6]:
            n = cg.get(nid) or {}
            txt = str(n.get("content") or "").strip().replace("\n", " ")
            if txt:
                body.append(txt[:EXCERPT_CHARS // 6])
            if sum(len(x) for x in body) >= EXCERPT_CHARS:
                break
        if body:
            out.append((sid, " ".join(body)[:EXCERPT_CHARS]))
    return out


def build_prompt(sid, excerpt, first_msg=""):
    return [
        {"role": "system", "content":
         "你是记忆整理员。读一个会话的节选，判断这个会话主要在做什么。"
         "每个会话都有用途（既然开这个会话来干活），必须选一个，只回该值本身，不要解释。"
         "允许写成 大类/小类 更精确，例如 修缺陷/依赖升级、做设计/文档。"
         "斜杠前的大类必须取自下列闭集。大类：" + " / ".join(ALLOWED)},
        {"role": "user", "content": ("会话标识：" + sid
                                     + ("\n用户首条消息：" + first_msg if first_msg else "")
                                     + "\n记忆节选：" + excerpt)},
    ]


def judge(cfg, sid, excerpt):
    msgs = build_prompt(sid, excerpt, first_user_message(sid))
    res = llm_chat(cfg["model"], cfg["base"], cfg["key"], msgs,
                   max_tokens=LLM_MAX_TOKENS,
                   timeout=int(os.environ.get("PURPOSE_TIMEOUT", "60")),
                   extra_payload={"thinking": {"type": "disabled"}})
    content = res[0] if isinstance(res, (tuple, list)) and res else res
    val = str(content or "").strip()
    for ch in "。．.，,；;：:！!？?":
        val = val.strip(ch)
    head = val.split("/")[0].strip()
    for a in ALLOWED:
        if head == a or head.startswith(a):
            tail = val[len(head):].strip().lstrip("/").strip()
            tail = "".join(ch for ch in tail if ch.isalnum())[:20]
            return (a + "/" + tail) if tail else a
    return ""
def apply_tag(cg, sid, purpose):
    # 方案B（使用者 2026-11-14）：大类当桶（分桶与排序），小类只作描述性检索线索；正文不改。
    # 落盘走**公开写口 add**（与其它写路径同一把锁与同一套闸），不碰私有 _write_node。
    parts = str(purpose or "").split("/", 1)
    big = parts[0].strip()
    sub = parts[1].strip() if len(parts) > 1 else ""
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    changed = 0
    for nid, rec in nodes.items():
        if str((rec or {}).get("session") or "") != sid:
            continue
        n = cg.get(nid) or {}
        fm = n.get("frontmatter") or {}
        tags = [str(t) for t in (fm.get("tags") or [])]
        new_tags = [t for t in tags if not (t.startswith("用途:") or t.startswith("说明:"))]
        if big:
            new_tags.append("用途:" + big)
        if sub:
            new_tags.append("说明:" + sub)
        if new_tags == tags:
            continue
        kw = {k: v for k, v in fm.items() if k not in ("layer", "tags")}
        try:
            cg.add(nid, n.get("content") or "", layer=fm.get("layer") or "contextual",
                   tags=new_tags, override=True, **kw)
            changed += 1
        except Exception:
            continue
    return changed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--limit', type=int, default=20)
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--out', default='')
    ap.add_argument('--model', default=os.environ.get('PURPOSE_MODEL', 'deepseek-chat'))
    ap.add_argument('--base', default=os.environ.get('PURPOSE_BASE', 'https://api.deepseek.com'))
    args = ap.parse_args()

    key = os.environ.get('DEEPSEEK_API_KEY') or ''
    cg = MdCGOS(args.root, actor='dsh端')
    rows = session_samples(cg, args.limit)
    print('候选会话 %d 个（闭集：%s）' % (len(rows), ' / '.join(ALLOWED)))
    if not key:
        print('无 DEEPSEEK_API_KEY：只打印待判会话，不判定。')
        for sid, ex in rows[:10]:
            print('  %-46s 节选 %d 字' % (sid[:46], len(ex)))
        return 0

    cfg = {'model': args.model, 'base': args.base, 'key': key}
    from concurrent.futures import ThreadPoolExecutor

    def _one(row):
        sid, ex = row
        try:
            return sid, judge(cfg, sid, ex)
        except Exception as exc:
            return sid, '!error:%s' % type(exc).__name__

    rows_out = []
    stat = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for sid, pr in pool.map(_one, rows):
            rows_out.append({'session': sid, 'purpose': pr})
            k = pr or '（空）'
            stat[k] = stat.get(k, 0) + 1

    for k, v in sorted(stat.items(), key=lambda kv: -kv[1]):
        print('  %-24s %d' % (k, v))
    print('统计:', json.dumps(stat, ensure_ascii=False))
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            for r in rows_out:
                fh.write(json.dumps(r, ensure_ascii=False) + chr(10))
        print('明细已写:', args.out)
    if args.write:
        n_all = 0
        for r in rows_out:
            if r['purpose'] and not str(r['purpose']).startswith('!error'):
                n_all += apply_tag(cg, r['session'], r['purpose'])
        print('落库改动节点数:', n_all)
    return 0

if __name__ == "__main__":
    sys.exit(main())
