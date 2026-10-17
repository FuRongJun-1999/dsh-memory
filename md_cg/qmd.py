# -*- coding: utf-8 -*-
"""QMD 多维汇流检索（零模型核）：TriCue v3 种子 + 源图分维扩散 + 题面侧抽取维，加权倒数排名融合。

本模块只做**排序**，不调模型、不联网、无学习状态。源图三元组与题面扩展（hints）由调用方给出
（可用 ``md_cg/qmd_llm.py`` 抽取，也可来自任何缓存）；本模块不接入 ``MdCG`` / ``MdCGOS`` 的任何
既有检索路径——不 import 本模块的代码路径行为逐位不变（守卫 ``md_cg/test_qmd.py`` P13）。

依据（白箱三问之一：依据什么）
------------------------------
  · 原型：TanPowasd/LingShu-prime ``TanPowasd/agm/confluence/``（``multidim.py`` ``MultiDim``、
    ``qmd.py`` ``QMD``、``hive_qmd.py`` ``HiveQMD``）与 ``TanPowasd/agm/tricue/tricue.py``
    （``TriCueMemory.v3()``）；本文件是为本仓重写的等价实现，排序与原型逐位相同（抽检见 PR 说明）。
  · 冻结配置 ``FROZEN``（w_v3=3, w_qx=3，其余取 ``DEF``/``QDEF`` 缺省）在 LoCoMo 英文 dev
    （conv-30、conv-47，231 题）上预注册选定，之后才在中文 hive 主轮 92 题上留出验证
    （原型 ``PREREG_qmd.md``）。

算法（参数全部是模块常量）
--------------------------
  v3 维    TriCue v3：词项＝中日韩重叠字二元组 + 其余小写整词（有序）；打分 BM25+(k1=1.2,b=.75,δ=1)
           × SDM（单词项 .85 / 有序相邻对 .10 / 无序窗口对 .05，窗口 8，无序对只在前 1000 篇算）；
           每条文本按行累积约 300 字切块，同文本相邻块 前→后 .5 / 后→前 .25，上一文本末块→本文本首块
           .4 / 反向 .25；打分前 8 名为种子，扩散 2 步，非种子每步衰减 35%，阈值 .05，k-WTA 80；
           块序折回文本序（首次出现）。
  源图     三元组（主，谓，宾）的主/宾归一成实体；实体 → 出处文本（出处边）；主↔宾 为谓词边
           （正 .6 / 反 .4）；实体内容词 Jaccard≥.5 或互相包含为近义边（只连边、不合并）。
  枢纽抑制 出处文本数 > hub×文本总数（hub=.02）的实体不进任何维（高频噪声实体不扩散）。
  ent/pred/syn/tmp 维  题面实体与 v3 前 8 名种子文本的实体为种子，沿各自的边一跳；
           tmp = 种子文本的同会话邻文本（前 .3 / 后 .15）。每维取前 50。
  qent/qtri/qx 维（需要题面扩展 hint）  qent：hint 实体 → 图实体（Jaccard≥.5 或包含）→ 出处；
           qtri：三元组主/宾命中 hint 实体且谓词与 hint 谓词有词重合 → 该文本；
           qx：题面 + 检索词 + 假想答句 + 实体 + 谓词 拼成扩展查询再跑一次 v3。
  融合     score(t) = Σ_维 w_维 / (60 + 名次)（每维前 400），其后接 v3 剩余顺序。

生效条件（白箱三问之二：在什么条件下成立）
------------------------------------------
  · triples 与 texts 等长；某条为 ``None`` = 该文本**没抽过**源图 ⇒ 构造时抛 ``PartialGraph``
    （空列表 ``[]`` = 抽过、无事实，合法）。截断/空源图不会被当作完整图使用。
  · ``QMD.rank(q)`` 缺 hint 时抛 ``MissingHint``；只有显式 ``require_hints=False`` 才退回多维
    （结果与 ``MultiDim.rank`` 逐位相同，守卫 P11）。
  · lang="zh"：实体键＝去标点字串，内容词＝字二元组集合；题面实体＝二元组全在题面里的图实体
    （单字名不算）。lang="en"：实体键＝小写字母数字词，内容词＝去停用词的词集。

错了怎么办 / 边界（白箱三问之三）
--------------------------------
  · 无 LLM 可用时没有源图与 hint，只剩 v3/多维的零 key 检索面；端到端增益不成立（不宣称）。
  · 单题材料很短、全文可直接放进上下文时，直读仍是上界，本模块无必要。
  · 原型的 set 迭代序依赖 PYTHONHASHSEED：同进程内与原型逐位相同；跨进程浮点累加次序不同可能使
    并列项次序不同（推断，未见读数差异）。
"""
from __future__ import annotations

import bisect
import collections
import math
import re

__all__ = ["V3", "MultiDim", "QMD", "PartialGraph", "MissingHint", "FROZEN", "DEF", "QDEF"]

# ---------------------------------------------------------------- TriCue v3 最小核
CHUNK = 300
SEEDS, DECAY, THETA, KWTA, STEPS = 8, 0.35, 0.05, 80, 2
W_FWD, W_BWD, W_QA = 0.5, 0.25, 0.4
K1, B, DELTA = 1.2, 0.75, 1.0
SDM_W = (0.85, 0.10, 0.05)
SDM_WIN = 8
UW_TOP = 1000

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]+")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


# 生效条件：给定字符串 s，去掉全部非字词字符后返回。
def norm(s) -> str:
    return re.sub(r"[^\w]", "", str(s or ""), flags=re.UNICODE)


# 生效条件：给定字符串 s，中日韩连续段取重叠字二元组（单字段取单字），其余字母数字串取小写整词，按出现顺序返回列表。
def seq_tokens(s: str) -> list:
    out = []
    for w in _WORD.findall(s):
        pos = 0
        for m in _CJK.finditer(w):
            if m.start() > pos:
                out.append(w[pos:m.start()].lower())
            run = m.group()
            if len(run) > 1:
                out.extend(run[i:i + 2] for i in range(len(run) - 1))
            else:
                out.extend(run)
            pos = m.end()
        if pos < len(w):
            out.append(w[pos:].lower())
    return out


# 生效条件：给定文本与块长 size，按行累积、去标点长度达到 size 即切出一块，返回块列表（末块非空才保留）。
def split_chunks(text: str, size: int = CHUNK) -> list:
    out, buf = [], ""
    for line in text.split("\n"):
        buf += line + "\n"
        if len(norm(buf)) >= size:
            out.append(buf)
            buf = ""
    if norm(buf):
        out.append(buf)
    return out


class _SDM:
    """文档级 BM25+ × SDM 三类特征（单词项、有序相邻对、无序窗口对）。"""

    def __init__(self, uw_top: int = UW_TOP):
        self.uw_top = uw_top
        self.tf, self.tf2, self.pos, self.dl = [], [], [], []
        self.inv = collections.defaultdict(list)
        self.inv2 = collections.defaultdict(list)
        self.total = 0

    @property
    def N(self) -> int:
        return len(self.dl)

    # 生效条件：给定词项序列 toks，登记为新文档并返回其号。
    def add(self, toks: list) -> int:
        d = self.N
        c = collections.Counter(toks)
        c2 = collections.Counter(zip(toks, toks[1:]))
        p = collections.defaultdict(list)
        for i, t in enumerate(toks):
            p[t].append(i)
        self.tf.append(c); self.tf2.append(c2); self.pos.append(dict(p)); self.dl.append(len(toks))
        self.total += len(toks)
        for t in c:
            self.inv[t].append(d)
        for t in c2:
            self.inv2[t].append(d)
        return d

    def _part(self, tf, df, dl, avg):
        idf = math.log((self.N + 1) / df)
        return idf * ((K1 + 1) * tf / (K1 * (1 - B + B * dl / avg) + tf) + DELTA)

    @staticmethod
    def _uw(pa, pb):
        n = 0
        for x in pa:
            i = bisect.bisect_left(pb, x - SDM_WIN + 1)
            while i < len(pb) and pb[i] <= x + SDM_WIN - 1:
                if pb[i] != x:
                    n += 1
                    break
                i += 1
        return n

    # 生效条件：给定查询词项序列 q，返回 {文档号: BM25+×SDM 分}（无文档或空查询返回空字典）。
    def score(self, q: list) -> dict:
        if not self.N or not q:
            return {}
        avg = self.total / self.N or 1.0
        sc = collections.defaultdict(float)
        wt, wo, wu = SDM_W
        for t in set(q):
            post = self.inv.get(t)
            if post:
                df = len(post)
                for d in post:
                    sc[d] += wt * self._part(self.tf[d][t], df, self.dl[d], avg)
        pairs = {(a, b) for a, b in zip(q, q[1:]) if a != b}
        for pr in pairs:
            post = self.inv2.get(pr)
            if post:
                df = len(post)
                for d in post:
                    sc[d] += wo * self._part(self.tf2[d][pr], df, self.dl[d], avg)
        cand = set(sorted(sc, key=lambda d: -sc[d])[: self.uw_top]) if self.uw_top else None
        for pr in pairs:
            a, b = pr
            pa_, pb_ = self.inv.get(a), self.inv.get(b)
            if not pa_ or not pb_:
                continue
            both = set(pa_).intersection(pb_) if len(pa_) < len(pb_) else set(pb_).intersection(pa_)
            if cand is not None:
                both &= cand
            hits = {}
            for d in both:
                n = self._uw(self.pos[d][a], self.pos[d][b])
                if n:
                    hits[d] = n
            if hits:
                df = len(hits)
                for d, n in hits.items():
                    sc[d] += wu * self._part(n, df, self.dl[d], avg)
        return sc


class V3:
    """TriCue v3：BM25+×SDM 为种子的 AGM 扩散单路；按写入顺序给每条文本一个号。"""

    def __init__(self, texts):
        self.sdm = _SDM()
        self.turn_of = []
        self.out = collections.defaultdict(dict)
        self._last = None
        for t, text in enumerate(texts):
            prev = None
            for piece in split_chunks(text):
                i = self.sdm.add(seq_tokens(piece))
                self.turn_of.append(t)
                if prev is not None:
                    self.out[prev][i] = W_FWD; self.out[i][prev] = W_BWD
                elif self._last is not None:
                    self.out[self._last][i] = W_QA; self.out[i][self._last] = W_BWD
                prev = i
            if prev is not None:
                self._last = prev

    # 生效条件：给定查询字符串 q，返回块号排序：AGM 放电块按激活降序，其后接打分剩余块按分降序；无命中返回空列表。
    def rank_chunks(self, q: str) -> list:
        sc = self.sdm.score(seq_tokens(q))
        if not sc:
            return []
        top = sorted(sc, key=lambda i: -sc[i])[:SEEDS]
        m = sc[top[0]] or 1.0
        x = {i: sc[i] / m for i in top}
        a = dict(x)
        for _ in range(STEPS):
            nxt = collections.defaultdict(float)
            for i, ai in a.items():
                for j, w in self.out[i].items():
                    nxt[j] += ai * w
            for i, v in x.items():
                nxt[i] += v
            nxt = {i: (v if i in x else (1 - DECAY) * v) for i, v in nxt.items()}
            a = dict(sorted(((i, v) for i, v in nxt.items() if v >= THETA), key=lambda kv: -kv[1])[:KWTA])
        rest = sorted((i for i in sc if i not in a), key=lambda i: -sc[i])
        return sorted(a, key=lambda i: -a[i]) + rest

    # 生效条件：给定查询字符串 q，把 rank_chunks 的块序折回文本号（首次出现保留），返回文本号列表。
    def rank(self, q: str) -> list:
        seen, o = set(), []
        for c in self.rank_chunks(q):
            t = self.turn_of[c]
            if t not in seen:
                seen.add(t); o.append(t)
        return o


# ---------------------------------------------------------------- 语言口径
_STOP = set(("a an the of to in on at for with and or is are was were be been my your his her their our its this that "
             "these those i you he she we they it me him them us some any").split())


# 生效条件：lang="en" 时实体键＝小写字母数字词以空格连接；其余（"zh"）＝去标点字串。
def ent_key(s, lang: str) -> str:
    if lang == "en":
        return " ".join(re.findall(r"[a-z0-9]+", str(s).lower()))
    return norm(s)


# 生效条件：lang="en" 时内容词＝去停用词且长度>1 的词集；其余（"zh"）＝字二元组集合，单字键退为 {键}，空键为空集。
def content(k: str, lang: str) -> set:
    if lang == "en":
        return {w for w in k.split() if w not in _STOP and len(w) > 1}
    n = norm(k)
    return {n[i:i + 2] for i in range(len(n) - 1)} or ({k} if k else set())


class PartialGraph(ValueError):
    """源图没有覆盖全部文本（triples 里有 None，或长度与 texts 不符）。"""


class MissingHint(KeyError):
    """QMD.rank 的问题没有题面扩展 hint，且未显式允许退回多维。"""


# ---------------------------------------------------------------- 多维
DEF = dict(seeds=8, hub=.02, w_v3=2.0, w_ent=1.0, w_pred=1.0, w_syn=1.0, w_tmp=1.0, coinc=0, k=60, depth=50,
           pf=.6, pb=.4, tf=.3, tb=.15)


class MultiDim:
    """源图分维（ent/pred/syn/tmp）各自一跳扩散、各自排名，与 v3 加权 RRF。"""

    def __init__(self, texts, sessions, triples, lang: str = "zh", **p):
        if len(sessions) != len(texts) or len(triples) != len(texts):
            raise PartialGraph(f"texts={len(texts)} sessions={len(sessions)} triples={len(triples)} 长度不一致")
        miss = [i for i, t in enumerate(triples) if t is None]
        if miss:
            raise PartialGraph(f"源图缺 {len(miss)}/{len(texts)} 条文本（首个缺号 {miss[0]}）；先补抽，"
                               "截断源图不得当完整图用")
        P = self.p = {**DEF, **p}
        self.lang = lang
        self.base = V3(texts)
        self.n = n = len(texts)
        eid, self.cw = {}, []
        prov = collections.defaultdict(set); pred = []
        for ti, tri in enumerate(triples):
            for s, _p, o in tri:
                ab = []
                for x in (s, o):
                    k = ent_key(x, lang)
                    if not content(k, lang):
                        ab.append(None); continue
                    if k not in eid:
                        eid[k] = len(self.cw); self.cw.append(content(k, lang))
                    ab.append(eid[k]); prov[eid[k]].add(ti)
                if None not in ab and ab[0] != ab[1]:
                    pred.append(tuple(ab))
        self.hubs = {e for e, ts in prov.items() if P["hub"] and len(ts) > P["hub"] * n}
        self.prov = {e: ts for e, ts in prov.items() if e not in self.hubs}
        self.t2e = collections.defaultdict(set)
        for e, ts in self.prov.items():
            for t in ts:
                self.t2e[t].add(e)
        self.pred = collections.defaultdict(dict)
        for a, b in pred:
            if a in self.prov and b in self.prov:
                self.pred[a][b] = max(self.pred[a].get(b, 0), P["pf"]); self.pred[b][a] = max(self.pred[b].get(a, 0), P["pb"])
        inv = collections.defaultdict(list)
        for e, ws in enumerate(self.cw):
            if e in self.prov:
                for w in ws:
                    inv[w].append(e)
        self.syn = collections.defaultdict(dict)
        for e in self.prov:
            ws = self.cw[e]
            for j, sh in collections.Counter(j for w in ws for j in inv[w] if j != e).items():
                jac = sh / len(ws | self.cw[j])
                if jac >= .5 or ws <= self.cw[j] or self.cw[j] <= ws:
                    self.syn[e][j] = max(jac, .5)
        self.nb = collections.defaultdict(dict)
        for i in range(n - 1):
            if sessions[i] == sessions[i + 1]:
                self.nb[i][i + 1] = P["tf"]; self.nb[i + 1][i] = P["tb"]

    def spec(self, e):
        return 1 / math.log(math.e + len(self.prov[e]))

    # 生效条件：给定 {实体: 激活}，按出处边乘特异度 1/ln(e+出处数) 累加到文本，返回 {文本: 分}。
    def to_turns(self, ea):
        s = collections.defaultdict(float)
        for e, v in ea.items():
            for t in self.prov.get(e, ()):
                s[t] += v * self.spec(e)
        return s

    # 生效条件：给定问题 q，返回题面实体 {实体: 权}：zh＝实体内容词全为二元组且都在题面二元组里（权 1）；en＝实体内容词 ⊆ 题面内容词（权＝内容词数）。
    def qents(self, q):
        if self.lang == "en":
            qw = content(ent_key(q, "en"), "en")
            return {e: len(self.cw[e]) for e in self.prov if self.cw[e] and self.cw[e] <= qw}
        n = norm(q)
        qb = {n[i:i + 2] for i in range(len(n) - 1)}
        return {e: 1 for e in self.prov if self.cw[e] and all(len(w) == 2 for w in self.cw[e]) and self.cw[e] <= qb}

    # 生效条件：给定问题 q，返回各维排名 {"v3", "ent", "pred", "syn", "tmp"}（非 v3 维各取前 depth）。
    def channels(self, q):
        P = self.p
        v3 = self.base.rank(q)
        seed_t = {t: 1 / (1 + .25 * r) for r, t in enumerate(v3[:P["seeds"]])}
        qe = self.qents(q)
        se = collections.defaultdict(float)
        for e, v in qe.items():
            se[e] = max(se[e], 1.0)
        for t, v in seed_t.items():
            for e in self.t2e.get(t, ()):
                se[e] = max(se[e], .5 * v)
        ch = {"v3": v3}
        ch["ent"] = self.to_turns({e: 1.0 for e in qe})
        for name, adj in (("pred", self.pred), ("syn", self.syn)):
            nxt = collections.defaultdict(float)
            for e, v in se.items():
                for j, w in adj.get(e, {}).items():
                    nxt[j] += v * w
            ch[name] = self.to_turns(nxt)
        tmp = collections.defaultdict(float)
        for t, v in seed_t.items():
            for j, w in self.nb[t].items():
                tmp[j] += v * w
        ch["tmp"] = tmp
        for k in ("ent", "pred", "syn", "tmp"):
            ch[k] = sorted(ch[k], key=lambda t: -ch[k][t])[: P["depth"]]
        return ch

    # 生效条件：给定各维排名 ch，按 Σ w_维/(k+名次)（每维前 400）融合，其后接 v3 剩余顺序，返回文本号列表。
    def _fuse(self, ch):
        P = self.p
        sc = collections.defaultdict(float)
        for k, r in ch.items():
            w = P.get("w_" + k, 0)
            for i, t in enumerate(r[:400]):
                sc[t] += w / (P["k"] + i + 1)
        o = sorted(sc, key=lambda t: -sc[t])
        s = set(o)
        return o + [t for t in ch["v3"] if t not in s]

    # 生效条件：给定问题 q，返回融合后的文本号排序（coinc>0 时非 v3 维只保留在 ≥coinc 个维里出现的文本）。
    def rank(self, q):
        P = self.p
        ch = self.channels(q)
        if P["coinc"]:
            cnt = collections.Counter(t for k in ("ent", "pred", "syn", "tmp") for t in ch[k])
            for k in ("ent", "pred", "syn", "tmp"):
                ch[k] = [t for t in ch[k] if cnt[t] >= P["coinc"]]
        return self._fuse(ch)


# ---------------------------------------------------------------- QMD
QDEF = dict(w_qent=1.0, w_qtri=1.5, w_qx=2.0, use_hyde=1, use_kw=1)
FROZEN = dict(w_v3=3.0, w_qx=3.0)


class QMD(MultiDim):
    """多维 + 题面侧抽取维（qent / qtri / qx）。hints: {问题原文: {"ents","preds","time","kw","hyde"}}。"""

    def __init__(self, texts, sessions, triples, hints, lang: str = "zh", require_hints: bool = True, **p):
        q = {k: p.pop(k) for k in list(p) if k in QDEF}
        super().__init__(texts, sessions, triples, lang=lang, **p)
        self.p.update({**QDEF, **q})
        self.hints = dict(hints or {})
        self.require_hints = require_hints
        self.tri = []
        eid = {}
        for e, ws in enumerate(self.cw):
            eid.setdefault(frozenset(ws), e)
        for ti, tri in enumerate(triples):
            for s, pr, o in tri:
                es = [eid.get(frozenset(content(ent_key(x, lang), lang))) for x in (s, o)]
                self.tri.append((ti, es[0] if es[0] in self.prov else None, content(ent_key(pr, lang), lang),
                                 es[1] if es[1] in self.prov else None))
        self.inv = collections.defaultdict(set)
        for e in self.prov:
            for w in self.cw[e]:
                self.inv[w].add(e)

    # 生效条件：给定名字 name，返回与之内容词 Jaccard≥.5 或互相包含的图实体 {实体: max(Jaccard, .5)}；名字无内容词返回空字典。
    def match(self, name):
        ws = content(ent_key(name, self.lang), self.lang)
        if not ws:
            return {}
        cand = set().union(*(self.inv.get(w, set()) for w in ws))
        out = {}
        for e in cand:
            c = self.cw[e]
            j = len(ws & c) / len(ws | c)
            if j >= .5 or c <= ws or ws <= c:
                out[e] = max(j, .5)
        return out

    # 生效条件：给定问题 q：有 hint ⇒ 多维各维之外加 qent/qtri/qx 三维；无 hint 且 require_hints ⇒ 抛 MissingHint；无 hint 且显式 require_hints=False ⇒ 只返回多维各维。
    def channels(self, q, h=None):
        ch = super().channels(q)
        h = h or self.hints.get(q)
        if not h:
            if self.require_hints:
                raise MissingHint(q)
            return ch
        qe = collections.defaultdict(float)
        for n in h["ents"]:
            for e, v in self.match(n).items():
                qe[e] = max(qe[e], v)
        ch["qent"] = sorted((s := self.to_turns(qe)), key=lambda t: -s[t])[: self.p["depth"]]
        pw = set().union(*[content(ent_key(x, self.lang), self.lang) for x in h["preds"]]) if h["preds"] else set()
        tri = collections.defaultdict(float)
        for ti, s, pr, o in self.tri:
            hit = (qe.get(s, 0) if s is not None else 0) + (qe.get(o, 0) if o is not None else 0)
            if hit and (not pw or pr & pw):
                tri[ti] += hit * (1.5 if pr & pw else 1.0)
        ch["qtri"] = sorted(tri, key=lambda t: -tri[t])[: self.p["depth"]]
        ext = " ".join([q] + (h["kw"] if self.p["use_kw"] else []) + ([h["hyde"]] if self.p["use_hyde"] and h["hyde"] else [])
                       + h["ents"] + h["preds"])
        ch["qx"] = self.base.rank(ext)
        return ch

    # 生效条件：给定问题 q，返回 QMD 融合排序（文本号列表）；缺 hint 的处理见 channels。
    def rank(self, q):
        return self._fuse(self.channels(q))
