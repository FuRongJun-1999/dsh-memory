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

from . import codeindex

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


def _body_start(lines):
    """跳过开头 YAML frontmatter，返回正文起始行下标（0 基）。"""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


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


def _anchor(title):
    a = (title or "").strip().lower()
    a = re.sub(r"`|\*|\[|\]|\(|\)", "", a)
    a = re.sub(r"[^\w\s-]", "", a, flags=re.UNICODE)   # CJK 属 \w，保留
    return re.sub(r"[\s_]+", "-", a).strip("-")


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


def _region_hash(lines, lineno, end):
    # 唯一实现复用 codeindex.region_hash：两侧各写一份，漂移检测会悄悄失效。
    return codeindex.region_hash(lines, lineno, end)


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
        f"# 生效条件：文档={path}；检索「{heading}」或正文关键词时",
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


def node_id(item):
    """稳定 id：path#heading_path 的短哈希（重复索引幂等；同名用 dup 区分）。"""
    key = item["path"] + "#" + "/".join(item["heading_path"])
    if item.get("dup", 1) > 1:
        key += f"#{item['dup']}"
    return "doc_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def index_dir(root, patterns=None, max_files=500, max_items=2000):
    """按大域（目录）遍历 md，产出 `(items, errors, stats)`。零 LLM。

    stats 语义与 `codeindex.index_dir` 一致：`truncated`/`truncated_reason` 显式上报
    （截断不静默），`skipped_suffixes` 列出扫到但没被索引的后缀（覆盖缺口可审计）。
    """
    pats = tuple(patterns or SUFFIX)
    items, errors, files = [], [], 0
    seen_suffix = set()
    stats = {"root": root, "patterns": list(pats), "files": 0, "truncated": False,
             "truncated_reason": "", "max_files": max_files, "max_items": max_items,
             "skipped_suffixes": []}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
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
            try:
                with open(fp, encoding="utf-8") as f:
                    src = f.read()
                items.extend(extract(src, rel))
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
