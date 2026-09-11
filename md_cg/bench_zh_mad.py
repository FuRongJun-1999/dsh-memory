# -*- coding: utf-8 -*-
"""中文多维探针（MAD, multi-axis）——20 条「中文层 + 英文原文」语料，Rust 侧四路检索。

与既有 zh_probe 探针的关系：前一版探针只测「中文层做索引」的单点效果；本探针
把写入侧加工拆成可消融的四个维度，逐一叠加，看每一步对检索指标的边际贡献：

  轴 1 实体规范化  —— 全库 df 聚合出的 canonical 词 + 人物/地点/时间 → tags（entity 路）
  轴 2 指代消解    —— **仅当本条自身无实体**时承接**前一条自身**的 canonical（保守附加）
  轴 3 意图抽象    —— 摘要 → 规范意图类目；类目 + 动词原形 → tags，类目 → 正文子功能行
  轴 4 关系图遍历  —— 人物/事件/时间/身份/地点/条件 多维关系 → edges（graph 路）

首轮五臂实测出现三项反直觉负增益，经取证判定为**实现/口径缺陷**而非能力缺陷
（结论已归档灵枢记忆；本段为修正说明）：
  * 轴2 原实现无条件承接，且 `last_canon = cur`（含继承）单调累积 → tags 退化为
    「历史全集」，后段条目对任何查询都命中 entity 路（-15~-20pp）。本文件已改为
    规格语义；修正后本探针集**无「自身无实体」条目 → 该轴未激活**（`承接条数=0`）。
  * 轴3 原产出是摘要切片（非抽象），且只进正文、只喂词法路；RRF 按**名次**融合，
    该行只改变 jaccard 分母不改名次 → 边际恒 0。本文件已改为规范类目 + tags 通道。
  * 轴4 `_path_graph` 契约要求「种子已排序」，但 `_lexical` 在 LIKE 命中
    ≤ `GLOBAL_CAP`(500) 时返回**未排序**列表 → seeds[:5] 退化为索引枚举序前 5 条，
    图路对多题注入同一恒定集合。`run_seed_control` 用于隔离该口径缺陷。

数据源（**全部既有真源，零新增标注**）：
  * data/external/zh_probe/manual_zh.json          20 条 gold turn 的中文层（既有产物）
  * data/external/zh_probe/manual_q.json           20 条中文查询
  * data/external/longmemeval/lme_s_haystack.jsonl 英文原文（按 id 取）
  * data/external/longmemeval/lme_s_questions.jsonl qid → qtype / evidence_turns

诚实条款（报告必须原样声明）：
  * 中文层与查询均为**既有产物**（非本次生成），本脚本不改一字，只做结构解析；
  * 写入侧加工是**确定性纯规则**（零 LLM、零第三方依赖、同输入必同输出），
    词表随源码公开，第三方可重放；
  * 加工**盲于查询集**：canonical 判定只用全库 df 与中文层自身字段，
    不读 manual_q.json 的任何内容——否则即数据泄漏，评测作废；
  * 池仅 20 条 → 随机基线 hit@1 = 5%，单项能力 ±1 题即 ±5 个百分点。
    结论只能作**方向性证据**，不可作定量结论。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 本脚本既可能被当脚本跑（sys.path[0] 是 md_cg/），也可能被当包内模块导入
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

EXT = os.path.join(HERE, "data", "external")
ZP = os.path.join(EXT, "zh_probe")
LM = os.path.join(EXT, "longmemeval")

MANUAL_ZH = os.path.join(ZP, "manual_zh.json")
MANUAL_Q = os.path.join(ZP, "manual_q.json")
LM_H = os.path.join(LM, "lme_s_haystack.jsonl")
LM_Q = os.path.join(LM, "lme_s_questions.jsonl")

CORPUS20 = os.path.join(ZP, "corpus20.jsonl")
QUESTIONS20 = os.path.join(ZP, "questions20.jsonl")

# 关系轴：用户裁决「条件链 + 人物/事件/时间/身份/地点都可以作为关系」
AXES = ("person", "event", "time", "identity", "place", "condition")


def iter_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_zh(raw):
    """中文层串 → 槽位 dict。

    格式（manual_zh.json 既有形态，本函数只解析不改写）：
        身份=用户；时间=2023/05/24 04:49；摘要=…；
        条件=观测位置:会话陈述|观测工具:会话记录|时间窗口:2023-05-24|存在约束:公开；
        词=礼物,礼物清单,场合
    """
    out = {"identity": "", "time": "", "summary": "", "condition": {},
           "terms": []}
    for seg in str(raw).split("；"):
        seg = seg.strip()
        if not seg or "=" not in seg:
            continue
        key, val = seg.split("=", 1)
        key, val = key.strip(), val.strip()
        if key == "身份":
            out["identity"] = val
        elif key == "时间":
            out["time"] = val
        elif key == "摘要":
            out["summary"] = val
        elif key == "条件":
            for kv in val.split("|"):
                if ":" in kv:
                    k, v = kv.split(":", 1)
                    out["condition"][k.strip()] = v.strip()
        elif key == "词":
            out["terms"] = [t.strip() for t in val.split(",") if t.strip()]
    return out


def prepare(verbose=True):
    """生成 corpus20.jsonl 与 questions20.jsonl（幂等覆盖）。"""
    man_zh = load_json(MANUAL_ZH)
    man_q = load_json(MANUAL_Q)
    meta = {r["qid"]: r for r in iter_jsonl(LM_Q)}
    want_ids = set(man_zh)
    hay = {}
    for r in iter_jsonl(LM_H):
        if r["id"] in want_ids:
            hay[r["id"]] = r
            if len(hay) == len(want_ids):
                break

    missing = want_ids - set(hay)
    if missing:
        raise SystemExit(f"[失败] haystack 缺以下 turn：{sorted(missing)}")

    # corpus：按 turn id 的数值序（= 时间序），保证「承接前一条」有确定语义
    def turn_no(tid):
        return int(tid.rsplit("t", 1)[1])

    corpus = []
    for tid in sorted(man_zh, key=turn_no):
        t = hay[tid]
        corpus.append({
            "id": tid,
            "text": str(t.get("text") or ""),
            "speaker": str(t.get("speaker") or ""),
            "date": str(t.get("date") or ""),
            "zh": man_zh[tid],
            "zh_fields": parse_zh(man_zh[tid]),
        })

    # questions：qid → 中文查询 + 证据（完整 evidence_turns，池里仅 ev0 存在）
    questions = []
    for qid, q in man_q.items():
        m = meta.get(qid)
        if m is None:
            raise SystemExit(f"[失败] questions 缺 qid={qid}")
        questions.append({
            "qid": qid,
            "qtype": m["qtype"],
            "question": q,
            "answer": str(m.get("answer") or ""),
            "evidence_turns": list(m.get("evidence_turns") or []),
        })

    with open(CORPUS20, "w", encoding="utf-8") as f:
        for r in corpus:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(QUESTIONS20, "w", encoding="utf-8") as f:
        for r in questions:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if verbose:
        print(f"语料 {len(corpus)} 条 → {CORPUS20}")
        print(f"题库 {len(questions)} 条 → {QUESTIONS20}")
        n_etype = {}
        for q in questions:
            n_etype[q["qtype"]] = n_etype.get(q["qtype"], 0) + 1
        print("题型分布：" + ", ".join(f"{k}={v}" for k, v in sorted(n_etype.items())))
    return corpus, questions


def analyze(verbose=True):
    """诊断：查询词能否落到 gold 中文层 / 池内其他条目（决定各轴是否有可桥接的实体）。

    只读既有产物，不修改任何语料。输出两类事实：
      * 查询词在 gold 中文层的字面命中率 → 词法路的天花板；
      * 查询词在**池内**的 df → 该词的判别力（df=1 是精确定位，df=20 则无信息量）。
    """
    corpus, questions = prepare(verbose=False)
    zh_of = {c["id"]: c["zh"] for c in corpus}

    per_q = []
    for q in questions:
        ev0 = q["evidence_turns"][0] if q["evidence_turns"] else ""
        terms = [t for t in str(q["question"]).split() if t]
        hit = [t for t in terms if ev0 and t in zh_of.get(ev0, "")]
        globalish = [t for t in terms
                     if sum(1 for c in corpus if t in zh_of[c["id"]]) == len(corpus)]
        per_q.append({
            "qid": q["qid"], "ev0": ev0, "qtype": q["qtype"],
            "n_term": len(terms), "n_hit": len(hit),
            "hit_terms": hit,
            "df1": sorted({t for t in terms
                           if sum(1 for c in corpus if t in zh_of[c["id"]]) == 1}),
            "all_df": globalish,
        })

    if verbose:
        print(f"\n== 查询词覆盖诊断（池 {len(corpus)} 条，题 {len(questions)} 道）==")
        print(f"{'qid':<16}{'ev0':<12}{'词数':>5}{'命中':>5}  命中词")
        print("-" * 72)
        for r in per_q:
            print(f"{r['qid']:<16}{r['ev0']:<12}{r['n_term']:>5}{r['n_hit']:>5}  "
                  f"{','.join(r['hit_terms'])[:40]}")
        tot_t = sum(r["n_term"] for r in per_q)
        tot_h = sum(r["n_hit"] for r in per_q)
        zero = [r["qid"] for r in per_q if r["n_hit"] == 0]
        print("-" * 72)
        print(f"合计：{tot_h}/{tot_t} 个查询词落在 gold 中文层"
              f"（{tot_h / max(1, tot_t):.1%}）")
        print(f"零重叠题（{len(zero)}）：{', '.join(zero) if zero else '无'}")
        return per_q

    return per_q


# ---------------------------------------------------------------- 写入侧四轴
# 全部为确定性纯规则：零 LLM、零外部依赖，同输入必同输出；词表随源码公开。
# **盲于查询集**：以下规则只读 corpus20（语料）与中文层自身字段，从不打开 manual_q.json。

STOP_ZH = frozenset(
    "的 了 在 是 我 你 他 她 它 和 与 或 这 那 有 没 不 就 都 也 还 要 会 能 可以 "
    "多少 什么 哪里 哪 怎么 为什么 几 一些 一个 之 其 与 及 等 被 把 给 对 从 到".split()
)

PERSON_HINTS = (
    "妹妹", "姐姐", "哥哥", "弟弟", "妈妈", "爸爸", "母亲", "父亲", "父母", "奶奶",
    "爷爷", "外婆", "外公", "同事", "朋友", "同学", "邻居", "老板", "上司", "教练",
    "医生", "老师", "室友", "伴侣", "丈夫", "妻子", "儿子", "女儿", "叔叔", "阿姨",
    "表亲", "未婚夫", "未婚妻",
)

PLACE_HINTS = (
    "市", "州", "城", "镇", "岛", "公园", "中心", "大学", "海滩", "广场", "机场",
    "河", "湖", "山", "街", "路", "区", "国家", "澳洲", "欧洲", "亚洲", "美洲",
)

EN_STOP = frozenset("""
The A An And But Or For Nor So Yet This That These Those There Their They Them Then Than
When What Where Which While Who Whom Whose Why How However Also Always Never Often Sometimes
I You He She It We They Me Him Her Us My Your His Its Our Very Really Just Only Even Still
Have Has Had Having Do Does Did Doing Be Been Being Am Is Are Was Were Will Would Shall
Should Can Could May Might Must Not No Yes If In On At By To Of With From Into Onto Over
Under Above Below Between During After Before About Around Because Since Until Upon While
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May
June July August September October November December Today Yesterday Tomorrow Last Next
New Old Good Bad Best Worst First Second Third One Two Three Four Five Six Seven Eight Nine
Ten Okay Ok Well Thanks Thank Please Hi Hello Hey
""".split())

EN_NAME_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:[ ][A-Z][a-z]{2,})*\b")
DATE_RE = re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})")


def norm_time(raw):
    """'2023/05/24 04:49' → '2023-05-24'（跨条目统一格式，使日期查询可命中）。"""
    m = DATE_RE.search(str(raw or ""))
    if not m:
        return ""
    y, mo, d = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def en_names(text):
    """英文原文中的专名候选（跨语言桥：中文查询里的英文专名可经 entity 路命中）。"""
    out, seen = [], set()
    for m in EN_NAME_RE.finditer(str(text or "")):
        w = m.group(0)
        if any(p in EN_STOP for p in w.split()):
            continue
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def build_tables(corpus):
    """全库统计：# 词项 df（**只读语料**，与查询集无关）。"""
    df = {}
    for c in corpus:
        for t in set(c["zh_fields"]["terms"]):
            if t and t not in STOP_ZH:
                df[t] = df.get(t, 0) + 1
    return df


def axis_values(c, df):
    """一条 turn 的六个关系轴取值（用户裁决：条件链 + 人物/事件/时间/身份/地点）。"""
    f = c["zh_fields"]
    terms = [t for t in f["terms"] if t and t not in STOP_ZH]
    tw = norm_time(f["condition"].get("时间窗口") or f["time"])
    person = [t for t in terms if any(h in t for h in PERSON_HINTS)]
    place = [t for t in terms if any(h in t for h in PLACE_HINTS)]
    event = [t for t in terms if df.get(t, 0) >= 2]
    return {
        "person": person,
        "event": event,
        "time": [tw] if tw else [],
        "identity": [f["identity"]] if f["identity"] else [],
        "place": place,
        "condition": [f"{k}:{v}" for k, v in f["condition"].items()],
    }


# 意图类目：意图动词 → 规范类目（确定性词表，只读摘要，与查询集无关）
INTENT_CLASSES = (
    ("推荐", ("推荐", "建议", "咨询", "请教")),
    ("购置", ("购买", "买", "挑选", "选购", "下单", "购买")),
    ("整理", ("整理", "清理", "分类", "收纳", "归档")),
    ("学习", ("学习", "了解", "阅读", "查阅", "研究")),
    ("规划", ("计划", "安排", "准备", "制定")),
    ("比较", ("比较", "对比", "估算", "计算")),
    ("维修", ("维修", "修理", "更换", "保养")),
    ("出行", ("旅行", "搬家", "搬迁", "游玩", "漂流")),
    ("参加", ("参加", "报名", "出席")),
    ("健身", ("锻炼", "跑步", "训练")),
    ("取退", ("退还", "退回", "归还")),
    ("完成", ("完成", "做完", "结课")),
)


def intent_of(c):
    """意图抽象：摘要 → (规范类目, 命中的动词原形)。

    规格要求「抽象」。原实现返回摘要切片 `f"{v}：" + summary[i-6:i+10]`——
    那只是把原文再抄一遍：不产生任何新词、不构成类目，且只写进正文，
    而正文只喂词法路、RRF 又只按**名次**融合（见 bench 报告），故边际恒为 0。
    此处归一为固定类目，并保留命中的动词原形，二者一并进 tags（entity 路——
    存在性匹配，不吃分数尺度），使该轴真正获得独立检索通道。
    """
    s = c["zh_fields"]["summary"]
    for cls, verbs in INTENT_CLASSES:
        for v in verbs:
            if v in s:
                return cls, v
    return "", ""


def normalize_terms(c, df):
    """实体规范化：去停用 + 去重 + 附时间规范式 + 附英文专名（跨语言对齐）。"""
    f = c["zh_fields"]
    out, seen = [], set()
    for t in list(f["terms"]) + en_names(c["text"]):
        t = t.strip()
        if not t or t in STOP_ZH or t.lower() in STOP_ZH or t in seen:
            continue
        seen.add(t)
        out.append(t)
    tw = norm_time(f["condition"].get("时间窗口") or f["time"])
    if tw and tw not in seen:
        out.append(tw)
    return out


def build_arm(corpus, arm, max_df=5, root_base=None, verbose=True):
    """按消融臂建库。每臂一个独立 root，互不污染。

    臂的差异**只体现在库内容**（正文/tags/edges），检索路固定
    lexical+entity+graph——这样"能力未开"就等于"库内没有对应信息"，
    归因干净：指标变化可直接归给该轴，而不是归给路开关。
    """
    from md_cg.mdcos import MdCGOS
    root = os.path.join(HERE, root_base or f"_md_cg_eval_zhprobe_{arm['name']}")

    df = build_tables(corpus)
    axes = {c["id"]: axis_values(c, df) for c in corpus}

    edges = {}
    if arm.get("graph"):
        for ax in AXES:
            val2ids = {}
            for c in corpus:
                for v in axes[c["id"]][ax]:
                    val2ids.setdefault(v, set()).add(c["id"])
            for v, ids in val2ids.items():
                if not (2 <= len(ids) <= max_df):
                    continue  # df=1 无边；df>max_df 全连通，零信息量只注入噪声
                for a in ids:
                    for b in ids:
                        if a != b:
                            edges.setdefault(a, {})[b] = ax

    if os.path.isdir(root):
        import shutil
        shutil.rmtree(root, ignore_errors=True)
    cg = MdCGOS(root, autoflush=500)

    prev_own = None  # 前一条**自身**的 canonical（不累积）
    n_coref = 0
    for c in corpus:
        f = c["zh_fields"]
        own = normalize_terms(c, df) if arm.get("norm") else []

        # 轴2 指代消解（规格：保守附加）——**仅当本条自身无实体**时，
        # 才承接**前一条自身**的 canonical。
        # 原实现：`if coref and last_canon` 无条件承接，且 `last_canon = cur`
        # 把「继承结果」也计入 → 单调累积成「历史全集」，tags 雪球污染。
        inherit = []
        if arm.get("coref") and not own and prev_own:
            inherit = list(prev_own)
            n_coref += 1

        # 轴3 意图抽象：类目写正文（规格的「子功能行」），类目词 + 动词原形写 tags。
        intent_terms = []
        intent_line = ""
        if arm.get("intent"):
            cls, verb = intent_of(c)
            if cls:
                intent_line = f"意图：{cls}"
                intent_terms = [f"意图:{cls}"] + ([verb] if len(verb) >= 2 else [])

        body = [f"身份：{f['identity']}", f"时间：{f['time']}",
                f"摘要：{f['summary']}", f"词：{','.join(f['terms'])}",
                "条件：" + "|".join(f"{k}:{v}" for k, v in f["condition"].items())]
        if intent_line:
            body.append(intent_line)
        if inherit:
            body.append("承接：" + ",".join(inherit))
        body.append("")
        body.append(c["text"])

        tags = own[:]
        for t in intent_terms + inherit:
            if t not in tags:
                tags.append(t)

        e = [{"target": t, "axis": a} for t, a in edges.get(c["id"], {}).items()]
        cg.add(c["id"], "\n".join(body), layer="contextual", tags=tags,
               edges=e, eval_src=f"zh_mad:{arm['name']}", verification_basis="data")

        prev_own = own[:]

    cg.flush()
    if verbose:
        n_e = sum(len(v) for v in edges.values())
        print(f"  [{arm['name']}] root={os.path.basename(root)} "
              f"tags_axis={'on' if arm.get('norm') else 'off'} "
              f"coref={'on' if arm.get('coref') else 'off'} "
              f"intent={'on' if arm.get('intent') else 'off'} "
              f"graph={'on' if arm.get('graph') else 'off'} 有向边={n_e} "
              f"承接条数={n_coref}")
    return root


ARMS = [
    {"name": "a0_base", "norm": False, "coref": False, "intent": False, "graph": False},
    {"name": "a1_norm", "norm": True, "coref": False, "intent": False, "graph": False},
    {"name": "a2_coref", "norm": True, "coref": True, "intent": False, "graph": False},
    {"name": "a3_intent", "norm": True, "coref": True, "intent": True, "graph": False},
    {"name": "a4_graph", "norm": True, "coref": True, "intent": True, "graph": True},
]


def build_all(max_df=5):
    corpus, _ = prepare(verbose=False)
    print(f"== 建库（消融 {len(ARMS)} 臂，max_df={max_df}）==")
    roots = {}
    for arm in ARMS:
        roots[arm["name"]] = build_arm(corpus, arm, max_df=max_df)
    return roots


RUST_BIN = os.path.join(HERE, "rust", "target", "release", "mdcg-eval.exe")
ROW_RE = re.compile(
    r"^\s*(precise|temporal|interference|reference)\s+(\d+)\s+"
    r"([\d.]+)%\s+([\d.]+)%\s+([\d.]+)\s*$", re.M)
GROUPS = ["precise", "temporal", "interference", "reference"]


def run_one(name, lib, extra=None):
    """调用 **Rust 检索器** 跑一臂，返回 {组: (n, hit@1, hit@5, MRR)}。

    命令执行走 subprocess argv 列表 + 显式 UTF-8 + PYTHONUTF8=1（不经 Windows shell），
    规避 GBK 解码异常。
    """
    import subprocess

    if not os.path.exists(RUST_BIN):
        raise SystemExit(f"[失败] 未找到 Rust 评测器：{RUST_BIN}（先 cargo build --release）")
    argv = [RUST_BIN, "--dataset", "mad", "--tag", name, "--lib", lib]
    if extra:
        argv += list(extra)
    env = dict(os.environ, PYTHONUTF8="1")
    p = subprocess.run(argv, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, cwd=HERE)
    if p.returncode != 0:
        raise SystemExit(f"[失败] {name}：{(p.stderr or '')[-900:]}")
    got = {}
    for m in ROW_RE.finditer(p.stdout):
        g, n, h1, h5, mrr = m.groups()
        got[g] = (int(n), float(h1), float(h5), float(mrr))
    if not got:
        raise SystemExit(f"[失败] {name}：未解析到组指标\n{p.stdout[-1200:]}")
    return got


def print_table(title, rows, baseline=None):
    """rows: [(label, got, note)]；baseline = 参照行 label（算 Δ）。"""
    print(f"\n== {title} ==")
    hdr = (f"{'臂':<14}" + "".join(f"{g[:12]:>15}" for g in GROUPS)
           + f"{'总体hit@1':>12}{'总体MRR':>10}")
    print(hdr)
    print("-" * len(hdr))
    ref = None
    for label, got, note in rows:
        cells, tot_h1, tot_n, tot_mrr = [], 0.0, 0, 0.0
        for g in GROUPS:
            n, h1, _h5, mrr = got[g]
            cells.append(f"{h1:.0f}%/{mrr:.3f}")
            tot_h1 += h1 / 100.0 * n
            tot_n += n
            tot_mrr += mrr * n
        ov_h1 = tot_h1 / max(1, tot_n)
        ov_mrr = tot_mrr / max(1, tot_n)
        if baseline is not None and label == baseline:
            ref = (ov_h1, ov_mrr)
        delta = ""
        if ref is not None and label != baseline:
            delta = f"  (Δ{(ov_h1 - ref[0]) * 100:+.1f}pp)"
        suffix = f"  {note}" if note else ""
        print(f"{label:<14}" + "".join(f"{c:>15}" for c in cells)
              + f"{ov_h1 * 100:>10.1f}%{ov_mrr:>10.3f}{delta}{suffix}")


def run_ablation():
    """消融主表：逐臂调用 Rust 检索器并汇总（种子口径 = 缺省，即生产现状）。"""
    rows = []
    for arm in ARMS:
        name = arm["name"]
        rows.append((name, run_one(name, f"_md_cg_eval_zhprobe_{name}"), ""))
    print_table("消融主表（Rust 检索器，k=5，jaccard，证据命中；graph 种子=索引序）",
                rows, baseline=ARMS[0]["name"])
    print("\n随机基线 hit@1 = 5.0%（1/20）；池仅 20 条，±1 题 = ±5pp，"
          "结论只作方向性证据。")
    return rows


def run_seed_control():
    """对照：**同一个 a4 库**（写入侧与边结构完全相同），只切换 graph 路种子口径。

    用于把 a4 相对 a3 的变化拆成两个因子：
      * 边结构质量（本轴真正要测的能力）；
      * `_path_graph`「种子须已排序」契约被违反 → seeds[:5] 退化为索引枚举序前 5。
    """
    lib = f"_md_cg_eval_zhprobe_{ARMS[-1]['name']}"
    rows = [
        ("a4/index", run_one("a4_index", lib), "现状：seeds=索引枚举序前 5"),
        ("a4/sorted", run_one("a4_sorted", lib, ("--graph-seeds", "sorted")),
         "文档语义：seeds=top-5 词法"),
    ]
    print_table("graph 种子口径对照（库内容完全相同，只换种子）", rows,
                baseline="a4/index")
    return rows


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "prepare"
    if cmd == "prepare":
        prepare()
    elif cmd == "analyze":
        analyze()
    elif cmd == "build":
        build_all()
    elif cmd == "run":
        run_ablation()
    elif cmd == "seed-control":
        run_seed_control()
    elif cmd == "all":
        prepare()
        analyze()
        build_all()
        run_ablation()
        run_seed_control()
    else:
        raise SystemExit(
            f"未知子命令：{cmd}"
            "（可用：prepare / analyze / build / run / seed-control / all）")


if __name__ == "__main__":
    main(sys.argv)
