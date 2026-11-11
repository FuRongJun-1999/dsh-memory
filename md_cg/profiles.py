# -*- coding: utf-8 -*-
"""资料树（档 1）：把散落节点聚合成**可召回的一等节点**——人物 / 地点 / 事件。

判据（使用者 2026-11-12）：人物·地点·时间·事件是核心状态；物品与情绪是辅助（只进 facet，不建树）。

为什么必须写成**真节点**而不是渲染期拼装：外测归因（弱项 19 题）证明「要素不在 pack」——
单点事实（姓名/年龄/职业）散在某几轮原话里，召回不命中。资料卡的价值是**给单点事实造一个
稠密的可召回容器**：查询提到「沈知夏」时，一张 20 字的卡同时带着姓名/年龄/职业。

设计约束：
  · **增量 + 幂等**：重跑只在内容真的变了才写（按渲染结果逐字比对）；
  · **只增不改事实**：事实行按 (日期, 节点 id) 稳定排序，新增节点只会追加行；
  · **不判断真假/归属**：抽取只产候选（见 entities），本层只做聚合与去重；
  · **辅助面只进 tags**：`obj:` / `emo:` 前缀标签，用于辅助检索，不参与状态。

节点命名（可预测、可回查）：
    profile:person:<人名>    profile:place:<地点>    profile:event:<YYYY-MM-DD>

不适用条件：实体抽取为确定性规则（见 entities 的不适用条件）；同一人多名（昵称/全名）不合并；
跨人物同名歧义不消解。
"""
from __future__ import annotations

import hashlib
import os
import time

from . import distill as _dis
from . import dossier as _dos
from . import entities as _en

# 落盘 id 只允许 ^[A-Za-z0-9_.@\u4e00-\u9fff,-]{1,128}$（**冒号非法**，会拼进路径），
# 故用 `profile-<kind>-<slug>` 形态；实体名里的非法字符按 _ 归一。
PREFIX = "profile-"
#: 角色名（闭集）：未配置则为空串 ⇒ 不建角色卡（不猜名字）。
_ROLE_USER = (os.environ.get("MDCG_ROLE_USER") or "").strip()
_ROLE_AI = (os.environ.get("MDCG_ROLE_AI") or "").strip()
LAYER = "knowledge"

#: 渲染时单条事实的最大字数（资料卡要稠密，不能变成原文堆）。
SNIPPET_MAX = 60
#: 单个资料卡最多保留的事实条数（超出按最近保留）。
MAX_FACTS = 40


# 生效条件：s 为任意实体名；返回只含合法 node_id 字符的 slug（长度 ≤48）
def _slug(s):
    out = []
    for ch in str(s or ""):
        if ch.isalnum() or ch in "_.@,-" or "\u4e00" <= ch <= "\u9fff":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:48] or "x"


# 生效条件：kind ∈ {person, place, event}、name 为实体名；返回资料卡节点 id（可预测，便于回查与幂等覆写）
def card_id(kind, name):
    return "%s%s-%s" % (PREFIX, kind, _slug(name))


# 生效条件：text 为正文；返回压成单行的片段（去换行/去 CCG 头，截 SNIPPET_MAX）
def _snippet(text):
    lines = [l.strip() for l in str(text or "").splitlines()]
    body = [l for l in lines if l and not l.startswith("#")]
    return (" ".join(body) or "")[:SNIPPET_MAX]


# 生效条件：facts 为 [(日期, 节点id, 片段)]；返回渲染后的资料卡正文（CCG 六要素 + 事实序列）
def render(kind, name, facts, dossier=None):
    title = {"role": "角色资料", "person": "人物资料", "place": "地点资料", "event": "事件资料"}[kind]
    head = [
        "# 功能名：%s：%s" % (title, name),
        "# 生效条件：查询提到「%s」或其属性（姓名/年龄/职业/地点/日期）时" % name,
        "# 子功能：① 事实序列（按日期升序，每条带来源节点）",
        "# 执行：由 profiles.build 从既有节点确定性聚合（无模型抽取）",
        "# 验证方式：tests/test_profiles.py",
        "# 不适用条件：正文未出现的属性不在本卡；同名不合并",
        "",
    ]
    #: 档案字段的展示顺序（基本信息 → 身份职业 → 家庭）
    _ORDER = ("姓名", "年龄", "城市", "职业", "单位", "学历", "专业",
              "父", "母", "配偶", "子女")
    _LIST_ORDER = ("经历", "家庭")
    body = []
    if dossier:
        body.append(dept_line := "【档案】")
        for k in _ORDER:
            v = dossier.get(k)
            if not v:
                continue
            # 值 + 陈述时刻（用括号注出，便于模型直接引用，不必自己换算）
            body.append("- %s：%s%s" % (
                k, v.get("value"),
                "（%s）" % time.strftime("%Y-%m", time.localtime(float(v["t"])))
                if v.get("t") else ""))
        for k in _LIST_ORDER:
            v = dossier.get(k)
            items = (v or {}).get("value") or []
            if not items:
                continue
            body.append("【%s】" % k)
            for it in items:
                if not isinstance(it, dict):
                    continue
                parts = [str(x) for x in it.values() if x not in (None, "")]
                if parts:
                    body.append("- " + " | ".join(parts))
        body.append("")
    for date, nid, snip in facts:
        body.append("- %s | %s（来源 %s）" % (date or "日期不明", snip, nid))
    return "\n".join(head + body) + "\n"


# 生效条件：cg 提供 index/get/add；返回 {"scanned", "cards", "written", "skipped", "facts"}
def build(cg, dry_run=True, limit=None):
    """扫描既有节点 → 按实体聚合 → 写成资料卡（幂等；dry_run 只算不写）。"""
    from . import reldate
    nodes = (cg.index.get("nodes") or {})
    buckets = {}          # (kind, name) -> [(date, nid, snippet)]
    _declared_nids = set()  # 带 diary 声明的来源节点（用于卡来源标记）
    st = {"scanned": 0, "cards": 0, "written": 0, "skipped": 0, "facts": 0,
          "dry_run": bool(dry_run), "declared": 0, "extracted": 0}
    for nid, e in list(nodes.items()):
        if str(nid).startswith(PREFIX):
            continue
        if limit and st["scanned"] >= int(limit):
            break
        node = cg.get(nid)
        if not node:
            continue
        st["scanned"] += 1
        fm = node.get("frontmatter") or {}
        content = node.get("content") or ""
        ts = fm.get("created_at")
        day = ""
        if ts is not None:
            try:
                day = time.strftime("%Y-%m-%d", time.localtime(float(ts)))
            except (TypeError, ValueError, OSError):
                day = ""
        tags = fm.get("tags") or []
        snip = _snippet(content)
        # 【情景层 v0.1】diary 声明优先：角色名是闭集，由写入声明（零抽取）。
        # 外测实证：靠正则猜名字会抽出 profile-person-号你 这类错卡，正确卡反被淹没。
        diary = fm.get("diary") if isinstance(fm.get("diary"), dict) else None
        if diary:
            _declared_nids.add(nid)
            day = str(diary.get("date") or day or "")
            for key in ("speaker", "listener"):
                v = str(diary.get(key) or "").strip()
                if v:
                    buckets.setdefault(("role", v), []).append((day, nid, snip))
            for pp in (diary.get("participants") or []):
                v = str(pp or "").strip()
                if v and _en.gate_name(v):
                    buckets.setdefault(("person", v), []).append((day, nid, snip))
            pl = str(diary.get("place") or "").strip()
            if pl:
                buckets.setdefault(("place", pl), []).append((day, nid, snip))
            if day:
                buckets.setdefault(("event", day), []).append((day, nid, snip))
            continue
        # 【外测实证 2026-11-12】只传 diary 的节点极少时，role/person 卡会**完全不产出**，
        # 注入就只能塞事件卡（对属性题无用）。故补一条**角色兜底**：
        # 节点带 role=user/assistant 且配置了角色名（MDCG_ROLE_USER / MDCG_ROLE_AI）⇒ 归到角色卡。
        # 未配置则不做——**不猜角色名**。
        _role = str(fm.get("role") or "").strip().lower()
        if _role in ("user", "assistant"):
            _rname = ((os.environ.get("MDCG_ROLE_USER") or _ROLE_USER).strip()
                      if _role == "user" else
                      (os.environ.get("MDCG_ROLE_AI") or _ROLE_AI).strip())
            if _rname:
                buckets.setdefault(("role", _rname), []).append((day, nid, snip))
        # 回落：无 diary 的存量节点按确定性抽取（卡标 extracted，与 declared 不混报）
        for name in _en.persons(content, tags):
            buckets.setdefault(("person", name), []).append((day, nid, snip))
        for name in _en.places(content, tags):
            buckets.setdefault(("place", name), []).append((day, nid, snip))
        if day and any(k in content for k in ("约定", "约好", "碰面", "聚餐", "改期", "会议")):
            buckets.setdefault(("event", day), []).append((day, nid, snip))
    for (kind, name), facts in sorted(buckets.items()):
        # 去重 + 稳定排序（日期, 节点 id）⇒ 增量：新节点只会往后追加
        seen, uniq = set(), []
        for f in sorted(facts, key=lambda x: (x[0] or "", x[1])):
            if f[1] in seen:
                continue
            seen.add(f[1])
            uniq.append(f)
        uniq = uniq[-MAX_FACTS:]
        # 档案：从本卡来源节点里抽字段并增量合并（只对 role/person 卡建）
        # 【外测 2026-11-12】必须扫**未截断的全量 facts**：早期自我介绍（w=3）曾因
        # MAX_FACTS 窗口只保留最近 N 条而被丢弃 ⇒ 卡的档案里只剩弱证据的误填。
        _dos_all = {}
        if kind in ("role", "person"):
            _seen_dos = set()
            for _d, _nid, _snip in facts:
                if _nid in _seen_dos:
                    continue
                _seen_dos.add(_nid)
                _n = cg.get(_nid) or {}
                _fm = _n.get("frontmatter") or {}
                # ① 先并入**声明/LLM 填表**的档案（fm.dossier，带 ev_span、经原文复核）
                # 档案可能落在 fm.dossier，也可能被未知 kwarg 收进 fm.extra.dossier，
                # 两处都读（口径单点：先顶层，后 extra）。
                _dec = _fm.get("dossier")
                if not isinstance(_dec, dict):
                    _dec = (_fm.get("extra") or {}).get("dossier")
                # ② 再补**规则抽取**的档案（LLM 没填的字段由规则兜底；不覆盖已有值）
                _rule = _dos.extract(_n.get("content") or "", _fm.get("created_at"), _nid)
                # 【证据权重】自我介绍/声明的条目权重大于泛提；合并时弱者不得覆盖强者。
                _w = _dos.weight_of(_n.get("content") or "")
                for _fk, _fv in _rule.items():
                    _fv = dict(_fv)
                    _fv["w"] = _w
                    if _fk == "城市" and not _dis.is_place(_fv.get("value")):
                        continue          # 合并期同样过地名闸（旧节点可能绕过写入期复核）
                    _dos_all = _dos.merge(_dos_all, {_fk: _fv})
                # 声明/LLM 填表的档案同样按该节点权重入账
                if isinstance(_dec, dict) and _dec:
                    for _fk, _fv in _dec.items():
                        if _fk.startswith("_"):
                            continue
                        _fv = dict(_fv) if isinstance(_fv, dict) else {"value": _fv}
                        _fv.setdefault("w", _w)
                        if _fk == "城市" and not _dis.is_place(_fv.get("value")):
                            continue      # 声明/LLM 的旧档案也过闸
                        _dos_all = _dos.merge(_dos_all, {_fk: _fv})
        st["cards"] += 1
        st["facts"] += len(uniq)
        text = render(kind, name, uniq, dossier=_dos_all)
        nid = card_id(kind, name)
        prev = cg.get(nid)
        if prev and (prev.get("content") or "") == text:
            st["skipped"] += 1
            continue
        if dry_run:
            continue
        # 辅助面（物品/情绪）只进 tags：用于辅助检索，不参与状态
        aux = _en.auxiliary(" ".join(f[2] for f in uniq))
        tags = ["%s%s" % (kind, ":" + name if kind != "event" else ""),
                "profile", "%s:%s" % (kind, name)]
        _src = "declared" if any(nid in _declared_nids for _d, nid, _s in uniq) else "extracted"
        st[_src] = st.get(_src, 0) + 1
        tags.append("card_source:" + _src)
        tags += ["obj:" + o for o in aux["objects"][:8]]
        tags += ["emo:" + w for w in aux["emotions"][:5]]
        # created_at 只在**已有卡**时透传（保持出生时刻）；新卡交给 add 取 now。
        # 传 None 会落到 add 的观测窗锚点计算上（`None + float` 直接炸）。
        # 【外测请求 #2/#3】卡的 created_at 不能是**建卡时刻**：库历史到 2026-05、卡却落在 2026-11-11，
        # 桶/日路径因此 bucket=0，卡只能靠词法进——而词法长句只给 1 条。
        # 现取**最早事实日**（有 diary.date 就用它），并把它换算成时刻；推不出则不传（交给 add 取 now）。
        _dates = sorted(f[0] for f in uniq if f[0])
        _first_day = _dates[0] if _dates else ""
        _kw = {"layer": LAYER, "tags": tags, "importance": 0.6,
               "consistency": False}
        # session 继承：取来源节点里出现最多的 session（多人物隔离时卡才不会被 session 过滤掉）。
        import time as _t
        _sess = {}
        for _f in uniq:
            _n = cg.get(_f[1]) or {}
            _s = ((_n.get("frontmatter") or {}).get("session"))
            if _s:
                _sess[_s] = _sess.get(_s, 0) + 1
        if _sess:
            _kw["session"] = sorted(_sess.items(), key=lambda x: -x[1])[0][0]
        _prev_has_ts = (((prev or {}).get("frontmatter") or {}).get("created_at") is not None)
        if _first_day and not _prev_has_ts:
            try:
                _kw["created_at"] = _t.mktime(_t.strptime(_first_day, "%Y-%m-%d"))
            except ValueError:
                pass
        _prev_ts = ((prev or {}).get("frontmatter") or {}).get("created_at")
        if _prev_ts is not None:
            _kw["created_at"] = _prev_ts
        cg.add(nid, text, **_kw)
        st["written"] += 1
    return st