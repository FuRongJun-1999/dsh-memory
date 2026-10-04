# -*- coding: utf-8 -*-
"""A2 探针：幽灵引用检查器（短语层标记 + id 层「目标晚于自身」告警）的改前基线。

对照结构（多主体世界模型对齐 v0.1 §4 路线 A 之 A2）：
  P1 短语层回指·无可解析出处（CD-WHALE-01 发现 C 的现实形态）→ 现状应零痕迹；
  P2 短语层回指·有 id 出处（合法对照）→ 现状应建 reference 边；
  P3 id 层「目标晚于自身」：source 声明 valid_from 远早于 target 的 created_at，
     正文引用 target → 现状应照常建边、无任何降级告警（A2 落点）；
  P4 反例对照：source 的 valid_from 晚于 target 创建时刻（正常时序）→ 应无告警。

隔离临时库（tempfile.mkdtemp），不触碰活库。A2 动工后复跑对照。
用法：python -X utf8 scripts/probe_a2_ghostref.py
"""
import json
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, ".")
from md_cg.mdcos import MdCGOS
from md_cg.writepipe import default_pipeline

root = tempfile.mkdtemp(prefix="mdcg_a2probe_")
cg = MdCGOS(root)
pipe = default_pipeline()
print("root =", root)

H = ("# 功能名：幽灵引用探针\n# 生效条件：探针环境\n# 子功能：无\n"
     "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n")


def _write(node_id, body, **kw):
    a = {"op": "write", "node_id": node_id, "content": H + body + "\n",
         "layer": "knowledge", "content_kind": "text",
         "verification_basis": "test"}
    a.update(kw)
    return pipe.execute(cg, a)


def _fm(node_id):
    return ((cg.get(node_id) or {}).get("frontmatter")) or {}


def _edges(node_id):
    return _fm(node_id).get("edges") or []


def _report(tag, out, node_id):
    fm = _fm(node_id)
    print(tag, "committed:", out.get("committed"),
          "| edges:", len(_edges(node_id)),
          "| 节点含 uncertain/ghost 类键:",
          sorted(k for k in fm if "uncertain" in k or "ghost" in k),
          "| 出口含告警键:", sorted(k for k in out if "ghost" in k or "warn" in k))


# ---- P1 短语层回指·无可解析出处（现状应零痕迹）----
out1 = _write("phrase_ghost", "可以允许你在帐篷里点那根你上次买的香薰蜡烛。"
                              "明明讲过那件事的。")
_report("P1", out1, "phrase_ghost")

# ---- P2 短语层回指·有 id 出处（合法对照，现状应建 1 条 reference 边）----
_write("prior_note", "集市采购的凭证记录。")
out2 = _write("phrase_ref", "上次说的那件事，见 prior_note 的记载。")
_report("P2", out2, "phrase_ref")

# ---- P3 id 层「目标晚于自身」（现状应照常建边、无告警）----
now = time.time()
_write("ghost_target", "晚出现的凭证节点。")
t_created = _fm("ghost_target").get("created_at")
out3 = _write("ghost_source_early", "依据见 ghost_target 记载。",
              valid_from=now - 100000)
_report("P3", out3, "ghost_source_early")
print("P3 时序读数: source.valid_from =", now - 100000,
      "target.created_at =", t_created,
      "| 目标晚于自身 =", (t_created or 0) > (now - 100000))

# ---- P4 反例对照：正常时序引用（现状无告警；A2 后也应无）----
out4 = _write("ghost_source_late", "依据见 ghost_target 记载。",
              valid_from=now + 10)
_report("P4", out4, "ghost_source_late")

print("DONE")
