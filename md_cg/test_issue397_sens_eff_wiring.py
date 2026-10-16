# -*- coding: utf-8 -*-
# 功能名：remember_gated 的三处下游原语必须读**有效密级** _sens_eff（issue #397）；confirm 档 B 类单出单前必须按同一有效密级判降密级（issue #424）
# 生效条件：python -X utf8 -m md_cg.test_issue397_sens_eff_wiring [--mutate]；被测面＝md_cg/mdcos.py::MdCGSecure.remember_gated 内三个下游落点（converge_into / reinforce / record_drop）的 sensitivity 实参来源 + _autonomy_gate_merge 出单前的降密级判据（confirm 档）
# 子功能：A 组＝复现（不重传 sensitivity 改写既有 private 节点 ⇒ MERGE 泄漏 / DROP 全文明文）+ 库层直调 + 工具面两条入口；B 组＝#424（缺省 confirm 档 B 类单：MERGE/CONVERGE 两腿、restricted 源走 CONVERGE、库层直调、伪造单的执行桥纵深防御、同档与显式声明对照）；K 组＝非恒真对照（显式声明路径两态皆绿、同密级合并照常、低密级并入高密级照常）；E 组＝**同函数内 kw.get(sensitivity) 全枚举 + AST 钉子**（除声明值入口外不得直传下游；#424 两处档位闸调用必须传 _sens_eff、判据先于出单）
# 执行：--mutate 时在镜像树里把 _sens_eff 改回 kw.get("sensitivity")（回缺陷，逐落点）与「恒取较高密级」（过度收紧）、拆 #424 接线（M5/M6）与恒真判据（M7），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**
# 不适用条件：不判 secret 密级的同形复现（报告自陈未跑；同一根因应按同构成立）；不判多进程/多租户同路径；不穷尽 restricted 的全部角色组合（只测 record/output/guest）
"""issue #397 守卫：#345 的有效密级单点 `_sens_eff` 只接到了 2 处；issue #424 守卫：
#397 修好的只有 ALLOW 档（full），confirm 档出单面按**合并目标**继承密级。

病象（修前）：`remember_gated` 在 :4904-4913 已算出**有效密级** `_sens_eff`（声明值 ∨ 继承既有
节点密级），但只有 `writelimit.check`(:4919) 与 `writelimit.record_accepted`(:5057) 用了它；
`converge_into`(:4942) / `reinforce`(:5092) / `record_drop`(:5105) 三处仍读**声明值**
`kw.get("sensitivity")`——在「同 id 改写既有节点 + 不重传 sensitivity」（本仓常态）时为 `None`，
而 `security.merge_downgrades(target, None)` 按 DEFAULT_SENSITIVITY 处理 ⇒ 恒 False ⇒ 放行：
  · MERGE：private 正文以聚合行并入 **internal** 节点，internal 档读者可读回全文（P0）；
  · DROP ：private 正文**全文**明文入 `_forgetting.jsonl`（content_redacted=false，P0）；
  · CONVERGE：restricted 明文并入 internal（P1）。

**与 #315 的分工（为什么 #315 的守卫没抓住）**：#315 补的是「MERGE 支行没传 sensitivity 形参」，
其 A 组只测**显式声明**路径（`write(..., "private")`）——那种情形下 `kw.get("sensitivity")` 恰好
等于 `_sens_eff`，故 #315 守卫两态皆绿。本条补的是**取值对象错了**（继承路径），故 A 组专测
「不重传 sensitivity 的同 id 改写」。

**#424 增补（B 组）**：#397 修好的三处落点只在 `B_MERGE == ALLOW`（full 档）可达；缺省
confirm 档 MERGE/CONVERGE 先进 `_autonomy_gate_merge` 出 B 类变更单，出单传的是声明值
（None）⇒ `MdCGSecure.propose` 按**合并目标** id 继承密级（#297 的继承单点为「同 id 改写」
设计）⇒ 单面 sensitivity=目标的 internal ⇒ accept 后 `_mutation_execute` 把 internal 喂给
原语、降密级判「同档」放行，private/restricted 正文以聚合行明文并入 internal 节点（无令牌
访客可读）。修复＝出单前按源有效密级（incoming_sensitivity=_sens_eff）走
security.merge_downgrades 唯一单点判降密级，判中即与 full 档同形 fail-closed 拒绝；
另在载荷 meta 记 source_node_id/incoming_sensitivity，执行桥 B 分支取「单面 ∨ 源」更严一档
（纵深防御，B10/B11 用伪造单钉）。

「守卫必须能在变异态下跑完」：取数一律经包装折成可命名形态，不崩栈。
"""
from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

#: 夹具模板逐字取自 `md_cg/test_issue315_merge_branch_sensitivity.py`（复用口径，不另造）。
TPL = ("灵枢运维记录：本次把门禁卡新口令已更新为 {N}，并同步更新了值班手册与交接清单；"
       "后续把预热检查加进值班流程，把巡检脚本的日志目录改到 D 盘，确认备份窗口在凌晨三点，"
       "网络抖动期间不要触发重建；以上变更已在预发环境验证通过，观察一周无异常后同步到生产。"
       "另外记录三件待办：其一，把缓存预热脚本的并发度从四调到八并观察一周；其二，巡检告警的"
       "阈值按上周的基线重算，避免夜间误报；其三，把交接文档里的联系人表补齐并同步到共享盘。")
SECRET = "397MARK私密备用金藏在书架第三格"
SECRET_R = "424MARK跳板机口令在机柜二层"
ANCHOR_N = "739155"

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


class _Env:
    """隔离库根 + 工具面/库层两条写入口（口径照 test_issue315）。

    b_merge：按 §三矩阵的 B_MERGE 格选档（None=ALLOW 即 full 档，#397 原口径）；
    #424 起另测 CONFIRM 格（confirm 档出单面）——档位字面量不入本文件
    （test_autonomy_modes G 组是全仓反漂移守卫）。
    """

    def __init__(self, clearance="secret", b_merge=None):
        self.dir = tempfile.mkdtemp(prefix="iss397_")
        self.clearance = clearance
        self.saved = {}
        self.b_merge = b_merge

    def __enter__(self):
        from md_cg import autonomy_modes as _am
        from md_cg import crypto
        _cell = self.b_merge if self.b_merge is not None else _am.ALLOW
        self.mode = next(m for m in _am.AUTONOMY_MODES
                         if (_am.MATRIX.get(m) or {}).get(_am.B_MERGE) == _cell)
        env = {"MDCG_ROOT": self.dir + "/brain",
               "MDCG_STATE_ROOT": self.dir + "/state",
               "MDCG_AUX_ROOT": self.dir + "/auxstore",
               "MDCG_DATA_ROOT": self.dir + "/data",
               "MDCG_EXPORT_ROOT": self.dir,
               "MDCG_TOKEN_FILE": self.dir + "/auxstore/tokens.json",
               "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
               _am.AUTONOMY_ENV_KEYS["mode"]: self.mode,
               crypto.MASTER_ENV: "ab" * 32}
        for k, v in env.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        self.cg = MdCGSecure(os.environ["MDCG_ROOT"],
                             principal=Principal(clearance=self.clearance,
                                                 can_admin=True),
                             autoflush=1)
        return self

    def __exit__(self, *exc):
        try:
            self.cg.close()
        except Exception:                           # noqa: BLE001
            pass
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)
        return False

    def write(self, nid, content, sens=None, role="user"):
        """工具面入口：mdcg_remember(gated=True)。sens 为 None 即「不重传 sensitivity」。"""
        from md_cg import mcp_server
        kw = {"node_id": nid, "content": content, "layer": "contextual",
              "role": role, "gated": True, "verification_basis": "test"}
        if sens:
            kw["sensitivity"] = sens
        return mcp_server._dispatch(self.cg, "mdcg_remember", kw)

    def write_lib(self, nid, content, sens=None, role="user"):
        """**库层直调**入口：MdCGSecure.remember_gated。"""
        kw = {"layer": "contextual", "role": role, "verification_basis": "test"}
        if sens:
            kw["sensitivity"] = sens
        return self.cg.remember_gated(nid, content, **kw)

    def read(self, nid, clearance="internal"):
        """以**另一档 clearance** 的读者读同一库根（谁能读到）。"""
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        cg2 = MdCGSecure(os.environ["MDCG_ROOT"],
                         principal=Principal(clearance=clearance), autoflush=0)
        try:
            n = cg2.get(nid)
            return (n or {}).get("content") or ""
        finally:
            cg2.close()

    def forgetting_ledger(self):
        p = os.path.join(os.environ["MDCG_ROOT"], "_forgetting.jsonl")
        if not os.path.exists(p):
            return []
        rows = []
        with io.open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
        return rows


print("== A 组：#397 复现——不重传 sensitivity 改写既有 private 节点 ==")
with _Env() as e:
    A = TPL.format(N=ANCHOR_N)
    B = TPL.format(N=ANCHOR_N) + " 私密补充：" + SECRET
    r1 = e.write("t_internal", A, "internal")
    _check("A01 前提：internal 目标节点写入成功", r1.get("ok") is True, r1)
    r2 = e.write("p_priv", "私密草稿：仅本人可见的初始正文。", "private")
    _check("A02 前提：private 节点以 private 创建成功", r2.get("ok") is True, r2)
    r3 = e.write("p_priv", B)                      # ← 不重传 sensitivity（本仓常态）
    gate = r3.get("gate") or {}
    _check("A03 前提：本次改写被判 MERGE（走的就是本支）",
           gate.get("verdict") == "MERGE", gate.get("verdict"))
    rein = r3.get("reinforced") or {}
    _check("A04 ★行：reinforced 报 merge_downgrade_refused（有效密级 private 高于目标 internal）",
           rein.get("error") == "merge_downgrade_refused"
           and rein.get("incoming_sensitivity") == "private", rein)
    body = e.read("t_internal", clearance="internal")
    _check("A05 ★行：internal 档读者读回的正文**不含** private 独有串",
           SECRET not in body, (len(body), body[-90:]))
    _check("A06 ★行：目标节点正文里没有聚合行被追加",
           (rein.get("content_sink") or {}).get("action") != "appended",
           rein.get("content_sink"))

print("== A 组（库层直调）：同一条路径的 API 入口 ==")
with _Env() as e:
    A = TPL.format(N=ANCHOR_N)
    B = TPL.format(N=ANCHOR_N) + " 私密补充：" + SECRET
    e.write("t_internal", A, "internal")
    e.write("p_priv", "私密草稿：仅本人可见的初始正文。", "private")
    r4 = e.write_lib("p_priv", B)                  # ← 库层直调、不重传 sensitivity
    rein4 = r4.get("reinforced") or {}
    _check("A07 ★行（库层直调）：reinforced 报 merge_downgrade_refused",
           rein4.get("error") == "merge_downgrade_refused", rein4)
    _check("A08 ★行（库层直调）：internal 档读者读回不含 private 独有串",
           SECRET not in e.read("t_internal", clearance="internal"), "")

print("== A 组（DROP 支）：private 全文不得明文落 _forgetting.jsonl ==")
with _Env() as e:
    A = TPL.format(N=ANCHOR_N)
    B = TPL.format(N=ANCHOR_N) + " 私密补充：" + SECRET
    e.write("t_internal", A, "internal")
    e.write("p_priv", "私密草稿：仅本人可见的初始正文。", "private")
    r5 = e.write("p_priv", B, role="tool-output")   # 内部确定性来源 ⇒ assess 的 DROP 支
    gate5 = r5.get("gate") or {}
    _check("A09 前提：本次改写被判 DROP（走的是本支）",
           gate5.get("verdict") == "DROP", gate5.get("verdict"))
    rows = e.forgetting_ledger()
    _check("A10 ★行：台账非空且确有 drop 留痕", bool(rows), len(rows))
    _check("A11 ★行：台账里**不含** private 正文明文独有串",
           all(SECRET not in json.dumps(r, ensure_ascii=False) for r in rows),
           [json.dumps(r, ensure_ascii=False)[:120] for r in rows][:2])
_check("A12 ★行：DROP 留痕的 content_redacted 为 true（密级为加密级时不留明文）",
       bool(rows) and all(r.get("content_redacted") is True for r in rows
                          if r.get("action") == "drop" or "dropped_content" in r
                          or r.get("content_redacted") is not None),
       [(r.get("content_redacted"), str(r.get("dropped_content"))[:60]) for r in rows][:3])

print("== A 组（CONVERGE 支）：restricted 明文不得并入 internal ==")
with _Env() as e:
    TITLE = "# 功能名：批次397收官记忆"
    c1 = TITLE + chr(10) + "正文甲：本次盘点把三条待办收敛成一条。" * 3
    c2 = TITLE + chr(10) + "正文乙：补充说明 " + SECRET + "。" * 3
    e.write("c_t1", c1, "internal")
    e.write("p_priv2", "私密草稿：仅本人可见的初始正文二。", "private")
    r6 = e.write("p_priv2", c2)                    # 不重传 ⇒ 有效密级 = private（继承）
    g6 = r6.get("gate") or {}
    _check("A13 加密级改写（有效密级 private）⇒ check **不**判 CONVERGE（#313 闸口：加密级跳过同构聚合）",
           g6.get("verdict") != "CONVERGE", g6.get("verdict"))
    _check("A14 因此 CONVERGE 落点的「加密级→internal」降密级组合**不可达**（结构性前提，非遗漏）",
           g6.get("verdict") != "CONVERGE"
           and SECRET not in e.read("c_t1", clearance="internal"),
           (g6.get("verdict"), e.read("c_t1", clearance="internal")[-60:]))

print("== B 组（#424）：缺省 confirm 档 B 类单——出单前按**源有效密级**判降密级 ==")
# #397 只修了 ALLOW 档（full）：`_sens_eff` 直达 reinforce/converge_into，判据在原语内
# 生效。confirm 档 B_MERGE 出单走 propose（sensitivity=声明值，未声明即 None），
# `MdCGSecure.propose` 按**传入 id** 继承密级——而传入的是合并目标 ⇒ 单面密级换成
# 目标的 internal ⇒ accept 后 `_mutation_execute` 把 internal 喂给原语，降密级判
# 「同档」放行：private/restricted 正文以聚合行明文并入 internal 节点（#424 病象）。
# 处置：`_autonomy_gate_merge` 出单前按 incoming_sensitivity（＝_sens_eff）判
# security.merge_downgrades（唯一单点），判中即与 full 档同形 fail-closed 拒绝
# （不出单、不落盘、不进 inbox）。
from md_cg import autonomy_modes as _am424


def _drain_accept(e, r):
    """缺陷态兜底：若回执带 pid（出单了），accept 之——复现「裁决者照常 accept」
    这一环，让泄漏在读数上可见（修复态无 pid，本函数为 no-op）。"""
    pid = r.get("pid")
    if pid:
        try:
            e.cg.review_decide(pid, "accept", reason="守卫：缺陷态兜底 accept")
        except Exception:                           # noqa: BLE001
            pass


with _Env(b_merge=_am424.CONFIRM) as e:
    A = TPL.format(N=ANCHOR_N)
    B = TPL.format(N=ANCHOR_N) + " 私密补充：" + SECRET
    e.write("t_int_c", A, "internal")
    e.write("p_priv_c", "私密草稿：confirm 档初始正文。", "private")
    r = e.write("p_priv_c", B)                      # 不重传 ⇒ 有效密级 = private（继承）
    _check("B01 前提：confirm 档 MERGE 改写走的就是本支",
           (r.get("gate") or {}).get("verdict") == "MERGE", (r.get("gate") or {}).get("verdict"))
    _check("B02 ★行：出单前拦下——回执无 pid、无 mutation（不进审核队列）",
           not r.get("pid") and not r.get("mutation"),
           {k: r.get(k) for k in ("pid", "moved_to", "error")})
    _check("B03 ★行：回执 error=merge_downgrade_refused（与 full 档原语同名单点）、"
           "incoming=private / target=internal",
           r.get("error") == "merge_downgrade_refused"
           and r.get("moved_to") == "merge_downgrade_refused"
           and r.get("incoming_sensitivity") == "private"
           and r.get("target_sensitivity") == "internal"
           and r.get("committed") is False, r)
    _check("B04 ★行：审核队列无本条 B 类单（源正文不落 inbox）",
           all(SECRET not in (x.get("content") or "") for x in e.cg.review_list()),
           [x.get("pid") for x in e.cg.review_list()])
    _drain_accept(e, r)
    _check("B05 ★行：internal 档读者读回目标正文**不含** private 独有串",
           SECRET not in e.read("t_int_c", clearance="internal"), "")
    _check("B06 对照：源节点仍是 private、internal 档读者读不到（K6 同款）",
           ((e.cg.get("p_priv_c") or {}).get("frontmatter") or {}).get("sensitivity")
           == "private"
           and SECRET not in e.read("p_priv_c", clearance="internal"), "")

print("== B 组（CONVERGE/restricted 腿 + 库层直调） ==")
with _Env(b_merge=_am424.CONFIRM) as e:
    TITLE = "# 功能名：批次424收官记忆"
    c1 = TITLE + chr(10) + "正文甲：本次盘点把三条待办收敛成一条。" * 3
    c2 = TITLE + chr(10) + "正文乙：补充说明 " + SECRET_R + "。" * 3
    e.write("c_t1c", c1, "internal")
    e.write("r_res_c", "受限草稿：confirm 档初始正文。", "restricted")
    r2 = e.write("r_res_c", c2)          # restricted ∉ ENCRYPTED_LEVELS ⇒ 走得到 CONVERGE
    g2 = r2.get("gate") or {}
    _check("B07 ★行：restricted 源走 CONVERGE（#313 闸口不含 restricted）同样被"
           "出单前拦下（incoming=restricted）",
           g2.get("verdict") == "CONVERGE"
           and r2.get("error") == "merge_downgrade_refused"
           and r2.get("incoming_sensitivity") == "restricted"
           and not r2.get("pid"), (g2.get("verdict"), r2.get("error")))
    _drain_accept(e, r2)
    _check("B08 ★行：internal 档读者读回 CONVERGE 目标**不含** restricted 独有串",
           SECRET_R not in e.read("c_t1c", clearance="internal"), "")

with _Env(b_merge=_am424.CONFIRM) as e:
    A = TPL.format(N=ANCHOR_N)
    B = TPL.format(N=ANCHOR_N) + " 私密补充：" + SECRET
    e.write("t_int_l", A, "internal")
    e.write("p_priv_l", "私密草稿：库层直调初始正文。", "private")
    r3 = e.write_lib("p_priv_l", B)                 # 库层直调、不重传 sensitivity
    _drain_accept(e, r3)
    _check("B09 ★行（库层直调）：同一路径出单前拦下且不泄漏（C5 同款场景）",
           r3.get("error") == "merge_downgrade_refused" and not r3.get("pid")
           and SECRET not in e.read("t_int_l", clearance="internal"),
           {k: r3.get(k) for k in ("error", "pid")})

print("== B 组（纵深防御：伪造「单面密级取目标」的 B 类单，执行桥复核） ==")
with _Env(b_merge=_am424.CONFIRM) as e:
    A = TPL.format(N=ANCHOR_N)
    B = TPL.format(N=ANCHOR_N) + " 私密补充：" + SECRET
    e.write("t_int_d", A, "internal")
    pay = _am424.mutation_payload(
        _am424.B_MERGE, "t_int_d", after=B,
        reason="伪造单：单面密级按目标继承（#424 病灶形态），载荷如实记 private",
        primitive="reinforce",
        meta={"source_node_id": "p_priv_d", "incoming_sensitivity": "private"})
    pr = _am424.propose_mutation(e.cg, _am424.B_MERGE, "t_int_d", payload=pay,
                                 layer="contextual", info=True)
    rd = e.cg.review_decide(pr["pid"], "accept", reason="守卫")
    det = rd.get("detail") or {}
    _check("B10 ★行（纵深防御）：单面 internal/载荷 private 的 B 类单 accept 被执行桥拦",
           rd.get("ok") is False and rd.get("error") == "mutation_execute_failed"
           and det.get("error") == "merge_downgrade_refused",
           {k: rd.get(k) for k in ("ok", "error")})
    _check("B11 ★行（纵深防御）：目标正文未并入 private 串、单保持 pending 可见",
           SECRET not in e.read("t_int_d", clearance="internal")
           and any(x.get("pid") == pr["pid"] for x in e.cg.review_list()), "")

print("== B 组（对照：判据只拦降密级，同档与显式声明腿的行为面） ==")
with _Env(b_merge=_am424.CONFIRM) as e:
    A = TPL.format(N=ANCHOR_N)
    B2 = TPL.format(N=ANCHOR_N) + " 内部补充：无密级串。"
    e.write("t_int_k", A, "internal")
    e.write("q_int_k", "内部草稿：confirm 同档初始正文。", "internal")
    rk = e.write("q_int_k", B2)
    _check("B12 对照：confirm 档同密级（internal→internal）照常出单（K4 同款）",
           rk.get("verdict") == "CONFIRM" and bool(rk.get("pid"))
           and rk.get("moved_to") == "review_queue",
           {k: rk.get(k) for k in ("verdict", "pid", "moved_to")})
    rk_pid = rk.get("pid")
    ra = (e.cg.review_decide(rk_pid, "accept", reason="守卫")
          if rk_pid else {"ok": False, "skipped": "无 pid（未出单）"})
    _check("B13 对照：accept 照常执行合并（判据不误伤同档）",
           ra.get("ok") is True
           and "内部补充" in e.read("t_int_k", clearance="internal"), ra)
with _Env(b_merge=_am424.CONFIRM) as e:
    A = TPL.format(N=ANCHOR_N)
    B = TPL.format(N=ANCHOR_N) + " 私密补充：" + SECRET
    e.write("t_int_x", A, "internal")
    e.write("p_priv_x", "私密草稿：显式声明腿初始正文。", "private")
    rx = e.write("p_priv_x", B, "private")          # 显式声明（K3 场景）
    _check("B14 对照：confirm 档显式声明 private 同样**出单前**拦下"
           "（K3 由「单上 private、accept 拒」收紧为当场拒，回执含 hint）",
           rx.get("error") == "merge_downgrade_refused" and not rx.get("pid")
           and bool(rx.get("hint")), rx.get("error"))

print("== K 组：非恒真对照（含过度收紧方向） ==")
# 因果对照：显式声明 ⇒ 判据照旧拦下（证明 A04/A07 的绿不是「判据恒拒」）
with _Env() as e:
    A = TPL.format(N=ANCHOR_N)
    B = TPL.format(N=ANCHOR_N) + " 私密补充：" + SECRET
    e.write("t_internal", A, "internal")
    e.write("p_priv", "私密草稿：仅本人可见的初始正文。", "private")
    r7 = e.write("p_priv", B, "private")
    _check("K01 因果对照：**显式声明** private 改写 ⇒ 仍被 fail-closed 拦下",
           (r7.get("reinforced") or {}).get("error") == "merge_downgrade_refused",
           r7.get("reinforced"))
_check("K02 对照：新写入（无既有节点）不因单点改读有效值而被误拦",
       True, "")   # 由 A01 的前提断言覆盖（t_internal 首次写入即 ok=True）
with _Env() as e:
    A = TPL.format(N=ANCHOR_N)
    B = TPL.format(N=ANCHOR_N) + " 内部补充：无密级串。"
    e.write("t_internal", A, "internal")
    e.write("q_int", "内部草稿：初始正文。", "internal")
    r8 = e.write("q_int", B)                       # 不重传 ⇒ 继承 internal
    _check("K03 ★过度收紧方向的对照：未声明改写既有 **internal** 节点 ⇒ 继承 internal、照常合并",
           (r8.get("reinforced") or {}).get("error") is None
           and SECRET not in (e.read("t_internal", clearance="internal") or ""),
           r8.get("reinforced"))
with _Env() as e:
    A = TPL.format(N=ANCHOR_N)
    B = TPL.format(N=ANCHOR_N) + " 内部补充。"
    e.write("t_private", A, "private")
    e.write("q_int2", "内部草稿：初始正文二。", "internal")
    r9 = e.write("q_int2", B)
    _check("K04 低密级并入高密级照常放行（非泄漏方向，不在判据范围）",
           (r9.get("reinforced") or {}).get("error") is None, r9.get("reinforced"))

print("== E 组：全枚举 ＋ AST 钉子（本 issue 的正题：洞不得再漏一次） ==")


def _rg_fn():
    with io.open(os.path.join(_REPO, "md_cg/mdcos.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "remember_gated":
            return n
    return None


_FN = _rg_fn()
_PARENT = {}
for _p in ast.walk(_FN):
    for _c in ast.iter_child_nodes(_p):
        _PARENT[id(_c)] = _p
_KW_SENS = [c for c in ast.walk(_FN) if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute) and c.func.attr == "get"
            and getattr(c.func.value, "id", "") == "kw"
            and c.args and isinstance(c.args[0], ast.Constant)
            and c.args[0].value == "sensitivity"]
_SENS_ARGS = [(ast.unparse(c.func), ast.unparse(k.value), k.value.lineno)
              for c in ast.walk(_FN) if isinstance(c, ast.Call)
              for k in c.keywords if k.arg == "sensitivity"]
_check("E01 全枚举：remember_gated 内 kw.get(\"sensitivity\") **恰 1 处**（声明值入口）",
       len(_KW_SENS) == 1, [(c.lineno) for c in _KW_SENS])
_check("E02 ★钉子：该唯一入口是**声明值入口**（赋值给 _dec），不是直传下游",
       len(_KW_SENS) == 1
       and isinstance(_PARENT.get(id(_KW_SENS[0])), ast.Assign),
       type(_PARENT.get(id(_KW_SENS[0]))).__name__)
_check("E03 ★钉子：该函数内所有 sensitivity= 实参**全部**来自单点 _sens_eff",
       bool(_SENS_ARGS) and all(v == "_sens_eff" for _f, v, _l in _SENS_ARGS),
       [(l, v) for _f, v, l in _SENS_ARGS if v != "_sens_eff"])
_check("E04 钉子非空转：下游落点数 ≥ 5（check/record_accepted/converge_into/reinforce/record_drop）",
       len(_SENS_ARGS) >= 5, len(_SENS_ARGS))
_check("E05 报告点名的三个落点逐名检查（各自 sensitivity 均为 _sens_eff）",
       all(any(f.endswith(n) and v == "_sens_eff" for f, v, _l in _SENS_ARGS)
           for n in ("converge_into", "reinforce", "record_drop")),
       [(f, v) for f, v, _l in _SENS_ARGS])
_check("E06 声明值入口仍在（防把入口一并删掉后 _sens_eff 无源）",
       any(isinstance(n, ast.Assign)
           for n in ast.walk(_FN) if isinstance(n, ast.Assign)
           and any(isinstance(t, ast.Name) and t.id == "_dec" for t in n.targets)), "")


def _agm_fn():
    with io.open(os.path.join(_REPO, "md_cg/mdcos.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "_autonomy_gate_merge":
            return n
    return None


_GATE_CALLS = [c for c in ast.walk(_FN) if isinstance(c, ast.Call)
               and isinstance(c.func, ast.Attribute)
               and c.func.attr == "_autonomy_gate_merge"]
_check("E07 ★钉子（#424）：remember_gated 对档位闸的调用恰 2 处（MERGE/CONVERGE），"
       "每处都传 incoming_sensitivity=_sens_eff",
       len(_GATE_CALLS) == 2 and all(
           any(k.arg == "incoming_sensitivity"
               and ast.unparse(k.value) == "_sens_eff" for k in c.keywords)
           for c in _GATE_CALLS),
       [(c.lineno, [ast.unparse(k.value) for k in c.keywords]) for c in _GATE_CALLS])
_agm = _agm_fn()
_agm_calls = [c for c in ast.walk(_agm or ast.Module(body=[], type_ignores=[]))
              if isinstance(c, ast.Call)]
_md424 = [c for c in _agm_calls if isinstance(c.func, ast.Attribute)
          and c.func.attr == "merge_downgrades"]
_pm424 = [c for c in _agm_calls if isinstance(c.func, ast.Attribute)
          and c.func.attr == "propose_mutation"]
_check("E08 ★钉子（#424）：_autonomy_gate_merge 具 incoming_sensitivity 形参，"
       "且 merge_downgrades 判据**先于**propose_mutation 出单",
       bool(_agm)
       and "incoming_sensitivity" in [a.arg for a in _agm.args.args
                                      + _agm.args.kwonlyargs]
       and len(_md424) == 1 and len(_pm424) == 1 and _md424[0].lineno < _pm424[0].lineno,
       (bool(_agm), len(_md424), len(_pm424)))

shutil.rmtree(os.path.join(tempfile.gettempdir(), "iss397_probe"), ignore_errors=True)
# ---------------------------------------------------------------- 定点变异表
# 锚点跨行用 chr(10) 拼接；_apply_text 按目标文件实际行尾折算（mdcos.py 为 CRLF）。
# M1/M2 锚点随 #417（reinforce 增 src_id= 形参）重钉：单行 `sensitivity=_sens_eff,`
# 在 reinforce 与 record_drop 两处同形，须带上下文行区分（修前 0/2 命中的现场教训）。
_REINFORCE_OK = chr(10).join([
    "                # 可读回全文（本处即报告的第 2 落点，P0）。",
    "                sensitivity=_sens_eff,"])
_DROP_OK = chr(10).join([
    "                # 第 1 落点，P0）。",
    "                sensitivity=_sens_eff,",
    "                session=_writer_session(self, kw), actor=self.actor)"])
_CONVERGE_OK = "                           sensitivity=_sens_eff)}"
_MUTATIONS = (
    # M1 回缺陷（MERGE 支读声明值）⇒ A04–A08（工具面 + 库层直调）转红；E03/E05 一并转红。
    ("M1 回缺陷：reinforce 改读声明值", "md_cg/mdcos.py",
     ((_REINFORCE_OK, chr(10).join([
         "                # 可读回全文（本处即报告的第 2 落点，P0）。",
         '                sensitivity=kw.get("sensitivity"),'])),),
     ("A04", "A05", "A06", "A07", "A08", "E01", "E02", "E03", "E05")),
    # M2 回缺陷（DROP 支读声明值）⇒ A11/A12 转红（private 全文入台账）；E03/E05 同红。
    ("M2 回缺陷：record_drop 改读声明值", "md_cg/mdcos.py",
     ((_DROP_OK, chr(10).join([
         "                # 第 1 落点，P0）。",
         '                sensitivity=kw.get("sensitivity"),',
         "                session=_writer_session(self, kw), actor=self.actor)"])),),
     ("A11", "A12", "E01", "E02", "E03", "E05")),
    # M3 回缺陷（CONVERGE 支读声明值）⇒ 该落点的降密级行为在本树**不可达**（A13/A14 已钉），
    # 故只有**结构性**两条转红——如实：这条腿证明接线一致性，不是行为泄漏。
    ("M3 回缺陷：converge_into 改读声明值（该落点不可达，红项为结构性）",
     "md_cg/mdcos.py",
     ((_CONVERGE_OK, '                           sensitivity=kw.get("sensitivity"))}'),),
     ("E01", "E02", "E03", "E05")),
    # M4 过度收紧（声明值入口恒抬高成 private）⇒ 未声明继承腿被误拦：confirm 档同档
    # 合并（B12/B13）与 restricted 走 CONVERGE 腿（B07）转红；full 档同款误拦 K03 转红；
    # E02 转红（kw.get 的父节点由 Assign 变 BinOp——声明值入口形态被改）。
    ("M4 过度收紧：声明值入口恒抬高为 private（误伤继承腿）", "md_cg/mdcos.py",
     (('        _dec = kw.get("sensitivity")',
       '        _dec = kw.get("sensitivity") or "private"'),),
     ("B07", "B12", "B13", "E02", "K03")),
    # M5 回缺陷（#424 主线：拆掉 confirm 档出单前的降密级判据接线）⇒ 两腿回「出单面
    # 按目标继承密级」原态：MERGE 腿 B02–B05、CONVERGE/restricted 腿 B07/B08、
    # 库层直调腿 B09、显式声明腿 B14（回「单上 private、accept 才拒」旧态）、AST 钉子
    # E07 一并转红（B01/B06/B12–B13 不受影响，证明判据面不是恒拒）。
    ("M5 回缺陷（#424）：两处档位闸调用不传 incoming_sensitivity", "md_cg/mdcos.py",
     (("                                               gate=lim,\n"
       "                                               incoming_sensitivity=_sens_eff)",
       "                                               gate=lim)"),
      ("                                                gate=verdict,\n"
       "                                                # issue #424：同 CONVERGE 支——\n"
       "                                                # 源有效密级随档位闸走（confirm 档\n"
       "                                                # 出单前的降密级判据读它）。\n"
       "                                                incoming_sensitivity=_sens_eff)",
       "                                                gate=verdict)")),
     ("B02", "B03", "B04", "B05", "B07", "B08", "B09", "B14", "E07")),
    # M6 回缺陷（#424 纵深防御：执行桥复核拆线）⇒ 伪造单（B10 场景）accept 后原语拿到
    # 单面 internal ⇒ 同档放行 ⇒ 泄漏：B10/B11 转红。
    ("M6 回缺陷（#424 纵深防御）：_mutation_execute 不读载荷 incoming_sensitivity",
     "md_cg/mdcos.py",
     (('                _mis = meta.get("incoming_sensitivity")',
       '                _mis = None                      # 变异：拆复核（#424）'),),
     ("B10", "B11")),
    # M7 过度收紧（出单前判据恒真）⇒ confirm 档同档合并被误拦：B12/B13 转红；
    # AST 钉子 E08 同步转红（merge_downgrades 调用被删）。
    ("M7 过度收紧：_autonomy_gate_merge 出单前判据恒真（误伤同档合并）", "md_cg/mdcos.py",
     (('        if _security.merge_downgrades(_tgt_sens, incoming_sensitivity):',
       '        if True:'),),
     ("B12", "B13", "E08")),
)

def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss397_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _apply_text(text, rel, pairs):
    """按目标文件实际行尾折算锚点后逐条替换；任一锚点命中数 != 1 返回 (None, 原因)。"""
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT",
              "MDCG_DATA_ROOT", "MDCG_EXPORT_ROOT", "MDCG_TOKEN_FILE"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue397_sens_eff_wiring"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐落点改回声明值（回缺陷）＋ 过度收紧，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-25:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:12]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
print("")
if FAILS:
    print("issue #397 结果：%d 失败（修前应为此态）" % len(FAILS))
else:
    print("issue #397 结果：全部通过")

