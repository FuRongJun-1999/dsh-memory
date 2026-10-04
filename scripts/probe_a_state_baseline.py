# -*- coding: utf-8 -*-
"""A 项（口径收口）基线探针：L0 事件台账 / 检验强度 / 幽灵引用 的读写实测。

对照结构（多主体世界模型对齐 v0.1 §4 路线 A）：
  · A1 已落地机制的**现场读数**——状态事件五元台账（md_cg/state_events.py）与
    check_strength 字段，与「动工前承载探针」并列：原探针证明 remember_event(meta)
    可作为临时承载（有回读），但无 append-only 语义、无五元强校验、无 kind 闭集；
    本探针把两代承载同时打印，读数差即 A1 的落点。
  · A2 动工前的**幽灵引用基线**——写入「被引对象不存在」的句子时 linkref 的现行
    行为（edges 现状），以及正文显式引用已存在节点的对照；A2（幽灵引用检查器，
    短语层标记、不拒收）动工后复跑对照。

隔离临时库（tempfile.mkdtemp），不触碰活库。用法：python -X utf8 scripts/probe_a_state_baseline.py
"""
import json
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, ".")
from md_cg.mdcos import MdCGOS
from md_cg import state_events
from md_cg.writepipe import default_pipeline

root = tempfile.mkdtemp(prefix="mdcg_aprobe_")
cg = MdCGOS(root)
pipe = default_pipeline()   # linkref 钩子只在写链上（walk：MCP op=write 同路径）
print("root =", root)

# 六要素齐全的头（写入链的 audit 闸要求；直调 cg.add 不受该闸约束）
H = ("# 功能名：蜡烛使用\n# 生效条件：在家时\n# 子功能：无\n"
     "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n")


def _write(node_id, body):
    return pipe.execute(cg, {"op": "write", "node_id": node_id,
                             "content": H + body + "\n",
                             "layer": "knowledge",
                             "content_kind": "text",
                             "verification_basis": "test"})


def _edges_of(node_id):
    fm = ((cg.get(node_id) or {}).get("frontmatter")) or {}
    return fm.get("edges") or []


# ============ P1 幽灵引用现状（A2 改前基线·短语层）：自由文本回指，被引对象不存在 ============
out1 = _write("ghost_candle", "可以允许你在帐篷里点那根你上次买的香薰蜡烛。")
fm = ((cg.get("ghost_candle") or {}).get("frontmatter")) or {}
print("P1 写链出口 keys:", sorted(out1.keys())[:8],
      "| committed:", out1.get("committed"))
edges = _edges_of("ghost_candle")
print("P1 幽灵引用节点 edges 数:", len(edges),
      "| edges:", json.dumps(edges, ensure_ascii=False)[:200])
print("P1 writer/harness 现值:", repr(fm.get("writer")), "/", repr(fm.get("harness")),
      "（None 属结构预期：归属注入在 MdCGSecure._attribution 库层，生产 MCP 路径落值；"
      "本探针经 MdCGOS 直调、无 principal）")

# P1b 幽灵 id（裸 id 形态但库内不存在）：既有 known 白名单防幽灵边——预期 0 条
out1b = _write("ghost_id_node", "参照 goblin_candle 那条记载。")
edges1b = _edges_of("ghost_id_node")
print("P1b 幽灵 id 引用 edges 数:", len(edges1b),
      "| edges:", json.dumps(edges1b, ensure_ascii=False)[:200])

# ============ P2 对照：正文含**已存在裸 id** 引用（linkref 正常解析路径，预期 1 条）============
out0 = _write("prior_node", "集市购物，周末进行。")
out2 = _write("ref_exists", "prior_node 那条是依据。")
edges2 = _edges_of("ref_exists")
print("P2 prior_node 落盘:", out0.get("committed"),
      "| ref_exists 落盘:", out2.get("committed"),
      "| edges 数:", len(edges2),
      "| edges:", json.dumps(edges2, ensure_ascii=False)[:240])

# ============ P3 事件承载对照：旧承载 remember_event(meta) vs 新台账 state_events ============
r = cg.remember_event("user", "搬家事件：住所 帐篷→海景别墅",
                      tags=["state-event"],
                      meta={"subject": "鲸娘", "slot": "住所", "old": "帐篷",
                            "new": "海景别墅", "round": 553, "evidence": "用户侧 r0553"})
print("P3a remember_event ok:", json.dumps(
    {k: r.get(k) for k in ("event", "dropped")}, ensure_ascii=False)[:160])
evs = cg.recent_events(limit=5)
print("P3a recent count:", len(evs))
if evs:
    print("P3a last event keys:", sorted(evs[-1].keys()))
    print("P3a meta 回读:", json.dumps(evs[-1].get("meta"), ensure_ascii=False)[:240])

rec = state_events.append(
    cg, "鲸娘", "住所", old="帐篷", new="海景别墅", kind="migration",
    seq=553, evidence="用户侧 r0553", actor="zcode")
print("P3b state_events.append 落盘:", json.dumps(
    {k: rec.get(k) for k in ("subject", "slot", "old", "new", "kind", "seq",
                             "evidence", "actor")}, ensure_ascii=False))
back = state_events.read(cg, subject="鲸娘", slot="住所")
print("P3b 回读条数:", len(back), "| kind 过滤:",
      len(state_events.read(cg, kind="migration")),
      "| 非命中过滤:", len(state_events.read(cg, subject="别的角色")),
      "| limit=1:", len(state_events.read(cg, limit=1)))
for bad, why in ((dict(subject="", slot="x", new="v"), "空 subject"),
                 (dict(subject="x", slot="  ", new="v"), "空白 slot"),
                 (dict(subject="x", slot="s", old=None, new=None), "old/new 同空"),
                 (dict(subject="x", slot="s", new="v", kind="bogus"), "非法 kind")):
    try:
        state_events.append(cg, **bad)
        print("P3b 校验缺失（应拒未拒）：", why)
    except ValueError as e:
        print("P3b 拒绝(%s) ok:" % why, str(e)[:60])

# ============ P4 check_strength 实测（A1 已落地）：落键 / 缺省 / 继承 / 非法 ============
cg.add("cs_node", "# 功能名：鲸娘住在哪里\n# 生效条件：常驻\n住所是海景别墅。\n",
       layer="knowledge", verification_basis="test", check_strength="smoking_gun")
cs1 = ((cg.get("cs_node") or {}).get("frontmatter") or {}).get("check_strength")
print("P4 落键:", repr(cs1))
cg.add("cs_plain", "# 功能名：无强度声明\n# 生效条件：常驻\n正文。\n",
       layer="knowledge", verification_basis="test")
cs2 = ((cg.get("cs_plain") or {}).get("frontmatter") or {}).get("check_strength")
print("P4 缺省不落键:", "check_strength" not in (
    (cg.get("cs_plain") or {}).get("frontmatter") or {}), "| 读值:", repr(cs2))
cg.add("cs_node", "# 功能名：鲸娘住在哪里\n# 生效条件：常驻\n住所是海景别墅（再述）。\n",
       layer="knowledge", verification_basis="test")
cs3 = ((cg.get("cs_node") or {}).get("frontmatter") or {}).get("check_strength")
print("P4 覆写继承:", repr(cs3))
try:
    cg.add("cs_bad", "# 功能名：非法强度\n# 生效条件：常驻\n正文。\n",
           layer="knowledge", verification_basis="test", check_strength="bogus")
    print("P4 非法强度未拒（应拒未拒）")
except ValueError as e:
    print("P4 非法强度拒绝 ok:", str(e)[:80])

print("DONE")
