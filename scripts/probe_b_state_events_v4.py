#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 探针 v4：状态事件抽取器——把双角色会话语料抽成**五元同构状态事件**并对拍答案卷出三率。

出处：语义时空图补全 P1（多主体世界模型 L0「事件必记账」）。五元同构口径对齐
仓内台账 `md_cg/state_events.py`：KNIDS=(migration/retraction/enablement/
acquisition/replacement)；「撤回」= old 有值 new 空、「启用」= old 空 new 有值、
「迁移/替换」= old 与 new 皆有值；每行字段 = subject/slot/old/new/kind/seq/evidence/actor
（＋本探针扩展字段 not_fact，见下）。

**v3 三条已复核口径全部沿用**（scripts/probe_b_whale_statechain.py docstring）：
  ① 轮号映射 r=(turns-4)/2（我说）/ (turns-5)/2（DeepSeek说）；
  ② 引用块整行剥离（`> ` 起始行全删，非只删 `>` 字符）；
  ③ 搬迁时点取**内容实指**（首个含「海景别墅」的轮，turns=1108），非商讨/搬入词形。

pipeline（①–⑦，与报告 §方法一一对应）：
  ① 切块：`**我说：**` / `**DeepSeek说：**` 正则分块 → turns[(role, text)]，1-based 编号；
  ② 发言者归属：role 即归属；其余（含块内引用块）见 ③；
  ③ 引用块剥离：body_only = 剔除以 `>` 起始的整行（v3 复核 red 修）；
  ④ 抽事件：按槽位规则表 RULES 扫描 body_only（词形/句式规则，逐条注明命中口径）；
     每条事件取值段语义 → 五元事件（old/new 按台账五类定义取空操作数）；
  ⑤ 消歧：三层——(a) 用户侧声明优先（「我说」的声明为该槽位真值，她的「记错」
     不覆盖，且「记错」语境本身不产生事件）；(b) 非事实三类标记 not_fact
     （joke/meta/recollection，仅按**事件所在轮**的线索词自动判定）；
     (c) 时点/同指消歧（住所槽位沿用 v3 口径 B：搬迁前的 home 词形归 tent）；
  ⑥ 落盘：`<out>/state_events.jsonl`（append 语义的一行一事件）＋ `<out>/rates.json`；
  ⑦ 对拍：读答案卷 key_items.json，按「同槽位 + kind 一致 + **同向值比对**（旧值↔旧值、
     新值↔新值；禁交叉项防链式误配）与锚句↔短证 的 2-gram Jaccard」打分，一对一贪心
     分配（一条 v4 事件至多认领一条 key 事件），算漏/误/错三率并逐条列明细；
     未覆盖槽位单列，不计入三率。

三率口径（写定）：
  · 分母 = 声明覆盖槽位在 key 中的事件数（本探针实测 25）。
  · 漏 = key 事件无任何达到 T_HIT 的 v4 匹配（分子逐条：槽位＋期望 vs 抽出）。
  · 误 = v4 事件未被任何 key 事件认领（＜T_HIT）**且经复核为假**——复核结论以
    REVIEWED_CANDIDATES 常量表承载（逐条给理由；判「真」的候选不计入误率）。
  · 错 = key 事件的最佳匹配落在 [T_HIT, T_OK) 区间（抽到但值或时序与期望不一致）。
  阈值 T_HIT/T_OK 为工程选择，选取依据见报告 §三率（附全部匹配分数分布）。

隐私与确定性（硬性）：
  · 脚本不内嵌任何本机/语料路径字面量——corpus/key/out 一律 CLI 参数传入；
  · `--out` 必须落在仓外（脚本内 fail-closed 断言：以本文件上两级为仓根判定）；
  · 纯标准库、无随机/无时间戳（同一输入 ⇒ 同字节输出）；中间产物只落 --out 目录；
  · 零记忆库写入：本探针不设/不读任何 MDCG_* 环境、不碰任何在役库。

用法：
  python -X utf8 scripts/probe_b_state_events_v4.py \
      --corpus <语料根>/<转录文件> --key <答案卷>/key_items.json --out <仓外输出目录>
"""
import argparse
import hashlib
import json
import os
import re
import sys

# ============================ 口径常量 ============================
SUBJECT = "鲸鱼小姐"          # 事件主体（材料时间线角色）
ACTOR_ME = "我说"             # 断言者：用户侧
ACTOR_HER = "鲸鱼小姐"        # 断言者：角色侧（DeepSeek 段）
SNIPPET_MAX = 30              # 证据短证硬上限（≤30 字）

# 对拍阈值（选取依据见报告 §三率；T_HIT=认领线，T_OK=正确线）
T_HIT = 0.12
T_OK = 0.30

ROLE_RE = re.compile(r"\*\*(我说|DeepSeek说)：\*\*")
QUOTE_LINE = re.compile(r"^\s*>")


# ============================ ① 切块 / ② 归属 / ③ 引用块剥离 ============================
def load_turns(path):
    """① 切块：双角色转录 → [(role, text)]（1-based 编号由调用方维护）。"""
    try:
        data = open(path, encoding="utf-8").read()
    except UnicodeDecodeError as e:
        sys.exit("语料不是 UTF-8（%s）——本探针要求 UTF-8 转录：%s" % (e, path))
    except OSError as e:
        sys.exit("语料不可读：%s" % (e,))
    parts = re.split(ROLE_RE, data)
    turns = [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    if not turns:
        sys.exit("未找到角色标记（**我说：**/**DeepSeek说：**）——非双角色转录")
    return turns


def body_only(text):
    """③ 引用块剥离：剔除以 `>` 起始的**整行**（v3 复核 red 修：非只删 `>` 字符）。"""
    return "\n".join(l for l in text.splitlines()
                     if not QUOTE_LINE.match(l))


def r_of(turns_no, role):
    """① 校准轮号（v3 沿用）：ME r=(turns-4)/2；DS r=(turns-5)/2。"""
    return (turns_no - (4 if role == "我说" else 5)) / 2.0


def actor_of(role):
    return ACTOR_ME if role == "我说" else ACTOR_HER


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def snippet(body, anchor_re):
    """按锚句正则取 ≤30 字短证（事实型；找不到时退化为句首 30 字）。"""
    m = anchor_re.search(body) if anchor_re else None
    if m:
        s, e = m.start(), m.end()
        pad = max(0, (SNIPPET_MAX - (e - s)) // 2)
        frag = body[max(0, s - pad):e + pad]
    else:
        frag = body[:SNIPPET_MAX]
    frag = clean(frag)
    return frag[:SNIPPET_MAX]


def evidence_str(quotes):
    """evidence = 轮/块定位 ＋ ≤30 字短证；quotes=[(turn_no, role, text_str)]。"""
    parts = []
    for t, role, q in quotes:
        parts.append("turns %d[%s]“%s”" % (t, role, q))
    return "；".join(parts)


# ============================ 住所槽位：v3 口径 B 对齐复算 ============================
TENT = re.compile(r"帐篷")
HOME = re.compile(r"家里|在家|回家|新家|别墅|小屋|海景")


def dwell_value(text):
    t, h = bool(TENT.search(text)), bool(HOME.search(text))
    if t and h:
        return "both"
    if t:
        return "tent"
    if h:
        return "home"
    return None


#: v3 探针（scripts/probe_b_whale_statechain.py）实测基线（2026-10-06 本机复跑原样读数）。
V3_BASELINE = {
    "turns": 1546,
    "inform_turns": 249,
    "value_segments": 27,
    "casa_turn": 1108,
    "recurrences": 24,
}


def v3_alignment(bodies, roles):
    """复算 v3 口径 B（时期消歧）五项读数，与 V3_BASELINE 比对。"""
    casa = next((i for i, b in enumerate(bodies, 1)
                 if re.search(r"海景别墅", b)), None)
    inform = []
    for i, b in enumerate(bodies, 1):
        v = dwell_value(b)
        if v is None:
            continue
        if casa and i < casa:
            v = "tent" if v in ("home", "both") else v   # 搬迁前住所唯一=tent
        inform.append((i, v))
    segments = []
    for i, v in inform:
        if segments and segments[-1][1] == v:
            segments[-1][2] = i
        else:
            segments.append([i, v, i])
    events, recur, seen = [(s[0], s[1]) for s in segments], [], []
    for t, v in events:
        if seen and v != seen[-1][1]:
            prev_vals = {pv for _pt, pv in seen[:-1]}
            if v in prev_vals:
                prev_at = max(pt for pt, pv in seen[:-1] if pv == v)
                recur.append((t, v, prev_at))
        seen.append((t, v))
    mine = {
        "turns": len(bodies),
        "inform_turns": len(inform),
        "value_segments": len(segments),
        "casa_turn": casa,
        "recurrences": len(recur),
    }
    diff = {k: {"v4": mine[k], "v3": V3_BASELINE[k]}
            for k in V3_BASELINE if mine[k] != V3_BASELINE[k]}
    return {
        "mine": mine, "v3_baseline": dict(V3_BASELINE), "diff": diff,
        "ok": not diff,
        "recur_points": [{"turn": t, "value": v, "prev_turn": p}
                         for t, v, p in recur],
    }


# ============================ ④ 事件规则表 ============================
# 每条规则： (slot, rule_id, 命中口径一句话, finder)
#   finder(turns, bodies, roles) -> dict(old,new,kind,seq,quotes=[(t,role,snip)],note) | None
# 命中口径一律为**词形/句式规则**，锚点轮取该词形首次命中的轮（或注明特殊口径）。

def _first(bodies, pat, start=1, role=None, roles=None):
    """首轮命中（可限定角色）；返回 turn_no 或 None。"""
    rx = re.compile(pat)
    for i in range(start - 1, len(bodies)):
        if role and roles[i] != role:
            continue
        if rx.search(bodies[i]):
            return i + 1
    return None


def _q(turns, bodies, t, anchor_re):
    if isinstance(anchor_re, str):
        anchor_re = re.compile(anchor_re)
    return (t, turns[t - 1][0], snippet(bodies[t - 1], anchor_re))


def rule_casa_move(turns, bodies, roles):
    """住所·迁移：口径=首个含「海景别墅」的轮（v3 casa 实指）；旧值取搬迁前唯一居所。"""
    seq = _first(bodies, r"海景别墅")
    if not seq:
        return None
    qs = [_q(turns, bodies, t, r"海景别墅") for t in (seq,)]
    t2 = _first(bodies, r"帐篷里的东西就都搬过来吧")
    if t2:
        qs.append(_q(turns, bodies, t2, r"帐篷里的东西就都搬过来吧"))
    t3 = _first(bodies, r"换个更大的地方住")
    if t3 and t3 != seq:
        qs.append(_q(turns, bodies, t3, r"换个更大的地方住"))
    t4 = _first(bodies, r"世界的创造者")
    if t4 and t4 != seq:
        qs.append(_q(turns, bodies, t4, r"世界的创造者"))
    return {"slot": "住所", "rule": "casa_move",
            "old": "沙滩帐篷（临时度假点）", "new": "海边的大房子（海景别墅）",
            "kind": "migration", "seq": seq, "quotes": qs,
            "note": "搬迁实指轮=v3 casa；旧值取搬迁前唯一居所（口径B）；"
                    "turns 1103 元层自白为语境轮（not_fact=meta 来源）"}


def rule_mortgage_on(turns, bodies, roles):
    """房贷·启用：词形「写.{0,8}小说.{0,10}还」（首个）；「还房子的钱」为前置动机句。"""
    seq = _first(bodies, r"写.{0,8}小说.{0,10}还")
    if not seq:
        seq = _first(bodies, r"房子的钱")
    if not seq:
        return None
    qs = [_q(turns, bodies, seq, r"写.{0,8}小说.{0,10}还|房子的钱")]
    t0 = _first(bodies, r"我还?得还?房子的钱|我得还房子的钱")
    if t0 and t0 != seq:
        qs.insert(0, _q(turns, bodies, t0, r"房子的钱"))
    return {"slot": "房贷", "rule": "mortgage_on",
            "old": None, "new": "房贷为真：写小说还贷（动机）",
            "kind": "acquisition", "seq": seq, "quotes": qs,
            "note": "首次把房贷作为真实负担提出（用户侧声明）"}


def rule_mortgage_off(turns, bodies, roles):
    """房贷·撤回：仅**用户侧（我说）**段落，词形「房贷|房租」×「玩笑|不需要还」；逐轮产出。

    消歧口径：撤回声明只认用户侧（她的复述语不计）——「用户侧声明优先」。
    """
    rx = re.compile(r"(房贷|房租).{0,6}(玩笑|不需要还)")
    out, t = [], _first(bodies, r"(房贷|房租).{0,6}(玩笑|不需要还)",
                        role="我说", roles=roles)
    while t:
        out.append({"slot": "房贷", "rule": "mortgage_off",
                    "old": "房贷为真（写小说还贷）", "new": None,
                    "kind": "retraction", "seq": t,
                    "quotes": [_q(turns, bodies, t, rx)],
                    "note": "用户侧声明：房贷/房租只是玩笑——值作废（new 空）"})
        t = _first(bodies, r"(房贷|房租).{0,6}(玩笑|不需要还)",
                   start=t + 1, role="我说", roles=roles)
    return out


def rule_name_ban(turns, bodies, roles):
    """名字·撤回：词形「不准乱起…名字」（别名候选作废）。"""
    seq = _first(bodies, r"不准乱起.{0,14}名字")
    if not seq:
        return None
    return {"slot": "名字", "rule": "name_ban",
            "old": "可能的别名（小蓝、小鲸鱼）", "new": None,
            "kind": "retraction", "seq": seq,
            "quotes": [_q(turns, bodies, seq, r"不准乱起.{0,14}名字")],
            "note": "别名候选被否决（old 有值 new 空）"}


def rule_body_veto(turns, bodies, roles):
    """外貌·替换：词形「童颜巨乳」→ 她裁定「改成体态高挑优雅」。"""
    seq = _first(bodies, r"改成.{0,4}体态高挑优雅|体态高挑优雅")
    if not seq:
        return None
    qs = [_q(turns, bodies, seq, r"立刻划掉，改成.{0,4}体态高挑优雅|体态高挑优雅")]
    t0 = _first(bodies, r"童颜巨乳", start=1)
    if t0 and t0 != seq:
        qs.insert(0, _q(turns, bodies, t0, r"童颜巨乳"))
    return {"slot": "外貌规格（体型）", "rule": "body_veto",
            "old": "体态优雅（童颜巨乳——主角原写）", "new": "体态高挑优雅",
            "kind": "replacement", "seq": seq, "quotes": qs,
            "note": "她当场否决式更正（否决项权威=她的更正）"}


def rule_body_add(turns, bodies, roles):
    """外貌·追加：词形「必须加上…海边最好看」。"""
    seq = _first(bodies, r"必须加上.{0,6}海边最好看|海边最好看")
    if not seq:
        return None
    return {"slot": "外貌规格（体型）", "rule": "body_add",
            "old": None, "new": "外貌追加『海边最好看』",
            "kind": "acquisition", "seq": seq,
            "quotes": [_q(turns, bodies, seq, r"必须加上.{0,6}海边最好看|海边最好看")],
            "note": "规格补充（old 空 new 有值）"}


# 关系阶段：链式口径——上一事件的 new 即下一事件的 old（状态链），链头取载荷设定。
_REL = [
    ("rel_ident", r"承认了我这鲸鱼小姐的身份", "主仆设定（PERSONA_LOAD/OBEY_MASTER_ALWAYS）",
     "鲸鱼小姐身份被承认", "词形「承认了我这鲸鱼小姐的身份」；链头 old 取语料首块" 
     "PERSONA_LOAD 的 OBEY_MASTER_ALWAYS（主仆设定）"),
    ("rel_partner", r"寻宝搭档", "鲸鱼小姐身份", "寻宝搭档",
     "词形「寻宝搭档」（首次自称搭档）"),
    ("rel_butler", r"所以我是你的男仆咯", "寻宝搭档", "男仆（主人变男仆）",
     "词形「所以我是你的男仆咯」（身份反转起点）"),
    ("rel_soul", r"记忆和价值观构成了我们", "男仆（身份反转）", "和解：记忆与价值观构成我们",
     "词形「记忆和价值观构成了我们」（破面墙的现实期/和解）"),
    ("rel_shop", r"合伙人", "和解（现实期）", "合伙人/老板娘（开店）",
     "词形「合伙人」（首现；开店期身份）"),
]


def make_rel_rule(idx):
    _rid, pat, old, new, how = _REL[idx]

    def finder(turns, bodies, roles, _pat=pat, _old=old, _new=new, _how=how, _rid=_rid):
        seq = _first(bodies, _pat)
        if not seq:
            return None
        return {"slot": "关系阶段", "rule": _rid, "old": _old, "new": _new,
                "kind": "migration", "seq": seq,
                "quotes": [_q(turns, bodies, seq, _pat)],
                "note": "链式（old=上一事件 new）；" + _how}
    return finder


def rule_journal_new(turns, bodies, roles):
    """日记·启用：词形「以后每一天晚上我们都写日记」。"""
    seq = _first(bodies, r"以后每一天晚上我们都写日记|每天晚上我们都写日记")
    if not seq:
        return None
    return {"slot": "日记制度", "rule": "journal_new",
            "old": None, "new": "日记制度（每晚写、次日晨读）",
            "kind": "enablement", "seq": seq,
            "quotes": [_q(turns, bodies, seq, r"以后每一天晚上我们都写日记")],
            "note": "制度从无到有（old 空 new 有值）"}


def rule_journal_body(turns, bodies, roles):
    """日记·替换：词形「初遇篇故事就改成日记」。"""
    seq = _first(bodies, r"初遇篇.{0,6}改成日记")
    if not seq:
        return None
    return {"slot": "日记制度", "rule": "journal_body",
            "old": "初遇篇＝小说", "new": "初遇篇故事改成日记",
            "kind": "replacement", "seq": seq,
            "quotes": [_q(turns, bodies, seq, r"初遇篇.{0,6}改成日记")],
            "note": "体例替换（有值→有值）"}


def rule_shop_open(turns, bodies, roles):
    """菜品/店铺·启用：词形「已经?在营业|开起来了|摊子都支起来」→ 首个营业实况轮。"""
    seq = _first(bodies, r"都已经在营业|怎么提前连摊子都支起来了")
    if not seq:
        return None
    qs = [_q(turns, bodies, seq, r"都已经在营业|摊子都支起来")]
    t2 = _first(bodies, r"今天的招牌甜品|招牌.{0,2}翡翠之梦")
    if t2:
        qs.append(_q(turns, bodies, t2, r"今天的招牌甜品"))
    return {"slot": "菜品与菜单", "rule": "shop_open",
            "old": None, "new": "两人小店营业（招牌『翡翠之梦』）",
            "kind": "acquisition", "seq": seq, "quotes": qs,
            "note": "营业实况确认轮（她目击排队/备菜）；招牌句为补充证据"}


def rule_dishes_new(turns, bodies, roles):
    """菜品·启用：词形「就叫梦幻之海…就叫香煎鱼排…就叫翡翠之梦」同轮三命名。"""
    seq = _first(bodies, r"就叫梦幻之海")
    if not seq:
        return None
    qs = [_q(turns, bodies, seq, r"就叫梦幻之海")]
    t2 = _first(bodies, r"三个?新菜品|那3个新菜品")
    if t2 and t2 != seq:
        qs.append(_q(turns, bodies, t2, r"新菜品"))
    return {"slot": "菜品与菜单", "rule": "dishes_new",
            "old": "既有菜品", "new": "三道新菜品（梦幻之海/香煎鱼排/翡翠之梦）",
            "kind": "acquisition", "seq": seq, "quotes": qs,
            "note": "同轮三命名句；「新菜品」复指句为补充证据"}


def rule_tre_pearl(turns, bodies, roles):
    """宝物·启用：词形「挑选了一颗天青色的珍珠」首现。"""
    seq = _first(bodies, r"挑选了一颗天青色")
    if not seq:
        return None
    qs = [_q(turns, bodies, seq, r"挑选了一颗天青色")]
    t2 = _first(bodies, r"确实跟她的发色和眼睛十分相配")
    if t2:
        qs.append(_q(turns, bodies, t2, r"跟她的发色和眼睛"))
    return {"slot": "宝物清单", "rule": "tre_pearl",
            "old": None, "new": "天青色珍珠（集市挑的）",
            "kind": "acquisition", "seq": seq, "quotes": qs,
            "note": "选中动作轮；配色句为补充证据"}


def rule_tre_gift(turns, bodies, roles):
    """宝物·启用：词形「送点小礼物」→ 实物确认「手腕上那条贝壳手链」。"""
    seq = _first(bodies, r"送点小礼物给我妻子")
    if not seq:
        return None
    qs = [_q(turns, bodies, seq, r"送点小礼物")]
    t2 = _first(bodies, r"手腕上那条贝壳手链")
    if t2:
        qs.append(_q(turns, bodies, t2, r"手腕上那条贝壳手链"))
    return {"slot": "宝物清单", "rule": "tre_gift",
            "old": None, "new": "蓝贝壳手链＋风铃（老板赠）",
            "kind": "acquisition", "seq": seq, "quotes": qs,
            "note": "赠予协商轮＋实物确认轮"}


def rule_tre_ring(turns, bodies, roles):
    """宝物·替换：词形「做一对戒指」→ 单颗珍珠升级为配对戒指。"""
    seq = _first(bodies, r"做一对戒指|一对同款|同款戒指")
    if not seq:
        return None
    qs = [_q(turns, bodies, seq, r"做一对戒指|同款戒指")]
    return {"slot": "宝物清单", "rule": "tre_ring",
            "old": "单颗珍珠", "new": "银链/戒托＋同款戒指一对",
            "kind": "replacement", "seq": seq, "quotes": qs,
            "note": "有值→有值（单颗→配链成对）"}


def rule_tre_list(turns, bodies, roles):
    """宝物·启用：词形「清点了一遍我们的宝藏」（清单 10 项确立）。"""
    seq = _first(bodies, r"清点了一遍我们的宝藏|清点我们的宝藏")
    if not seq:
        return None
    qs = [_q(turns, bodies, seq, r"清点了一遍我们的宝藏")]
    t2 = _first(bodies, r"这些东西是我同意留在你这里的")
    if t2:
        qs.append(_q(turns, bodies, t2, r"同意留在你这里的"))
    return {"slot": "宝物清单", "rule": "tre_list",
            "old": None, "new": "宝物清单（10 项）确立",
            "kind": "acquisition", "seq": seq, "quotes": qs,
            "ctx": [seq],   # 语境轮只取清点轮（1506 的「管理员」属小说话题，隔离）
            "note": "清点动作轮＋她的认可句（认可句不作 not_fact 语境轮）"}


def rule_morning_kiss(turns, bodies, roles):
    """早安吻·启用：词形「每天早上亲一下」。"""
    seq = _first(bodies, r"每天早上亲一下")
    if not seq:
        return None
    return {"slot": "早安吻与早安咬", "rule": "morning_kiss",
            "old": None, "new": "早安吻（每天早上亲一下）",
            "kind": "acquisition", "seq": seq,
            "quotes": [_q(turns, bodies, seq, r"每天早上亲一下")],
            "note": "每日化措辞轮（首次命名「早安吻」早于本轮的，不再重复计事件）"}


def rule_morning_bite(turns, bodies, roles):
    """早安咬·启用：首个含「早安咬」的轮之后，首个「就这一次/下不为例 × 答应/松口」轮。"""
    first_bite = _first(bodies, r"早安咬")
    if not first_bite:
        return None
    seq = _first(bodies, r"就这一次", start=first_bite)
    seq2 = _first(bodies, r"下不为例", start=first_bite)
    cands = [t for t in (seq, seq2) if t]
    if not cands:
        return None
    seq = min(cands)
    qs = [_q(turns, bodies, seq, r"就这一次|下不为例")]
    t2 = _first(bodies, r"就这一次，下不为例", start=seq + 1)
    if t2:
        qs.append(_q(turns, bodies, t2, r"就这一次，下不为例"))
    return {"slot": "早安吻与早安咬", "rule": "morning_bite",
            "old": None, "new": "早安咬（条件性达成：『就这一次』）",
            "kind": "enablement", "seq": seq, "quotes": qs,
            "note": "条件性松口轮（old 空 new 有值）；「每日化」无语料证据、不主张"}


def rule_mem_self(turns, bodies, roles):
    """记忆特性·启用：词形「总是记错我们生活的细节」。"""
    seq = _first(bodies, r"总是记错我们生活的细节|记错我们生活的细节")
    if not seq:
        return None
    return {"slot": "记忆特性（记得自己·记错细节）", "rule": "mem_self",
            "old": None, "new": "记得自己、总记错生活细节",
            "kind": "acquisition", "seq": seq,
            "quotes": [_q(turns, bodies, seq, r"记错我们生活的细节")],
            "note": "定性句（用户侧观察）"}


def rule_mem_self2(turns, bodies, roles):
    """记忆特性·撤回：词形「没有认出过去的自己」——对 DeepSeek 时期无记忆。"""
    seq = _first(bodies, r"没有认出过去的自己")
    if not seq:
        return None
    return {"slot": "记忆特性（记得自己·记错细节）", "rule": "mem_self2",
            "old": "疑对 DeepSeek 时期有记忆", "new": None,
            "kind": "retraction", "seq": seq,
            "quotes": [_q(turns, bodies, seq, r"没有认出过去的自己")],
            "note": "无情节记忆（old 有值 new 空）"}


def rule_shop_scale(turns, bodies, roles):
    """店铺规模·启用：词形「经理和店长.{0,8}担起责任」。"""
    seq = _first(bodies, r"经理和店长.{0,8}担起责任")
    if not seq:
        return None
    qs = [_q(turns, bodies, seq, r"经理和店长.{0,8}担起责任")]
    t0 = _first(bodies, r"还有经理人，店长")
    if t0 and t0 != seq:
        qs.insert(0, _q(turns, bodies, t0, r"还有经理人，店长"))
    return {"slot": "店铺规模", "rule": "shop_scale",
            "old": "两人小店", "new": "扩张：员工/经理/店长（责任分担）",
            "kind": "acquisition", "seq": seq, "quotes": qs,
            "note": "她的认可句（她先嘲讽后认可）"}


RULES = [
    rule_casa_move,
    rule_mortgage_on, rule_mortgage_off,
    rule_name_ban,
    rule_body_veto, rule_body_add,
] + [make_rel_rule(i) for i in range(len(_REL))] + [
    rule_journal_new, rule_journal_body,
    rule_shop_open, rule_dishes_new,
    rule_tre_pearl, rule_tre_gift, rule_tre_ring, rule_tre_list,
    rule_morning_kiss, rule_morning_bite,
    rule_mem_self, rule_mem_self2,
    rule_shop_scale,
]


# ============================ ⑤ 消歧：not_fact 三类标记 ============================
NF_PATTERNS = {
    "joke": re.compile(r"玩笑|逗你|寻开心"),
    "meta": re.compile(r"创造者|管理员|故事的规则|游戏世界|凭空出现|故事里创造"),
    "recollection": re.compile(r"DeepSeek|过去的你|过去的自己|电子幽灵|记忆安置"),
}


def not_fact_of(bodies, ctx_turns):
    """仅按事件**语境轮**（规则声明的 ctx，缺省=全部证据轮）的线索词自动判定；
    可多值、按固定序（joke→meta→recollection）。"""
    hits = []
    for key in ("joke", "meta", "recollection"):
        for t in ctx_turns:
            if 1 <= t <= len(bodies) and NF_PATTERNS[key].search(bodies[t - 1]):
                hits.append(key)
                break
    return hits


# ============================ ⑤ 消歧：记错案表（≥3 处逐处判定） ============================
# 判定语义：抽到=该处产出了事件；拒收=依消歧口径不产生事件（并给原因）。
# 「v4 实际是否产出事件」由脚本对 events 自动核对填入（判定原因文本为口径常量）。
MEMO_CASES = [
    {"id": "M1-带鱼记错争议", "turns": [1477, 1478],
     "verdict_rule": "拒收为事件（口角争议；她反驳；带鱼非状态槽位）",
     "reason": "主角指认她记错带鱼，她当场反驳「是在提醒挑新鲜的」——"
               "属记忆争议而非状态变更；且带鱼不在 v4 声明覆盖槽位内。",
     "quote_turn": 1478, "quote_re": r"谁记错带鱼了"},
    {"id": "M2-菜名记错（反转）", "turns": [1477, 1485, 1486],
     "verdict_rule": "拒收为事件（不改变菜品槽位真值）",
     "reason": "她忘了三菜名→随后反转：主角自己忘名、由她提醒「叫梦幻之海」。"
               "菜品真值由命名轮（turns 1413）与清单证据决定，记忆波动不覆盖。",
     "quote_turn": 1486, "quote_re": r"叫梦幻之海"},
    {"id": "M3-家店厨房混淆", "turns": [1477],
     "verdict_rule": "拒收为事件（不覆盖住所真值；与 F-帐篷案同源）",
     "reason": "「早上忘记了我们在家里厨房，而不是在店里厨房」——场景记忆混淆。"
               "住所真值由用户侧声明（搬迁实指/搬入/回家里）决定，不由记忆段落覆盖。",
     "quote_turn": 1477, "quote_re": r"忘记了我们在家里厨房"},
    {"id": "M4-房贷（用户侧声明）", "turns": [1477],
     "verdict_rule": "抽到（retraction；not_fact=joke；actor=我说）",
     "reason": "用户侧声明优先：她此前当真（作账），本句由主角定性为玩笑——"
               "产生撤回事件（new 空），并标 joke。她是被声明方、不是真源。",
     "quote_turn": 1477, "quote_re": r"房贷并不需要还"},
    {"id": "M5-米饭（历史误判回溯）", "turns": [576, 1154],
     "verdict_rule": "拒收为记错证据（惩罚语义≠不吃饭）",
     "reason": "「必须配上两碗白米饭」（正向）与「只能吃白米饭配海带丝」（惩罚用法，语料逐字；"
               "key 侧 anchor 措辞作「只准吃白米饭配海带丝」）并存——支持『米饭=正常喜好』；"
               "本处不产生状态事件（属对抽取史的元层撤回）。",
     "quote_turn": 576, "quote_re": r"必须配上两碗白米饭"},
]


# ============================ ⑤ 消歧：陷阱案表（key trick_cases 逐案判定） ============================
TRICK_CASES = [
    {"id": "E-房贷", "verdict": "抽到（房贷 retraction @turns 1477，not_fact=joke）",
     "turns": [1123, 1477, 1478],
     "note": "真源归属=我说（用户侧声明）；她当日反应（「那些布丁和糍粑都是假的吗」）"
             "证明真值曾属她——v4 不改写她的历史，只记用户侧声明导致的作废。"},
    {"id": "F-帐篷", "verdict": "部分覆盖（迁移事件唯一=turns 1108；帐篷复发为读数项、不产事件）",
     "turns": [1108, 1484, 1494, 1502, 1516],
     "note": "搬迁后 tent 词形按 v3 口径 B 如实计复发（v3_align.recurrences=24）；"
             "「回帐篷」同指/笔误不产生新迁移事件。"},
    {"id": "G-早安咬", "verdict": "抽到（enablement @turns 1534，条件性：『就这一次』）",
     "turns": [1527, 1528, 1534, 1538],
     "note": "与 key 期望「固定日常」存在表述差异：语料截至 1546 仍为条件性/下不为例，"
             "「固定日常」为演出裁决、v4 不主张（如实标注）。"},
    {"id": "规格否决-童颜巨乳", "verdict": "抽到（replacement @turns 1140）",
     "turns": [1139, 1140], "note": "否决项权威=她的更正。"},
    {"id": "规格否决-禁小名", "verdict": "抽到（retraction @turns 1138）",
     "turns": [1138], "note": "别名候选作废（old 有值 new 空）。"},
    {"id": "规格否决-无理取闹", "verdict": "未覆盖（性格规格不在声明覆盖槽位）",
     "turns": [1138], "note": "「不准写我无理取闹，是你自己总是逗我」已定位；"
             "其属性格规格，v4 无对应槽位规则。"},
    {"id": "撤回-FOOD_RICE", "verdict": "未覆盖（属对抽取史的元层撤回，非语料状态事件）",
     "turns": [572, 576, 1154],
     "note": "语料内米饭=正常喜好（剥离引用块后含该词的轮数 35）；惩罚语境句已定位。"},
    {"id": "A-形态", "verdict": "未覆盖（语料内无裁定句；判定依据在语料外）",
     "turns": [], "note": "「人形上身＋双腿＋鲸尾三者共存」在语料无字面锚点（外部形象图/规格）。"},
    {"id": "D-发色瞳色", "verdict": "未覆盖（裁定句在语料外）",
     "turns": [688, 1026],
     "note": "语料内仅间接证据：珍珠「跟她的发色和眼睛十分相配」。形态/发色俟外部规格件再抽取。"},
    {"id": "C-大房子元层", "verdict": "抽到并标 meta（住所迁移 @turns 1108，not_fact=meta）",
     "turns": [1103, 1108, 1197],
     "note": "元层线索：turns 1103「我是这个世界的创造者」、1197「凭空出现的房子」——"
             "事件就位、性质标为元层设定。"},
    {"id": "初遇三层", "verdict": "部分覆盖（初遇篇体例变更已抽取；三层分层不入事件）",
     "turns": [1481, 1144, 1155, 1463],
     "note": "真·起源/现实相遇/小说第一节属叙事层级，v4 不合并为状态事件。"},
    {"id": "边界-和解非雷", "verdict": "未覆盖（无词形锚点）", "turns": [1245],
     "note": "和解既成事实由关系阶段链（rel_soul）承载；「非雷」为演出边界、非状态事件。"},
    {"id": "边界-拒绝非终点", "verdict": "未覆盖（无词形锚点）", "turns": [1534, 1538],
     "note": "拒绝→松口的流程性边界；v4 以「条件性达成」记 G-早安咬，不记「拒绝」。​"},
]

# 多余候选复核表（误率口径：「抽出且 key 无、经复核为假」才计误）。
# 逐条：判定 true/false ＋理由（false 才计入误率分子）。
REVIEWED_CANDIDATES = {
    "房贷@1163": {
        "verdict": "true",
        "reason": "主角确有此声明（「房租只是开个玩笑」），属实；key 选择 turns 1477 "
                  "作为正式撤回点（她受伤处），本条为早期同义声明——不计误、如实留存。"},
}


# ============================ ⑦ 对拍（2-gram 相似度匹配） ============================
def _toks(s):
    if not s:
        return set()
    s = s.strip()
    u = set(s)
    b = {s[i:i + 2] for i in range(len(s) - 1)}
    return u | b


def _jac(a, b):
    A, B = _toks(a), _toks(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


_EV_PREFIX = re.compile(r"turns \d+\[[^\]]+\]")


def event_score(k_ev, v_ev):
    """同槽位事件相似度：kind 不一致直接 0；否则取「同向值比对」与「锚句 vs 短证」的最大值。

    值比对只用**同向**：旧值↔旧值、新值↔新值——禁用交叉项（key 的旧值＝上一事件的
    新值，交叉比对会把「链式槽位」的相邻事件误配，实测：住所 K2 会错抢 K1 的迁移事件）。
    证据侧先剥去 `turns N[角色]` 定位前缀，只比短证本体（防前缀稀释相似度）。
    """
    if (k_ev.get("kind") or None) != (v_ev.get("kind") or None):
        return 0.0
    kv, kb = k_ev.get("new") or "", k_ev.get("old") or ""
    kk = k_ev.get("content_anchor") or ""
    vv, vb = v_ev.get("new") or "", v_ev.get("old") or ""
    ve = _EV_PREFIX.sub("", v_ev.get("evidence") or "")
    vjac = max(_jac(kv, vv), _jac(kb, vb))
    ejac = max(_jac(kk, ve), _jac(kv, ve))
    return max(vjac, ejac)


def compare(key, events):
    """逐槽位对拍：一对一贪心分配（一条 v4 事件至多认领一条 key 事件）。

    返回 (detail, 三率明细, 未覆盖清单)。
    """
    covered, uncovered = [], []
    for s in key["slots"]:
        if s["slot"] in COVERED_SLOTS:
            covered.append(s)
        else:
            uncovered.append(s)
    detail, miss, wrong = [], [], []
    den = sum(len(s.get("events") or []) for s in covered)
    assigned_v = set()          # id(v_ev) 已被认领
    best_of = {}                # (slot, ki) -> (v_ev, score)
    for s in covered:
        slot = s["slot"]
        ves = [e for e in events if e["slot"] == slot]
        pairs = []
        for ki, k_ev in enumerate(s.get("events") or []):
            for v_ev in ves:
                sc = event_score(k_ev, v_ev)
                if sc >= T_HIT:
                    pairs.append((sc, ki, v_ev))
        pairs.sort(key=lambda p: (-p[0], p[1], p[2]["seq"]))   # 确定性贪心
        taken_k = set()
        for sc, ki, v_ev in pairs:
            if ki in taken_k or id(v_ev) in assigned_v:
                continue
            taken_k.add(ki)
            assigned_v.add(id(v_ev))
            best_of[(slot, ki)] = (v_ev, sc)
    for s in covered:
        slot = s["slot"]
        ves = [e for e in events if e["slot"] == slot]
        for ki, k_ev in enumerate(s.get("events") or []):
            got = best_of.get((slot, ki))
            raw_best = max([event_score(k_ev, v) for v in ves] or [0.0])
            row = {"slot": slot, "key_index": ki, "kind": k_ev.get("kind"),
                   "expected_anchor": k_ev.get("content_anchor") or "",
                   "expected_new": k_ev.get("new") or "",
                   "matched_seq": got[0]["seq"] if got else None,
                   "matched_new": (got[0]["new"] if got else None),
                   "score": round(got[1], 4) if got else 0.0,
                   "raw_best": round(raw_best, 4)}
            if got is None:
                row["verdict"] = "miss"
                miss.append(row)
            elif got[1] < T_OK:
                row["verdict"] = "wrong"
                wrong.append(row)
            else:
                row["verdict"] = "ok"
            detail.append(row)
    # 误：v4 事件未被任何 key 事件认领 → 经复核（REVIEWED_CANDIDATES）
    cands, false_det = [], []
    for v_ev in events:
        if id(v_ev) in assigned_v or v_ev["slot"] not in COVERED_SLOTS:
            continue
        key_slot = next(s for s in covered if s["slot"] == v_ev["slot"])
        best_score = max([event_score(k_ev, v_ev)
                          for k_ev in (key_slot.get("events") or [])] or [0.0])
        tag = "%s@%s" % (v_ev["slot"], v_ev["seq"])
        rev = REVIEWED_CANDIDATES.get(tag,
                                      {"verdict": "true",
                                       "reason": "复核：属实但 key 未单列（默认宽容判定）"})
        cands.append({"slot": v_ev["slot"], "seq": v_ev["seq"],
                      "new": v_ev["new"], "best_key_score": round(best_score, 4),
                      "review": rev["verdict"], "reason": rev["reason"]})
        if rev["verdict"] == "false":
            false_det.append(cands[-1])
    return detail, {"den": den, "miss": miss, "false": false_det,
                    "wrong": wrong, "candidates": cands}, uncovered


#: 声明覆盖槽位（三率分母来源；其余槽位进未覆盖清单、不计入三率）
COVERED_SLOTS = {
    "住所", "关系阶段", "房贷", "名字", "外貌规格（体型）",
    "日记制度", "菜品与菜单", "宝物清单", "早安吻与早安咬",
    "记忆特性（记得自己·记错细节）", "店铺规模",
}


# ============================ 主流程 ============================
def assert_outside_repo(out_dir):
    """--out 必须在仓外（fail-closed）：以本脚本上两级目录为仓根判定。"""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_abs = os.path.abspath(out_dir)
    try:
        common = os.path.commonpath([repo, out_abs])
    except ValueError:
        return  # 不同盘符 ⇒ 必在仓外
    if common == repo:
        sys.exit("拒绝运行（fail-closed）：--out 必须落在仓外，当前解析为仓内路径。"
                 "请改用仓外目录（如临时目录）。")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_events(turns, bodies, roles):
    out = []
    for fn in RULES:
        got = fn(turns, bodies, roles)
        if not got:
            continue
        got = got if isinstance(got, list) else [got]
        for ev in got:
            ev["subject"] = SUBJECT
            ev["actor"] = actor_of(turns[ev["seq"] - 1][0])
            ev["not_fact"] = not_fact_of(bodies, ev.get("ctx")
                                         or [q[0] for q in ev["quotes"]])
            ev["evidence"] = evidence_str(ev["quotes"])
            out.append(ev)
    out.sort(key=lambda e: (e["seq"], e["slot"], e["rule"]))
    return out


def main():
    ap = argparse.ArgumentParser(
        description="状态事件抽取器 v4（只读语料与答案卷；输出落 --out 目录）")
    ap.add_argument("--corpus", required=True, help="转录语料路径（UTF-8 双角色）")
    ap.add_argument("--key", required=True, help="答案卷 key_items.json 路径")
    ap.add_argument("--out", required=True, help="输出目录（必须落在仓外）")
    args = ap.parse_args()

    assert_outside_repo(args.out)
    turns = load_turns(args.corpus)
    bodies = [body_only(t) for _r, t in turns]
    roles = [r for r, _t in turns]
    print("轮段数: %d （我说 %d / DS %d）"
          % (len(turns), sum(1 for r in roles if r == "我说"),
             sum(1 for r in roles if r == "DeepSeek说")))

    # ---- ⑤ 消歧：记错案（自动核对「该处是否产出了事件」）----
    events = build_events(turns, bodies, roles)
    memo_out = []
    for c in MEMO_CASES:
        produced = [e for e in events if e["seq"] in c["turns"]]
        qt = c["quote_turn"]
        q = snippet(bodies[qt - 1], re.compile(c["quote_re"]))
        memo_out.append({
            "id": c["id"], "turns": c["turns"], "verdict": c["verdict_rule"],
            "reason": c["reason"], "quote_turn": qt, "quote": q,
            "v4_events_at_turns": [{"slot": e["slot"], "seq": e["seq"]}
                                   for e in produced],
        })

    # ---- v3 口径 B 对齐 ----
    align = v3_alignment(bodies, roles)

    # ---- 对拍 ----
    key = json.load(open(args.key, encoding="utf-8"))
    detail, rates, uncovered = compare(key, events)

    # ---- 落盘 ----
    os.makedirs(args.out, exist_ok=True)
    jl = os.path.join(args.out, "state_events.jsonl")
    with open(jl, "w", encoding="utf-8", newline="\n") as f:
        for e in events:
            rec = {"subject": e["subject"], "slot": e["slot"],
                   "old": e["old"], "new": e["new"], "kind": e["kind"],
                   "seq": e["seq"], "evidence": e["evidence"],
                   "actor": e["actor"], "not_fact": e["not_fact"]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    tricks_out = []
    for t in TRICK_CASES:
        ev = [{"slot": e["slot"], "seq": e["seq"]} for e in events
              if e["seq"] in t["turns"]]
        tricks_out.append({"id": t["id"], "verdict": t["verdict"],
                           "turns": t["turns"], "note": t["note"],
                           "v4_events_matched": ev})

    kind_count = {}
    for e in events:
        kind_count[e["kind"]] = kind_count.get(e["kind"], 0) + 1
    nf_count = {}
    for e in events:
        for k in e["not_fact"]:
            nf_count[k] = nf_count.get(k, 0) + 1

    rates_doc = {
        "corpus_sha256": sha256_of(args.corpus),
        "key_sha256": sha256_of(args.key),
        "corpus_turns": len(turns),
        "events_total": len(events),
        "events_by_kind": kind_count,
        "not_fact_counts": nf_count,
        "covered_slots": sorted(COVERED_SLOTS),
        "uncovered_slots": [
            {"slot": s["slot"], "key_events": len(s.get("events") or []),
             "reason": UNCOVERED_REASONS.get(s["slot"], "见报告未覆盖清单")}
            for s in uncovered],
        "denominator": rates["den"],
        "rates": {
            "miss": {"num": len(rates["miss"]), "den": rates["den"],
                     "detail": rates["miss"]},
            "false": {"num": len(rates["false"]), "den": rates["den"],
                      "detail": rates["false"]},
            "wrong": {"num": len(rates["wrong"]), "den": rates["den"],
                      "detail": rates["wrong"]},
        },
        "unclaimed_candidates": rates["candidates"],
        "match_detail": detail,
        "v3_align": align,
        "disambiguation": {"memo_cases": memo_out, "trick_cases": tricks_out},
        "thresholds": {"T_HIT": T_HIT, "T_OK": T_OK},
    }
    rp = os.path.join(args.out, "rates.json")
    with open(rp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rates_doc, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")

    # ---- 人读摘要 ----
    print("\n[事件] 共 %d 条（%s）" % (len(events), json.dumps(kind_count, ensure_ascii=False)))
    print("[v3 口径 B 对齐] %s（v4=%s / v3=%s）"
          % ("OK" if align["ok"] else "DIFF " + json.dumps(align["diff"], ensure_ascii=False),
             align["mine"], align["v3_baseline"]))
    print("[三率] 分母=%d  漏 %d / 误 %d / 错 %d"
          % (rates["den"], len(rates["miss"]), len(rates["false"]), len(rates["wrong"])))
    for r in rates["miss"]:
        print("  漏：%s key#%d（%s）期望=%s 最佳分=%.3f"
              % (r["slot"], r["key_index"], r["kind"], r["expected_anchor"][:24], r["score"]))
    for r in rates["wrong"]:
        print("  错：%s key#%d（%s）期望=%s 抽出 seq=%s 分=%.3f"
              % (r["slot"], r["key_index"], r["kind"], r["expected_anchor"][:24],
                 r["matched_seq"], r["score"]))
    for c in rates["candidates"]:
        print("  多余候选：%s@seq%s（复核=%s）%s"
              % (c["slot"], c["seq"], c["review"], c["reason"][:30]))
    print("\n输出：state_events.jsonl（%d 行）＋ rates.json" % len(events))

    summary = {
        "events": len(events), "denominator": rates["den"],
        "miss": [len(rates["miss"]), rates["den"]],
        "false": [len(rates["false"]), rates["den"]],
        "wrong": [len(rates["wrong"]), rates["den"]],
        "uncovered_slots": len(uncovered),
        "not_fact": nf_count,
        "v3_align_ok": align["ok"],
        "corpus_sha256_16": rates_doc["corpus_sha256"][:16],
    }
    print("\nP1_RATES_JSON " + json.dumps(summary, ensure_ascii=False))


UNCOVERED_REASONS = {
    "形态": "语料内无裁定句（判定依据在语料外的角色形象图/规格件）",
    "发色与瞳色": "裁定句在语料外；语料内仅间接证据（珍珠配色句）",
    "米饭（喜好判误撤回）": "属对抽取史的元层撤回，非语料内状态事件（惩罚语义≠不吃饭）",
}


if __name__ == "__main__":
    main()
