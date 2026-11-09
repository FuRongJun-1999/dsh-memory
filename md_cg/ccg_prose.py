"""把 CCG 字段堆渲染成人话（只读展示层，不改存储、不改判据）。

背景（2026-11-06）：库里的记忆有两套写法并存——
  · 散文卡（蒸馏产物，`## 做了什么 / ## 结论 …`）；
  · CCG 字段堆（`# 功能名：… # 生效条件：… # 子功能：…`，历史写入惯例）。
第二种对机器友好、对人难读：检索回包直接把字段名当正文吐出来，人看到的是
「# 验证方式：同模型自验 # 不适用条件：…」。本模块只做**展示**：把同一份内容
重新排成 2–4 句自然语言，塞进回包的新键 `plain`；`content` 原样不动，任何按
字段名取值的代码不受影响。

判据（test_ccg_prose.py）：字段堆能出句子、散文卡原样返回、空内容返回空串、
超长截断带省略号、绝不抛异常（展示层坏了也不许拖垮检索）。
"""

import re

_FIELD = re.compile(r"^\s*#\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_]{1,11})\s*[：:]\s*(.*)$", re.M)
_SECTION = re.compile(r"^\s*##\s*(.+?)\s*$", re.M)

# 字段 → 句子模板；顺序即渲染顺序（先说什么后说什么）
_ORDER = ("功能名", "主题", "生效条件", "子功能", "验证方式", "不适用条件", "假设")
_LEAD = {
    "功能名": "这条讲的是「%s」。",
    "主题": "这条的主题是「%s」。",
    "生效条件": "什么时候用：%s",
    "子功能": "具体做法：%s",
    "验证方式": "依据：%s",
    "不适用条件": "不适用：%s",
    "假设": "前提假设：%s",
}
_DEFAULT_MAX = 420


def _clean(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"^[：:，,、。；;\-\s]+", "", text)
    return text.rstrip("，,、；; ")


def _clip(text, limit):
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip("，,、；; ") + "…"


def _from_fields(body):
    """字段堆 → 人话。顺序：标题句 → 正文那句 → 什么时候用 → 具体做法 → 依据 → 其余。

    正文（不属于任何字段的行）放前面，因为它是这条记忆真正想说的话；字段是补充。
    实测样例：`# 生效条件：…` 后面紧跟正文时，若字段先说，会读成
    「什么时候用：… NapCat 被踢的根因是…」，两句话黏在一起没人看得懂。
    """
    fields = {}
    body_lines = []
    cur = None
    for line in body.splitlines():
        m = _FIELD.match(line)
        if m:
            cur = m.group(1)
            fields.setdefault(cur, []).append(m.group(2))
            continue
        s = line.strip()
        if not s:
            continue
        if cur is not None and line[:1].isspace():
            fields[cur].append(s)   # 缩进行 = 上一条字段的续行
        else:
            body_lines.append(s)
    parts = []
    for name in ("功能名", "主题"):
        if name in fields:
            val = _clean(" ".join(fields.pop(name)))
            if val:
                parts.append(_LEAD[name] % val)
    if body_lines:
        parts.append(_clean(" ".join(body_lines)))
    for name in ("生效条件", "子功能", "验证方式", "不适用条件", "假设"):
        if name not in fields:
            continue
        val = _clean(" ".join(fields.pop(name)))
        if val:
            parts.append(_LEAD[name] % val)
    for name, vals in fields.items():
        val = _clean(" ".join(vals))
        if val:
            parts.append("%s：%s" % (name, val))
    return " ".join(parts)


def _from_sections(body):
    parts = []
    title = None
    buf = []
    for line in body.splitlines():
        m = _SECTION.match(line)
        if m:
            if title and buf:
                parts.append("%s：%s" % (title, _clean(" ".join(buf))))
            title, buf = m.group(1), []
            continue
        if line.strip():
            buf.append(line.strip())
    if title and buf:
        parts.append("%s：%s" % (title, _clean(" ".join(buf))))
    elif buf:
        parts.append(_clean(" ".join(buf)))
    return " ".join(parts)


def render(content, max_chars=_DEFAULT_MAX):
    """CCG 字段堆 / 分节散文 → 一段人话；空内容返回空串；永不抛。"""
    try:
        body = content or ""
        if not body.strip():
            return ""
        if _FIELD.search(body):
            text = _from_fields(body)
            if not text:
                text = _from_sections(body)
        elif _SECTION.search(body):
            text = _from_sections(body)
        else:
            text = _clean(body)
        return _clip(text, max_chars or _DEFAULT_MAX)
    except Exception:                                  # noqa: BLE001 —— 展示层不拖垮检索
        return ""
