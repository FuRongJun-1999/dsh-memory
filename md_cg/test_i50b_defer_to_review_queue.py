# -*- coding: utf-8 -*-
"""md_cg · issue50-b 守卫：遗忘闸门 DEFER → 审核队列（带原文）+ 双跑去重

缺陷（编排侧复核，非推断）
--------------------------
`md_cg/mdcos.py::remember_gated` 的 DEFER 出口**只写一行 `_forgetting.jsonl`
留痕**（node_id/layer/verdict/reason/importance/entropy/actor，**不含正文**），
不调用任何入队入口——对比 DROP 分支有 `forgetting.record_drop`（留全文 +
trace_id）。审核队列的条目一律来自**另一条链**（审计/策略闸
`writepipe._gate_audit` :255、一致性闸 `_gate_consistency` :318 的
`cg.propose`）。

于是 issue50-a（半重复 → DEFER）单落会把半重复从「落成近似重复节点」改成
「**不落盘且无收件箱**」——把噪声缺陷换成静默不记缺陷。本批补这个入口。

本批修复（契约冻结）
--------------------
`remember_gated` 的 DEFER 出口接线**既有入队单点** `self.propose`
（与审计闸/一致性闸同一条链、同一 payload_hash 幂等对账）：
  · 「为何待定」写进提案的既有任意槽 `extra.defer_reason`（不新增队列字段）；
  · 密级与**调用方声明的其余 meta** 随 `**kw` 一并透传（issue50-c F1 扩面：
    此前只传 `sensitivity`，tags/condition_space/verification_basis/… 全丢）；
  · `node_id` 非字符串时兜底成内容派生 id（issue50-c F2，`_nid`）；
  · 返回体带 `proposed` = pid（可检索句柄）；
  · forgetting 留痕行**形状不变**；
  · **限流 DEFER 不入队**（语义是「先别写」，原文在 recent 时间线）；
  · gated=False 旁路、ACCEPT 后 on_conflict=defer 降级**都不入队**。

双跑面（现场读码，非照抄）
--------------------------
`writepipe.execute` 的 before 链为 linkref→deps→**audit→consistency→gated**，
任一闸返回 dict 即短路（execute :137-142）⇒ audit 判 DEFER 时 gated 根本不跑，
audit 判 ACCEPT 时 gated 才跑且 audit 未入队 ⇒ **同一次 `op=write` 至多一条
队列记录**；`mdcg_remember(gated=true)`（`mcp_server.py:3325`）**绕过整条
writepipe**，直接调 `remember_gated`，故也不双跑。此外即便双跑，`propose` 的
`payload_hash = _sig(content)` 幂等对账也会吸收（同内容不长第二条）。
本守卫的 F 组把「单次调用恰 1 条」与「writepipe 全链恰 1 条」都钉住。

断言分组（每组都在**隔离临时根**的合成库上真跑，绝不触在役数据根）
  A 修复面：半重复 DEFER → 队列恰 1 条、正文逐字可取回（jsonl 面 + review_list
    面）、layer/归因/为何待定在位、不落盘、forgetting 留痕行形状不变
  B 幂等：同内容重复写入 → 队列仍 1 条、幂等返回既有 pid
  C 裁决：accept → 正文真的落盘且逐字相等；reject → 不落盘
  D 限流 DEFER 不入队（且反向腿：knowledge 半重复仍入队）
  E gated=False 直写旁路不受影响、不入队
  F 同一次写入只产生 1 条队列记录（含 writepipe 全链）

定点变异自证（--mutate）
------------------------
每一处判据都配一个定点变异把它打红，且**恰好**命中预期红项数（`_SRC_MUTATIONS`
的 expected 列；实测计数不符即判 FAIL——照 test_neg_condition_hits.py /
test_i50a_half_dup_defer.py 同口径）。锚点漂移（实现改了却没同步本表）→ 报
ANCHOR-MISS 并 **exit 2**（fail-closed）；默认模式同样先做锚点自检。
**不以 git HEAD 为基线源**——基线绑提交即失效（本仓已有两次教训），变异一律
作用在**当前盘的实现**上。

运行：python -X utf8 -m md_cg.test_i50b_defer_to_review_queue
      python -X utf8 -m md_cg.test_i50b_defer_to_review_queue --mutate
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import shutil
import sys
import tempfile

# 三档自治批次②（2026-10-02）**夹具隔离**：本守卫考的不是档位面（档位守卫 =
# md_cg/test_autonomy_modes.py），故显式置 full 档——回到改动前「动作直落」的
# 行为，使本文件的断言意图（合并/覆写/软删真的发生）逐条不变；env 键名从唯一
# 真源表取（本文件不构成第二处字面量）。
from . import autonomy_modes as _autonomy_modes          # noqa: E402
os.environ[_autonomy_modes.AUTONOMY_ENV_KEYS["mode"]] = "full"

from . import writelimit
from .mdcos import MdCGOS, MdCGSecure
from .security import Principal
from .writepipe import default_pipeline

_PASS = []
_FAIL = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


# ---------------------------------------------------------------- 夹具构造
# 与 test_i50a_half_dup_defer.py 同一套夹具口径：600 个互异汉字作基线正文、
# 另 600 个互异汉字作全新填充，前 k 字的覆盖比例即重复度（实测 k=360 → dup
# 0.6078、k=436 → 0.7310、k=503 → 0.8395，三处分别落在 DUP_DROP 侧、中部、
# 贴近 DUP_MERGE）。
BASE = "".join(chr(0x4e00 + i) for i in range(600))
FILL = "".join(chr(0x8000 + i) for i in range(600))
T_BASE, T_NEW = "基线节点标题", "新写入标题"

K_EDGE = 360        # dup ≈ 0.6078（刚好越过 DUP_DROP）
K_HALF = 436        # dup ≈ 0.7310
K_TOP = 503         # dup ≈ 0.8395（贴近 DUP_MERGE 但未到）


# 生效条件：title 与 body 给定时按本仓 CCG 六要素模板拼出节点正文（模板行两侧
# 一致，故不成为重复度的差量来源）；无输入校验，参数缺失即抛 TypeError。
def _doc(title, body):
    return ("# 功能名：%s\n# 生效条件：任意情境\n# 子功能：验收\n"
            "# 执行：直接调用\n# 验证方式：test\n# 不适用条件：无\n%s\n"
            % (title, body))


# 生效条件：k 为整数下标；返回「前 k 字取自 BASE、其余取自 FILL」的新正文。
def _mixed(k):
    return BASE[:k] + FILL[:len(BASE) - k]


# 生效条件：sess 为真值时作为会话归属，否则用固定串；返回 designer-cli 形态的
# 本地身份（与 review_cli._cg 同一构造口径：clearance=secret / can_admin /
# role=designer / auth_mode=local-cli）——队列面的 review_list / review_decide
# 需要 review op 与 can_admin，本守卫因此不触在役库、只用临时根。
def _princ(sess="sess-i50b"):
    return Principal(tenant="t1", actor="designer-cli", clearance="secret",
                     can_write=True, can_admin=True, role="designer",
                     auth_mode="local-cli", session=sess)


# 生效条件：无输入；在系统临时目录下新建隔离根并构造 MdCGSecure（autoflush=1，
# 与 server/CLI 同款可见性兜底），退出时先 close()（落索引/关分片句柄，免
# atexit 兜底再去碰已删的根）再无条件递归删除该根（异常路径也删）。
@contextlib.contextmanager
def _lib(sess="sess-i50b"):
    root = tempfile.mkdtemp(prefix="i50b_")
    cg = None
    try:
        cg = MdCGSecure(root, principal=_princ(sess), autoflush=1)
        yield cg
    finally:
        with contextlib.suppress(Exception):
            if cg is not None:
                cg.close()
        shutil.rmtree(root, ignore_errors=True)


# 生效条件：cg 有 inbox_log 属性；返回其 JSONL 全记录（文件不存在或空行即空
# 列表）；单行畸形按跳过处理，不抛。
def _inbox(cg):
    p = getattr(cg, "inbox_log", None)
    if not p or not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


# 生效条件：cg 有 root 属性；返回 `_forgetting.jsonl` 里 node_id 等于 nid 的
# 最后一条记录（无则空 dict）。
def _forget_rec(cg, nid):
    p = os.path.join(cg.root, "_forgetting.jsonl")
    if not os.path.exists(p):
        return {}
    hit = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("node_id") == nid:
                hit = rec
    return hit


# 生效条件：k 给定时在隔离根建「基线节点 + 一条半重复写入」；产出 (cg, out,
# content)。基线层与新写层同为 layer（缺省 knowledge：无 writelimit 介入，只
# 走 forgetting 闸），role 缺省 user（外部惊奇来源），hint 缺省 0.60（插件缺省
# 形态）。退出时删根。
@contextlib.contextmanager
def _half_dup_case(k, nid="w", hint=0.60, layer="knowledge", role="user"):
    root = tempfile.mkdtemp(prefix="i50b_case_")
    cg = None
    try:
        cg = MdCGSecure(root, principal=_princ(), autoflush=1)
        cg.add("base", _doc(T_BASE, BASE), layer=layer, importance=0.5,
               role=role)
        content = _doc(T_NEW, _mixed(k))
        out = cg.remember_gated(nid, content, layer=layer, role=role,
                                gated=True, importance_hint=hint)
        yield cg, out, content
    finally:
        with contextlib.suppress(Exception):
            if cg is not None:
                cg.close()
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- A 修复面
def g_a():
    print("== A 遗忘 DEFER → 正文进审核队列 ==")
    with _half_dup_case(K_HALF) as (cg, out, content):
        dup = ((out.get("gate") or {}).get("redundancy") or {}).get("max")
        ok(out.get("verdict") == "DEFER" and 0.60 <= (dup or 0) < 0.85,
           "A1 半重复 + hint=0.60 → DEFER（dup=%.4f）" % (dup or -1),
           out.get("verdict"))
        recs = _inbox(cg)
        ok(len(recs) == 1, "A2 审核队列恰 1 条", len(recs))
        rec = recs[0] if recs else {}
        ok(rec.get("id") == "w", "A3 队列条目的 node_id 即本次节点", rec.get("id"))
        ok(rec.get("content") == content,
           "A4 队列面正文与原文**逐字相等**（含换行/空白）")
        ok(rec.get("layer") == "knowledge", "A5 队列条目 layer 随写入",
           rec.get("layer"))
        why = ((rec.get("extra") or {}).get("defer_reason") or "")
        ok(("遗忘闸门" in why and "半重复" in why and "base" in why),
           "A6 「为何待定」在位且含重复对象 id（extra.defer_reason）", why)
        ok(rec.get("sensitivity") == "internal",
           "A7 密级随 sensitivity 透传（不静默降级）", rec.get("sensitivity"))
        ok(cg.get("w") is None, "A8 DEFER 不落盘")
        lg = _forget_rec(cg, "w")
        ok(lg.get("verdict") == "DEFER" and "reason" in lg and "importance" in lg
           and "entropy" in lg and "actor" in lg and "limiter" not in lg,
           "A9 forgetting 留痕行仍在且形状不变（无 limiter 键）", sorted(lg))
        ok(bool(out.get("proposed")) and out.get("proposed") == rec.get("pid"),
           "A10 返回体 proposed == 队列 pid（可检索句柄）",
           (out.get("proposed"), rec.get("pid")))
        vis = [r for r in cg.review_list() if r.get("content") == content]
        ok(len(vis) == 1 and vis[0].get("id") == "w",
           "A11 **队列读面**（review_list）同样能取回该正文")


# ---------------------------------------------------------------- B 幂等
def g_b():
    print("== B 幂等：同内容重复写入不长第二条 ==")
    with _half_dup_case(K_HALF) as (cg, out1, content):
        pid1 = out1.get("proposed")
        out2 = cg.remember_gated("w2", content, layer="knowledge", role="user",
                                 gated=True, importance_hint=0.60)
        recs = _inbox(cg)
        ok(out2.get("verdict") == "DEFER",
           "B1 同内容再写（换 node_id）仍判 DEFER", out2.get("verdict"))
        ok(len(recs) == 1, "B2 队列仍 1 条（payload_hash 幂等对账）", len(recs))
        ok(bool(pid1) and out2.get("proposed") == pid1,
           "B3 幂等返回既有 pid（同一单点）", (out2.get("proposed"), pid1))
        ok(len([r for r in recs if r.get("content") == content]) == 1,
           "B4 队列里该内容的记录恰 1 条")


# ---------------------------------------------------------------- C 裁决
def g_c():
    print("== C 裁决：accept 落盘 / reject 不落盘 ==")
    with _half_dup_case(K_EDGE) as (cg, out, content):
        pid = out.get("proposed")
        acc = cg.review_decide(pid, "accept", reason="i50b 守卫")
        ok(bool(acc.get("ok")), "C1 队列裁定 accept 返回 ok", acc)
        node = cg.get("w")
        ok(node is not None, "C2 accept 后正文真的落盘")
        ok((node or {}).get("content") == content,
           "C3 落盘正文与原文逐字相等")
    with _half_dup_case(K_TOP) as (cg, out, content):
        pid = out.get("proposed")
        rej = cg.review_decide(pid, "reject", reason="i50b 守卫")
        ok(bool(rej.get("ok")), "C4 队列裁定 reject 返回 ok", rej)
        ok(cg.get("w") is None, "C5 reject 后不落盘")


# ---------------------------------------------------------------- D 限流
def g_d():
    print("== D 限流 DEFER 不入队（语义是先别写，不是内容待定）==")
    with _lib() as cg:
        writelimit._save(cg, {"sigs": {}, "rate": {}})
        for i in range(8):
            cg.remember_gated("rl%d" % i, "盘点条目甲乙丙丁戊%d号" % i,
                              layer="contextual", role="user", gated=True)
        rl = cg.remember_gated("rl9", "盘点条目甲乙丙丁戊9号",
                               layer="contextual", role="user", gated=True)
        g = rl.get("gate") or {}
        ok(rl.get("verdict") == "DEFER" and "ratelimit" in (g.get("reason") or ""),
           "D1 窗口超量 → 限流 DEFER", g.get("reason"))
        ok(not rl.get("proposed"),
           "D2 限流 DEFER 不带 proposed（不入队）", rl.get("proposed"))
        ok(len(_inbox(cg)) == 0, "D3 队列 0 条")
        lg = _forget_rec(cg, "rl9")
        ok(bool(lg.get("limiter")), "D4 限流留痕照旧（limiter 键在位）",
           sorted(lg))
        cg.add("base", _doc(T_BASE, BASE), layer="knowledge", importance=0.5,
               role="user")
        r2 = cg.remember_gated("w", _doc(T_NEW, _mixed(K_HALF)),
                               layer="knowledge", role="user", gated=True,
                               importance_hint=0.60)
        ok(r2.get("verdict") == "DEFER" and len(_inbox(cg)) == 1,
           "D5 反向腿：knowledge 半重复 DEFER 仍入队 1 条",
           (r2.get("verdict"), len(_inbox(cg))))


# ---------------------------------------------------------------- E 旁路
def g_e():
    print("== E gated=False 直写旁路不受影响 ==")
    with _lib() as cg:
        out = cg.remember_gated("byp", _doc(T_NEW, BASE), layer="knowledge",
                                role="user", gated=False)
        ok(out.get("verdict") == "ACCEPT" and out.get("bypass") is True,
           "E1 旁路 verdict=ACCEPT / bypass=True", out.get("verdict"))
        ok(cg.get("byp") is not None, "E2 旁路正文真的落盘")
        ok(len(_inbox(cg)) == 0, "E3 旁路不进审核队列")
        ok("proposed" not in out, "E4 旁路返回体无 proposed 键", sorted(out))


# ---------------------------------------------------------------- F 双跑
def g_f():
    print("== F 同一次写入只产生 1 条队列记录（双跑去重）==")
    with _half_dup_case(K_HALF) as (cg, out, content):
        ok(len(_inbox(cg)) == 1, "F1 单次 gated 调用 → 恰 1 条",
           len(_inbox(cg)))
    root = tempfile.mkdtemp(prefix="i50b_wp_")
    try:
        cg = MdCGSecure(root, principal=_princ("sess-wp"), autoflush=1)
        cg.add("p0", _doc(T_BASE, BASE), layer="knowledge", importance=0.5,
               role="user")
        content = _doc(T_NEW, _mixed(K_HALF))
        out = default_pipeline().execute(cg, {
            "node_id": "p0_w", "content": content, "layer": "knowledge",
            "role": "user", "content_kind": "text", "gated": True})
        gate = out.get("gate") or {}
        ok(gate.get("verdict") == "DEFER",
           "F2 writepipe 全链（audit ACCEPT → gated DEFER）判 DEFER",
           gate.get("verdict"))
        recs = _inbox(cg)
        ok(len(recs) == 1,
           "F3 writepipe 全链 → 队列恰 1 条（audit 未在 ACCEPT 时入队、不双跑）",
           len(recs))
        ok(len([r for r in recs if r.get("content") == content]) == 1,
           "F4 队列里该内容的记录恰 1 条")
        ok(bool(gate.get("proposed")),
           "F5 writepipe 返回体保留了入队 pid（gate.proposed）",
           gate.get("proposed"))
    finally:
        with contextlib.suppress(Exception):
            cg.close()
        shutil.rmtree(root, ignore_errors=True)


_GROUPS = (g_a, g_b, g_c, g_d, g_e, g_f)


def _run_fails():
    """跑全部断言组（静默），返回失败断言名列表——供变异自证复用。"""
    _PASS.clear()
    _FAIL.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        for g in _GROUPS:
            g()
    return list(_FAIL)


def _run_groups():
    return len(_run_fails())


# ---------------------------------------------------------------- 定点变异自证
# 表内每项 = (说明, 锚点原文, 替换文, 预期红项数)。锚点必须**逐字**出现在当前
# `MdCGOS.remember_gated` 的源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。
# issue50-c F1 后入队单点把调用方 meta 一并透传（`**kw`）；F2 后 node_id 走
# 内容派生兜底（`_nid`）。锚点随实现同步，判据（红项数）不变。
_PROPOSE_BLOCK = ('            out["proposed"] = self.propose(\n'
                  '                _nid, content, layer=layer, **kw, '
                  'defer_reason=_why)')

_SRC_MUTATIONS = (
    # ① 契约指定：DEFER 出口不接线（入队单点整个摘掉）。实测红项 20：
    # A1/A8/A9 三条不依赖队列的判据仍绿，其余 A2-A7/A10/A11（8）+ B2-B4（3）
    # + C1-C4（4；C5「reject 不落盘」在无提案时反而为真）+ D5（1）
    # + F1/F3/F4/F5（4）= 20。
    ("DEFER 出口不接线（删掉 propose 调用）",
     _PROPOSE_BLOCK,
     '            out["proposed"] = None',
     20),
    # ② 契约指定：入队正文传成空串——「正文可取回」那几条必红。实测红项 5：
    # A4/A11（逐字比对）+ B4 + C3 + F4——**所有「队列恰 1 条」类计数断言不红**
    # （空串也是 1 条），这正是本变异要区分的：它只钉住「正文」而非「条数」。
    ("入队正文传成空串（正文可取回必红）",
     _PROPOSE_BLOCK,
     '            out["proposed"] = self.propose(\n'
     '                _nid, "", layer=layer, **kw, defer_reason=_why)',
     5),
    # ③ 限流 DEFER 也入队（违背「先别写」语义）——D2/D3/D5 必红（实测 3）。
    ("限流 DEFER 也入队（违背先别写语义）",
     '            else:                                    # DEFER\n'
     '                out = {"verdict": "DEFER", "node_id": node_id,\n'
     '                       "gate": lim}\n'
     '                fv = "DEFER"',
     '            else:                                    # DEFER\n'
     '                out = {"verdict": "DEFER", "node_id": node_id,\n'
     '                       "gate": lim}\n'
     '                fv = "DEFER"\n'
     '                out["proposed"] = self.propose(node_id, content,\n'
     '                                               layer=layer)',
     3),
    # ④ gated=False 旁路也入队——E3 必红（实测 1）。
    ("gated=False 旁路也入队",
     '        if not gated:\n'
     '            return {"verdict": "ACCEPT", "bypass": True, "gate": None,',
     '        if not gated:\n'
     '            self.propose(node_id, content, layer=layer)\n'
     '            return {"verdict": "ACCEPT", "bypass": True, "gate": None,',
     1),
    # ⑤ 模拟「双跑」：第二条入队带零宽字符绕开 payload_hash 幂等。**为何要绕**：
    # 纯重复调用会被 propose 自己的对账吸收（第二次不落行），打不红 F——这本身
    # 就是本批「双跑不致双条」的第二道防线（见模块 docstring）。本变异一次写入
    # 长出两条队列记录 ⇒ F1/F3（恰 1 条）与 B2、D5 同类计数据必红（实测 5：
    # A2、B2、D5、F1、F3）。
    ("双跑（第二路绕开幂等键）",
     _PROPOSE_BLOCK,
     _PROPOSE_BLOCK + '\n'
     '            self.propose(node_id, content + "\\u200b", layer=layer,\n'
     '                         defer_reason=_why)',
     5),
    # ⑥ DEFER 不再写 forgetting 留痕（违背契约③「留痕行形状不变」）——A9 必红。
    ("DEFER 不写 forgetting 留痕",
     '        if v != "DROP":',
     '        if v not in ("DROP", "DEFER"):',
     1),
    # ⑦ 「为何待定」文案清空——A6 必红。
    ("defer_reason 文案清空",
     '            _why = "遗忘闸门：" + str(verdict.get("reason") or "待定复核")',
     '            _why = ""',
     1),
)

# 静态锚点（默认模式也自检，fail-closed）：
#   · 入队单点必须**仍是 self.propose**（不得被换成另一套入队实现）
#   · DEFER 分支必须在位，且限流 DEFER 出口不得带 propose
_ANCHORS_REQUIRED = (
    'out["proposed"] = self.propose(',
    'layer=layer, **kw, defer_reason=_why)',
    'elif v == "DEFER":',
)
_ANCHORS_BANNED = (
    # 限流 DEFER 出口旁出现 propose ⇒ 违契约④
    '"gate": lim}\n                fv = "DEFER"\n                out["proposed"]',
)


def _gated_src():
    return inspect.getsource(MdCGOS.remember_gated)


def _anchor_check():
    """返回 ANCHOR-MISS 说明列表（空 = 全部在位）。"""
    src = _gated_src()
    bad = []
    for name, old, _new, _n in _SRC_MUTATIONS:
        if old not in src:
            bad.append("变异锚点缺失：%s（锚点 %r）" % (name, old[:60]))
    for s in _ANCHORS_REQUIRED:
        if s not in src:
            bad.append("必需锚点缺失：%r" % s)
    for s in _ANCHORS_BANNED:
        if s in src:
            bad.append("禁用锚点回归（限流 DEFER 被接线）：%r" % s)
    return bad


# 生效条件：old 与 new 给定时，取当前 MdCGOS.remember_gated 的源码做字面替换，
# 以 mdcos 的模块 globals 副本 exec 出新函数；返回该函数对象（不落盘、不改源文件）。
# 方法体在类里缩进 4 格，故用 `if True:` 前缀承接（不用 dedent，避免空白行被
# textwrap 归一后与表内锚点错位）。
def _mutate_src(old, new):
    ns = dict(vars(sys.modules[MdCGOS.__module__]))
    exec(compile("if True:\n" + _gated_src().replace(old, new),
                 "i50b_mut.py", "exec"), ns)
    return ns["remember_gated"]


def _with_patched(fn, run):
    """把 MdCGOS.remember_gated 临时换成 fn 跑一遍 run()，finally 原样还原。"""
    live = MdCGOS.remember_gated
    MdCGOS.remember_gated = fn
    try:
        return run()
    finally:
        MdCGOS.remember_gated = live


def _mutate_mode():
    bad = []
    anchor_bad = _anchor_check()
    if anchor_bad:
        for b in anchor_bad:
            print("  ANCHOR-MISS " + b)
        print("\n锚点自检：FAIL（fail-closed，exit 2）")
        return 2
    clean = _run_groups()
    print("  未变异基线：红项=%d%s"
          % (clean, "" if clean == 0 else "  ← 基线即红，变异核验无意义"))
    if clean:
        bad.append("未变异基线即失败")
    for name, old, new, expect in _SRC_MUTATIONS:
        fails = _with_patched(_mutate_src(old, new), _run_fails)
        verdict = ("命中预期" if len(fails) == expect
                   else "**红项数不符（预期 %d）**" % expect)
        print("  变异「%s」→ 红项=%d  %s" % (name, len(fails), verdict))
        if len(fails) != expect:
            bad.append(name)
            print("      实际红项：" + "、".join(fails))
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都有变异钉死，且红项数逐处吻合）"
             if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    src = os.path.basename(os.path.abspath(__file__))
    if "--mutate" in sys.argv:
        print("!! 定点变异模式：逐个变异判据，套件应转红且红项数吻合\n")
        return _mutate_mode()
    anchor_bad = _anchor_check()
    if anchor_bad:
        for b in anchor_bad:
            print("  ANCHOR-MISS " + b)
        print("\n锚点自检：FAIL（fail-closed，exit 2）——实现改了请同步变异表/文案")
        return 2
    print("锚点自检：PASS（%s；不以 git HEAD 为基线源）" % src)
    for g in _GROUPS:
        g()
    print("\nissue50-b 守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：" + "、".join(_FAIL))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
