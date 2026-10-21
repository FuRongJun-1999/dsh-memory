# -*- coding: utf-8 -*-
"""QMD 的 LLM 接入：源图抽取、题面扩展、作答与判官调用 + 统一系统提示词 + 身份隔离缓存。

开关与配置（全部显式，无隐式回落）
----------------------------------
  · ``MDCG_QMD_SYS``：**只有取值恰为 "1"** 才给 extract / query / answer 三类调用带同一条
    统一系统提示词 ``SYSTEM``；未设或其它任何取值 = 关，messages 只有一条 user（与原型不带系统
    提示词的臂逐字相同）。**judge（判官）在任何取值下都不带 system**——保证与既有臂判分口径可比。
  · ``MDCG_QMD_LLM_BASE`` / ``MDCG_QMD_LLM_MODEL`` / ``MDCG_QMD_LLM_KEY``：OpenAI 兼容
    ``/chat/completions`` 的地址、模型、密钥，三者**缺一即抛 ``LLMUnavailable``**（点名缺哪个），
    不发请求、不静默降级。刻意**不**回落 ``MDCG_LLM_KEY`` / ``DEEPSEEK_API_KEY``：QMD 的网关可能
    与反思单元不同厂商，回落即凭证外泄（与 issue #96 同一立场）。

依据（白箱三问之一）
--------------------
  · 原型：TanPowasd/LingShu-prime ``TanPowasd/agm/bench/hive_official.py``（``SYSTEM``、``chat``、
    ``parse_json``）、``TanPowasd/agm/confluence/qx.py``（题面扩展提示词与 ``clean``）、
    ``hive_extract.py`` / ``extract.py``（源图抽取提示词）。提示词文本逐字取自原型。
  · 原型审计 dsh-bounty#466：追问缓存未按系统提示词隔离、产物按臂名存在即复用 ⇒ 本模块的缓存键
    含（角色、模型、地址、密钥摘要、max_tokens、实际发出的 system 文本、prompt），条目内另存身份并在
    读出时逐项比对。密钥只以 sha256 摘要进身份，明文不写入任何缓存文件（PR #395 对抗复核补）。

生效条件（白箱三问之二）
------------------------
  · 只被显式调用时生效；本仓既有检索/写入路径不 import 本模块（守卫 ``md_cg/test_qmd.py`` P13）。
  · 网关返回体若外包一层 ``{"data": {...}}``（实测 Cline 网关如此）则解开；``choices`` 缺失、
    content 为空、``finish_reason == "length"`` 一律抛 ``RuntimeError``，不当作空答案。

错了怎么办 / 边界（白箱三问之三）
--------------------------------
  · 抽取失败的批次会拆半重试到单条；仍失败的条目**原样列入返回的 missing**，由调用方决定；
    ``md_cg/qmd.py`` 拿到缺块源图会抛 ``PartialGraph``、缺题 hint 会抛 ``MissingHint``。
  · 无 LLM 时端到端增益不成立；本模块只提供调用面，不提供任何「无 key 替代」。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request

__all__ = ["SYSTEM", "SYS_ENV", "BASE_ENV", "MODEL_ENV", "KEY_ENV", "ROLES", "LLMUnavailable", "CacheIdentityError",
           "sys_on", "system_for", "messages", "config", "chat", "Cache", "call", "parse_json", "clean_hint",
           "query_prompt", "graph_prompt", "extract_hints", "extract_triples"]

SYS_ENV = "MDCG_QMD_SYS"
BASE_ENV = "MDCG_QMD_LLM_BASE"
MODEL_ENV = "MDCG_QMD_LLM_MODEL"
KEY_ENV = "MDCG_QMD_LLM_KEY"
ROLES = ("extract", "query", "answer", "judge")

SYSTEM = ("你是灵枢长期记忆系统里的一个组件，负责从给定材料中抽取、检索或回答。\n"
          "1. 只依据本次用户消息里给出的材料和问题工作，不使用材料以外的知识，不猜测，不编造。\n"
          "2. 人名、地名、物品名、日期、数字一律照原文逐字写，不改写、不意译。\n"
          "3. 问题有多个要点时逐点覆盖，不遗漏；材料里确实没有的，明确说没有，不要硬凑。\n"
          "4. 严格按要求的格式输出：要 JSON 就只输出一个 JSON 对象，不加代码块、不加解释。")


class LLMUnavailable(RuntimeError):
    """QMD 的 LLM 配置不全（缺地址/模型/密钥）。显式边界：不发请求、不降级。"""


class CacheIdentityError(RuntimeError):
    """缓存条目记录的身份与本次调用不一致（不复用、不覆盖）。"""


# 生效条件：环境变量 MDCG_QMD_SYS 取值恰为 "1" 时返回 True，否则 False。
def sys_on() -> bool:
    return os.environ.get(SYS_ENV) == "1"


# 生效条件：role 为 judge 时恒返回 None；其余角色在 sys_on() 为真时返回 SYSTEM，否则 None；未知角色抛 ValueError。
def system_for(role: str):
    if role not in ROLES:
        raise ValueError(f"未知角色 {role!r}（应为 {ROLES}）")
    if role == "judge":
        return None
    return SYSTEM if sys_on() else None


# 生效条件：给定 role 与 prompt，返回实际要发出的 messages 列表（system_for 非空时首条为 system）。
def messages(role: str, prompt: str) -> list:
    s = system_for(role)
    return ([{"role": "system", "content": s}] if s else []) + [{"role": "user", "content": prompt}]


# 生效条件：MDCG_QMD_LLM_BASE / MODEL / KEY 三个环境变量都为非空时返回 {"base","model","key"}，任一缺失抛 LLMUnavailable 并点名。
def config() -> dict:
    cfg = {"base": os.environ.get(BASE_ENV), "model": os.environ.get(MODEL_ENV), "key": os.environ.get(KEY_ENV)}
    miss = [n for n, k in ((BASE_ENV, "base"), (MODEL_ENV, "model"), (KEY_ENV, "key")) if not (cfg[k] or "").strip()]
    if miss:
        raise LLMUnavailable("QMD 的 LLM 未配置：缺 " + "、".join(miss) + "（不回落其它厂商的密钥变量）")
    return cfg


# 生效条件：给定网关返回体 data，解开可选的 {"data": ...} 外包；choices 缺失、content 空或 finish_reason=="length" 时抛 RuntimeError，否则返回 content。
def _content(data: dict) -> str:
    if "choices" not in data and isinstance(data.get("data"), dict):
        data = data["data"]
    ch = data.get("choices") or []
    if not ch:
        raise RuntimeError("LLM 响应无 choices：" + json.dumps(data, ensure_ascii=False)[:300])
    if ch[0].get("finish_reason") == "length":
        raise RuntimeError("LLM 输出被截断（finish_reason=length）")
    txt = (ch[0].get("message") or {}).get("content") or ""
    if not txt.strip():
        raise RuntimeError("LLM 返回空 content")
    return txt


# 生效条件：给定 role、prompt（cfg 缺省时由 config() 解析，配置不全即抛 LLMUnavailable），向 base 的 /chat/completions 发一次 POST（temperature=0，max_tokens 仅在显式给出时传），经 _content 校验后返回文本；opener 供测试注入。
def chat(role: str, prompt: str, cfg: dict = None, timeout: int = 300, max_tokens: int = None, opener=None) -> str:
    cfg = cfg or config()
    body = {"model": cfg["model"], "messages": messages(role, prompt), "temperature": 0}
    if max_tokens:
        body["max_tokens"] = max_tokens
    req = urllib.request.Request(cfg["base"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['key']}"})
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
        return _content(json.loads(r.read().decode("utf-8")))


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class Cache:
    """按调用身份隔离的结果缓存：一调用一文件，文件名 = 身份的 sha256。

    身份 = （角色，模型，地址，密钥的 sha256，max_tokens（未给为 None），实际发出的 system 文本的 sha256 或 None，
    prompt 的 sha256）。密钥只存摘要，明文不落盘。
    读出时把条目里存的身份与本次逐项比对，不一致抛 CacheIdentityError（不复用、不覆盖）。
    """

    def __init__(self, root):
        self.root = os.fspath(root)
        os.makedirs(self.root, exist_ok=True)

    # 生效条件：给定 role、prompt、cfg 与 max_tokens，返回身份字典；max_tokens 取假值时记 None（与 chat 不传该字段一致），密钥只记 sha256。
    @staticmethod
    def identity(role: str, prompt: str, cfg: dict, max_tokens: int = None) -> dict:
        s = system_for(role)
        return {"role": role, "model": cfg["model"], "base": cfg["base"], "key_sha": _sha(cfg["key"]),
                "max_tokens": max_tokens or None, "system_sha": _sha(s) if s else None, "prompt_sha": _sha(prompt)}

    # 生效条件：给定 identity 字典，返回其规范 JSON 的 sha256 作为缓存文件名主干。
    @staticmethod
    def key(ident: dict) -> str:
        return _sha(json.dumps(ident, ensure_ascii=False, sort_keys=True))

    def _path(self, ident):
        return os.path.join(self.root, self.key(ident) + ".json")

    # 生效条件：给定 role、prompt、cfg、max_tokens：缓存文件不存在返回 None；存在且条目身份与本次相同返回其文本；身份不同抛 CacheIdentityError。
    def get(self, role: str, prompt: str, cfg: dict, max_tokens: int = None):
        ident = self.identity(role, prompt, cfg, max_tokens)
        p = self._path(ident)
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("identity") != ident:
            raise CacheIdentityError(f"{p} 的身份 {d.get('identity')} ≠ 本次 {ident}")
        return d["text"]

    # 生效条件：给定 role、prompt、cfg、文本与 max_tokens，把 {"identity","text"} 写入身份对应的缓存文件。
    def put(self, role: str, prompt: str, cfg: dict, text: str, max_tokens: int = None) -> None:
        ident = self.identity(role, prompt, cfg, max_tokens)
        with open(self._path(ident), "w", encoding="utf-8") as f:
            json.dump({"identity": ident, "text": text}, f, ensure_ascii=False)


# 生效条件：给定 role、prompt：cache 命中则返回缓存文本（counter 不变）；否则调用 chat，结果写入 cache（若给）并给 counter["calls"] 加一后返回；kw 里的 max_tokens 同时进缓存身份。
def call(role: str, prompt: str, cfg: dict = None, cache: Cache = None, counter: dict = None, **kw) -> str:
    cfg = cfg or config()
    mt = kw.get("max_tokens")
    if cache is not None:
        hit = cache.get(role, prompt, cfg, mt)
        if hit is not None:
            return hit
    if counter is not None:
        counter["calls"] = counter.get("calls", 0) + 1
    txt = chat(role, prompt, cfg=cfg, **kw)
    if cache is not None:
        cache.put(role, prompt, cfg, txt, mt)
    return txt


# 生效条件：给定模型输出文本，剥掉首尾代码围栏后取首个 "{" 到末个 "}" 之间解析为 JSON 返回；解析失败抛 ValueError。
def parse_json(txt: str):
    t = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j + 1])


# 生效条件：给定一题的原始抽取结果 v：非字典或 ents/preds 皆空返回 None；否则返回字段裁成字符串（ents/preds/kw 各至多 8 条、hyde 至多 300 字、time 空值归 None）的规范字典。
def clean_hint(v):
    if not isinstance(v, dict):
        return None
    L = lambda x: [str(s).strip() for s in (x if isinstance(x, list) else [x] if x else []) if str(s).strip()][:8]  # noqa: E731
    ents, preds = L(v.get("ents")), L(v.get("preds"))
    if not ents and not preds:
        return None
    t = v.get("time")
    return {"ents": ents, "preds": preds, "time": str(t).strip() if t not in (None, "", "null") else None,
            "kw": L(v.get("kw")), "hyde": str(v.get("hyde") or "").strip()[:300]}


Q_EN = """You prepare search queries for a memory system over a long chat history between two people.
For EACH question, output:
- "ents": the people, objects, places, events, activities it asks about, written as they would appear in the chat (short noun phrases; resolve "she/he" only if the question names them);
- "preds": the relation or action asked about, as short verb phrases, plus 1-2 likely paraphrases;
- "time": the time constraint if any ("last year", "May 2023", "before the move"), else null;
- "kw": 3-6 extra keywords a matching chat line would likely contain (synonyms, related concrete words);
- "hyde": one short sentence, as the speaker might have said it in the chat, that would answer the question (invent plausible specifics; it is only used for search).
Output ONLY JSON: {{"q": {{"<id>": {{"ents": [...], "preds": [...], "time": null, "kw": [...], "hyde": "..."}}, ...}}}}

Questions:
{qs}"""

Q_ZH = """你在为一个检索中文小说正文的记忆系统准备检索式。对下面每道题，输出：
- "ents"：题目问到的人物、物品、地点、事件，用小说原文里可能出现的写法（人名写全名，也给常见称呼）；
- "preds"：题目问的关系或动作，短动词短语，并给 1-2 个近义说法；
- "time"：题中的时间约束（如“第三天夜里”“事发前”），没有就 null；
- "kw"：3-6 个命中的原文句子里很可能出现的词（近义词、相关具体词）；
- "hyde"：一句像小说原文的假想句子，能回答本题（细节可以编，只用于检索）。
只输出 JSON：{{"q": {{"<题号>": {{"ents": [...], "preds": [...], "time": null, "kw": [...], "hyde": "..."}}, ...}}}}

题目：
{qs}"""

G_EN = """You convert dialogue turns into a knowledge graph. For EACH turn below, list its facts as
[subject, predicate, object] triples.
Rules:
- Replace pronouns (I, me, my, you, she, we, it...) with the concrete name they refer to; "I" is the speaker.
- Keep entity names short and as written (e.g. "Caroline", "LGBTQ support group", "pottery class").
- Predicates are short verb phrases ("attended", "plans to", "is", "painted", "felt").
- Add a date/time only if the turn states one, as a triple [event, "when", time].
- Include facts from [image: ...] captions as things the speaker shared.
- A turn with no factual content gets [].
Output ONLY JSON: {{"turns": {{"<turn id>": [[s,p,o], ...], ...}}}}

Turns:
{turns}"""

G_ZH = """你要把小说正文片段转成知识图谱。对下面每个片段，列出其中的事实，格式为 [主语, 谓语, 宾语] 三元组。
规则：
- 代词（他、她、它、我们、这……）一律换成它指代的具体人名或事物名。
- 实体名保持简短、照原文写法（人名、地名、物品、组织、事件）。
- 谓语是简短的动词短语（“交给”“怀疑”“住在”“是”“答应”）。
- 原文写了时间、原因、条件时，用 [事件, "时间"/"原因"/"条件", 内容] 表示。
- 没有事实的片段给 []。
只输出 JSON：{{"chunks": {{"<片段编号>": [[主,谓,宾], ...], ...}}}}

片段：
{chunks}"""


# 生效条件：给定 [(题号, 问题)] 与 lang（"zh"/"en"），返回题面扩展提示词（与原型 qx.py 逐字相同）。
def query_prompt(items, lang: str) -> str:
    return (Q_ZH if lang == "zh" else Q_EN).format(qs="\n".join(f"[{i}] {q}" for i, q in items))


# 生效条件：给定 [(编号, 文本)] 与 lang，返回源图抽取提示词（zh 与原型 hive_extract.py、en 与 extract.py 逐字相同）。
def graph_prompt(items, lang: str) -> str:
    if lang == "zh":
        return G_ZH.format(chunks="\n".join(f"[{i}] {t.strip()}" for i, t in items))
    return G_EN.format(turns="\n".join(f"[{i}] {t}" for i, t in items))


# 生效条件：给定条目批 items、单批解析函数 one(批) → {编号: 结果}（异常视为整批失败）与重试次数：整批失败先原样重试 retries 次；仍缺的条目多于 1 条则拆半递归，单条则记入 missing。返回 (结果字典, missing 编号列表)。
def _batched(items, one, retries: int = 1):
    got, missing = {}, []

    def run(b, left):
        try:
            r = one(b)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError, urllib.error.URLError) as e:   # 显式列举，结果计入 missing
            r, err = {}, e
        else:
            err = None
        got.update(r)
        miss = [x for x in b if x[0] not in r]
        if not miss:
            return
        if not r and left > 0:
            return run(miss, left - 1)
        if len(miss) > 1:
            h = (len(miss) + 1) // 2
            run(miss[:h], retries); run(miss[h:], retries)
        else:
            missing.append((miss[0][0], repr(err) if err else "输出缺该条"))

    run(list(items), retries)
    return got, missing


# 生效条件：给定 [(题号, 问题)]、lang 与批大小，按批调用 query 角色抽题面扩展（缓存/计数见 call），返回 ({题号: hint}, [(缺失题号, 原因)])。
def extract_hints(items, lang: str, batch: int = 10, cfg: dict = None, cache: Cache = None, counter: dict = None):
    cfg = cfg or config()

    def one(b):
        obj = parse_json(call("query", query_prompt(b, lang), cfg=cfg, cache=cache, counter=counter))
        g = (obj or {}).get("q", obj) or {}
        return {i: c for i, _ in b if (c := clean_hint(g.get(i) or g.get(f"[{i}]")))}

    got, missing = {}, []
    for k in range(0, len(items), batch):
        a, m = _batched(items[k:k + batch], one)
        got.update(a); missing += m
    return got, missing


# 生效条件：给定 [(编号, 文本)]、lang 与批大小，按批调用 extract 角色抽源图三元组，返回 ({编号: [[主,谓,宾], ...]}, [(缺失编号, 原因)])；输出里不是三元组的项丢弃，[] 合法。
def extract_triples(items, lang: str, batch: int = 10, cfg: dict = None, cache: Cache = None, counter: dict = None,
                    max_tokens: int = None):
    cfg = cfg or config()
    field = "chunks" if lang == "zh" else "turns"

    def one(b):
        obj = parse_json(call("extract", graph_prompt(b, lang), cfg=cfg, cache=cache, counter=counter, max_tokens=max_tokens))
        m = {}
        for k, v in ((obj or {}).get(field, {}) or {}).items():
            if isinstance(v, list):
                m[str(k).strip("[] ")] = [t for t in v if isinstance(t, list) and len(t) == 3]
        return {i: m[i] for i, _ in b if i in m}

    got, missing = {}, []
    for k in range(0, len(items), batch):
        a, m = _batched(items[k:k + batch], one)
        got.update(a); missing += m
    return got, missing
