# -*- coding: utf-8 -*-
"""md_cg · verify 写面全域层闸守卫（N209：同族未接线的相邻写面入口）

缺陷（修复前，本守卫红态实跑）：verify 角色的写面**只有 `falsified` 一态**有层闸
（N130/N196，`md_cg/mdcos.py:3934-3949` 里 `if verdict == "falsified":` 才加闸），
`confirmed` / `weakened` 分支全程零闸——`md_cg/mdcg.py:3502` 直写
`self._write_node(...)`、`:3492` 直调 `self._move_layer(node_id, "contextual", …)`，
上下无 `require_layer_write`、无 `guard_write`。连带三条腿：

  ① 持 verify 令牌（`md_cg/tokens.py:156-172`：`layers_allow=('rejected','contextual')`，
     forbidden 明列「knowledge/self/anchor 层（不得改被验证内容）」）对任意
     clearance 可读的 knowledge 节点发 `verdict=weakened/confirmed` → 重写其
     frontmatter（confidence/evidence_count/positive|negative_evidence/evidence_log）；
  ② `trust.mark_dependents` → `trust.set_state`（`md_cg/trust.py:697-698` 直写
     `cg._write_node(...)`）→ 把**任意层**依赖者（实证含 self 层）置 doubted：
     `MdCGSecure` 对 `set_state`/`set_verification`/`mark_dependents` 无任何覆盖，
     state/verification 写路径全程无层闸；
  ③ 连续 weakened 把 knowledge 层节点降级迁出到 contextual（`_move_layer` 只过
     保护闸 `guard_move`，无层闸——而搬迁 = 源层一次删除写 + 目标层一次新增写）。
  无需 admin、无需 override（对照同一节点走 `falsified` 已被 AccessDenied 拦）。

修复（最小改动 · 三个单点，全部 fail-closed）：
  ① 新增 `protect.require_layer(cg, node_id, layer=…, sensitivity=…)`：「既有节点
     写面的 principal 层闸」单点（解析顺序：实参层/敏感度 → 索引条目 → 节点
     frontmatter → 缺省口径同 `require_layer_write`；进入前索引代际探活 N195）；
     `guard_overwrite` 复用同一解析（第二份口径 = 下一个漏点）。
  ② `MdCGSecure.verify` 的闸从「仅 falsified」放宽到**三态全覆盖**——verify 写面
     与 `add`/`add_rejected`（`:3889`/`:3898`）同闸；「真不存在」语义照旧由基类
     not_found 承接（索引无条目时不加闸、也不写盘）。
  ③ `trust.set_state`（验证态**唯一推进入口**，同时覆盖 `mark_dependents` 与
     `set_verification` 两条写路）与 `MdCG._move_layer`（降级搬迁入口，同时覆盖
     `scrub.decontaminate` 与 `evolution` 回滚两个调用者）各自补层闸。
     `set_state` 走**负路由**（`ok=False, error="layer_denied"`）而非抛：该函数契约
     是「非法迁移不抛异常」、`mark_dependents` 契约是「永不抛、不阻断本次裁决」——
     但**绝不写盘**，并把拒绝记进 `_trust.jsonl`（不静默）。

守卫（五组，全临时库 + 哑主密钥 + 临时令牌库，**绝不触真实 ~/.mdcg**）：
  ⓿ 隔离自证：aux 根 / 令牌库都须落在守卫临时目录，否则中止；
  ① verify 三态的层闸：verify 令牌对 knowledge 节点 weakened/confirmed 被拒且
     盘面零改写（含依赖者未被连带改写）；对照 falsified 早已被拒；反向腿为
     verify 令牌对 contextual 节点 confirmed 仍成立（防一刀切收紧）；
  ② 连续 weakened 的降级迁出：verify 令牌连发 4 次全拒、盘面仍在 knowledge/；
     反向腿 designer 同链路降级迁出仍生效（fail-closed ≠ 掐死合法路径）；
  ③ 依赖者写面单点（`trust.set_state`）：verify 令牌直调被负路由拒绝且盘面零
     改写；端到端 falsified（合法）→ mark_dependents 一跳传播对 self 层依赖者
     不再落盘（拒绝入 `skipped`）；反向腿 sustain 对 self 层节点推进仍成功；
  ④ 搬迁写面单点（`_move_layer`）：sustain 令牌越层搬迁被拒且文件未移动；
     反向腿 designer 搬迁仍生效；同族邻接出口 `scrub._weaken` 被同一单点拒；
     邻接 op 面 `op=scrub action=decontaminate`（expired/high 实靶）零改写且失败
     动作在审计里显式可见（修前该 op 实测 conf 0.5→0.35 且迁出 contextual）；
  ⑤ 源断言 + floor：三处单点的代码形态（闸必须在写点之前）与实弹计数下限。

留档（本席未改，属邻接面的既有口径）：`scrub.decontaminate` 对每个 issue 的
try/except（`md_cg/scrub.py:683-696`）把 `_move_layer` 的 AccessDenied 记成
`demote_failed:AccessDenied`、`_weaken` 的记成 `weaken_failed:AccessDenied`
（留痕正确），但该 issue 仍计入 `n_applied` 并返回 `applied: True` ——「阻挡成功、
计数仍算已处置」是 scrub 自己的聚合口径，不在本席（写面层闸）范围。

实测（本机）：修前 8 passed / 15 failed（红腿 = 1a/1b/1c/1e/2a/2b/3a/3b/4a/4c/4d
十一条端到端腿 + 5a-5d 四条源断言腿；复跑法：把 md_cg 包整份复制到临时目录，再用
`git show HEAD:md_cg/{mdcg,protect,trust,mdcos}.py` 覆盖回修复前版本后实跑）；
修后 23 passed / 0 failed（live=16）。

运行：python -X utf8 -m md_cg.test_n209_verify_write_face_gates
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import time

# ── 隔离前置：必须在 import md_cg 子模块**之前**（tokens/theory 等在模块级把
# aux_root() 冻成常量）——否则会指到真实 ~/.mdcg 并在那里建密钥/令牌库。 ──
_TMP = tempfile.mkdtemp(prefix="n209v_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "ef" * 32          # 哑主密钥（绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES",
           "PYTHONIOENCODING", "PYTHONUTF8"):
    os.environ.pop(_k, None)

from . import mcp_server, protect, scrub, tokens, trust          # noqa: E402
from .datapath import aux_root                              # noqa: E402
from .mdcos import MdCGSecure                               # noqa: E402
from .security import Principal                             # noqa: E402

atexit.register(lambda: _cleanup(_TMP))       # LIFO：晚于库层 _atexit_flush_all

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.join(_TMP, "cgroot")
PASS = FAIL = LIVE = 0
LIVE_FLOOR = 16
FAILS = []


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
    return Principal(tenant="default", actor="n209-" + role,
                     clearance=clearance, can_write=bool(spec["can_write"]),
                     can_admin=can_admin, role=role,
                     layers_allow=spec["layers_allow"],
                     ops_allow=spec["ops_allow"], auth_mode="test")


_OPEN = []


def _secured(principal):
    cg = MdCGSecure(ROOT, principal=principal)
    _OPEN.append(cg)
    return cg


def _cleanup(path) -> bool:
    import gc
    for cg in _OPEN:
        try:
            cg.close()
        except Exception:                      # noqa: BLE001 —— 清理面不得再抛
            pass
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        gc.collect()
        time.sleep(0.25)
    return not os.path.exists(path)


def _fm_of(cg, nid):
    node = cg.get(nid)
    return (node or {}).get("frontmatter") or {}, (node or {}).get("content") or ""


VERIFY_FIELDS = ("confidence", "evidence_count", "positive_evidence",
                 "negative_evidence", "evidence_log", "verification_state",
                 "layer", "path")


def _vstate(cg, nid):
    """frontmatter 关键位 + 正文 —— 用于「盘面零改写」断言。"""
    fm, content = _fm_of(cg, nid)
    return {k: fm.get(k) for k in VERIFY_FIELDS}, content


def _disk_layers(nid):
    """盘上真实所在层（不依赖索引快照：搬迁断言必须看文件系统）。"""
    out = []
    for r, _d, files in os.walk(ROOT):
        if nid + ".md" in files:
            seg = os.path.relpath(r, ROOT).replace("\\", "/").split("/")[0]
            if seg not in out:
                out.append(seg)
    out.sort()
    return out


def _raises(fn, *a, **kw):
    """执行并返回 (ok, 异常类名/空, 结果/异常文本)。"""
    try:
        return True, "", fn(*a, **kw)
    except Exception as exc:                   # noqa: BLE001 —— 守卫要的是拒绝形态
        return False, type(exc).__name__, str(exc)


def _src_of(fname):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), fname),
              encoding="utf-8", errors="replace") as fh:
        return fh.read().replace("\r\n", "\n")


def _src_window(src, start, end):
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i)
    return src[i:] if j < 0 else src[i:j]


def main():
    global LIVE
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

    designer = _secured(_princ("designer", clearance="internal", can_admin=True))
    k_rule = designer.add("k_rule", "# 正文：知识规则 A\n", layer="knowledge",
                          confidence=0.6)
    k_low = designer.add("k_low", "# 正文：知识规则 B\n", layer="knowledge",
                         confidence=0.4)
    k_low2 = designer.add("k_low2", "# 正文：知识规则 C\n", layer="knowledge",
                          confidence=0.1)
    k_move = designer.add("k_move", "# 正文：待搬迁知识节点\n", layer="knowledge")
    k_move2 = designer.add("k_move2", "# 正文：待搬迁知识节点 2\n", layer="knowledge")
    k_scrub = designer.add("k_scrub", "# 正文：scrub 邻接出口探针\n",
                           layer="knowledge", confidence=0.6)
    k_exp = designer.add("k_exp", "# 正文：时效已过的知识节点\n",
                         layer="knowledge", confidence=0.5,
                         valid_until=time.time() - 86400 * 30)
    c_hyp = designer.add("c_hyp", "# 正文：情境假设 D\n", layer="contextual",
                         confidence=0.6)
    c_bad = designer.add("c_bad", "# 正文：情境假设 C\n", layer="contextual")
    s_prop = designer.add("s_prop", "# 正文：自我层依赖者（prop）\n", layer="self",
                          depends_on=["k_rule"])
    s_set = designer.add("s_set", "# 正文：自我层节点（set_state 直调）\n",
                         layer="self")
    s_dep = designer.add("s_dep", "# 正文：自我层依赖者（falsified 一跳）\n",
                         layer="self", depends_on=["c_bad"])
    s_ok = designer.add("s_ok", "# 正文：自我层节点（反向腿）\n", layer="self")
    _idx = designer.index["nodes"]
    check("0b 夹具就位（层 + depends_on 落入索引快照）",
          all(_idx.get(n) for n in (k_rule, k_low, k_low2, k_move, k_move2,
                                    c_hyp, c_bad, s_prop, s_set, s_dep, s_ok))
          and (_idx[s_prop].get("depends_on") == ["k_rule"])
          and (_idx[s_dep].get("depends_on") == ["c_bad"])
          and _idx[s_prop].get("layer") == "self",
          "deps=%s/%s" % (_idx.get(s_prop, {}).get("depends_on"),
                          _idx.get(s_dep, {}).get("depends_on")))

    # ---------- ① verify 三态的层闸（缺陷腿 ① + 对照 falsified） ----------
    print("[1] verify 三态全覆盖：越层裁决被拒（含依赖者连带写面）")
    v = _secured(_princ("verify"))
    before_k, before_kc = _vstate(v, k_rule)
    before_s, before_sc = _vstate(v, s_prop)
    ok1, exc1, out1 = _raises(mcp_server.call_tool, v, "cg",
                              {"op": "verify", "node_id": k_rule,
                               "evidence": "越层探针证据", "verdict": "weakened"})
    after_k, after_kc = _vstate(v, k_rule)
    after_s, after_sc = _vstate(v, s_prop)
    check("1a verify 令牌对 knowledge 节点 weakened 被拒（修前 = 改 knowledge 层 "
          "frontmatter 成功且无痕）",
          (not ok1) and exc1 == "AccessDenied",
          "exc=%s out=%s" % (exc1, str(out1)[:80]), live=True)
    check("1b 盘面零改写：confidence/evidence_count/negative_evidence/evidence_log "
          "与正文全等、层与路径不变",
          after_k == before_k and after_kc == before_kc,
          "before=%s after=%s" % (before_k, after_k), live=True)
    check("1c 依赖者（self 层）未被连带改写：verification_state 仍非 doubted",
          after_s == before_s and after_sc == before_sc
          and after_s.get("verification_state") != "doubted",
          "before=%s after=%s" % (before_s, after_s), live=True)
    ok2, exc2, out2 = _raises(mcp_server.call_tool, v, "cg",
                              {"op": "verify", "node_id": k_rule,
                               "evidence": "对照腿", "verdict": "falsified"})
    check("1d 对照腿（材料口径）：同一 verify 令牌对同一节点走 falsified 早已被拒",
          (not ok2) and exc2 == "AccessDenied"
          and _disk_layers(k_rule) == ["knowledge"],
          "exc=%s layers=%s" % (exc2, _disk_layers(k_rule)), live=True)
    ok3, exc3, out3 = _raises(mcp_server.call_tool, v, "cg",
                              {"op": "verify", "node_id": k_rule,
                               "evidence": "confirmed 探针", "verdict": "confirmed"})
    after_k3, _c3 = _vstate(v, k_rule)
    check("1e confirmed 同臂同样被拒且盘面零改写（三态全覆盖，非只补 weakened）",
          (not ok3) and exc3 == "AccessDenied" and after_k3 == before_k,
          "exc=%s out=%s" % (exc3, str(out3)[:80]), live=True)
    c_h_before, c_h_bc = _vstate(v, c_hyp)
    ok4, exc4, out4 = _raises(mcp_server.call_tool, v, "cg",
                              {"op": "verify", "node_id": c_hyp,
                               "evidence": "同层正当裁决", "verdict": "confirmed"})
    c_h_after, c_h_ac = _vstate(v, c_hyp)
    check("1f 反向腿：verify 令牌对 contextual 节点 confirmed 仍成立（同层正当写入 "
          "未被一刀切掐死）",
          ok4 and isinstance(out4, dict) and out4.get("action") == "confirmed"
          and c_h_after["evidence_count"] == (c_h_before["evidence_count"] or 0) + 1
          and c_h_after["confidence"] == 0.65,
          "exc=%s out=%s" % (exc4, str(out4)[:80]), live=True)

    # ---------- ② 连续 weakened 的降级迁出 ----------
    print("[2] 连续 weakened 降级迁出：越层搬迁被拒（缺陷腿 ③）")
    v2 = _secured(_princ("verify"))
    denied = 0
    for _i in range(4):
        _ok, _exc, _out = _raises(mcp_server.call_tool, v2, "cg",
                                  {"op": "verify", "node_id": k_low,
                                   "evidence": "连续 weakened 探针 #%d" % _i,
                                   "verdict": "weakened"})
        if (not _ok) and _exc == "AccessDenied":
            denied += 1
    check("2a verify 令牌连发 4 次 weakened 全被拒（修前 3 次即跌破 "
          "DEMOTE_CONFIDENCE 并迁出）",
          denied == 4, "denied=%d" % denied, live=True)
    check("2b 盘面仍在 knowledge 层且 layer=knowledge、confidence=0.4"
          "（迁出后盘上落在 contextual/）",
          _disk_layers(k_low) == ["knowledge"]
          and _vstate(v2, k_low)[0]["layer"] == "knowledge"
          and _vstate(v2, k_low)[0]["confidence"] == 0.4,
          "layers=%s layer=%s conf=%s" % (_disk_layers(k_low),
                                          _vstate(v2, k_low)[0].get("layer"),
                                          _vstate(v2, k_low)[0].get("confidence")),
          live=True)
    okd, excd, _outd = _raises(designer.verify, k_low2, "合法降级腿", "weakened")
    check("2c 反向腿：designer（layers='*'）同链路降级迁出仍生效（confidence "
          "0.1→0.0 < 0.2 → contextual）",
          okd and _disk_layers(k_low2) == ["contextual"],
          "exc=%s layers=%s" % (excd, _disk_layers(k_low2)), live=True)

    # ---------- ③ 依赖者写面单点：trust.set_state ----------
    print("[3] 依赖者/验证态写面单点（trust.set_state）")
    v3 = _secured(_princ("verify"))
    s_set_before = _vstate(v3, s_set)
    ok5, exc5, out5 = _raises(trust.set_state, v3, s_set, "doubted",
                              reason="N209 越层写面探针", actor="n209")
    s_set_after = _vstate(v3, s_set)
    check("3a verify 令牌直调 trust.set_state 对 self 层节点被**负路由**拒绝"
          "（修前 ok=True 且写盘）",
          ok5 and isinstance(out5, dict) and out5.get("ok") is False
          and out5.get("changed") is False
          and out5.get("error") == "layer_denied"
          and s_set_after == s_set_before
          and s_set_after[0].get("verification_state") != "doubted",
          "out=%s" % (str(out5)[:120]), live=True)
    v4 = _secured(_princ("verify"))
    s_dep_before = _vstate(v4, s_dep)
    ok6, exc6, out6 = _raises(mcp_server.call_tool, v4, "cg",
                              {"op": "verify", "node_id": c_bad,
                               "evidence": "情境假设被证伪", "verdict": "falsified"})
    s_dep_after = _vstate(v4, s_dep)
    prop = (out6 or {}).get("propagation") if isinstance(out6, dict) else None
    check("3b 端到端：falsified（contextual 层，合法）的一跳传播不再写 self 层依赖者"
          "——本裁决仍成功、传播记 skipped 而非落盘",
          ok6 and isinstance(out6, dict) and out6.get("action") == "falsified"
          and s_dep_after == s_dep_before
          and s_dep_after[0].get("verification_state") != "doubted"
          and isinstance(prop, dict) and prop.get("changed") == 0
          and any("layer_denied" in str(x) for x in (prop.get("skipped") or [])),
          "exc=%s prop=%s" % (exc6, str(prop)[:150]), live=True)
    sustain = _secured(_princ("sustain"))
    ok7, exc7, out7 = _raises(sustain.set_verification, s_ok, "doubted",
                              reason="sustain 自层运维", actor="n209-sustain")
    check("3c 反向腿：sustain（layers=('self',)）对 self 层节点推进仍成功"
          "（同层正当写面未被收紧误伤）",
          ok7 and isinstance(out7, dict) and out7.get("ok") is True
          and _vstate(sustain, s_ok)[0].get("verification_state") == "doubted",
          "exc=%s out=%s" % (exc7, str(out7)[:100]), live=True)

    # ---------- ④ 搬迁写面单点：_move_layer ----------
    print("[4] 降级搬迁写面单点（_move_layer，同族未接线入口）")
    ok8, exc8, out8 = _raises(sustain._move_layer, k_move, "contextual",
                              reason="N209 越层搬迁探针")
    check("4a sustain（layers=('self',)）把 knowledge 节点搬出层被拒（修前成功搬入 "
          "contextual）",
          (not ok8) and exc8 == "AccessDenied"
          and _disk_layers(k_move) == ["knowledge"],
          "exc=%s layers=%s" % (exc8, _disk_layers(k_move)), live=True)
    ok9, exc9, out9 = _raises(designer._move_layer, k_move2, "contextual",
                              reason="N209 反向腿合法搬迁")
    check("4b 反向腿：designer 同调用仍生效（文件已到 contextual/）",
          ok9 and isinstance(out9, dict) and out9.get("to") == "contextual"
          and _disk_layers(k_move2) == ["contextual"],
          "exc=%s layers=%s" % (exc9, _disk_layers(k_move2)), live=True)
    ok10, exc10, out10 = _raises(scrub._weaken, sustain, k_scrub, "stale",
                                 "N209 邻接出口探针")
    check("4c 同族邻接调用者：scrub._weaken 经 cg.verify 同一单点被拒且盘面零改写"
          "（scrub ∈ sustain ops_allow，修前可对 knowledge 节点 weaken）",
          (not ok10) and exc10 == "AccessDenied"
          and _vstate(sustain, k_scrub)[0]["confidence"] == 0.6,
          "exc=%s out=%s" % (exc10, str(out10)[:80]), live=True)
    sus2 = _secured(_princ("sustain"))
    ok11, exc11, out11 = _raises(mcp_server.call_tool, sus2, "cg",
                                 {"op": "scrub", "action": "decontaminate",
                                  "node_ids": [k_exp], "kinds": ["expired"],
                                  "min_severity": "info", "dry_run": False})
    fm11, _c11 = _vstate(sus2, k_exp)
    acts = (out11 or {}).get("actions") if isinstance(out11, dict) else None
    _done0 = (acts[0].get("done") if isinstance(acts, list) and acts
              and isinstance(acts[0], dict) else []) or []
    check("4d 同族邻接 op 面：sustain 经 op=scrub action=decontaminate 对 "
          "expired/high 实靶不再能 weaken/降级 knowledge 节点——零改写，且两条"
          "失败动作在审计里显式可见（不静默假装成功）",
          ok11 and isinstance(out11, dict) and fm11["confidence"] == 0.5
          and fm11["layer"] == "knowledge"
          and _disk_layers(k_exp) == ["knowledge"]
          and "weaken_failed:AccessDenied" in _done0
          and "demote_failed:AccessDenied" in _done0,
          "exc=%s conf=%s layer=%s done=%s"
          % (exc11, fm11.get("confidence"), fm11.get("layer"), _done0), live=True)

    # ---------- ⑤ 源断言 + floor ----------
    print("[5] 源断言 + 守卫自检")
    src_t = _src_of("trust.py")
    src_m = _src_of("mdcg.py")
    src_o = _src_of("mdcos.py")
    src_p = _src_of("protect.py")
    win_set = _src_window(src_t, "def set_state(cg, node_id: str, dst: str",
                          "# ---------------------------------------------------------")
    win_mv = _src_window(src_m, "    def _move_layer(self, node_id: str",
                         "# 生效条件：verdict 不在")
    win_v = _src_window(src_o, "    def verify(self, node_id: str, evidence: str",
                        "# 生效条件：sens 取 sensitivity or DEFAULT_SENSITIVITY")
    check("5a trust.set_state 写点前紧邻 protect.require_layer（负路由，写盘前）",
          "protect.require_layer(cg, node_id" in win_set
          and win_set.index("protect.require_layer(cg, node_id")
          < win_set.index("cg._write_node(")
          and '"error": "layer_denied"' in win_set,
          "win_len=%d" % len(win_set))
    check("5b MdCG._move_layer 对**源层与目标层**各过一道层闸，且都在 "
          "self._write_node( 之前",
          win_mv.count("protect.require_layer(") >= 2
          and win_mv.index("protect.require_layer(")
          < win_mv.index("self._write_node(")
          and "layer=to_layer" in win_mv and "layer=from_layer" in win_mv,
          "n=%d" % win_mv.count("protect.require_layer("))
    check("5c MdCGSecure.verify 的闸已从「仅 falsified」放宽到三态全覆盖",
          'v in ("confirmed", "weakened", "falsified")' in win_v
          and "protect.require_layer(" in win_v
          and '== "falsified"' not in win_v,
          "win_len=%d" % len(win_v))
    win_go = _src_window(src_p, "def guard_overwrite(cg, node_id",
                         "def mark(cg, node_id")
    check("5d protect.require_layer 单点存在，且 guard_overwrite 复用同一解析"
          "（第二份口径 = 下一个漏点）",
          "\ndef require_layer(cg, node_id, layer=None, sensitivity=None," in src_p
          and "require_layer(cg, node_id" in win_go
          and src_p.count("def _resolve_target(") == 1
          and src_p.count("def require_layer(") == 1,
          "n_resolve_def=%d" % src_p.count("def _resolve_target("))
    check("5e 实弹断言计数下限（防某条腿被静默跳过/提前 return）",
          LIVE >= LIVE_FLOOR,
          "LIVE=%d floor=%d" % (LIVE, LIVE_FLOOR))

    print("\n[RESULT] %d passed / %d failed · live=%d" % (PASS, FAIL, LIVE))
    if FAILS:
        print("失败清单：")
        for n in FAILS:
            print("  · %s" % n)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
