# -*- coding: utf-8 -*-
"""md_cg · issue50-c 守卫：DEFER→accept 的元数据完整性（F1）+ node_id=None 捩点（F2）

缺陷（编排侧复核实测，非推断）
------------------------------
F1（扩面修）`md_cg/mdcos.py::remember_gated` 的 DEFER 出口接线入队时**只传
content/layer/sensitivity**（issue50-b 接线），调用方声明的其余 meta 全丢：
`tags` / `condition_space` / `verification_basis` / `non_applicable_conditions` /
`derived_from` / `relation`（以及 `role`）。accept 只能从队列记录取值，于是
**同一声明**下「DEFER→经队列 accept 落盘」的节点比「直接 ACCEPT」少掉这些键
（实测 tags 为 [] 而对面有值、derived_from 缺失、bucket_zh 因 tags 空而不生成）
——同一份声明的两条落地路径**元数据不等价**。

F2（捩点收口）`remember_gated(None, 半重复内容, …)` 现行会崩：新 DEFER 分支里
`propose` 造 pid 时拼接 `node_id + str(time.time())` ⇒
`TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'`。生产入口经
`mint_auto_id` 兜底故不可达，但「静默 → 抛异常」是新引入的面。

本批修复（契约冻结）
--------------------
F1：入队时把本闸收到的 meta 一并落进队列记录——`**kw` 交给 `self.propose`
（其形参 `tags`/`condition_space`/`sensitivity`/`verify` 落 rec 专属槽，其余键落
`extra`），口径与直接 ACCEPT 的 `add(**kw)` **同源**；accept 分支既有的
`tags=` / `condition_space=` / `**extra` 映射即把它写回节点 fm。不新增队列字段，
不改队列裁决动词，`review_decide` **零行为改动**（其 accept 映射早已在位）。
F2：`node_id` 非字符串时按仓内既有形态兜底成**内容派生 id**
（`forgetting._prefeed_id` 同款，`pre_<sha1[:12]>`），不崩且非静默（返回体
`proposed_id_fallback` 如实标注；**不进** forgetting 留痕行——该行形状由
issue50-b 冻结）。

两路对拍口径（本守卫的 A/B 组）
-------------------------------
同一声明（同一 `tags`/`condition_space`/`verification_basis`/
`non_applicable_conditions`/`derived_from`/`relation`/`role`/`importance`）跑两个
**隔离临时根**（同名节点 `n`）：一路内容全新 ⇒ 直接 ACCEPT；另一路内容与基线半
重复（dup≈0.73）⇒ DEFER ⇒ 入队 ⇒ `review_decide(accept)`。逐键对拍两个节点的
frontmatter。`importance` 用显式 `importance=`（而非 `importance_hint=`）传入，
使两条路径的 fm.importance 同源——「裁决用与落盘记的重要度不同源」是**另有裁定**
的独立问题，本批不动、也不靠本守卫混淆。

白名单（B 组逐键读数的允许差异，每条附理由）
--------------------------------------------
  · `defer_reason` —— issue50-b 引入的「为何待定」文案，**仅 DEFER 路有**
    （契约已裁定接受，本批保持现状）。
  · `reviewer`   —— accept 路径的裁决归属留痕（mdcos.py:2565-2567）。硬边界
    ②「不许削弱 review_decide 既有职责」⇒ 不可为「对齐」而删；直接 ACCEPT 路
    不经裁决，本就没有。
  · `created_at` —— 写入时刻时间戳（时间轴锚点）：直接路写入即落盘、DEFER 路
    裁决 accept 时才落盘，两次时刻必然不同；**非调用方声明的 meta**。
  · `condition_space` —— 仅其**派生**键 `time_window`（= created_at 起算，
    add :2225）随之变；其余键必须逐位相等（B3 单列）。其余三个白名单项之外的
    任何差异必须为 0（B1 逐行读数，不是结论）。

断言分组（全部在**隔离临时根**的合成库上真跑，绝不触在役数据根）
  A 修复面：DEFER→accept 节点的声明 meta 与直接 ACCEPT 路**逐位相等**（六键
    点名 + role/derived_relation/bucket_zh 佐证；并证「两路都有」而非「两路都缺」）
  B 白名单外差异为 0（逐键对拍表 + 白名单恰 4 条 + 缺键为 0 + cs 非 time_window 键相等）
  C `node_id=None` 不抛异常且行为可辨（DEFER / 入队 / 内容派生 id / 如实标注 / accept 闭环）
  D 裁决既有职责不削弱（幂等对账、自验违例、reject/noop 不落盘、merge 并集、留痕）

定点变异自证（--mutate）
------------------------
每一处判据都配一个定点变异把它打红，且**恰好**命中预期红项数（`_MUTATIONS`
的 expected 列；实测计数不符即判 FAIL——与 test_neg_condition_hits.py /
test_i50a / test_i50b 同口径）。锚点必须**逐字**出现在当前盘实现的源码里；漂移
即 ANCHOR-MISS 并 **exit 2**（fail-closed，默认模式同样先自检）。
**不以 git HEAD 为基线源**——基线绑提交即失效（本仓已有两次教训）；变异一律
作用在**当前盘的实现**上。

运行：python -X utf8 -m md_cg.test_i50c_meta_passthrough
      python -X utf8 -m md_cg.test_i50c_meta_passthrough --mutate
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

from . import forgetting
from .mdcos import MdCGOS, MdCGSecure
from .security import Principal

_PASS = []
_FAIL = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


# ---------------------------------------------------------------- 夹具构造
# 与 test_i50a / test_i50b 同一套夹具口径：600 个互异汉字作基线正文，另 600 个
# 互异汉字作填充；前 k 字的覆盖比例即重复度（k=436 → dup≈0.73，落在
# DUP_DROP=0.60 与 DUP_MERGE=0.85 之间 ⇒ 分支④ DEFER）。
BASE = "".join(chr(0x4e00 + i) for i in range(600))
FILL = "".join(chr(0x8000 + i) for i in range(600))
NOVEL = "".join(chr(0x9000 + i) for i in range(600))
T_BASE, T_NEW = "基线节点标题", "新写入标题"
K_HALF = 436
NID = "n"                       # 两个隔离根用**同一个**节点 id，使 fm.id 不成为差异源

# 同一声明（两路逐字相同）。`relation` 取非缺省值 refined_from——缺省值恰等于
# provenance.DEFAULT_RELATION，无法区分「relation 生效」与「走了缺省」。
META = dict(tags=["标签甲", "标签乙"],
            condition_space={"observation_position": "pos-x"},
            verification_basis="test",
            non_applicable_conditions=["不适用甲", "不适用乙"],
            derived_from=["base"],
            relation="refined_from",
            role="user",
            importance=0.5)

_ABSENT = object()


# 生效条件：title 与 body 给定时按本仓 CCG 六要素模板拼出节点正文（模板行两侧
# 一致，故不成为重复度差量来源）；无输入校验，参数缺失即抛 TypeError。
def _doc(title, body):
    return ("# 功能名：%s\n# 生效条件：任意情境\n# 子功能：验收\n"
            "# 执行：直接调用\n# 验证方式：test\n# 不适用条件：无\n%s\n"
            % (title, body))


# 生效条件：k 为整数下标；返回「前 k 字取自 BASE、其余取自 FILL」的新正文。
def _mixed(k):
    return BASE[:k] + FILL[:len(BASE) - k]


# 生效条件：sess 为真值时作为会话归属；返回 designer-cli 形态的本地身份
# （clearance=secret / can_admin / role=designer / auth_mode=local-cli）——队列面
# 的 review_list / review_decide 需要 review op 与 can_admin，故本守卫只用临时根。
def _princ(sess="sess-i50c"):
    return Principal(tenant="t1", actor="designer-cli", clearance="secret",
                     can_write=True, can_admin=True, role="designer",
                     auth_mode="local-cli", session=sess)


# 生效条件：cg 有 inbox_log 属性；返回其 JSONL 全记录（不存在或空行即空列表）；
# 单行畸形按跳过处理，不抛。
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


# 生效条件：mode ∈ {"direct","defer"}；在系统临时目录新建隔离根，建基线节点
# base 并按 mode 写入同名节点 NID（direct=全新内容⇒ACCEPT；defer=半重复⇒DEFER
# 且经 review_decide(accept) 落盘）。产出 (fm, out, content, accept_result)；
# 退出时先 close() 再无条件删根（异常路径也删）。
@contextlib.contextmanager
def _case(mode):
    root = tempfile.mkdtemp(prefix="i50c_%s_" % mode)
    cg = None
    try:
        # 两个根用**同一**会话串：会话归属同为「同一声明」的一部分，不引入
        # 与被测修复无关的 fm.session 差异源。
        cg = MdCGSecure(root, principal=_princ("sess-i50c"), autoflush=1)
        cg.add("base", _doc(T_BASE, BASE), layer="knowledge", importance=0.5,
               role="user")
        content = _doc(T_NEW, NOVEL if mode == "direct" else _mixed(K_HALF))
        out = cg.remember_gated(NID, content, layer="knowledge", **META)
        acc = None
        if mode == "defer" and out.get("proposed"):
            acc = cg.review_decide(out["proposed"], "accept", reason="i50c 守卫")
        fm = dict(((cg.get(NID) or {}).get("frontmatter")) or {})
        yield fm, out, content, acc
    finally:
        with contextlib.suppress(Exception):
            if cg is not None:
                cg.close()
        shutil.rmtree(root, ignore_errors=True)


# 生效条件：无输入；返回 (fm_direct, fm_defer, out_direct, out_defer, acc_defer)。
def _pair():
    with _case("direct") as (fd, od, _c1, _a1):
        pass
    with _case("defer") as (fz, oz, _c2, az):
        pass
    return fd, fz, od, oz, az


# 白名单（键 → 理由）。B 组要求 diff ⊆ 本表，且条目数恰 4。
_WHITELIST = {
    "defer_reason": "issue50-b 的「为何待定」文案，仅 DEFER 路有（契约已裁定接受）",
    "reviewer": "accept 路径的裁决归属留痕（mdcos.py:2571-2572）；硬边界②不许削弱",
    "created_at": "写入时刻时间戳：直接路写入即落盘 / DEFER 路裁决 accept 时落盘",
    "condition_space": "仅派生键 time_window（= created_at 起算）随之变；其余键见 B3",
}

# 契约点名的六个声明键 → 直接 ACCEPT 路应落在的那些 fm 键。
_NAMED = (("tags", "tags"),
          ("condition_space", "condition_space"),
          ("verification_basis", "verification_basis"),
          ("non_applicable_conditions", "non_applicable_conditions"),
          ("derived_from", "derived_from"),
          ("relation", "derived_relation"))
# 佐证键（同一声明的其余 meta 也应等价；`derived_relation` 已随 `_NAMED` 的
# relation 检查，不重复计）。
_EXTRA_KEYS = ("role", "bucket_zh")


# ---------------------------------------------------------------- A 修复面
def g_a():
    print("== A 修复面：DEFER→accept 的声明 meta 与直接 ACCEPT 逐位相等 ==")
    fd, fz, od, oz, az = _pair()
    ok(od.get("verdict") == "ACCEPT" and bool(od.get("written")),
       "A0 对照路（全新内容）verdict=ACCEPT 且已落盘", od.get("verdict"))
    ok(oz.get("verdict") == "DEFER" and bool(oz.get("proposed")),
       "A0b 被测路（半重复）verdict=DEFER 且已入队", oz.get("verdict"))
    ok(bool(az and az.get("ok")), "A0c DEFER 提案 accept 成功", az)
    # 契约点名的六键：必须**在位且相等**（同时防「两路都缺」的假等价）。
    # condition_space 按「除派生 time_window 外」比较（该键是写入时刻的函数，
    # 见白名单；其非 time_window 部分必须逐位相等，故这里要求非空）。
    for want, key in _NAMED:
        if key == "condition_space":
            va = {k: v for k, v in (fz.get(key) or {}).items()
                  if k != "time_window"}
            vb = {k: v for k, v in (fd.get(key) or {}).items()
                  if k != "time_window"}
            ok(key in fz and key in fd and bool(vb) and va == vb,
               "A1[%s] 在位且逐位相等（除派生 time_window）" % want,
               (key in fz, key in fd, va, vb))
            continue
        # relation 经 add 落到 fm.derived_relation；其余同名。
        ok(key in fz and key in fd and fz.get(key) == fd.get(key),
           "A1[%s] 在位且逐位相等" % want,
           (key in fz, key in fd, fz.get(key), fd.get(key)))
    for key in _EXTRA_KEYS:
        ok(key in fz and key in fd and fz.get(key) == fd.get(key),
           "A3[%s] 佐证键在位且逐位相等" % key,
           (key in fz, key in fd, fz.get(key), fd.get(key)))


# ---------------------------------------------------------------- B 白名单
def g_b():
    print("== B 白名单外差异为 0（逐键对拍表）==")
    fd, fz, _od, _oz, _az = _pair()
    keys = sorted(set(fd) | set(fz))
    print("  %-28s | %-34s | %-34s | %s" % ("fm 键", "直接 ACCEPT", "DEFER→accept", "判定"))
    print("  " + "-" * 112)
    diff = []
    for k in keys:
        va, vb = fd.get(k, _ABSENT), fz.get(k, _ABSENT)
        same = va == vb
        if not same:
            diff.append(k)
        sa = "<absent>" if va is _ABSENT else json.dumps(va, ensure_ascii=False, default=str)
        sb = "<absent>" if vb is _ABSENT else json.dumps(vb, ensure_ascii=False, default=str)
        if len(sa) > 32:
            sa = sa[:29] + "..."
        if len(sb) > 32:
            sb = sb[:29] + "..."
        print("  %-28s | %-34s | %-34s | %s"
              % (k, sa, sb, "同" if same else ("白名单" if k in _WHITELIST else "**差异**")))
    outside = [k for k in diff if k not in _WHITELIST]
    ok(not outside, "B1 白名单外的 fm 差异为 0（逐行读数）", outside)
    only_direct = [k for k in keys if k in fd and k not in fz]
    ok(not only_direct, "B2 DEFER 路不缺任何 fm 键（无 only-in-DIRECT）", only_direct)
    cs_z = {k: v for k, v in (fz.get("condition_space") or {}).items()
            if k != "time_window"}
    cs_d = {k: v for k, v in (fd.get("condition_space") or {}).items()
            if k != "time_window"}
    ok(cs_z == cs_d and bool(cs_d),
       "B3 condition_space 的差异**仅限**派生的 time_window", (cs_z, cs_d))
    tw_z = (fz.get("condition_space") or {}).get("time_window")
    tw_d = (fd.get("condition_space") or {}).get("time_window")
    ok(isinstance(tw_z, list) and isinstance(tw_d, list) and len(tw_z) == 2
       and len(tw_d) == 2 and float(tw_z[0]) >= float(tw_d[0]),
       "B4 time_window 确为两次写入时刻（差异真实存在，非被掩盖）",
       (tw_d, tw_z))
    ok(len(_WHITELIST) == 4 and all(k in diff for k in _WHITELIST),
       "B5 白名单恰 4 条且每条都真实命中（无空挂）", (len(_WHITELIST), diff))


# ---------------------------------------------------------------- C None 捩点
def g_c():
    print("== C node_id=None 捩点收口（不崩、不静默）==")
    root = tempfile.mkdtemp(prefix="i50c_none_")
    cg = None
    try:
        cg = MdCGSecure(root, principal=_princ("sess-i50c-none"), autoflush=1)
        cg.add("base", _doc(T_BASE, BASE), layer="knowledge", importance=0.5,
               role="user")
        content = _doc(T_NEW, _mixed(K_HALF))
        try:
            out = cg.remember_gated(None, content, layer="knowledge", **META)
            exc = None
        except Exception as e:               # 改前此处为 TypeError
            out, exc = {}, e
        ok(exc is None, "C1 node_id=None 不抛异常（改前 TypeError）", repr(exc))
        ok(out.get("verdict") == "DEFER", "C2 半重复仍判 DEFER", out.get("verdict"))
        ok(out.get("node_id") is None,
           "C3 返回体 node_id 原样为 None（不伪装成派生 id）", out.get("node_id"))
        exp = forgetting._prefeed_id(content)
        recs = [r for r in _inbox(cg) if r.get("content") == content]
        ok(len(recs) == 1 and recs[0].get("id") == exp and exp.startswith("pre_"),
           "C4 仍入队且条目 id = 内容派生 id（forgetting._prefeed_id 同款）",
           (len(recs), (recs[0].get("id") if recs else None), exp))
        ok(bool(out.get("proposed")) and out.get("proposed") == (recs[0].get("pid") if recs else None),
           "C5 返回体 proposed == 队列 pid（收件箱不因缺 id 而丢）", out.get("proposed"))
        ok(out.get("proposed_id_fallback") == exp,
           "C6 兜底事实在返回体如实标注（非静默）", out.get("proposed_id_fallback"))
        acc = cg.review_decide(out.get("proposed"), "accept", reason="i50c 守卫")
        ok(bool(acc and acc.get("ok")) and acc.get("node_id") == exp
           and cg.get(exp) is not None and (cg.get(exp) or {}).get("content") == content,
           "C7 accept 后落盘节点 id 即派生 id 且正文逐字相等（闭环可用）", acc)
    finally:
        with contextlib.suppress(Exception):
            if cg is not None:
                cg.close()
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- D 既有职责
def g_d():
    print("== D 裁决既有职责不削弱（本批扩面的边界）==")
    root = tempfile.mkdtemp(prefix="i50c_duty_")
    cg = None
    try:
        cg = MdCGSecure(root, principal=_princ("sess-i50c-duty"), autoflush=1)
        cg.add("base", _doc(T_BASE, BASE), layer="knowledge", importance=0.5,
               role="user")
        p1 = cg.propose("d1", _doc("候选一", _mixed(K_HALF)), layer="knowledge",
                        tags=["t1"], verification_basis="test")
        r1 = cg.review_decide(p1, "accept", reason="i50c")
        ok(bool(r1.get("ok")), "D1 accept 落盘成功", r1)
        r2 = cg.review_decide(p1, "accept", reason="i50c")
        ok(r2.get("ok") is False and r2.get("error") == "already_decided",
           "D2 幂等对账/终态仍在（同 pid 再裁 already_decided）", r2)
        p2 = cg.propose("d2", _doc("候选二", _mixed(K_HALF)), layer="knowledge",
                        verification_basis="test")
        r3 = cg.review_decide(p2, "edit", edits={"verify": {"kind": "x"}},
                              reason="i50c")
        ok(r3.get("ok") is False and r3.get("error") == "verify_readonly",
           "D3 自验违例检测仍在（裁决期改判据 verify_readonly）", r3)
        r4 = cg.review_decide(p2, "reject", reason="i50c")
        ok(bool(r4.get("ok")) and cg.get("d2") is None, "D4 reject 仍不落盘", r4)
        p3 = cg.propose("d3", _doc("候选三", _mixed(K_HALF)), layer="knowledge")
        r5 = cg.review_decide(p3, "noop", reason="i50c")
        ok(bool(r5.get("ok")) and cg.get("d3") is None, "D5 noop 仍不落盘（只留痕）",
           r5)
        p4 = cg.propose("m9", _doc("候选四", _mixed(K_HALF)), layer="knowledge",
                        non_applicable_conditions=["乙"])
        r6 = cg.review_decide(p4, "merge", merge_into="base", reason="i50c")
        fm_b = ((cg.get("base") or {}).get("frontmatter") or {})
        ok(bool(r6.get("ok")) and "乙" in (fm_b.get("non_applicable_conditions") or []),
           "D6 merge 仍把不适用条件并集落目标 fm（既有职责）",
           (r6, fm_b.get("non_applicable_conditions")))
        ok(any(d.get("pid") == p1 for d in cg.decisions()),
           "D7 裁决留痕仍在（decisions.jsonl 有该 pid）")
    finally:
        with contextlib.suppress(Exception):
            if cg is not None:
                cg.close()
        shutil.rmtree(root, ignore_errors=True)


_GROUPS = (g_a, g_b, g_c, g_d)


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
# 表内每项 = (说明, 目标类, 方法名, 锚点原文, 替换文, 预期红项数)。锚点必须**逐字**
# 出现在当前盘实现的源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。
_PROPOSE = ('            out["proposed"] = self.propose(\n'
            '                _nid, content, layer=layer, **kw, '
            'defer_reason=_why)')
_NID = ('            _nid = node_id if isinstance(node_id, str) and node_id else \\\n'
        '                forgetting._prefeed_id(content)')
_FALLBACK_MARK = ('            if _nid != node_id:\n'
                  '                out["proposed_id_fallback"] = _nid')
_ALREADY = ('        if pid in self._closed_pids():\n'
            '            return {"ok": False, "error": "already_decided"}')
_VERIFY_RO = ('        if (edits and "verify" in edits) or (redteam and "verify" in redteam):')
_NOOP = '        if decision == DECISION_NOOP:'
_NEG_UNION = ('            neg = list(fm.get("non_applicable_conditions") or [])\n'
              '            for x in (item.get("extra") or {}).get("non_applicable_conditions") or []:\n'
              '                if x not in neg:\n'
              '                    neg.append(x)\n'
              '            fm["non_applicable_conditions"] = neg')
_TAGS_MAP = '            tags = list(item.get("tags") or [])'
_CS_MAP = '                           condition_space=item.get("condition_space"), **extra)'

_MUTATIONS = (
    # ① 契约指定：DEFER 出口**不再透传 meta**（退回 issue50-b 的只传 sensitivity）。
    # 实测红项 11：A1 六键全部（tags/condition_space/verification_basis/
    # non_applicable_conditions/derived_from/relation=6）+ A3 的 role/bucket_zh（2；
    # bucket_zh 因 tags/cs 双缺而变）+ B1（白名单外差异）+ B2（only-in-DIRECT 非空）
    # + B3（cs 非 time_window 键不等）。
    ("DEFER 出口不透传 meta（退回只传 sensitivity）",
     MdCGOS, "remember_gated", _PROPOSE,
     '            out["proposed"] = self.propose(\n'
     '                _nid, content, layer=layer,\n'
     '                sensitivity=kw.get("sensitivity"), defer_reason=_why)',
     11),
    # ② 只丢 condition_space（其余 meta 仍在）——打红「cs 相等」那条。实测 5：
    # A1[condition_space] + A3[bucket_zh]（**route_key 读 cs.observation_position**
    # ⇒ 桶/别名随之变，是本表的连带项而非噪声）+ B1 + B2 + B3。
    ("只丢 condition_space（连带桶路由变化）",
     MdCGOS, "remember_gated", _PROPOSE,
     '            out["proposed"] = self.propose(\n'
     '                _nid, content, layer=layer,\n'
     '                **{k: v for k, v in kw.items() if k != "condition_space"},\n'
     '                defer_reason=_why)',
     5),
    # ③ 只丢 derived_from——打红 derived_from 与它派生的 derived_relation。实测 4：
    # A1[derived_from] + A1[relation]（fm.derived_relation 缺席）+ B1 + B2。
    ("只丢 derived_from（连同其派生 derived_relation）",
     MdCGOS, "remember_gated", _PROPOSE,
     '            out["proposed"] = self.propose(\n'
     '                _nid, content, layer=layer,\n'
     '                **{k: v for k, v in kw.items() if k != "derived_from"},\n'
     '                defer_reason=_why)',
     4),
    # ④ 契约指定：去掉 None 兜底（`_nid` 直接取 node_id）→ propose 里 None + str 抛
    # TypeError。实测 6：C1（抛异常）/C2/C4/C5/C6/C7 红；C3（node_id is None）在
    # 空返回体下仍为真，故不红。
    ("去掉 node_id=None 兜底（退回 TypeError）",
     MdCGOS, "remember_gated", _NID,
     '            _nid = node_id',
     6),
    # ⑤ None 仍兜底但**静默**（不写返回体标注）。预期：C6 = 1。
    ("None 兜底但静默（不写 proposed_id_fallback）",
     MdCGOS, "remember_gated", _FALLBACK_MARK,
     '            pass',
     1),
    # ⑥ accept 不再映射 tags（削弱 review_decide 既有映射）——DEFER 路 tags 丢失，
    # 且 bucket_zh 因 tags 空而变。实测 3：A1[tags] + A3[bucket_zh] + B1
    # （B2 不红：tags 键仍在，只是值为 []）。
    ("accept 不再映射 tags（削弱既有映射）",
     MdCGOS, "review_decide", _TAGS_MAP,
     '            tags = []',
     3),
    # ⑦ accept 不再映射 condition_space。实测 5：A1[condition_space] +
    # A3[bucket_zh]（route_key 读 cs ⇒ 桶别名变）+ B1 + B2 + B3。
    ("accept 不再映射 condition_space（削弱既有映射）",
     MdCGOS, "review_decide", _CS_MAP,
     '                           condition_space=None, **extra)',
     5),
    # ⑧ 去掉幂等对账（既有职责）。预期：D2 = 1。
    ("去掉幂等对账 already_decided（既有职责）",
     MdCGOS, "review_decide", _ALREADY,
     '        if False:\n'
     '            return {"ok": False, "error": "already_decided"}',
     1),
    # ⑨ 去掉自验违例检测 verify_readonly（既有职责）。实测 2：D3（该检不报）+
    # D4（连带——edit 不再被拦，把 d2 真写盘了，后面的 reject 断言「不落盘」随之红）。
    ("去掉自验违例检测 verify_readonly（既有职责 连带 D4）",
     MdCGOS, "review_decide", _VERIFY_RO,
     '        if False:',
     2),
    # ⑩ noop 不再短路（落到 else/merge 分支）。预期：D5 = 1。
    ("noop 不再短路（落到 merge 分支）",
     MdCGOS, "review_decide", _NOOP,
     '        if False and decision == DECISION_NOOP:',
     1),
    # ⑪ merge 不再做不适用条件并集（既有职责）。预期：D6 = 1。
    ("merge 不再并集不适用条件（既有职责）",
     MdCGOS, "review_decide", _NEG_UNION,
     '            pass',
     1),
)

# 静态锚点（默认模式也自检，fail-closed）：
_ANCHORS_REQUIRED = (
    (MdCGOS, "remember_gated", '**kw, defer_reason=_why)'),
    (MdCGOS, "remember_gated", 'elif v == "DEFER":'),
    (MdCGOS, "remember_gated", 'forgetting._prefeed_id(content)'),
    (MdCGOS, "review_decide", 'condition_space=item.get("condition_space"), **extra)'),
    (MdCGOS, "review_decide", 'if pid in self._closed_pids():'),
)


def _src(cls, name):
    return inspect.getsource(getattr(cls, name))


# 生效条件：无输入；逐条比对变异锚点与必需锚点是否仍逐字在位，返回 ANCHOR-MISS
# 说明列表（空 = 全部在位）。
def _anchor_check():
    bad = []
    for note, cls, name, old, _new, _n in _MUTATIONS:
        if old not in _src(cls, name):
            bad.append("变异锚点缺失：%s（锚点 %r）" % (note, old[:60]))
    for cls, name, s in _ANCHORS_REQUIRED:
        if s not in _src(cls, name):
            bad.append("必需锚点缺失：%s.%s 内 %r" % (cls.__name__, name, s))
    return bad


# 生效条件：old 与 new 给定时，取目标方法在当前盘实现的源码做字面替换，以模块
# globals 副本 exec 出新函数；返回该函数对象（不落盘、不改源文件）。方法体在类里
# 缩进 4 格，故用 `if True:` 前缀承接。
def _mutate(cls, name, old, new):
    ns = dict(vars(sys.modules[cls.__module__]))
    exec(compile("if True:\n" + _src(cls, name).replace(old, new),
                 "i50c_mut.py", "exec"), ns)
    return ns[name]


# 生效条件：把 cls.name 临时换成 fn 跑一遍 run()，finally 原样还原。
def _with_patched(cls, name, fn, run):
    live = getattr(cls, name)
    setattr(cls, name, fn)
    try:
        return run()
    finally:
        setattr(cls, name, live)


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
    for note, cls, name, old, new, expect in _MUTATIONS:
        fn = _mutate(cls, name, old, new)
        fails = _with_patched(cls, name, fn, _run_fails)
        verdict = ("命中预期" if len(fails) == expect
                   else "**红项数不符（预期 %d）**" % expect)
        print("  变异「%s」→ 红项=%d  %s" % (note, len(fails), verdict))
        if len(fails) != expect:
            bad.append(note)
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
    print("\nissue50-c 守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：" + "、".join(_FAIL))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
