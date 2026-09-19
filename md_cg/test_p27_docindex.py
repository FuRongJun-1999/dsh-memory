# -*- coding: utf-8 -*-
"""条件文档图端到端测试（P27 · 认知图的文档面）。

R2 改造的验收（对照 docs/mdcg/认知图_索引与工程规范化_计划_v0.1.md §六 R2、§七）：

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
  ⑦ 不静默：truncated / skipped_suffixes / skipped_dirs 显式上报；排除为**追加**
     （只增不减，内置 .git/.venv/node_modules 不可被关闭）；只读契约（源 mtime 不变）；
     幂等（重跑节点数不变）；`index_doc` 进 ALL_OPS 且与工具 schema 一致。
  ⑧ fence 往返列六件套的形状与边界：BINDING_FIELDS / binding_of / binding_key
     （**不含行位**）/ binding_slug / validate_binding / binding_drift / locate。
     为什么必须钉死：列形状漂移会让对账器把坏列当好消息（漏报）；键若悄悄带上
     行位，真源上方插一行就会让整库失配——两者都是静默退化，只有断言看得见。
  ⑨ 逐字节回放回归：对**真实索引出的卡**断言 `render(条目) + "\n" == 卡片正文`。
     ⑧ 只证「列可定位」；只有逐字节相等才证明卡片是真源条目的**派生物**而非另一份
     副本（渲染漂移或人工改写时列全然不变，对账器看不出来）。外部历史库另段抽样
     （设 MDCG_ROOT 则跑，未设如实 SKIP 不虚报通过）。

运行：python -m md_cg.test_p27_docindex
     设 MDCG_ROOT=<认知图库根> 追加跑【12b】外部历史库逐字节回放抽样
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile

from . import codeindex, corpus, docindex, nodefile, refindex, routing, tokens
from . import mcp_server
from .mdcos import MdCGOS, MdCGSecure   # 生产路径：forget 属 OS 层，基础层 MdCG 无删除原语
from .mcp_server import call_tool
from .security import Principal

PASS = FAIL = 0
FAILS = []

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(_BASE, "_md_cg_p27")
DOCS = os.path.join(_BASE, "docs")
PLAN_DOC = "mdcg/认知图_MD目录方案_v0.1.md"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _norm(p):
    """路径归一（大小写 + 分隔符）：root 归属比对用，避免同一目录被判成两个。"""
    return os.path.normcase(os.path.normpath(str(p or "")))


# 逐字节回放：把「往返列」从「形状可校验」推进到「内容可无损重建」。
# 生效条件：cg 已索引完成的库；索引条目 tags 含 "doc" 且 frontmatter 有非空 doc_ref。
# 判据：真源同键条目 `render(条目)` 补一个换行 == 卡片正文——`nodefile.dumps` 对不以
# 换行结尾的正文补 '\n'，故卡片正文恒比 render 多 1 字节（是常态，不是缺陷；判等
# 一律按 `render + "\n"`，避免把口径差当回归）。
# 为什么非此不可：列形状对（validate_binding）只保证「可定位」；只有逐字节相等才
# 证明卡片是真源条目的**派生物**而非另一份副本。渲染漂移或人工改写卡片正文时，
# 列全都不变（路径/行位/hash 都是真源侧的值），对账器看不出来——本函数才看得见。
# 悬空（真源已移出）/ 未解析如实计数：那是数据面事实，不冒充渲染失败。
def _replay_cards(cg, roots=None, sample=0, seed=7):
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    picks = []
    for nid in sorted(nodes):
        if "doc" not in ((nodes.get(nid) or {}).get("tags") or []):
            continue
        kind, ref = refindex.ref_of(cg.get(nid))
        if kind != "doc_ref" or not ref:
            continue
        if roots is not None and _norm(ref.get("root")) not in roots:
            continue
        picks.append((nid, ref))
    if sample and len(picks) > sample:
        picks = sorted(random.Random(seed).sample(picks, sample))
    out = {"sampled": len(picks), "ok": 0, "dangling": 0, "gone": 0,
           "unreadable": 0, "mismatch": []}
    cache = {}
    for nid, ref in picks:
        fp = (str(ref.get("root") or ""), str(ref.get("path") or ""))
        ckey = (_norm(fp[0]), fp[1])
        if ckey not in cache:
            # 把「源文件已移出」（数据面事实，非缺陷）与其它 IO/抽取异常（可能是真
            # 问题：权限、编码、源被改成无标题文档）分开计数——混为一谈会把真实
            # 故障伪装成历史遗留，静默吞掉回归。三态：True 读得 / False 不存在 /
            # None 读不了。
            try:
                with open(os.path.join(fp[0], fp[1]), "r", encoding="utf-8",
                          errors="replace") as f:
                    cache[ckey] = (True, docindex.extract(f.read(), fp[1]))
            except FileNotFoundError:
                cache[ckey] = (False, None)
            except (OSError, ValueError):
                cache[ckey] = (None, None)
        hit, items = cache[ckey]
        if hit is not True:
            out["gone" if hit is False else "unreadable"] += 1
            continue
        node = cg.get(nid) or {}
        want = docindex.binding_key(docindex.binding_of(node))
        # 键（path#heading_path）在同名标题重复时可能命中多条：先按行位锁定同名代，
        # 行位也漂了才回落首条（此时本来就判「不符」，不掩盖结论）。
        cands = [i for i in items if docindex.binding_key(i) == want]
        if not cands:
            out["dangling"] += 1
            continue
        item = next((i for i in cands if i.get("lineno") == ref.get("lineno")),
                    cands[0])
        got = docindex.render(item) + "\n"
        content = node.get("content") or ""
        if got == content:
            out["ok"] += 1
            continue
        k = next((i for i in range(min(len(got), len(content)))
                  if got[i] != content[i]), min(len(got), len(content)))
        out["mismatch"].append(
            f"{nid}@{k} 回放={got[k:k + 24]!r} 卡片={content[k:k + 24]!r}")
    return out


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
    cg = MdCGOS(ROOT)
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
        check("CCG 完整 → state=DEFER（v2：情境未确认条件不冒充接受，非 BLINDSPOT）",
              bool(hits) and hits[0]["state"] == "DEFER",
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
        # docs/experiments/ 是 .gitignore 整目录忽略的实验产物（实测 2358 个 md，
        # 属索引噪声而非文档事实源），会把 max_files=500 撑爆：显式 skip_dirs 排除。
        # 用「排除 + 回报」而不是「调大上限」——排除结果落在 skipped_dirs 里，不静默。
        SKIP_NOISE = ("experiments",)

        def _count_md(base, skip_names):
            n = 0
            for d, dirs, fs in os.walk(base):
                dirs[:] = [x for x in dirs if x not in skip_names]
                n += sum(1 for fn in fs if fn.lower().endswith(".md"))
            return n

        # 测试不得依赖仓库外状态：docs/experiments/ 被 .gitignore 整目录忽略，
        # 外部 clone 后物理不存在，而本段断言的正是「真实扫描中 skip_dirs 命中
        # 要被回报」。不存在时自备最小探针目录（跑完即清）；已存在时零动作
        # （不碰本机历史产物）。探针为无标题正文——extract 返回空条目，不产生
        # doc 节点；且探针在 experiments 内，_count_md 与被测扫描两侧口径一致，
        # 对「全部 md 被索引」断言零影响。
        probe_dir = os.path.join(DOCS, "experiments")
        probe_created = not os.path.isdir(probe_dir)
        if probe_created:
            os.makedirs(probe_dir, exist_ok=True)
            with open(os.path.join(probe_dir, "_probe_no_heading.md"),
                      "w", encoding="utf-8") as f:
                f.write("探针正文：无标题不产节点，仅让 experiments 物理存在。\n")
        try:
            expect_files = _count_md(DOCS, SKIP_NOISE)
            real = index_doc(cg, DOCS, skip_dirs=list(SKIP_NOISE))
        finally:
            if probe_created:
                shutil.rmtree(probe_dir)
        check("docs/ 全部 md 被索引（无静默跳过）",
              real.get("error_count") == 0 and real.get("files") == expect_files
              and real.get("truncated") is False,
              f"files={real.get('files')}/{expect_files} errs={real.get('error_count')}")
        check("skip_dirs 实际排掉的目录被回报（排除不静默）",
              any("experiments" in p for p in (real.get("skipped_dirs") or [])),
              str(real.get("skipped_dirs"))[:80])
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
        check("§9 表可被检索到且可判（state=DEFER，非 BLINDSPOT）",
              bool(h2) and h2[0]["state"] == "DEFER",
              str(h2[0]["state"] if h2 else None))
        rr4 = call_tool(cg, "cg", {"op": "ref", "node_id": r_id})
        check("回读到 §9 表原文（给出行号区间）",
              rr4.get("ok") and "分阶段实施" in (rr4.get("text") or ""),
              f"L{s9r['lineno']}-L{s9r['end']}" if s9r else "")

        # ===================================================== ⑨b skip_dirs
        print("\n【9b】skip_dirs：追加排除（只增不减）+ 结果可审计")
        hit0, rules0 = codeindex.skip_matcher(None)
        check("skip_dirs 缺省时判定器为空（默认行为与改造前逐字一致）",
              hit0 is None and rules0 == [], f"{hit0} {rules0}")
        sb = os.path.join(tmp, "skipdirs")
        for rel in ("docs/keep/keep.md", "docs/experiments/probe/p.md",
                    "docs/experiments/x.md", "sub/experiments/y.md",
                    "node_modules/pkg/n.md"):
            fp = os.path.join(sb, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write("# 标题\n\n" + LONG + "\n")
        _i, _e, st_plain = docindex.index_dir(sb)
        check("不给 skip_dirs：内置排除照旧（node_modules 不计入）",
              st_plain["files"] == 4 and st_plain["skipped_dirs"] == [],
              f"files={st_plain['files']} skip={st_plain['skipped_dirs']}")
        _i, _e, st_name = docindex.index_dir(sb, skip_dirs=["experiments"])
        check("不含 / 的规则按目录名匹配（各层级同名目录都排）"
              " · 且内置排除不可被关闭（node_modules 仍被排）",
              st_name["files"] == 1
              and sorted(st_name["skipped_dirs"]) == ["docs/experiments",
                                                      "sub/experiments"],
              f"files={st_name['files']} skip={sorted(st_name['skipped_dirs'])}")
        _i, _e, st_path = docindex.index_dir(sb, skip_dirs=["docs/experiments"])
        check("含 / 的规则按相对路径匹配（只排这一处）",
              st_path["files"] == 2 and st_path["skipped_dirs"] == ["docs/experiments"],
              f"files={st_path['files']} skip={st_path['skipped_dirs']}")
        _i, _e, st_norm = docindex.index_dir(sb, skip_dirs=["docs\\experiments\\"])
        check("规则先归一（反斜杠/首尾斜杠）再匹配，不静默失配",
              st_norm["files"] == 2
              and st_norm["skipped_dirs"] == ["docs/experiments"],
              f"files={st_norm['files']} skip={st_norm['skipped_dirs']}")

        # ===================================================== ⑩ 索引对账
        # 缺口：node_id 含 heading_path，改标题 → 整篇 id 重算；add_items 只做
        # 同 id 幂等 upsert，旧代节点无人清退 → 新旧并存、同一文档召回两份。
        # 水位 reconcile 只剪水位条目、不剪节点，所以必须在索引后显式清。
        print("\n【10】节点级对账：改标题 → 清退过期代（消除重复召回）")
        rn = os.path.join(fx, "rename.md")
        b1 = "# 标题甲\n\n" + LONG + "\n"
        with open(rn, "w", encoding="utf-8") as f:
            f.write(b1)
        r1 = index_doc(cg, fx)
        ids1 = {docindex.node_id(i) for i in docindex.extract(b1, "rename.md")}
        check("首轮：节点在库", all(cg.get(n) for n in ids1), f"n={len(ids1)}")
        check("首轮无孤儿（清退计数 0）",
              (r1.get("pruned") or {}).get("count") == 0, str(r1.get("pruned")))

        b2 = "# 标题乙（已改名）\n\n" + LONG + "\n"
        with open(rn, "w", encoding="utf-8") as f:
            f.write(b2)
        r2 = index_doc(cg, fx)
        ids2 = {docindex.node_id(i) for i in docindex.extract(b2, "rename.md")}
        check("改标题后新代上台", all(cg.get(n) for n in ids2), f"n={len(ids2)}")
        check("旧代被清退（新旧不并存）",
              not any(cg.get(n) for n in ids1),
              f"残留={sorted(n for n in ids1 if cg.get(n))}")
        check("清退数量上报", (r2.get("pruned") or {}).get("count") == len(ids1 - ids2),
              str(r2.get("pruned")))

        b3 = "# 标题丙\n\n" + LONG + "\n"
        with open(rn, "w", encoding="utf-8") as f:
            f.write(b3)
        r3 = index_doc(cg, fx, prune_dry_run=True)
        check("prune_dry_run 只列不清（节点仍在库）",
              (r3.get("pruned") or {}).get("dry_run") is True
              and any(cg.get(n) for n in ids2), str(r3.get("pruned")))
        index_doc(cg, fx)
        check("随后实际清退 → 旧代消失", not any(cg.get(n) for n in ids2))

        b4 = "# 标题丁\n\n" + LONG + "\n"
        with open(rn, "w", encoding="utf-8") as f:
            f.write(b4)
        ids4 = {docindex.node_id(i) for i in docindex.extract(b4, "rename.md")}
        r5 = index_doc(cg, fx, prune=False)
        check("prune=false 可关闭（不清退）",
              r5.get("pruned") is None and all(cg.get(n) for n in ids4),
              str(r5.get("pruned")))
        r6 = index_doc(cg, fx, max_files=1)
        check("截断时不清退（没扫完 ≠ 剩下都过期）",
              r6.get("pruned") is None, f"truncated={r6.get('truncated')}")

        print("\n【10b】悬空清退：源文件删除 → op=ref action=prune 处置")
        ck1 = call_tool(cg, "cg", {"op": "ref", "action": "check", "max_nodes": 5000})
        pre = len(ck1.get("dangling") or [])
        os.remove(rn)
        ck2 = call_tool(cg, "cg", {"op": "ref", "action": "check", "max_nodes": 5000})
        check("删源后 check 报悬空", len(ck2.get("dangling") or []) > pre,
              f"{pre}→{len(ck2.get('dangling') or [])}")
        dry = call_tool(cg, "cg", {"op": "ref", "action": "prune", "dry_run": True})
        check("prune_dry_run 列出待清退但不删",
              dry.get("dry_run") is True and dry.get("count", 0) >= 1
              and any(cg.get(n) for n in ids4), str(dry)[:130])
        gone = call_tool(cg, "cg", {"op": "ref", "action": "prune"})
        check("prune 清退悬空节点",
              gone.get("count", 0) >= 1 and not any(cg.get(n) for n in ids4),
              str(gone)[:130])
        ck3 = call_tool(cg, "cg", {"op": "ref", "action": "check", "max_nodes": 5000})
        check("清退后悬空归零", not (ck3.get("dangling") or []),
              str(ck3.get("dangling"))[:130])

        # 跨进程一致性：新实例重放 _index_log 后，已清退节点不得复活成幽灵条目
        # （索引有条目、文件不存在）——只有把「删除」也写进增量日志才成立。
        cg2 = MdCGOS(ROOT)
        revived = sorted(n for n in ids4 if n in (cg2.index.get("nodes") or {}))
        check("清退后重开不复活幽灵条目", not revived, f"复活={revived}")

        # 存量幽灵（历史「删除只摘内存索引」遗留）：索引有条目、节点文件不存在
        # 也必须清得掉，否则 dangling 永远够不着零。
        gid = "doc_ghost_probe0001"
        cg.index["nodes"][gid] = {"path": "knowledge/ghost_probe.md",
                                  "layer": "knowledge", "tags": ["doc"],
                                  "bucket": None, "importance": 0.5}
        g1 = call_tool(cg, "cg", {"op": "ref", "action": "prune"})
        check("幽灵条目被清退（索引有、文件无）",
              len(g1.get("ghost_pruned") or []) >= 1
              and gid not in (cg.index.get("nodes") or {}), str(g1)[:130])
        ck4 = call_tool(cg, "cg", {"op": "ref", "action": "check", "max_nodes": 5000})
        check("清幽灵后悬空仍为零", not (ck4.get("dangling") or []),
              str(ck4.get("dangling"))[:130])

        # ============================================ ⑪ fence 往返列（binding）
        # 缺口：往返列（取列 / 造键 / 校验 / 漂移 / 反查）是「条件卡 ↔ Markdown 真源」
        # 的可校验面，此前零测试。列形状一旦漂移，对账器会把坏列当好消息（漏报）；
        # 键若悄悄带上行位，真源上方插一行就会让整库失配——故两者都要钉死。
        print("\n【11】fence 往返列：形状 / 键不含行位 / 校验 / 漂移 / 反查")
        li = docindex.extract(GUIDE, "guide.md")
        s9b = next(i for i in li if i["heading"] == "9. 分阶段实施")
        rendered = docindex.render(s9b)
        gnode = cg.get(g_id) or {}
        g_ref = (gnode.get("frontmatter") or {}).get("doc_ref") or {}
        b0 = docindex.binding_of(gnode)
        check("必需列齐全且无空值",
              isinstance(b0, dict)
              and all(b0.get(k) not in (None, "") for k in docindex.BINDING_FIELDS),
              str(sorted(docindex.BINDING_FIELDS)))
        check("列面 = 必需列 + 附加列（无第二份列口径）",
              set(b0 or {}) == set(docindex.BINDING_FIELDS)
              | set(docindex.BINDING_OPTIONAL),
              str(sorted(set(b0 or {}) ^ (set(docindex.BINDING_FIELDS)
                                          | set(docindex.BINDING_OPTIONAL)))))
        check("必需列/附加列 ⊆ 写侧 doc_ref 列（读写同一列面）",
              (set(docindex.BINDING_FIELDS) | set(docindex.BINDING_OPTIONAL))
              <= set(g_ref),
              str(sorted(set(docindex.BINDING_FIELDS) - set(g_ref))))
        check("binding_of 与直接读 frontmatter 同源（同一投影）",
              b0 == docindex.binding_of({"frontmatter": {"doc_ref": g_ref}}))
        check("binding_of 对非索引节点返回 None（不猜、不补默认值）",
              docindex.binding_of(None) is None
              and docindex.binding_of([]) is None
              and docindex.binding_of({}) is None
              and docindex.binding_of({"frontmatter": {"tags": ["doc"]}}) is None)
        check("validate_binding：本仓卡片列形状合法（ok + 零 issue）",
              docindex.validate_binding(b0) == {"ok": True, "issues": []},
              str(docindex.validate_binding(b0)))
        check("validate_binding：非 dict 如实报错且不抛",
              docindex.validate_binding(None)
              == {"ok": False, "issues": ["绑定不是字典（该节点无 doc_ref）"]})
        lo0 = b0["lineno"]
        bad_detail = []
        for _nm, _b, _want in (
                ("缺列", {k: v for k, v in b0.items() if k != "anchor"},
                 "缺列 anchor"),
                ("类型错 root", {**b0, "root": 123},
                 "root 应为字符串，实为 int"),
                ("类型错 lineno", {**b0, "lineno": "十"}, "行位不是整数"),
                ("行位越界", {**b0, "lineno": 0}, "lineno 越界（0 < 1）"),
                ("区间倒置", {**b0, "end": lo0 - 1},
                 f"end 早于 lineno（{lo0}-{lo0 - 1}）")):
            _v = docindex.validate_binding(_b)
            if _v["ok"] or _want not in _v["issues"]:
                bad_detail.append(f"{_nm}→{_v['issues']}")
        check("validate_binding 逐类坏列均被点出（缺列/类型错/越界/区间倒置）",
              not bad_detail, "; ".join(bad_detail)[:170])
        b_shift = docindex.binding_of({"frontmatter": {"doc_ref": {
            **g_ref, "lineno": lo0 + 40, "end": g_ref["end"] + 40}}})
        check("键不含行位：行位位移不改键（重排后仍是同一章节）",
              docindex.binding_key(b0) == docindex.binding_key(b_shift)
              == "guide.md#总览/9. 分阶段实施",
              docindex.binding_key(b0))
        check("漂移按固定列序报出变化项（lineno → end → hash）",
              docindex.binding_drift(b0, b_shift) == ["lineno", "end"]
              and docindex.binding_drift(b0, {**b0, "hash": "zz"}) == ["hash"]
              and docindex.binding_drift(
                  b0, {**b0, "hash": "zz", "lineno": lo0 + 1})
              == ["lineno", "hash"],
              str(docindex.binding_drift(b0, b_shift)))
        check("同列零漂移（无变化不报 / 空值不炸）",
              docindex.binding_drift(b0, dict(b0)) == []
              and docindex.binding_drift(None, None) == [])
        check("binding_key 缺 heading_path 回落 path#anchor · 非 dict 返空串",
              docindex.binding_key({"path": "a.md", "anchor": "s1"}) == "a.md#s1"
              and docindex.binding_key({"path": "a.md"}) == "a.md#"
              and docindex.binding_key(None) == "")
        check("binding_slug 与 render 正文「本条目属于」逐字同源",
              docindex.binding_slug(b0) == "guide.md#9-分阶段实施"
              and f"本条目属于 {docindex.binding_slug(b0)}" in rendered,
              docindex.binding_slug(b0))
        check("反查取最内层（父节区间内的子节优先，不回落父节）",
              docindex.locate(li, 12)["heading"] == "9. 分阶段实施"
              and docindex.locate(li, 30)["heading"] == "代码示例",
              str((docindex.locate(li, 12) or {}).get("heading")))
        check("反查区间闭合（标题行与末行都算本节）",
              docindex.locate(li, s9b["lineno"])["heading"] == "9. 分阶段实施"
              and docindex.locate(li, s9b["end"])["heading"] == "9. 分阶段实施")
        check("反查越界/非整数/空表 → None（fail-closed 不猜）",
              docindex.locate(li, 10 ** 6) is None
              and docindex.locate(li, 0) is None
              and docindex.locate(li, "x") is None
              and docindex.locate(li, None) is None
              and docindex.locate([], 10) is None)

        # ================================ ⑫ 逐字节回放回归（往返列无损）
        # ⑪ 只证「列可校验」；本段把口径推到内容无损：卡片必须是真源条目的派生物
        # （render 补一个换行 == 卡片正文）。root 限定为本次真正索引过的两个真源，
        # 断言只落在本轮写入的卡上——历史残留不参与，避免把脏数据当回归。
        print("\n【12】逐字节回放回归：render(条目) + 换行 == 卡片正文")
        cg.flush()
        rp = _replay_cards(cg, roots={_norm(fx), _norm(DOCS)})
        print(f"      取样 {rp['sampled']} 卡：一致 {rp['ok']} · 键未命中 "
              f"{rp['dangling']} · 源已移出 {rp['gone']} · 读不了 "
              f"{rp['unreadable']}")
        check("回放取样命中卡片（root 限定=本次索引的两个真源）",
              rp["sampled"] > 0, str(rp["sampled"]))
        check("可读卡 100% 逐字节回放一致（写侧 render 与读侧同源）",
              not rp["mismatch"],
              f"一致 {rp['ok']}/{rp['sampled']}；" + "；".join(rp["mismatch"][:2]))
        check("零键未命中 / 零源已移出 / 零读不了（源在库则必可重定位并读回）",
              rp["dangling"] == 0 and rp["gone"] == 0
              and rp["unreadable"] == 0,
              f"键未命中={rp['dangling']} 源已移出={rp['gone']} "
              f"读不了={rp['unreadable']}")
        check("回放账目闭合（一致 + 键未命中 + 源已移出 + 读不了 = 取样数）",
              (rp["ok"] + rp["dangling"] + rp["gone"] + rp["unreadable"])
              == rp["sampled"],
              f"{rp['ok']}+{rp['dangling']}+{rp['gone']}+{rp['unreadable']}"
              f" vs {rp['sampled']}")

        # 历史抽样：真实认知图库（仓外数据面，历史卡最多）。以 MDCG_ROOT 显式声明；
        # 裸 clone / CI 无此数据面 → 如实报 SKIP（不虚报通过、也不 FAIL）。
        ext_root = os.environ.get("MDCG_ROOT") or ""
        if not (ext_root and os.path.isdir(ext_root)):
            print("\n【12b】历史抽样：跳过（未设 MDCG_ROOT 或目录不存在）"
                  "—— 本仓语料回放见【12】")
        else:
            print(f"\n【12b】历史抽样：外部认知图库 {ext_root}（只读身份）")
            ext = MdCGSecure(ext_root, principal=Principal(
                actor="p27-replay", clearance="secret", can_write=False,
                can_admin=False, role="designer", auth_mode="local-cli"))
            try:
                hp = _replay_cards(ext, sample=120)
            finally:
                ext.close()
            print(f"      抽样 {hp['sampled']} 卡：一致 {hp['ok']} · 键未命中 "
                  f"{hp['dangling']} · 源已移出 {hp['gone']} · 读不了 "
                  f"{hp['unreadable']}")
            check("【12b】历史库抽样命中卡片（数据面可达）",
                  hp["sampled"] > 0, str(hp["sampled"]))
            check("【12b】可读历史卡零回放不符（未被渲染漂移/人工改写腐化）",
                  not hp["mismatch"],
                  f"一致 {hp['ok']}/{hp['sampled']}；"
                  + "；".join(hp["mismatch"][:2]))
            check("【12b】未读回的全部是「源已移出」（非 IO/抽取故障）",
                  hp["unreadable"] == 0,
                  f"源已移出={hp['gone']} 读不了={hp['unreadable']}")
            check("【12b】抽样账目闭合（无静默丢弃）",
                  (hp["ok"] + hp["dangling"] + hp["gone"] + hp["unreadable"])
                  == hp["sampled"],
                  f"{hp['ok']}+{hp['dangling']}+{hp['gone']}+{hp['unreadable']}"
                  f" vs {hp['sampled']}")

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
