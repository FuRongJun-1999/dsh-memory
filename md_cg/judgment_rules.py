# -*- coding: utf-8 -*-
r"""判据规则表 J1–J11（E-T18a 蓝图 t1）——**写入侧前置判定的唯一真源**。

## 这个模块是什么

把 `D:\wook\目标清单.md:382-408` 的 J1–J11 判据从**散文**落成**机器可判的规则表**：
输入一段对话事件（来源方 role / 文本 text / 实体 / 是否被引用信号），输出**三态之一**：

    KEEP      留        —— J1–J6
    DROP      丢        —— J7–J10
    KEEP_LIFE 留但定寿  —— J11（寿命交给引用次数）

三态是**互斥且穷尽**的：任何输入必落其一，绝不返回 None 或空判。

## 判据分组（逐条对应目标清单原文）

留（J1–J6）：
  J1 用户的性格、语气、习惯、命令方式
  J2 助手正在长成的性格
  J3 两人的相处方式
  J4 项目架构、技术结论、踩过的坑
  J5 可复用的东西（脚本、路径、做法）
  J6 能长期成立的事实（长期偏好、环境、底线）

丢（J7–J10）：
  J7 一次性的需求与交代本身
  J8 讨论过程（选项、取舍、来回商量）
  J9 噪声（工具日志、重复、系统上下文）
  J10 会随时间自动失效的（当时状态、临时设计方案）

留但定寿（J11）：
  J11 寿命交给引用次数——没人再提就沉底直到忘，反复提起就留住

## 判定次序（**先丢后留**，次序本身是判据的一部分）

    ① J9 噪声 → ② J7 一次性需求 → ③ J8 讨论过程 → ④ J11 引用计数寿命
    → ⑤ J10 时效性 → ⑥ J1–J6 留

为什么 J11 排在 J10 **前面**：一条消息可能同时命中两者——「这个临时方案
先记着」既含 J10 的「临时方案」时效信号、又含 J11 的「先记着」寿命信号。
后者的语义是「预留给将来引用」，比「随时间的临时性」更值得留（留但定寿），
故 J11 先判；只有**没有**寿命信号、纯是临时设计的正文才落 J10 丢。

为什么「丢」的判据排在「留」的前面：一条消息可以**同时**命中两侧——例如
「今天把 report.pdf 生成一下，我主力语言是 Python」既含 J7 的一次性交代、
又含 J1/J6 的长期偏好。若先判「留」就会因为有偏好词而**整条留下**，把一次性
交代一并拖进记忆库。先判「丢」也同样不对（会丢掉真偏好）。故本模块的实际口径是
**分句判定 + 取最高优先级**：逐句判定，任一句命中更高优先级的类别即取该类别；
同优先级内「丢」胜过「留」；只有当**所有**句子都只命中「留」时才返回 KEEP。
混合句因此按「一次性交代」丢——**这是有意的**：一次性交代的正文含长期偏好时，
该偏好会在**其它**轮次被单独说出，届时自会留下；宁可漏留一条，不可把临时交代
沉淀成长期记忆（写入侧过滤器的成本不对称：错留的代价是持久污染，错丢的代价
只是少记一条、下次还会再说）。

## 为什么是规则表而不是模型

判据要**机器可判**：同输入必同输出、可枚举、可回归、无网络、无随机。故全部
判据落成**词表 + 结构信号**，每条规则都带 `evidence`（命中的具体词/信号），
让「为什么这么判」可复现、可 grep、可断言——而不是一个黑箱分数。

规则表数据在 `RULES`，判定实现在 `judge_event`。改判据只改 `RULES`。
唯一例外：J9 的**重复噪声**（同类句重复 / 同句 CJK 立即重复）由 `judge_text`
的 `_dup_noise_of` 判定（E-T11a t1 新增来源——只加这一个 J9 来源，
`_PRIORITY` 与其余判据判定均未动）。

## 引用信号与 J11

J11 的「引用次数」由上游提供：`judge_event(..., ref_signals=...)`。无信号时
J11 不生效（回落 J1–J6 判 KEEP）——因为**寿命是事后属性**，一条刚说的话还没
被引用过，不能凭「像是会被引用」就预先定寿。有引用信号时：

    ref_count == 0 且命中寿命类信号  → KEEP_LIFE（引用计数=0，沉底起点）
    ref_count == 0 但**无**寿命信号  → KEEP（普通留，走 J1–J6）
    ref_count  > 0                  → KEEP_LIFE（已被反复提起，留住但继续计数）

三种都返回 KEEP_LIFE 时给出 `lifetime` 子结构（见 `_lifetime_of`），写入侧据此
在 frontmatter 打寿命标记，`retain.retain_verdict` 的 `access_count` 语义可直接消费。

## 接线

`mdcg.MdCG.add` / `mdcg.MdCG.remember_event` 的写入路径**前置短路**调用本模块：
判 `DROP` 即拒写、判 `KEEP_LIFE` 即打引用计数寿命标记。开关默认**关闭**
（`MDCG_JUDGMENT=1|true|on|yes|enable` 显式开启）——默认关 = 写入行为与
接线前**逐字节一致**（存量回归把 DROP 类输入当合法用例写入，测试文件不可改；
E-T31a 关闭回归同样锁「未设=关」契约）；显式开启才引入判定。接线判定
**只按正文内容**（role 一律 None）——role 是 fm/index 元数据不是判据，
command/tool-output 事件照常写入，噪声判定靠内容词表与结构信号。
"""

from __future__ import annotations

import os
import re

__all__ = [
    "KEEP", "DROP", "KEEP_LIFE", "STATES",
    "RULES", "LIFETIME_FIELD", "REF_COUNT_FIELD", "STATE_FIELD",
    "WHY_KEPT_FIELD",
    "ENABLE_VALUES", "ENV_FLAG",
    "judge_event", "judge_text", "is_enabled", "lifetime_mark_of",
    "should_write", "explain", "why_kept_of",
    "split_keep_parts",
]

# ---------------------------------------------------------------------------
# 三态
# ---------------------------------------------------------------------------

KEEP = "keep"              # J1–J6   留
DROP = "drop"              # J7–J10  丢
KEEP_LIFE = "keep_life"    # J11     留但定寿

#: 三态全集（互斥且穷尽；判定函数的返回值必在此内）。
STATES = (KEEP, DROP, KEEP_LIFE)

#: 写入侧落 frontmatter 的寿命标记字段（J11 的载体）。
LIFETIME_FIELD = "judgment_lifetime"
#: 写入侧落 frontmatter 的引用计数快照字段（复用 retain 的 access_count 语义）。
REF_COUNT_FIELD = "judgment_ref_count"
#: 写入侧落 frontmatter 的判定结论字段（三态可回溯）。
STATE_FIELD = "judgment_state"

#: E-T31a t1：写入侧落 frontmatter/meta 的「为什么留下这条」判断理由字段。
#: 内容来自判定 verdict 的命中规则/evidence（AI 自判，不靠用户标注），
#: KEEP 与 KEEP_LIFE 均带；DROP 不落（拒写无节点可附）。
WHY_KEPT_FIELD = "why_kept"

#: 开关：`MDCG_JUDGMENT` **未设一律关闭**（默认关=与接线前逐字节一致，存量
#: 回归与 E-T31a 关闭回归都锁此契约）；显式取 ENABLE_VALUES 之一（大小写不
#: 敏感）才开启；其它取值一律关闭。判定面本身 fail-open（坏形状放行写入）。
ENABLE_VALUES = ("1", "true", "on", "yes", "enable")
ENV_FLAG = "MDCG_JUDGMENT"


# ---------------------------------------------------------------------------
# 规则表数据
# ---------------------------------------------------------------------------
# 每类判据一条规则：词表（命中即计数）+ 结构性信号（正则）。全部命中都记进
# evidence，让判定可复现。词表刻意保持**窄**（宁可漏判不可误判）：写入侧过滤器
# 的错判代价不对称——错留污染长期记忆，错丢只是少记一条（下次还会再说）。

RULES = {
    # ---------------- 留（J1–J6） ----------------
    "J1": {
        "state": KEEP,
        "title": "用户的性格、语气、习惯、命令方式",
        "terms": (
            "我主力语言", "我的习惯", "我习惯", "我的偏好", "我偏好",
            "我喜欢", "我讨厌", "我受不了", "我一般", "我通常",
            "我要求", "我的要求", "我的原则", "我的风格", "别给我",
            "不要给我", "直接说", "少废话", "命令方式", "我的底线",
        ),
        "patterns": (
            r"我(?:一直|从来|总是|通常|一般)(?:都)?[喜欢讨厌习惯用]",
            r"以后(?:都|一律|全部)",
        ),
    },
    "J2": {
        "state": KEEP,
        "title": "助手正在长成的性格",
        "terms": (
            "你的性格", "你的风格", "你的语气", "你的习惯", "你应该",
            "你要记住", "助手要", "你以后", "你以后都", "你要一直",
            "你的判断", "你的原则",
        ),
        "patterns": (
            r"你(?:以后|今后|下次)(?:都|要|别)",
            r"你(?:的)?(?:性格|风格|语气|原则)是",
        ),
    },
    "J3": {
        "state": KEEP,
        "title": "两人的相处方式",
        "terms": (
            "我们俩", "我们之间", "咱俩", "我们的相处", "我们的约定",
            "我们说好", "我们的默契", "我们的分工", "以后我们",
        ),
        "patterns": (
            r"我们(?:说好|约定|讲好|商量好)",
            r"(?:咱俩|我们俩)(?:以后|之间|的默契)",
        ),
    },
    "J4": {
        "state": KEEP,
        "title": "项目架构、技术结论、踩过的坑",
        "terms": (
            "架构", "技术结论", "踩过的坑", "踩了坑", "坑在于", "结论是",
            "根因", "定位到", "报错原文", "因为", "原因是", "根因是",
            "设计决策", "选型", "落点", "唯一真源", "入口是",
            "模块", "接口", "签名", "接线点",
        ),
        "patterns": (
            r"(?:根因|原因|结论)(?:是|在于|为)",
            r"(?:踩|掉)(?:过|进)?(?:了)?坑",
            r"\w+\.py(?::\d+(?:-\d+)?)?",          # 文件:行号 = 技术结论的指纹
            r"报错|异常|Traceback|Error:",
        ),
    },
    "J5": {
        "state": KEEP,
        "title": "可复用的东西（脚本、路径、做法）",
        "terms": (
            "脚本", "路径", "做法", "流程", "命令是", "用法", "复用",
            "模板", "工具", "入口", "跑法", "怎么跑", "步骤",
        ),
        "patterns": (
            r"[A-Za-z]:\\[^\s，。；]+",              # Windows 绝对路径
            r"python\s+\S+\.py",                     # 可复跑的命令行
            r"(?:脚本|路径|做法|流程)(?:在|是|为)",
        ),
    },
    "J6": {
        "state": KEEP,
        "title": "能长期成立的事实（长期偏好、环境、底线）",
        "terms": (
            "长期", "一直", "永远", "从来", "底线", "红线", "禁止",
            "不准", "不许", "环境是", "本机", "这台机器", "固定",
            "默认", "以后都", "长期有效", "不允许",
        ),
        "patterns": (
            r"(?:长期|永久|一直)(?:有效|成立|如此|这样)",
            r"(?:禁止|不许|不准|绝不)",
            r"这(?:台|个)机器(?:上|是)",
        ),
    },
    # ---------------- 丢（J7–J10） ----------------
    "J7": {
        "state": DROP,
        "title": "一次性的需求与交代本身",
        "terms": (
            "今天把", "现在把",
            "生成一下", "跑一下", "改一下", "看一下",
            "查一下", "写一下", "做一下",
            # E-T09a t1：补「需求句柄」漏网面——祈使动词（生成/导出/发/修复/
            # 清理/封装/整理）+ 给/帮/提醒 句式。词表刻意保持**不带宾语的空壳
            # 句柄**（如「给我生成」「提醒我」），这样留/丢两侧同时出现时由
            # 「分句 + 取最高优先级、丢胜过留」自动判丢（见模块头）；而
            # 「我的生日是…」「我主力语言是…」这类**陈述钉存**句不含任何需求
            # 动词，故不误伤（实测落 J6 兜底留）。
            "给我生成", "给我发", "给我整理", "给我来一份",
            "帮我生成", "帮我导", "帮我封装", "帮我整理", "帮我打包",
            "把数据导", "导出来给我", "导出来发",
            "修复一下", "清理一下", "封装一下",
            "提醒我", "提醒一下我",
        ),
        "patterns": (
            r"(?:帮|给)我\S{0,8}(?:一下|下|个)",
            r"(?:今天|现在|马上|立刻|这次|本轮)(?:把|帮我|给我|跑|做|写|改|生成)",
            r"\S+\.(?:pdf|docx|xlsx|pptx|csv|txt|png|jpg)(?:\s|$|，|。)",
            # E-T09a t1：需求句柄的结构信号（与上方 terms 同口径，见那里的注释）。
            r"(?:帮我|给我|替我|请帮|麻烦)(?:生成|导|发|发一份|做|写|改|查|修|清理|整理|封装|打包|跑|来一份|出一份)",
            r"提醒(?:我|一下我)",
            r"需要你\S{0,6}(?:生成|导|写|做|改|查|整理|封装|修复|清理|发)",
            r"把\S{1,14}?(?:导出来给我|修复一下|清理一下|导出|删掉|清掉|关掉)",
        ),
    },
    "J8": {
        "state": DROP,
        "title": "讨论过程（选项、取舍、来回商量）",
        "terms": (
            "要不要", "该不该", "权衡", "取舍", "商量", "讨论",
            "两种方案", "倾向于",
        ),
        "patterns": (
            r"(?:A|甲)\s*(?:还是|或)\s*(?:B|乙)",
            r"(?:方案|选项)\s*(?:一|二|1|2|甲|乙)",
            r"(?:要不要|该不该)\S{0,10}[？?]",
        ),
    },
    "J9": {
        "state": DROP,
        "title": "噪声（工具日志、重复、系统上下文）",
        "terms": (
            "stdout", "stderr", "exit code", "system-reminder",
            "tool-output", "[exit code", "已压缩", "上下文状态",
            # E-T11a t1：收紧噪声门槛——工具日志形态 / 系统上下文引用块。
            # 词/短语刻意取**完整日志原文**（窄）：npm/pip 输出行、Python 栈帧
            # 头、框架注入文本的固定字面量——这类串只出现在工具回显里，不会
            # 出现在用户正经陈述中，故判丢不误伤（对照样本实测仍 keep）。
            "npm error code",
            "Traceback (most recent call last)",
            "Collecting xyz",
            "Downloading xyz",
            "Instructions from:",
            "file access denied",
        ),
        "patterns": (
            r"(?:File|at)\s+\"[^\"]+\",\s+line\s+\d+",       # Python/Rust 栈帧
            r"^\s*(?:\$ |PS\s+[A-Z]:\\)",                    # shell 提示符回显
            r"\[(?:exit code|sandbox|acp|Compressed)\b",     # 框架注入标记
            r"<[a-z-]+(?:\s[^>]*)?>.*?</[a-z-]+>",           # 系统上下文标签块
            r"(?:PASS|FAIL|SUMMARY)\s+\d+/\d+",              # 测试汇总噪声
            # E-T11a t1：npm install 汇总行（added 123 packages 的数字不固定，
            # 用数字通配；其余字面量照抄日志原文）。
            r"added \d+ packages",
            # E-T11a t1：管道捕获标记的**方括号**形态（[stdout]/[stderr] 是
            # 回显标志，不是对话正文）。
            r"\[(?:stderr|stdout)\]",
            # E-T11a t1：ACP 标签的**开标签**（<acp tokens=… type=text> 常
            # 不成对出现，标签块正则要求闭合故补此条；</acp> 闭合不含 <acp\b
            # 不会被误吞）。
            r"<acp\b[^>]*>",
        ),
    },
    "J10": {
        "state": DROP,
        "title": "会随时间自动失效的（当时状态、临时设计方案）",
        "terms": (
            "先这样", "凑合", "等会儿", "过会儿",
            "目前状态", "当前状态", "待定", "暂定", "回头再说",
        ),
        "patterns": (
            r"(?:临时|暂时|暂定)(?:方案|办法|设计|这样|先)",
            r"(?:目前|当前|现在)(?:状态|情况)(?:是|为)",
        ),
    },
    # ---------------- 留但定寿（J11） ----------------
    "J11": {
        "state": KEEP_LIFE,
        "title": "寿命交给引用次数",
        "terms": (
            "先记着", "先存着", "以后备用", "待验证", "留着", "回头再用",
        ),
        "patterns": (
            r"(?:先|暂时)(?:记|存|留)(?:着|下|住)",
            r"(?:以后|回头)(?:可能|也许|如果)(?:用|需要)得?[到着上]?",
        ),
    },
}


# ---------------------------------------------------------------------------
# 判定实现
# ---------------------------------------------------------------------------

#: 判据优先级（**丢在前、留在后**；J11 排在 J10 **前面**——「临时方案先记着」
#: 这类既含时效、又含「预留给引用」的信号按留但定寿处理）。次序即口径，见模块头。
_PRIORITY = ("J9", "J7", "J8", "J11", "J10", "J1", "J2", "J3", "J4", "J5", "J6")

#: 分句：中文/英文句读 + 换行都算边界。分句是「混合句取最高优先级」的前提。
_SPLIT_RE = re.compile(r"[。！？!?；;\n\r]+")

#: 重复噪声（E-T11a t1，J9 的**新增来源**）——同一句内相邻 2 个 CJK 字符**立即
#: 完全重复**（'收到收到' / '好的好的'：双字词原样回显两遍）。只认 2 字单位、
#: 只认相邻、只认 CJK——'收到，收到'（句读分隔的强调）、'明明白白'（叠字成语）、
#: '哈哈哈'（3 字拟声）、英文 'okok' / 十六进制 'abab' 一律不误伤；宁可漏判。
_CJK_REPEAT_RE = re.compile(r"([\u4e00-\u9fff]{2})\1")


# 生效条件：按 _SPLIT_RE 分句后，任一非空句子在全文出现 ≥2 次（同类句重复，
# 如 '这个项目是 wook。这个项目是 wook。'），或任一非空句内含 _CJK_REPEAT_RE
# 的立即重复单位——两种情况都返回非空 evidence 列表（含原文片段，可回溯），
# 否则返回 []。它是 J9 噪声的**一个**新增来源：只追加 J9 命中，不改 _PRIORITY
# 与任何既有规则判定（J9 排在 _PRIORITY 首位，命中即丢胜过留）。
def _dup_noise_of(text) -> list:
    """重复噪声判定（J9 新增来源）：同类句重复 / 同句 CJK 立即重复。"""
    sents = _sentences(text)
    ev = []
    if len(sents) >= 2:
        seen = {}
        for s in sents:
            seen[s] = seen.get(s, 0) + 1
        for s, n in seen.items():
            if n >= 2 and len(s) >= 2:
                ev.append("dup-sentence×%d:%s" % (n, s[:40]))
    for s in sents:
        m = _CJK_REPEAT_RE.search(s)
        if m:
            ev.append("dup-cjk:%s" % m.group(0)[:40])
    return ev


# 生效条件：text 为假值时返回 []；否则按句读/换行切分，逐段 strip 后丢弃空段，
# 返回非空片段列表（保持原序）。
def _sentences(text) -> list:
    """把一段文本切成句子（判定以句子为单位，见模块头的混合句口径）。"""
    if not text:
        return []
    return [s.strip() for s in _SPLIT_RE.split(str(text)) if s.strip()]


# 生效条件：对单句逐条规则取词表命中（子串，大小写不敏感）与正则命中，返回按
# _PRIORITY 次序排列的命中列表 [(判据名, evidence 列表)]；无命中返回 []。
def _hits_of(sentence: str) -> list:
    """对**单个句子**跑一遍全规则表，返回按优先级排序的命中。"""
    low = sentence.lower()
    out = []
    for jid in _PRIORITY:
        rule = RULES[jid]
        ev = []
        for term in rule["terms"]:
            if term.lower() in low:
                ev.append(term)
        for pat in rule["patterns"]:
            try:
                m = re.search(pat, sentence, re.IGNORECASE | re.MULTILINE)
            except re.error:
                continue
            if m:
                ev.append(m.group(0)[:60])
        if ev:
            out.append((jid, ev))
    return out


# 生效条件：ref_signals 为 None/非 dict 时恒返回 None（无信号 = J11 不生效）；
# 否则取 ref_count（缺键回落 0，非数回落 0）与 cited（假值回落 False），
# 返回 (ref_count:int, cited:bool) 二元组。
def _read_ref_signals(ref_signals):
    """归一引用信号：无信号 → None；有信号 → (ref_count, cited)。"""
    if not isinstance(ref_signals, dict):
        return None
    try:
        n = int(ref_signals.get("ref_count") or 0)
    except (TypeError, ValueError):
        n = 0
    if n < 0:
        n = 0
    return n, bool(ref_signals.get("cited"))


# 生效条件：ref_count 为 0 时返回 {"ref_count":0,"policy":"ref_count_zero",
# "why":含「引用计数=0」与沉底语义的串}；ref_count>0 时返回
# {"ref_count":n,"policy":"ref_count_positive","why":含「反复提起」与留住语义的串}。
def _lifetime_of(ref_count: int, cited: bool) -> dict:
    """J11 的寿命子结构——写入侧据此打 frontmatter 标记。

    `policy` 是**机器可判的关键字**（测试与下游 grep 它，不解析 why 散文）：
      ref_count_zero     —— 引用计数=0：沉底起点，没人再提就往遗忘走；
      ref_count_positive —— 引用计数>0：反复提起，留住并继续计数。
    """
    n = int(ref_count)
    if n <= 0:
        return {
            "ref_count": 0,
            "cited": bool(cited),
            "policy": "ref_count_zero",
            "why": "J11 引用计数=0：沉底起点——没人再提就一路沉到忘",
        }
    return {
        "ref_count": n,
        "cited": bool(cited),
        "policy": "ref_count_positive",
        "why": "J11 引用计数=%d：已被反复提起，留住并继续计数" % n,
    }


# 生效条件：返回三态之一的结论 dict——键 state 必在 STATES 内；命中的判据名在
# judge；evidence 为命中的词/正则原文列表（**永远非空**，命中不到任何规则时
# 是兜底 J6）；ref_signals 给出时附 lifetime 子结构（仅 KEEP_LIFE 时非 None）。
# 混合句（同句/多句命中不同类）按 _PRIORITY 取最高优先级——丢胜过留。
def judge_text(text, role=None, entities=None, ref_signals=None) -> dict:
    """判据规则表 J1–J11 的**核心判定**：文本 → 三态结论。

    参数：
        text        —— 待判文本（必填；假值按 J9 噪声丢）。
        role        —— 来源方 role。`tool-output` / `command` 结构性判 J9 噪声
                       （工具日志不属于对话内容，无论正文写了什么）；其余 role
                       不吃特殊待遇，逐句判。
        entities    —— 实体列表。给出实体时，含实体的句子额外标 J4/J5 的可复用
                       信号（实体 = 可指名回溯的东西）。
        ref_signals —— 引用信号 dict，形如 {"ref_count": 3, "cited": True}。
                       **None = 无信号 = J11 不生效**（寿命是事后属性，不能凭
                       「像是会被引用」预先定寿，见模块头）。

    返回 dict：
        state     —— KEEP / DROP / KEEP_LIFE 之一（必在 STATES 内）
        judge     —— 主导判据名（J1…J11）
        state_of  —— {判据名: 三态} 全命中映射（可回溯每条判据的落点）
        evidence  —— list[str]，命中的词/正则原文（**永远非空**）
        lifetime  —— J11 子结构（非 KEEP_LIFE 时为 None）
    """
    text_s = "" if text is None else str(text)
    role_s = str(role or "").strip().lower()
    ref = _read_ref_signals(ref_signals)

    # ① role 结构性判噪声（J9）：工具面产出不是对话，无论正文写了什么。
    # 为什么放在最前：工具输出里常常**内嵌**用户/助手原文（回显、日志引用），
    # 逐句判会让那些内嵌原文把日志整条捞成「留」——role 是比正文更硬的信号。
    if role_s in ("tool-output", "tool_output", "command", "tool"):
        return {
            "state": DROP,
            "judge": "J9",
            "state_of": {"J9": DROP},
            "evidence": ["role:%s" % role_s],
            "lifetime": None,
        }

    ents = [str(e) for e in (entities or []) if str(e).strip()]

    # ② 逐句跑全表，收集每句的最高优先级命中。
    per_sentence = []          # [(句子, 判据名, evidence)]
    for s in _sentences(text_s):
        hits = _hits_of(s)
        if not hits and ents and any(e in s for e in ents):
            # 句子本身没命中词表、但含已知实体 → 实体即「可指名回溯的东西」，
            # 按 J5 可复用信号留（实体是比词表更硬的证据）。
            hits = [("J5", ["entity:" + next(e for e in ents if e in s)])]
        if hits:
            per_sentence.append((s, hits[0][0], hits[0][1]))

    # ②½ E-T11a t1：重复噪声（J9 新增来源）——同类句重复 / 同句 CJK 立即
    #    重复，追加一条 J9 命中。不改 _PRIORITY 与任何既有规则判定：J9 本就在
    #    优先级首位，命中即「丢胜过留」自动接管（含与 J1 类的混合文本）。
    _dup_ev = _dup_noise_of(text_s)
    if _dup_ev:
        per_sentence.append(("<repeat>", "J9", _dup_ev))

    # ③ 取全场最高优先级判据（_PRIORITY 序即优先级；丢在前 ⇒ 混合句判丢）。
    best_j, best_ev = None, []
    for _s, jid, ev in per_sentence:
        if best_j is None or _PRIORITY.index(jid) < _PRIORITY.index(best_j):
            best_j, best_ev = jid, list(ev)
        elif jid == best_j:
            best_ev.extend(ev)

    # ④ 空文本 / 全无命中：空文本判 J9 噪声丢；有内容但命中不到任何规则时
    # **兜底判留**（J6）——判据表是**过滤器**不是门禁，宁可多留一条让下游
    # 生命周期面去沉底，不可因为词表没用上就静默丢掉用户的话。
    if best_j is None:
        if not _sentences(text_s):
            return {"state": DROP, "judge": "J9", "state_of": {"J9": DROP},
                    "evidence": ["empty-text"], "lifetime": None}
        best_j, best_ev = "J6", ["fallback:no-rule-hit"]

    if RULES[best_j]["state"] == DROP:
        return {"state": DROP, "judge": best_j, "state_of": {best_j: DROP},
                "evidence": best_ev or [best_j], "lifetime": None}

    # ⑤ J11：命中寿命信号，或**已有引用计数**（ref_count>0 = 已被反复提起）。
    # 有引用信号才生效；无信号时 J11 不生效（回落 KEEP），见模块头。
    life_hit = (best_j == "J11")
    if ref is not None and (life_hit or ref[0] > 0):
        life = _lifetime_of(ref[0], ref[1])
        jid = "J11" if life_hit else best_j
        return {"state": KEEP_LIFE, "judge": "J11", "state_of": {jid: KEEP_LIFE},
                "evidence": (best_ev if life_hit else []) or
                            ["ref_count=%d" % ref[0]],
                "lifetime": life}

    # ⑥ KEEP（J1–J6）。J11 命中但**无**引用信号 ⇒ 回落普通留（寿命未定，
    # 不能凭空定寿）。
    if life_hit:
        return {"state": KEEP, "judge": "J6", "state_of": {best_j: KEEP},
                "evidence": best_ev, "lifetime": None}
    return {"state": RULES[best_j]["state"], "judge": best_j,
            "state_of": {best_j: RULES[best_j]["state"]},
            "evidence": best_ev, "lifetime": None}


# 生效条件：接受一对一整条**对话事件**（dict 或关键字），归一 role/text/entities/
# ref_signals 后转调 judge_text；event 为 dict 时按 role/text/entities/ref_signals
# 取键（缺失即 None），非 dict 时按关键字取。返回同 judge_text。
def judge_event(event=None, *, role=None, text=None, entities=None,
                ref_signals=None) -> dict:
    """判据规则表对**一段对话事件**的入口（mdcg 接线调它）。

    event 形如 `{"role": "user", "text": "…", "entities": […],
    "ref_signals": {"ref_count": 0}}`。显式关键字优先于 event 内同名键。
    """
    if isinstance(event, dict):
        role = role if role is not None else event.get("role")
        text = text if text is not None else event.get("text")
        entities = entities if entities is not None else event.get("entities")
        if ref_signals is None:
            ref_signals = event.get("ref_signals")
    return judge_text(text, role=role, entities=entities,
                      ref_signals=ref_signals)


# 生效条件：MDCG_JUDGMENT 未设时返回 False（默认**关闭**——与接线前行为逐字节
# 一致，存量回归 & E-T31a 关闭回归都锁此契约）；取值 ∈ ENABLE_VALUES（大小写
# 不敏感，即 "1"/"true"/"on"/"yes"/"enable"）返回 True（显式开启）；其它一律 False。
def is_enabled() -> bool:
    """写入侧过滤器的总开关（默认**关闭**；`MDCG_JUDGMENT=1` 显式开启）。"""
    v = os.environ.get(ENV_FLAG)
    if v is None:
        return False
    return str(v).strip().lower() in ENABLE_VALUES


# 生效条件：verdict 是 dict 且其 state 为 KEEP_LIFE 时返回 verdict["lifetime"]
# （缺键回落 None）；其余一律返回 None。
def lifetime_mark_of(verdict) -> dict:
    """从判定结论里取 J11 的寿命标记（非 KEEP_LIFE 返回 None）。"""
    if isinstance(verdict, dict) and verdict.get("state") == KEEP_LIFE:
        life = verdict.get("lifetime")
        return life if isinstance(life, dict) else None
    return None


# 生效条件：verdict 非 dict 时返回 True（**坏形状放行**——判定面故障不得堵死写入）；
# 否则返回 verdict.get("state") != DROP（KEEP 与 KEEP_LIFE 都放行）。
def should_write(verdict) -> bool:
    """写入侧的唯一裁决：**只有 DROP 拒写**，KEEP/KEEP_LIFE 都放行。

    坏形状（None/非 dict）放行——判定面自己出故障时必须**默认允许**，否则
    一个词表 typo 就会静默堵死整条写入路径（fail-open 是有意的，与 node_id
    校验那种 fail-closed 相反：那是防止**污染**，这是防止**误伤**）。
    """
    if not isinstance(verdict, dict):
        return True
    return verdict.get("state") != DROP


# 生效条件：返回一条可读的判定说明串——含三态、判据名、首条证据与（KEEP_LIFE
# 时）寿命 why；verdict 非 dict 时返回「坏形状（放行）」串。
def explain(verdict) -> str:
    """把判定结论渲染成一行可读说明（调试/审计用，机器判据请读 state 键）。"""
    if not isinstance(verdict, dict):
        return "判定面坏形状（放行）"
    ev = verdict.get("evidence") or []
    head = "%s ← %s" % (verdict.get("state"), verdict.get("judge"))
    if ev:
        head += "（证据：%s）" % ev[0]
    life = lifetime_mark_of(verdict)
    if life:
        head += "｜" + life.get("why", "")
    return head


# 生效条件：verdict 非 dict 时返回空串（坏形状/未判）；state 为 DROP 或空串
# 时返回空串；否则返回「J<n> <规则标题>（证据：…）」非空串——判据名取自
# verdict["judge"]（兜底缺键取 state_of 内首个键），规则标题取自 RULES，
# 证据取 verdict["evidence"] 原文（去重，最多前 4 条；KEEP_LIFE 时追加
# lifetime 的 ref_count 信号，让「为什么定寿」也可回溯）。
# 返回**恒与 verdict 回溯一致**：含命中规则名与证据片段，绝不含正文抄录。
def why_kept_of(verdict) -> str:
    """从判定结论推导「为什么留下」的可读理由（E-T31a t1 写入侧落字段）。

    只组合 verdict 自带的结构（judge / state_of / evidence / lifetime），
    不读正文、不猜——规则名 + 证据原文，AI 自判、可回溯到判定。
    """
    if not isinstance(verdict, dict):
        return ""
    if verdict.get("state") in (None, "", DROP):
        return ""
    jid = verdict.get("judge")
    if not jid and isinstance(verdict.get("state_of"), dict):
        jid = next(iter(verdict["state_of"]), None)
    if not jid:
        return ""
    title = RULES.get(jid, {}).get("title", jid)
    parts = []
    for e in verdict.get("evidence") or []:
        s = str(e).strip()
        if s and s not in parts:
            parts.append(s)
    life = lifetime_mark_of(verdict)
    if life and "ref_count=%s" % life.get("ref_count") not in parts:
        parts.append("ref_count=%s" % life.get("ref_count"))
    if not parts:
        parts.append(jid)
    return "%s %s（证据：%s）" % (jid, title, "；".join(parts[:4]))


# ---------------------------------------------------------------------------
# E-T24a t1：写入侧拆分器 split_keep_parts
# ---------------------------------------------------------------------------
# 缺陷（本任务入口）：判据面是**分句 + 取最高优先级（丢胜过留）**的口径（见模块头
# 「分句判定 + 取最高优先级」），故「今天把 report.pdf 生成一下，我主力语言是
# Python」这种一段里既有一次性交代、又有长期偏好的混句，**整条判 DROP**——偏好
# 被一次性交代连坐丢掉。模块头那句「该偏好会在其它轮次被单独说出」是设计上的
# 兜底假设，而实测中用户并不会为它再补一句。
#
# 修法（★ 只动写入侧，判定面一字不改）：判定面的语义**本来就是逐句**的，只是把
# 逐句结果的裁决定在「取最高优先级」这一步上。拆分器复用**同一个** `_hits_of`
# 单点重跑一遍逐句命中，把「单看这句是留」的句子挑出来——等价于问「这段文本若
# 逐句写，哪些句会留下」。于是：
#
#     judge_text(整条)        仍判 DROP/J7、DROP/J9（契约：不改判定面）
#     split_keep_parts(整条)  给出该留的句子 → 写路径用它拼正文
#     无保留片段              → `kept==""` → 写路径维持原 DROP 行为
#
# 为什么 kept 是单串而不是列表：写路径只需要「写什么」——`"".join(kept)` 即
# 正文。保留 `list[str]` 的副作用是下游各自 join，join 口径（分隔符）迟早分叉；
# 故在拆分器里定死，写路径不再做第二次拼接。`parts` 保留句子粒度是为可断言、
# 可审计（哪几句留的）。

#: 判定面的四个落盘字段（默认关时一个都不许出现）——真源在此，测试与接线共用。
JUDGMENT_FIELDS = (STATE_FIELD, WHY_KEPT_FIELD, LIFETIME_FIELD,
                   REF_COUNT_FIELD)


# 生效条件：接受 text/role/entities/ref_signals（与 judge_event 同形），返回 dict
#   {"kept": str,               # 保留片段按原序拼接（写路径的正文）
#    "parts": [str, ...],       # 保留片段列表（可断言/可审计）
#    "dropped": [str, ...],     # 丢弃片段列表（顺序同原文）
#    "kept_verdicts": [dict, ...],      # 与 parts 一一对应的判定结论
#    "dropped_verdicts": [dict, ...]}   # 与 dropped 一一对应的判定结论
# ——按 _SPLIT_RE 分句（复用 _sentences 单点）后再按逗号（`,` / `，`）二次切分子
# 片段，逐条跑 judge_text（同一判定面），state 为 KEEP/KEEP_LIFE 的进 parts/
# kept_verdicts（kept 即 parts 拼接），DROP 的进 dropped/dropped_verdicts。无保留
# 片段时 kept == ""（写路径据此维持原 DROP 行为）；空文本 → parts/kept 为空。恒不
# 抛：坏 shape 一律按「无保留」返回。**不改模块级 `_SPLIT_RE`**——逗号二次切分
# 只在本函数内做（本地 `_SPLIT_COMMA_RE`），判定面结构一动不动。
def split_keep_parts(text, role=None, entities=None, ref_signals=None) -> dict:
    r"""写入侧拆分器（E-T24a t1）：把整条判 DROP 的混句拆出该留的片段。

    与 `judge_text` **共用同一个** `_sentences` 分句单点与判定面——不另写一套
    词表/正则（`_PRIORITY`、`_SPLIT_RE` 与既有判定实现一字不动，本函数只**读**
    它们）。混合句常以中文/英文逗号隔开不同语义片段，故在此函数内**额外**按
    逗号做二次切分（等价于把「一句里的子片段」作独立单元逐条判）。因此拆分结果
    与「同一段逐句判」逐位一致：任何一句（或子片段）在 `judge_text` 下判
    KEEP/KEEP_LIFE，它就是这里的一个保留片段。

    返回：：

        {"kept": str,               # 保留片段按原序拼接（写路径的正文）
         "parts": [str, ...],       # 保留片段列表（可断言/可审计）
         "dropped": [str, ...],     # 丢弃片段列表（顺序同原文）
         "kept_verdicts": [dict, ...],      # 与 parts 一一对应的判定结论
         "dropped_verdicts": [dict, ...]}   # 与 dropped 一一对应的判定结论

    ★ 判定面语义不变：`judge_text(整条)` 的结果**一个字节都没变**——拆出的片段
    只由写路径消费（`MdCG.add` / `MdCG.remember_event`），调用方若直接读
    `judge_text` 拿到的仍是整条的 DROP。这是本任务最硬的契约。

    role 的口径与 `judge_text` 一致：role ∈ {tool-output, command, tool} 时整条
    结构性判 J9 丢，**不拆**（工具回显不是对话，里面内嵌的原文片段留在日志里，
    不是用户的话）——此时 kept == ""。
    """
    # 逗号二次切分（E-T24a t1）：只在函数内生效，不碰模块级 `_SPLIT_RE`。
    _SPLIT_COMMA_RE = re.compile(r"[,，]")
    text_s = "" if text is None else str(text)
    ent = entities
    role_s = str(role or "").strip().lower()
    if role_s in ("tool-output", "tool_output", "command", "tool"):
        return {"kept": "", "parts": [], "dropped": _sentences(text_s),
                "kept_verdicts": [], "dropped_verdicts": []}
    # E-T24a t1 修正：重复噪声（J9 的 `_dup_noise_of` 来源）是**全文属性**
    # ——它按 `_sentences` 统计「同一句在全文出现 ≥2 次」，不是单句自含的
    # 属性。拆到句子/子片段级后该属性会凭空消失，'A。A。' 拆出的单个 'A'
    # 单看是 KEEP（J6 兜底），于是整句判 DROP 的重复噪声被写入路径**救回**
    # ——违反既有测试对重复噪声「整句拒写」的契约。故先按原文计数复算一遍：
    # 在全文重复出现的句子不进逗号切分，整句按 DROP 处理（与整句
    # judge_text 的结论一致）。句内 CJK 立即重复（'收到收到'）是单句自含
    # 属性，逐条 judge_text 已能自行判 DROP，无需在此补。
    _dup_counts: dict = {}
    for _s in _sentences(text_s):
        _dup_counts[_s] = _dup_counts.get(_s, 0) + 1
    # 先按 _SPLIT_RE 切句，再按逗号切子片段——两级都去空白。逗号切分**只在
    # 该句同时出现保留与丢弃片段时生效**：两句都留（如 '我主力语言是 Python，
    # 讨厌过度抽象'）时子片段切分只破坏正文子串性，一律保留原句；同样，整句
    # 全丢时也返回原句（由 dropped 承载），写路径据此维持原 DROP 行为。
    candidates: list = []
    for _sent in _SPLIT_RE.split(text_s):
        _sent = _sent.strip()
        if not _sent:
            continue
        if _dup_counts.get(_sent, 0) >= 2:
            candidates.append(_sent)   # 全文重复句：不拆，整句留给下方判丢
            continue
        _sub = [s.strip() for s in _SPLIT_COMMA_RE.split(_sent) if s.strip()]
        if len(_sub) > 1:
            _keep_sub, _drop_sub = [], []
            for _s in _sub:
                try:
                    _v = judge_text(_s, entities=ent, ref_signals=ref_signals)
                except Exception:                       # fail-open：判留不抛
                    _v = {"state": KEEP, "judge": "J6",
                          "evidence": ["split:fail-open"], "lifetime": None}
                if _v.get("state") in (KEEP, KEEP_LIFE):
                    _keep_sub.append(_s)
                else:
                    _drop_sub.append(_s)
            # 混 keep/drop 才切；否则原样保留整句（契约 C：正文须为原文子串）
            if _keep_sub and _drop_sub:
                candidates.extend(_sub)
            else:
                candidates.append(_sent)
        else:
            candidates.append(_sent)
    parts, dropped, kv, dv = [], [], [], []
    for s in candidates:
        # 全文重复句按 J9 丢（与 `_dup_noise_of` 同源，见上方注释）。
        if _dup_counts.get(s, 0) >= 2:
            dropped.append(s)
            dv.append({"state": DROP, "judge": "J9",
                       "state_of": {"J9": DROP},
                       "evidence": ["dup-sentence×%d:%s"
                                    % (_dup_counts[s], s[:40])],
                       "lifetime": None})
            continue
        try:
            v = judge_text(s, entities=ent, ref_signals=ref_signals)
        except Exception:                           # pragma: no cover - fail-open
            v = {"state": KEEP, "judge": "J6",
                 "evidence": ["split:fail-open"], "lifetime": None}
        if v.get("state") in (KEEP, KEEP_LIFE):
            parts.append(s)
            kv.append(v)
        else:
            dropped.append(s)
            dv.append(v)
    return {"kept": "".join(parts), "parts": parts, "dropped": dropped,
            "kept_verdicts": kv, "dropped_verdicts": dv}
