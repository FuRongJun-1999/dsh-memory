"""正文指纹（bottom-k minhash）——**跨进程去重用，不解密**。

账 127（2026-10-29）的根因不是"阈值太松"，是**读不到**：`forgetting.redundancy()`
逐个候选调 `cg.get(nid)`，而 `MdCG.get` 先过 `_readable`（`sensitivity` 与
`session`/`actor` 绑定）；`app/memstore.py` 与 cron 用的主体 `actor="system"`
在 1,482 条 contextual 节点里 **0 条可读**（实测 `/tmp/probe-a127.py`），
于是"去重"实际等于"跟 0–2 条比"，而返回值里 `compared` 只报成功比过的条数，
不报被跳过多少 ⇒ 静默。

修法：写入时把正文的 **bottom-k minhash 指纹**存进索引条目（`sk`），
去重时**只读指纹**做 Jaccard 估计，需要精确值再解密那一条。

不可逆性：minhash 只保留 bigram 哈希的最小 k 个值，**不能反推正文**；
但它确实会泄露"两段文本是否相似"，故只写进索引（`_index.json` 已含正文哈希
`content_hash`，同一泄露面），不写 frontmatter、不进检索结果。
"""

from __future__ import annotations

import base64
import hashlib
import struct

K = 32  # 指纹长度（32 个 32-bit 最小哈希）

# 与 `forgetting.payload()` 同形的模板标签（两边各自归一，指纹互比时口径一致）
_TEMPLATE_LABELS = (
    "功能名：", "功能名:", "生效条件：", "生效条件:", "子功能：", "子功能:",
    "执行：", "执行:", "验证方式：", "验证方式:", "不适用条件：", "不适用条件:",
    "结果：", "结果:", "现场：", "现场:",
)


def norm(text: str) -> str:
    """剥掉 markdown 标题前缀与 CCG 模板标签，留内容骨架（与 forgetting.payload 同形）。"""
    out = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            s = s.lstrip("#").strip()
            for lab in _TEMPLATE_LABELS:
                if s.startswith(lab):
                    s = s[len(lab):].lstrip("：: ").strip()
                    break
        if s:
            out.append(s)
    return "\n".join(out)


def _h(b: bytes) -> int:
    return int.from_bytes(hashlib.blake2b(b, digest_size=4).digest(), "big")


def grams(text: str) -> set:
    """2-gram 集合（去空白），与 `mdcg.bigrams` 同口径。"""
    s = "".join((text or "").split())
    if not s:
        return set()
    if len(s) <= 1:
        return {s}
    return {s[i:i + 2] for i in range(len(s) - 1)}


def sig(text: str, k: int = K) -> str:
    """正文 → base64(N×uint32 升序最小哈希)。空正文返回 ""。"""
    g = grams(norm(text))
    if not g:
        return ""
    hs = sorted({_h(x.encode("utf-8")) for x in g})[:k]
    return base64.b64encode(struct.pack(">%dI" % len(hs), *hs)).decode("ascii")


def unpack(s: str) -> list:
    if not s:
        return []
    try:
        raw = base64.b64decode(s.encode("ascii"))
    except Exception:
        return []
    n = len(raw) // 4
    return list(struct.unpack(">%dI" % n, raw[:n * 4]))


def est_jaccard(a: str, b: str) -> float:
    """Two bottom-k 估计：两串指纹并起来取前 k 小，看交集占比。"""
    xa, xb = unpack(a), unpack(b)
    if not xa or not xb:
        return 0.0
    sa, sb = set(xa), set(xb)
    k = min(len(xa), len(xb))
    merged = sorted(sa | sb)[:k]
    if not merged:
        return 0.0
    hit = sum(1 for v in merged if v in sa and v in sb)
    return hit / float(len(merged))
