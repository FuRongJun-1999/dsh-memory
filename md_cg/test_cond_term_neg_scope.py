# -*- coding: utf-8 -*-
"""#753 续：否定词 + **非连接字**（使用/采用/用）作用域的守卫。

背景
====
`_negated_at` 原先把「否定词与被否定成分之间」的允许字符限定为连接字
（`NEG_LINK_CHARS` = 的/这/种/是/…）。于是：

    条件写 `PE`，问句 `这里未使用 pe 估值`
      #761 归一前：`pe` 不命中 `PE` → DEFER   ✓
      #761 归一后：命中          → ACCEPT       ✗（否定句被当成"条件已确认"）

缺口在**语义**：`未`否定的是动词`使用`，`pe估值`是`使用`的宾语。
宾语被否定动词管辖，故仍是"条件未确认"。只认连接字会把这类全漏掉。

本文件钉三件事
==============
1. **动词字集生效**：`未使用X` / `不是用X` / `没有使用X` / `未采用X` 等必须判为否定。
2. **不误伤肯定句**：`使用X` / `用X`（无否定词）必须判为命中。
3. **不碰 #362 既有语义**：`不适合梅雨季节的施工` **照旧命中**（`适合`不是动词字，
   否定词作用的是`适合`而非`梅雨季节`）；A-not-A（`是不是X`）照旧命中。

判别力：删掉 `NEG_VERB_CHARS` 的任一字符 → 第 1 组红。
把 `NEG_VERB_CHARS` 塞进 `NEG_LINK_CHARS`（合并两表）→ 结构断言红。
"""
import sys

import md_cg.mdcg as M
from md_cg.mdcg import MdCG, neg_condition_hits

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("  FAIL  %s" % label)


print("=" * 68)
print("R14. 否定词 + 非连接字（虚化动词）作用域")
print("=" * 68)

# ---------------------------------------------------------------- R14a 结构
# 两表**分开**存放：连接字（纯语法）与虚化动词（承载语义）词性不同，
# 合并会掩盖「否定词作用于动作、动作的宾语才是词项」这层结构。
ok(hasattr(M, "NEG_VERB_CHARS"), "R14a NEG_VERB_CHARS 应存在（独立于 NEG_LINK_CHARS）")
ok(hasattr(M, "NEG_SCOPE_CHARS"), "R14a NEG_SCOPE_CHARS 应存在（判据准入集的单点）")
ok(
    set(M.NEG_SCOPE_CHARS) == set(M.NEG_LINK_CHARS) | set(M.NEG_VERB_CHARS),
    "R14a NEG_SCOPE_CHARS 必须恰为 连接字 ∪ 虚化动词字（不多不少）",
)
ok(
    not (set(M.NEG_VERB_CHARS) <= set("是这那该此种个些的了在为之其")),
    "R14a 虚化动词字不得全部落在连接字表内（否则分表无意义）",
)
# 逐字符断言，防止有人写成多字串（frozenset 里多字串永不匹配单个字符）
ok(
    all(len(c) == 1 for c in M.NEG_VERB_CHARS),
    "R14a NEG_VERB_CHARS 必须逐**单字**存放（多字串在逐字符判据里永不匹配）",
)
for ch in "使用采":
    ok(ch in M.NEG_VERB_CHARS, "R14a NEG_VERB_CHARS 应含 %r" % ch)

# ------------------------------------------------------- R14b 否定句须判否定
NEG_SENTS = [
    ("未使用pe估值", "pe"),
    ("不是用pe估值", "pe"),
    ("没有使用pe估值", "pe"),
    ("未采用pe估值", "pe"),
    ("不是采用pe估值", "pe"),
    ("未使用这种pe估值", "pe"),      # 动词 + 连接字混合
    ("没有用这个pe估值", "pe"),      # 动词 + 连接字混合
]
for sent, needle in NEG_SENTS:
    i = sent.find(needle)
    ok(i >= 0, "R14b 用例自检：%r 应含 %r" % (sent, needle))
    if i < 0:
        continue
    ok(M._negated_at(sent, i), "R14b %r 中 %r 应判为被否定" % (sent, needle))

# ---------------------------------------------- R14c 肯定句不得被误判否定
POS_SENTS = [
    ("使用pe估值", "pe"),
    ("用pe估值", "pe"),
    ("采用pe估值", "pe"),
    ("pe估值", "pe"),
]
for sent, needle in POS_SENTS:
    i = sent.find(needle)
    ok(i >= 0, "R14c 用例自检：%r 应含 %r" % (sent, needle))
    if i < 0:
        continue
    ok(not M._negated_at(sent, i), "R14c %r 中 %r 不应被判否定" % (sent, needle))

# ------------------------------------------------- R14d #362 既有语义不变
# 这是**回归防线**：本补丁只扩字符集，不改判定结构。
# `不适合梅雨季节的施工`：否定词是`不`，其后`适合`不在准入集 ⇒ 仍判「未被否定」。
ok(
    bool(neg_condition_hits(["梅雨季节"], "不适合梅雨季节的施工", "")),
    "R14d `不适合梅雨季节的施工` 必须**照旧命中**（#362 语义，不得因本补丁收紧）",
)
ok(
    not bool(neg_condition_hits(["梅雨季节"], "不是梅雨季节", "")),
    "R14d `不是梅雨季节` 仍须判为否定（取消命中）",
)
ok(
    not bool(neg_condition_hits(["梅雨季节"], "不是这种梅雨季节", "")),
    "R14d `不是这种梅雨季节` 仍须判为否定",
)
ok(
    bool(neg_condition_hits(["梅雨季节"], "是不是梅雨季节", "")),
    "R14d A-not-A（`是不是X`）仍须命中（不得被本补丁误判为否定）",
)

# ------------------------------------- R14e 端到端：条件面在否定句上须 DEFER
CONTENT = """# 功能名：T 节点
# 生效条件：PE
# 子功能：x
# 执行：y
# 验证方式：z
# 不适用条件：无
"""
NODE = {
    "frontmatter": {"non_applicable_conditions": [], "verification_basis": "单测"},
    "content": CONTENT,
}
for q in ["未使用 pe 估值", "不是用 pe 估值", "没有使用 pe 估值",
          "未采用 pe 估值", "不是采用 pe 估值"]:
    st = MdCG.judge_qualification(NODE, q, None)["state"]
    ok(st == "DEFER", "R14e 否定句 %r 应 DEFER（实得 %s）" % (q, st))

# 肯定句必须保持 ACCEPT（否则是矫枉过正）
for q in ["pe 估值", "使用 pe 估值", "用 pe 估值"]:
    st = MdCG.judge_qualification(NODE, q, None)["state"]
    ok(st == "ACCEPT", "R14e 肯定句 %r 应 ACCEPT（实得 %s）" % (q, st))

print()
print("=" * 68)
print("cond_term_neg_scope: %d passed, %d failed" % (PASS, FAIL))
print("=" * 68)
sys.exit(1 if FAIL else 0)
