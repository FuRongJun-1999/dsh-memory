# -*- coding: utf-8 -*-
"""md_cg · issue #411 守卫：去污染「动作全败」不进幂等账本（ok 判据=真处置）

缺陷（修复前，本守卫红态实跑）：`scrub.decontaminate` 对每个 issue 的
try/except 把失败动作记成 `weaken_failed:AccessDenied` /
`demote_failed:AccessDenied`（留痕正确），但随后**无条件** `n_applied += 1`
并写单条台账 `ok=True`（修前 `md_cg/scrub.py:737-739`）。`_handled` 只认
`op=="decontaminate"` 且 `ok` 为真的单条记录 ⇒ 无权身份（sustain，
`layers_allow=("self",)`）跑一轮**全败**的 decontaminate 后，该
(节点, 污染类型) 进入幂等名单——此后**任何轮次、任何身份（含有权身份）**
都在已处置检查处提前 skip，处置在该库余生永不发生；审计面同时写
`ok=true` + `applied=1` 掩盖零改写（issue #411 实测：轮 1 sustain 全败
入账，轮 2 designer 得「已处置过（幂等）」+ 盘面一个字节没变）。

修复（最小改动 · 写账端单点）：done 含成功的 weaken/demote 才算「真处置」
——计 `applied`、单条台账 `ok=True`（进幂等名单）；全败计 `failed`、
`ok=False`（**不进名单**），下轮仍会动手。`_handled` 读法不动（仍只认
ok——两处只改一处，防判据分叉）。覆盖账由五键扩成六键（+`failed`），
互斥分类口径不变。

守卫（三组端到端 + 隔离，全临时库 + 哑主密钥 + 临时令牌库，绝不触真实
~/.mdcg；轮次全走**真实分发面** `cg(op=scrub, action=decontaminate,
dry_run=false)`）：
  ⓿ 隔离自证 + 夹具（knowledge 层 expired/high 实靶，audit 可见）；
  ① 轮1 · sustain（无权）：盘面零变化；单条台账该行 `ok is not True`
     （修前 = True ⇒ 永久占位）；回执 `applied=0 / failed=1`、逐条动作
     `action=="failed"`、失败原因（AccessDenied）显式可见；批量行
     覆盖账 `{applied:0, failed:1}`；
  ② 轮2 · designer（有权）同靶：`applied=1 / already_handled=0` 且盘面
     真的变了（weaken 0.5→0.35、负例 +1、降级 contextual）——修前 =
     `already_handled=1` + 零变化（永久跳过）；轮 2 单条台账 `ok=True`
     （真处置才进名单，判据对正例同样成立）；
  ③ 轮3 · designer 再轮：幂等名单本身仍工作——`already_handled=1 /
     applied=0`，盘面保持轮 2 的处置态（修的是**喂名单的判据**，不是名单）。

变异自证（唯一替换，非唯一即拒绝；经 sys.modules + 包属性双换注入，
分发面 `from . import scrub` 调用期解析到变异体）：
  M1 单条台账 ok 改回常量 True ⇒ 恰好打中 ①台账腿 + ②③轮（红项组
     {G1, G2, G3}）；M2 n_applied 改回无条件计数 ⇒ 恰好打中 ①回执/
     覆盖账计数腿（红项组 {G1}）。无连带、无漏网。

诚实边界：守卫只构造「权限不足 ⇒ 全败」一种成因；其它成因（节点消失、
写盘 OSError 等）与 AccessDenied 走同一 except→写账路径（读码确认，
未逐个构造）。dry_run 路径不写单条台账（不受影响，读码确认，未实跑）。

实测（本机）：修前 7 passed / 7 failed（红腿 = 1c/1d/1e/2a/2b/2c/3b——
轮 1 台账 ok=true 全败入账、轮 2 designer 得「已处置过（幂等）」+ 盘面
零改写，与 issue #411 读数逐字一致）；修后 14 passed / 0 failed（live=8）。

运行：
  python -X utf8 -m md_cg.test_issue411_scrub_idempotent_on_failure
  python -X utf8 -m md_cg.test_issue411_scrub_idempotent_on_failure --mutate M1
  python -X utf8 -m md_cg.test_issue411_scrub_idempotent_on_failure --mutate M2
"""
from __future__ import annotations

import atexit
import contextlib
import json
import os
import shutil
import sys
import tempfile
import time
import types

# ── 隔离前置：必须在 import md_cg 子模块**之前**（tokens/theory 等在模块级
# 把 aux_root() 冻成常量）——否则会指到真实 ~/.mdcg 并在那里建密钥/令牌库。 ──
_TMP = tempfile.mkdtemp(prefix="i411_")
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

from . import mcp_server, scrub as _scrub, tokens   # noqa: E402
from .datapath import aux_root                      # noqa: E402
from .mdcos import MdCGSecure                       # noqa: E402
from .security import Principal                     # noqa: E402

atexit.register(lambda: _cleanup(_TMP))       # LIFO：晚于库层 _atexit_flush_all

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.join(_TMP, "cgroot")
LIVE_FLOOR = 8
PASS = FAIL = LIVE = 0
FAILS = []
_OPEN = []


def check(group, name, cond, detail="", live=False):
    global PASS, FAIL, LIVE
    if live:
        LIVE += 1
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        FAILS.append((group, name))
        print("  [FAIL] %s · %s" % (name, detail))


def _princ(role, clearance="internal", can_admin=False):
    spec = tokens.role_spec(role)
    return Principal(tenant="default", actor="i411-" + role,
                     clearance=clearance, can_write=bool(spec["can_write"]),
                     can_admin=can_admin, role=role,
                     layers_allow=spec["layers_allow"],
                     ops_allow=spec["ops_allow"], auth_mode="test")


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


def _ledger_rows():
    p = os.path.join(ROOT, _scrub.SCRUB_LOG)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _row(rows, op, node_id, kind):
    return [r for r in rows if r.get("op") == op and r.get("node_id") == node_id
            and r.get("kind") == kind]


def _fm(cg, nid):
    node = cg.get(nid) or {}
    f = node.get("frontmatter") or {}
    return {"confidence": f.get("confidence"), "layer": f.get("layer"),
            "negative_evidence": f.get("negative_evidence")}


def _disk_layers(nid):
    """盘上真实所在层（不依赖索引快照：降级断言必须看文件系统）。"""
    out = []
    for r, _d, files in os.walk(ROOT):
        if nid + ".md" in files:
            seg = os.path.relpath(r, ROOT).replace("\\", "/").split("/")[0]
            if seg not in out:
                out.append(seg)
    out.sort()
    return out


@contextlib.contextmanager
def _patched_scrub(mod):
    """变异注入：sys.modules + 包属性双换——分发面 `from . import scrub`
    在调用期经包属性解析，故两处都要换（只换 sys.modules 不够）。"""
    pkg = sys.modules["md_cg"]
    old_mod = sys.modules.get("md_cg.scrub")
    old_attr = getattr(pkg, "scrub", None)
    sys.modules["md_cg.scrub"] = mod
    setattr(pkg, "scrub", mod)
    try:
        yield
    finally:
        if old_mod is not None:
            sys.modules["md_cg.scrub"] = old_mod
        if old_attr is not None:
            setattr(pkg, "scrub", old_attr)


def _round(role, nid, scrub_mod):
    """一轮真实分发面调用：cg(op=scrub, action=decontaminate, dry_run=false)。"""
    cg = _secured(_princ(role, can_admin=(role == "designer")))
    try:
        with _patched_scrub(scrub_mod):
            out = mcp_server.call_tool(cg, "cg",
                                       {"op": "scrub",
                                        "action": "decontaminate",
                                        "node_ids": [nid], "kinds": ["expired"],
                                        "dry_run": False,
                                        "actor": "i411-" + role})
        return cg, out
    except Exception as exc:                   # noqa: BLE001 —— 守卫要的是形态
        return cg, exc


# --------------------------------------------------------------------------
# 定点变异
# --------------------------------------------------------------------------

def _mutation_table():
    here = os.path.dirname(os.path.abspath(__file__))
    scrub_p = os.path.join(here, "scrub.py")
    return {
        # 单条台账 ok 改回常量 True（修前形态）：全败尝试重新污染幂等名单
        "M1": (scrub_p,
               '''        _log(cg, "decontaminate", node_id=nid, kind=kind, ok=bool(_did),
             actions=done, severity=issue["severity"], actor=actor)''',
               '''        _log(cg, "decontaminate", node_id=nid, kind=kind, ok=True,
             actions=done, severity=issue["severity"], actor=actor)''',
               {"G1", "G2", "G3"},
               "台账 ok 改回常量 True：全败尝试重新进幂等名单（#411 复发）"),
        # n_applied 改回无条件计数（修前形态）：零改写仍报 applied=1
        "M2": (scrub_p,
               '''        n_applied += 1 if _did else 0''',
               '''        n_applied += 1''',
               {"G1"},
               "n_applied 改回无条件计数：零改写仍冒充 applied（审计面失真）"),
    }


def _load_mutated(path, old, new, name):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    n = src.count(old)
    if n != 1:
        raise SystemExit(f"变异目标在源码中出现 {n} 次（须恰 1 次）：{name}")
    mod = types.ModuleType(name)
    mod.__package__ = "md_cg"          # 相对导入仍解析到真包
    mod.__file__ = path
    exec(compile(src.replace(old, new, 1), path, "exec"), mod.__dict__)
    return mod


# --------------------------------------------------------------------------
# 断言面
# --------------------------------------------------------------------------

def run_rounds(sc):
    global PASS, FAIL, FAILS
    PASS = FAIL = 0
    FAILS = []
    k_exp = "k_exp"

    print("[0] 隔离自证 + 夹具")
    _tok = tokens.token_file()
    check("G0", "0a 默认令牌库与 aux 根都落在守卫临时目录（绝不触真实凭据）",
          os.path.abspath(_tok).lower().startswith(os.path.abspath(_TMP).lower())
          and os.path.abspath(aux_root()).lower().startswith(
              os.path.abspath(_TMP).lower()),
          "tok=%s aux=%s" % (_tok, aux_root()))
    if not os.path.abspath(ROOT).lower().startswith(os.path.abspath(_TMP).lower()):
        print("FATAL: 隔离失败，中止（绝不带病跑真实库）")
        return 2

    designer = _secured(_princ("designer", can_admin=True))
    designer.add(k_exp, "# 正文：issue #411 时效探针\n", layer="knowledge",
                 confidence=0.5, valid_until=time.time() - 86400 * 30)
    _rep0 = sc.audit(designer, [k_exp])
    check("G0", "0b 夹具就位：knowledge 层 expired/high 实靶（audit 可见）",
          any(i["node_id"] == k_exp and i["kind"] == "expired"
              for i in _rep0["issues"]),
          "issues=%s" % [(i["node_id"], i["kind"]) for i in _rep0["issues"]])

    # ---------- ① 轮1 · sustain（无权）：全败不占幂等名额 ----------
    print("[1] 轮1 · sustain（layers=('self',)）真实分发面：全败尝试")
    sus, out1 = _round("sustain", k_exp, sc)
    fm1 = _fm(sus, k_exp)
    acts1 = out1.get("actions") if isinstance(out1, dict) else []
    a1 = acts1[0] if isinstance(acts1, list) and acts1 else {}
    rows1 = _row(_ledger_rows(), "decontaminate", k_exp, "expired")
    check("G1", "1a 调用被受理（scrub ∈ sustain ops_allow）：轮级回执 ok 且 "
          "检查到该 issue",
          isinstance(out1, dict) and out1.get("ok") is True
          and out1.get("n_issues", 0) >= 1,
          "out=%s" % str(out1)[:80])
    check("G1", "1b 盘面零变化：confidence=0.5 / 负例=0 / 层=knowledge"
          "（文件系统核实）",
          fm1 == {"confidence": 0.5, "layer": "knowledge",
                  "negative_evidence": 0}
          and _disk_layers(k_exp) == ["knowledge"],
          "fm=%s disk=%s" % (fm1, _disk_layers(k_exp)), live=True)
    check("G1", "1c 单条台账该行 ok is not True（修前 = True ⇒ 该污染被永久"
          "写进幂等名单）",
          len(rows1) == 1 and rows1[0].get("ok") is not True,
          "rows=%s" % rows1, live=True)
    check("G1", "1d 回执按真处置计数：applied=0 / failed=1 / "
          "already_handled=0；逐条动作 action=failed、applied=False，失败"
          "原因（AccessDenied）显式可见",
          isinstance(out1, dict) and out1.get("applied") == 0
          and out1.get("failed") == 1 and out1.get("already_handled") == 0
          and a1.get("action") == "failed" and a1.get("applied") is False
          and "weaken_failed:AccessDenied" in (a1.get("done") or [])
          and "demote_failed:AccessDenied" in (a1.get("done") or []),
          "applied=%s failed=%s already=%s a1=%s"
          % (out1.get("applied"), out1.get("failed"),
             out1.get("already_handled"), a1), live=True)
    bt1 = [r for r in _ledger_rows() if r.get("op") == "decontaminate_batch"]
    cb1 = (bt1[-1].get("checked_breakdown") if bt1 else None) or {}
    check("G1", "1e 批量行覆盖账 {applied:0, failed:1}（零改写不冒充已治理）",
          cb1.get("applied") == 0 and cb1.get("failed") == 1,
          "breakdown=%s" % cb1, live=True)

    # ---------- ② 轮2 · designer（有权）：同靶不再被永久跳过 ----------
    print("[2] 轮2 · designer（layers=('*')）同靶：真处置发生")
    des, out2 = _round("designer", k_exp, sc)
    fm2 = _fm(des, k_exp)
    acts2 = out2.get("actions") if isinstance(out2, dict) else []
    a2 = acts2[0] if isinstance(acts2, list) and acts2 else {}
    rows2 = _row(_ledger_rows(), "decontaminate", k_exp, "expired")
    check("G2", "2a applied=1 / already_handled=0 / failed=0（修前 = "
          "already_handled=1 + applied=0：有权身份也被跳过）",
          isinstance(out2, dict) and out2.get("applied") == 1
          and out2.get("already_handled") == 0 and out2.get("failed") == 0
          and a2.get("action") == "applied" and a2.get("applied") is True
          and "weaken" in (a2.get("done") or []) and "demote" in (a2.get("done")
                                                                  or []),
          "applied=%s already=%s a2=%s"
          % (out2.get("applied"), out2.get("already_handled"), a2), live=True)
    check("G2", "2b 盘面真的变了：weaken 0.5→0.35、负例 +1、降级 contextual"
          "（文件系统核实；修前 = 一个字节都没改）",
          fm2 == {"confidence": 0.35, "layer": "contextual",
                  "negative_evidence": 1}
          and _disk_layers(k_exp) == ["contextual"],
          "fm=%s disk=%s" % (fm2, _disk_layers(k_exp)), live=True)
    check("G2", "2c 轮2 单条台账 ok=True（真处置才进名单——判据对正例同样"
          "成立）",
          len(rows2) == 2 and rows2[-1].get("ok") is True,
          "rows=%s" % rows2, live=True)

    # ---------- ③ 轮3 · designer 再轮：幂等名单本身仍工作 ----------
    print("[3] 轮3 · designer 再轮：真处置过的才进名单（幂等不破）")
    des2, out3 = _round("designer", k_exp, sc)
    fm3 = _fm(des2, k_exp)
    acts3 = out3.get("actions") if isinstance(out3, dict) else []
    a3 = acts3[0] if isinstance(acts3, list) and acts3 else {}
    check("G3", "3a already_handled=1 / applied=0，逐条动作 skip（已处置过"
          "（幂等））",
          isinstance(out3, dict) and out3.get("already_handled") == 1
          and out3.get("applied") == 0 and a3.get("action") == "skip",
          "already=%s applied=%s a3=%s"
          % (out3.get("already_handled"), out3.get("applied"), a3))
    check("G3", "3b 盘面保持轮2 的处置态（0.35/contextual/负例1）——不是"
          "「从未处置」的 0.5/knowledge",
          fm3 == {"confidence": 0.35, "layer": "contextual",
                  "negative_evidence": 1}
          and _disk_layers(k_exp) == ["contextual"],
          "fm=%s disk=%s" % (fm3, _disk_layers(k_exp)), live=True)
    check("G3", "3c _handled 名单恰为 {(k_exp, expired)}（收的是真处置过的对）",
          sc._handled(des2) == {(k_exp, "expired")},
          "handled=%s" % sorted(map(str, sc._handled(des2))))

    # ---------- ⓸ 守卫自检 ----------
    check("GF", "4a live 腿数达到下限（端到端实弹 ≥ %d）" % LIVE_FLOOR,
          LIVE >= LIVE_FLOOR, "live=%d" % LIVE)
    return PASS, FAIL, list(FAILS)


def main(argv=None):
    global LIVE
    argv = list(sys.argv[1:] if argv is None else argv)
    mutate = None
    if argv and argv[0] == "--mutate":
        mutate = argv[1] if len(argv) > 1 else None
    sc = _scrub
    expect = None
    if mutate:
        muts = _mutation_table()
        if mutate not in muts:
            print(f"未知变异：{mutate}（可选：{', '.join(sorted(muts))}）")
            return 2
        path, old, new, expect, why = muts[mutate]
        sc = _load_mutated(path, old, new,
                           f"md_cg.scrub_i411_{mutate.lower()}")
        print(f"== 定点变异 {mutate}：{why} ==")
    passed, failed, fails = run_rounds(sc)
    if failed:                                   # 失败轮也先收尸临时目录
        pass
    if expect is None:
        print(f"\nissue411_scrub_idempotent: {passed} passed, {failed} failed "
              f"(live={LIVE})")
        for g, lbl in fails:
            print(f"  - [{g}] {lbl}")
        return 1 if failed else 0
    hit = sorted({g for g, _ in fails})
    good = set(hit) == set(expect)
    print(f"  变异红项组={hit} 预期={sorted(expect)} → "
          f"{'定点命中' if good else '未命中/连带'}")
    if not good:
        for g, lbl in fails:
            print(f"  - [{g}] {lbl}")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
