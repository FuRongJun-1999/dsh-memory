# -*- coding: utf-8 -*-
"""只读验收：md_cg / compiler 域 code 节点是否已全部为新 render 产物。

判据（机械，与 nodefile.INDEX_META_MARK 契约同源）：
  meta_indep       —— 正文含独立成行的 `# 索引元条件：`（新 render 第三区产物）
  old_synth        —— 正文含 `# 生效条件：载体/位置：`（旧 render 四槽合成冒充形态）
  active_old_synth —— 上述 old_synth 中「文件 mtime 落在最近 ACTIVE_WINDOW_S 秒内」者

某域 ok ⟺ total > 0 且 meta_indep == total 且 old_synth == 0 且 active_old_synth == 0
（全量重建后应为 meta_indep == total、old_synth == 0）

三态解读（把「重建被旧 render 覆盖」变成当次可发现的判据）：
  全绿                       = 新 render 覆盖全量，且无新鲜旧 render 写入
  old_synth > 0、active = 0   = 存量旧 render 未被重切（重建未做 / 未覆盖该域）
  active_old_synth > 0        = 「刚刚被写了旧 render」——存在活跃污染源
                                （持旧代码的常驻 md_cg MCP server 正在覆盖重建成果），
                                须先处置污染源再重建，否则重建成果必被刷回。

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

DOMAINS = ("md_cg", "compiler")
KN = os.path.join(ROOT, "knowledge")
META = "# " + nodefile.INDEX_META_MARK + "："
SYNTH = "# 生效条件：载体/位置："
COND = "# 生效条件："
ACTIVE_WINDOW_S = 300  # 「新鲜写入」窗口：重建后落入此窗的旧 render 即活跃污染证据

_now = time.time()
dom = collections.defaultdict(collections.Counter)
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
        if META in content:
            c["meta_indep"] += 1
        if SYNTH in content:
            c["old_synth"] += 1
            try:
                fresh = (_now - os.path.getmtime(p)) <= ACTIVE_WINDOW_S
            except OSError:
                fresh = False
            if fresh:
                c["active_old_synth"] += 1
                if not c["active_sample"]:
                    c["active_sample"] = p
        if COND in content:
            c["has_human_cond"] += 1

out = {"ok": True, "domains": {}, "hint": []}
for name in DOMAINS:
    c = dom[name]
    ok = (c["total"] > 0 and c["meta_indep"] == c["total"]
          and c["old_synth"] == 0 and c["active_old_synth"] == 0)
    out["domains"][name] = {
        "total": c["total"], "meta_indep": c["meta_indep"],
        "old_synth": c["old_synth"],
        "active_old_synth": c["active_old_synth"],
        "has_human_cond": c["has_human_cond"],
        "ok": ok}
    out["ok"] = out["ok"] and ok
    if c["active_old_synth"] > 0:
        out["hint"].append(
            "%s: 检测到 %d 个新鲜旧 render 写入（样本 %s）——存在活跃污染源"
            "（持旧代码的常驻 md_cg MCP server 正在覆盖重建成果）；"
            "先 python scripts/mdcg_stale_servers.py kill --pid <PID> 再重建。"
            % (name, c["active_old_synth"], c["active_sample"] or "-"))

print(json.dumps(out, ensure_ascii=False))
sys.exit(0 if out["ok"] else 1)
