# -*- coding: utf-8 -*-
"""条件文档图端到端测试（P27 · 认知图的文档面）。

R2 改造的验收（对照 docs/认知图_索引与工程规范化_计划_v0.1.md §六 R2、§七）：

  ① 切块纪律：只切 level<=3；直接正文 <200 字且无子节的小节**合并进父节**
     （不单独建节点，其文字进父节摘要）。既不过细，也不丢内容。
  ② md 解析硬约束：
     · **围栏代码块内的 `#` 不是标题**（docs/ 里全是 python/shell 片段，不跟踪
       围栏就会切出假标题、把一节切碎）；
     · **开头 YAML frontmatter 不被当正文索引**；**正文里的 `---` 不污染
       frontmatter**（nodefile 既有纪律，这里验证不回归）。
  ③ 渲染即 CCG：`docindex.render` 必须产 CCG 6 行，否则文档节点会像改造前的
     codeindex 一样「存得进、判不了、检索不到」（恒定 BLINDSPOT）。
  ④ doc_ref + op=ref：只存标题与摘要、**不存全文**；正文按 doc_ref 回读，
     与 code 节点共用同一 `region_hash` → hash_match 可检漂移、可重跑恢复。
  ⑤ §1.3-3 裁定落地：layer 默认 knowledge；密级默认 internal **显式写入**
     frontmatter，路径段命中私有提示再保守降为 private；调用方可显式覆盖。
  ⑥ 真实 docs/：章节可定位（行号与源文件一致），能检索到并按 CCG 判 ACCEPT。
  ⑦ 不静默：truncated / skipped_suffixes 显式上报；只读契约（源 mtime 不变）；
     幂等（重跑节点数不变）；`index_doc` 进 ALL_OPS 且与工具 schema 一致。

运行：python -m md_cg.test_p27_docindex
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

from . import corpus, docindex, nodefile, routing, tokens
from . import mcp_server
from .mdcg import MdCG
from .mcp_server import call_tool

PASS = FAIL = 0
FAILS = []

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(_BASE, "_md_cg_p27")
DOCS = os.path.join(_BASE, "docs")
PLAN_DOC = "认知图_MD目录方案_v0.1.md"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


LONG = "这是总览段落，" + "用以验证章节切块在长正文下的表现，" * 12 + "结束。"

GUIDE_LINES = [
    "---",
    "title: 测试指南",
    "tags: [a, b]",
    "---",
    "",
    "# 总览",
    "",
    LONG,
    "",
    "## 9. 分阶段实施",
    "",
    "表格与正文说明。",
    "",
    "| 阶段 | 内容 |",
    "|---|---|",
    "| R1 | 索引 |",
    "",
    "### 9.1 小节点",
    "",
    "一行小注。",
    "",
    "## 代码示例",
    "",
    "```python",
    "# 这不是标题",
    "## 也不是标题",
    "def f():",
    "    return 1",
    "```",
    "",
    "---",
    "",
    "### 末尾小节",
    "",
    "收尾正文。",
]
GUIDE = "\n".join(GUIDE_LINES)

SECRET = "\n".join([
    "# 私有配置",
    "",
    "这是私有目录下的文档。",
    "",
    "## 子节",
    "",
    "内容。",
])


def find(items, heading):
    return next((i for i in items if i["heading"] == heading), None)


def index_doc(cg, path, **extra):
    a = {"op": "index_doc", "path": path}
    a.update(extra)
    return call_tool(cg, "cg", a)


def main():
    print("=" * 68)
    print("md 认知图 P27 验收 · 文档索引（index_doc / doc_ref / op=ref）")
    print("=" * 68)

    tmp = tempfile.mkdtemp(prefix="mdcg_docidx_")
    fx = os.path.join(tmp, "fx")
    os.makedirs(os.path.join(fx, "private"))
    with open(os.path.join(fx, "guide.md"), "w", encoding="utf-8") as f:
        f.write(GUIDE)
    with open(os.path.join(fx, "private", "secret.md"), "w", encoding="utf-8") as f:
        f.write(SECRET)
    with open(os.path.join(fx, "notes.txt"), "w", encoding="utf-8") as f:
        f.write("不是文档")

    corpus.reset_root(ROOT)
    cg = MdCG(ROOT)
    guide_path = os.path.join(fx, "guide.md")

    try:
        # ===================================================== ① 注册表 + 切块
        print("\n【1】注册一致性 / 切块纪律（level<=3 + 小节点合并）")
        cg_tool = next(t for t in mcp_server.KERNEL_TOOLS if t["name"] == "cg")
        declared = set(cg_tool["inputSchema"]["properties"]["op"]["description"].split("|"))
        check("工具 op 枚举 == tokens.ALL_OPS（§七-11 防漏改）",
              declared == set(tokens.ALL_OPS),
              f"only-schema={sorted(declared - set(tokens.ALL_OPS))} "
              f"only-ops={sorted(set(tokens.ALL_OPS) - declared)}")
        check("index_doc 已进 ALL_OPS", "index_doc" in tokens.ALL_OPS)

        try:
            docindex.extract("x", "foo.txt")
            unknown = False
        except ValueError as exc:
            unknown = "无文档提取器" in str(exc)
        check("无文档提取器后缀显式报错", unknown)

        items = docindex.extract(GUIDE, "guide.md")
        heads = {i["heading"] for i in items}
        check("切块只产出 3 个节点（小节点已合并）", len(items) == 3,
              f"n={len(items)} heads={sorted(heads)}")
        check("围栏内的 # 不是标题（假标题零泄漏）",
              not any("不是标题" in h for h in heads), str(sorted(heads)))
        check("总览区间覆盖至文末（未被假标题截断）",
              find(items, "总览")["end"] == len(GUIDE_LINES),
              f"end={find(items, '总览')['end']}")
        check("YAML frontmatter 未被当正文（总览起始行=6）",
              find(items, "总览")["lineno"] == 6,
              f"lineno={find(items, '总览')['lineno']}")
        s9 = find(items, "9. 分阶段实施")
        check("9. 章节区间正确（10-21）",
              s9["lineno"] == 10 and s9["end"] == 21,
              f"{s9['lineno']}-{s9['end']}")
        check("heading_path 反映嵌套",
              s9["heading_path"] == ["总览", "9. 分阶段实施"],
              str(s9["heading_path"]))
        check("anchor 生成正常", s9["anchor"] == "9-分阶段实施", s9["anchor"])
        check("小节点正文并入父节摘要（不丢内容）",
              "一行小注" in s9["summary_parts"], s9["summary_parts"][:60])
        code = find(items, "代码示例")
        check("文末小节点正文并入其父节摘要",
              "收尾正文" in code["summary_parts"], code["summary_parts"][:60])
        check("只切 level<=3（条目层级均 <=3）",
              all(i["level"] <= 3 for i in items),
              str([i["level"] for i in items]))

        # ===================================================== ② 渲染即 CCG
        print("\n【2】render 产出 CCG（否则恒定 BLINDSPOT）")
        rendered = docindex.render(s9)
        cpl = nodefile.ccg_completeness(rendered)
        check("CCG 5 要素齐全", cpl["complete"] is True, str(cpl["required_present"]))
        check("CCG 6 行全在", cpl["all_present"] is True)
        # 「不存全文」的准确含义：不逐字复制整节，且摘要栏有长度上限
        # （表格/代码若落在前 200 字内被摘要带上是有意设计——否则检索不到关键词）。
        raw_section = "\n".join(GUIDE_LINES[9:21])
        exec_line = next(ln for ln in rendered.split("\n") if ln.startswith("# 执行："))
        check("不存全文（不逐字复制整节 + 摘要栏封顶）",
              raw_section not in rendered and len(exec_line) <= 200 + len("# 执行："),
              f"exec_len={len(exec_line)}")

        # 生效条件必须与 frontmatter 同源：四槽合成，单槽不是生效条件。
        # 改造前正文写「文档=X；检索…时」（第三种方言），frontmatter 只写单槽
        # observation_position → condition_space_text(require_full=True) 恒为 ""。
        cs = docindex.condition_space(s9)
        check("condition_space 四槽齐备",
              set(cs) == set(nodefile.CONDITION_SLOTS_REQUIRED), str(sorted(cs)))
        synth = nodefile.condition_space_text(cs)
        check("四槽合成出非空生效条件（单槽冒充已废止）", bool(synth), synth)
        check("正文生效条件 = 四槽合成结果（正文与 frontmatter 同源）",
              f"# 生效条件：{synth}" in rendered, synth)
        check("时间槽用全时窗哨兵（不把索引时刻伪造成条件）",
              nodefile.is_full_time_window(cs.get("time_window")),
              str(cs.get("time_window")))

        # ===================================================== ③ 索引 + 密级
        print("\n【3】index_doc：落盘 / 密级 / 层（§1.3-3 裁定）")
        mt_before = {}
        for d, _s, fs in os.walk(fx):
            for fn in fs:
                mt_before[os.path.join(d, fn)] = os.path.getmtime(os.path.join(d, fn))
        out = index_doc(cg, fx)
        check("op=index_doc ok", out.get("ok"), str(out)[:120])
        check("indexed == 4（guide 3 + secret 1）", out.get("indexed") == 4,
              str(out.get("indexed")))
        check("error_count == 0", out.get("error_count") == 0, str(out.get("errors")))
        check("files 只计 .md（2）", out.get("files") == 2, str(out.get("files")))
        check("skipped_suffixes 报出 .txt", ".txt" in out["skipped_suffixes"],
              str(out["skipped_suffixes"]))
        check("layer 默认 knowledge", out.get("layer") == "knowledge")
        check("密级默认 internal、私有目录降 private",
              out["sensitivity"].get("internal") == 3
              and out["sensitivity"].get("private") == 1,
              str(out["sensitivity"]))

        g_id = docindex.node_id(s9)
        g_fm = (cg.get(g_id) or {}).get("frontmatter") or {}
        check("guide 节点密级 frontmatter 显式 internal",
              g_fm.get("sensitivity") == "internal", str(g_fm.get("sensitivity")))
        check("guide 节点 layer=knowledge", g_fm.get("layer") == "knowledge")
        check("verification_basis=data（文档以原文为准）",
              g_fm.get("verification_basis") == "data")
        check("frontmatter.condition_space 四槽齐备（单槽冒充已废止）",
              set(g_fm.get("condition_space") or {}) ==
              set(nodefile.CONDITION_SLOTS_REQUIRED),
              str(sorted(g_fm.get("condition_space") or {})))
        check("frontmatter 条件空间与正文生效条件同源（同一纯函数）",
              g_fm.get("condition_space") == docindex.condition_space(s9),
              str(g_fm.get("condition_space")))
        check("路由域由 domain: 标签显式承担（分桶结果与改造前逐字相同）",
              routing.route_key(g_fm.get("condition_space"), g_fm.get("tags"))
              == routing.normalize_domain("guide.md"),
              str(routing.route_key(g_fm.get("condition_space"), g_fm.get("tags"))))
        sec = docindex.extract(SECRET, "private/secret.md")[0]
        s_fm = (cg.get(docindex.node_id(sec)) or {}).get("frontmatter") or {}
        check("私有目录文档密级=private（保守降级）",
              s_fm.get("sensitivity") == "private", str(s_fm.get("sensitivity")))

        mt_after = {}
        for d, _s, fs in os.walk(fx):
            for fn in fs:
                mt_after[os.path.join(d, fn)] = os.path.getmtime(os.path.join(d, fn))
        check("只读契约：索引不触碰源文件", mt_before == mt_after)

        # ===================================================== ④ doc_ref
        print("\n【4】frontmatter.doc_ref（指回原文，不存全文）")
        dr = g_fm.get("doc_ref") or {}
        check("doc_ref 字段齐全",
              all(k in dr for k in ("path", "heading", "heading_path", "level",
                                    "lineno", "end", "anchor", "lang", "precise",
                                    "hash", "root")), str(sorted(dr)))
        check("doc_ref 指向相对路径与源行号",
              dr.get("path") == "guide.md" and dr.get("lineno") == 10
              and dr.get("end") == 21, str({k: dr.get(k) for k in ("path", "lineno", "end")}))
        check("正文含 --- 未污染 frontmatter（doc_ref 可正常读回）",
              dr.get("heading_path") == ["总览", "9. 分阶段实施"],
              str(dr.get("heading_path")))

        # ===================================================== ⑤ 检索资格
        print("\n【5】检索资格（文档节点不得是 BLINDSPOT）")
        cg.flush()
        rd = call_tool(cg, "cg", {"op": "read", "query": "分阶段实施", "k": 10})
        hits = [r for r in rd.get("results", []) if r["node"]["id"] == g_id]
        check("文档节点可被检索到", bool(hits), f"hits={len(hits)}")
        check("CCG 完整 → state=ACCEPT",
              bool(hits) and hits[0]["state"] == "ACCEPT",
              str(hits[0]["state"] if hits else None))

        # ===================================================== ⑥ op=ref
        print("\n【6】op=ref 回读文档区间 + 漂移")
        rr = call_tool(cg, "cg", {"op": "ref", "node_id": g_id})
        check("ref 回读成功且识别为 doc_ref",
              rr.get("ok") and rr.get("ref_kind") == "doc_ref",
              str(rr.get("ref_kind")))
        check("回读文本 = 源章节（含标题与表格行）",
              "# 9. 分阶段实施" in (rr.get("text") or "")
              and "| R1 | 索引 |" in (rr.get("text") or ""))
        check("hash_match=True（索引侧与回读侧同算法）",
              rr.get("hash_match") is True, str(rr.get("hash")))
        with open(guide_path, "w", encoding="utf-8") as f:
            f.write(GUIDE.replace("| R1 | 索引 |", "| R9 | 已改 |"))
        rr2 = call_tool(cg, "cg", {"op": "ref", "node_id": g_id})
        check("文档改动 → stale 可检出", rr2.get("hash_match") is False
              and rr2.get("stale") is True, str(rr2.get("hash")))
        index_doc(cg, fx)
        rr3 = call_tool(cg, "cg", {"op": "ref", "node_id": g_id})
        check("重跑 index_doc → 漂移消除", rr3.get("hash_match") is True)
        with open(guide_path, "w", encoding="utf-8") as f:
            f.write(GUIDE)

        # ===================================================== ⑦ 覆盖/截断
        print("\n【7】显式覆盖与截断上报")
        ov = index_doc(cg, fx, sensitivity="public")
        check("sensitivity 参数可覆盖默认",
              ov["sensitivity"].get("public") == 4, str(ov["sensitivity"]))
        g_fm2 = (cg.get(g_id) or {}).get("frontmatter") or {}
        check("覆盖后 frontmatter 密级=public", g_fm2.get("sensitivity") == "public")
        index_doc(cg, fx)   # 复位默认密级
        tr = index_doc(cg, fx, max_files=1)
        check("触 max_files → truncated=True", tr.get("truncated") is True,
              str(tr.get("truncated_reason")))
        check("截断时 note 明确警告", "截断" in (tr.get("note") or ""),
              (tr.get("note") or "")[:50])
        index_doc(cg, fx)

        # ===================================================== ⑧ 幂等
        print("\n【8】幂等（重跑 ≡ 首跑）")
        first = index_doc(cg, fx)
        n1 = sum(1 for e in cg.index["nodes"].values() if e["layer"] == "knowledge")
        second = index_doc(cg, fx)
        n2 = sum(1 for e in cg.index["nodes"].values() if e["layer"] == "knowledge")
        check("重跑节点数不变（按 id 原子覆盖，不清目录）", n1 == n2, f"{n1} vs {n2}")
        check("重跑 id 集合稳定（幂等）",
              set(first["ids"]) == set(second["ids"]), str(first["ids"]))

        # ===================================================== ⑨ 真实 docs/
        print("\n【9】真实 docs/：章节可定位、行号与源一致、可检索")
        expect_files = sum(1 for d, _s, fs in os.walk(DOCS) for fn in fs
                           if fn.lower().endswith(".md"))
        real = index_doc(cg, DOCS)
        check("docs/ 全部 md 被索引（无静默跳过）",
              real.get("error_count") == 0 and real.get("files") == expect_files
              and real.get("truncated") is False,
              f"files={real.get('files')}/{expect_files} errs={real.get('error_count')}")
        r_items = docindex.extract(
            open(os.path.join(DOCS, PLAN_DOC), encoding="utf-8").read(), PLAN_DOC)
        s9r = next((i for i in r_items if i["heading"].startswith("9. ")), None)
        real_lines = open(os.path.join(DOCS, PLAN_DOC), encoding="utf-8").read().split("\n")
        hline = 1 + next(k for k, ln in enumerate(real_lines) if ln.startswith("## 9."))
        check("§9 章节被切出（真实文档）", s9r is not None,
              s9r["heading"] if s9r else "缺失")
        check("行号与源文件一致（可定位）",
              s9r is not None and s9r["lineno"] == hline,
              f"{s9r['lineno'] if s9r else None} == {hline}")
        r_id = docindex.node_id(s9r)
        rd2 = call_tool(cg, "cg", {"op": "read", "query": "分阶段实施（稳健）", "k": 10})
        h2 = [r for r in rd2.get("results", []) if r["node"]["id"] == r_id]
        check("§9 表可被检索到且判 ACCEPT",
              bool(h2) and h2[0]["state"] == "ACCEPT",
              str(h2[0]["state"] if h2 else None))
        rr4 = call_tool(cg, "cg", {"op": "ref", "node_id": r_id})
        check("回读到 §9 表原文（给出行号区间）",
              rr4.get("ok") and "分阶段实施" in (rr4.get("text") or ""),
              f"L{s9r['lineno']}-L{s9r['end']}" if s9r else "")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：\n  - " + "\n  - ".join(FAILS))
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
