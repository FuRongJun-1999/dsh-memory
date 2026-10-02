# -*- coding: utf-8 -*-
"""md_cg · issue50-e 守卫：读面保护只认显式来源（is_protected 的来源资格闸）

缺陷（编排侧已核 + 本守卫改前探针实测，非推断）
--------------------------------------------------
issue50-d（commit a33682eb）落盘了启发式真分：remember_gated 的启发式路径
importance=0.7x + importance_source="heuristic" 进 fm 与索引条目，**不打**
fm.protected 位（写侧 add 的 source 闸，mdcg.py:2453-2455）。但读面
`protect.is_protected` 的按分自动保护分支（原 :145-150）**不看来源**——
`imp >= AUTO_PROTECT_IMPORTANCE` 即 True（reason「重要性保护」），启发式
0.775 节点被读面认回受保护：写侧「只落分不打位」被读侧单方面推翻。
改前探针实测（隔离临时根合成库，2026-10-02）：a_heur（0.775/heuristic/无位）
is_protected=True「重要性保护：importance=0.78≥0.7」。

本批修复（使用者裁定 2026-10-02：读面也只认显式来源）
--------------------------------------------------
`is_protected` 的按分分支改为：**仅当 fm.importance_source 键缺省（None）或
== "hint" 时**才可由 importance 分数触发；"heuristic" 等显式非 hint 来源
不得由分数触发（落到返回 False，除非命中层保护或 fm.protected 位）。边界：
  ① 键缺省 = 存量节点（既有 cg.add(importance=0.9) 直写、维护路径调分等
    从未有过该键）⇒ 行为一字不变——按「缺省即不认」会大规模改变既有保护
    面，禁止；
  ② 新写入的启发式节点恒带该键 ⇒ 本语义恰好只把「机器推断的重要度」从
    按分保护里摘出去；
  ③ 层保护（PROTECTED_LAYERS）、fm.protected 位、is_immutable 一律不动；
  ④ MERGE 强化（forgetting.reinforce 跨 0.7 置 protected=True）是「重复
    确认」的显式动作，不经本分支，不受影响。
  ⑤ 不改 add() 的写侧 source 闸（issue50-d 已落）、不改遗忘判据、不改检索面；
    fm 形态零新增字段（importance_source 键 issue50-d 已落，读面只是消费）。

改前/改后对拍表（E 组；同一组用例改前/改后两棵树各跑一遍的实测读数）
------------------------------------------------------------------------
  本表是**实施期一次性实测的字面量**，不是 git HEAD 引用（基线绑提交即失效，
  本仓已有两次教训）——改前树用临时探针跑出（Temp/i50e_probe_before.py），
  改后由本守卫的 E 组断言钉住。「期望仅 heuristic 行变」实测成立。

  | 节点（importance/source/protected） | is_protected | guard_forget | guard_move | guard_overwrite | check.protected | stats 计入 |
  |--------------------------------------|--------------|--------------|------------|-----------------|-----------------|------------|
  | a_heur（0.775/heuristic/无位）       | True「重要性保护：importance=0.78≥0.7」→False""【变】| 拦→放【变】| 拦→放【变】| 放→放【不变】| true→false【变】| 计→不计【变】|
  | b_legacy（0.85/无键/无位）           | True「重要性保护：importance=0.85≥0.7」逐字同【不变】| 拦【不变】| 拦【不变】| 放【不变】| true【不变】| 计【不变】|
  | c_hint（0.9/hint/位True）            | True「importance=0.90≥0.7」逐字同【不变】| 拦【不变】| 拦【不变】| 放【不变】| true【不变】| 计【不变】|
  | d_self（0.775/heuristic/self层）     | True「层保护：self（不可遗忘层）」【不变】| 拦【不变】| 拦【不变】| 拦【不变】| true【不变】| 计【不变】|
  | stats 聚合（含 a_ref=0.775/无键/无位 对照，5 节点）| protected_count 5→4【变】auto_by_importance 4→3【变】||||
  | scrub._apply_offset（只含 a_heur）   | (adjusted,skipped) (0,1)→(1,0)【变：启发式不再免疫净化校准】||||
  注：guard_overwrite 走 is_immutable（只认层/位，不认分）⇒ 与本语义无交集，
  三类节点改前改后均放行——「不再要求 override」落地为「无 override 放行」
  的恒真锚（契约 A），列标【不变】。

调用方枚举（F 组静态枚举实测：4 文件、非注释/非 def 的 is_protected( 调用 7 处）
------------------------------------------------------------------------
  protect.guard_forget(:262) / protect.guard_move(:274) / protect.stats(:408)
  / mcp_server._protect_call action=check(:1216)（protect.check 工具读面）
  / scrub.apply 的 skip_protected 判定(:665) / scrub._apply_offset 的 skip
  判定(:728) / self_state.check 的 8 保护一致(:865，判据同 is_protected，
  状态卡为 self 层 ⇒ 层保护先行，经 d_self 钉住)。
  逐类读数（三类节点 × 调用方）见 E 表与 F2 行读数——启发式行：遗忘/搬迁
  放行、check 读 false、净化与校准不再 skip、stats 退出（含 auto 分类）；
  存量/hint/self 行全部一字不变。

定点变异自证（--mutate）
------------------------
每一处判据都配一个定点变异把它打红，且**恰好**命中预期红项数
（_SRC_MUTATIONS 的 expected 列为实施期实测；计数不符即判 FAIL——照
test_i50d_importance_source.py / test_neg_condition_hits.py 同口径）：
  m1「把 heuristic 也认保护」→ A 组启发式读数红（存量/位面不红——闸只加宽
     heuristic 一态）；
  m2「把缺省键也判不认」→ B 组存量零回归锚红 + A6 同分缺省对照红；
  m3「按分整支删除」→ A/B 同红（A 经 A6 同分缺省对照——对照节点不被按分
     保护即红；B 经存量锚），启发式行不红（启发式改后本就该 False，整支
     删除不改变其读数——这正是对照断言 A6 存在的理由）。
锚点漂移（实现改了却没同步本表）→ 报 ANCHOR-MISS 并 **exit 2**（fail-closed）；
默认模式同样先做锚点自检。**不以 git HEAD 为基线源**——变异一律作用在当前
盘的实现上（inspect.getsource + 字面替换 + exec，不落盘不改源文件）。

运行：python -X utf8 -m md_cg.test_i50e_readside_protection
      python -X utf8 -m md_cg.test_i50e_readside_protection --mutate
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import shutil
import subprocess
import sys
import tempfile

# 三档自治批次②（2026-10-02）**夹具隔离**：本守卫考的不是档位面（档位守卫 =
# md_cg/test_autonomy_modes.py），故显式置 full 档——回到改动前「动作直落」的
# 行为，使本文件的断言意图（合并/覆写/软删真的发生）逐条不变；env 键名从唯一
# 真源表取（本文件不构成第二处字面量）。
from . import autonomy_modes as _autonomy_modes          # noqa: E402
os.environ[_autonomy_modes.AUTONOMY_ENV_KEYS["mode"]] = "full"

from . import mcp_server, protect, scrub
from .mdcg import MdCG

_PASS = []
_FAIL = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


# ---------------------------------------------------------------- 夹具
# 四类节点 + 同分缺省对照，全部落在隔离临时根合成库（绝不触在役数据根）：
#   a_heur   0.775 / importance_source="heuristic" / 无 protected 位
#            —— add 直传 source="heuristic"（写侧闸 issue50-d：不打位），
#               与 remember_gated 启发式路径的落盘形态同构（i50d A4-A7 已钉
#               落盘三件套：落分=裁决值 / source=heuristic / 无位）。
#   a_ref    0.775 / 无 source 键 / 无位 —— 同分缺省对照（判别力锚：证明
#            A1 的 False 是「来源」导致而非分数/形态导致；m3 整支删除时它红）。
#   b_legacy 0.85 / 无 source 键 / 无位 —— 存量形态（0.3 写入后调分，模拟
#            既有直写/维护路径调分的无键节点）。
#   c_hint   0.9 / "hint" / protected=True —— 写侧对显式 hint 过线打位。
#   d_self   0.775 / "heuristic" / self 层 —— 层保护先行（heuristic 不认也
#            轮不到按分分支）。
DOC = ("# 功能名：i50e 守卫节点\n# 生效条件：任意情境\n# 子功能：验收\n"
       "# 执行：直接调用\n# 验证方式：test\n# 不适用条件：无\n"
       "读面保护来源资格闸守卫正文。")


def _set_fm(cg, nid, **kv):
    """按 scrub._apply_offset / protect.mark 同口径写回 fm（值 None = 删键），
    同步索引条目并标脏 flush——让读面（索引）与盘面一致。"""
    node = cg.get(nid)
    fm = dict(node.get("frontmatter") or {})
    for k, v in kv.items():
        if v is None:
            fm.pop(k, None)
        else:
            fm[k] = v
    e = cg.index["nodes"].get(nid) or {}
    path = os.path.join(cg.root, e.get("path") or node.get("path")
                        or (nid + ".md"))
    cg._write_node(nid, path, fm, node.get("content") or "")
    if e is not None:
        for k in ("importance", "protected", "protection_reason",
                  "importance_source", "confidence", "immutable"):
            e[k] = fm.get(k)
        d = getattr(cg, "_dirty", None)
        if isinstance(d, dict):
            d[nid] = e
        fl = getattr(cg, "flush", None)
        if callable(fl):
            try:
                fl()
            except Exception:
                pass


@contextlib.contextmanager
def _cg(*nids):
    """隔离临时根上构造指定节点集合；with 出来的是 MdCG 实例（finally 清理）。"""
    root = tempfile.mkdtemp(prefix="i50e_")
    cg = MdCG(root)
    try:
        for nid in nids:
            if nid == "a_heur":
                cg.add(nid, DOC, layer="knowledge", importance=0.775,
                       importance_source="heuristic", verification_basis="test")
            elif nid == "a_ref":
                cg.add(nid, DOC, layer="knowledge", importance=0.3,
                       verification_basis="test")
                _set_fm(cg, nid, importance=0.775)   # 无 source 键、无位
            elif nid == "b_legacy":
                cg.add(nid, DOC, layer="knowledge", importance=0.3,
                       verification_basis="test")
                _set_fm(cg, nid, importance=0.85)    # 存量：无键、无位
            elif nid == "c_hint":
                cg.add(nid, DOC, layer="knowledge", importance=0.9,
                       importance_source="hint", verification_basis="test")
            elif nid == "d_self":
                cg.add(nid, DOC, layer="self", importance=0.775,
                       importance_source="heuristic",
                       verification_basis="test")
            else:
                raise KeyError(nid)
        yield cg
    finally:
        try:
            cg.close()
        except Exception:
            pass
        shutil.rmtree(root, ignore_errors=True)


def _guard_line(fn, *args, **kw):
    """守卫读数：None=放行，否则 ProtectionError 文案（逐字比对用）。"""
    try:
        r = fn(*args, **kw)
        return None if r is None else ("ret:" + str(r))
    except protect.ProtectionError as e:
        return "ProtectionError:" + str(e)


# 改前探针实测字面量（改前树一次性实测，非 git HEAD 引用；E 组逐格钉住）
_BEFORE = {
    "a_heur": {"is_protected": (True, "重要性保护：importance=0.78≥0.7"),
               "guard_forget": "ProtectionError:节点 a_heur 不可遗忘"
                               "（重要性保护：importance=0.78≥0.7）；删除需显式"
                               " override=True",
               "guard_overwrite": None,
               "check_protected": True},
    "b_legacy": {"is_protected": (True, "重要性保护：importance=0.85≥0.7"),
                 "guard_forget": "ProtectionError:节点 b_legacy 不可遗忘"
                                 "（重要性保护：importance=0.85≥0.7）；删除需显式"
                                 " override=True",
                 "guard_overwrite": None,
                 "check_protected": True},
    "c_hint": {"is_protected": (True, "importance=0.90≥0.7"),
               "guard_forget": "ProtectionError:节点 c_hint 不可遗忘"
                               "（importance=0.90≥0.7）；删除需显式 override=True",
               "guard_overwrite": None,
               "check_protected": True},
    "d_self": {"is_protected": (True, "层保护：self（不可遗忘层）"),
               "guard_overwrite": "ProtectionError:节点 d_self 受写保护"
                                  "（层保护：self（不可篡改层））；覆盖需显式"
                                  " override=True",
               "check_protected": True},
}
# 改后期望（「变」列）：a_heur 退出按分保护，其余逐字同改前
_AFTER_A_HEUR = {"is_protected": (False, ""), "check_protected": False}
_AFTER_STATS5 = {"protected_count": 4, "auto_by_importance": 3,
                 "ids": ["a_ref", "b_legacy", "c_hint", "d_self"]}


# ---------------------------------------------------------------- F0 夹具自检
def g_f0():
    print("== F0 夹具自检（四类节点确实落在契约形态上）==")
    with _cg("a_heur", "a_ref", "b_legacy", "c_hint", "d_self") as cg:
        fma = (cg.get("a_heur") or {}).get("frontmatter") or {}
        ok(fma.get("importance") == 0.775
           and fma.get("importance_source") == "heuristic"
           and fma.get("protected") is None,
           "F0-1 a_heur 落盘形态：0.775/heuristic/无位（issue50-d 写侧同构）",
           (fma.get("importance"), fma.get("importance_source"),
            fma.get("protected")))
        fmr = (cg.get("a_ref") or {}).get("frontmatter") or {}
        ok(fmr.get("importance") == 0.775
           and "importance_source" not in fmr
           and fmr.get("protected") is None,
           "F0-2 a_ref 落盘形态：0.775/无 source 键/无位（同分缺省对照）",
           (fmr.get("importance"), fmr.get("importance_source"),
            fmr.get("protected")))
        fmb = (cg.get("b_legacy") or {}).get("frontmatter") or {}
        ok(fmb.get("importance") == 0.85
           and "importance_source" not in fmb
           and fmb.get("protected") is None,
           "F0-3 b_legacy 落盘形态：0.85/无 source 键/无位（存量）",
           (fmb.get("importance"), fmb.get("importance_source"),
            fmb.get("protected")))
        fmc = (cg.get("c_hint") or {}).get("frontmatter") or {}
        ok(fmc.get("importance") == 0.9
           and fmc.get("importance_source") == "hint"
           and fmc.get("protected") is True,
           "F0-4 c_hint 落盘形态：0.9/hint/位True（写侧显式打位不受影响）",
           (fmc.get("importance"), fmc.get("importance_source"),
            fmc.get("protected")))


# ---------------------------------------------------------------- A 启发式面
def g_a():
    print("== A 启发式节点：读面不再按分认保护（含同分缺省对照）==")
    with _cg("a_heur", "a_ref", "d_self") as cg:
        ok(protect.is_protected(cg, "a_heur") == (False, ""),
           "A1 is_protected(a_heur) == (False, '')（0.775/heuristic/无位"
           " → 改前 (True,「重要性保护：importance=0.78≥0.7」)）",
           protect.is_protected(cg, "a_heur"))
        ok(_guard_line(protect.guard_forget, cg, "a_heur") is None,
           "A2 guard_forget(a_heur) 放行（改前拦：不可遗忘 ProtectionError）",
           _guard_line(protect.guard_forget, cg, "a_heur"))
        ok(_guard_line(protect.guard_move, cg, "a_heur", "contextual") is None,
           "A3 guard_move(a_heur, contextual) 放行（改前拦：降级搬迁）",
           _guard_line(protect.guard_move, cg, "a_heur", "contextual"))
        ok(_guard_line(protect.guard_overwrite, cg, "a_heur") is None,
           "A4 guard_overwrite(a_heur) 无 override 放行（该闸走 is_immutable"
           " 不认分——改前改后同，恒真锚）",
           _guard_line(protect.guard_overwrite, cg, "a_heur"))
        chk = mcp_server._protect_call(cg, {"action": "check",
                                            "node_id": "a_heur"})
        ok(chk.get("protected") is False and chk.get("reason") == "",
           "A5 protect.check 工具读面：protected=false / reason=''（改前 true"
           " /「重要性保护：importance=0.78≥0.7」）", chk)
        ok(protect.is_protected(cg, "a_ref") == (True,
                                                 "重要性保护：importance=0.78"
                                                 "≥0.7"),
           "A6 同分缺省对照 a_ref：is_protected True 且 reason 与改前逐字同"
           "（判别力锚——A1 的 False 是来源导致而非分数/形态导致；m3 靠它红）",
           protect.is_protected(cg, "a_ref"))
    with _cg("a_heur") as cg:
        adj, skip = scrub._apply_offset(cg, 0.1, override=False,
                                        min_evidence=0)
        ok((adj, skip) == (1, 0),
           "A7 scrub._apply_offset 不再 skip 启发式节点：(adjusted,skipped)"
           "==(1,0)（改前 (0,1)——机器推断重要度不再免疫净化校准）",
           (adj, skip))
        st = protect.stats(cg)
        ok(st["protected_count"] == 0 and st["auto_by_importance"] == 0
           and st["ids"] == [],
           "A8 stats（只含 a_heur）：protected_count=0 / auto_by_importance=0"
           " / ids=[]（改前 1/1/[a_heur]）", st)


# ---------------------------------------------------------------- B 存量面
def g_b():
    print("== B 存量形态（0.85/无键/无位）：零回归锚，reason 逐字同改前 ==")
    with _cg("b_legacy") as cg:
        ok(protect.is_protected(cg, "b_legacy")
           == (True, "重要性保护：importance=0.85≥0.7"),
           "B1 is_protected(b_legacy) 逐字同改前（键缺省 ⇒ 按分保护一字不变）",
           protect.is_protected(cg, "b_legacy"))
        ok(_guard_line(protect.guard_forget, cg, "b_legacy")
           == _BEFORE["b_legacy"]["guard_forget"],
           "B2 guard_forget(b_legacy) 拦且文案逐字同改前",
           _guard_line(protect.guard_forget, cg, "b_legacy"))
        ok(_guard_line(protect.guard_move, cg, "b_legacy", "contextual")
           == _BEFORE["b_legacy"]["guard_forget"].replace(
               "不可遗忘", "受写保护").replace("删除需显式", "降级移出保护层需显式"),
           "B3 guard_move(b_legacy) 拦且文案同改前形态",
           _guard_line(protect.guard_move, cg, "b_legacy", "contextual"))
        ok(_guard_line(protect.guard_overwrite, cg, "b_legacy") is None,
           "B4 guard_overwrite(b_legacy) 放行（改前改后同）",
           _guard_line(protect.guard_overwrite, cg, "b_legacy"))
        chk = mcp_server._protect_call(cg, {"action": "check",
                                            "node_id": "b_legacy"})
        ok(chk.get("protected") is True
           and chk.get("reason") == "重要性保护：importance=0.85≥0.7",
           "B5 protect.check 读面逐字同改前", chk)
        st = protect.stats(cg)
        ok(st["protected_count"] == 1 and st["auto_by_importance"] == 1
           and st["ids"] == ["b_legacy"],
           "B6 stats（只含 b_legacy）：1/1/计入 auto（改前改后同）", st)


# ---------------------------------------------------------------- C hint 面
def g_c():
    print("== C 显式 hint 节点：fm.protected 位分支不受影响 ==")
    with _cg("c_hint") as cg:
        ok(protect.is_protected(cg, "c_hint") == (True, "importance=0.90≥0.7"),
           "C1 is_protected(c_hint) 走 fm.protected 位分支且 reason 逐字同改前",
           protect.is_protected(cg, "c_hint"))
        fmc = (cg.get("c_hint") or {}).get("frontmatter") or {}
        ok(fmc.get("protected") is True,
           "C2 写侧显式 hint 过线打位不受本批影响", fmc.get("protected"))
        ok(_guard_line(protect.guard_forget, cg, "c_hint")
           == _BEFORE["c_hint"]["guard_forget"],
           "C3 guard_forget(c_hint) 拦且文案逐字同改前",
           _guard_line(protect.guard_forget, cg, "c_hint"))
        ok(protect.is_immutable(cg, "c_hint") == (False, ""),
           "C4 is_immutable(c_hint) == (False, '')（immutable 位零变化）",
           protect.is_immutable(cg, "c_hint"))
        st = protect.stats(cg)
        ok(st["protected_count"] == 1 and st["auto_by_importance"] == 1,
           "C5 stats（只含 c_hint）：位 reason 含 importance= ⇒ 依旧计 auto"
           "（改前改后同）", st)


# ---------------------------------------------------------------- D 层保护/不可覆盖
def g_d():
    print("== D 层保护与 is_immutable 零变化（钉既有断言跑通而非重写）==")
    with _cg("a_heur", "b_legacy", "c_hint", "d_self") as cg:
        ok(protect.is_protected(cg, "d_self")
           == (True, "层保护：self（不可遗忘层）"),
           "D1 d_self（heuristic + self 层）：层保护先于按分分支，reason 逐字"
           "同改前", protect.is_protected(cg, "d_self"))
        ok(protect.is_immutable(cg, "d_self")
           == (True, "层保护：self（不可篡改层）"),
           "D2 is_immutable(d_self) 层保护逐字同改前",
           protect.is_immutable(cg, "d_self"))
        ok(all(protect.is_immutable(cg, n) == (False, "")
               for n in ("a_heur", "b_legacy", "c_hint")),
           "D3 knowledge 层三节点 is_immutable 全 (False, '')（不可覆盖闸"
           "零变化——不认分数也不认来源）",
           [protect.is_immutable(cg, n) for n in
            ("a_heur", "b_legacy", "c_hint")])
        ok(_guard_line(protect.guard_overwrite, cg, "d_self")
           == _BEFORE["d_self"]["guard_overwrite"],
           "D4 guard_overwrite(d_self) 拦且文案逐字同改前（层保护经"
           " is_immutable 生效）",
           _guard_line(protect.guard_overwrite, cg, "d_self"))
    ok("importance_source" not in inspect.getsource(protect.is_immutable),
       "D5 静态：is_immutable 源码零改动（不含 importance_source）")
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "md_cg.test_p9_forget_protect"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=repo, env=env, timeout=300)
    ok(proc.returncode == 0,
       "D6 既有保护族守卫 test_p9_forget_protect 不改断言跑通（rc=0）",
       proc.stdout[-400:] + proc.stderr[-200:])
    proc2 = subprocess.run(
        [sys.executable, "-X", "utf8", "-m",
         "md_cg.test_i50d_importance_source"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=repo, env=env, timeout=300)
    ok(proc2.returncode == 0,
       "D7 写侧守卫 test_i50d_importance_source 不改断言跑通（rc=0）",
       proc2.stdout[-400:] + proc2.stderr[-200:])


# ---------------------------------------------------------------- E 对拍锚
def g_e():
    print("== E 改前/改后对拍锚（docstring 表逐格：变列确实变、不变列逐字同）==")
    with _cg("a_heur", "a_ref", "b_legacy", "c_hint", "d_self") as cg:
        pa = protect.is_protected(cg, "a_heur")
        ok(pa == _AFTER_A_HEUR["is_protected"]
           and pa != _BEFORE["a_heur"]["is_protected"],
           "E1 a_heur 行变列：is_protected True→(False, '')（确实变了）", pa)
        ok(_guard_line(protect.guard_forget, cg, "a_heur") is None,
           "E2 a_heur 行变列：guard_forget 拦→放", "")
        chk_a = mcp_server._protect_call(cg, {"action": "check",
                                              "node_id": "a_heur"})
        ok(chk_a.get("protected") is False
           and _BEFORE["a_heur"]["check_protected"] is True,
           "E3 a_heur 行变列：check.protected true→false", chk_a)
        for nid in ("b_legacy", "c_hint", "d_self"):
            p = protect.is_protected(cg, nid)
            ok(p == _BEFORE[nid]["is_protected"],
               "E4 %s 行不变列：is_protected 与改前逐字相同" % nid, p)
            ok(_guard_line(protect.guard_overwrite, cg, nid)
               == _BEFORE[nid]["guard_overwrite"],
               "E5 %s 行不变列：guard_overwrite 与改前相同" % nid, "")
            chk = mcp_server._protect_call(cg, {"action": "check",
                                                "node_id": nid})
            ok(chk.get("protected") == _BEFORE[nid]["check_protected"],
               "E6 %s 行不变列：check.protected 与改前相同" % nid, chk)
        st = protect.stats(cg)
        ok(st["protected_count"] == _AFTER_STATS5["protected_count"]
           and st["auto_by_importance"] == _AFTER_STATS5["auto_by_importance"]
           and st["ids"] == _AFTER_STATS5["ids"]
           and st["protected_count"] != 5 and st["auto_by_importance"] != 4,
           "E7 stats 聚合变列：5 节点 protected_count 5→4、"
           "auto_by_importance 4→3（heuristic 退出是预期，不是回归）", st)
        ok(_BEFORE["a_heur"]["is_protected"][0] is True,
           "E8 改前锚自检：a_heur 改前确实 True（缺陷形态，探针实测字面）")


# ---------------------------------------------------------------- F 调用方枚举与逐类读数
_CALLSITES = {
    "protect.py": (3, "guard_forget:262 / guard_move:274 / stats:408"),
    "mcp_server.py": (1, "_protect_call action=check:1216"),
    "scrub.py": (2, "apply skip_protected:665 / _apply_offset skip:728"),
    "self_state.py": (1, "check 8 保护一致:865"),
}


def g_f():
    print("== F 调用方枚举与逐类读数 ==")
    pkg = os.path.dirname(os.path.abspath(__file__))
    total = 0
    for fn, (want, label) in _CALLSITES.items():
        with open(os.path.join(pkg, fn), encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines()
                     if "is_protected(" in ln
                     and not ln.strip().startswith("#")
                     and "def is_protected" not in ln]
        total += len(lines)
        ok(len(lines) == want,
           "F1 %s 的 is_protected( 调用点 == %d（%s）" % (fn, want, label),
           lines)
    ok(total == 7,
       "F1+ 全部非测试调用点恰 7 处（枚举完备性——新增调用方须同步本表）",
       total)
    with _cg("a_heur") as cg:
        row_a = (protect.is_protected(cg, "a_heur"),
                 _guard_line(protect.guard_forget, cg, "a_heur"),
                 _guard_line(protect.guard_move, cg, "a_heur", "contextual"),
                 _guard_line(protect.guard_overwrite, cg, "a_heur"),
                 mcp_server._protect_call(cg, {"action": "check",
                                               "node_id": "a_heur"}).get(
                                                     "protected"),
                 protect.stats(cg)["auto_by_importance"])
        ok(row_a == ((False, ""), None, None, None, False, 0),
           "F2 a_heur 逐类读数行：is_protected/遗忘/搬迁/覆写/check/auto "
           "== 不保护·放·放·放·false·0（改前 True·拦·拦·放·true·1）", row_a)
    with _cg("b_legacy") as cg:
        row_b = (protect.is_protected(cg, "b_legacy"),
                 _guard_line(protect.guard_forget, cg, "b_legacy"),
                 mcp_server._protect_call(cg, {"action": "check",
                                               "node_id": "b_legacy"}).get(
                                                     "protected"),
                 protect.stats(cg)["auto_by_importance"])
        ok(row_b == ((True, "重要性保护：importance=0.85≥0.7"),
                     _BEFORE["b_legacy"]["guard_forget"], True, 1),
           "F2 b_legacy 逐类读数行：存量零回归（逐字同改前）", row_b)
    with _cg("c_hint") as cg:
        row_c = (protect.is_protected(cg, "c_hint"),
                 protect.is_immutable(cg, "c_hint"),
                 protect.stats(cg)["protected_count"])
        ok(row_c == ((True, "importance=0.90≥0.7"), (False, ""), 1),
           "F2 c_hint 逐类读数行：位分支/immutable 零变化", row_c)
    with _cg("d_self") as cg:
        row_d = (protect.is_protected(cg, "d_self"),
                 protect.is_immutable(cg, "d_self"))
        ok(row_d == ((True, "层保护：self（不可遗忘层）"),
                     (True, "层保护：self（不可篡改层）")),
           "F2 d_self 逐类读数行：层保护先行（self_state:865 的 protection_missing"
           " 判据同 is_protected ⇒ 恒不报，读数不变）", row_d)


_GROUPS = (g_f0, g_a, g_b, g_c, g_d, g_e, g_f)


def _run_groups():
    """跑全部断言组（静默），返回失败数——供变异自证复用。"""
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        g()
    return len(_FAIL)


# ---------------------------------------------------------------- 定点变异自证
# 表内每项 = (说明, 锚点原文, 替换文, 预期红项数)。锚点必须**逐字**出现在当前
# is_protected 函数源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。
#   契约 G：m1 把 heuristic 也认保护 → A 红；m2 把缺省键也判不认 → B 红；
#   m3 按分整支删除 → A/B 同红（A 经 A6 同分缺省对照）。
_SRC_MUTATIONS = (
    # 契约 G①：启发式也认保护（闸加宽一态）。红 11（实测 2026-10-02）：
    # A1/A2/A3/A5/A7/A8（启发式读数面 6）+ E1/E2/E3（a_heur 行三格变列锚）
    # + E7（stats 聚合）+ F2 a_heur 行。存量/对照/位面全不红——闸只加宽
    # heuristic 一态，恰证语义按来源分叉。
    ("heuristic 也认保护（m1）",
     '(_src is None or _src == "hint")',
     '(_src is None or _src == "hint" or _src == "heuristic")',
     11),
    # 契约 G②：缺省键也判不认（「缺省即不认」被禁的缺陷形态）。红 10
    # （实测 2026-10-02）：A6（同分缺省对照）+ B1/B2/B3/B5/B6（存量零回归
    # 锚 5——B4 走 guard_overwrite 放行不受影响）+ E4/E6（b_legacy 行两格，
    # E5 走 guard_overwrite 不红）+ E7（stats 聚合）+ F2 b_legacy 行。
    ("缺省键也判不认（m2，禁用缺陷形态）",
     '(_src is None or _src == "hint")',
     '(_src == "hint")',
     10),
    # 契约 G③：按分分支整支删除。红 10（实测同 m2 构成）：A6 + B1/B2/B3/
    # B5/B6 + E4/E6 + E7 + F2 b_legacy 行——A/B 同红（A 经 A6 对照；
    # a_heur 行不红，因启发式改后本就 False，整支删除不改变其读数）。
    ("按分整支删除（m3）",
     '    _src = fm.get("importance_source")\n'
     '    if imp >= AUTO_PROTECT_IMPORTANCE and (_src is None or _src == "hint"):\n'
     '        return True, f"重要性保护：importance={imp:.2f}≥{AUTO_PROTECT_IMPORTANCE}"',
     '    pass',
     10),
)

# 静态锚点（默认模式也自检，fail-closed）：
#   · 改前缺陷形态（无来源闸的按分分支）**不得**回归出现在 is_protected 源码里
#   · 本批新判据的锚点必须在位
_ANCHORS_BANNED = (
    ("is_protected", 'if imp >= AUTO_PROTECT_IMPORTANCE:\n        return True'),
)
_ANCHORS_REQUIRED = (
    ("is_protected", '_src = fm.get("importance_source")'),
    ("is_protected", 'and (_src is None or _src == "hint"):'),
)


def _fn_src(target):
    if target == "is_protected":
        return inspect.getsource(protect.is_protected)
    raise KeyError(target)


def _anchor_check():
    """返回 ANCHOR-MISS 说明列表（空 = 全部在位）。"""
    bad = []
    for _name, old, _new, _n in _SRC_MUTATIONS:
        if old not in _fn_src("is_protected"):
            bad.append("变异锚点缺失：%r @is_protected" % old)
    for target, s in _ANCHORS_BANNED:
        if s in _fn_src(target):
            bad.append("缺陷形态回归：%s 可执行源码里仍有 %r" % (target, s))
    for target, s in _ANCHORS_REQUIRED:
        if s not in _fn_src(target):
            bad.append("新判据锚点缺失：%s 找不到 %r" % (target, s))
    return bad


@contextlib.contextmanager
def _patched_ctx(old, new):
    """把 protect.is_protected 按字面替换变异后安装/还原（不落盘不改源文件）。

    guard_forget / guard_move / stats 经 protect 模块 __dict__ 解析
    is_protected，mcp_server/scrub/self_state 经 `from . import protect`
    属性查找——setattr 后全部出口同闸生效。
    """
    src = _fn_src("is_protected")
    mutated = src.replace(old, new)
    ns = dict(vars(protect))
    exec(compile(mutated, "i50e_mut.py", "exec"), ns)
    live = protect.is_protected
    protect.is_protected = ns["is_protected"]
    try:
        yield
    finally:
        protect.is_protected = live


def _mutate_mode():
    bad = []
    anchor_bad = _anchor_check()
    if anchor_bad:
        for b in anchor_bad:
            print("  ANCHOR-MISS " + b)
        print("\n锚点自检：FAIL（fail-closed，exit 2）")
        return 2
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：红项=%d%s"
          % (clean, "" if clean == 0 else "  ← 基线即红，变异核验无意义"))
    if clean:
        bad.append("未变异基线即失败")
    for name, old, new, expect in _SRC_MUTATIONS:
        with _patched_ctx(old, new), \
                contextlib.redirect_stdout(io.StringIO()):
            fails = _run_groups()
        verdict = ("命中预期" if fails == expect
                   else "**红项数不符（预期 %d）**" % expect)
        print("  变异「%s」→ 红项=%d  %s" % (name, fails, verdict))
        if fails != expect:
            bad.append(name)
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都有变异钉死，且红项数逐处吻合）" if not bad
             else "FAIL —— " + "、".join(bad)))
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
        print("\n锚点自检：FAIL（fail-closed，exit 2）——实现改了请同步变异表")
        return 2
    print("锚点自检：PASS（%s；不以 git HEAD 为基线源）" % src)
    for g in _GROUPS:
        g()
    print("\nissue50-e 守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("失败项：" + "、".join(_FAIL))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
