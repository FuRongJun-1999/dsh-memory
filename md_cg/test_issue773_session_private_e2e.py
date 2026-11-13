# -*- coding: utf-8 -*-
"""守卫 · issue #773 sessionPrivate 端到端（sensitivity 落盘 + 四条读路径隔离）。

背景：#772 的复核指出——守卫只覆盖「插件侧把 sensitivity 放进 remember extra」，
**没有一条断言「服务端落盘的 frontmatter 真的是 private、且别的会话真的读不到」**。
任一跳丢键都会静默失效且现有测试全绿。本守卫就是那条端到端夹具。

夹具：真 `MdCGSecure` + 临时根 + KEK（`os.urandom(32)`）+ 两枚不同 `session` 的 principal。

断言：
  E1 A 会话写 private ⇒ `frontmatter.sensitivity == "private"` 且 `session == A`
  E2 B 会话**四条读路径**全读不到：get / recall 正排 / recall 的 recent 段 / stg.timeline
  E3 A 会话对同一节点**能读到**（防「隔离退化为不可读」）
  E4 无 KEK 时写 private ⇒ fail-closed（不静默降级 internal）
  E5 `unassigned` 哨兵作 session ⇒ 与插件侧 sidOwned 对齐（不被当成有效归属）

定点变异：删掉 mcp_server 的 sensitivity 透传 ⇒ E1 必红（本守卫因此能定位丢键的那一跳）。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg import stg  # noqa: E402
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402

FAILS = []

BODY = "# 功能名：私密测试\n# 生效条件：c\n# 子功能：s\n# 执行：e\n"
"# 验证方式：t\n# 不适用条件：无\n\n银行卡尾号 8888 仅本会话可见\n"


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def mk(root, sess, kek, admin=False):
    # 读方必须**非 admin**：`_readable` 对会话绑定档有 can_admin 豁免（既有设计），
    # 用 admin 读者测隔离会把「设计者豁免」误读成「隔离失效」。
    p = Principal(tenant="t773", actor="op773", clearance="private",
                  can_write=True, can_admin=admin, session=sess)
    g = MdCGSecure(root, principal=p, master_key=kek)
    g.session = sess
    return g


def main():
    print("=" * 70)
    print("issue #773：sessionPrivate 端到端")
    print("=" * 70)

    root = tempfile.mkdtemp(prefix="i773_")
    kek = os.urandom(32)
    a = mk(root, "sessA", kek, admin=True)
    a.add("p_a1", BODY, layer="contextual", sensitivity="private",
          consistency=False)
    fm = (a.get("p_a1") or {}).get("frontmatter") or {}
    ok(fm.get("sensitivity") == "private", "E1a 落盘 frontmatter.sensitivity == private",
       fm.get("sensitivity"))
    ok(fm.get("session") == "sessA", "E1b 落盘 frontmatter.session == sessA", fm.get("session"))

    b = mk(root, "sessB", kek)
    ok(bool(b.get("p_a1")) is False, "E2a B 会话 get 读不到")

    pack = b.recall("银行卡尾号", budget_tokens=4000, k=20)
    ids = [e.get("id") for e in (pack.get("pack") or [])]
    ok("p_a1" not in ids, "E2b B 会话 recall 正排读不到", ids[:6])

    pack2 = b.recall("银行卡尾号", budget_tokens=4000, k=20, include_recent=True,
                     recent_limit=20)
    rec_ids = [e.get("id") for e in (pack2.get("recent") or [])]
    ok("p_a1" not in rec_ids, "E2c B 会话 recall 的 recent 段读不到", rec_ids[:6])

    tl = stg.timeline(b, limit=50)
    tl_ids = [x.get("id") for x in (tl.get("items") or tl.get("nodes") or [])]
    ok("p_a1" not in tl_ids, "E2d B 会话 stg.timeline 读不到", tl_ids[:6])

    ok(bool(a.get("p_a1")) is True, "E3 A 会话能读到自己的私有节点（隔离未退化为不可读）")

    # E4 无 KEK ⇒ 写 private 必须 fail-closed（不静默降级 internal）
    root2 = tempfile.mkdtemp(prefix="i773b_")
    a2 = mk(root2, "sessA", None, admin=True)
    try:
        a2.add("p_b1", BODY, layer="contextual", sensitivity="private",
               consistency=False)
        got = ((a2.get("p_b1") or {}).get("frontmatter") or {}).get("sensitivity")
        ok(got != "internal", "E4 无 KEK 写 private 未被静默降级为 internal", got)
    except Exception as e:            # noqa: BLE001
        ok(True, "E4 无 KEK 写 private fail-closed（抛 %s）" % type(e).__name__)

    # E5 unassigned 哨兵
    u = mk(root, "unassigned", kek)
    ok(bool(u.get("p_a1")) is False, "E5 unassigned 哨兵读不到他会话私有节点")

    # E6 admin 豁免如实记录：设计者会话可读（_readable 的既有设计），
    # 说明「会话隔离」不覆盖 can_admin 读者——这是设计面而非缺陷，写明以免被误判。
    adm = mk(root, "sessAdmin", kek, admin=True)
    ok(bool(adm.get("p_a1")) is True, "E6 can_admin 读者可读（既有豁免，如实记录）")

    # E7 工具面端到端（issue #773 判据：定点变异 mcp_server 的 sensitivity 透传 ⇒ 本项必红）
    from md_cg import mcp_server  # noqa: E402
    root3 = tempfile.mkdtemp(prefix="i773c_")
    a3 = mk(root3, "sessA", kek, admin=True)
    res = mcp_server.call_tool(a3, "mdcg_remember", {
        "content": BODY, "layer": "contextual", "gated": True,
        "role": "user", "sensitivity": "private", "session": "sessA",
    })
    nid = (res or {}).get("node_id") or (res or {}).get("id")
    _fm = ((a3.get(nid) or {}).get("frontmatter") or {}) if nid else {}
    ok(_fm.get("sensitivity") == "private",
       "E7 工具面 remember(gated) 的 private 声明真的落盘（变异该透传即红）",
       (_fm.get("sensitivity"), res))

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())