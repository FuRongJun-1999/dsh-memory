# -*- coding: utf-8 -*-
"""守卫 · coverage 父母子项 / writepipe received_at / 剩余 4 模块 `_dirty_lock`（Refs #1005 / #1011）。

覆盖范围：
- G1 `coverage.slot_gaps`：复合亲属词（父母 / 爸妈 / 双亲）同时展开父亲与母亲，单亲查询不误扩，
     非 dict 的 `pack` 条目不崩溃（与 `gaps()` 对齐）。
- G2 `writepipe` `received_at` 透传：`_write_values` / `_OUTLET_PARAMS` / `_AUTONOMY_META_KEYS`
     直写、gated、确认档变更单（direct & gated `C_REWRITE` → accept 重放）与审计 DEFER 提案
     （accept 重放）均保留 `received_at`，缺省 `None` 回落 `created_at` 行为不变。
- G3 静态 AST 锁护与纯叶锁审计 + 内存定点变异对照：`scrub.py` / `protect.py` / `rollback.py` /
     `writelimit.py` 全部 `._dirty` 写点均在 `_dirty_lock` 内，且锁内零磁盘 IO / `FileLock` /
     `flush()` / `add()` 锁序倒置。
- G4 运行时持锁深度实测：5 处写点（`scrub._apply_offset` / `protect.mark` / `rollback._land` /
     `writelimit.converge_into` / `writelimit._demote`）均以 `_TrackingRLock` + `_ObservingDirtyDict`
     实证写 `_dirty` 时 `depth>=1`、`_write_node` / `flush` / `_node_entry` 时 `depth==0`。
- G5 Mock 兼容（无 `_dirty_lock` 桩不崩溃）+ 确定性 `flush` 并发竞态消除（零 `RuntimeError`、
     零丢脏项）+ 多线程压测（零异常、零死锁）。

跑法：py -3.13 -X utf8 -m md_cg.test_coverage_writepipe_and_dirty_locks
"""
from __future__ import annotations

import ast
import atexit
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types

# 沙箱隔离必须在导入任何 md_cg 子模块之前生效（crypto/tokens 在导入期求值）。
_SANDBOX = tempfile.mkdtemp(prefix="cov_wp_dlock_")
atexit.register(shutil.rmtree, _SANDBOX, True)
os.environ["MDCG_AUX_ROOT"] = os.path.join(_SANDBOX, "auxstore")
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "libroot")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ["MDCG_WRITE_GATE"] = "warn"
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
os.makedirs(os.environ["MDCG_ROOT"], exist_ok=True)
for _env_k in (
    "MDCG_POLICY_FILE", "MDCG_SESSION", "DSH_SESSION_ID", "MDCG_TOKEN",
    "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_STATE_ROOT", "MDCG_DATA_ROOT",
    "MDCG_EXPORT_ROOT", "MDCG_TEST_LIVE_ROOT", "MDCG_REVIEW_DUAL_CHECK",
    "MDCG_REDTEAM_REQUIRED",
):
    os.environ.pop(_env_k, None)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from md_cg import (  # noqa: E402
    audit as audit_mod,
    autonomy_modes as _am,
    coverage,
    hyperedge,
    mcp_server,
    nodefile,
    protect,
    rollback,
    scrub,
    writelimit,
    writepipe,
)
from md_cg.mdcg import _DirtyDict  # noqa: E402
from md_cg.mdcos import MdCGOS, MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402

_PASS = []
_FAIL = []

_CCG = (
    "# 功能名：{name}\n"
    "# 生效条件：{cond}\n"
    "# 子功能：核验写链与脏集锁护\n"
    "# 执行：{body}\n"
    "# 验证方式：单测\n"
    "# 不适用条件：不涉及远程同步\n"
)

#: 2026-11-24 10:47 左右（与当前日期明显错开，用于验证 received_at 与昨天换算）
_TS_1 = 1795488442.29
_TS_2 = 1795402042.29
_TS_3 = 1795315642.29

_DIRTY_MODULES = (
    "md_cg/scrub.py",
    "md_cg/protect.py",
    "md_cg/rollback.py",
    "md_cg/writelimit.py",
)

_FORBIDDEN_IN_DIRTY_LOCK = frozenset({
    "flush", "_flush", "_write_node", "add", "get", "FileLock",
    "stat", "open", "atomic_write", "publish", "snapshot",
    "_node_entry", "guard_overwrite", "guard_write", "invalidate_cache",
})


def ok(cond, label, detail=""):
    (_PASS if cond else _FAIL).append(label)
    suffix = ("  <- " + str(detail)[:240]) if (detail and not cond) else ""
    print(("  PASS " if cond else "  FAIL ") + label + suffix)
    return bool(cond)


class _TrackingRLock:
    """包装真实 RLock，按线程精确记录持锁深度与进入次数。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._tls = threading.local()
        self.entries = 0

    @property
    def depth(self) -> int:
        return getattr(self._tls, "depth", 0)

    def acquire(self, *args, **kwargs):
        got = self._lock.acquire(*args, **kwargs)
        if got:
            self._tls.depth = self.depth + 1
            self.entries += 1
        return got

    def release(self):
        self._tls.depth = max(0, self.depth - 1)
        return self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False


class _ObservingDirtyDict(_DirtyDict):
    """在 `_DirtyDict` 关键操作时记录 `_dirty_lock` 持锁深度。"""

    def __init__(self, lock: _TrackingRLock, log: list, src: _DirtyDict):
        super().__init__()
        self._obs_lock = lock
        self._obs_log = log
        self._obs_enabled = False
        self.root = src.root
        self.write_gen = src.write_gen
        self.broad_gen = src.broad_gen
        self.path_gen = dict(src.path_gen)
        self.staged_stat = dict(src.staged_stat)
        self.superseded_ids = set(src.superseded_ids)
        dict.update(self, src)
        self._obs_enabled = True

    def _rec(self, op: str, key=None):
        if object.__getattribute__(self, "_obs_enabled"):
            lk = object.__getattribute__(self, "_obs_lock")
            lg = object.__getattribute__(self, "_obs_log")
            lg.append((op, key, lk.depth))

    def __setitem__(self, k, v):
        self._rec("__setitem__", k)
        return super().__setitem__(k, v)

    def __delitem__(self, k):
        self._rec("__delitem__", k)
        return super().__delitem__(k)

    def clear(self, broad: bool = False):
        self._rec("clear", broad)
        return super().clear(broad=broad)


def _attach_observer(cg):
    lock = _TrackingRLock()
    log = []
    cg._dirty_lock = lock
    cg._dirty = _ObservingDirtyDict(lock, log, cg._dirty)
    return lock, log


# ---------------------------------------------------------------- G1: coverage.slot_gaps
def g1_coverage_slot_gaps():
    print("== G1 coverage.slot_gaps 复合亲属词与非 dict 防御 ==")

    def slots(pack, q):
        return [g.get("slot") for g in coverage.slot_gaps(pack, q)]

    only_father = [{"content": "我爸是中学教师，退休前教数学"}]
    only_mother = [{"content": "我妈退休前在纺织厂上班"}]
    both_sep = [{"content": "我爸是中学教师"}, {"content": "我妈在纺织厂上班"}]
    both_joint = [{"content": "我父母退休前都在国企工厂上班"}]

    ok(slots(only_father, "父母退休前各干什么") == ["母亲·职业"],
       "G1a 「父母退休前各干什么」仅有父亲职业 ⇒ 报 ['母亲·职业']",
       slots(only_father, "父母退休前各干什么"))
    ok(slots(only_mother, "父母退休前各干什么") == ["父亲·职业"],
       "G1b 「父母退休前各干什么」仅有母亲职业 ⇒ 报 ['父亲·职业']",
       slots(only_mother, "父母退休前各干什么"))
    ok(slots(both_sep, "父母退休前各干什么") == [],
       "G1c 「父母退休前各干什么」父母职业均存在 ⇒ 不报",
       slots(both_sep, "父母退休前各干什么"))
    ok(slots(both_joint, "父母退休前各干什么") == [],
       "G1d 「父母退休前各干什么」合述句「我父母退休前都在国企工厂上班」⇒ 不误报",
       slots(both_joint, "父母退休前各干什么"))
    ok(set(slots([], "父母退休前各干什么")) == {"父亲·职业", "母亲·职业"},
       "G1e 「父母退休前各干什么」空 pack ⇒ 父母两项都报",
       slots([], "父母退休前各干什么"))

    # 爸妈 & 双亲
    ok(slots(only_father, "爸妈退休前各干什么") == ["母亲·职业"]
       and slots(both_sep, "爸妈退休前各干什么") == []
       and set(slots([], "爸妈退休前各干什么")) == {"父亲·职业", "母亲·职业"},
       "G1f 「爸妈退休前各干什么」单缺 / 齐全 / 空包均正确")
    ok(slots(only_father, "双亲退休前各干什么") == ["母亲·职业"]
       and slots(only_mother, "双亲退休前各干什么") == ["父亲·职业"]
       and slots(both_sep, "双亲退休前各干什么") == []
       and set(slots([], "双亲退休前各干什么")) == {"父亲·职业", "母亲·职业"},
       "G1g 「双亲退休前各干什么」单缺 / 齐全 / 空包均正确")

    # 单亲查询不得误扩另一亲属
    ok(slots(only_father, "我父亲退休前干什么") == [],
       "G1h 单亲查询「我父亲退休前干什么」有父亲时不误报母亲",
       slots(only_father, "我父亲退休前干什么"))
    ok(slots(only_mother, "我母亲退休前干什么") == [],
       "G1i 单亲查询「我母亲退休前干什么」有母亲时不误报父亲",
       slots(only_mother, "我母亲退休前干什么"))

    # 非 dict 混入 pack 不崩溃（子项路径与槽位兜底路径双覆盖）
    mixed_pack = [None, "纯字符串", 42, ["list"], {"content": "我爸是中学教师"}]
    ok(slots(mixed_pack, "父母退休前各干什么") == ["母亲·职业"],
       "G1j pack 含 None/str/int/list 非 dict 条目时 slot_gaps 不崩溃且判定准确",
       slots(mixed_pack, "父母退休前各干什么"))
    ok(slots([None, "raw", 123], "家里人情况") == ["家庭"],
       "G1k 非属性槽位兜底路径遇到非 dict 条目同样不崩溃",
       slots([None, "raw", 123], "家里人情况"))
    ok(slots([{"content": "", "content_dated": "我爸是教师，我妈在厂里上班"}],
             "父母退休前各干什么") == [],
       "G1l content 为空时回落 content_dated 正常识别")


# ---------------------------------------------------------------- G2: writepipe received_at
def g2_writepipe_received_at(tmp_root: str):
    print("== G2 writepipe received_at 全通路透传与缺省兼容 ==")
    old_mode = os.environ.get(_am.AUTONOMY_ENV_KEYS["mode"])
    old_pol = os.environ.get("MDCG_POLICY_FILE")
    os.environ[_am.AUTONOMY_ENV_KEYS["mode"]] = "full"
    try:
        # G2a: 表结构与 _outlet_kwargs
        vals_set = writepipe._write_values({"a": {"received_at": _TS_1}, "verdict": None})
        vals_none = writepipe._write_values({"a": {}, "verdict": None})
        kw_d = writepipe._outlet_kwargs("direct", {"a": {"received_at": _TS_1}, "verdict": None})
        kw_g = writepipe._outlet_kwargs("gated", {"a": {"received_at": _TS_1}, "verdict": None})
        ok(vals_set.get("received_at") == _TS_1 and vals_none.get("received_at") is None
           and kw_d.get("received_at") == _TS_1 and kw_g.get("received_at") == _TS_1
           and "received_at" in writepipe._AUTONOMY_META_KEYS,
           "G2a _write_values / _OUTLET_PARAMS / _AUTONOMY_META_KEYS 均登记并透传 received_at")

        # G2b: cg(op="write", gated=False, received_at=_TS_1) 直写落盘 + recall 日期锚定
        cg = MdCGOS(os.path.join(tmp_root, "g2_direct"), actor="tester",
                    autoflush=0, async_flush=False)
        body1 = _CCG.format(name="直写收到时刻", cond="需要记录直写收到时刻",
                            body="我昨天去杭州参加了直写收到时刻演练")
        r_dir = mcp_server.call_tool(cg, "cg", {
            "op": "write", "node_id": "wp_dir_1", "content": body1,
            "content_kind": "text", "layer": "contextual",
            "received_at": _TS_1, "consistency": False,
        })
        n_dir = cg.get("wp_dir_1")
        fm_dir = (n_dir or {}).get("frontmatter") or {}
        ok(r_dir.get("committed") is True
           and abs(float(fm_dir.get("received_at") or 0) - _TS_1) < 1e-6,
           "G2b cg(op='write', gated=False, received_at=...) 落盘 frontmatter.received_at",
           {"resp": r_dir.get("committed"), "fm_ra": fm_dir.get("received_at")})

        # recall 使用 received_at 渲染 created_at_date 与 content_dated（「昨天」→ 2026-11-23）
        cg.flush()
        rec = cg.recall("直写收到时刻演练", budget_tokens=800, k=8)
        hit = next((e for e in (rec.get("pack") or []) if e.get("id") == "wp_dir_1"), None)
        ok(hit is not None and hit.get("created_at_date") == "2026-11-24"
           and "2026-11-23" in (hit.get("content_dated") or ""),
           "G2c cg(op='write') 落盘的 received_at 被 recall 用于日期戳与相对日期换算",
           {"date": (hit or {}).get("created_at_date"),
            "dated": ((hit or {}).get("content_dated") or "")[:90]})

        # G2d: cg(op="write", gated=True, received_at=_TS_2) gated 出口落盘（独立库避免与 wp_dir_1 模板重合触发 MERGE）
        cg_gat = MdCGOS(os.path.join(tmp_root, "g2_gated"), actor="tester",
                        autoflush=0, async_flush=False)
        body2 = _CCG.format(name="门控收到时刻", cond="需要记录门控收到时刻",
                            body="我昨天提交了门控收到时刻的独立核验报告")
        r_gat = mcp_server.call_tool(cg_gat, "cg", {
            "op": "write", "node_id": "wp_gat_1", "content": body2,
            "content_kind": "text", "layer": "contextual", "gated": True,
            "received_at": _TS_2, "consistency": False,
        })
        fm_gat = ((cg_gat.get("wp_gat_1") or {}).get("frontmatter") or {})
        ok(r_gat.get("committed") is True
           and abs(float(fm_gat.get("received_at") or 0) - _TS_2) < 1e-6,
           "G2d cg(op='write', gated=True, received_at=...) 落盘 frontmatter.received_at",
           {"resp": r_gat.get("committed"), "gate": r_gat.get("gate"),
            "fm_ra": fm_gat.get("received_at")})

        # G2e: 省略 received_at（None）保持老行为，回落 created_at
        body_none = _CCG.format(name="缺省收到时刻", cond="不传收到时刻时",
                                body="今天记录一条缺省收到时刻的普通笔记")
        r_none = mcp_server.call_tool(cg, "cg", {
            "op": "write", "node_id": "wp_none_1", "content": body_none,
            "content_kind": "text", "layer": "contextual", "consistency": False,
        })
        fm_none = ((cg.get("wp_none_1") or {}).get("frontmatter") or {})
        cg.flush()
        rec_none = cg.recall("缺省收到时刻的普通笔记", budget_tokens=800, k=8)
        hit_none = next((e for e in (rec_none.get("pack") or [])
                         if e.get("id") == "wp_none_1"), None)
        today = time.strftime("%Y-%m-%d")
        ok(r_none.get("committed") is True and fm_none.get("received_at") is None
           and (hit_none is None or hit_none.get("created_at_date") == today),
           "G2e 省略 received_at 时 fm.received_at 为 None 且 recall 回落 created_at",
           {"fm_ra": fm_none.get("received_at"),
            "date": (hit_none or {}).get("created_at_date")})

        # G2f: confirm 档下 direct C_REWRITE 出变更单 → review_decide(accept) 重放保住 received_at
        os.environ[_am.AUTONOMY_ENV_KEYS["mode"]] = "confirm"
        body_rew = _CCG.format(name="直写改写确认", cond="确认档下改写已有节点",
                               body="直写改写后的最新正文内容用于核验变更单重放")
        r_tkt = mcp_server.call_tool(cg, "cg", {
            "op": "write", "node_id": "wp_dir_1", "content": body_rew,
            "content_kind": "text", "layer": "contextual",
            "received_at": _TS_2, "consistency": False,
        })
        tkt_meta = ((r_tkt.get("mutation") or {}).get("meta") or {})
        pid1 = r_tkt.get("pid")
        ok(r_tkt.get("committed") is False
           and r_tkt.get("moved_to") == "review_queue"
           and bool(pid1)
           and abs(float(tkt_meta.get("received_at") or 0) - _TS_2) < 1e-6,
           "G2f-1 confirm 档 direct C_REWRITE 变更单 meta 携带 received_at",
           {"moved_to": r_tkt.get("moved_to"), "pid": pid1, "meta": tkt_meta})

        dec1 = cg.review_decide(pid1, "accept", reason="批准直写改写单")
        fm_after1 = ((cg.get("wp_dir_1") or {}).get("frontmatter") or {})
        ok(dec1.get("ok") is True
           and abs(float(fm_after1.get("received_at") or 0) - _TS_2) < 1e-6,
           "G2f-2 direct C_REWRITE 变更单 accept 重放后 frontmatter 保留 received_at",
           {"dec": dec1.get("ok"), "fm_ra": fm_after1.get("received_at")})

        # G2g: confirm 档下 gated C_REWRITE 出变更单 → accept 重放保住 received_at
        body_grew = (
            "# 功能名：南极科考站能源调度\n"
            "# 生效条件：极夜期间风力发电功率波动\n"
            "# 子功能：蓄电池组切换与备用柴油机预热\n"
            "# 执行：按负荷曲线在零下四十度环境分阶段切换储电回路，记录每次切换压降与油温\n"
            "# 验证方式：模拟断电演练\n"
            "# 不适用条件：极昼满负荷光伏直供阶段\n"
        )
        r_gtkt = mcp_server.call_tool(cg_gat, "cg", {
            "op": "write", "node_id": "wp_gat_1", "content": body_grew,
            "content_kind": "text", "layer": "contextual", "gated": True,
            "importance_hint": 0.8,
            "received_at": _TS_3, "consistency": False,
        })
        gtkt_meta = ((r_gtkt.get("mutation") or {}).get("meta") or {})
        pid2 = (r_gtkt.get("gate") or {}).get("pid") or r_gtkt.get("pid")
        ok(r_gtkt.get("committed") is False
           and r_gtkt.get("moved_to") == "review_queue"
           and bool(pid2)
           and abs(float(gtkt_meta.get("received_at") or 0) - _TS_3) < 1e-6,
           "G2g-1 confirm 档 gated C_REWRITE 变更单 meta 携带 received_at",
           {"moved_to": r_gtkt.get("moved_to"), "pid": pid2,
            "gate": r_gtkt.get("gate"), "meta": gtkt_meta})

        dec2 = cg_gat.review_decide(pid2, "accept", reason="批准门控改写单")
        fm_after2 = ((cg_gat.get("wp_gat_1") or {}).get("frontmatter") or {})
        ok(dec2.get("ok") is True
           and abs(float(fm_after2.get("received_at") or 0) - _TS_3) < 1e-6,
           "G2g-2 gated C_REWRITE 变更单 accept 重放后 frontmatter 保留 received_at",
           {"dec": dec2.get("ok"), "fm_ra": fm_after2.get("received_at")})

        # G2h: 审计 DEFER 入队 → accept 重放保住 received_at
        os.environ[_am.AUTONOMY_ENV_KEYS["mode"]] = "full"
        empty_pol = os.path.join(tmp_root, "empty_policy.json")
        with open(empty_pol, "w", encoding="utf-8") as fh:
            json.dump({"forbidden": [], "required": []}, fh)
        os.environ["MDCG_POLICY_FILE"] = empty_pol
        r_def = mcp_server.call_tool(cg, "cg", {
            "op": "write", "node_id": "wp_defer_1",
            "content": "空规则入队待审正文 77319",
            "content_kind": "text", "layer": "contextual",
            "received_at": _TS_3, "consistency": False,
        })
        pid3 = r_def.get("pid")
        dec3 = cg.review_decide(pid3, "accept", reason="批准审计入队提案") if pid3 else {}
        fm_def = ((cg.get("wp_defer_1") or {}).get("frontmatter") or {})
        ok(r_def.get("moved_to") == "review_queue" and dec3.get("ok") is True
           and abs(float(fm_def.get("received_at") or 0) - _TS_3) < 1e-6,
           "G2h 审计 DEFER 入队 → accept 重放同样保留 received_at",
           {"pid": pid3, "dec": dec3.get("ok"), "fm_ra": fm_def.get("received_at")})

        # G2i: hyperedge 写链回归（复现 test_hyperedge 路径：_outlet_kwargs 与 _hyperedge_extra
        # 不得对 received_at 双重传参，MdCGSecure.add 正常落盘且六列回放 ACCEPT）
        if old_pol is None:
            os.environ.pop("MDCG_POLICY_FILE", None)
        else:
            os.environ["MDCG_POLICY_FILE"] = old_pol
        os.environ[_am.AUTONOMY_ENV_KEYS["mode"]] = "full"
        row_std = {
            "received_at": "2026-09-17T16:40:07",
            "verify_id": "verify-fff1ce7-phase0", "commit": "fff1ce7",
            "verdict": "PASS", "receipt_job": "h1789634407680_445c",
            "iter_id": "iter-002-carrier-align",
        }
        row_sparse = {
            "received_at": "", "verify_id": "close-clean-batch",
            "commit": "", "verdict": "", "receipt_job": "",
            "iter_id": "iter-002-carrier-align",
        }
        p_std = hyperedge.row_from_ledger(row_std)
        a_he_std = {
            "op": "write", "node_id": hyperedge.node_id_for(row_std),
            "content_kind": "hyperedge", "content": p_std["content"],
            "layer": "knowledge", "tags": ["receipt"],
        }
        a_he_std.update(p_std["frontmatter"])
        kw_he_direct = writepipe._outlet_kwargs("direct", {"a": a_he_std, "verdict": None})
        ex_he_std = writepipe._hyperedge_extra(a_he_std)
        overlap_he = sorted((set(kw_he_direct) | {"layer"}) & set(ex_he_std))
        ok(not overlap_he and kw_he_direct.get("received_at") == row_std["received_at"],
           "G2i-1 hyperedge 场景 _outlet_kwargs('direct') 与 _hyperedge_extra 键集严格不交",
           {"overlap": overlap_he, "ra": kw_he_direct.get("received_at")})

        cg_he = MdCGSecure(
            os.path.join(tmp_root, "g2_hyperedge"),
            principal=Principal(tenant="default", actor="t_he", role="designer",
                                can_write=True, can_admin=True),
            autoflush=0, async_flush=False,
        )
        saved_ver = audit_mod.VERIFIERS.get(hyperedge.CONTENT_KIND)
        try:
            audit_mod.register_verifier(hyperedge.CONTENT_KIND,
                                        hyperedge.verify_payload, override=True)
            pipe_he = writepipe.install_default_gates(writepipe.WritePipeline())
            out_he = pipe_he.execute(cg_he, dict(a_he_std))
            rec_he = cg_he.get(a_he_std["node_id"]) or {}
            fm_he = rec_he.get("frontmatter") or {}
            ver_he = hyperedge.verify_payload(hyperedge.payload_from_node(rec_he))

            p_sp = hyperedge.row_from_ledger(row_sparse)
            a_he_sp = {
                "op": "write", "node_id": hyperedge.node_id_for(row_sparse),
                "content_kind": "hyperedge", "content": p_sp["content"],
                "layer": "knowledge", "tags": ["receipt"],
            }
            a_he_sp.update(p_sp["frontmatter"])
            out_sp = pipe_he.execute(cg_he, dict(a_he_sp))
            rec_sp = cg_he.get(a_he_sp["node_id"]) or {}
            fm_sp = rec_sp.get("frontmatter") or {}
            ver_sp = hyperedge.verify_payload(hyperedge.payload_from_node(rec_sp))

            ok(out_he.get("committed") is True
               and fm_he.get("received_at") == row_std["received_at"]
               and ver_he.get("state") == "ACCEPT"
               and out_sp.get("committed") is True
               and fm_sp.get("received_at") == ""
               and ver_sp.get("state") == "ACCEPT",
               "G2i-2 hyperedge 标准行与稀疏行经 writepipe 落 MdCGSecure 零重复传参且回放 ACCEPT",
               {"std_ok": out_he.get("committed"), "std_ra": fm_he.get("received_at"),
                "std_v": ver_he.get("state"), "sp_ok": out_sp.get("committed"),
                "sp_ra": fm_sp.get("received_at"), "sp_v": ver_sp.get("state")})

            # G2j: hyperedge 在 confirm 档 C_REWRITE 出单重放 + 未注册验证器 DEFER 重放均不重复传 received_at
            os.environ[_am.AUTONOMY_ENV_KEYS["mode"]] = "confirm"
            out_he_cfm = pipe_he.execute(cg_he, dict(a_he_std))
            pid_he_cfm = out_he_cfm.get("pid")
            dec_he_cfm = (cg_he.review_decide(pid_he_cfm, "accept", reason="批准超边改写")
                          if pid_he_cfm else {})
            fm_he_cfm = ((cg_he.get(a_he_std["node_id"]) or {}).get("frontmatter") or {})

            os.environ[_am.AUTONOMY_ENV_KEYS["mode"]] = "full"
            audit_mod.VERIFIERS.pop(hyperedge.CONTENT_KIND, None)
            row_def = dict(row_std, verify_id="verify-defer-he", receipt_job="h_defer_01")
            p_def = hyperedge.row_from_ledger(row_def)
            a_he_def = {
                "op": "write", "node_id": hyperedge.node_id_for(row_def),
                "content_kind": "hyperedge", "content": p_def["content"],
                "layer": "knowledge", "tags": ["receipt"],
            }
            a_he_def.update(p_def["frontmatter"])
            out_he_def = pipe_he.execute(cg_he, dict(a_he_def))
            pid_he_def = out_he_def.get("pid")
            dec_he_def = (cg_he.review_decide(pid_he_def, "accept", reason="批准超边入队")
                          if pid_he_def else {})
            fm_he_def = ((cg_he.get(a_he_def["node_id"]) or {}).get("frontmatter") or {})

            ok(out_he_cfm.get("moved_to") == "review_queue"
               and dec_he_cfm.get("ok") is True
               and fm_he_cfm.get("received_at") == row_std["received_at"]
               and out_he_def.get("moved_to") == "review_queue"
               and dec_he_def.get("ok") is True
               and fm_he_def.get("received_at") == row_def["received_at"],
               "G2j hyperedge 确认档变更单与 DEFER 入队 accept 重放均无重复 received_at 且保值",
               {"cfm": (out_he_cfm.get("moved_to"), dec_he_cfm.get("ok"), fm_he_cfm.get("received_at")),
                "def": (out_he_def.get("moved_to"), dec_he_def.get("ok"), fm_he_def.get("received_at"))})
        finally:
            if saved_ver is not None:
                audit_mod.VERIFIERS[hyperedge.CONTENT_KIND] = saved_ver
            else:
                audit_mod.VERIFIERS.pop(hyperedge.CONTENT_KIND, None)
            cg_he.close()
    finally:
        if old_mode is None:
            os.environ.pop(_am.AUTONOMY_ENV_KEYS["mode"], None)
        else:
            os.environ[_am.AUTONOMY_ENV_KEYS["mode"]] = old_mode
        if old_pol is None:
            os.environ.pop("MDCG_POLICY_FILE", None)
        else:
            os.environ["MDCG_POLICY_FILE"] = old_pol


# ---------------------------------------------------------------- G3: AST + 叶锁审计
def _audit_dirty_module(src: str, rel: str):
    """AST 审计单个模块：
    1. 收集所有不在 `_dirty_lock` 保护内的 `_dirty` 写/删/变更调用点
       （识别 `obj._dirty[...]` / 本地别名 `_dirty = getattr(obj, "_dirty", None)`、
       以及零新增 import 的 `if _dlock is not None: with _dlock: <stmt> else: <同构 stmt>`
       Mock 回退守卫）；
    2. 收集 `_dirty_lock` 块内一切违背纯叶锁纪律的禁止调用。
    """
    tree = ast.parse(src)
    unlocked_writes = []
    lock_inversions = []
    _MUT_METHODS = frozenset({"clear", "pop", "popitem", "update", "setdefault"})

    class _Visitor(ast.NodeVisitor):
        def __init__(self):
            self.fn_stack = []
            self.in_dirty_lock = 0
            self.dirty_aliases = set()
            self.lock_aliases = set()

        def _is_dirty_expr(self, node) -> bool:
            if isinstance(node, ast.Attribute) and node.attr == "_dirty":
                return True
            if isinstance(node, ast.Name) and node.id in self.dirty_aliases:
                return True
            return False

        def _is_lock_expr(self, node) -> bool:
            if isinstance(node, ast.Name) and node.id in self.lock_aliases:
                return True
            return "_dirty_lock" in ast.unparse(node)

        def _is_guarded_fallback_if(self, node: ast.If) -> bool:
            """判定是否为 `if _dlock is not None: with _dlock: <B> else: <B>` 的严格同构回退。"""
            test = node.test
            if not (isinstance(test, ast.Compare)
                    and len(test.ops) == 1 and isinstance(test.ops[0], ast.IsNot)
                    and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value is None
                    and isinstance(test.left, ast.Name)
                    and test.left.id in self.lock_aliases):
                return False
            if len(node.body) != 1 or not isinstance(node.body[0], ast.With):
                return False
            with_node = node.body[0]
            if not any(isinstance(i.context_expr, ast.Name)
                       and i.context_expr.id == test.left.id
                       for i in with_node.items):
                return False
            if not node.orelse:
                return False
            locked_stmts = [ast.unparse(s) for s in with_node.body]
            fallback_stmts = [ast.unparse(s) for s in node.orelse]
            return locked_stmts == fallback_stmts

        def visit_FunctionDef(self, node):
            prev_aliases = set(self.dirty_aliases)
            prev_locks = set(self.lock_aliases)
            self.dirty_aliases = set()
            self.lock_aliases = set()
            self.fn_stack.append(node.name)
            self.generic_visit(node)
            self.fn_stack.pop()
            self.dirty_aliases = prev_aliases
            self.lock_aliases = prev_locks

        def visit_Assign(self, node):
            # 识别 `_dirty = getattr(cg, "_dirty", ...)` / `_dlock = getattr(cg, "_dirty_lock", ...)`
            val = node.value
            binds_dirty = False
            binds_lock = False
            if isinstance(val, ast.Attribute) and val.attr == "_dirty":
                binds_dirty = True
            elif isinstance(val, ast.Attribute) and val.attr == "_dirty_lock":
                binds_lock = True
            elif (isinstance(val, ast.Call) and isinstance(val.func, ast.Name)
                  and val.func.id == "getattr" and len(val.args) >= 2
                  and isinstance(val.args[1], ast.Constant)):
                if val.args[1].value == "_dirty":
                    binds_dirty = True
                elif val.args[1].value == "_dirty_lock":
                    binds_lock = True
            if binds_dirty:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.dirty_aliases.add(t.id)
            if binds_lock:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.lock_aliases.add(t.id)
            for t in node.targets:
                if isinstance(t, ast.Subscript) and self._is_dirty_expr(t.value):
                    if self.in_dirty_lock == 0:
                        unlocked_writes.append((rel, ".".join(self.fn_stack), node.lineno))
            self.generic_visit(node)

        def visit_Delete(self, node):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and self._is_dirty_expr(t.value):
                    if self.in_dirty_lock == 0:
                        unlocked_writes.append((rel, ".".join(self.fn_stack), node.lineno))
            self.generic_visit(node)

        def visit_Call(self, node):
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr in _MUT_METHODS
                    and self._is_dirty_expr(node.func.value)):
                if self.in_dirty_lock == 0:
                    unlocked_writes.append((rel, ".".join(self.fn_stack), node.lineno))
            if self.in_dirty_lock > 0:
                fname = None
                if isinstance(node.func, ast.Name):
                    fname = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    fname = node.func.attr
                if fname in _FORBIDDEN_IN_DIRTY_LOCK:
                    lock_inversions.append((rel, ".".join(self.fn_stack), node.lineno, fname))
            self.generic_visit(node)

        def visit_If(self, node):
            if self._is_guarded_fallback_if(node):
                # 严格验证加锁分支（持锁深度 + 叶锁禁止调用）；orelse 仅在 _dlock is None 时运行
                # 且已由 _is_guarded_fallback_if 证明与锁内语句逐句同构。
                self.visit(node.test)
                for stmt in node.body:
                    self.visit(stmt)
                return
            self.generic_visit(node)

        def visit_With(self, node):
            is_dl = any(self._is_lock_expr(i.context_expr) for i in node.items)
            if is_dl:
                self.in_dirty_lock += 1
            self.generic_visit(node)
            if is_dl:
                self.in_dirty_lock -= 1

    _Visitor().visit(tree)
    return unlocked_writes, lock_inversions


def g3_ast_dirty_lock_audit():
    print("== G3 静态 AST 锁护与纯叶锁审计（4 模块 + 变异自证 + 零新依赖）==")
    all_unlocked = []
    all_inversions = []
    contextlib_imports = []
    sources = {}
    for rel in _DIRTY_MODULES:
        path = os.path.join(_REPO, rel.replace("/", os.sep))
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        sources[rel] = src
        u, inv = _audit_dirty_module(src, rel)
        all_unlocked.extend(u)
        all_inversions.extend(inv)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "contextlib":
                contextlib_imports.append(rel)
            elif isinstance(node, ast.Import) and any(a.name == "contextlib" for a in node.names):
                contextlib_imports.append(rel)

    ok(not all_unlocked,
       "G3a AST 审计：scrub/protect/rollback/writelimit 零处锁外 _dirty 写/删/变更",
       all_unlocked)
    ok(not all_inversions,
       "G3b AST 叶锁审计：4 模块 _dirty_lock 内零 flush/IO/FileLock/add 锁序倒置",
       all_inversions)
    ok(not contextlib_imports,
       "G3e 零新增顶层依赖：4 模块均不导入 contextlib（保住 #190 S1.4 白名单）",
       contextlib_imports)

    # G3c: 内存变异自证 —— 对全部 4 个模块逐一撤掉 if _dlock / with _dlock，审计必须全部检出
    mut_hits = {}
    for rel, src in sources.items():
        lines = src.splitlines()
        mut_lines = []
        i = 0
        while i < len(lines):
            ln = lines[i]
            if ln.strip() == "if _dlock is not None:" and i + 4 < len(lines):
                indent = ln[:len(ln) - len(ln.lstrip())]
                stmt = lines[i + 2].strip()
                mut_lines.append(indent + stmt)
                i += 5
                continue
            mut_lines.append(ln)
            i += 1
        u_mut, _ = _audit_dirty_module("\n".join(mut_lines), rel)
        mut_hits[rel] = len(u_mut)
    ok(mut_hits == {
        "md_cg/scrub.py": 1,
        "md_cg/protect.py": 1,
        "md_cg/rollback.py": 1,
        "md_cg/writelimit.py": 2,
    }, "G3c 变异自证：撤锁后准确检出全部 5 处写点（1+1+1+2）", mut_hits)

    # G3d: 内存变异自证 —— 把 flush() 注入 protect.py 的 _dirty_lock 内，叶锁审计必检出
    inv_src = sources["md_cg/protect.py"].replace(
        "            if _dlock is not None:\n"
        "                with _dlock:\n"
        "                    _dirty[node_id] = e",
        "            if _dlock is not None:\n"
        "                with _dlock:\n"
        "                    _dirty[node_id] = e\n"
        "                    _flush()",
        1,
    )
    _, inv_mut = _audit_dirty_module(inv_src, "md_cg/protect.py")
    ok(any(fn == "_flush" for _r, _f, _ln, fn in inv_mut),
       "G3d 叶锁变异自证：把 _flush() 误入 _dirty_lock 时立即检出锁序倒置", inv_mut)


# ---------------------------------------------------------------- G4: 运行时持锁深度
def g4_runtime_lock_depth_observation(tmp_root: str):
    print("== G4 运行时持锁深度与纯叶锁实测（全部 5 处写点）==")
    cg = MdCGOS(os.path.join(tmp_root, "g4_obs"), actor="obs",
                autoflush=1000, async_flush=False)
    try:
        cg.add("s1", _CCG.format(name="校准样本", cond="校准测试", body="校准测试样本正文"),
               layer="knowledge", verification_basis="test", consistency=False)
        cg.verify("s1", "unit ok", "confirmed")
        cg.add("p1", _CCG.format(name="打标样本", cond="打标测试", body="保护打标测试样本"),
               layer="contextual", consistency=False)
        cg.add("r1", _CCG.format(name="回滚样本", cond="回滚测试", body="回滚落盘测试样本"),
               layer="contextual", consistency=False)
        cg.add("w1", _CCG.format(name="聚合样本", cond="聚合测试", body="同构聚合目标正文"),
               layer="contextual", consistency=False)
        cg.add("w2", _CCG.format(name="降权样本", cond="降权测试", body="同构降权成员正文"),
               layer="contextual", consistency=False)
        cg.flush()

        lock, log = _attach_observer(cg)
        wn_depths = []
        fl_depths = []
        ne_depths = []
        orig_wn = cg._write_node
        orig_fl = cg.flush
        orig_ne = cg._node_entry

        def _obs_wn(*a, **k):
            wn_depths.append(lock.depth)
            return orig_wn(*a, **k)

        def _obs_fl(*a, **k):
            fl_depths.append(lock.depth)
            return orig_fl(*a, **k)

        def _obs_ne(*a, **k):
            ne_depths.append(lock.depth)
            return orig_ne(*a, **k)

        cg._write_node = _obs_wn
        cg.flush = _obs_fl
        cg._node_entry = _obs_ne
        try:
            # G4a: scrub._apply_offset
            log.clear()
            wn_depths.clear()
            adj, _skip = scrub._apply_offset(cg, -0.05, min_evidence=1, actor="obs")
            sets = [d for op, k, d in log if op == "__setitem__" and k == "s1"]
            ok(adj >= 1 and sets and all(d >= 1 for d in sets)
               and wn_depths and all(d == 0 for d in wn_depths),
               "G4a scrub._apply_offset：写 _dirty 时 depth>=1，_write_node 时 depth==0",
               {"adj": adj, "sets": sets, "wn": wn_depths})

            # G4b: protect.mark（同时实证 flush 在锁外）
            log.clear()
            wn_depths.clear()
            fl_depths.clear()
            mres = protect.mark(cg, "p1", "关键基准节点")
            sets = [d for op, k, d in log if op == "__setitem__" and k == "p1"]
            ok(mres.get("protected") is True and sets and all(d >= 1 for d in sets)
               and wn_depths and all(d == 0 for d in wn_depths)
               and fl_depths and all(d == 0 for d in fl_depths),
               "G4b protect.mark：写 _dirty 时 depth>=1，_write_node 与 flush() 均 depth==0",
               {"sets": sets, "wn": wn_depths, "fl": fl_depths})

            # G4c: rollback._land
            log.clear()
            wn_depths.clear()
            ne_depths.clear()
            n_r1 = cg.get("r1")
            r1_path = os.path.join(cg.root, n_r1["path"])
            lres = rollback._land(cg, "r1", r1_path, dict(n_r1["frontmatter"]),
                                  (n_r1.get("content") or "") + "\n已回滚校验\n")
            sets = [d for op, k, d in log if op == "__setitem__" and k == "r1"]
            ok(lres is None and sets and all(d >= 1 for d in sets)
               and wn_depths and all(d == 0 for d in wn_depths)
               and ne_depths and all(d == 0 for d in ne_depths),
               "G4c rollback._land：写 _dirty 时 depth>=1，_write_node/_node_entry 均 depth==0",
               {"sets": sets, "wn": wn_depths, "ne": ne_depths})

            # G4d: writelimit.converge_into
            log.clear()
            wn_depths.clear()
            cres = writelimit.converge_into(cg, "w1", "追加一行同构聚合内容")
            sets = [d for op, k, d in log if op == "__setitem__" and k == "w1"]
            ok(cres.get("ok") is True and sets and all(d >= 1 for d in sets)
               and wn_depths and all(d == 0 for d in wn_depths),
               "G4d writelimit.converge_into：写 _dirty 时 depth>=1，_write_node 时 depth==0",
               {"sets": sets, "wn": wn_depths})

            # G4e: writelimit._demote
            log.clear()
            wn_depths.clear()
            n_w2 = cg.get("w2")
            writelimit._demote(cg, n_w2, actor="obs")
            sets = [d for op, k, d in log if op == "__setitem__" and k == "w2"]
            ok(sets and all(d >= 1 for d in sets)
               and wn_depths and all(d == 0 for d in wn_depths),
               "G4e writelimit._demote：写 _dirty 时 depth>=1，_write_node 时 depth==0",
               {"sets": sets, "wn": wn_depths})
        finally:
            cg._write_node = orig_wn
            cg.flush = orig_fl
            cg._node_entry = orig_ne
    finally:
        cg.close()


# ---------------------------------------------------------------- G5: Mock 安全 + 竞态消除 + 压测
def g5_mock_safety_and_concurrency(tmp_root: str):
    print("== G5 Mock 安全、确定性 flush 竞态消除与多线程压测 ==")

    # G5a: 无 _dirty_lock 的极简 stub cg 在全部 5 处写点均不报错
    stub_root = os.path.join(tmp_root, "g5_stub")
    os.makedirs(stub_root, exist_ok=True)

    def _mk_stub(nid, layer="contextual", ev_count=2):
        rel_p = f"{nid}.md"
        full_p = os.path.join(stub_root, rel_p)
        fm = {
            "id": nid, "layer": layer, "confidence": 0.7, "importance": 0.5,
            "evidence_count": ev_count, "tags": [],
        }
        body = f"stub body {nid}\n"
        with open(full_p, "w", encoding="utf-8") as fh:
            fh.write(nodefile.dumps(fm, body))
        entry = {
            "path": rel_p, "layer": layer, "confidence": 0.7,
            "importance": 0.5, "evidence_count": ev_count, "tags": [],
        }
        stub = types.SimpleNamespace(
            root=stub_root,
            index={"nodes": {nid: entry}},
            _dirty={},
            actor="stub",
        )

        def _get(k):
            if k != nid:
                return None
            return {"id": nid, "path": rel_p, "frontmatter": dict(fm), "content": body}

        def _wn(_nid, path, new_fm, new_body, **_kw):
            fm.clear()
            fm.update(new_fm)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(nodefile.dumps(new_fm, new_body))
            return new_body

        def _ne(_path, _layer, new_fm, _body):
            return dict(entry, layer=_layer, tags=list(new_fm.get("tags") or []))

        stub.get = _get
        stub._write_node = _wn
        stub._node_entry = _ne
        return stub, full_p, fm

    st_s, _, _ = _mk_stub("st_s", layer="knowledge", ev_count=2)
    adj_s, _ = scrub._apply_offset(st_s, -0.05, min_evidence=1)
    st_p, _, _ = _mk_stub("st_p")
    pm_s = protect.mark(st_p, "st_p", "stub mark")
    st_r, st_r_path, st_r_fm = _mk_stub("st_r")
    rb_s = rollback._land(st_r, "st_r", st_r_path, dict(st_r_fm), "landed\n")
    st_w1, _, _ = _mk_stub("st_w1")
    cv_s = writelimit.converge_into(st_w1, "st_w1", "stub merge line")
    st_w2, _, _ = _mk_stub("st_w2")
    writelimit._demote(st_w2, st_w2.get("st_w2"))

    ok(adj_s == 1 and "st_s" in st_s._dirty
       and pm_s.get("protected") is True and "st_p" in st_p._dirty
       and rb_s is None and "st_r" in st_r._dirty
       and cv_s.get("ok") is True and "st_w1" in st_w1._dirty
       and "st_w2" in st_w2._dirty,
       "G5a 无 _dirty_lock 的极简 stub cg 在全部 5 处写点均安全写入 _dirty",
       {"s": "st_s" in st_s._dirty, "p": "st_p" in st_p._dirty,
        "r": "st_r" in st_r._dirty, "w1": "st_w1" in st_w1._dirty,
        "w2": "st_w2" in st_w2._dirty})

    # G5b: 确定性 flush 迭代竞态测试（逐点验证 5 处写点在 flusher 持 _dirty_lock 迭代期间
    # 不会触发 RuntimeError，且写点等待锁释放后安全标脏不丢失）
    race_results = []
    for case_name in ("scrub", "protect", "rollback", "converge", "demote"):
        cg = MdCGOS(os.path.join(tmp_root, f"g5_det_{case_name}"), actor="det",
                    autoflush=1000, async_flush=False)
        try:
            cg.add("target", _CCG.format(name="目标", cond="竞态测试", body="目标节点初始内容"),
                   layer="knowledge" if case_name == "scrub" else "contextual",
                   verification_basis="test", consistency=False)
            if case_name == "scrub":
                cg.verify("target", "ok", "confirmed")
            cg.flush()
            # 放两条待刷条目，确保 target 不在 _dirty 中（插入 target 会改变 dict 大小）
            cg.add("d1", _CCG.format(name="脏1", cond="c1", body="待刷1"),
                   layer="contextual", consistency=False)
            cg.add("d2", _CCG.format(name="脏2", cond="c2", body="待刷2"),
                   layer="contextual", consistency=False)

            orig_items = cg._dirty.items
            iter_entered = threading.Event()
            iter_release = threading.Event()
            paused_once = [False]

            def _slow_items(_oi=orig_items, _ie=iter_entered,
                            _ir=iter_release, _po=paused_once, _d=cg._dirty):
                it = iter(dict.items(_d))
                first = next(it, None)
                if first is not None:
                    yield first
                if not _po[0]:
                    _po[0] = True
                    _ie.set()
                    _ir.wait(timeout=3.0)
                yield from it

            cg._dirty.items = _slow_items
            fl_err = []
            wr_err = []
            wr_done = threading.Event()

            def _flusher(_cg=cg, _fe=fl_err):
                try:
                    _cg.flush()
                except Exception as exc:  # noqa: BLE001
                    _fe.append((type(exc).__name__, str(exc)))

            def _writer(_cg=cg, _cn=case_name, _we=wr_err, _wd=wr_done):
                try:
                    if _cn == "scrub":
                        scrub._apply_offset(_cg, -0.05, min_evidence=1)
                    elif _cn == "protect":
                        protect.mark(_cg, "target", "race mark")
                    elif _cn == "rollback":
                        nt = _cg.get("target")
                        rollback._land(_cg, "target", os.path.join(_cg.root, nt["path"]),
                                       dict(nt["frontmatter"]),
                                       (nt.get("content") or "") + "\nrace land\n")
                    elif _cn == "converge":
                        writelimit.converge_into(_cg, "target", "race converge line")
                    elif _cn == "demote":
                        writelimit._demote(_cg, _cg.get("target"))
                except Exception as exc:  # noqa: BLE001
                    _we.append((type(exc).__name__, str(exc)))
                finally:
                    _wd.set()

            tf = threading.Thread(target=_flusher, name=f"fl_{case_name}")
            tf.start()
            entered = iter_entered.wait(timeout=3.0)
            tw = threading.Thread(target=_writer, name=f"wr_{case_name}")
            tw.start()
            # 给写者时间跑到 `_dirty_lock` 处并被阻塞（若无锁会直接插入引发 RuntimeError）
            blocked_while_flushing = not wr_done.wait(timeout=0.08)
            iter_release.set()
            tf.join(timeout=5.0)
            tw.join(timeout=5.0)
            cg._dirty.items = orig_items
            # protect.mark 自己带末尾 flush，所以它标脏并刷盘完毕；其余 4 处 target 必须留在 _dirty
            with cg._dirty_lock:
                still_dirty = "target" in cg._dirty
            dirty_ok = True if case_name == "protect" else still_dirty
            race_results.append((
                case_name, entered, blocked_while_flushing,
                fl_err, wr_err, dirty_ok,
            ))
        finally:
            cg.close()

    ok(all(en and blk and not fe and not we and dok
           for _c, en, blk, fe, we, dok in race_results),
       "G5b 确定性 flush 竞态：5 处写点均等待 _dirty_lock 释放、零 RuntimeError 且零丢脏项",
       race_results)

    # G5c: 真多线程并发压测
    cg_mt = MdCGOS(os.path.join(tmp_root, "g5_mt"), actor="mt",
                   autoflush=1, async_flush=True)
    try:
        cg_mt.add("mt_scrub", _CCG.format(name="压测校准", cond="mt", body="校准压测节点"),
                  layer="knowledge", verification_basis="test", consistency=False)
        cg_mt.verify("mt_scrub", "ok", "confirmed")
        cg_mt.add("mt_prot", _CCG.format(name="压测保护", cond="mt", body="保护压测节点"),
                  layer="contextual", consistency=False)
        cg_mt.add("mt_rb", _CCG.format(name="压测回滚", cond="mt", body="回滚压测节点"),
                  layer="contextual", consistency=False)
        cg_mt.add("mt_wl1", _CCG.format(name="压测聚合", cond="mt", body="聚合压测节点"),
                  layer="contextual", consistency=False)
        cg_mt.add("mt_wl2", _CCG.format(name="压测降权", cond="mt", body="降权压测节点"),
                  layer="contextual", consistency=False)
        cg_mt.flush()

        stop = threading.Event()
        errors = []
        err_lk = threading.Lock()

        def _rec_err(who, exc):
            with err_lk:
                errors.append((who, type(exc).__name__, str(exc)))

        def _t_flusher():
            try:
                while not stop.is_set():
                    cg_mt.flush()
                    time.sleep(0.002)
            except Exception as exc:  # noqa: BLE001
                _rec_err("flusher", exc)

        def _t_scrub():
            try:
                for i in range(12):
                    scrub._apply_offset(cg_mt, -0.02 if i % 2 == 0 else 0.02, min_evidence=1)
            except Exception as exc:  # noqa: BLE001
                _rec_err("scrub", exc)

        def _t_prot():
            try:
                for i in range(12):
                    protect.mark(cg_mt, "mt_prot", f"mt_reason_{i}")
            except Exception as exc:  # noqa: BLE001
                _rec_err("protect", exc)

        def _t_rb():
            try:
                n0 = cg_mt.get("mt_rb")
                p0 = os.path.join(cg_mt.root, n0["path"])
                fm0 = dict(n0["frontmatter"])
                for i in range(12):
                    rollback._land(cg_mt, "mt_rb", p0, dict(fm0), f"rb body {i}\n")
            except Exception as exc:  # noqa: BLE001
                _rec_err("rollback", exc)

        def _t_wl():
            try:
                for i in range(12):
                    writelimit.converge_into(cg_mt, "mt_wl1", f"mt line {i}")
                    n2 = cg_mt.get("mt_wl2")
                    if n2:
                        writelimit._demote(cg_mt, n2)
            except Exception as exc:  # noqa: BLE001
                _rec_err("writelimit", exc)

        fl_th = threading.Thread(target=_t_flusher, name="mt_flusher")
        workers = [
            threading.Thread(target=_t_scrub, name="mt_scrub"),
            threading.Thread(target=_t_prot, name="mt_prot"),
            threading.Thread(target=_t_rb, name="mt_rb"),
            threading.Thread(target=_t_wl, name="mt_wl"),
        ]
        fl_th.start()
        for th in workers:
            th.start()
        for th in workers:
            th.join(timeout=30.0)
        stop.set()
        fl_th.join(timeout=15.0)
        cg_mt.flush()

        alive = [th.name for th in [fl_th, *workers] if th.is_alive()]
        ok(not alive and not errors,
           "G5c 多线程压测：5 处写点与 flush 并发碰撞零死锁、零异常",
           {"alive": alive, "errors": errors[:5]})
    finally:
        cg_mt.close()


def main():
    tmp_root = tempfile.mkdtemp(prefix="cov_wp_dlock_run_", dir=_SANDBOX)
    try:
        g1_coverage_slot_gaps()
        g2_writepipe_received_at(tmp_root)
        g3_ast_dirty_lock_audit()
        g4_runtime_lock_depth_observation(tmp_root)
        g5_mock_safety_and_concurrency(tmp_root)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    print()
    print("覆盖/写链/脏集锁护守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for name in _FAIL:
            print("  - " + name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
