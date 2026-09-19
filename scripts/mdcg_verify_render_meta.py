# -*- coding: utf-8 -*-
"""只读验收：md_cg / compiler 域 code 节点是否已全部为新 render 产物。

判据（机械，与 nodefile.INDEX_META_MARK / codeindex.RENDER_VERSION 契约同源）：
  meta_indep       —— 正文存在独立成行的 `# 索引元条件：…`（新 render 第三区产物）
  old_synth        —— 正文存在独立成行的 `# 生效条件：载体/位置：本地源码仓…`
                      （旧 render 四槽合成**冒充**生效条件的形态）
  active_old_synth —— 上述 old_synth 中「文件 mtime 落在最近 ACTIVE_WINDOW_S 秒内」者
  versioned        —— frontmatter.code_ref.render_version >= codeindex.RENDER_VERSION
                      （版本戳判据：与 render 契约**同源**，非形态启发式——
                      形态判据只能区分「像不像」，版本戳能确定「是哪一代」）

某域 ok ⟺ total > 0 且 meta_indep == total 且 old_synth == 0
           且 active_old_synth == 0 且 versioned == total
（全量重建后应为 meta_indep == total、old_synth == 0、versioned == total）

判据缺陷史（第4条归因，勿回退）：
  2026-09-19 初版 meta_indep / old_synth 均为**全文 substring** 匹配，两处失真：
    ① old_synth 用 `# 生效条件：载体/位置：` 全文匹配 → 源码区**人工注释**若写成该形态
       即被误判为合成区冒充。实证：`md_cg/selfreport.py` 模块 docstring 的人工注释
       `# 生效条件：载体/位置：仓根 md_cg/selfreport.py（import 路径…）` 使该节点
       被判 old_synth=1 / active_old_synth=1，而它实为新契约产物（带独立元条件行）；
    ② 该串在新契约里**本就存在**——`# 索引元条件：载体/位置：本地源码仓（大域=…）`
       由同一纯函数合成，故退化的 substring 判据天然无法区分两代。
  修法：两判据一律**行级**（起点必须是 `# 索引元条件：` / `# 生效条件：`），且
  old_synth 额外要求命中合成模板固定值「载体/位置：本地源码仓」（四槽第一槽恒为
  「本地源码仓」；人工注释写的是具体载体路径，字面不会等于该固定串）。

三态解读（把「重建被旧 render 覆盖」变成当次可发现的判据）：
  全绿                       = 新 render 覆盖全量，且无新鲜旧 render 写入
  old_synth > 0、active = 0   = 存量旧 render 未被重切（重建未做 / 未覆盖该域）
  active_old_synth > 0        = 「刚刚被写了旧 render」——存在活跃污染源
                                （持旧代码的常驻 md_cg MCP server 正在覆盖重建成果），
                                须先处置污染源再重建，否则重建成果必被刷回。
  versioned < total           = 存在「形态达标但无版本戳（或版本戳落后）」的节点，
                                说明该节点由早于当前契约的 render 产出（存量未重切）。

输出单行 JSON，ok 为总闸；任一域不达即 sys.exit(1)；未提供 MDCG_ROOT 即 sys.exit(2)。

用法：
  MDCG_ROOT=<认知图库根> python scripts/mdcg_verify_render_meta.py
"""
import os
import sys
import json
import time
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

# 生效条件：环境变量 MDCG_ROOT 非空时取其值；为空时打印 ok=False 的单行 JSON 并以退出码 2 结束（fail-closed，不猜测库根）。
ROOT = (os.environ.get("MDCG_ROOT") or "").strip()
if not ROOT:
    print(json.dumps(
        {"ok": False, "error": "未提供认知图库根：设环境变量 MDCG_ROOT"},
        ensure_ascii=False))
    sys.exit(2)

from md_cg import nodefile  # noqa: E402
from md_cg import codeindex  # noqa: E402

# 要求的契约代际：直接取本仓常量（同源，不硬编码版本号）。
REQ_RV = int(getattr(codeindex, "RENDER_VERSION", 1))

DOMAINS = ("md_cg", "compiler")
KN = os.path.join(ROOT, "knowledge")
META_PREFIX = "# " + nodefile.INDEX_META_MARK + "："
COND_PREFIX = "# 生效条件："
# 旧契约（RENDER_VERSION=1）合成区产出的生效条件行恒含该四槽第一槽的值。
# 人工注释写的是具体载体路径（如「仓根 md_cg/selfreport.py」），字面不等于该固定串。
SYNTH_MARK = "载体/位置：本地源码仓"
ACTIVE_WINDOW_S = 300  # 「新鲜写入」窗口：重建后落入此窗的旧 render 即活跃污染证据

_now = time.time()
dom = collections.defaultdict(collections.Counter)
rvdist = collections.defaultdict(collections.Counter)
for d, _s, fs in os.walk(KN):
    for f in fs:
        if not (f.startswith("code_") and f.endswith(".md")):
            continue
        p = os.path.join(d, f)
        try:
            with open(p, "r", encoding="utf-8",
                      errors="replace") as fh:
                fm, content = nodefile.loads(fh.read())
        except Exception:
            continue
        r = str((fm.get("code_ref") or {}).get("root") or "")
        rl = r.replace("/", "\\").rstrip("\\").lower()
        hit = None
        for name in DOMAINS:
            if rl.endswith("\\" + name):
                hit = name
        if hit is None:
            continue
        c = dom[hit]
        c["total"] += 1
        # 行级判定（见模块 docstring「判据缺陷史」）：全文 substring 会把源码区人工
        # 注释与新契约元条件行一并误判——两代契约的该行串本就同源。
        _lines = [ln.strip() for ln in content.splitlines()]
        if any(ln.startswith(META_PREFIX) for ln in _lines):
            c["meta_indep"] += 1
        if any(ln.startswith(COND_PREFIX) and SYNTH_MARK in ln
               for ln in _lines):
            c["old_synth"] += 1
            try:
                fresh = (_now - os.path.getmtime(p)) <= ACTIVE_WINDOW_S
            except OSError:
                fresh = False
            if fresh:
                c["active_old_synth"] += 1
                if not c["active_sample"]:
                    c["active_sample"] = p
        if any(ln.startswith(COND_PREFIX) for ln in _lines):
            c["has_human_cond"] += 1
        # 版本戳判据：code_ref.render_version 与本仓 codeindex.RENDER_VERSION 同源比对
        rv = (fm.get("code_ref") or {}).get("render_version")
        rvdist[hit][rv if isinstance(rv, int) else "missing"] += 1
        if isinstance(rv, int) and rv >= REQ_RV:
            c["versioned"] += 1
        elif not c["versioned_sample"]:
            c["versioned_sample"] = "%s（render_version=%s）" % (p, rv)

out = {"ok": True, "required_render_version": REQ_RV, "domains": {}, "hint": []}
for name in DOMAINS:
    c = dom[name]
    ok = (c["total"] > 0 and c["meta_indep"] == c["total"]
          and c["old_synth"] == 0 and c["active_old_synth"] == 0
          and c["versioned"] == c["total"])
    out["domains"][name] = {
        "total": c["total"], "meta_indep": c["meta_indep"],
        "old_synth": c["old_synth"],
        "active_old_synth": c["active_old_synth"],
        "has_human_cond": c["has_human_cond"],
        "versioned": c["versioned"],
        "render_version_dist": {str(k): v for k, v in sorted(
            rvdist[name].items(), key=lambda kv: str(kv[0]))},
        "ok": ok}
    out["ok"] = out["ok"] and ok
    if c["active_old_synth"] > 0:
        out["hint"].append(
            "%s: 检测到 %d 个新鲜旧 render 写入（样本 %s）——存在活跃污染源"
            "（持旧代码的常驻 md_cg MCP server 正在覆盖重建成果）；"
            "先 python scripts/mdcg_stale_servers.py kill --pid <PID> 再重建。"
            % (name, c["active_old_synth"], c["active_sample"] or "-"))
    if c["versioned"] < c["total"]:
        out["hint"].append(
            "%s: %d/%d 节点带 >=%d 的 render_version 戳（缺口 %d，样本 %s）"
            "——存量节点由旧契约 render 产出，需重切；"
            "重建后若缺口复现，说明存在活跃污染源。"
            % (name, c["versioned"], c["total"], REQ_RV,
               c["total"] - c["versioned"], c["versioned_sample"] or "-"))

print(json.dumps(out, ensure_ascii=False))
sys.exit(0 if out["ok"] else 1)
