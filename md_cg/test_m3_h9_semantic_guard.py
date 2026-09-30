# -*- coding: utf-8 -*-
# 功能名：分区健康度自检的两向诚实化（M3）· protect.mark 打标失败不得冒充成功（H9）
#         ——守卫员席的独立语义级判别力守卫
# 生效条件：md_cg/routing.py 的 `bucket_health(counts, total_nodes=None)`、md_cg/mdcg.py
#           的 `MdCG.health` 呼叫点（把节点总数传进判据）、md_cg/protect.py 的 `mark`
#           三处修复在位时成立；沙箱条件：所有库根一律 tempfile.mkdtemp，绝不触在役库
#           （D:/program/dsh-memory-main 的 in-service 库）与在役服务；本文件只读源码，
#           变异时只写目标文件且在 finally 里按原始字节复原。
# 子功能：钉的是**消费方看得见的目标语义**，不是站点文本——
#   A M3 假警报方向：「从未分区」的库（单桶）不得被读成「分区退化」——读数里不得
#     出现「巨桶 / 碎片化 / 路由无效」这类退化结论，必须把原因归到「单桶·条件路由
#     本就不可用」；ok 仍为 False、数值面（expected_scan/max_bucket_share）仍为真值
#   B M3 不得放宽方向：真巨桶 / 碎片化 / 期望扫描超阈仍必须被报出并判退化，
#     阈值（>30% / >50%）边界与多桶形态逐位不变（消假警报 ≠ 放宽判据）
#   C M3 假健康方向：库里有节点而分桶表为空 ⇒ 消费方（`cg.health_os()`，即 MCP
#     `mdcg_health` 的返回体）不得读到 ok=True；真空库仍读 ok=True；缺省
#     total_nodes 时旧调用方读数与加参数前逐位一致（兼容面）
#   D H9 假成功方向：节点不存在时打标读数必须自证失败，且与「成功」形态互斥、
#     与仓内既有负路由契约同形；畸形 id 一律不裸穿透
#   E H9 返回值与事实一致（反方向）：成功打标必须真落保护位（返回值 / 内存判据 /
#     盘上 frontmatter / guard_forget 四面），失败打标必须真的什么都没发生
#   F 单点与接线：体检面的分区读数 == 判据单点（`routing.bucket_health`）的读数；
#     呼叫点显式传节点总数；MCP mark 分支无第二套判据（逐位透传）
# 执行：python -X utf8 -m md_cg.test_m3_h9_semantic_guard
#       python -X utf8 -m md_cg.test_m3_h9_semantic_guard --mutation=m3_bucket_guard
#       python -X utf8 -m md_cg.test_m3_h9_semantic_guard --mutation=all
# 验证方式：本文件自跑（自带断言计数、live 计数与退出码 rc=0/1）；定点变异自证见
#           --mutation（把每处修复逐点抽回改动前语义 → 本守卫必红且红项名可贴出；
#           变异在 finally 中按原始字节复原并回读核对逐字节相等 → 无残余）。
# 不适用条件：情感交互｜闲聊｜纯查询无改动；routing.py 的**阈值与文案措辞**本身不在
#           本席改动面（属 routing 判据席）——本守卫只钉「读数不得说假话」与「判据
#           不得被放宽」两向语义，不钉措辞；`protect.mark` 在 MCP 面「不存在节点该给
#           error 值还是 null」的协议登记（md_cg/protocol.py）不在本席改动面内。
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

# ── 隔离前置：在任何 md_cg 子模块 import 之前把根指到临时目录 ──
_TMP = tempfile.mkdtemp(prefix="m3h9sem_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES"):
    os.environ.pop(_k, None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import protect, routing, trust                # noqa: E402
from md_cg.mdcos import MdCGOS                           # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS = FAIL = LIVE = 0
LIVE_FLOOR = 8
FAILS = []
_OPEN = []

BODY = ("# 功能名：分区健康度探针\n"
        "# 生效条件：M3/H9 语义守卫临时库\n"
        "# 子功能：给沙箱库写入可打标节点\n"
        "# 执行：直接调用 cg.add\n"
        "# 验证方式：本守卫断言\n"
        "# 不适用条件：无\n"
        "守卫探针正文。\n")


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


def _mk(rel):
    cg = MdCGOS(os.path.join(_TMP, rel), autoflush=0)
    _OPEN.append(cg)
    return cg


def _close_all():
    for cg in _OPEN:
        try:
            cg.close()
        except Exception:                                # noqa: BLE001
            pass


def _cleanup():
    import gc
    import time
    for _ in range(6):
        shutil.rmtree(_TMP, ignore_errors=True)
        if not os.path.exists(_TMP):
            return
        gc.collect()
        time.sleep(0.25)


# ───────────────────────── 语义判据（两向） ─────────────────────────

DEGRADE_WORDS = ("巨桶", "碎片化", "路由无效")


def _degraded_reading(h) -> bool:
    """读数是否断言了「分区退化」（消费方会据此去重建分桶键）。"""
    return any(any(w in p for w in DEGRADE_WORDS)
               for p in (h.get("problems") or []))


def _fail_shape(r) -> bool:
    """打标失败必须自证失败：显式 ok=False + 非空 error 值。"""
    return (isinstance(r, dict) and r.get("ok") is False
            and isinstance(r.get("error"), str) and bool(r["error"]))


def _ok_shape(r) -> bool:
    """打标成功形态：protected=True 且不带任何失败标记。"""
    return (isinstance(r, dict) and r.get("protected") is True
            and "error" not in r and "ok" not in r)


LEGACY_EMPTY = {"ok": True, "reason": "empty", "buckets": 0}


def main():
    # ================= ⓪ 隔离自证 =================
    print("【⓪】隔离自证（临时根，不触在役库）")
    cg_one = _mk("lib_one")      # 全 knowledge 层节点 ⇒ 单桶（orphan）
    cg_self = _mk("lib_self")    # 全 self 层节点 ⇒ 有节点但分桶表为空
    cg_empty = _mk("lib_empty")  # 真空库
    cg_mark = _mk("lib_mark")    # 打标面（contextual 层，默认不带保护位）
    check("0a 库根落在本次临时目录内（不指在役库）",
          all(os.path.abspath(c.root).startswith(os.path.abspath(_TMP))
              for c in (cg_one, cg_self, cg_empty, cg_mark)),
          str([c.root for c in (cg_one, cg_self, cg_empty, cg_mark)]), live=True)
    check("0b MDCG_ROOT / MDCG_AUX_ROOT 亦在临时目录内（import 期不会冻到 ~/.mdcg）",
          os.path.abspath(os.environ["MDCG_ROOT"]).startswith(
              os.path.abspath(_TMP))
          and os.path.abspath(os.environ["MDCG_AUX_ROOT"]).startswith(
              os.path.abspath(_TMP)),
          os.environ["MDCG_ROOT"], live=True)
    n_one = [cg_one.add("sem_one_%d" % i, BODY, layer="knowledge")
             for i in range(3)]
    cg_one.flush()
    for i in range(3):
        cg_self.add("sem_self_%d" % i, BODY, layer="self")
    cg_self.flush()
    cg_mark.add("sem_mark_0", BODY, layer="contextual")
    cg_mark.flush()
    check("0c 沙箱库非空（防 fixture 空转绿）",
          len(cg_one.index["nodes"]) == 3 and len(cg_self.index["nodes"]) == 3
          and len(cg_mark.index["nodes"]) == 1
          and len(cg_empty.index["nodes"]) == 0,
          "%d / %d / %d / %d" % (len(cg_one.index["nodes"]),
                                 len(cg_self.index["nodes"]),
                                 len(cg_mark.index["nodes"]),
                                 len(cg_empty.index["nodes"])), live=True)
    check("0d fixture 前提：单桶库确为单桶、self 库确为零分桶",
          len(cg_one.index.get("buckets") or {}) == 1
          and (cg_self.index.get("buckets") or {}) == {},
          "%r / %r" % (cg_one.index.get("buckets"),
                       cg_self.index.get("buckets")), live=True)

    # ================= ① M3 假警报方向 =================
    print("\n【①】M3：从未分区（单桶）不得被读成分区退化")
    one = routing.bucket_health({"cond_a": 100})
    one_p = one.get("problems") or []
    one1 = routing.bucket_health({"cond_a": 1})
    check("A1 单桶库读数不含任何「分区退化」结论（巨桶/碎片化/路由无效）",
          not _degraded_reading(one), str(one_p))
    check("A2 单桶库 ok 仍为 False（读数更真 ≠ 判据放宽）",
          one.get("ok") is False, str(one))
    check("A3 单桶库数值面仍为真值（expected_scan/max_bucket_share 1.0、buckets 1、nodes 100）",
          one.get("expected_scan") == 1.0 and one.get("max_bucket_share") == 1.0
          and one.get("buckets") == 1 and one.get("nodes") == 100, str(one))
    check("A4 单桶库读数的原因归属：「单桶」+「不可用」（不是泛化退化结论）",
          any("单桶" in p and "不可用" in p for p in one_p), str(one_p))
    check("A5 单桶单节点 {a:1} 同口径（不因 n==1 走另一分支）",
          not _degraded_reading(one1)
          and any("单桶" in p and "不可用" in p
                  for p in (one1.get("problems") or [])), str(one1))
    h_e2e = cg_one.health_os()                       # = MCP `mdcg_health` 返回体
    check("A6 端到端：真库（同桶）经 cg.health_os() 亦不含退化结论且 ok False",
          not _degraded_reading(h_e2e) and h_e2e.get("buckets") == 1
          and h_e2e.get("ok") is False,
          str(h_e2e.get("problems")), live=True)
    check("A7 端到端：该库读数点名「单桶」（消费方知道该去分区，而非去重分键）",
          any("单桶" in p for p in (h_e2e.get("problems") or [])),
          str(h_e2e.get("problems")), live=True)

    # ================= ② M3 不得放宽方向 =================
    print("\n【②】M3：真退化仍必须被报出（消假警报 ≠ 放宽判据）")
    giant = routing.bucket_health({"cond_a": 80, "cond_b": 10, "cond_c": 10})
    check("B1 多桶真巨桶（80/10/10）仍报「巨桶」且 ok False",
          any("巨桶" in p for p in (giant.get("problems") or []))
          and giant.get("ok") is False, str(giant))
    frag = routing.bucket_health({"k1": 1, "k2": 1, "k3": 1, "k4": 1, "k5": 1,
                                  "cond_a": 3})
    check("B2 多桶碎片化仍报「碎片化」且 ok False",
          any("碎片化" in p for p in (frag.get("problems") or []))
          and frag.get("ok") is False, str(frag))
    scan = routing.bucket_health({"cond_a": 3, "cond_b": 3, "cond_c": 4})
    check("B3 多桶期望扫描超阈仍报「路由无效」",
          any("路由无效" in p for p in (scan.get("problems") or [])), str(scan))
    over = routing.bucket_health({"cond_a": 31, "cond_b": 35, "cond_c": 34})
    at = routing.bucket_health({"cond_a": 3, "cond_b": 3, "cond_c": 3,
                                "cond_d": 1})
    check("B4 阈值边界：多桶 top/n=0.31 报巨桶、=0.30 不报（阈值未被抬高）",
          any("巨桶" in p for p in (over.get("problems") or []))
          and not any("巨桶" in p for p in (at.get("problems") or [])),
          "%r / %r" % (over.get("problems"), at.get("problems")))
    live_buckets = dict(cg_one.index.get("buckets") or {})
    cg_one.index["buckets"] = {"cond_a": 80, "cond_b": 10, "cond_c": 10}
    try:
        h_deg = cg_one.health_os()
    finally:
        cg_one.index["buckets"] = live_buckets
    check("B5 端到端：真退化经 cg.health_os() 仍报「巨桶」且 ok False",
          any("巨桶" in p for p in (h_deg.get("problems") or []))
          and h_deg.get("ok") is False,
          str(h_deg.get("problems")), live=True)

    # ================= ③ M3 假健康方向 + 兼容面 =================
    print("\n【③】M3：有节点而分桶表为空不得被读成健康；兼容面逐位不变")
    n_self = len(cg_self.index["nodes"])
    h_self = cg_self.health_os()                      # = MCP `mdcg_health` 返回体
    check("C1 端到端：有节点而分桶表为空 ⇒ 消费方读到 ok False（不得冒充健康）",
          (cg_self.index.get("buckets") or {}) == {}
          and h_self.get("ok") is False, str(h_self.get("ok")), live=True)
    check("C2 该读数可被机械分流（reason=empty_buckets、nodes/total_nodes=节点数）",
          h_self.get("reason") == "empty_buckets"
          and h_self.get("nodes") == n_self
          and h_self.get("total_nodes") == n_self,
          str({k: h_self.get(k) for k in ("reason", "nodes", "total_nodes")}))
    h_empty = cg_empty.health_os()
    check("C3 真空库仍读 ok True / reason empty（反方向不误报）",
          h_empty.get("ok") is True and h_empty.get("reason") == "empty"
          and h_empty.get("total_nodes") == 0, str(h_empty.get("reason")))
    check("C4 缺省 total_nodes 时空 counts 读数与加参数前逐位一致（旧调用方零变更）",
          routing.bucket_health({}) == LEGACY_EMPTY
          and routing.bucket_health({}, total_nodes=None) == LEGACY_EMPTY
          and routing.bucket_health({"cond_a": 0}) == LEGACY_EMPTY
          and routing.bucket_health({}, total_nodes=0) == LEGACY_EMPTY,
          "%r / %r" % (routing.bucket_health({}),
                       routing.bucket_health({"cond_a": 0})))
    check("C5 缺省时键集亦未变（不给空桶路径偷加键）",
          set(routing.bucket_health({})) == set(LEGACY_EMPTY),
          str(sorted(routing.bucket_health({}))))
    gc_counts = {"cond_a": 80, "cond_b": 10, "cond_c": 10}
    check("C6 total_nodes 只参与「空 counts」一支：多桶库传任意值读数逐位一致",
          routing.bucket_health(gc_counts, total_nodes=7)
          == routing.bucket_health(gc_counts, total_nodes=99999)
          == routing.bucket_health(gc_counts),
          str([routing.bucket_health(gc_counts, total_nodes=7),
               routing.bucket_health(gc_counts)]))
    bad = routing.bucket_health({}, total_nodes=7)
    check("C7 两种读数互不同一（有节点零分桶 ≠ 真空库，消费方可分流处置）",
          set(bad) != set(LEGACY_EMPTY)
          and bad.get("reason") != LEGACY_EMPTY["reason"], str(bad))
    lie = routing.bucket_health(cg_self.index.get("buckets") or {})
    truth = routing.bucket_health(cg_self.index.get("buckets") or {},
                                  total_nodes=n_self)
    check("C8 旧假话可复现且被新读数否证（缺省=ok True 冒充健康 / 显式传参=ok False）",
          lie.get("ok") is True and truth.get("ok") is False
          and truth.get("nodes") == n_self, "%r / %r" % (lie, truth), live=True)

    # ================= ④ H9 假成功方向 =================
    print("\n【④】H9：打标失败必须自证失败，且与成功形态互斥")
    missing = "sem_不存在_%d" % os.getpid()
    miss = protect.mark(cg_mark, missing, "语义守卫·显式保护标记")
    check("D1 不存在节点打标读数显式标记失败（ok False + error 值在场）",
          _fail_shape(miss), repr(miss))
    check("D2 失败读数不得与成功形态混淆（成功形态判据必须为假）",
          not _ok_shape(miss), repr(miss))
    check("D3 失败读数不得被读成「打了保护位」（protected 不得为 True）",
          not (isinstance(miss, dict) and miss.get("protected") is True),
          repr(miss))
    ts = trust.set_state(cg_mark, missing, "verified")
    check("D4 与仓内既有负路由契约同形（trust.set_state 缺失分支：键集同、error 同值）",
          _fail_shape(miss) and set(miss) == set(ts)
          and miss.get("error") == ts.get("error"), "%r / %r" % (miss, ts))
    shapes, details = [], []
    for odd in ("", None, 0, True, ["x"], {"a": 1}, ("t",), 1.5):
        try:
            r = protect.mark(cg_mark, odd, "理由")
        except Exception as exc:                         # noqa: BLE001
            shapes.append(False)
            details.append("%r -> RAISED %s" % (odd, type(exc).__name__))
        else:
            shapes.append(_fail_shape(r) and not _ok_shape(r))
            details.append("%r -> %r" % (odd, r))
    check("D5 畸形/空 node_id 一律不裸穿透且给出同一失败形态（消费方无需 try）",
          all(shapes), "；".join(details))
    try:
        from .mcp_server import _protect_call
    except Exception as exc:                             # noqa: BLE001
        check("D6 MCP 面 _protect_call 可取到（否则 H9 的假成功无发生面）",
              False, type(exc).__name__)
    else:
        mcp_bad = _protect_call(cg_mark, {"action": "mark", "node_id": missing,
                                          "reason": "语义守卫·显式保护标记"})
        mcp_ok = _protect_call(cg_mark, {"action": "mark", "node_id": "sem_mark_0",
                                         "reason": "理由"})
        check("D6 MCP 面 mark：缺失 id 不得给出成功形态，存在 id 必须给出成功形态",
              _fail_shape(mcp_bad) and not _ok_shape(mcp_bad)
              and _ok_shape(mcp_ok) and not _fail_shape(mcp_ok),
              "%r / %r" % (mcp_bad, mcp_ok), live=True)
        check("D7 MCP 面 mark 与判据单点逐位一致（无第二套包装/判据）",
              mcp_bad == miss, "%r vs %r" % (mcp_bad, miss))
        rt = json.loads(json.dumps(mcp_bad, ensure_ascii=False))
        check("D8 失败读数经 JSON 往返（模拟 MCP 序列化）后仍可判别",
              _fail_shape(rt) and not _ok_shape(rt), repr(rt), live=True)

    # ================= ⑤ H9 返回值与事实一致（反方向） =================
    print("\n【⑤】H9：成功必须真落保护位；失败必须真的什么都没发生")
    mark_id = "sem_mark_%d" % os.getpid()      # ⑤ 组专用新鲜节点（不被 D6 沾过）
    cg_mark.add(mark_id, BODY, layer="contextual")
    cg_mark.flush()
    pre_prot, pre_why = protect.is_protected(cg_mark, mark_id)
    check("E0 前置：该节点初始未被保护（防 fixture 自带保护位使 E3 空转）",
          pre_prot is False, "%r / %r" % (pre_prot, pre_why), live=True)
    before = protect.stats(cg_mark)["protected_count"]
    r_bad = protect.mark(cg_mark, missing, "理由")
    after = protect.stats(cg_mark)["protected_count"]
    check("E1 失败打标真的什么都没发生：无节点被物化、保护位未设、保护计数不变",
          _fail_shape(r_bad) and cg_mark.get(missing) is None
          and protect.is_protected(cg_mark, missing)[0] is False
          and before == after,
          "%r / %r / %d->%d" % (r_bad, cg_mark.get(missing), before, after),
          live=True)
    r_ok = protect.mark(cg_mark, mark_id, "语义守卫·保护标记")
    pro, why = protect.is_protected(cg_mark, mark_id)
    disk_fm = (cg_mark.get(mark_id) or {}).get("frontmatter") or {}
    check("E2 成功打标返回值与事实三面一致（返回体 / 内存判据 / 盘上 frontmatter）",
          _ok_shape(r_ok) and pro is True
          and disk_fm.get("protected") is True
          and disk_fm.get("protection_reason") == "语义守卫·保护标记",
          "%r / %r / %r" % (r_ok, pro, disk_fm), live=True)
    try:
        protect.guard_forget(cg_mark, mark_id)
    except Exception as exc:                             # noqa: BLE001
        check("E3 打标成功后守卫真的拦得住遗忘（ProtectionError 在场）",
              type(exc).__name__ == "ProtectionError", type(exc).__name__,
              live=True)
    else:
        check("E3 打标成功后守卫真的拦得住遗忘（ProtectionError 在场）",
              False, "guard_forget 静默放行——「打标成功」是空话")
    r_again = protect.mark(cg_mark, mark_id, "语义守卫·保护标记二")
    check("E4 幂等：同节点再打标仍成功、原因更新、保护位仍在",
          _ok_shape(r_again)
          and protect.is_protected(cg_mark, mark_id)[0] is True
          and protect.is_protected(cg_mark, mark_id)[1] == "语义守卫·保护标记二",
          "%r / %r" % (r_again, protect.is_protected(cg_mark, mark_id)))

    # ================= ⑥ 单点与接线 =================
    print("\n【⑥】单点与接线（判据唯一真源 + 呼叫点显式传参）")
    seen = []
    orig_bh = routing.bucket_health

    def _recorder(counts, total_nodes=None):
        seen.append((dict(counts), total_nodes))
        return orig_bh(counts, total_nodes=total_nodes)

    routing.bucket_health = _recorder
    try:
        h_from_health = cg_self.health()
    finally:
        routing.bucket_health = orig_bh
    check("F1 呼叫点把节点总数显式传进判据（否则「有节点零分桶」不可判别）",
          len(seen) >= 1 and all(s[1] == n_self for s in seen),
          str(seen), live=True)
    ref = orig_bh(cg_self.index.get("buckets") or {}, total_nodes=n_self)
    keys = ("ok", "reason", "buckets", "nodes", "max_bucket_share",
            "singleton_ratio", "expected_scan", "problems")
    check("F2 体检面的分区读数 == 判据单点的读数（不是第二份判据）",
          all(h_from_health.get(k) == ref.get(k) for k in keys),
          "%r / %r" % ({k: h_from_health.get(k) for k in keys},
                       {k: ref.get(k) for k in keys}))
    check("F3 判据单点在位且空桶缺省读数不变（旧调用方零变更）",
          callable(orig_bh) and orig_bh({}) == LEGACY_EMPTY,
          repr(orig_bh({})))

    # ================= ⑦ floor =================
    print("\n【⑦】live floor（防空转绿）")
    print("  [INFO] live 断言数 = %d（floor=%d）" % (LIVE, LIVE_FLOOR))
    check("G1 live 断言数不低于 floor", LIVE >= LIVE_FLOOR, "live=%d" % LIVE)

    print("\n" + "=" * 66)
    print("PASS=%d  FAIL=%d  LIVE=%d" % (PASS, FAIL, LIVE))
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


# =========================================================================
# 定点变异（把修复逐点抽回改动前语义）——字节保真改写 → 跑 → finally 复原
# =========================================================================

def _read_bytes(rel):
    with open(os.path.join(_REPO, rel), "rb") as f:
        return f.read()


def _j(*lines):
    return "\n".join(lines) + "\n"


MUTATIONS = {
    # M3①：巨桶判据退回「无 nb > 1 守卫」⇒ 从未分区的库被读成「巨桶·分区失效」
    "m3_bucket_guard": ("md_cg/routing.py",
                        "    if nb > 1 and top / n > 0.30:\n",
                        "    if top / n > 0.30:\n"),
    # M3②：单桶如实读数退回泛化的「路由无效·接近全量」
    "m3_single_read": ("md_cg/routing.py",
                       "    if nb == 1:\n",
                       "    if False:\n"),
    # M3③a：空 counts 的「有节点」分支抽掉（保留形参）
    "m3_empty_branch": ("md_cg/routing.py",
                        "        if total_nodes and total_nodes > 0:\n",
                        "        if False:\n"),
    # M3③b：呼叫点退回只传 counts（等价改动前形态）
    "m3_call_site": ("md_cg/mdcg.py",
                     _j('        h = routing.bucket_health(self.index.get("buckets", {}),',
                        '                                  total_nodes=len(self.index["nodes"]))'),
                     _j('        h = routing.bucket_health(self.index.get("buckets", {}))')),
    # H9：失败分支退回裸 None（None 与成功在调用方不可区分）
    "h9_none": ("md_cg/protect.py",
                _j('        return {"ok": False, "error": "node_not_found", '
                   '"node_id": node_id}'),
                _j("        return None")),
    # H9 反向：失败分支退回「成功形态」（不存在的 id 读成打标成功）
    "h9_fake_ok": ("md_cg/protect.py",
                   _j('        return {"ok": False, "error": "node_not_found", '
                      '"node_id": node_id}'),
                   _j('        return {"node_id": node_id, "protected": True, '
                      '"reason": reason}')),
    # H9 反向：一律走失败分支（成功路径被抽掉——防守卫片面）
    "h9_always_fail": ("md_cg/protect.py",
                       _j("    if not node:",
                          '        return {"ok": False, "error": "node_not_found", '
                          '"node_id": node_id}'),
                       _j("    if True:",
                          '        return {"ok": False, "error": "node_not_found", '
                          '"node_id": node_id}')),
}


def _run_child():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, "-X", "utf8", "-m",
                        "md_cg.test_m3_h9_semantic_guard"],
                       cwd=_REPO, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _mutate(name):
    rel, old, new = MUTATIONS[name]
    path = os.path.join(_REPO, rel)
    raw = _read_bytes(rel)
    text = raw.decode("utf-8")
    if text.count(old) != 1:
        raise SystemExit("[MUT] %s：锚点命中 %d 次（应为 1）——树已变，请复核"
                         % (name, text.count(old)))
    try:
        with open(path, "wb") as f:
            f.write(text.replace(old, new, 1).encode("utf-8"))
        rc, out = _run_child()
    finally:
        with open(path, "wb") as f:
            f.write(raw)
    restored = _read_bytes(rel) == raw
    reds = [ln.strip() for ln in out.splitlines() if "[FAIL]" in ln]
    print("\n" + "=" * 66)
    print("[MUT] %s（%s）→ 子进程 rc=%d" % (name, rel, rc))
    for ln in reds:
        print("      RED " + ln)
    print("[MUT] 红项数 = %d" % len(reds))
    print("[MUT] 恢复核对：%s 逐字节复原=%s" % (rel, restored))
    return rc, len(reds), restored


if __name__ == "__main__":
    args = list(sys.argv[1:])
    _mut = [a for a in args if a.startswith("--mutation")]
    if _mut:
        want = _mut[-1].split("=", 1)[1] if "=" in _mut[-1] else "all"
        names = list(MUTATIONS) if want == "all" else [want]
        bad = []
        for nm in names:
            if nm not in MUTATIONS:
                raise SystemExit("未知变异：%s" % nm)
            rc, nred, ok = _mutate(nm)
            if rc == 0 or nred == 0 or not ok:
                bad.append(nm)
        print("\n[SUMMARY] 变异 %d 项；未变红或未复原的：%s"
              % (len(names), bad or "无"))
        _close_all()
        _cleanup()
        sys.exit(1 if bad else 0)
    try:
        rc = main()
    finally:
        _close_all()
        _cleanup()
    sys.exit(rc)
