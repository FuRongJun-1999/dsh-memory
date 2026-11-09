# -*- coding: utf-8 -*-
"""rubric92 端到端 SUT：灵枢检索 → 断言判定 → 判分（含闭卷对照）。

题库口径（bench/mcq/reasoning/README.md）：
  · 92 题 × 6 断言 = 552 条「是/否」；
  · 官方开卷上界（只给所引章节）87.1%（φ=0.745），闭卷 50.0%（φ=0.000）；
  · 引用必须同时报闭卷 φ 与开卷材料口径；模型 deepseek-flash + temperature=0。

本脚本做三件事：
  prepare：灌语料（行窗切块 + 章号 tag）→ 逐断言检索 → 产出待判 payload
  （外部作答）→ picks.jsonl
  grade  ：平衡准确率 + φ（与闭卷对照同口径）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CCG = ('# 功能名：{n}\n# 生效条件：语料\n# 子功能：s\n# 执行：e\n'
       '# 验证方式：bench\n# 不适用条件：无\n\n{body}\n')
CN = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8,
      '九': 9, '十': 10}


def cn2int(s):
    s = (s or '').strip()
    if s.isdigit():
        return int(s)
    if s in CN:
        return CN[s]
    if len(s) == 2 and s[1] == '十':
        return CN.get(s[0], 0) * 10
    if len(s) == 2 and s[0] == '十':
        return 10 + CN.get(s[1], 0)
    if len(s) == 3 and s[1] == '十':
        return CN.get(s[0], 0) * 10 + CN.get(s[2], 0)
    return None


def line_chapters(lines):
    out = {}
    cur = None
    for i, ln in enumerate(lines, 1):
        # 语料里章节标题层级不一致（第18章是 `# `，其余是 `## `）——必须认 1-6 级
        m = re.match(r'^#{1,6}\s*第([一二三四五六七八九十\d]+)章', ln)
        if m:
            n = cn2int(m.group(1))
            if n:
                cur = n
        out[i] = cur
    return out


def chunks_of(bench, window=12):
    lines = open(os.path.join(bench, 'corpus', '语料.md'), encoding='utf-8').read().splitlines()
    ch = line_chapters(lines)
    out = []
    buf, start = [], None
    for i, ln in enumerate(lines, 1):
        if ln.startswith('#') and buf:
            out.append((start, i - 1, chr(10).join(buf), ch.get(start)))
            buf, start = [], None
        if start is None:
            start = i
        buf.append(ln)
        if len(buf) >= window:
            out.append((start, i, chr(10).join(buf), ch.get(start)))
            buf, start = [], None
    if buf:
        out.append((start, len(lines), chr(10).join(buf), ch.get(start)))
    return out




#: 投喂单元的目标体量（使用者口径：按「一万字一份」控制输入总量）。
PACK_CHARS = 10000


def chapters_text(bench):
    """按章聚合原文（章节 = 时间桶）：{章号: (标题, 全文)}。"""
    lines = open(os.path.join(bench, 'corpus', '语料.md'), encoding='utf-8').read().splitlines()
    cur, title, buf = None, '', []
    out = {}
    for ln in lines:
        m = re.match(r'^##\s*第([一二三四五六七八九十\d]+)章', ln)
        if m:
            if cur is not None and buf:
                out[cur] = (title, chr(10).join(buf))
            n = cn2int(m.group(1))
            cur, title, buf = n, ln.strip('# ').strip(), []
            continue
        if cur is not None:
            buf.append(ln)
    if cur is not None and buf:
        out[cur] = (title, chr(10).join(buf))
    return out




def pack_from_chapters(chap_text, chapters, budget=PACK_CHARS):
    """按时间桶装配：命中章优先（按票数），不足预算再向**相邻（前后）**章补齐。"""
    picked, used, seen = [], 0, set()
    def _take(ch):
        nonlocal used
        if ch in seen or ch not in chap_text or used >= budget:
            return
        title, body = chap_text[ch]
        take = body[:budget - used]
        picked.append({'chapter': ch, 'title': title, 'text': take})
        used += len(take)
        seen.add(ch)
    for ch in chapters:
        _take(ch)
    # 补齐：从命中章里最小的章号向两侧扩展（时间桶相邻）
    base = sorted(chapters)[0] if chapters else None
    step = 1
    while used < budget and base is not None and step <= max(chap_text):
        _take(base - step)
        _take(base + step)
        step += 1
    picked.sort(key=lambda c: c['chapter'])
    return picked


def pack_by_time(chap_text, primary, budget=PACK_CHARS):
    """按时间桶装配投喂单元：主章 + 不足 1 万字时向**更早的章**回溯补齐。

    使用者口径（2026-11-09）：按一万字一份控制输入总量；不足一万字就调相邻时间桶往前的记忆；
    同一会话（人物）按时间（天/章节）聚合给原文线索。
    """
    if primary is None or primary not in chap_text:
        return []
    picked = []
    used = 0
    n = primary
    while used < budget and n >= 1:
        if n in chap_text:
            title, body = chap_text[n]
            take = body[:budget - used]
            picked.append({'chapter': n, 'title': title, 'text': take})
            used += len(take)
        n -= 1          # 向更早的时间桶回溯
    return picked


def build_store(chunks, boost_struct=True):
    from md_cg.mdcos import MdCGOS
    if boost_struct:
        os.environ['MDCG_STRUCT_BOOST'] = '1'
    os.environ.setdefault('MDCG_BUCKET_SCOPE', '1')
    g = MdCGOS(tempfile.mkdtemp(prefix='rubric_'), actor='bench')
    for i, (a, b, body, ch) in enumerate(chunks):
        tags = ['ch:%d' % ch] if ch else []
        g.add('c_%04d' % i, CCG.format(n='L%d-L%d' % (a, b), s='win', e='%d-%d' % (a, b),
                                       body=body), tags=tags)
    return g


def prepare(bench, out_dir, k, shards, ev_chars=600, window=12):
    chunks = chunks_of(bench, window=window)
    g = build_store(chunks)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for q in data:
        points = []
        ev_all = []
        for j, pt in enumerate(q.get('points') or []):
            res, _meta = g.search_rrf(pt['stmt'], k=k)
            ev = []
            for item in res[:k]:
                m = re.match(r'c_(\d+)', str(item[0].get('id') or ''))
                a, b = (), ()
                if m:
                    a, b, _body, ch = chunks[int(m.group(1))]
                    ev.append({'lines': '%d-%d' % (a, b), 'chapter': ch,
                               'text': str(item[0].get('content') or '')[:ev_chars]})
            points.append({'idx': j, 'stmt': pt['stmt'], 'evidence': ev})
            ev_all.extend(ev)
        rows.append({'qid': q['qid'], 'points': points})
    per = max(1, (len(rows) + shards - 1) // shards)
    for i in range(0, len(rows), per):
        part = rows[i:i + per]
        p = os.path.join(out_dir, 'r_%02d.jsonl' % (i // per))
        with open(p, 'w', encoding='utf-8') as fh:
            for r in part:
                fh.write(json.dumps(r, ensure_ascii=False) + chr(10))
    # 闭卷对照（无证据）
    for i in range(0, len(rows), per):
        part = rows[i:i + per]
        p = os.path.join(out_dir, 'c_%02d.jsonl' % (i // per))
        with open(p, 'w', encoding='utf-8') as fh:
            for r in part:
                r2 = {'qid': r['qid'],
                      'points': [{'idx': p2['idx'], 'stmt': p2['stmt'], 'evidence': []}
                                 for p2 in r['points']]}
                fh.write(json.dumps(r2, ensure_ascii=False) + chr(10))
    print(json.dumps({'questions': len(rows),
                      'assertions': sum(len(r['points']) for r in rows),
                      'chunks': len(chunks), 'k': k,
                      'shards': (len(rows) + per - 1) // per}, ensure_ascii=False))
    return 0






#: 混合装配的三段预算（占总额的比例）：精确块 / 章节上下文 / 同人物线索。
HYBRID_SPLIT = (0.40, 0.70, 1.00)


def _person_of(stmt):
    """六元素 · 分隔：第 2 段是人物（章节是第 1 段）。"""
    parts = [p.strip() for p in str(stmt or '').split('·') if p.strip()]
    return parts[1] if len(parts) >= 2 else None


def pack_hybrid(store, chunks, chap_text, stmts, k=5, budget=PACK_CHARS):
    """混合装配：① 精确块（可核对性最高）② 其章节上下文 ③ 同一人物线索。

    动机（实测，2026-11-09）：整章优先的两种装配分别只有 0.7156 / 0.7301，
    低于精确块的 0.8098——差别在 fn（97 → 146/154）：整章把无关段落带进来，
    稀释了六要素的可核对性。故改成「精确块优先、整章补齐、同人物线索兜底」。
    """
    b1, b2, b3 = (int(budget * r) for r in HYBRID_SPLIT)
    picked, used = [], 0
    # ① 精确块：逐断言检索命中，按最佳名次去重
    seen_ids, hit_chunks, hit_chapters = set(), [], {}
    for stmt in stmts:
        res, _meta = store.search_rrf(stmt, k=k)
        for rank, item in enumerate(res[:k]):
            m = re.match(r'c_(\d+)', str(item[0].get('id') or ''))
            if not m:
                continue
            ci = int(m.group(1))
            if ci in seen_ids:
                continue
            seen_ids.add(ci)
            a, b, body, ch = chunks[ci]
            hit_chunks.append((rank, ci, a, b, body, ch))
            if ch:
                hit_chapters[ch] = hit_chapters.get(ch, 0) + 1
    hit_chunks.sort()
    for rank, ci, a, b, body, ch in hit_chunks:
        if used >= b1:
            break
        take = body[:min(600, b1 - used)]
        picked.append({'part': 'exact', 'lines': '%d-%d' % (a, b),
                       'chapter': ch, 'text': take})
        used += len(take)
    # ② 命中章的上下文（按章号顺序，补齐到第二段预算）
    for ch in sorted(hit_chapters):
        if used >= b2:
            break
        if ch not in chap_text:
            continue
        title, body = chap_text[ch]
        take = body[:min(b2 - used, 1500)]
        picked.append({'part': 'chapter', 'chapter': ch, 'title': title, 'text': take})
        used += len(take)
    # ③ 同一人物线索：其他出现该人物的块（按时间/行号顺序）
    persons = [p for p in {_person_of(x) for x in stmts} if p]
    for person in persons:
        if used >= b3:
            break
        for a, b, body, ch in chunks:
            if used >= b3:
                break
            if person not in body:
                continue
            if any(p.get('text', '')[:60] == body[:60] for p in picked):
                continue
            take = body[:min(400, b3 - used)]
            picked.append({'part': 'same_person', 'person': person,
                           'lines': '%d-%d' % (a, b), 'chapter': ch, 'text': take})
            used += len(take)
    return picked


def prepare_hybrid(bench, out_dir, k, shards, pack_chars=PACK_CHARS):
    chunks = chunks_of(bench)
    g = build_store(chunks)
    chap_text = chapters_text(bench)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for q in data:
        stmts = [pt['stmt'] for pt in (q.get('points') or [])]
        pack = pack_hybrid(g, chunks, chap_text, stmts, k=k, budget=pack_chars)
        rows.append({'qid': q['qid'],
                     'points': [{'idx': j, 'stmt': st} for j, st in enumerate(stmts)],
                     'pack': pack})
    per = max(1, (len(rows) + shards - 1) // shards)
    for i in range(0, len(rows), per):
        with open(os.path.join(out_dir, 'h_%02d.jsonl' % (i // per)), 'w', encoding='utf-8') as fh:
            for r in rows[i:i + per]:
                fh.write(json.dumps(r, ensure_ascii=False) + chr(10))
    chars = [sum(len(c['text']) for c in r['pack']) for r in rows]
    parts = {}
    for r in rows:
        for c in r['pack']:
            parts[c['part']] = parts.get(c['part'], 0) + len(c['text'])
    print(json.dumps({'questions': len(rows),
                      'assertions': sum(len(r['points']) for r in rows),
                      'avg_pack_chars': int(sum(chars) / max(1, len(chars))),
                      'part_chars': parts,
                      'shards': (len(rows) + per - 1) // per}, ensure_ascii=False))
    return 0








def prepare_cited_ctx(bench, out_dir, k, shards, pack_chars=PACK_CHARS):
    """所引章节 + 前后上下文，**保留章边界**（补齐到 pack_chars 但不丢判据范围）。

    动机（实测）：只给所引章节 0.9436/φ0.887；给多章混合（hybrid/整章）跌到 0.72–0.74。
    差别不在字数，在**边界**：多章混在一起后，模型失去「本章」这个判据范围。
    """
    chap_text = chapters_text(bench)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for q in data:
        points = []
        for j, pt in enumerate(q.get('points') or []):
            m = re.search(r'第([一二三四五六七八九十\d]+)章', pt['stmt'])
            ch = cn2int(m.group(1)) if m else None
            pack, used = [], 0
            if ch in chap_text:
                title, body = chap_text[ch]
                take = body[:pack_chars]
                pack.append({'role': 'cited', 'chapter': ch, 'title': title, 'text': take})
                used += len(take)
                for delta in (-1, 1):            # 前后各一章作背景（明确标注）
                    nb = ch + delta
                    if used >= pack_chars or nb not in chap_text:
                        continue
                    t2, b2 = chap_text[nb]
                    take2 = b2[:min(2000, pack_chars - used)]
                    pack.append({'role': 'context_only', 'chapter': nb,
                                 'title': t2, 'text': take2})
                    used += len(take2)
            points.append({'idx': j, 'stmt': pt['stmt'], 'pack': pack})
        rows.append({'qid': q['qid'], 'points': points})
    per = max(1, (len(rows) + shards - 1) // shards)
    for i in range(0, len(rows), per):
        with open(os.path.join(out_dir, 'y_%02d.jsonl' % (i // per)), 'w', encoding='utf-8') as fh:
            for r in rows[i:i + per]:
                fh.write(json.dumps(r, ensure_ascii=False) + chr(10))
    chars = [sum(len(c['text']) for c in p2['pack']) for r in rows for p2 in r['points']]
    print(json.dumps({'questions': len(rows),
                      'assertions': sum(len(r['points']) for r in rows),
                      'avg_chars': int(sum(chars) / max(1, len(chars))),
                      'shards': (len(rows) + per - 1) // per}, ensure_ascii=False))
    return 0


def prepare_cited(bench, out_dir, k, shards, pack_chars=PACK_CHARS):
    """只给「题面所述章节」的原文（官方开卷上界口径，用于定位「多给章节」的副作用）。"""
    chap_text = chapters_text(bench)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for q in data:
        points = []
        for j, pt in enumerate(q.get('points') or []):
            m = re.search(r'第([一二三四五六七八九十\d]+)章', pt['stmt'])
            ch = cn2int(m.group(1)) if m else None
            pack = []
            if ch in chap_text:
                title, body = chap_text[ch]
                pack = [{'part': 'cited_chapter', 'chapter': ch, 'title': title,
                         'text': body[:pack_chars]}]
            points.append({'idx': j, 'stmt': pt['stmt'], 'pack': pack})
        rows.append({'qid': q['qid'], 'points': points})
    per = max(1, (len(rows) + shards - 1) // shards)
    for i in range(0, len(rows), per):
        with open(os.path.join(out_dir, 'x_%02d.jsonl' % (i // per)), 'w', encoding='utf-8') as fh:
            for r in rows[i:i + per]:
                fh.write(json.dumps(r, ensure_ascii=False) + chr(10))
    chars = [sum(len(c['text']) for c in p2['pack']) for r in rows for p2 in r['points']]
    print(json.dumps({'questions': len(rows),
                      'assertions': sum(len(r['points']) for r in rows),
                      'avg_chars': int(sum(chars) / max(1, len(chars))),
                      'missing_chapter': sum(1 for r in rows for p2 in r['points'] if not p2['pack']),
                      'shards': (len(rows) + per - 1) // per}, ensure_ascii=False))
    return 0


def prepare_exact(bench, out_dir, k, shards, pack_chars=PACK_CHARS):
    """只用**精确检索块**填满 1 万字预算（不掺整章、不掺同人物）——对照实验。"""
    global HYBRID_SPLIT
    HYBRID_SPLIT = (1.0, 0.0, 0.0)      # ② ③ 段预算为 0 ⇒ 只剩 part=exact
    chunks = chunks_of(bench)
    g = build_store(chunks)
    chap_text = chapters_text(bench)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for q in data:
        stmts = [pt['stmt'] for pt in (q.get('points') or [])]
        pack = pack_hybrid(g, chunks, chap_text, stmts, k=k, budget=pack_chars)
        rows.append({'qid': q['qid'],
                     'points': [{'idx': j, 'stmt': st} for j, st in enumerate(stmts)],
                     'pack': pack})
    per = max(1, (len(rows) + shards - 1) // shards)
    for i in range(0, len(rows), per):
        with open(os.path.join(out_dir, 'e_%02d.jsonl' % (i // per)), 'w', encoding='utf-8') as fh:
            for r in rows[i:i + per]:
                fh.write(json.dumps(r, ensure_ascii=False) + chr(10))
    chars = [sum(len(c['text']) for c in r['pack']) for r in rows]
    print(json.dumps({'questions': len(rows), 'k': k,
                      'avg_pack_chars': int(sum(chars) / max(1, len(chars))),
                      'parts': sorted({c['part'] for r in rows for c in r['pack']}),
                      'shards': (len(rows) + per - 1) // per}, ensure_ascii=False))
    return 0


def prepare_timepack(bench, out_dir, k, shards, pack_chars=PACK_CHARS):
    """时间桶投喂（**每题一份**）：检索投票定位主章 → 按 1 万字一份装配，
    不足则向更早的章回溯。六条断言共享同一份聚合线索（使用者口径：
    同一会话/人物按时间聚合给原文线索，控制输入总量）。"""
    chunks = chunks_of(bench)
    g = build_store(chunks)
    chap_text = chapters_text(bench)
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for q in data:
        vote = {}
        for pt in q.get('points') or []:
            res, _meta = g.search_rrf(pt['stmt'], k=k)
            for item in res[:k]:
                m = re.match(r'c_(\d+)', str(item[0].get('id') or ''))
                if not m:
                    continue
                _a, _b, _body, ch = chunks[int(m.group(1))]
                if ch:
                    vote[ch] = vote.get(ch, 0) + 1
        # 命中章**全部纳入**（不只票王），再按时间顺序补齐到 1 万字：
        # 只取票王 + 向更早回溯的版本实测只有 71.6%（票王常选错，越回溯越偏）。
        pack = pack_from_chapters(chap_text, sorted(vote, key=lambda c: -vote[c]),
                                  budget=pack_chars)
        points = [{'idx': j, 'stmt': pt['stmt']}                      # 共享 pack，避免 6 倍重复
                  for j, pt in enumerate(q.get('points') or [])]
        rows.append({'qid': q['qid'], 'points': points, 'pack': pack})
    per = max(1, (len(rows) + shards - 1) // shards)
    for i in range(0, len(rows), per):
        part = rows[i:i + per]
        with open(os.path.join(out_dir, 't_%02d.jsonl' % (i // per)), 'w', encoding='utf-8') as fh:
            for r in part:
                fh.write(json.dumps(r, ensure_ascii=False) + chr(10))
    chars = [sum(len(c['text']) for c in r.get('pack') or []) for r in rows]
    print(json.dumps({'questions': len(rows),
                      'assertions': sum(len(r['points']) for r in rows),
                      'chapters': len(chap_text), 'pack_chars': pack_chars,
                      'avg_pack_chars': int(sum(chars) / max(1, len(chars))),
                      'min_pack': min(chars) if chars else 0,
                      'max_pack': max(chars) if chars else 0,
                      'shards': (len(rows) + per - 1) // per}, ensure_ascii=False))
    return 0


def grade(bench, picks_path):
    data = json.load(open(os.path.join(bench, 'mcq', 'reasoning',
                                       '题目_多跳六元素_rubric92_平衡掩码.json'),
                          encoding='utf-8'))
    gold = {}
    for q in data:
        for j, pt in enumerate(q.get('points') or []):
            gold['%s#%d' % (q['qid'], j)] = bool(pt['answer'])
    picks = {}
    for line in open(picks_path, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        for a in d.get('answers') or []:
            key = '%s#%s' % (d.get('qid'), a.get('idx'))
            v = a.get('answer')
            if isinstance(v, str):
                v = v.strip() in ('是', 'true', 'True', 'T', 'Y', 'yes')
            picks[key] = bool(v)
    tp = tn = fp = fn = 0
    for key, g in gold.items():
        p = picks.get(key)
        if p is None:
            continue
        if g and p:
            tp += 1
        elif g and not p:
            fn += 1
        elif (not g) and p:
            fp += 1
        else:
            tn += 1
    pos, neg = tp + fn, tn + fp
    tpr = tp / pos if pos else 0.0
    tnr = tn / neg if neg else 0.0
    bal = (tpr + tnr) / 2
    phi = 0.0
    n = tp + tn + fp + fn
    if n and (tp + fp) and (tp + fn) and (tn + fp) and (tn + fn):
        phi = ((tp * tn) - (fp * fn)) / (((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)) ** 0.5)
    print(json.dumps({'n': n, 'answered': len(picks), 'tp': tp, 'tn': tn,
                      'fp': fp, 'fn': fn, 'balanced_acc': round(bal, 4),
                      'phi': round(phi, 4)}, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=('prepare', 'grade'))
    ap.add_argument('--bench', default=os.environ.get('HMB', ''))
    ap.add_argument('--out', default='.tmp/rubric_payload')
    ap.add_argument('--picks', default='.tmp/rubric_picks.jsonl')
    ap.add_argument('--k', type=int, default=5)
    ap.add_argument('--shards', type=int, default=12)
    ap.add_argument('--ev-chars', type=int, default=600)
    ap.add_argument('--window', type=int, default=12)
    ap.add_argument('--mode-pack', default='chunk', choices=('chunk', 'timepack', 'hybrid', 'exact', 'cited', 'cited_ctx'))
    ap.add_argument('--pack-chars', type=int, default=PACK_CHARS)
    a = ap.parse_args()
    if not a.bench or not os.path.isdir(a.bench):
        print('需要 --bench 或 HMB', file=sys.stderr)
        return 2
    if a.mode == 'prepare' and a.mode_pack == 'cited_ctx':
        return prepare_cited_ctx(a.bench, a.out, a.k, a.shards, a.pack_chars)
    if a.mode == 'prepare' and a.mode_pack == 'cited':
        return prepare_cited(a.bench, a.out, a.k, a.shards, a.pack_chars)
    if a.mode == 'prepare' and a.mode_pack == 'exact':
        return prepare_exact(a.bench, a.out, a.k, a.shards, a.pack_chars)
    if a.mode == 'prepare' and a.mode_pack == 'hybrid':
        return prepare_hybrid(a.bench, a.out, a.k, a.shards, a.pack_chars)
    if a.mode == 'prepare' and a.mode_pack == 'timepack':
        return prepare_timepack(a.bench, a.out, a.k, a.shards, a.pack_chars)
    if a.mode == 'prepare':
        return prepare(a.bench, a.out, a.k, a.shards, a.ev_chars, a.window)
    return grade(a.bench, a.picks)


if __name__ == '__main__':
    sys.exit(main())