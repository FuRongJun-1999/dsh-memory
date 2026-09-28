# -*- coding: utf-8 -*-
"""md_cg · 可见性/读出口零闸低危机械同批（N204/N205/N226/N227/N228/N229）

六项，**修法同范式**：出口接既有单点（`_readable` 经跨层包装
`security.visible_to`/`node_visible`，或对齐规范出口的 `require_op` 词），
不新写第二份密级/会话口径。

  ① N205 `md_cg/trust.py:934-971` + `:975-985` × `mcp_server.py:1814/1826-1834`：
     `describe` 在 `cg.get` 被读闸拒后**回落索引条目**仍报 ok=True，并附
     `load_ledger` 全量行（行内 `reason` 含明文证据串）⇒ 任何持 read op 的身份
     （含无令牌 guest）读走读闸拒绝节点的验证态/依赖/履历与裁决证据。
  ② N204 `md_cg/docindex.py:186/192-199`：父节摘要先按 MAX_SUMMARY 取满，再并入
     小/超层级子节摘要后整体截断 ⇒ 父节直接正文 ≥200 字时被合并子节的文字
     **一个字都进不去**（合并的唯一目的即「否则这些小节的正文只存在于父节 ref
     区间里，检索不到」）——静默丢索引（非攻击面，可检索性缺陷）。
  ③ N226 `md_cg/provenance.py:427`（`_node_digest` 直读 cg.index）+`539-543`：
     `cg(op="edges", expand_nodes=true)` 的端点摘要与边拓扑零可见性闸，两端都
     不可见的边照返回、`aggregates.sample` 亦回 `child->parent`（同库同身份的
     `stg.timeline` stg.py:133/172 早已接线 `_readable`——本处是漏网出口）。
  ④ N227 `md_cg/evolution.py:265/332` × `mdcos.py:3261`（health_os 挂
     evolution.summary）× `mcp_server.py:3071-3072/2125/3288-3292`：演化台账
     （`_evolution/ledger.md`）出口无可见性/身份闸，且工具面粗粒度 op 映射
     使 guest 可达；同一份自由文本还被 health_os→`cg(op=info)`/`mdcg_health`
     带出。
  ⑤ N228 `mcp_server.py:3063`（"mdcg_protect":"write"）/`:3264`/`:1155-1179`
     （snapshot 分支）× `protect.py:153-170`：写保护面被映射到**粗粒度 write**
     （protect op 在 cg 面是 designer 专属）⇒ 任何 can_write 角色可
     `action=snapshot` 真落盘 `_protected_history` 且 `protect.snapshot` 全文
     零 `_audit`（越作用域＋无审计＋污染后续 override 快照链）。
  ⑥ N229 `md_cg/forgetting.py:289-306` × `mcp_server.py:3068/3267/1162-1163`：
     `forgetting.history` 逐行 `json.loads(_forgetting.jsonl)` 原文返回
     （actor/verdict/reason/importance/duplicate_with），零可见性、零归属过滤。

修复（最小改动，全部复用单点）：
  · 新增跨层可见性单点 `security.visible_to(cg, entry)` / `node_visible(cg, node_id)`
    （口径 = `_readable`：无钩子=不限制、有钩子=按判据、判据异常/不可证=不可见；
    `can_admin` 豁免）。`mdcos._note_visible` 改为委派它（同一实现）。
  · ① `trust.describe` 在 get 被拒且节点不可见时返回 `node_not_found`（「不可见
    即不存在」，与 get/search/recall 同口径）；`trust.load_ledger` 逐行按行所属
    node_id 过滤。
  · ② `docindex` 摘要改为**预算预分配**：合并段最多占 MAX_SUMMARY 的一半，父段
    按「总预算 − 合并段实占 − 分隔符」取 ⇒ 合并段保证进得去。
  · ③ `provenance._node_digest` 不可见端点返回 `present=False`（不附任何字段）；
    `find_edges` 在谓词过滤前先按「两端都可见」过滤边（半条边同样泄露隐藏端点
    id 与关系）。
  · ④ `evolution.entries` 逐行按 node_id 过滤（summary/patterns/history/show/
    health_os 全部经此单点）；工具面 `mdcg_evolution` op 由 read 对齐到规范出口
    的 `evolution`。
  · ⑤ `mdcg_protect` op 由 write 对齐到 `protect`（designer 专属）；`protect.snapshot`
    成功即 `_audit(action="snapshot")`。
  · ⑥ `forgetting.history` 逐行按 node_id 过滤；`mdcg_forgetting_history` op 由
    read 对齐到规范出口的 `protect`。

守卫（八组，全部临时库 + 哑主密钥 + 临时令牌库，**绝不触真实 ~/.mdcg**）：
  ⓿ 隔离自证 + 夹具；① N205 两出口（含设计者/可见节点阳性对照）；
  ② N204 纯函数三档父长（440/200/199）+ 上限契约 + 无合并段对照；
  ③ N226 边/摘要/聚合 + 可见边阳性对照；④ N227 工具面与库面 + health 面；
  ⑤ N228 工具面越权 + 审计留痕；⑥ N229 工具面 + 行级过滤；
  ⑦ 同族横扫（guest 只读面全扫，任何私密标记都不许出现）；
  ⑧ 源断言 + live floor。

如实边界（本轮残留，见报告）：演化账本/遗忘留痕的**自由文本内跨节点引用**
不做机械脱敏（只能按行所属 node_id 判定）；`trust.load_ledger` 对已删节点
（索引无条目）在有身份模型时 fail-closed 丢弃（设计者豁免）。

运行：python -X utf8 -m md_cg.test_n204_n205_n226_n227_n228_n229_exit_gates
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
import time

# ── 隔离前置：必须在 import md_cg 子模块**之前**（tokens/theory 等在模块级把
# aux_root() 冻成常量）——否则会指到真实 ~/.mdcg 并在那里建密钥/令牌库。 ──
_TMP = tempfile.mkdtemp(prefix="n2xx_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "34" * 32          # 哑主密钥（绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_ACTOR", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES",
           "PYTHONIOENCODING", "PYTHONUTF8"):
    os.environ.pop(_k, None)

from . import (crypto, docindex, evolution, forgetting,           # noqa: E402
               mcp_server, protect, provenance, security, tokens, trust)
from .datapath import aux_root            # noqa: E402
from .mdcos import MdCGSecure             # noqa: E402
from .security import Principal           # noqa: E402

atexit.register(lambda: _cleanup(_TMP))       # LIFO：晚于库层 _atexit_flush_all

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.join(_TMP, "cg")
PASS = FAIL = LIVE = 0
LIVE_FLOOR = 26
FAILS = []

S_DESIGN = "sess_n2xx_design"
EVID = "N2XX-EVID-XYZ-外部证据串"
EVO_ROW = "N2XX-EVO-RULE-XYZ"
EVO_VIS = "N2XX-EVO-VIS-OK"
PRIV_BODY = "# 功能名：私密节点\n# 正文：N2XX-PRIV-BODY（designer 私有）\n"
VIS_BODY = "# 功能名：共享节点\n# 正文：N2XX-VIS-BODY（internal 跨会话共享）\n"
# 遗忘闸门专用正文：必须与上面两条**不同**（重复度会判 DROP 而不落节点，
# 那么「阳性对照」就会因为节点不存在而被 fail-closed 过滤掉，断言形同空转）
FG_VIS_BODY = "# 功能名：闸门留痕节点\n# 正文：N2XX-FG-VIS-BODY（独立内容，闸门应 ACCEPT）\n"

N_PRIV = "n2xx_priv"
N_VIS = "n2xx_vis"
N_CHILD_PRIV = "n2xx_child_priv"
N_CHILD_VIS = "n2xx_child_vis"


def check(name, cond, detail="", live=False):
    global PASS, FAIL, LIVE
    if live:
        LIVE += 1
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s · %s" % (name, detail))


def _princ(role, clearance="internal", can_admin=False, session=None, actor=None):
    spec = tokens.role_spec(role)
    return Principal(tenant="default", actor=actor or ("n2xx-" + role),
                     clearance=clearance, can_write=bool(spec["can_write"]),
                     can_admin=can_admin, role=role, session=session,
                     layers_allow=spec["layers_allow"],
                     ops_allow=spec["ops_allow"], auth_mode="test")


_OPEN = []


def _secured(principal):
    cg = MdCGSecure(ROOT, principal=principal)
    _OPEN.append(cg)
    return cg


def _close_all():
    for cg in _OPEN:
        try:
            cg.close()
        except Exception:                      # noqa: BLE001 —— 清理面不得再抛
            pass


def _cleanup(path) -> bool:
    import gc
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        gc.collect()
        time.sleep(0.25)
    return not os.path.exists(path)


def _raises(fn, *a, **kw):
    """执行并返回 (ok, 异常类名/空, 结果/异常文本)。"""
    try:
        return True, "", fn(*a, **kw)
    except Exception as exc:                   # noqa: BLE001 —— 守卫要的是拒绝形态
        return False, type(exc).__name__, str(exc)


def _read_src(rel):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)
    with open(p, encoding="utf-8") as f:
        return f.read()


def _dump(x):
    try:
        return json.dumps(x, ensure_ascii=False, default=str)
    except Exception:                          # noqa: BLE001
        return str(x)


def _audit_rows(cg, action=None):
    out = []
    p = os.path.join(ROOT, protect.AUDIT_FILE)
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:                  # noqa: BLE001
                continue
            if action and r.get("action") != action:
                continue
            out.append(r)
    return out


# ---------------------------------------------------------------- N204 夹具
def _doc(parent_len, child_text, with_child=True):
    """构造一份 md：父节直接正文 parent_len 字（+ 可选一个小子节）。"""
    lines = ["# 父节标题", ""]
    lines.append("父节直接正文" + ("甲" * max(0, parent_len - 6)))
    if with_child:
        lines += ["", "## 小子节标题", "", child_text]
    return "\n".join(lines) + "\n"


def main():
    global LIVE
    # ---------- ⓿ 隔离自证 + 夹具 ----------
    print("[0] 隔离自证 + 夹具")
    _tok = tokens.token_file()
    check("0a 默认令牌库与 aux 根都落在守卫临时目录（绝不触真实凭据）",
          os.path.abspath(_tok).lower().startswith(os.path.abspath(_TMP).lower())
          and os.path.abspath(aux_root()).lower().startswith(
              os.path.abspath(_TMP).lower()),
          "tok=%s aux=%s" % (_tok, aux_root()))
    if not os.path.abspath(ROOT).lower().startswith(
            os.path.abspath(_TMP).lower()):
        print("FATAL: 隔离失败，中止（绝不带病跑真实库）")
        return 2

    design = _secured(_princ("designer", clearance="secret", can_admin=True,
                             session=S_DESIGN, actor="n2xx-design"))
    # 私密节点（private + 会话绑定）与共享节点（internal 跨会话）
    design.add(N_PRIV, PRIV_BODY, layer="knowledge", sensitivity="private",
               tags=["n2xx", "tag-PRIV-XYZ"], session=S_DESIGN)
    design.add(N_VIS, VIS_BODY, layer="knowledge", tags=["n2xx"])
    # 派生边：① 可见→不可见（N226 病灶）② 可见→可见（阳性对照）
    design.add(N_CHILD_PRIV, "# 功能名：派生边子节点（指向私密父）\n",
               layer="knowledge", tags=["n2xx"], derived_from=N_PRIV)
    design.add(N_CHILD_VIS, "# 功能名：派生边子节点（指向可见父）\n",
               layer="knowledge", tags=["n2xx"], derived_from=N_VIS)
    # 验证态台账：两条（私密节点 / 共享节点）
    design.verify(N_PRIV, EVID, "confirmed")
    design.verify(N_VIS, "N2XX-EVID-VIS-OK", "confirmed")
    design.flush()
    # 演化台账：两条（私密节点 / 共享节点）
    evolution.record(design, N_PRIV, pattern=EVO_ROW, missing="条件空间：未声明",
                     action="N2XX-EVO-DETAIL-XYZ")
    evolution.record(design, N_VIS, pattern=EVO_VIS, missing="条件空间：已声明",
                     action="N2XX-EVO-VIS-ACT")
    # 遗忘留痕：私密候选（DROP/ACCEPT 皆写行）+ 共享节点留痕
    design.remember_gated("n2xx_fg_priv", PRIV_BODY, layer="knowledge",
                          sensitivity="private", session=S_DESIGN,
                          verification_basis="test")
    design.remember_gated("n2xx_fg_vis", FG_VIS_BODY, layer="knowledge",
                          verification_basis="test")
    design.flush()
    _ev = len(evolution.entries(design, limit=0))
    _fh = len(forgetting.history(design, limit=100))
    check("0b 夹具就绪（私密/共享节点、两条边、台账/演化/遗忘留痕均在位）",
          design.index["nodes"].get(N_PRIV) is not None
          and design.index["nodes"].get(N_VIS) is not None
          and _ev >= 2 and _fh >= 2,
          "evo=%d forget=%d" % (_ev, _fh))

    guest = _secured(_princ("guest"))
    rec = _secured(_princ("record", session="sess_n2xx_rec"))
    # 阳性对照前置：其它身份确实读不到私密节点本体（既有闸仍然在位）
    check("0c 前置对照：guest/record 对私密节点 get→None（本批不重复修既有闸）",
          guest.get(N_PRIV) is None and rec.get(N_PRIV) is None)

    # ---------- ① N205 trust.status 两出口 ----------
    print("\n【①】N205 trust.status：describe 与 ledger 的可见性")
    ok_1, _e1, r_1 = _raises(mcp_server._dispatch, guest, "cg",
                             {"op": "status", "node_id": N_PRIV})
    check("1a guest cg(op=status,node_id=私密) 不再回落索引条目报 ok=True",
          (not ok_1) or (not (r_1 or {}).get("ok"))
          or (r_1 or {}).get("error") == "node_not_found",
          "ok=%r res=%r" % (ok_1, _dump(r_1)[:160]), live=True)
    ok_2, _e2, r_2 = _raises(mcp_server._dispatch, guest, "cg",
                             {"op": "status", "action": "ledger", "limit": 100})
    _led = _dump((r_2 or {}).get("rows") if ok_2 else r_2)
    check("1b guest 验证态台账不再含私密节点的裁决证据串",
          ok_2 and EVID not in _led and N_PRIV not in _led,
          "exc=%r EVID命中=%r priv命中=%r" % (_e2, EVID in _led, N_PRIV in _led),
          live=True)
    ok_3, _e3, r_3 = _raises(mcp_server._dispatch, guest, "cg",
                             {"op": "status", "node_id": N_VIS})
    check("1c 阳性对照：可见节点的验证态照常返回（未过度收口）",
          ok_3 and bool((r_3 or {}).get("ok"))
          and (r_3 or {}).get("verification_state") == "verified",
          "res=%r" % _dump(r_3)[:140], live=True)
    ok_4, _e4, r_4 = _raises(mcp_server._dispatch, design, "cg",
                             {"op": "status", "node_id": N_PRIV})
    check("1d 设计者（can_admin）仍可取私密节点验证态（治理本职不被误禁）",
          ok_4 and bool((r_4 or {}).get("ok")),
          "res=%r" % _dump(r_4)[:140], live=True)
    _led_d = _dump(trust.load_ledger(design, limit=200))
    check("1e 设计者台账仍含该证据串（未把治理面掏空）",
          EVID in _led_d, "len=%d" % len(trust.load_ledger(design, limit=200)),
          live=True)
    _lib = trust.describe(guest, N_PRIV)
    check("1f 库层 describe 同口径（单点在库不在工具面）",
          not _lib.get("ok") and _lib.get("error") == "node_not_found",
          _dump(_lib)[:140], live=True)

    # ---------- ② N204 docindex 摘要预算 ----------
    print("\n【②】N204 docindex：合并子节文字必须进得去")
    _uniq = "子节独有文本-ZZZ-仅此一处"
    for _plen, _tag in ((440, "2a"), (200, "2b"), (199, "2c")):
        items = docindex.extract(_doc(_plen, _uniq), path="x.md")
        _hit = any(_uniq in (it.get("summary_parts") or "") for it in items)
        check("%s 父节直接正文 %d 字时，被合并子节的独有文本仍在摘要中"
              % (_tag, _plen), _hit,
              "items=%d summaries=%r" % (len(items),
                                         [(it.get("name"), len(it.get("summary_parts") or ""))
                                          for it in items]), live=True)
    items_len = docindex.extract(_doc(440, _uniq), path="x.md")
    check("2d 摘要仍不超 MAX_SUMMARY 上限（契约不变）",
          all(len(it.get("summary_parts") or "") <= docindex.MAX_SUMMARY
              for it in items_len),
          "max=%r" % max(len(it.get("summary_parts") or "") for it in items_len))
    items_ctl = docindex.extract(_doc(300, "", with_child=False), path="x.md")
    check("2e 对照：无合并子节时父节自身文字照旧进摘要（预算改动无副作用）",
          bool(items_ctl) and "父节直接正文" in (items_ctl[0].get("summary_parts") or ""),
          _dump(items_ctl)[:120])

    # ---------- ③ N226 provenance.find_edges ----------
    print("\n【③】N226 派生边出口的可见性")
    ok_5, _e5, r_5 = _raises(mcp_server._dispatch, guest, "cg",
                             {"op": "edges", "expand_nodes": True, "limit": 50})
    _d5 = _dump(r_5 if ok_5 else _e5)
    check("3a guest 边列表不含指向私密节点的边（拓扑不泄露隐藏端点）",
          ok_5 and N_PRIV not in _d5,
          "exc=%r priv命中=%r" % (_e5, N_PRIV in _d5), live=True)
    _digests = []
    for _e in ((r_5 or {}).get("edges") or []) if ok_5 else []:
        for _k in ("child_node", "parent_node"):
            if isinstance(_e.get(_k), dict):
                _digests.append(_e[_k])
    check("3b guest 端点摘要不含私密节点（present=False 而非元数据照回）",
          ok_5 and all(d.get("id") != N_PRIV for d in _digests),
          "digests=%r" % [d.get("id") for d in _digests], live=True)
    check("3c 阳性对照：两端都可见的派生边照常返回",
          ok_5 and N_CHILD_VIS in _d5 and N_VIS in _d5,
          "exc=%r" % _e5, live=True)
    ok_6, _e6, r_6 = _raises(mcp_server._dispatch, design, "cg",
                             {"op": "edges", "expand_nodes": True, "limit": 50})
    check("3d 设计者仍看得到指向私密节点的边与摘要（全局观测本职）",
          ok_6 and N_PRIV in _dump(r_6), "exc=%r" % _e6, live=True)
    ok_7, _e7, r_7 = _raises(mcp_server._dispatch, guest, "cg",
                             {"op": "edges", "aggregation": "by_child",
                              "limit": 50})
    check("3e guest 聚合 sample 不再出现 child->priv 关系串",
          ok_7 and N_PRIV not in _dump(r_7),
          "exc=%r sample=%r" % (_e7, _dump((r_7 or {}).get("aggregates"))[:160]),
          live=True)

    # ---------- ④ N227 evolution 台账 ----------
    print("\n【④】N227 演化台账出口")
    ok_8, e_8, _r8 = _raises(mcp_server._dispatch, guest, "mdcg_evolution",
                             {"action": "entries", "limit": 50})
    check("4a guest 经工具面 mdcg_evolution 被 AccessDenied（与 cg op 同口径）",
          (not ok_8) and e_8 == "AccessDenied", "exc=%r" % e_8, live=True)
    _ge = evolution.entries(guest, limit=0)
    check("4b 库层 entries 逐行按 node_id 过滤（私密台账行整条不出）",
          all(r.get("node_id") != N_PRIV for r in _ge)
          and all(EVO_ROW not in _dump(r) for r in _ge),
          "rows=%r" % [_dump(r)[:60] for r in _ge][:4], live=True)
    check("4c 阳性对照：可见节点的演化条目照常返回",
          any(r.get("node_id") == N_VIS and EVO_VIS in _dump(r) for r in _ge),
          "rows=%d" % len(_ge), live=True)
    ok_9, _e9, r_9 = _raises(mcp_server._dispatch, guest, "mdcg_health", {})
    _hr = _dump(((r_9 or {}).get("os") or {}).get("evolution", {}).get("recent")
                if ok_9 else r_9)
    check("4d health 面（op=read 可达）带出的演化摘要不含私密台账行",
          ok_9 and N_PRIV not in _hr and EVO_ROW not in _hr,
          "exc=%r recent=%r" % (_e9, _hr[:160]), live=True)
    ok_10, _e10, r_10 = _raises(mcp_server._dispatch, design, "cg", {"op": "info"})
    _hrd = _dump(((r_10 or {}).get("os") or {}).get("evolution", {}).get("recent")
                 if ok_10 else r_10)
    check("4e 设计者 info 面仍带私密台账行（治理面不掏空）",
          ok_10 and EVO_ROW in _hrd, "exc=%r" % _e10, live=True)

    # ---------- ⑤ N228 写保护面 ----------
    print("\n【⑤】N228 写保护面：作用域 + 审计")
    _before = len(_audit_rows(design, "snapshot"))
    ok_11, e_11, _r11 = _raises(mcp_server._dispatch, rec, "mdcg_protect",
                                {"action": "snapshot", "node_id": N_VIS})
    check("5a record（can_write）经工具面 snapshot 被 AccessDenied（越作用域已闭）",
          (not ok_11) and e_11 == "AccessDenied", "exc=%r" % e_11, live=True)
    _snap = protect.snapshot(design, N_VIS)
    check("5b protect.snapshot 落盘即留痕（新增 action=snapshot 审计行）",
          bool(_snap) and len(_audit_rows(design, "snapshot")) == _before + 1,
          "snap=%r rows=%d→%d" % (_snap, _before,
                                  len(_audit_rows(design, "snapshot"))), live=True)
    ok_12, e_12, r_12 = _raises(mcp_server._dispatch, design, "mdcg_protect",
                                {"action": "stats"})
    check("5c 设计者 protect stats 照常可用（未过度收口）",
          ok_12 and (r_12 or {}).get("protected_count", -1) >= 0,
          "exc=%r res=%r" % (e_12, _dump(r_12)[:120]), live=True)
    ok_13, e_13, _r13 = _raises(mcp_server._dispatch, rec, "mdcg_protect",
                                {"action": "stats"})
    check("5d record 经工具面 protect stats 亦被 AccessDenied（盘点面不越权）",
          (not ok_13) and e_13 == "AccessDenied", "exc=%r" % e_13, live=True)

    # ---------- ⑥ N229 遗忘留痕 ----------
    print("\n【⑥】N229 遗忘留痕出口")
    ok_14, e_14, _r14 = _raises(mcp_server._dispatch, guest,
                                "mdcg_forgetting_history", {"limit": 100})
    check("6a guest 经工具面 mdcg_forgetting_history 被 AccessDenied",
          (not ok_14) and e_14 == "AccessDenied", "exc=%r" % e_14, live=True)
    _gh = forgetting.history(guest, limit=100)
    check("6b 库层 history 逐行按 node_id 过滤（私密候选行整条不出）",
          all(r.get("node_id") != "n2xx_fg_priv" for r in _gh)
          and PRIV_BODY not in _dump(_gh),
          "rows=%r" % [_dump(r)[:70] for r in _gh][:4], live=True)
    check("6c 阳性对照：共享节点的遗忘留痕照常返回",
          any(r.get("node_id") == "n2xx_fg_vis" for r in _gh),
          "rows=%d" % len(_gh), live=True)
    ok_15, e_15, _r15 = _raises(mcp_server._dispatch, rec,
                                "mdcg_forgetting_history", {"limit": 100})
    check("6d record 经工具面亦被 AccessDenied（他人写入裁决不跨身份外露）",
          (not ok_15) and e_15 == "AccessDenied", "exc=%r" % e_15, live=True)

    # ---------- ⑦ 同族横扫（guest 只读面全扫） ----------
    print("\n【⑦】同族横扫：guest 只读面不许出现任何私密标记")
    # 标记集：**必须绝不出现**的私密面内容（正文标记/证据串/演化行/私密标签）。
    # 私密节点 **id 本身**单独判（7c）：可见节点自身的 `derived_from` 声明里
    # 本来就会写出它的父 id（那是该可见节点自己的溯源字段，属另一面，本批
    # 不redact——见报告残留下结论）。
    _marks = (EVID, EVO_ROW, "N2XX-PRIV-BODY", "tag-PRIV-XYZ")
    _sweep = [
        ("cg", {"op": "status", "action": "ledger", "limit": 200}),
        ("cg", {"op": "status"}),
        ("cg", {"op": "edges", "expand_nodes": True, "limit": 200}),
        ("cg", {"op": "edges", "aggregation": "by_child", "limit": 200}),
        ("cg", {"op": "info"}),
        ("cg", {"op": "health"}),
        ("cg", {"op": "evolution", "action": "entries", "limit": 200}),
        ("cg", {"op": "protect", "action": "forgetting"}),
        ("mdcg_health", {}),
        ("mdcg_evolution", {"action": "entries", "limit": 200}),
        ("mdcg_protect", {"action": "stats"}),
        ("mdcg_forgetting_history", {"limit": 200}),
        ("mdcg_metacognition", {}),
        ("mdcg_self_state", {}),
        ("mdcg_identity", {}),
        ("mdcg_predict", {}),
        ("mdcg_causal", {}),
        ("mdcg_watermarks", {}),
        ("mdcg_whoami", {}),
        ("mdcg_service_info", {}),
        ("cg", {"op": "search", "query": "N2XX-PRIV-BODY"}),
        ("cg", {"op": "recall", "query": "N2XX-PRIV-BODY"}),
        ("mdcg_search", {"query": "N2XX-PRIV-BODY"}),
        ("mdcg_recall", {"query": "N2XX-PRIV-BODY"}),
    ]
    _hits, _okn, _id_dumps = [], 0, []
    _samples = {}
    for _name, _args in _sweep:
        _o, _ex, _res = _raises(mcp_server._dispatch, guest, _name, _args)
        if _o:
            _okn += 1
        _s = _dump(_res)
        for _m in _marks:
            if _m in _s:
                _hits.append("%s%r:%s" % (_name, _args, _m))
                _samples.setdefault("%s:%s" % (_name, _m), _s[:300])
        if N_PRIV in _s:
            _id_dumps.append((_name, _args, _s))
    check("7a guest 只读面全扫：私密正文/证据串/演化行/私密标签均不出现",
          not _hits, "命中=%r 样本=%r" % (_hits[:6], _samples), live=True)
    check("7b 横扫非空转（正常返回≥6 个出口，否则该断言无意义）",
          _okn >= 6, "成功返回出口数=%d/%d" % (_okn, len(_sweep)), live=True)
    # 7c：私密 id 若出现，只允许是「可见节点自身的 derived_from 声明」这一形态
    # （其余通道由 1b/3a/3b/3e/4b/4d/6b 分别钉死）
    check("7c 私密 id 的出现只限可见节点自身的 derived_from 声明（无第二通道）",
          all("derived_from" in _s for _n, _a, _s in _id_dumps),
          "含 id 出口=%r" % [(n, a) for n, a, _ in _id_dumps][:5], live=True)

    # ---------- ⑧ 源断言 + floor ----------
    print("\n【⑧】源断言（单点与接线在位）")
    _sec = _read_src("security.py")
    check("8a security 提供跨层可见性单点 visible_to/node_visible",
          "def visible_to(cg, entry)" in _sec and "def node_visible(cg, node_id)" in _sec)
    _os_ = _read_src("mdcos.py")
    check("8b mdcos._note_visible 委派单点（不另立第二份口径）",
          "return _security.visible_to(cg, e)" in _os_)
    _tr = _read_src("trust.py")
    check("8c trust.describe/load_ledger 接单点",
          "_security.node_visible(cg, node_id)" in _tr
          and "_security.node_visible(cg, r.get(\"node_id\"))" in _tr)
    _pv = _read_src("provenance.py")
    check("8d provenance._node_digest/find_edges 接单点",
          _pv.count("_security.node_visible(cg, nid)") >= 1
          and "_security.node_visible(cg, e.get(\"child\"))" in _pv
          and "_security.node_visible(cg, e.get(\"parent\"))" in _pv)
    check("8e evolution.entries 接单点",
          "_security.node_visible(cg, r.get(\"node_id\"))" in _read_src("evolution.py"))
    check("8f forgetting.history 接单点",
          "_security.node_visible(cg, (r or {}).get(\"node_id\"))"
          in _read_src("forgetting.py"))
    _pr = _read_src("protect.py")
    check("8g protect.snapshot 留痕（_audit action=\"snapshot\"）",
          '_audit(cg, "snapshot"' in _pr)
    _mcp = _read_src("mcp_server.py")
    check("8h 工具面 op 对齐：protect/evolution/forgetting_history",
          '"mdcg_protect": "protect"' in _mcp
          and '"mdcg_evolution": "evolution"' in _mcp
          and '"mdcg_forgetting_history": "protect"' in _mcp)
    check("8i docindex 摘要预算预分配（merged_budget）",
          "merged_budget" in _read_src("docindex.py"))
    print("  [INFO] live 断言数 = %d（floor=%d）" % (LIVE, LIVE_FLOOR))
    check("8j live 断言数不低于 floor（防空转绿）", LIVE >= LIVE_FLOOR,
          "live=%d" % LIVE)

    print("\n" + "=" * 64)
    print("PASS=%d  FAIL=%d  LIVE=%d" % (PASS, FAIL, LIVE))
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        _close_all()
        time.sleep(0.05)
    sys.exit(rc)
