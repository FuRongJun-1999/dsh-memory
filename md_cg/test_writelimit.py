# -*- coding: utf-8 -*-
"""md_cg · 自动写入限流与同构聚合（流水污染治理）写入侧 + 读侧整理。

覆盖：
  A 模板签名：同模板异数字同签名 / 长文 None / 短骨架 None
  B 同构聚合：第 2+ 条并入既有（merge_count+1，不新增节点）
  C 频率限制：窗口内超量 DEFER；其他 role 不受影响
  D 保护优先：hint≥0.7 不限流
  E 层豁免：knowledge 不聚合不限流
  F env 关闭：MDCG_WRITELIMIT=0 放行
  G 留痕：_forgetting.jsonl 有 limiter 记录
  H tidy：已落盘同构组聚合 + 成员降权 + 永不删除
  I SustainLoop：auto_tidy 参数与调度字段

运行：python -m md_cg.test_writelimit
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time

from .mdcos import MdCGOS
from . import writelimit

# ---------------------------------------------------------------- 测试脚手架

_d = tempfile.mkdtemp(prefix="mdcg_wl_")
cg = MdCGOS(_d)
root = cg.root
N = [0]


def check(name: str, cond, detail: str = "") -> None:
    assert cond, f"[FAIL] {name} {detail}"
    print(f"[ok] {name}")


def _write(node_id, content, layer="contextual", gated=True,
           hint=None, role="user"):
    """remember_gated 快捷封装（单测直接注入固定 id 便于断言）。"""
    kw = {}
    if hint is not None:
        kw["importance_hint"] = hint
    return cg.remember_gated(node_id, content, layer=layer, role=role,
                             gated=gated, **kw)


# ---------------------------------------------------------------- A 模板签名

check("A1 同模板异数字 → 同签名",
      writelimit.template_signature("批次247收官记忆")
      == writelimit.template_signature("批次248收官记忆"))
check("A2 长文（≥200）→ None（正经记忆不聚合）",
      writelimit.template_signature("长" * 200) is None)
check("A3 短骨架（<4）→ None（防「好的/收到」误聚）",
      writelimit.template_signature("好的 001") is None)
check("A4 URL/时间戳归一 → 同签名",
      writelimit.template_signature("同步 2024 完成")
      == writelimit.template_signature("同步 2025 完成"))
check("A5 标题模板优先（正文长也聚合）",
      writelimit.template_signature(
          "# 功能名：批次247收官记忆\n" + "正文" * 150)
      == writelimit.template_signature(
          "# 功能名：批次248收官记忆\n" + "另文" * 150)
      and writelimit.template_signature(
          "# 功能名：批次247收官记忆\n" + "正文" * 150) is not None)

# ---------------------------------------------------------------- B 同构聚合

r1 = _write("wl_001", "批次247收官记忆")
check("B1 首条放行 ACCEPT", r1["verdict"] == "ACCEPT", str(r1.get("gate")))
r2 = _write("wl_002", "批次248收官记忆")
check("B2 第二条 CONVERGE→MERGE",
      r2["verdict"] == "MERGE" and r2.get("merged_into") == "wl_001",
      str(r2.get("gate")))
check("B3 聚合不新增节点", cg.get("wl_002") is None)
tgt = cg.get("wl_001")
check("B4 正文追加聚合行", "【聚合" in (tgt.get("content") or ""))
check("B5 merge_count+1",
      int(tgt["frontmatter"].get("merge_count", 0)) == 1)
# B6 精确重复 → DROP（模拟会话重启后 hooks 重复 memorize 同一事件）：
# 与既有节点正文完全一致 = 零新信息，交回旧闸门 DROP 语义（对齐 test_p9
# 「确定性内部冗余 → DROP 先于 MERGE」），不追加重复聚合行
r_f1 = _write("wl_f1", "会议纪要模板甲乙丙丁版")
check("B6a 首写 ACCEPT", r_f1["verdict"] == "ACCEPT", str(r_f1.get("gate")))
writelimit._save(cg, {"sigs": writelimit._load(cg)["sigs"], "rate": {}})
r_f2 = _write("wl_f2", "会议纪要模板甲乙丙丁版")   # 与 wl_f1 同文
check("B6b 精确重复 → DROP（不落库不强化）",
      r_f2["verdict"] == "DROP" and cg.get("wl_f2") is None
      and "merge_count" not in cg.get("wl_f1")["frontmatter"],
      str(r_f2.get("gate")))

# ---------------------------------------------------------------- C 频率限制

# 换不同模板绕开聚合，只压频率：9 条连写，第 9 条应 DEFER（RATE_MAX=8）
for i in range(8):
    _write(f"wl_r{i}", f"盘点条目甲乙丙丁戊{i}号")
r9 = _write("wl_r9", "盘点条目甲乙丙丁戊9号")
check("C1 窗口超量 DEFER",
      r9["verdict"] == "DEFER" and "ratelimit" in (r9.get("gate") or {})
      .get("reason", ""), str(r9.get("gate")))
# DEFER 节点不落盘
check("C2 DEFER 不落盘", cg.get("wl_r9") is None)
# 其他 role 不受影响（各自独立窗口）
r_other = _write("wl_r10", "盘点条目甲乙丙丁戊10号", role="tool-output")
check("C3 其他 role 独立窗口",
      r_other["verdict"] in ("ACCEPT", "MERGE"), str(r_other.get("gate")))

# ---------------------------------------------------------------- D 保护优先

r_hi = _write("wl_hi1", "高价值条目甲乙丙丁1号", hint=0.9)
r_hi2 = _write("wl_hi2", "高价值条目甲乙丙丁2号", hint=0.9)
check("D1 hint≥0.7 跳过限流（不聚合）",
      r_hi2["verdict"] == "ACCEPT" and cg.get("wl_hi2") is not None,
      str(r_hi2.get("gate")))

# ---------------------------------------------------------------- E 层豁免

writelimit._save(cg, {"sigs": {}, "rate": {}})   # 清状态隔离本节
r_k1 = _write("wl_k1", "知识条目甲乙丙丁1号", layer="knowledge")
r_k2 = _write("wl_k2", "知识条目甲乙丙丁2号", layer="knowledge")
check("E1 knowledge 不聚合不限流",
      r_k1["verdict"] == "ACCEPT" and r_k2["verdict"] == "ACCEPT",
      f"{r_k1.get('gate')}/{r_k2.get('gate')}")

# ---------------------------------------------------------------- F env 关闭

writelimit._save(cg, {"sigs": {}, "rate": {}})
os.environ["MDCG_WRITELIMIT"] = "0"
try:
    r_off = _write("wl_off", "批次999收官记忆")
    check("F1 env 关闭放行", r_off["verdict"] in ("ACCEPT", "MERGE"),
          str(r_off.get("gate")))
finally:
    os.environ.pop("MDCG_WRITELIMIT", None)

# ---------------------------------------------------------------- G 留痕

_log = os.path.join(root, "_forgetting.jsonl")
lims = []
if os.path.exists(_log):
    with open(_log, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("limiter"):
                lims.append(rec)
check("G1 限流留痕 _forgetting.jsonl",
      any(r.get("verdict") == "MERGE" for r in lims)
      and any(r.get("verdict") == "DEFER" for r in lims),
      f"limiter recs={len(lims)}")

# ---------------------------------------------------------------- H tidy

writelimit._save(cg, {"sigs": {}, "rate": {}})
os.environ["MDCG_WRITELIMIT"] = "0"      # 绕过写入限流，直造存量同构组
try:
    for i in range(5):
        _write(f"wl_t{i}", f"巡检批次{i}收官记忆")
finally:
    os.environ.pop("MDCG_WRITELIMIT", None)
dry = writelimit.tidy_contextual(cg, apply=False)
check("H1 dry-run 盘出同构组", dry["groups"] >= 1
      and dry["members"] >= 4, str(dry["groups"]))
before = len(cg.index["nodes"])
tidy = writelimit.tidy_contextual(cg, apply=True, min_group=3)
check("H2 apply 后节点总数不变（永不删除）",
      len(cg.index["nodes"]) == before,
      f"{before}->{len(cg.index['nodes'])}")
m0 = cg.get("wl_t0")
m1 = cg.get("wl_t1")
check("H3 主节点收编成员清单", "整理聚合" in (m0.get("content") or "")
      and "wl_t1" in (m0.get("content") or ""))
check("H4 成员降权 + tidy:converged",
      "tidy:converged" in (m1["frontmatter"].get("tags") or [])
      and float(m1["frontmatter"]["importance"]) <= 0.3,
      str(m1["frontmatter"].get("importance")))

# ---------------------------------------------------------------- I SustainLoop

from .sustain import SustainLoop, DEFAULT_TIDY_INTERVAL  # noqa: E402

lp = SustainLoop(cg, name="wl_test", auto_tidy=True,
                 tidy_interval=111.0)
check("I1 auto_tidy 透传", lp.auto_tidy is True and lp.tidy_interval == 111.0)
check("I2 默认间隔 6h", DEFAULT_TIDY_INTERVAL == 21600.0)
lp.stop()

# ---------------------------------------------------------------- 收尾

print("\nAll writelimit tests passed.")
shutil.rmtree(_d, ignore_errors=True)
