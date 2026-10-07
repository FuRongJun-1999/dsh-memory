# -*- coding: utf-8 -*-
"""md_cg · W6「存在契约」载体守卫（identity 契约记录 · anchor 层 · 引用锚 · 定点变异自证）

设计口径（`docs/eval/W6_存在契约载体_设计_v0.1.md` ＋ 末尾「设计者定稿 9 条」）：
  · 载体＝identity 模块新增「契约记录」（与 anchor/trait/observation 并列）；
  · 落 anchor 层（不可遗忘＋不可覆盖，无 self_state 豁免）；
  · 字段＝§3.2.1 四字段（contract_id/grantor/grantee/timestamp/status_summary）
    ＋ status_hash（四字段规范化后哈希）＋引用锚 doc_ref（复用 probe_ref/read_ref，
    不复制承诺原文）；
  · 节点 id 形如 `identity_contract_<slug>`；contract_id 保留 #ANCHOR- 原形；
  · 写入面走 admin 闸（对齐 set_anchor 先例）；显式非自动。

覆盖：
  A 写入→读回：五字段齐全 · contract_id 保留 #ANCHOR- 原形 · status_hash 在场且可复算一致
  B 保护：layer==anchor · is_immutable True · guard_write/guard_forget 无 override 抛
  C 幂等/唯一：同 slug 二写无 override 拒（不可覆盖）· 显式 override 放行
  D 引用锚：probe_ref ok · read_ref 回读含 §1.6.5 标题 · hash 改一位→stale（真跑）
  E MCP 入口：action=contract 无 admin→AccessDenied；有 admin→落盘；contracts 读回
  F 定点变异自证（4 处）：逐条要求恰好命中期望红项；复原后重跑全套全绿

运行：python -X utf8 -m md_cg.test_identity_contract
      python -X utf8 -m md_cg.test_identity_contract --self-proof
退出码：0 全绿 ｜ 1 断言失败 ｜ 2 ANCHOR-MISS（变异锚点漂移，fail-closed）

隔离：全部用 tempfile 临时库（不碰活库）；唯一读真源处＝构造引用锚（只读
`docs/theory/智能论3.4.md`，一字不写）。变异自证的基线源＝**运行中的实现源码**
（`inspect.getsource` 就地变异、就地复原），不读 git。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import sys
import tempfile
import textwrap

from .mdcos import MdCGOS, MdCGSecure
from .security import Principal, AccessDenied
from . import identity, protect, refindex, codeindex, mcp_server as ms

PASS = FAIL = 0
FAILS = []

# 引用锚指向的真源（仓内相对路径；只读，绝不写入）
THEORY_REL = "docs/theory/智能论3.4.md"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CID = "#ANCHOR-DS-001"
GRANTOR = "designer:(荣)"
GRANTEE = "agent:deepseek"
TS = "2026-08-09"
SUMMARY = "反思单元接入，设计者预备"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def blocked(fn):
    """执行 fn，返回是否被 ProtectionError / ValueError 拦下。"""
    try:
        fn()
        return False
    except (protect.ProtectionError, ValueError):
        return True


# ---------------------------------------------------------------- 引用锚构造
def _theory_ref():
    """构造指向 §1.6.5 区间的引用锚（与 index_doc 的 doc_ref 同构、逐键复用）。

    真源缺失时返回 None（引用锚断言优雅跳过）。**只读**真源、绝不一字写入。
    """
    fp = os.path.join(REPO_ROOT, THEORY_REL)
    if not os.path.isfile(fp):
        return None
    lines = io.open(fp, encoding="utf-8").read().split("\n")
    lineno = end = None
    for i, ln in enumerate(lines, 1):
        if ln.strip().startswith("#### 1.6.5"):
            lineno = i
        elif lineno and ln.strip().startswith("#### ") and i > lineno:
            end = i - 1
            break
    if not lineno:
        return None
    if not end:
        end = min(lineno + 45, len(lines))
    return {"root": REPO_ROOT, "path": THEORY_REL, "lineno": lineno,
            "end": end, "hash": codeindex.region_hash(lines, lineno, end),
            "heading": "1.6.5 协定式自我赋予", "heading_path": "1.6.5",
            "level": 4, "anchor": "1.6.5", "lang": "md", "precise": True}


# ---------------------------------------------------------------- A–D 核心组
def _core_group():
    """写入→读回 · 保护 · 幂等/唯一 · 引用锚（单隔离库，自造不依赖模块级实例）。"""
    cg = MdCGOS(tempfile.mkdtemp(prefix="mdcg_w6_contract_"))
    ref = _theory_ref()
    out = cg.identity_contract(
        CID, grantor=GRANTOR, grantee=GRANTEE, timestamp=TS,
        status_summary=SUMMARY, doc_ref=ref)
    fm = (cg.get(out["node_id"]) or {}).get("frontmatter") or {}
    fields = {k: fm.get(k) for k in identity.CONTRACT_HASH_FIELDS}

    # A 写入→读回
    check("C1 五字段齐全（contract_id/grantor/grantee/timestamp/status_summary）",
          all(fields.get(k) for k in identity.CONTRACT_HASH_FIELDS), str(fields))
    check("C2 contract_id 保留 #ANCHOR- 原形",
          fm.get("contract_id") == CID, str(fm.get("contract_id")))
    check("C3 status_hash 在场",
          bool(fm.get("status_hash")), str(fm.get("status_hash")))
    check("C4 status_hash 可复算一致",
          fm.get("status_hash") == identity.contract_status_hash(fields),
          f'{fm.get("status_hash")} vs {identity.contract_status_hash(fields)}')
    check("C9 节点 id 形态 identity_contract_<slug>",
          out["node_id"] == "identity_contract_ANCHOR-DS-001", out["node_id"])

    # B 保护（不可遗忘＋不可覆盖）
    check("C5 落 anchor 层",
          fm.get("layer") == "anchor", str(fm.get("layer")))
    imm, why = protect.is_immutable(cg, out["node_id"])
    check("C6 is_immutable True（不可覆盖）", imm, why)
    check("C7 guard_write 无 override 抛 ProtectionError",
          blocked(lambda: protect.guard_write(cg, out["node_id"])), "")
    check("C8 guard_forget 无 override 抛 ProtectionError",
          blocked(lambda: protect.guard_forget(cg, out["node_id"])), "")

    # C 幂等/唯一（定稿第 2 条：anchor 层不可覆盖 ⇒ 同 slug 二写默认拒）
    check("C10 同 slug 二写（无 override）被拒（anchor 层不可覆盖）",
          blocked(lambda: cg.identity_contract(
              CID, grantor=GRANTOR, grantee=GRANTEE, timestamp=TS,
              status_summary="试图覆盖", doc_ref=ref)), "")
    out2 = cg.identity_contract(
        CID, grantor=GRANTOR, grantee=GRANTEE, timestamp=TS,
        status_summary="经确认修订", doc_ref=ref, override=True)
    fm2 = (cg.get(out2["node_id"]) or {}).get("frontmatter") or {}
    check("C11 override=True 放行且四字段更新",
          bool(out2.get("ok")) and fm2.get("status_summary") == "经确认修订",
          str(fm2.get("status_summary")))

    # D 引用锚（真源在场时；漂移锚用局部 ref 构造，与 doc_ref 是否落盘解耦）
    if ref is None:
        check("D0 真源缺失 → 引用锚断言跳过", True, "理论文档缺失")
    else:
        dr = fm.get("doc_ref")
        p = refindex.probe_ref(dr, root=REPO_ROOT)
        check("D1 引用锚 probe_ref → ok（真源未漂移）",
              p.get("status") == "ok", p.get("status"))
        rr = refindex.read_ref(dr, root=REPO_ROOT)
        check("D2 read_ref 回读区间含 §1.6.5 标题",
              bool(rr.get("ok")) and "1.6.5" in (rr.get("text") or ""),
              (rr.get("text") or "")[:40])
        drift = dict(ref)
        h = str(drift.get("hash") or "")
        drift["hash"] = ("0" if h[:1] != "0" else "1") + h[1:]
        pd = refindex.probe_ref(drift, root=REPO_ROOT)
        check("D3 hash 改一位 → stale（记录侧对真源漂移敏感）",
              pd.get("status") == "stale", pd.get("status"))


# ---------------------------------------------------------------- E MCP 入口
def _mcp_group():
    """MCP 入口端到端：admin 闸 + 读回（对齐 test_p45 R65.9 的 MCP 做法）。"""
    root = tempfile.mkdtemp(prefix="mdcg_w6_contract_mcp_")
    ref = _theory_ref()
    args = {"action": "contract", "contract_id": CID, "grantor": GRANTOR,
            "grantee": GRANTEE, "timestamp": TS, "status_summary": SUMMARY,
            "doc_ref": ref}

    adm = MdCGSecure(root, principal=Principal(
        actor="w6_adm", role="designer", can_write=True, can_admin=True,
        clearance="secret", layers_allow=["*"]))
    o = ms._identity_call(adm, dict(args))
    check("E2 action=contract 有 admin → 落盘 anchor 层",
          bool(o.get("ok")) and o.get("layer") == "anchor", str(o)[:90])
    got = ms._identity_call(adm, {"action": "contracts", "contract_id": CID})
    check("E3 action=contracts 按 contract_id 单取",
          got.get("ok") and got.get("contract_id") == CID,
          str(got.get("contract_id")))
    lst = ms._identity_call(adm, {"action": "contracts"})
    check("E4 action=contracts 列表含该条",
          lst.get("count") == 1
          and lst["contracts"][0]["contract_id"] == CID, str(lst.get("count")))

    # 非 admin 实例在写入之后新建（索引需含该节点）：写被拒、读放行。
    noadm = MdCGSecure(root, principal=Principal(
        actor="w6_noadm", role="recorder", can_write=True, can_admin=False,
        clearance="secret", layers_allow=["*"]))
    denied = False
    try:
        ms._identity_call(noadm, dict(args))
    except AccessDenied:
        denied = True
    check("E1 action=contract 无 admin → AccessDenied", denied, "")
    got2 = ms._identity_call(noadm, {"action": "contracts", "contract_id": CID})
    check("E5 action=contracts 只读不需 admin", got2.get("ok"),
          str(got2.get("error")))


def main():
    global PASS, FAIL
    if "--self-proof" in sys.argv:
        return _self_proof()
    PASS = FAIL = 0
    del FAILS[:]
    print("\n[A–D] 写入→读回 · 保护 · 幂等/唯一 · 引用锚（隔离临时库）")
    _core_group()
    print("\n[E] MCP 入口（admin 闸 + 读回）")
    _mcp_group()
    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 68)
    return 1 if FAIL else 0


# ---------------------------------------------------------------- 定点变异自证
# 锚点在 `identity.set_contract` 的**实现源码**上定位（每条命中次数须恰为 1）。
# 每条变异声明**期望转红的断言项**；实跑红项与期望必须**恰好相等**——多红=断言语义
# 纠缠，少红=该判据空转。锚点漂移（命中次数 ≠1）→ ANCHOR-MISS + 退出码 2（fail-closed）。
_CORE_MUTATIONS = (
    ("①落层 anchor→knowledge（不可篡改依赖层保护）",
     'layer="anchor"', 'layer="knowledge"',
     {"C5", "C6", "C7", "C10"}),
    ("②去 status_hash（记录侧校验失效）",
     'extra["status_hash"] = sh', 'extra["status_hash"] = None',
     {"C3", "C4"}),
    ("③contract_id 落 slug 形态（丢失 #ANCHOR- 原形）",
     'fields = {"contract_id": cid, "grantor": gtor, "grantee": gtee,',
     'fields = {"contract_id": _slug(cid), "grantor": gtor, "grantee": gtee,',
     {"C2"}),
    ("④去引用锚 doc_ref（引用而非复制失效）",
     'extra["doc_ref"] = dict(doc_ref)', 'pass',
     {"D1", "D2"}),
)


def _w6_anchor_preflight():
    """锚点自检：任一变异锚点在实现源码里命中次数 ≠1 → ANCHOR-MISS + 退出码 2。"""
    src = textwrap.dedent(inspect.getsource(identity.set_contract))
    bad = [(old, src.count(old)) for _, old, _, _ in _CORE_MUTATIONS
           if src.count(old) != 1]
    if not bad:
        return 0
    for a, n in bad:
        print("  ANCHOR-MISS 锚点漂移（命中 %d 次，期望恰好 1）：%r" % (n, a[:70]))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed；请同步 _CORE_MUTATIONS）")
    return 2


def _core_run():
    """跑核心组，返回（转红断言项集合, 通过数, 失败数）。"""
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _core_group()
    return ({n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL)


def _self_proof():
    """逐条变异 → 要求恰好命中期望红项；复原后重跑全套应当全绿。"""
    rc = _w6_anchor_preflight()
    if rc:
        return rc
    print("!! W6 定点变异自证：就地变异运行中的 identity.set_contract（不读 git），"
          "逐条要求**恰好**命中期望红项\n")
    src = textwrap.dedent(inspect.getsource(identity.set_contract))
    orig = identity.set_contract
    bad = []
    with contextlib.redirect_stdout(io.StringIO()):
        base_red, _, _ = _core_run()
    print("  未变异基线：红项 %d %s" % (len(base_red),
                                       "（应为 0）" if base_red else ""))
    if base_red:
        bad.append("未变异基线即转红：%s" % sorted(base_red))
    marks = "①②③④"
    for i, (name, old, new, expect) in enumerate(_CORE_MUTATIONS):
        ns = dict(vars(identity))
        exec(compile(src.replace(old, new), "<w6-mutated-%d>" % i, "exec"), ns)
        identity.set_contract = ns["set_contract"]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                red, _, _ = _core_run()
        except Exception as exc:                       # noqa: BLE001
            red = {"<变异体运行异常:%s>" % type(exc).__name__}
        finally:
            identity.set_contract = orig
        hit = red == expect
        if not hit:
            bad.append("变异%s %s：红项 %s ≠ 期望 %s"
                       % (marks[i], name, sorted(red), sorted(expect)))
        print("  变异%s %-34s 红项 %d（期望 %d）%s"
              % (marks[i], name, len(red), len(expect),
                 "PASS" if hit else "**FAIL** 实=%s 期=%s" % (sorted(red), sorted(expect))))
    argv_bak = list(sys.argv)
    sys.argv[:] = [a for a in argv_bak if a != "--self-proof"]
    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf):
            full_rc = main()
    finally:
        sys.argv[:] = argv_bak
    print("  复原后重跑全套（A–E）：退出码 %d %s"
          % (full_rc, "（全绿）" if full_rc == 0 else "**非全绿**"))
    if full_rc:
        for _ln in _buf.getvalue().splitlines():
            if "[FAIL]" in _ln:
                print("    复原重跑红：%s" % _ln.strip()[:120])
        bad.append("复原后全套非全绿（rc=%d）" % full_rc)
    print("\n变异自证：%s"
          % ("PASS（四条腿逐条恰好命中期望红项；复原后全绿）" if not bad
             else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    _rc = main()
    sys.exit(_rc if _rc in (0, 2) else 1)
