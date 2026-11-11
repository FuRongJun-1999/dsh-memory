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

from . import entities as _en

# 落盘 id 只允许 ^[A-Za-z0-9_.@\u4e00-\u9fff,-]{1,128}$（**冒号非法**，会拼进路径），
# 故用 `profile-<kind>-<slug>` 形态；实体名里的非法字符按 _ 归一。
PREFIX = "profile-"
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
def render(kind, name, facts):
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
    body = []
    for date, nid, snip in facts:
        body.append("- %s | %s（来源 %s）" % (date or "日期不明", snip, nid))
    return "\n".join(head + body) + "\n"


# 生效条件：cg 提供 index/get/add；返回 {"scanned", "cards", "written", "skipped", "facts"}
def build(cg, dry_run=True, limit=None):
    """扫描既有节点 → 按实体聚合 → 写成资料卡（幂等；dry_run 只算不写）。"""
    from . import reldate
    nodes = (cg.index.get("nodes") or {})
    buckets = {}          # (kind, name) -> [(date, nid, snippet)]
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
        st["cards"] += 1
        st["facts"] += len(uniq)
        text = render(kind, name, uniq)
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
        _src = "declared" if kind == "role" else "extracted"
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