# -*- coding: utf-8 -*-
"""md_cg · 提案队列的密级/身份面（N201）

缺陷（修复前）：海马体提案走一条与节点正文**口径不一致**的落盘/读出面：

  · 写面（`md_cg/mdcos.py:1794-1803` `MdCGOS.propose`）：`rec["content"]` 以
    **明文**写进 `hippocampus/inbox.jsonl`，且 rec 顶层键**没有**
    `sensitivity`（密级只藏在 `extra` 内，`payload_hash` 按明文算）——同源节点
    正文「private 落盘即封套」（`MdCGSecure._seal_content`）在提案面整段缺失。
  · 读面（`md_cg/mdcos.py:1946-1963` `review_list`）：全函数体**零**
    `_readable`、零身份判定，原样返回全部待审提案的正文 + actor/session 归属。
  · 出口面（`md_cg/mcp_server.py:3067`）：细粒度工具 `mdcg_review_list` 映射到
    op `read`（`guest` 的 ops_allow 就含 read），而同库的规范出口
    `cg(op=review, action=list)` 要 `require_op("review")` ⇒ **同一库两条出口
    口径矛盾**：任一无令牌访客经细粒度工具即可读走 designer 以
    `sensitivity='private'` 提交的候选正文明文与归属（DSH 插件强制 full 工具面，
    `src/lib/mdcg_client.ts:121`，故该出口在插件部署下可达）。

修复（最小改动 · 与既有单点同口径）：
  ① `MdCGOS.propose` 的 rec 顶层补 `sensitivity`（取自 kw/extra，与节点
     frontmatter / 索引条目同形状，读侧判据免挖 extra）；
  ② `MdCGSecure.review_list` 覆写：逐条按 `_readable`（clearance × sensitivity
     ∧ 会话绑定，设计者豁免）过滤，密级未知按最高档 fail-closed；legacy 提案的
     密级从 `extra` 回退读取（存量不误伤）、封套内容仍按 `_open_content` 口径解封；
  ③ `mdcg_review_list` 的 op 要求对齐规范出口 ⇒ `"review"`（两出口同口径）；
  ④ 次生面：`MdCGSecure.review_list` 的 op 闸另引出只读体检面
     （`mdcg_health`，op=read 即可达）不再直连 `review_list` —— 新增
     `_review_list_visible`（基类=全量、隔离层=按可见性收窄，无 op 闸），
     health_os 的 `review_pending` 走它（否则 record/reflect/output/guest
     的体检面会被打成 AccessDenied）。

**刻意不改（本批如实留档）**：`inbox.jsonl` 的 `content` 仍为明文落盘。
提案队列是**跨身份交接面**，而 DEK 按身份签发（`crypto.provision_dek
(root, kek, tenant, actor)`，实测跨身份解密抛 CryptoError）——若按提案者
密钥封套落盘，复核者（另一身份）将**读不开自己必须裁决的候选**，accept
还会把提案者密钥的密文原样落进节点（`_write_node` 见 `is_encrypted` 即跳过
再封套），裁成盲审 + 节点此后对本身份以外永久不可读。故本批的补偿控制是
「读面身份闸（两出口）＋ 落盘密级留档（rec 顶层 sensitivity，为将来迁移
留字段）」；静态明文面属运维级信任边界（能读 root 文件系统者=运维权限），
如实标注为本轮残留，不冒充已修。

守卫（六组，全部临时库 + 哑主密钥 + 临时令牌库，**绝不触真实 ~/.mdcg**）：
  ⓿ 隔离自证；① 写面：rec 顶层 sensitivity / extra 保形 / 明文留档；
  ② 读面：guest 两出口同拒 + 复核者按密级与会话过滤（内部档被滤 / 高密级异
     会话仍滤 / 同会话可见 / 设计者全见 / 两出口 pid 集一致）+ 次生面（体检面
     `mdcg_health` 不被 op 闸误伤、位审计数随可见性收窄）+ 阳性对照（设计者经
     工具面 accept 成功、落盘节点正文为封套、裁决后出队）；
  ③ 泄漏量化（guest 若被放行则正文与归属必命中，一并钉死）；
  ④ 源断言 + live floor。

运行：python -X utf8 -m md_cg.test_n201_proposal_visibility
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
_TMP = tempfile.mkdtemp(prefix="n201_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "12" * 32          # 哑主密钥（绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_ACTOR", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES",
           "PYTHONIOENCODING", "PYTHONUTF8"):
    os.environ.pop(_k, None)

from . import crypto, mcp_server, nodefile, tokens          # noqa: E402
from .datapath import aux_root            # noqa: E402
from .fsutil import read_jsonl            # noqa: E402
from .mdcos import MdCGSecure             # noqa: E402
from .security import Principal           # noqa: E402

atexit.register(lambda: _cleanup(_TMP))       # LIFO：晚于库层 _atexit_flush_all

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.join(_TMP, "cg")
PASS = FAIL = LIVE = 0
LIVE_FLOOR = 12
FAILS = []

MARK = "N201-PROP-MARK-明文"
PRIV_BODY = "# 功能名：私密候选\n# 正文：%s（designer 提交，sensitivity=private）\n" % MARK
INT_BODY = "# 功能名：共享候选\n# 正文：N201-INBOX-共享档提案（record 提交，internal）\n"
S_DESIGN = "sess_n201_design"
S_ORCH = "sess_n201_orch"


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


def _princ(role, clearance="internal", can_admin=False, session=None,
           actor=None, layers=None):
    spec = tokens.role_spec(role)
    return Principal(tenant="default", actor=actor or ("n201-" + role),
                     clearance=clearance, can_write=bool(spec["can_write"]),
                     can_admin=can_admin, role=role, session=session,
                     layers_allow=(spec["layers_allow"] if layers is None
                                   else layers),
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


def _src_window(src, start, end):
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i)
    return src[i:] if j < 0 else src[i:j]


def _read_src(rel):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)
    with open(p, encoding="utf-8") as f:
        return f.read()


def _raw_rec(cg, pid):
    """原样读盘上 inbox 行（不经任何内存缓存）。"""
    for r in read_jsonl(cg.inbox_log):
        if r.get("pid") == pid:
            return r
    return None


def _pids(res):
    return sorted(str(r.get("pid")) for r in (res or {}).get("pending") or [])


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
    if not os.path.abspath(ROOT).lower().startswith(
            os.path.abspath(_TMP).lower()):
        print("FATAL: 隔离失败，中止（绝不带病跑真实库）")
        return 2

    # ---------- 夹具：designer 提 private、record 提 internal ----------
    print("\n[夹具] designer 提 private 候选 / record 提 internal 候选")
    design = _secured(_princ("designer", clearance="secret", can_admin=True,
                             session=S_DESIGN, actor="n201-design"))
    p_priv = design.propose("n201_priv", PRIV_BODY, layer="knowledge",
                            sensitivity="private", tags=["n201"])
    rec = _secured(_princ("record", session="sess_n201_rec", actor="n201-rec"))
    p_int = rec.propose("n201_int", INT_BODY, layer="knowledge", tags=["n201"])
    check("0b 夹具：两条提案入队（pid 前缀 prop_）",
          str(p_priv).startswith("prop_") and str(p_int).startswith("prop_"),
          "priv=%r int=%r" % (p_priv, p_int))

    # ---------- ① 写面：rec 顶层密级 + extra 保形 ----------
    print("\n【①】写面：提案落盘的密级口径")
    r_priv = _raw_rec(design, p_priv) or {}
    r_int = _raw_rec(design, p_int) or {}
    check("1a rec 顶层带 sensitivity（与节点 frontmatter/索引条目同形状）",
          r_priv.get("sensitivity") == "private"
          and r_int.get("sensitivity") == "internal",
          "顶层 sensitivity=%r / %r（修前：仅 extra 内有）"
          % (r_priv.get("sensitivity"), r_int.get("sensitivity")), live=True)
    check("1b extra.sensitivity 保形（存量读取方零变化）",
          (r_priv.get("extra") or {}).get("sensitivity") == "private",
          str((r_priv.get("extra") or {}).get("sensitivity")))
    check("1c 如实留档：正文仍为明文落在 inbox.jsonl（本批不封套，见报告）",
          MARK in str(r_priv.get("content") or ""),
          "content=%r" % (str(r_priv.get("content") or "")[:60]))

    # ---------- ② 读面：细粒度工具 vs 规范出口 ----------
    print("\n【②】读面：guest 两出口同拒 / 复核者按密级与会话过滤")
    guest = _secured(_princ("guest", clearance="internal", session="sess_n201_g"))
    ok_t, exc_t, res_t = _raises(mcp_server._dispatch, guest,
                                 "mdcg_review_list", {})
    _leak = json.dumps(res_t, ensure_ascii=False) if ok_t else ""
    check("2a guest 经细粒度工具 mdcg_review_list 被 AccessDenied"
          "（正文与 actor/session 归属均不返回）",
          (not ok_t) and exc_t == "AccessDenied"
          and MARK not in _leak and S_DESIGN not in _leak,
          "exc=%r leaked_mark=%r" % (exc_t, MARK in _leak), live=True)
    ok_k, exc_k, _res_k = _raises(mcp_server._dispatch, guest, "cg",
                                  {"op": "review", "action": "list"})
    check("2b 规范出口 cg(op=review, action=list) 对同身份同样 AccessDenied"
          "（两条出口口径一致）",
          (not ok_k) and exc_k == "AccessDenied", "exc=%r" % exc_k, live=True)
    orch = _secured(_princ("orchestr", clearance="internal",
                           session=S_ORCH, actor="n201-orch"))
    ok_o, exc_o, res_o = _raises(mcp_server._dispatch, orch,
                                 "mdcg_review_list", {})
    check("2c 复核者（orchestr/internal）看不到 private 候选、共享档仍可见",
          ok_o and p_priv not in _pids(res_o) and p_int in _pids(res_o),
          "pids=%r exc=%r" % (_pids(res_o) if ok_o else None, exc_o), live=True)
    orch_hi = _secured(_princ("orchestr", clearance="private",
                              session=S_ORCH, actor="n201-orch-hi"))
    ok_h, _e_h, res_h = _raises(mcp_server._dispatch, orch_hi,
                                "mdcg_review_list", {})
    check("2d 高密级但异会话的复核者：会话绑定档仍不可见（session 是隔离维度）",
          ok_h and p_priv not in _pids(res_h) and p_int in _pids(res_h),
          "pids=%r" % (_pids(res_h) if ok_h else None), live=True)
    orch_same = _secured(_princ("orchestr", clearance="private",
                                session=S_DESIGN, actor="n201-orch-same"))
    ok_s, _e_s, res_s = _raises(mcp_server._dispatch, orch_same,
                                "mdcg_review_list", {})
    check("2e 阳性对照：同会话且密级达标的复核者可见该 private 候选（未过度封禁）",
          ok_s and p_priv in _pids(res_s),
          "pids=%r" % (_pids(res_s) if ok_s else None), live=True)
    ok_d, _e_d, res_d = _raises(mcp_server._dispatch, design,
                                "mdcg_review_list", {})
    check("2f 设计者（can_admin）两条都在（管理位豁免，队列不被掏空）",
          ok_d and p_priv in _pids(res_d) and p_int in _pids(res_d),
          "pids=%r" % (_pids(res_d) if ok_d else None), live=True)
    _k_o = _raises(mcp_server._dispatch, orch, "cg",
                   {"op": "review", "action": "list"})
    check("2g 工具面与规范出口的待审 pid 集逐字一致（同一过滤单点）",
          ok_o and _k_o[0] and _pids(res_o) == _pids(_k_o[2]),
          "tool=%r kernel=%r" % (_pids(res_o) if ok_o else None,
                                 _pids(_k_o[2]) if _k_o[0] else _k_o[1]),
          live=True)

    # 次生面：只读体检面（mdcg_health，op=read 即可达）——本轮 op 闸只该管
    # 「取正文」面，不得把体检面打成 AccessDenied；计数面须随可见性收窄
    # （否则待审计数成了「暗中还有几条不可见提案」的越权元数据——低权身份
    # 可由 计数−可见 反推隐藏提案的存在与条数）。
    _h = _raises(mcp_server._dispatch, orch, "mdcg_health", {})
    _hp = ((_h[2] or {}).get("os") or {}).get("review_pending")
    _vis_n = len(_pids(res_o)) if ok_o else None
    _all_n = len(_pids(res_d)) if ok_d else None
    check("2h 次生面：体检面 mdcg_health 对低权身份可用不抛，且位审计数"
          "= 该身份可见待审数（可见集 ⊊ 全体：不越权暴露不可见提案的存在性）",
          _h[0] and _hp is not None and _vis_n is not None
          and _all_n is not None and _vis_n < _all_n and _hp == _vis_n,
          "exc=%r health_pending=%r 可见=%r 全体=%r"
          % (_h[1], _hp, _vis_n, _all_n), live=True)

    # 阳性对照：合规裁决路径在修复后仍走得通（本修复只收口越权读面，不封裁决面）
    ok_dd, exc_dd, res_dd = _raises(mcp_server._dispatch, design,
                                    "mdcg_review_decide",
                                    {"pid": p_priv, "decision": "accept",
                                     "reason": "N201 守卫：合规裁决"})
    check("2i 设计者经工具面 accept 私密候选成功（未过度收口）",
          ok_dd and bool((res_dd or {}).get("ok"))
          and (res_dd or {}).get("node_id") == "n201_priv",
          "exc=%r res=%r" % (exc_dd, res_dd), live=True)
    _e_np = (design.index.get("nodes") or {}).get("n201_priv") or {}
    _disk = ""
    if _e_np.get("path"):
        try:
            with open(os.path.join(ROOT, _e_np["path"]), encoding="utf-8") as f:
                _disk = f.read()
        except OSError as exc:
            _disk = "<读盘失败 %s>" % exc
    _disk_fm, _disk_body = {}, ""
    if _disk:
        try:
            _disk_fm, _disk_body = nodefile.loads(_disk)
            _disk_fm = _disk_fm or {}
        except Exception as exc:               # noqa: BLE001 —— 诊断面
            _disk_fm = {"<解析失败>": str(exc)}
    check("2j accept 落盘的 private 节点正文在盘上为封套"
          "（同源「private 落盘即封套」口径，提案面不成为绕过口）",
          bool(_disk) and crypto.is_encrypted(_disk_body) and MARK not in _disk,
          "path=%r fm.sensitivity=%r sealed=%r 明文命中=%r body=%r"
          % (_e_np.get("path"), _disk_fm.get("sensitivity"),
             crypto.is_encrypted(_disk_body), MARK in _disk,
             (_disk_body or "")[:90]), live=True)
    ok_l2, _e_l2, res_l2 = _raises(mcp_server._dispatch, design,
                                   "mdcg_review_list", {})
    check("2k 裁决后该 pid 出队（工具面队列与规范出口同步收口）",
          ok_l2 and p_priv not in _pids(res_l2),
          "pids=%r" % (_pids(res_l2) if ok_l2 else None), live=True)

    # ---------- ③ 泄漏量化（红态证据链） ----------
    print("\n【③】泄漏量化：若 guest 被放行，正文/归属必命中")
    _rows = res_t.get("pending") if ok_t else []
    _hit_body = [r.get("pid") for r in _rows
                 if MARK in str(r.get("content") or "")]
    _hit_attr = [r.get("pid") for r in _rows
                 if r.get("actor") == "n201-design"
                 and r.get("session") == S_DESIGN]
    check("3a 修前形态判定：guest 一旦拿到结果，私密正文与归属都在其中",
          (not ok_t) or (bool(_hit_body) and bool(_hit_attr)),
          "body=%r attr=%r" % (_hit_body, _hit_attr), live=True)

    # ---------- ④ 源断言 + floor ----------
    print("\n【④】源断言（三处接线在位）")
    _s_mdcos = _read_src("mdcos.py")
    _prop = _src_window(_s_mdcos, "def propose(self, node_id", "def _pid_status")
    check("4a propose 的 rec 顶层落 sensitivity（读侧判据免挖 extra）",
          '"sensitivity": kw.get("sensitivity")' in _prop, _prop[-200:])
    _rl = _src_window(_s_mdcos, "def review_list",
                      "# 生效条件：先 principal.require_op(\"review\")（语义修正 2026-09-22")
    check("4b MdCGSecure.review_list 覆写 = op 闸 + _readable 过滤（密级 × 会话）",
          "require_op(\"review\")" in _rl and "_readable" in _rl
          and "sensitivity" in _rl, _rl[-260:])
    _hsrc = _src_window(_s_mdcos, "def health_os(self):",
                        "def _log_scale")
    check("4e 体检面的待审计数走可见性计数面（不被取正文面的 op 闸误伤）",
          "_review_list_visible" in _hsrc, _hsrc[-160:])
    _s_mcp = _read_src("mcp_server.py")
    check("4c 细粒度工具 mdcg_review_list 的 op 要求对齐规范出口 = review",
          '"mdcg_review_list": "review"' in _s_mcp,
          _src_window(_s_mcp, '"mdcg_propose": "write"',
                      '"mdcg_review_decide"')[-160:])
    print("  [INFO] live 断言数 = %d（floor=%d）" % (LIVE, LIVE_FLOOR))
    check("4d live 断言数不低于 floor（防空转绿）", LIVE >= LIVE_FLOOR,
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
