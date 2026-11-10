#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""R-524 · 工具 schema ↔ 分发层读键对账（scripts/check_schema_keys.py）

【为什么有它】
`mcp_server.TOOLS` 里每个工具的 `inputSchema.properties` 是**给调用方看的契约**，
而真正读哪个键由分支里的 `a.get("x")` 决定。两者各写一份、无人对账 ⇒ 审计数出
**11 处不一致**：

- **schema 有、分发层不读**：调用方按契约传了键，实现静默忽略（最危险：以为生效了）；
- **分发层读、schema 没写**：调用方按契约猜不到这个键存在（`patterns` / `skip_dirs`
  这类**能大幅改变行为**的键，不传就是全库）。

性质与 R-523（`op_table.params` 对 handler）相同，只是那一层对的是「哪个键属于哪个 op」，
这一层对的是「哪个键属于哪个工具」。两层的真源不同，不能合并。

【判什么】
对 31 个 `mdcg_*` 工具，逐个取
  ① `inputSchema.properties` 的键集（丢弃嵌套 `properties` 里的子键，只看第一层）
  ② 该工具分支里 `a.get("x")` / `a["x"]` 的键集
并报出两个差集。

【不判什么（三类刻意留白）】
- **不判 `cg` 工具的 op 参数**：它走 `op_table` 的 38 个 op，由
  `check_op_table_parity.py` 与 R-523 的 params 面负责，本脚本不重复。
- **不判「分支被发现得对不对」**：分支靠 `if name == "mdcg_xxx":` 的文本定位，
  若某工具的实现抽到别的函数里，本脚本会**漏看它的读键**（判据的已知盲区）。
- **不判 schema 的 `required` / 类型 / 默认值**：那是另一维，混进来会让差集噪声压不住。

【退出码】0 = 两个差集都在白名单内；1 = 有新差异；2 = 自身故障
【负控】在任一分支里加一个 `a.get("__negctl__")` ⇒ 该工具应报「schema 未声明」。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP = os.path.join(ROOT, "md_cg", "mcp_server.py")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

#: 已知差异（审计已登记、处置留待逐条决定）。**新增差异必须在这里登记或修掉。**
#: 键 = 工具名；val = (schema有但不读 的键集, 读但schema没写 的键集, 理由)
#: 已登记差异。**只登记「schema 有、分发层不读」这一类**，且理由统一为「判据盲区」：
#: 这些键是**整体把 `a` 交给辅助函数**时被读的，本脚本的正则看不见：
#:   · `mdcg_remember` 的 `dedupe` → `writepipe._gate_dedupe({"a": {**a, ...}})`
#:   · `mdcg_remember` 的 `spatial` → `**_spatial_kw(a)`
#:   · `mdcg_remember` 的 `session` → `_attribution_session_of(self, ...)`
#: 「分发层读、schema 没写」这一类**不设白名单** —— 那是真缺陷，必须修。
KNOWN = {
    "mdcg_remember": ({"dedupe", "session", "spatial"}, set(), "整体 a 传辅助函数，判据看不见"),
    # `mdcg_search`：这 4 个**不是调用方参数**，是工具内部的判据键 ——
    #   · `op` / `node_id` / `validity` 一起决定「能不能用 query 缓存」：
    #     `None if ("node_id" in a or a.get("op") or a.get("validity")) else cg._hotcache_tool`
    #   · `index_gen` 进缓存键（索引代际变了就换桶）
    #   · `env_switch` 读环境开关；`identity` 只用于「有没有传」的存在性判定
    # 它们写进 schema 反而会误导（调用方传了没意义）。
    "mdcg_search": (set(), {"op", "index_gen", "env_switch", "identity"},
                    "内部判据键，非调用方参数"),
}


def _tools():
    src = io.open(MCP, encoding="utf-8").read()
    tree = compile(src, MCP, "exec", flags=0)
    ns = {}
    # 只取 TOOLS 常量：不 exec 整个模块，用正则切出 `TOOLS = [...]` 再 eval
    m = re.search(r"^TOOLS = \[", src, re.M)
    if not m:
        raise SystemExit("✗ 找不到 TOOLS 常量")
    i = m.start()
    depth, j = 0, i + len("TOOLS = ")
    while j < len(src):
        if src[j] == "[":
            depth += 1
        elif src[j] == "]":
            depth -= 1
            if depth == 0:
                j += 1
                break
        j += 1
    # `properties` 里可能有引用常量的表达式 —— 退化为正则取 `"name": "mdcg_x"` + 该段里的键
    out = []
    body = src[i:j]
    for mm in re.finditer(r'"name":\s*"(mdcg_[a-z_]+)"', body):
        out.append(mm.group(1))
    return src, body, out


def _schema_keys(body, name):
    """取该工具 `inputSchema.properties` 的第一层键。

    ★R-524 第一版用**文本解析**（切段 + 括号配平），当场踩坑：`inputSchema` 是
    用 `_s("", node_id=_p(...), content=_p(...))` **函数调用**构造的，不是 JSON
    字面量 ⇒ 文本里根本没有 `"properties"` 这个字面量，于是所有工具都被报成
    「schema 没写 X」（连 `mdcg_remember` 的 `content` 都被报成没写）。
    改成 **import 真值**（`mcp_server.TOOLS`），把解析与实际构造解耦。
    """
    try:
        from md_cg import mcp_server as _M
        for spec in _M.TOOLS:
            if spec.get("name") == name:
                props = (spec.get("inputSchema") or {}).get("properties") or {}
                return set(props.keys())
        return set()
    except Exception:
        pass
    i = body.find('"name": "%s"' % name)
    if i < 0:
        return set()
    # ★必须切到**下一个 `"name": "mdcg_`** 为止 —— 定长 8000 字符会跨进下一个工具的
    # schema（第一版就踩了：`mdcg_remember` 报「`content` 没写」，明显荒谬）。
    _nxt = body.find('"name": "mdcg_', i + 10)
    seg = body[i:(_nxt if _nxt > i else i + 8000)]
    j = seg.find('"inputSchema"')
    if j < 0:
        return set()
    sub = seg[j:]
    k = sub.find('"properties"')
    if k < 0:
        return set()
    # 从 properties 的 { 起做括号配平
    b = sub.find("{", k)
    depth, e = 0, b
    while e < len(sub):
        if sub[e] == "{":
            depth += 1
        elif sub[e] == "}":
            depth -= 1
            if depth == 0:
                e += 1
                break
        e += 1
    block = sub[b:e]
    # 只取深度 1 的键（"xxx": { 或 "xxx": ）
    keys, d = set(), 0
    for ln in block.split("\n"):
        s = ln.strip()
        mm = re.match(r'^"([a-z_]+)":', s)
        if mm and d == 1:
            keys.add(mm.group(1))
        d += ln.count("{") - ln.count("}")
    return keys


def _handler_keys(src, name):
    """切出该工具的分支段，收集 a.get("x") / a["x"] 的键。"""
    i = src.find('if name == "%s"' % name)
    if i < 0:
        i = src.find('name == "%s"' % name)
    if i < 0:
        return set(), False
    # 段尾：下一个 `if name ==` 或 4000 字符
    nxt = src.find('if name == "', i + 10)
    seg = src[i:(nxt if 0 < nxt < i + 20000 else i + 6000)]
    keys = set(re.findall(r'a\.get\("([a-z_0-9]+)"', seg))
    keys |= set(re.findall(r'a\["([a-z_0-9]+)"\]', seg))
    return keys, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    src, body, names = _tools()
    rows, unseen = [], []
    for n in names:
        sk = _schema_keys(body, n)
        hk, found = _handler_keys(src, n)
        if not found:
            unseen.append(n)
            continue
        only_s = sk - hk
        only_h = hk - sk
        kw = KNOWN.get(n, (set(), set(), ""))
        # 分级（R-524 实测后定的口径）：
        #   only_h（分发层读、schema 没写）= **hard** —— 调用方按契约猜不到这个键存在；
        #   only_s（schema 有、分发层不读）= **soft** —— 绝大多数是「整体 a 交辅助函数」
        #     的判据盲区（见 KNOWN 的说明），真「声明了却不读」才是缺陷，但判据分不开。
        rows.append((n, sorted(only_s - kw[0]), sorted(only_h - kw[1])))

    bad = [r for r in rows if r[2]]          # 只按 hard（分发层读、schema 没写）判红
    soft = [r for r in rows if r[1] and not r[2]]
    print("数：%d 个工具 / 分支定位到 %d 个 / **有差异 %d 个** / 未定位 %d 个"
          % (len(names), len(rows), len(bad), len(unseen)))
    print("口径：schema 取 `inputSchema.properties` 第一层键；handler 取该工具分支段内 "
          "`a.get(\"x\")` 与 `a[\"x\"]`；两边都减去 KNOWN 白名单")
    print("反例：若某工具把实现抽到 `_mdcg_xxx()` 辅助函数，本脚本**看不见它的读键** —— "
          "那类工具会落进「未定位」或报成「schema 有、不读」（判据的已知盲区）")

    for n, o_s, o_h in bad:
        print("\n✗ %s" % n)
        if o_s:
            print("   schema 有、分发层不读: %s" % ", ".join(o_s))
        if o_h:
            print("   分发层读、schema 没写: %s" % ", ".join(o_h))
    if unseen and not a.quiet:
        print("\n· 未定位到分支（%d）：%s" % (len(unseen), ", ".join(unseen[:8])))
    print("\n结果：%s" % ("PASS" if not bad else "FAIL（%d 个工具有差异）" % len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:                                   # noqa: BLE001
        print("✗ 自身故障：%s: %s" % (type(e).__name__, e))
        sys.exit(2)
