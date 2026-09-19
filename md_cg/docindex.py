# -*- coding: utf-8 -*-
"""条件文档图：按「章节」索引 md 文档，不存全文。

设计（2026-09-10）：
`docs/` 下的 md 是**规范/方案的唯一事实源**，认知图只需要「哪一份文档、哪一节、
哪几行」这一级坐标，不需要第二份全文（否则文档一改就有两份真相，且必然漂移）。
因此本模块与 `codeindex` 同构：切块 → 渲染 CCG → frontmatter.doc_ref 指回原文；
正文用 `op=ref` 回读。

切块纪律（对应计划 §八 的风险项）：
  · **只切 level<=3**：再深就过细，节点数爆炸且检索噪声上升；
  · 直接正文 < `MIN_BODY` 字且**无子节**的小节**合并进父节**（不单独建节点，
    其文字追加进父节摘要），否则会把「一行小标题」也变成一个节点；
  · **不存全文**：节点正文是 CCG 模板 + 摘要，正文一律回读。

md 解析的两处硬约束：
  · **围栏代码块内的 `#` 不是标题**：`docs/` 里大量 python/shell 片段带 `#` 注释，
    若不做围栏跟踪，一节会被切得七零八落（假标题、错行号）；
  · **正文里的 `---` 不参与 frontmatter 切分**：这条纪律在 `nodefile.py` 已定，
    本模块额外保证开头 YAML frontmatter 不被当成正文索引，其余 `---` 只当正文。

节点正文必须是 **CCG 6 行**（见 `render`）：非 CCG 正文会被 `judge_qualification`
的第一步（ccg_completeness）直接判 **BLINDSPOT**，文档节点会「存得进、判不了、
检索不到」——这与改造前的 `codeindex` 是同一个坑。

区间哈希复用 `codeindex.region_hash`（**唯一实现**），索引侧与 `op=ref` 回读侧共用。
"""
from __future__ import annotations

import hashlib
import os
import re

from . import codeindex, nodefile

SKIP_DIRS = ("__pycache__", ".git", ".venv", "venv", "node_modules", ".mypy_cache")

SUFFIX = (".md", ".markdown")

MAX_LEVEL = 3          # 只切 level<=3
MIN_BODY = 200         # 直接正文 < 200 字且无子节 → 合并进父节
MAX_SUMMARY = 200      # 「执行」栏摘要上限
MAX_DOC = 400

KIND = "section"
LANG = "md"
BASIS = "data"         # 文档的验证基底：以原始文档为准

# ---- 密级（计划 §1.3-3 的裁定，2026-09-10）--------------------------------
# 裁定一：layer 默认 knowledge。理由——文档是**可回读、可漂移检测**的参照知识，
#         与代码节点同层，保证进默认召回；contextual 表示情境绑定、会过期，
#         用在这里会让文档掉出默认召回。
# 裁定二：密级**默认 internal 并显式写入 frontmatter**，不依赖节点默认值
#         （mdcos 读隔离取的是 fm.sensitivity；不显式写就等于「靠默认值兜底」，
#         审计时看不出意图）。且路径段命中私有提示时**再保守一档降为 private**：
#         宁可漏召回，不可泄漏（计划 §八 的风险项）。
DEFAULT_SENSITIVITY = "internal"
PRIVATE_HINTS = ("private", "secret", "internal", "未公开", "私有", "内部")


# 生效条件：override 为真值即返回 (override, "调用方显式指定")；否则 path（假值按 ""）按 "\" 与 "/" 分段，任一段小写含 PRIVATE_HINTS 中任一提示即返回 ("private", 路径段命中理由)，全部不命中返回 (DEFAULT_SENSITIVITY, 默认密级理由)；
def sensitivity_for(path, override=None):
    """返回 (密级, 依据)。override 优先；否则按路径段保守降级。

    只可能**更严**、不可能更松：命中提示只会把 internal 收紧为 private，
    不会把 private 放开成 public。缺省值显式返回，便于调用方落盘与审计。
    """
    if override:
        return override, "调用方显式指定"
    for seg in (path or "").replace("\\", "/").split("/"):
        low = seg.lower()
        for hint in PRIVATE_HINTS:
            if hint in low:
                return "private", f"路径段「{seg}」命中私有提示 → 保守降级"
    return DEFAULT_SENSITIVITY, "默认密级（显式写入，不依赖节点默认值）"


# --------------------------------------------------------------------------
# md 解析
# --------------------------------------------------------------------------
_FENCE = re.compile(r"^\s*(```+|~~~+)")
_ATX = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


# 生效条件：lines 非空且 lines[0].strip() == "---" 时，从下标 1 起找到首个 strip() == "---" 的行并返回其后一行下标 i+1；lines 为空、首行不是 "---" 或找不到闭合 "---" 时返回 0；
def _body_start(lines):
    """跳过开头 YAML frontmatter，返回正文起始行下标（0 基）。"""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


# 生效条件：从 start（默认 0）遍历 lines，未处于围栏时遇 _FENCE 匹配行打开同标记围栏、围栏内遇同标记行关闭并继续；围栏外 _ATX 匹配行追加 {level: 一级 # 个数, title: 去空白后的标题, lineno: i+1}；返回 out 列表；start 不小于 len(lines) 时返回空列表；
def _headings(lines, start=0):
    """产出 ATX 标题 `{level,title,lineno}`；**围栏代码块内的 `#` 不算标题**。"""
    out, fence = [], None
    for i in range(start, len(lines)):
        line = lines[i]
        m = _FENCE.match(line)
        if m:
            mark = m.group(1)[0]
            if fence is None:
                fence = mark
            elif fence == mark:
                fence = None
            continue
        if fence is not None:
            continue
        m = _ATX.match(line)
        if m:
            out.append({"level": len(m.group(1)), "title": m.group(2).strip(),
                        "lineno": i + 1})
    return out


# 生效条件：title 真值时取其 strip 后小写，删去 `*[]() 与除 \w\s- 外字符，再把空白/下划线连成 "-" 并 strip("-")；title 为假值（含 None、空串）时按空串处理并返回 ""；
def _anchor(title):
    a = (title or "").strip().lower()
    a = re.sub(r"`|\*|\[|\]|\(|\)", "", a)
    a = re.sub(r"[^\w\s-]", "", a, flags=re.UNICODE)   # CJK 属 \w，保留
    return re.sub(r"[\s_]+", "-", a).strip("-")


# 生效条件：region_lines 逐行 strip 后跳过空行与 "---"，去掉行首 #+ 和 >|*- 标记，以空格连接成 text；返回 text[:limit]（limit 默认 MAX_SUMMARY；limit=0 返回 ""，limit=None 返回全文，limit='' 时切片抛 TypeError，负 limit 按负索引切片）；
def _summary(region_lines, limit=MAX_SUMMARY):
    """把一段正文压成一行摘要（去 markdown 噪声，不逐字保留）。"""
    parts = []
    for ln in region_lines:
        s = ln.strip()
        if not s or s == "---":
            continue
        s = re.sub(r"^#+\s*", "", s)
        s = re.sub(r"^[>|*-]\s*", "", s)
        parts.append(s)
    text = " ".join(parts).strip()
    return text[:limit]


# 生效条件：以 heads[i]["level"]-1 为需匹配层级向前回溯，返回按层级递减补齐的祖先标题列表（不含 heads[i] 自身）。
def _path_titles(heads, i):
    """第 i 个标题的祖先链（不含自身），按层级补齐。"""
    out, need = [], heads[i]["level"] - 1
    for k in range(i - 1, -1, -1):
        if heads[k]["level"] == need:
            out.insert(0, heads[k]["title"])
            need -= 1
            if need == 0:
                break
    return out


# 生效条件：直接以 lines、lineno、end 调用 codeindex.region_hash 并返回其结果；
def _region_hash(lines, lineno, end):
    # 唯一实现复用 codeindex.region_hash：两侧各写一份，漂移检测会悄悄失效。
    return codeindex.region_hash(lines, lineno, end)


# 生效条件：ext = suffix 真值时原样使用的 suffix，否则取 os.path.splitext(path)[1].lower()；ext 不在 SUFFIX 时抛 ValueError；在 SUFFIX 时把 source 按 "\n" 拆分，经 _body_start 与 _headings 得到标题，仅 level<=MAX_LEVEL 且非 small 的标题生成条目，小/过深子节摘要并入父摘要，返回 items；
def extract(source, path="", suffix=None):
    """抽取一份 md 的章节条目；按后缀分派。返回条目列表（可能为空）。

    条目字段与 `codeindex` 对齐（name/kind/lineno/end/hash/lang/precise/basis），
    另带文档专有：heading / heading_path / level / anchor / children。
    """
    ext = suffix or os.path.splitext(path)[1].lower()
    if ext not in SUFFIX:
        raise ValueError(f"无文档提取器（suffix={ext or '<none>'}）")
    lines = source.split("\n")
    heads = _headings(lines, _body_start(lines))

    # info 以 heads 序号为键：children 存的是 heads 序号，不能拿去过 secs 的下标。
    info = {}
    for i, h in enumerate(heads):
        end = len(lines)
        children = []
        for j in range(i + 1, len(heads)):
            if heads[j]["level"] <= h["level"]:
                end = heads[j]["lineno"] - 1
                break
            children.append(j)
        direct_end = (heads[i + 1]["lineno"] - 1) if i + 1 < len(heads) else len(lines)
        direct = lines[h["lineno"]:max(h["lineno"], min(direct_end, end))]
        info[i] = {"end": max(h["lineno"], end), "children": children, "direct": direct,
                   "small": len(_summary(direct)) < MIN_BODY and not children}

    items, seen = [], {}
    for i, h in enumerate(heads):
        if h["level"] > MAX_LEVEL or info[i]["small"]:
            continue          # 合并进父节点：父节点的 end 已覆盖其区间
        summary = _summary(info[i]["direct"])
        # 被合并进来的子节（自身过小，或层级过深从不单独建节点）：文字并入父节摘要，
        # 否则这些小节的正文只存在于父节的 ref 区间里，检索不到。
        merged = [_summary(info[k]["direct"], 80) for k in info[i]["children"]
                  if info[k]["small"] or heads[k]["level"] > MAX_LEVEL]
        merged = [m for m in merged if m]
        if merged:
            summary = (summary + "；" + "；".join(merged))[:MAX_SUMMARY]
        if not summary:
            summary = "（该节无直接正文，见子节）"
        parent = _path_titles(heads, i)
        heading_path = parent + [h["title"]]
        key = path + "#" + "/".join(heading_path)
        dup = seen.get(key, 0) + 1
        seen[key] = dup
        item = {
            "path": path, "name": h["title"], "heading": h["title"], "kind": KIND,
            "heading_path": heading_path, "level": h["level"],
            "anchor": _anchor(h["title"]), "parent": parent[-1] if parent else "",
            "lineno": h["lineno"], "end": info[i]["end"],
            "summary_parts": summary,
            "children": [heads[k]["title"] for k in info[i]["children"]],
            "dup": dup, "lang": LANG, "precise": True, "basis": BASIS,
        }
        item["hash"] = _region_hash(lines, item["lineno"], item["end"])
        items.append(item)
    return items


# --------------------------------------------------------------------------
# 渲染 / id
# --------------------------------------------------------------------------
# 生效条件：item.get("path") 缺键或为假值时 path 取 ""，top 取 path.split("/")[0] or "."（故空 path 时 top="."）；path 为真值时 top 取其 "/" 前首段，首段为空则 top="."；返回含 observation_position（大域=top）、time_window（[nodefile.FULL_TIME_WINDOW_MIN, nodefile.FULL_TIME_WINDOW_MAX]）、observation_tool、existence_constraint（以 path 拼入）的四槽字典；
def condition_space(item):
    """章节条目 → 条件空间四槽（纯函数，**唯一来源**）。

    与 `codeindex.condition_space` 同一职责、同一理由：`render` 的正文行与
    `refindex.add_items` 的 frontmatter 必须同源，否则 frontmatter 只剩单槽
    `observation_position`，`nodefile.condition_space_text(require_full=True)`
    恒返回 "" —— 条件空间等于没声明。改造前正文写的是「文档=X；检索…时」，
    是第三种方言，既进不了条件空间，也不可被 `_slot_overlap` 使用。

    时间槽给全时窗哨兵：文档章节条目声明的是「该文档里有这一节」，
    真值不随索引时刻衰减，不写成 1 小时观测窗。
    """
    path = item.get("path") or ""
    top = path.split("/")[0] or "."
    return {
        "observation_position": f"本地文档仓（大域={top}）",
        "time_window": [nodefile.FULL_TIME_WINDOW_MIN,
                        nodefile.FULL_TIME_WINDOW_MAX],
        "observation_tool": (f"{LANG}（md 章节切分，level≤{MAX_LEVEL}；"
                             f"只存标题+摘要，正文留在源文件）"),
        "existence_constraint": f"源文档 {path} 存在于本地仓且可读",
    }


# 生效条件：item 含 heading、path、lineno、end、anchor 键时渲染 7 行 CCG 文本（第2行取 condition_space(item) 文本），item.get("parent") 或 "" 假值回落 "（顶层章节）"，item.get("summary_parts") 假值回落 "（该节无直接正文，见子节）"，item.get("children") 假值回落空列表且不追加子节行，children 非空时追加 "# 子节：" + 前 12 个；返回以 "\n" 连接的行串；
def render(item):
    """章节条目 → CCG 6 行正文（可被 search 命中，不含全文）。

    **必须渲染成 CCG**：`judge_qualification` 第一步查 ccg_completeness 的 5 要素，
    缺任一即直接判 BLINDSPOT（与 codeindex.render 同一个坑）。
    """
    heading = item["heading"]
    path = item["path"]
    parent = item.get("parent") or ""
    summary = item.get("summary_parts") or "（该节无直接正文，见子节）"
    sub = f"父章节：{parent}" if parent else "（顶层章节）"
    children = item.get("children") or []
    lines = [
        f"# 功能名：{heading}",
        f"# 生效条件：{nodefile.condition_space_text(condition_space(item))}",
        f"# 子功能：{sub}",
        f"# 执行：{summary[:MAX_DOC]}",
        (f"# 验证方式：{BASIS}（以原始文档为准；"
         f"区间 {path} L{item['lineno']}-L{item['end']}）"),
        f"# 不适用条件：其它文档的同名标题（本条目属于 {path}#{item['anchor']}）",
        f"# 位置：{path}#{item['anchor']}:{item['lineno']}-{item['end']}"
        f"（{item.get('lang')}，precise=True）",
    ]
    if children:
        lines.append("# 子节：" + "；".join(children[:12]))
    return "\n".join(lines)


# 生效条件：以 item["path"] + "#" + "/".join(item["heading_path"]) 为 key，item.get("dup", 1)（缺键取 1）大于 1 时追加 "#" + item["dup"]，返回 "doc_" + sha1(key utf-8) hexdigest 前 12 位；
def node_id(item):
    """稳定 id：path#heading_path 的短哈希（重复索引幂等；同名用 dup 区分）。"""
    key = item["path"] + "#" + "/".join(item["heading_path"])
    if item.get("dup", 1) > 1:
        key += f"#{item['dup']}"
    return "doc_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


# ==========================================================================
# fence 真源绑定（§3.5）：条件卡 ↔ Markdown 真源的「往返列」
#
# 往返列 = 真源（root + path）+ 定位（anchor / heading_path）+ 行位（lineno/end）
# + 校验（hash）。**行位是易腐化量，键不含行位**：在章节上方插一段话会让整篇行号
# 位移，但键 `path#heading_path` 不变——故「同一章节」的匹配一律走键，行位只用于
# 回读原文与漂移判定。写侧唯一入口是 `refindex._doc_ref`（与索引同源，避免第二份
# 列口径）；本节只补读侧：取列 / 校验 / 造键 / 反查行位。
#   · 正向：卡片 → 真源（`doc_ref.lineno/end` + `refindex.read_ref` 回读原文区间）
#   · 反向：真源行 → 卡片（`locate`；对账器 `--at path:line` 即此接口）
# ==========================================================================

#: 必需列：真源（root/path）+ 定位（anchor）+ 行位（lineno/end）+ 校验（hash）
BINDING_FIELDS = ("root", "path", "anchor", "lineno", "end", "hash")
#: 附加列：有则参与更精确匹配与人读，缺省不算绑定失败
BINDING_OPTIONAL = ("heading_path", "heading", "level", "lang", "precise")


# 生效条件：node 为 cg.get 产物（含 frontmatter 子字典）或 frontmatter dict 本身，且其 doc_ref 为 dict 时，返回按 BINDING_FIELDS + BINDING_OPTIONAL 投影的列值 dict（缺列以 None 占位）；非 dict / 无 doc_ref 返回 None。
def binding_of(node):
    """取一条条件卡的往返列；**非索引节点返回 None**（不猜、不补默认值）。"""
    fm = node
    if isinstance(node, dict) and isinstance(node.get("frontmatter"), dict):
        fm = node["frontmatter"]
    if not isinstance(fm, dict):
        return None
    ref = fm.get("doc_ref")
    if not isinstance(ref, dict) or not ref:
        return None
    return {k: ref.get(k) for k in BINDING_FIELDS + BINDING_OPTIONAL}


# 生效条件：b 为 dict 且 heading_path 为非空 list/tuple 时返回 path#join(heading_path, '/')，否则回落 path#anchor；b 非 dict 返回空串。
def binding_key(b):
    """稳定键 `path#heading_path`：**不含行位**（真源重排只动行位、不动键）。"""
    if not isinstance(b, dict):
        return ""
    path = str(b.get("path") or "")
    hp = b.get("heading_path")
    if isinstance(hp, (list, tuple)) and hp:
        return path + "#" + "/".join(str(x) for x in hp)
    return path + "#" + str(b.get("anchor") or "")


# 生效条件：b 为 dict 时返回 'path#anchor'（与 render 正文里的「本条目属于」逐字同源）；非 dict 返回空串。
def binding_slug(b):
    """人读定位串 `path#anchor`——与 `render` 正文里的「本条目属于」同源。"""
    b = b if isinstance(b, dict) else {}
    return f"{b.get('path') or ''}#{b.get('anchor') or ''}"


# 生效条件：b 为 dict 时逐列校验（缺列 / 类型错 / 行位越界），返回 {"ok": bool, "issues": [str, ...]}；**不抛异常**——对账要逐条报告，不能因一条坏数据中断全库；行位仅在列齐且类型对时才判，避免级联噪声。
def validate_binding(b):
    """校验往返列形状。**不抛异常**：对账逐条报告，不能一条坏数据中断全库。"""
    if not isinstance(b, dict):
        return {"ok": False, "issues": ["绑定不是字典（该节点无 doc_ref）"]}
    issues = []
    for k in BINDING_FIELDS:
        if b.get(k) in (None, ""):
            issues.append(f"缺列 {k}")
    for k in ("root", "path", "anchor", "hash"):
        v = b.get(k)
        if v not in (None, "") and not isinstance(v, str):
            issues.append(f"{k} 应为字符串，实为 {type(v).__name__}")
    if not issues:
        try:
            lo, hi = int(b["lineno"]), int(b["end"])
        except (TypeError, ValueError):
            issues.append("行位不是整数")
        else:
            if lo < 1:
                issues.append(f"lineno 越界（{lo} < 1）")
            if hi < lo:
                issues.append(f"end 早于 lineno（{lo}-{hi}）")
    return {"ok": not issues, "issues": issues}


# 生效条件：old/new 任意为 dict 或假值；按 (path, anchor, heading_path, lineno, end, hash) 固定顺序返回取值不同的列名列表（空列表=同一章节同一行位），任一侧假值按空 dict 处理。
def binding_drift(old, new):
    """旧往返列 vs 新往返列 → 变化列名（顺序固定，供报告与测试断言）。"""
    old, new = old if isinstance(old, dict) else {}, new if isinstance(new, dict) else {}
    return [k for k in ("path", "anchor", "heading_path", "lineno", "end", "hash")
            if old.get(k) != new.get(k)]


# 生效条件：items 为 extract 产出的条目序列、lineno 可转 int；返回覆盖该行的条目中 **lineno 最大者**（嵌套即最内层，h3 优于其父 h2）；不可转值或无可覆盖条目返回 None。
def locate(items, lineno):
    """反向定位：真源第 `lineno` 行 → 覆盖它的条目（嵌套取**最内层**）。

    区间闭合：标题行算本节；多层嵌套时取 `lineno` 最大者即最内层。
    """
    try:
        ln = int(lineno)
    except (TypeError, ValueError):
        return None
    hit = None
    for it in items or []:
        lo, hi = it.get("lineno"), it.get("end")
        if lo is None or hi is None:
            continue
        try:
            lo, hi = int(lo), int(hi)
        except (TypeError, ValueError):
            continue
        if lo <= ln <= hi and (hit is None or lo > int(hit["lineno"])):
            hit = it
    return hit


# 生效条件：以 root 为根 os.walk，patterns 假值回落 SUFFIX；files 达到 max_files 或 items 达到 max_items 时提前返回并置 stats["truncated"]/truncated_reason；fresh 非 None 且 fresh(rel, fp) 为真时跳过该文件读盘并计 skipped_unchanged；on_file 非 None 且 open/extract 成功后以 (rel, fp, got) 回调；名字在 SKIP_DIRS 的目录仅剪枝不记录，skip_dirs 经 codeindex.skip_matcher 命中的目录剪枝并记入 stats["skipped_dirs"]；返回 (items, errors, stats)。
def index_dir(root, patterns=None, max_files=500, max_items=2000,
              fresh=None, on_file=None, skip_dirs=None):
    """按大域（目录）遍历 md，产出 `(items, errors, stats)`。零 LLM。

    stats 语义与 `codeindex.index_dir` 一致：`truncated`/`truncated_reason` 显式上报
    （截断不静默），`skipped_suffixes` 列出扫到但没被索引的后缀（覆盖缺口可审计）。

    `fresh(rel, fp)` / `on_file(rel, fp, items)` 是给 `refindex.Ledger` 留的增量钩子
    （默认 None → 行为与改造前逐字一致）：未变文件不读盘、计入 `skipped_unchanged`。

    `skip_dirs` 是**追加**排除，复用 `codeindex.skip_matcher`（唯一实现，避免两条
    索引链路口径漂移）：命中的目录整棵剪掉、不计入 `files`。本仓的实例就是
    `docs/experiments/`——`.gitignore` 已整目录忽略、物理却仍有 2358 个 md 的实验
    产物，会把 `max_files` 撑爆并把「索引不全」变成常态。排掉了哪些目录写进
    `stats["skipped_dirs"]`，排除与截断一样**不许静默**。
    """
    pats = tuple(patterns or SUFFIX)
    hit_skip, skip_rules = codeindex.skip_matcher(skip_dirs)
    items, errors, files = [], [], 0
    seen_suffix = set()
    stats = {"root": root, "patterns": list(pats), "files": 0, "truncated": False,
             "truncated_reason": "", "max_files": max_files, "max_items": max_items,
             "skipped_suffixes": [], "skipped_unchanged": 0,
             "skip_dirs": list(skip_rules), "skipped_dirs": []}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        keep = []
        for d in dirnames:
            if d in SKIP_DIRS:
                continue
            child = f"{rel_dir}/{d}" if rel_dir else d
            if hit_skip is not None and hit_skip(child, d):
                stats["skipped_dirs"].append(child)
                continue
            keep.append(d)
        dirnames[:] = keep
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            seen_suffix.add(ext)
            if not fn.lower().endswith(pats):
                continue
            if files >= max_files or len(items) >= max_items:
                stats["truncated"] = True
                stats["truncated_reason"] = (
                    f"files={files}>=max_files={max_files}"
                    if files >= max_files else
                    f"items={len(items)}>=max_items={max_items}")
                stats["files"] = files
                stats["skipped_suffixes"] = sorted(
                    s for s in seen_suffix if s and s not in pats)[:12]
                return items, errors, stats
            files += 1
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root).replace("\\", "/")
            if fresh is not None and fresh(rel, fp):
                stats["skipped_unchanged"] += 1
                continue
            try:
                with open(fp, encoding="utf-8") as f:
                    src = f.read()
                got = extract(src, rel)
                items.extend(got)
                if on_file is not None:
                    on_file(rel, fp, got)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                errors.append(f"{rel}: {exc}")
            if len(items) >= max_items:
                stats["truncated"] = True
                stats["truncated_reason"] = f"items={len(items)}>=max_items={max_items}"
                stats["files"] = files
                stats["skipped_suffixes"] = sorted(
                    s for s in seen_suffix if s and s not in pats)[:12]
                return items, errors, stats
    stats["files"] = files
    stats["skipped_suffixes"] = sorted(s for s in seen_suffix if s and s not in pats)[:12]
    return items, errors, stats