# -*- coding: utf-8 -*-
"""test_lifecycle · 节点显式生命周期状态机（Pi 可学习优点 ②）

背景：状态散落四处各说各话——`writelimit` 用 tag `tidy:converged`、`forgetting`
用 importance 升降、`protect` 用 `fm.protected`、`_evolution/ledger.md` 记账本；
**没有任何地方校验「这一步迁移合不合法」**。本测试覆盖唯一真源 `lifecycle.py`
及其四条收口路径。

覆盖：① 纯函数裁决 ② 索引快照带状态（内存+磁盘） ③ 合法逐级迁移（历史+审计）
④ 非法迁移拒绝（负路由，且拒绝不留痕） ⑤ 幂等 ⑥ 受保护豁免降级 / 回升不受限
⑦ add 全量重建 fm 时的状态继承 ⑧ 存量回填 backfill ⑨ 收口点（writelimit /
forgetting） ⑩ 边界（节点不存在 / 永不删除）

运行：python -m md_cg.test_lifecycle
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from . import lifecycle, writelimit
from .forgetting import reinforce
from .mdcos import MdCGOS

_root = tempfile.mkdtemp(prefix="mdcg_life_")
cg = MdCGOS(_root)

_ok = 0
_fail = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[ok] " + name)
    else:
        _fail.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


def _fm(nid):
    return ((cg.get(nid) or {}).get("frontmatter")) or {}


def _idx(nid):
    return (cg.index.get("nodes") or {}).get(nid) or {}


def _disk_index():
    """读**磁盘** `_index.json`——「免读文件可查」的硬验收面。"""
    p = os.path.join(cg.root, "_index.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def _index_log():
    """读**增量索引日志**（ShardedLog 分片）——`flush()` 的实际落点（`_index.json`
    是快照，由 `rebuild_index()` 写）。"""
    out = []
    d = os.path.join(cg.root, "_index_log")
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        p = os.path.join(d, fn)
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def _audit():
    p = os.path.join(cg.root, lifecycle.AUDIT_FILE)
    out = []
    if os.path.exists(p):
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
    return out


# ------------------------------------------------------------ ① 纯函数裁决
check("①1 缺字段 / 未知值 / 非 dict → active（存量兼容，不猜测）",
      lifecycle.state_of({}) == "active"
      and lifecycle.state_of({lifecycle.STATE_FIELD: "frozen"}) == "active"
      and lifecycle.state_of(None) == "active")
check("①2 状态集内值原样返回",
      all(lifecycle.state_of({lifecycle.STATE_FIELD: s}) == s
          for s in lifecycle.STATES))
check("①3 合法迁移对可通行（逐级降级 + 逐级回升）",
      lifecycle.can_transition("active", "converged")
      and lifecycle.can_transition("converged", "demoted")
      and lifecycle.can_transition("demoted", "archived")
      and lifecycle.can_transition("archived", "active"))
check("①4 跳级迁移一律不通",
      not lifecycle.can_transition("active", "archived")
      and not lifecycle.can_transition("converged", "archived")
      and not lifecycle.can_transition("archived", "demoted"))
check("①5 同状态幂等可通行", lifecycle.can_transition("demoted", "demoted"))
check("①6 check 未知状态 → unknown_state",
      lifecycle.check("active", "frozen")[:2] == (False, "unknown_state"))
check("①7 check 同状态 → noop",
      lifecycle.check("active", "active")[:2] == (True, "noop"))
check("①8 check 跳级 → illegal_transition",
      lifecycle.check("active", "archived")[:2]
      == (False, "illegal_transition"))
check("①9 check 受保护降级 → protected；override 放行",
      lifecycle.check("active", "demoted", protected=True)[:2]
      == (False, "protected")
      and lifecycle.check("active", "demoted", protected=True,
                          override=True)[:2] == (True, "ok"))
check("①10 is_downgrade 方向正确（回升不算降级）",
      lifecycle.is_downgrade("active", "archived")
      and not lifecycle.is_downgrade("archived", "active"))

# ------------------------------------------------------------ ② 新节点与索引
n1 = cg.add("lc_n1", "生命周期状态机测试节点甲", layer="knowledge")
check("②1 新节点**显式**落 active（不再依赖缺省约定）",
      _fm(n1).get(lifecycle.STATE_FIELD) == "active", _fm(n1))
check("②2 索引快照带状态（内存）",
      _idx(n1).get(lifecycle.STATE_FIELD) == "active", _idx(n1))
cg.flush()
check("②3 增量日志（_index_log）带状态",
      any((r.get("e") or {}).get(lifecycle.STATE_FIELD) == "active"
          for r in _index_log() if r.get("id") == n1), _index_log())
cg.rebuild_index()
check("②4 磁盘 _index.json 快照带状态（免读文件即可回答「这节点什么状态」）",
      ((_disk_index().get("nodes") or {}).get(n1) or {}
       ).get(lifecycle.STATE_FIELD) == "active")

# ------------------------------------------------------------ ③ 合法逐级迁移
r1 = cg.set_state(n1, "converged", reason="同构聚合定型", actor="test")
check("③1 active→converged 通过且落盘",
      r1.get("ok") and r1.get("changed")
      and _fm(n1).get(lifecycle.STATE_FIELD) == "converged", r1)
check("③2 索引同步到 converged",
      _idx(n1).get(lifecycle.STATE_FIELD) == "converged")
r2 = cg.set_state(n1, "demoted", reason="弱化", actor="test")
r3 = cg.set_state(n1, "archived", reason="归档", actor="test")
check("③3 converged→demoted→archived 逐级通过",
      r2.get("ok") and r3.get("ok")
      and _fm(n1).get(lifecycle.STATE_FIELD) == "archived")
h1 = _fm(n1).get(lifecycle.HISTORY_FIELD) or []
check("③4 迁移历史逐条留痕（from/to/reason/actor）",
      len(h1) == 3 and h1[-1]["from"] == "demoted"
      and h1[-1]["to"] == "archived" and h1[-1]["reason"] == "归档"
      and h1[-1]["actor"] == "test", h1)
check("③5 审计 _lifecycle.jsonl 留痕 3 条",
      len([a for a in _audit() if a.get("node_id") == n1]) == 3, _audit())
check("③6 永不删除：archived 后节点文件仍在且可读",
      bool(cg.get(n1))
      and os.path.exists(os.path.join(cg.root, cg.get(n1)["path"])))

# ------------------------------------------------------------ ④ 非法迁移拒绝
n2 = cg.add("lc_n2", "生命周期状态机测试节点乙", layer="knowledge")
bad = cg.set_state(n2, "archived", reason="跳级归档", actor="test")
check("④1 跳级 active→archived 被拒（负路由，不抛）",
      (not bad.get("ok")) and bad.get("error") == "illegal_transition", bad)
check("④2 拒绝后 frontmatter 未被改动（不留痕）",
      _fm(n2).get(lifecycle.STATE_FIELD) in (None, "active")
      and not (_fm(n2).get(lifecycle.HISTORY_FIELD) or []), _fm(n2))
check("④3 拒绝后索引未被改动",
      _idx(n2).get(lifecycle.STATE_FIELD) in (None, "active"))
check("④4 未知状态被拒",
      cg.set_state(n2, "frozen").get("error") == "unknown_state")
check("④5 节点不存在如实上报（不静默创建）",
      cg.set_state("lc_missing", "converged").get("error") == "node_not_found")
try:
    lifecycle.require_transition("active", "archived")
    _hard = False
except lifecycle.TransitionError:
    _hard = True
check("④6 require_transition 硬拒（写路径抛异常）", _hard)
try:
    cg.add("lc_n2", "覆写并试图跳级归档", state="archived")
    _add_hard = False
except lifecycle.TransitionError:
    _add_hard = True
check("④7 add 覆写显式非法状态 → 硬拒", _add_hard)
check("④8 硬拒后磁盘内容未被改写（校验先于写盘）",
      _fm(n2).get(lifecycle.STATE_FIELD) in (None, "active"))

# ------------------------------------------------------------ ⑤ 幂等
h_before = len(_fm(n1).get(lifecycle.HISTORY_FIELD) or [])
aud_before = len([a for a in _audit() if a.get("node_id") == n1])
same = cg.set_state(n1, "archived", reason="重复归档", actor="test")
check("⑤1 同状态幂等（noop / changed=False）",
      same.get("ok") and same.get("changed") is False
      and same.get("code") == "noop", same)
check("⑤2 幂等不刷历史",
      len(_fm(n1).get(lifecycle.HISTORY_FIELD) or []) == h_before)
check("⑤3 幂等不写审计",
      len([a for a in _audit() if a.get("node_id") == n1]) == aud_before)

# ------------------------------------------------------------ ⑥ 受保护豁免降级
n3 = cg.add("lc_n3", "受保护节点丙", layer="knowledge", importance=0.8)
check("⑥0 新建即自动受保护（importance≥0.7）",
      _fm(n3).get("protected") is True, _fm(n3))
prot = cg.set_state(n3, "demoted", reason="试图降级", actor="test")
check("⑥1 受保护节点降级被拒 → protected 码",
      (not prot.get("ok")) and prot.get("error") == "protected", prot)
check("⑥2 拒绝后状态未变（保护 = 不可遗忘）",
      _fm(n3).get(lifecycle.STATE_FIELD) == "active")
ov = cg.set_state(n3, "demoted", reason="显式放行", actor="test",
                  override=True)
check("⑥3 override=True 放行降级",
      ov.get("ok") and _fm(n3).get(lifecycle.STATE_FIELD) == "demoted", ov)
up = cg.set_state(n3, "active", reason="回升不受限", actor="test")
check("⑥4 回升不受保护限制（无需 override）",
      up.get("ok") and _fm(n3).get(lifecycle.STATE_FIELD) == "active")

# ------------------------------------------------------------ ⑦ add 状态继承
n4 = cg.add("lc_n4", "状态继承节点丁", layer="knowledge")
cg.set_state(n4, "converged", reason="定型", actor="test")
cg.add("lc_n4", "覆写内容（裸 add，不带状态）", layer="knowledge")
check("⑦1 裸 add 覆写**继承**旧状态（不静默打回 active）",
      _fm(n4).get(lifecycle.STATE_FIELD) == "converged", _fm(n4))
check("⑦2 继承后索引仍是 converged",
      _idx(n4).get(lifecycle.STATE_FIELD) == "converged")
cg.add("lc_n4", "覆写并合法回升", layer="knowledge", state="active")
check("⑦3 显式合法迁移放行（converged→active）",
      _fm(n4).get(lifecycle.STATE_FIELD) == "active")
check("⑦4 新节点显式状态从 active 起算（active→converged 合法）",
      _fm(cg.add("lc_n5", "显式定型节点", layer="knowledge",
                 state="converged")).get(lifecycle.STATE_FIELD) == "converged")

# ------------------------------------------------------------ ⑧ 存量回填
node4 = cg.get(n4)
fm4 = dict(node4["frontmatter"])
fm4.pop(lifecycle.STATE_FIELD, None)                 # 造「旧库缺字段」形态
cg._write_node(n4, os.path.join(cg.root, node4["path"]), fm4,
               node4.get("content") or "")
_idx(n4).pop(lifecycle.STATE_FIELD, None)
check("⑧0 旧库形态成立（字段已摘除）",
      lifecycle.STATE_FIELD not in _fm(n4))
pre = lifecycle.backfill(cg, apply=False)
check("⑧1 dry-run 盘点缺失且不改盘",
      pre.get("dry_run") and n4 in (pre.get("planned") or [])
      and lifecycle.STATE_FIELD not in _fm(n4), pre)
app = lifecycle.backfill(cg, apply=True)
check("⑧2 apply 回填为显式 active",
      app.get("backfilled", 0) >= 1
      and _fm(n4).get(lifecycle.STATE_FIELD) == "active", app)
check("⑧3 回填幂等（第二次无缺失）",
      lifecycle.backfill(cg, apply=True).get("backfilled") == 0)
check("⑧4 缺字段节点在回填前也按 active 工作（state_of 缺省）",
      lifecycle.state_of({}) == "active")

# ------------------------------------------------------------ ⑨ 收口点
n6 = cg.add("lc_n6", "同构聚合成员节点", layer="contextual", importance=0.4)
node6 = cg.get(n6)
e6 = {"id": n6, "path": node6["path"],
      "frontmatter": dict(node6["frontmatter"]),
      "content": node6.get("content") or ""}
writelimit._demote(cg, e6)
check("⑨1 tidy 降权 → lifecycle_state=converged",
      _fm(n6).get(lifecycle.STATE_FIELD) == "converged", _fm(n6))
check("⑨2 兼容别名 tidy:converged tag 保留（历史数据不破）",
      "tidy:converged" in (_fm(n6).get("tags") or []))
check("⑨3 降权后索引同步 converged",
      _idx(n6).get(lifecycle.STATE_FIELD) == "converged")
_imp_before = float(_fm(n6).get("importance") or 0)
reinforce(cg, n6)
check("⑨4 MERGE 强化 → 逐级回升 active",
      _fm(n6).get(lifecycle.STATE_FIELD) == "active", _fm(n6))
check("⑨5 回升与 importance 强化同批落盘（+delta）",
      float(_fm(n6).get("importance") or 0) > _imp_before)
h6 = _fm(n6).get(lifecycle.HISTORY_FIELD) or []
check("⑨6 两处收口共用同一迁移历史（active→converged→active 两条，同一 actor 面）",
      len(h6) == 2 and (h6[0]["from"], h6[0]["to"]) == ("active", "converged")
      and (h6[1]["from"], h6[1]["to"]) == ("converged", "active")
      and h6[0]["actor"] == "sustain_tidy"
      and h6[1]["actor"] == "forgetting:reinforce", h6)
n7 = cg.add("lc_n7", "普通节点庚", layer="knowledge")
h7_before = len(_fm(n7).get(lifecycle.HISTORY_FIELD) or [])
reinforce(cg, n7)
check("⑨7 强化 active 节点：状态幂等（不刷历史、不误降）",
      _fm(n7).get(lifecycle.STATE_FIELD) == "active"
      and len(_fm(n7).get(lifecycle.HISTORY_FIELD) or []) == h7_before)

# ------------------------------------------------------------ ⑩ 边界
check("⑩1 状态字段名与裁决四态 state 不撞名（消歧）",
      lifecycle.STATE_FIELD == "lifecycle_state"
      and lifecycle.STATE_FIELD != "state")
check("⑩2 set_state 返回体恒带 from/to/code（可审计）",
      set(("from", "to", "code")) <= set(cg.set_state(n7, "active").keys()))
check("⑩3 迁移历史滚动上限（不无界膨胀）",
      lifecycle.HISTORY_KEEP > 0
      and len(_fm(n1).get(lifecycle.HISTORY_FIELD) or [])
      <= lifecycle.HISTORY_KEEP)

print("=" * 58)
print("test_lifecycle: %d 通过 / %d 失败" % (_ok, len(_fail)))
if _fail:
    print("失败项：" + "、".join(_fail))
shutil.rmtree(cg.root, ignore_errors=True)
raise SystemExit(1 if _fail else 0)
