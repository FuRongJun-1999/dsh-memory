# -*- coding: utf-8 -*-
"""test_t65a_supersede_real —— T65 真实陈旧事实的「旧→新」覆盖演示验收。

在 E-T15a t1 已交付、已过 gate 的覆盖机制（`mdcg._supersede_try`）之上，
用 **T65 的真实陈旧事实** 把「旧→新」覆盖走一遍：
  · 覆盖键 = topic（旧值与新值写同一个 key）；
  · 默认口径（`kg.list_nodes()`）只见新节点，旧者不在列表里；
  · 旧节点 fm.superseded=true 且 superseded_by==新节点 id；
  · 审计口径（`kg.list_nodes(include_superseded=True)`）同时见两条；
  · 新节点正文反映新事实。

真实五对（key=topic）：
  1. server.host                    : 134.175.111.148 → 100.73.185.0
  2. assistant.ports.SuperMemory    : 6767 → 已由 /opt/assistant-gateway 接管
  3. infra.component （astrbot）    : 被新事实盖掉
  4. infra.component （napcat）     : 被新事实盖掉
  5. import.kb                      : import_kb.py → /opt/assistant-gateway

⚠ 覆盖开关同判定面开关 `MDCG_JUDGMENT`（真源 `judgment_rules.is_enabled`），
  **默认关**：未显式开启时同 key 二次写入仍按原样成两个节点、fm 无
  superseded 夹带。故覆盖段都在写完旧节点、写新节点**之前**显式
  `os.environ["MDCG_JUDGMENT"]="1"`，finally 恢复原值，不污染他段。

⚠ 已知边界（实测观察，非本测试要锁的口径）：`infra.component` 是**粗粒度键**
  ——astrbot 与 napcat 在 T65 共用同一个 key。同库内两条不同组件写同一个
  key 会互相覆盖（后写者盖掉先写者），且 `_supersede_try` 只标记**首个**
  匹配的既有节点。故 [A] 段五对各自用**独立临时库**（真实键原样）；
  [A2] 段同库演示时把两个组件拆成独立 key（`infra.component.astrbot` /
  `infra.component.napcat`），只验「同库多个 key 同时覆盖互不干扰」。

口径说明（与 test_t15a_supersede.py 同）：
- 真 frontmatter 只能经 `kg.get(nid)["frontmatter"]` 取——索引条目是扁平
  快照，没有 `frontmatter` 子字典；
- 「旧节点被标记」走包含口径 `list_nodes(include_superseded=True)` 或直读
  `kg.get(旧 nid)`（get 直读盘面，不受默认排除影响）；
- 节点计数用 `len(kg.list_nodes(...))`：默认口径=不含已废弃，包含口径=含之。

本测试**只用已交付机制**，不改 mdcg.py / mdcos.py / judgment_rules.py，
也不新增实现。

运行：cd D:\\wook\\lingshu-src && python -X utf8 -m md_cg.test_t65a_supersede_real
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg import mdcg                      # noqa: E402
from md_cg.mdcos import MdCGOS              # noqa: E402
from md_cg import judgment_rules as jr      # noqa: E402

passed = failed = 0

_ENV_KEY = "MDCG_JUDGMENT"


# ── helper: 造一个临时库并返回 MdCGOS 实例 ──
def _mk_cg():
    return MdCGOS(tempfile.mkdtemp(prefix="mdcg_t65a_"))


# ── check wrapper ──
def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:300])


# ── 读取节点（默认不含已废弃） ──
def _read_default(cg, nid):
    """默认口径读取——不含已废弃节点。"""
    got = cg.get(nid)
    if not got:
        return None
    fm = got.get("frontmatter") or {}
    if fm.get("superseded") is True:
        return None
    return got


# ── fm helper：经 get() 取真 frontmatter（索引里没有 fm） ──
def _fm(cg, nid):
    got = cg.get(nid)
    return (got or {}).get("frontmatter") or {}


# ── helper: 带 try/finally 地开关覆盖开关 ──
def _judgment_on():
    """开启 MDCG_JUDGMENT（覆盖开关同判定面开关），返回恢复函数。"""
    prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"

    def _restore():
        if prev is not None:
            os.environ[_ENV_KEY] = prev
        else:
            os.environ.pop(_ENV_KEY, None)

    return _restore


# ── T65 真实陈旧事实的五对『旧→新』（key=topic，[A] 段每对独立库） ──
#: (场景标签, topic key, 旧 id, 旧正文, 新 id, 新正文, 新正文必须出现的字样)
REAL_PAIRS = (
    ("1/5 server.host", "server.host",
     "t65a_server_host_old", "服务器 IP: 134.175.111.148（T65 旧事实）",
     "t65a_server_host_new", "服务器 IP: 100.73.185.0（T65 新事实）",
     "100.73.185.0"),
    ("2/5 assistant.ports.SuperMemory", "assistant.ports.SuperMemory",
     "t65a_supermem_old", "SuperMemory 端口: 6767（T65 旧事实）",
     "t65a_supermem_new",
     "SuperMemory 端口: 已由 /opt/assistant-gateway 接管（T65 新事实）",
     "/opt/assistant-gateway"),
    ("3/5 infra.component astrbot", "infra.component",
     "t65a_infra_astrbot_old", "astrbot：承载 QQ 机器人侧对话（T65 旧事实）",
     "t65a_infra_astrbot_new",
     "astrbot：已停用，其职责由 assistant-gateway 全量接管（T65 新事实）",
     "assistant-gateway"),
    ("4/5 infra.component napcat", "infra.component",
     "t65a_infra_napcat_old", "napcat：承载 OneBot 协议接入（T65 旧事实）",
     "t65a_infra_napcat_new",
     "napcat：已停用，其职责由 assistant-gateway 全量接管（T65 新事实）",
     "assistant-gateway"),
    ("5/5 import.kb", "import.kb",
     "t65a_importkb_old", "知识库导入脚本 import_kb.py（T65 旧事实）",
     "t65a_importkb_new",
     "知识库导入脚本 /opt/assistant-gateway/bin/import_kb.py（T65 新事实）",
     "/opt/assistant-gateway"),
)


# ---------------------------------------------------------------------------
# [A] 五对真实陈旧事实逐一覆盖（每对独立临时库）
# ---------------------------------------------------------------------------

def _one_pair(label, topic, old_id, old_content, new_id, new_content,
              must_have, kg):
    """在同一临时库 kg 上跑一对『旧→新』覆盖。返回 (旧 nid, 新 nid)。"""
    nid_old = kg.add(old_id, old_content, topic=topic)
    check("[%s] 旧节点写入成功（%s）" % (label, old_id), nid_old is not None)

    nid_new = kg.add(new_id, new_content, topic=topic)
    check("[%s] 新节点写入成功（%s）" % (label, new_id), nid_new is not None)

    # 1) 默认口径只见新节点：旧节点不在 list_nodes() 里
    default_ids = [n.get("nid") for n in kg.list_nodes()]
    check("[%s] 默认口径只见新节点（旧节点已排除）" % label,
          nid_new in default_ids and nid_old not in default_ids,
          "default_ids=%s" % str(default_ids)[:300])

    # 2) 旧节点 fm superseded=true 且 superseded_by==新 id
    fm_old = _fm(kg, nid_old)
    check("[%s] 旧节点 fm superseded=true" % label,
          fm_old.get("superseded") is True,
          "fm=%s" % fm_old)
    check("[%s] 旧节点 fm superseded_by==新节点 id" % label,
          fm_old.get("superseded_by") == nid_new,
          "superseded_by=%r" % fm_old.get("superseded_by"))

    # 3) 审计口径同时见两条
    all_ids = [n.get("nid")
               for n in kg.list_nodes(include_superseded=True)]
    check("[%s] 审计口径同时见旧新两条" % label,
          nid_old in all_ids and nid_new in all_ids,
          "all_ids=%s" % str(all_ids)[:300])

    # 4) 新节点内容反映新事实
    new_got = kg.get(nid_new) or {}
    check("[%s] 新节点正文反映新事实（含 %r）"
          % (label, must_have),
          must_have in (new_got.get("content") or ""),
          "content=%s" % (new_got.get("content") or "")[:200])

    return nid_old, nid_new


def test_a_real_pairs_independent():
    print("[A] T65 真实五对『旧→新』覆盖（每对独立临时库，键=topic）")
    restore = _judgment_on()
    try:
        for label, topic, oid, oc, nid, nc, mh in REAL_PAIRS:
            _one_pair(label, topic, oid, oc, nid, nc, mh, _mk_cg())
    finally:
        restore()


# ---------------------------------------------------------------------------
# [A2] 同一库内五对覆盖（每对一个 key，互不干扰）
# ---------------------------------------------------------------------------

#: 同库共用一个库对象：astrbot / napcat 共用 T65 的粗粒度键 infra.component，
#: 同库内会判为同一 key 互相覆盖（见模块头「已知边界」），故此处两个组件各
#: 拆成独立 key，只验「同库多 key 同时覆盖互不干扰」。
SHARED_PAIRS = (
    ("server.host",
     "t65a_s_server_host_old", "服务器 IP: 134.175.111.148（T65 旧事实）",
     "t65a_s_server_host_new", "服务器 IP: 100.73.185.0（T65 新事实）"),
    ("assistant.ports.SuperMemory",
     "t65a_s_supermem_old", "SuperMemory 端口: 6767（T65 旧事实）",
     "t65a_s_supermem_new",
     "SuperMemory 端口: 已由 /opt/assistant-gateway 接管（T65 新事实）"),
    ("infra.component.astrbot",
     "t65a_s_astrbot_old", "astrbot：承载 QQ 机器人侧对话（T65 旧事实）",
     "t65a_s_astrbot_new",
     "astrbot：已停用，其职责由 assistant-gateway 全量接管（T65 新事实）"),
    ("infra.component.napcat",
     "t65a_s_napcat_old", "napcat：承载 OneBot 协议接入（T65 旧事实）",
     "t65a_s_napcat_new",
     "napcat：已停用，其职责由 assistant-gateway 全量接管（T65 新事实）"),
    ("import.kb",
     "t65a_s_importkb_old", "知识库导入脚本 import_kb.py（T65 旧事实）",
     "t65a_s_importkb_new",
     "知识库导入脚本 /opt/assistant-gateway/bin/import_kb.py（T65 新事实）"),
)


def test_a2_real_pairs_shared():
    print("[A2] 同一库内五对『旧→新』覆盖（每对一个 key，互不干扰）")
    restore = _judgment_on()
    try:
        kg = _mk_cg()
        old_ids = []
        for topic, oid, oc, nid, nc in SHARED_PAIRS:
            old_ids.append(kg.add(oid, oc, topic=topic))
        new_ids = []
        for topic, oid, oc, nid, nc in SHARED_PAIRS:
            new_ids.append(kg.add(nid, nc, topic=topic))

        check("默认口径有效节点计数为 5（五个新者）",
              len(kg.list_nodes()) == 5,
              "nodes=%d" % len(kg.list_nodes()))
        check("审计口径节点计数为 10（五旧五新）",
              len(kg.list_nodes(include_superseded=True)) == 10,
              "nodes=%d"
              % len(kg.list_nodes(include_superseded=True)))
        default_ids = [n.get("nid") for n in kg.list_nodes()]
        check("默认口径恰为五个新节点",
              set(default_ids) == set(new_ids),
              "default=%s new=%s" % (str(sorted(default_ids))[:200],
                                     str(sorted(new_ids))[:200]))
        # 每条旧节点都被当次的新节点盖掉（互不干扰）
        for (topic, oid, oc, nid, nc), oid_v, nid_v in zip(
                SHARED_PAIRS, old_ids, new_ids):
            fm = _fm(kg, oid_v)
            check("[A2 %s] 旧节点 superseded_by==对应新节点" % topic,
                  fm.get("superseded") is True
                  and fm.get("superseded_by") == nid_v,
                  "fm=%s" % fm)
    finally:
        restore()


# ---------------------------------------------------------------------------
# [A3] 覆盖可回溯：旧节点仍在盘面，审计口径可读出完整来龙去脉
# ---------------------------------------------------------------------------

def test_a3_audit_traceability():
    print("[A3] 覆盖可回溯：旧节点未删，审计口径可读旧值与 superseded_by")
    restore = _judgment_on()
    try:
        kg = _mk_cg()
        nid_old = kg.add("t65a_trace_old",
                         "知识库导入脚本 import_kb.py（T65 旧事实）",
                         topic="import.kb")
        nid_new = kg.add("t65a_trace_new",
                         "知识库导入脚本 /opt/assistant-gateway/bin/import_kb.py"
                         "（T65 新事实）",
                         topic="import.kb")

        # 旧节点正文没有被删/改写——「覆盖」是读取口径上的让位，不是物理抹除
        old_got = kg.get(nid_old) or {}
        check("旧节点仍可读取（覆盖不物理删除）",
              old_got.get("content") is not None
              and "import_kb.py" in (old_got.get("content") or ""),
              "content=%s" % (old_got.get("content") or "")[:200])

        # 审计口径的列表条目自带 frontmatter——单点在 list_nodes
        audit_rows = {n.get("nid"): n
                      for n in kg.list_nodes(include_superseded=True)}
        old_row = audit_rows.get(nid_old) or {}
        fm_row = old_row.get("frontmatter") or {}
        check("审计口径返回的旧条目带真 frontmatter（superseded=true）",
              fm_row.get("superseded") is True,
              "row_fm=%s" % fm_row)
        check("审计口径的旧条目 superseded_by 指向新节点",
              fm_row.get("superseded_by") == nid_new,
              "superseded_by=%r" % fm_row.get("superseded_by"))

        # 新旧落在不同文件（不是原地改写）
        new_row = audit_rows.get(nid_new) or {}
        check("新旧节点盘路径不同（是两个文件）",
              bool(old_row.get("path")) and bool(new_row.get("path"))
              and old_row.get("path") != new_row.get("path"),
              "old_path=%r new_path=%r" % (old_row.get("path"),
                                           new_row.get("path")))
    finally:
        restore()


# ---------------------------------------------------------------------------
# [B] 不同 key 不误盖
# ---------------------------------------------------------------------------

def test_b_distinct_keys():
    print("[B] 不同 key 不误盖：两条共存、都无 superseded")
    restore = _judgment_on()
    try:
        kg = _mk_cg()
        nid_a = kg.add("t65b_supermem", "SuperMemory 端口: 6767",
                       topic="assistant.ports.SuperMemory")
        nid_b = kg.add("t65b_server", "服务器 IP: 100.73.185.0",
                       topic="server.host")
        check("不同 topic 两条共存（默认口径 2 节点）",
              len(kg.list_nodes()) == 2,
              "nodes=%d" % len(kg.list_nodes()))
        fm_a = _fm(kg, nid_a)
        fm_b = _fm(kg, nid_b)
        check("SuperMemory 条 fm 无 superseded",
              fm_a.get("superseded") is not True, "fm=%s" % fm_a)
        check("server.host 条 fm 无 superseded",
              fm_b.get("superseded") is not True, "fm=%s" % fm_b)
        check("不同 topic 的节点互不进入对方覆盖关系",
              fm_a.get("superseded_by") is None
              and fm_b.get("superseded_by") is None,
              "a_by=%r b_by=%r" % (fm_a.get("superseded_by"),
                                   fm_b.get("superseded_by")))

        # 同库再来一个第三种 key，仍各自为政
        nid_c = kg.add("t65b_importkb",
                       "知识库导入脚本 import_kb.py",
                       topic="import.kb")
        check("第三种 key 也各自为政（默认口径 3 节点）",
              len(kg.list_nodes()) == 3
              and _fm(kg, nid_c).get("superseded") is not True,
              "nodes=%d fm=%s" % (len(kg.list_nodes()), _fm(kg, nid_c)))
    finally:
        restore()


# ---------------------------------------------------------------------------
# [C] 默认关回归
# ---------------------------------------------------------------------------

def test_c_default_fallback():
    print("[C] 默认关回归：未设/显式 0 MDCG_JUDGMENT → 同 key 仍 2 个节点")
    # 与 t15a 的 [D] 段同构：未设开关时同 key 二次写入仍 2 个节点、
    # fm 无 superseded 夹带。
    prev = os.environ.get(_ENV_KEY)
    os.environ.pop(_ENV_KEY, None)
    try:
        # ── i. 未设 MDCG_JUDGMENT ──
        kg = _mk_cg()
        nid1 = kg.add("t65c_v1", "服务器 IP: 134.175.111.148",
                      topic="server.host")
        nid2 = kg.add("t65c_v2", "服务器 IP: 100.73.185.0",
                      topic="server.host")
        check("未设开关时同 key 二次写入仍 2 个节点",
              len(kg.list_nodes(include_superseded=True)) == 2,
              "nodes=%d" % len(kg.list_nodes(include_superseded=True)))
        fm1 = _fm(kg, nid1)
        fm2 = _fm(kg, nid2)
        check("未设开关时 fm 无 superseded 夹带",
              "superseded" not in fm1 and "superseded" not in fm2,
              "fm1_keys=%s fm2_keys=%s"
              % (list(fm1.keys()), list(fm2.keys())))

        # ── ii. 显式 MDCG_JUDGMENT=0 ──
        kg2 = _mk_cg()
        os.environ[_ENV_KEY] = "0"
        try:
            nid3 = kg2.add("t65c_v3", "SuperMemory 端口: 6767",
                           topic="assistant.ports.SuperMemory")
            nid4 = kg2.add("t65c_v4",
                           "SuperMemory 端口: 已由 /opt/assistant-gateway 接管",
                           topic="assistant.ports.SuperMemory")
            check("显式0时同 key 二次写入仍 2 个节点",
                  len(kg2.list_nodes(include_superseded=True)) == 2,
                  "nodes=%d" % len(kg2.list_nodes(include_superseded=True)))
            fm3 = _fm(kg2, nid3)
            fm4 = _fm(kg2, nid4)
            check("显式0时 fm 无 superseded 夹带",
                  "superseded" not in fm3 and "superseded" not in fm4,
                  "fm3_keys=%s fm4_keys=%s"
                  % (list(fm3.keys()), list(fm4.keys())))
        finally:
            os.environ.pop(_ENV_KEY, None)
    finally:
        if prev is not None:
            os.environ[_ENV_KEY] = prev


# ---------------------------------------------------------------------------
# [D] 机制版本自证（不重复实现，只确认用的是 E-T15a 的同一入口）
# ---------------------------------------------------------------------------

def test_d_mechanism_identity():
    print("[D] 机制自证：覆盖入口同 E-T15a 已交付实现")
    check("mdcg._supersede_try 存在（E-T15a t1 交付点）",
          callable(getattr(mdcg, "_supersede_try", None)),
          "attr=%r" % getattr(mdcg, "_supersede_try", None))
    prev = os.environ.get(_ENV_KEY)
    try:
        os.environ.pop(_ENV_KEY, None)
        check("is_enabled() 在未设 MDCG_JUDGMENT 时为 False（默认关）",
              jr.is_enabled() is False,
              "is_enabled=%r" % jr.is_enabled())
        os.environ[_ENV_KEY] = "1"
        check("is_enabled() 在显式 1 时为 True",
              jr.is_enabled() is True,
              "is_enabled=%r" % jr.is_enabled())
        os.environ[_ENV_KEY] = "0"
        check("is_enabled() 在显式 0 时为 False",
              jr.is_enabled() is False,
              "is_enabled=%r" % jr.is_enabled())
    finally:
        if prev is not None:
            os.environ[_ENV_KEY] = prev
        else:
            os.environ.pop(_ENV_KEY, None)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    global passed, failed
    print("===== md_cg.test_t65a_supersede_real"
          "（T65 真实陈旧事实旧→新覆盖验收） =====")
    os.environ.pop(_ENV_KEY, None)       # 全程自管开关状态
    test_a_real_pairs_independent()
    test_a2_real_pairs_shared()
    test_a3_audit_traceability()
    test_b_distinct_keys()
    test_c_default_fallback()
    test_d_mechanism_identity()
    print("\n===== t65a supersede real：%d 通过，%d 失败 ====="
          % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
