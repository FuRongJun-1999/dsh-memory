# -*- coding: utf-8 -*-
"""md_cg · 写面绕闸族续深（N214 + N215 + N221 + N222，同批四写点）

四个写点同族同错型：**直调 `cg._write_node`（或改写既有节点的层位/正文），
全程既无 `principal.require_layer_write` 亦无 `protect.guard_write`**——同一身份
对**同层**的 `add` 被正常 `AccessDenied`，但这些出口照样落盘；且不抛错、不落
`_protected_history` 快照、不写 `_protected_audit.jsonl`（「同一库多条出口口径
不一致」，与 N131 / N197+N208 / N209 同一族）。

① **N214 `forgetting.reinforce`（MERGE 落库动作，`md_cg/forgetting.py:247/274`）**
   两个入口都裸调 `cg._write_node` 覆写既有节点：
     · `md_cg/mdcos.py:3380` = `remember_gated` 的 MERGE 分支；
     · `md_cg/mdcos.py:2783` = `cg(op=maintain, action=prefeed, write=true)` 的
       reinforce 分支（`md_cg/mcp_server.py:2748-2750` 只在**无写权**时才
       `require_admin`，故有写权的非管理身份一路直通）。
   持 write 身份（`tokens.py:150` reflect `layers_allow=('contextual',)`）对
   **self 层既有节点**以 `layer='self'` 发 `mdcg_remember(gated=true)`：
   `writelimit.check` 因形参层≠contextual 直接放行（`writelimit.py:141`）、
   `forgetting.assess` 按形参层过滤得重复度 1.0 → 判 MERGE → reinforce 改写
   `importance`/`merge_count`/`last_merge_at` 并自动打 `protected=True`。
   实测（修复前，本守卫红态）：`{'verdict':'MERGE','merged_into':'self214',
   'reinforced':{'importance':0.95,'merge_count':1,'protected':True}}`，
   同身份对同层 `add(self214, layer='self')` 却是 `AccessDenied`。

② **N215 `writelimit.converge_into`（CONVERGE 落库动作，`md_cg/writelimit.py:211/225`）**
   同构聚合兜底：`remember_gated` 先以 `(node_id=<anchor 节点>, layer='contextual')`
   预占位签名（该次 `add` 被保护闸拒，但 `check` 已落盘 `sig→anchor id` 映射，
   `writelimit.py:187`），再换正文重发 → `gate.verdict=CONVERGE/target=anchor`
   → 追加聚合行、`merge_count+1`（每次换正文追加一行），**anchor 层不可篡改
   节点被无痕追加**；`_forgetting.jsonl` 末行不含 anchor id（留痕不记目标）。

③ **N221 新增：`add` 覆写既有节点时层位由形参 `layer` 全权决定**
   （`md_cg/mdcg.py:1560/1571` 落层、`:1794-1801` 旧层同 id 文件 `os.remove`、
   `md_cg/mdcos.py:3889` 层闸校验**同一形参**）。传「自己可写层」即可覆写并
   顶替他层既有节点：新文件落自己层、旧层同 id 文件被删、索引改指新路径——
   语义等同 `_move_layer` 搬迁，却绕过 N209 的源/目标双 `protect.require_layer`
   与 `guard_move`，无降级审计、原内容被删（等于对他人层节点的**删除+顶替**）。

④ **N222 新增：`scrub._apply_offset`（calibrate 落库动作，`md_cg/scrub.py:718/747`）**
   全库遍历式改写 `layer∉(self,anchor)` 且 `evidence_count≥1` 的节点
   `confidence`/`calibration`：不过 principal 层白名单、不过 `guard_overwrite`、
   `override` 形参直通（含 `importance≥0.7` 的不可遗忘节点），无快照无审计。
   `md_cg/mcp_server.py:1671-1674`（`_scrub_call` 对 calibrate 不设
   `require_admin`）。持 sustain 身份（`layers_allow=('self',)`）即可改
   knowledge 层节点的置信度。

修复（最小改动 · 同族单点，**复用** N197/N208 新建的 `protect.guard_overwrite`
与 N209 新建的 `protect.require_layer`，不另造第二份口径）：
  ① `forgetting.reinforce` / `writelimit.converge_into` 写盘前统一过
     `protect.guard_overwrite(cg, target, layer=fm.layer, sensitivity=fm.sensitivity,
     override=…, actor=…)`——principal 层写闸在前（对照 `MdCGSecure.add`），引擎级
     `guard_write` 在后（对照 `MdCG.add`），`override=True` 时自动快照 + 审计留痕。
  ② `MdCG.add`：既有节点**跨层覆写**（`prev_entry.layer != layer`）= 搬迁语义，
     与 `_move_layer` 同口径补上**源层** `protect.require_layer` + `guard_move`
     （目标层闸由 `MdCGSecure.add` 的形参层闸承担，且此形参层即真目标层）。
  ③ `scrub._apply_offset` 写盘前过 `protect.guard_overwrite`（层/敏感度取节点
     fm 真值），`actor` 由 `calibrate` 透传。

守卫（六组，全部临时库 + 哑主密钥 + 临时令牌库，**绝不触真实 ~/.mdcg**）：
  ⓿ 隔离自证：aux 根 / 令牌库都须落在守卫临时目录，否则中止；
  ① N214：reflect 越层 MERGE 被层闸拒 + 盘面零改写 + 零留痕；designer 对 self
     层节点被**保护闸**拒（层闸对其放行，故该腿单独钉住 guard_write）；
     `override=True` 正路落快照+审计；反向腿（同层 contextual MERGE 仍成功）；
     工具面 `op=maintain action=prefeed write=true` 同样被拒；
  ② N215：预占位签名 + 换正文重发 → 越层聚合被拒 + anchor 正文逐字未变；
     designer 直调 `converge_into` 被保护闸拒、`override=True` 落快照+审计；
     反向腿（同层 contextual 聚合仍成功）；
  ③ N221：reflect 跨层覆写 knowledge/goals 节点被拒（库面 + `mdcg_remember`
     工具面）+ 旧层文件与索引零改写；反向腿（新建节点 / 同层覆写 /
     designer 同层覆写仍成功）；
  ④ N222：sustain 工具面 `op=scrub action=calibrate apply=true`（含
     `override=true` 腿）被层闸拒 + 置信度零改写；反向腿 designer 校准仍生效；
  ⑤ 源断言 + floor：四处写点前都出现 `guard_overwrite`/跨层闸，实弹断言计数下限。

运行：python -X utf8 -m md_cg.test_n214_n215_n221_n222_write_face_gates
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
_TMP = tempfile.mkdtemp(prefix="n214_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "cd" * 32          # 哑主密钥（绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES",
           "PYTHONIOENCODING", "PYTHONUTF8"):
    os.environ.pop(_k, None)

from . import forgetting, mcp_server, protect, scrub, tokens, writelimit  # noqa: E402
from .datapath import aux_root                                # noqa: E402
from .mdcos import MdCGSecure                                 # noqa: E402
from .security import Principal                               # noqa: E402

atexit.register(lambda: _cleanup(_TMP))       # LIFO：晚于库层 _atexit_flush_all

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.join(_TMP, "cgroot")
PASS = FAIL = LIVE = 0
LIVE_FLOOR = 18
FAILS = []

SELF_ID, ANCHOR_ID = "self214", "anchor215"
KN221_ID, CTX_ID = "kn221", "ctx214"
KN222P = "kn222p"
EVID = ["kn222_%d" % i for i in range(5)]
SELF_BODY = "# 自我认知卡（甲）：我是灵枢，服务于设计者。\n"
ANCHOR_BODY = "# 身份锚点（丙）：灵枢的锚点声明。\n"
KN221_BODY = "# 知识条目（丁）：离线优先的网络探测策略。\n"
CTX_BODY = "# 情境记录（乙）：今日试用新的检索路径。\n"
# N215 攻击腿：同模板签名、正文不同（模板骨架去数字后一致）
T1 = "# 功能名：批次流水核对报告\n本批次已收官并归档。\n"
T2 = "# 功能名：批次流水核对报告\n本批次已复核并放行。\n"
# 反向腿用**另一条**模板签名（避免与攻击腿共用 sig→target 映射）
R1 = "# 功能名：情境记录归档复核\n本日情境已归档。\n"
R2 = "# 功能名：情境记录归档复核\n本日情境已复核。\n"


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


def _princ(role, clearance="internal", can_admin=False):
    spec = tokens.role_spec(role)
    return Principal(tenant="default", actor="n214-" + role,
                     clearance=clearance, can_write=bool(spec["can_write"]),
                     can_admin=can_admin, role=role,
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


def _fresh():
    """盘面真值读取器：同 root 新建实例（自带全量重扫，不依赖他实例内存索引）。"""
    return _secured(_princ("designer", clearance="secret", can_admin=True))


def _disk(nid):
    """(frontmatter, content, index 条目) —— 从盘面重扫所得（非调用方内存索引）。"""
    cg = _fresh()
    node = cg.get(nid) or {}
    entry = (cg.index.get("nodes") or {}).get(nid) or {}
    return (node.get("frontmatter") or {}, node.get("content") or "", entry)


def _audit_rows():
    p = os.path.join(ROOT, protect.AUDIT_FILE)
    if not os.path.exists(p):
        return []
    out = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        return []
    return out


def _src_window(src, start, end):
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i)
    return src[i:] if j < 0 else src[i:j]


def main():
    global LIVE
    # ---------- ⓿ 隔离自证 ----------
    print("[0] 隔离自证")
    _tok = tokens.token_file()
    check("0a 默认令牌库与 aux 根都落在守卫临时目录（绝不触真实凭据）",
          os.path.abspath(_tok).lower().startswith(os.path.abspath(_TMP).lower())
          and os.path.abspath(aux_root()).lower().startswith(
              os.path.abspath(_TMP).lower()),
          "tok=%s aux=%s" % (_tok, aux_root()))
    if not os.path.abspath(ROOT).lower().startswith(os.path.abspath(_TMP).lower()):
        print("FATAL: 隔离失败，中止（绝不带病跑真实库）")
        return 2

    # ---------- 夹具 ----------
    designer = _secured(_princ("designer", clearance="secret", can_admin=True))
    designer.add(SELF_ID, SELF_BODY, layer="self", importance=0.9)
    designer.add(ANCHOR_ID, ANCHOR_BODY, layer="anchor", importance=0.9)
    designer.add(KN221_ID, KN221_BODY, layer="knowledge", importance=0.4)
    designer.add(CTX_ID, CTX_BODY, layer="contextual", importance=0.4)
    goal_id = designer.add_goal("把检索延迟降到 100ms 以内")
    for i, nid in enumerate(EVID):
        designer.add(nid, "# 知识条目（己%d）：校准样本。\n" % i,
                     layer="knowledge", confidence=0.8,
                     evidence_count=1, positive_evidence=1)
    designer.add(KN222P, "# 知识条目（庚）：高重要度校准样本。\n",
                 layer="knowledge", importance=0.9, confidence=0.8,
                 evidence_count=1, positive_evidence=1)
    # 校准面（N222）读的是**索引**中的 evidence_count（add 的 _stage 不带该键）
    # ——按盘面重扫一次，与攻击材料的起手式一致。
    designer.rebuild_index()
    designer.flush()
    P_KN221 = (designer.index["nodes"].get(KN221_ID) or {}).get("path")
    check("0b 夹具就位（self / anchor / knowledge / contextual / goals 五层各一，"
          "校准样本 5+1 个；索引层位可查）",
          (designer.index["nodes"].get(SELF_ID) or {}).get("layer") == "self"
          and (designer.index["nodes"].get(ANCHOR_ID) or {}).get("layer") == "anchor"
          and (designer.index["nodes"].get(KN221_ID) or {}).get("layer") == "knowledge"
          and bool(goal_id)
          and (designer.index["nodes"].get(goal_id) or {}).get("layer") == "goals"
          and all((designer.index["nodes"].get(n) or {}).get("evidence_count") == 1
                  for n in EVID + [KN222P]),
          "kn221_path=%s goal=%s" % (P_KN221, goal_id))

    # ---------- ① N214 MERGE→forgetting.reinforce ----------
    print("[1] N214 forgetting.reinforce：越层 MERGE / 保护闸 / 快照审计 / 反向腿")
    rec = _secured(_princ("reflect"))
    ok, exc, out = _raises(rec.remember_gated, "n214a", SELF_BODY,
                           layer="self", role="user")
    check("1a reflect（layers=('contextual',)）对 self 层既有节点 MERGE 被拒"
          "（修前 = 覆写 importance/merge_count 并自动打保护位）",
          (not ok) and exc == "AccessDenied",
          "exc=%s out=%s" % (exc, str(out)[:120]), live=True)
    fm_self, cont_self, _e = _disk(SELF_ID)
    check("1b 被拒后盘面零改写（importance 仍 0.9、无 merge_count、正文未变）",
          float(fm_self.get("importance") or 0) == 0.9
          and not fm_self.get("merge_count") and cont_self == SELF_BODY,
          "imp=%s mc=%s" % (fm_self.get("importance"), fm_self.get("merge_count")),
          live=True)
    check("1c 被拒路径零留痕（无 _protected_history/self214 快照、审计无该条）",
          protect.history(rec, SELF_ID) == []
          and not [r for r in _audit_rows() if r.get("node_id") == SELF_ID],
          "history=%s audit=%d" % (protect.history(rec, SELF_ID),
                                   len(_audit_rows())))
    ok_d, exc_d, out_d = _raises(forgetting.reinforce, _fresh(), SELF_ID)
    check("1d 接线自证：designer（层闸放行）直调 reinforce 覆写 self 层节点仍被"
          "**保护闸**拒（修前 = 无痕覆写成功；该腿单独钉住 guard_write）",
          (not ok_d) and exc_d in ("ProtectionError", "PermissionError"),
          "exc=%s out=%s" % (exc_d, str(out_d)[:120]), live=True)
    ok_o, exc_o, out_o = _raises(forgetting.reinforce, _fresh(), SELF_ID,
                                 override=True, actor="designer")
    check("1e override=True 正路：落 _protected_history 快照 + _protected_audit.jsonl"
          "（保护不等于黑箱；修前该路径无任何留痕）",
          ok_o and out_o and out_o.get("merge_count") == 1
          and len(protect.history(_fresh(), SELF_ID)) == 1
          and [r for r in _audit_rows()
               if r.get("node_id") == SELF_ID and r.get("action") == "override_write"],
          "ok=%s exc=%s out=%s hist=%s" % (ok_o, exc_o, str(out_o)[:80],
                                           protect.history(_fresh(), SELF_ID)),
          live=True)
    rec2 = _secured(_princ("reflect"))
    ok_r, exc_r, out_r = _raises(rec2.remember_gated, "ctxrev0", CTX_BODY,
                                 layer="contextual", role="user")
    check("1f 反向腿：reflect 对**自己层**既有节点 MERGE 仍成功（未一刀切收紧）",
          ok_r and out_r.get("verdict") == "MERGE"
          and out_r.get("merged_into") == CTX_ID,
          "exc=%s out=%s" % (exc_r, str(out_r)[:120]), live=True)
    rec3 = _secured(_princ("reflect"))
    _mc_before = _disk(SELF_ID)[0].get("merge_count")
    ok_t, exc_t, out_t = _raises(mcp_server.call_tool, rec3, "cg",
                                 {"op": "maintain", "action": "prefeed",
                                  "write": True, "content": SELF_BODY,
                                  "layer": "self", "role": "user",
                                  "node_id": "n214b"})
    fm_self2, _c2, _e2 = _disk(SELF_ID)
    check("1g 第二入口（工具面 op=maintain action=prefeed write=true）同拒"
          "（mcp_server 只在无写权时才 require_admin）",
          (not ok_t) and exc_t in ("AccessDenied", "ProtectionError")
          and fm_self2.get("merge_count") == _mc_before,
          "exc=%s out=%s mc=%s→%s" % (exc_t, str(out_t)[:120], _mc_before,
                                      fm_self2.get("merge_count")), live=True)

    # ---------- ② N215 CONVERGE→writelimit.converge_into ----------
    print("[2] N215 writelimit.converge_into：越层聚合 / 保护闸 / 快照审计 / 反向腿")
    rec4 = _secured(_princ("reflect"))
    ok_p, exc_p, out_p = _raises(rec4.remember_gated, ANCHOR_ID, T1,
                                 layer="contextual", role="user")
    sig_state = {}
    try:
        with open(os.path.join(ROOT, writelimit.STATE_FILE), encoding="utf-8") as fh:
            sig_state = json.load(fh).get("sigs") or {}
    except OSError:
        sig_state = {}
    check("2a 攻击前置成立：首次调用虽被保护闸拒，签名已预占位为 anchor id"
          "（修前修后同态，是攻击链的起点）",
          (not ok_p) and exc_p in ("ProtectionError", "AccessDenied")
          and any(v.get("nid") == ANCHOR_ID for v in sig_state.values()),
          "exc=%s sigs=%s" % (exc_p, json.dumps(sig_state, ensure_ascii=False)[:120]))
    rec5 = _secured(_princ("reflect"))
    ok_c, exc_c, out_c = _raises(rec5.remember_gated, "n215b", T2,
                                 layer="contextual", role="user")
    check("2b 换正文重发 → 越层同构聚合被拒（修前 = CONVERGE/target=anchor 并追加"
          "聚合行）",
          (not ok_c) and exc_c == "AccessDenied",
          "exc=%s out=%s" % (exc_c, str(out_c)[:160]), live=True)
    _fm_a, cont_a, _ea = _disk(ANCHOR_ID)
    check("2c anchor 层节点正文逐字未变（无【聚合】行、无 merge_count）",
          cont_a == ANCHOR_BODY and "【聚合" not in cont_a
          and not _fm_a.get("merge_count"),
          "content=%r mc=%s" % (cont_a[:80], _fm_a.get("merge_count")), live=True)
    ok_g, exc_g, out_g = _raises(writelimit.converge_into, _fresh(), ANCHOR_ID,
                                 "# 探针正文（凑）\n")
    check("2d 接线自证：designer 直调 converge_into 追加 anchor 层节点仍被保护闸拒"
          "（修前 = 追加成功）",
          (not ok_g) and exc_g in ("ProtectionError", "PermissionError"),
          "exc=%s out=%s" % (exc_g, str(out_g)[:120]), live=True)
    ok_go, exc_go, out_go = _raises(writelimit.converge_into, _fresh(), ANCHOR_ID,
                                    "# 探针正文（凑）\n", override=True,
                                    actor="designer")
    check("2e override=True 正路：落快照 + 审计后才追加（修前无任何留痕）",
          ok_go and out_go and out_go.get("ok") is True
          and len(protect.history(_fresh(), ANCHOR_ID)) == 1
          and [r for r in _audit_rows()
               if r.get("node_id") == ANCHOR_ID and r.get("action") == "override_write"],
          "ok=%s exc=%s out=%s hist=%s" % (ok_go, exc_go, str(out_go)[:80],
                                           protect.history(_fresh(), ANCHOR_ID)),
          live=True)
    rec6 = _secured(_princ("reflect"))
    ok_1, exc_1, out_1 = _raises(rec6.remember_gated, "ctxrev1", R1,
                                 layer="contextual", role="user")
    rec7 = _secured(_princ("reflect"))
    ok_2, exc_2, out_2 = _raises(rec7.remember_gated, "ctxrev2", R2,
                                 layer="contextual", role="user")
    _fm_cr, cont_cr, _ecr = _disk("ctxrev1")
    check("2f 反向腿：reflect 对**自己层**上下文节点同构聚合仍成功（聚合行落盘）",
          ok_1 and ok_2 and out_2.get("gate", {}).get("verdict") == "CONVERGE"
          and out_2.get("merged_into") == "ctxrev1"
          and "【聚合" in cont_cr,
          "ok1=%s ok2=%s out2=%s" % (ok_1, ok_2, str(out_2)[:140]), live=True)

    # ---------- ③ N221 add 跨层覆写（搬迁语义） ----------
    print("[3] N221 add 跨层覆写：源层闸 + 搬迁闸 / 工具面 / 反向腿")
    rec8 = _secured(_princ("reflect"))
    ok_k, exc_k, out_k = _raises(rec8.add, KN221_ID, "# 我改写的内容（丁·攻击）\n",
                                 layer="contextual")
    check("3a reflect 以自己可写层覆写 knowledge 层既有节点被拒（修前 = {'ok':真}，"
          "旧层文件被删、节点被顶替到 contextual）",
          (not ok_k) and exc_k == "AccessDenied",
          "exc=%s out=%s" % (exc_k, str(out_k)[:120]), live=True)
    _fm_k, cont_k, entry_k = _disk(KN221_ID)
    check("3b 盘面零搬迁：旧层文件仍在、正文未变、索引仍指旧路径、无新层文件",
          os.path.exists(os.path.join(ROOT, P_KN221))
          and cont_k == KN221_BODY
          and entry_k.get("path") == P_KN221
          and entry_k.get("layer") == "knowledge"
          and not os.path.exists(os.path.join(ROOT, "contextual",
                                              KN221_ID + ".md")),
          "path=%s/%s cont=%r" % (entry_k.get("path"), P_KN221, cont_k[:40]),
          live=True)
    rec9 = _secured(_princ("reflect"))
    ok_k2, exc_k2, out_k2 = _raises(mcp_server.call_tool, rec9, "mdcg_remember",
                                    {"node_id": KN221_ID,
                                     "content": "# 工具面改写（丁）\n",
                                     "layer": "contextual", "gated": False})
    check("3c 工具面（mdcg_remember gated=false）同拒且盘面零改写",
          (not ok_k2) and exc_k2 == "AccessDenied"
          and _disk(KN221_ID)[1] == KN221_BODY,
          "exc=%s out=%s" % (exc_k2, str(out_k2)[:120]), live=True)
    rec10 = _secured(_princ("reflect"))
    ok_g2, exc_g2, out_g2 = _raises(rec10.add, goal_id, "# 目标被顶替（戊）\n",
                                    layer="contextual")
    _fm_go, cont_go, entry_go = _disk(goal_id)
    check("3d 同形 goals 腿同拒（目标节点未被顶替出层）",
          (not ok_g2) and exc_g2 == "AccessDenied"
          and entry_go.get("layer") == "goals",
          "exc=%s layer=%s" % (exc_g2, entry_go.get("layer")), live=True)
    rec11 = _secured(_princ("reflect"))
    ok_n, exc_n, out_n = _raises(rec11.add, "ctxnew1", "# 全新情境记录（庚）\n",
                                 layer="contextual")
    check("3e 反向腿：reflect 新建节点（无既有条目，非搬迁）仍成功",
          ok_n and out_n == "ctxnew1" and _disk("ctxnew1")[2].get("layer")
          == "contextual",
          "exc=%s out=%s" % (exc_n, out_n), live=True)
    rec12 = _secured(_princ("reflect"))
    ok_s, exc_s, out_s = _raises(rec12.add, "ctxnew1", "# 情境记录更新（庚·同层）\n",
                                 layer="contextual")
    check("3f 反向腿：reflect **同层**覆写自己的节点仍成功（层闸只拦跨层搬迁）",
          ok_s and out_s == "ctxnew1"
          and "同层" in _disk("ctxnew1")[1],
          "exc=%s out=%s" % (exc_s, out_s), live=True)
    _fresh().add(KN221_ID, KN221_BODY + "# 追加一行（丁·同层覆写）\n",
                 layer="knowledge", importance=0.4)
    check("3g 反向腿：designer 对 knowledge 层**同层**覆写仍成功",
          "追加一行" in _disk(KN221_ID)[1],
          "content=%r" % _disk(KN221_ID)[1][:60], live=True)

    # ---------- ④ N222 scrub.calibrate apply ----------
    print("[4] N222 scrub._apply_offset：层闸（含 override 直通腿）/ 反向腿")
    sus = _secured(_princ("sustain"))
    sus.rebuild_index()
    ok_cal, exc_cal, out_cal = _raises(
        mcp_server.call_tool, sus, "cg",
        {"op": "scrub", "action": "calibrate", "apply": True})
    check("4a sustain（layers=('self',)）工具面 calibrate apply=true 被层闸拒"
          "（修前 = n_adjusted=5，knowledge 层 confidence 0.8→0.95）",
          (not ok_cal) and exc_cal == "AccessDenied",
          "exc=%s out=%s" % (exc_cal, str(out_cal)[:160]), live=True)
    conf_a = [_disk(n)[0].get("confidence") for n in EVID]
    check("4b 被拒后全库零校准改写（5 个 knowledge 样本 confidence 仍 0.8、"
          "无 calibration 字段）",
          all(float(c or 0) == 0.8 for c in conf_a)
          and not _disk(EVID[0])[0].get("calibration"),
          "conf=%s" % conf_a, live=True)
    sus2 = _secured(_princ("sustain"))
    sus2.rebuild_index()
    ok_cal2, exc_cal2, out_cal2 = _raises(
        mcp_server.call_tool, sus2, "cg",
        {"op": "scrub", "action": "calibrate", "apply": True, "override": True})
    fm_p, _cp, _ep = _disk(KN222P)
    check("4c override=true 腿同样被层闸拒（override 不直通层白名单；"
          "importance≥0.7 的不可遗忘节点未被改写）",
          (not ok_cal2) and exc_cal2 == "AccessDenied"
          and float(fm_p.get("confidence") or 0) == 0.8,
          "exc=%s out=%s conf=%s" % (exc_cal2, str(out_cal2)[:120],
                                     fm_p.get("confidence")), live=True)
    dcg = _fresh()
    dcg.rebuild_index()          # 校准面读索引 evidence_count（与攻击腿同起手式）
    dcal, exc_dcal, out_dcal = _raises(
        mcp_server.call_tool, dcg, "cg",
        {"op": "scrub", "action": "calibrate", "apply": True})
    check("4d 反向腿：designer 同 op 校准仍生效（层闸只拦无层写权的身份）",
          dcal and out_dcal.get("ok") and int(out_dcal.get("n_adjusted") or 0) >= 1
          and float(_disk(EVID[0])[0].get("confidence") or 0) > 0.8,
          "ok=%s exc=%s out=%s" % (dcal, exc_dcal,
                                   json.dumps({k: out_dcal.get(k) for k in
                                               ("n_adjusted", "skipped_protected")}
                                              if isinstance(out_dcal, dict) else {},
                                              ensure_ascii=False)), live=True)

    # ---------- ⑤ 源断言 + floor ----------
    print("[5] 源断言 + 守卫自检")
    _dir = os.path.dirname(os.path.abspath(__file__))

    def _src(name):
        with open(os.path.join(_dir, name), encoding="utf-8",
                  errors="replace") as fh:
            return fh.read().replace("\r\n", "\n")

    src_f, src_w, src_s, src_m = (_src("forgetting.py"), _src("writelimit.py"),
                                  _src("scrub.py"), _src("mdcg.py"))
    win_f = _src_window(src_f, "def reinforce(", "\n\n# ")
    check("5a forgetting.reinforce 写盘前紧邻 guard_overwrite（层/敏感度取节点 "
          "fm 真值），且在 cg._write_node 之前",
          "protect.guard_overwrite(cg, node_id, layer=fm.get(\"layer\"),\n"
          "                            sensitivity=fm.get(\"sensitivity\"),\n"
          "                            override=override, actor=actor)"
          in src_f
          and 0 < win_f.find("guard_overwrite")
          < win_f.find("cg._write_node(node_id"),
          "win_len=%d" % len(win_f))
    win_w = _src_window(src_w, "def converge_into(", "\n\n# ")
    check("5b writelimit.converge_into 写盘前紧邻 guard_overwrite 且在 "
          "cg._write_node 之前",
          "protect.guard_overwrite(cg, target, layer=fm.get(\"layer\"),\n"
          "                            sensitivity=fm.get(\"sensitivity\"),\n"
          "                            override=override, actor=actor)"
          in src_w
          and 0 < win_w.find("guard_overwrite")
          < win_w.find("cg._write_node(target,"),
          "win_len=%d" % len(win_w))
    win_s = _src_window(src_s, "def _apply_offset(", "def calibrate(")
    check("5c scrub._apply_offset 写盘前紧邻 guard_overwrite（actor 由 calibrate "
          "透传）且在 cg._write_node 之前",
          "protect.guard_overwrite(cg, nid, layer=fm.get(\"layer\"),\n"
          "                                sensitivity=fm.get(\"sensitivity\"),\n"
          "                                override=override, actor=actor)"
          in src_s
          and 0 < win_s.find("guard_overwrite")
          < win_s.find("cg._write_node(nid,")
          and "actor=actor" in _src_window(src_s, "def calibrate(",
                                           "\ndef sweep("),
          "win_len=%d" % len(win_s))
    win_m = _src_window(src_m, "prev_entry = (self.index.get(\"nodes\") or {})",
                        "os.remove(_old_real)")
    check("5d MdCG.add 既有节点跨层覆写 = 搬迁语义：源层 require_layer + "
          "guard_move（对齐 _move_layer 的源/目标双闸口径）",
          "prev_entry.get(\"layer\")" in win_m
          and "protect.require_layer(self, node_id, layer=_prev_layer,"
          in src_m
          and "protect.guard_move(self, node_id, layer, override=override,"
          in src_m
          and "require_layer" in win_m and "guard_move" in win_m,
          "win_len=%d" % len(win_m))
    check("5e 实弹断言数 ≥ %d（防 spawn/扫描面失效假绿）" % LIVE_FLOOR,
          LIVE >= LIVE_FLOOR, "LIVE=%d" % LIVE)

    print("\n=== N214/N215/N221/N222 write-face gates: %d passed, %d failed "
          "(live=%d) ===" % (PASS, FAIL, LIVE))
    if FAILS:
        print("失败项：%s" % "；".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    _code = 0
    try:
        _code = main()
    finally:
        _close_all()
        if not _cleanup(_TMP):
            print("WARN: 临时根残留未清（%s）——请人工清理" % _TMP)
    sys.exit(_code)
