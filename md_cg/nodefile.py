# -*- coding: utf-8 -*-
"""md 认知图 · 节点文件格式（YAML-ish frontmatter + CCG 正文）

格式：
    ---
    id: node_x
    tags: ["a","b"]
    verification_basis: "compiler"   # 验证方式（frontmatter 侧）
    non_applicable_conditions: [...]  # 不适用条件
    ---
    # 功能名：...
    # 生效条件：...（可隐含——常用条件默认省略）
    # 子功能：...
    # 执行：...
    # 验证方式：...（白箱要求"能被验证才能被信任"）
    # 不适用条件：...（白箱第 1 篇第 10 章从 28%→88% 的关键改进）
    正文

解析要点（原型代码 md_cg_prototype.py 的缺陷修复）：
原型用 `re.match(r"---\\n(.*?)\\n---\\n(.*)", txt, re.S)` 非贪婪匹配，正文里只要
出现一行 `---`（markdown 分隔线在知识卡里极常见）就会把正文前半截当成 frontmatter，
字段全丢。这里改为：frontmatter 的所有值都 JSON 序列化（因此不含裸换行），
只切「开头 --- 之后的第一个 \\n---\\n」，正文里的 --- 一律不参与切分。

CCG 5 要素的语义对应（白箱第 1 篇第 17 章）：
- 适用条件 → MARKS 第 2 行「生效条件」（可隐含）
- 子功能   → MARKS 第 3 行
- 执行     → MARKS 第 4 行
- 验证方式 → MARKS 第 5 行（frontmatter 同步存 verification_basis 做可查询化）
- 不适用条件 → MARKS 第 6 行（frontmatter 同步存 non_applicable_conditions）

第 1 行「功能名」是 markdown 风格的标题，不在 5 要素之列但作为可读标识保留。
用户许可 MARKS 中内容可前置，条件可隐含——故顺序不强制。
"""
import json

_DELIM = "---"
# 完整的 6 行 MARKS：功能名（标题）+ 5 要素（条件、子功能、执行、验证、不适用）。
# 「验证方式」与「不适用条件」是白箱的关键新增，缺则不可证 ACCEPT/REJECT。
CCG_MARKS = ("功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件")
CCG_REQUIRED = ("功能名", "子功能", "执行", "验证方式", "不适用条件")  # 5 要素缺一不可
# 外部验证基底的可取值（frontmatter.verification_basis）
VERIFICATION_BASIS = ("compiler", "test", "measurement", "formal_proof", "data", "other")


def dumps(frontmatter: dict, content: str) -> str:
    lines = [_DELIM]
    for k in sorted(frontmatter):
        v = frontmatter[k]
        # 一律 JSON 序列化：值内不会出现裸换行，切分才可靠；数字/字符串也保持可读
        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    lines.append(_DELIM)
    body = content if content.endswith("\n") else content + "\n"
    return "\n".join(lines) + "\n" + body


def loads(text: str):
    """返回 (frontmatter dict, content str)。非法格式返回 ({}, 原文)。"""
    if not text.startswith(_DELIM + "\n"):
        return {}, text
    rest = text[len(_DELIM) + 1:]
    end = rest.find("\n" + _DELIM + "\n")
    if end < 0:
        return {}, text
    head, content = rest[:end], rest[end + len(_DELIM) + 2:]
    fm = {}
    for line in head.split("\n"):
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        try:
            fm[k] = json.loads(v)
        except ValueError:
            fm[k] = v
    return fm, content


def ccg_completeness(content: str) -> dict:
    """CCG 5 要素齐全度——白箱可审计性的量化指标。

    「生效条件」可隐含（用户许可：常用条件默认省略），
    故「5 要素全在」的判定用 CCG_REQUIRED（不含生效条件）。
    6 行都齐全才报 complete（含可隐含的生效条件）。
    """
    all_present = [m for m in CCG_MARKS if f"# {m}：" in content or f"# {m}:" in content]
    required_present = [m for m in CCG_REQUIRED
                        if f"# {m}：" in content or f"# {m}:" in content]
    return {
        "present": all_present,
        "required_present": required_present,
        # 完整 = 5 要素全在（生效条件可隐含）——这是资格判定的硬门槛
        "complete": len(required_present) == len(CCG_REQUIRED),
        # 全齐 = 6 行都在（包括可隐含的生效条件）
        "all_present": len(all_present) == len(CCG_MARKS),
        "ratio": len(required_present) / len(CCG_REQUIRED),
    }


def verification_basis_valid(fm: dict) -> bool:
    """frontmatter.verification_basis 是否落在可接受枚举里。"""
    vb = fm.get("verification_basis")
    if vb is None:
        return False
    return vb in VERIFICATION_BASIS


def has_non_applicable(content: str) -> bool:
    """是否声明了不适用条件——REJECT 路径成立的必要条件。

    没有不适用条件的节点在白箱下不能 REJECT（无法证明「不适用」），
    只能 ACCEPT 或 BLINDSPOT。这是第 1 篇第 10 章从 28%→88% 的关键。
    """
    return "# 不适用条件：" in content or "# 不适用条件:" in content