# -*- coding: utf-8 -*-
"""md_cg · 分区健康度自检对单桶库说假话（M3）+ protect.mark 不存在节点裸 None（H9）

M3（`md_cg/routing.py::bucket_health`）——自检对「从未分区」的库报「分区退化」：
  ① 巨桶判据 `top/n > 0.30` 在 nb == 1 时恒真（单桶必然 100%）⇒ 一把从未分区
     的库报成「巨桶 · 分区失效」。判据缺 `nb > 1` 守卫，而同函数碎片化判据早
     就带着这个守卫（同形缺口）。修复：巨桶判据加 `nb > 1`。
  ② nb == 1 时巨桶与期望扫描（同样恒 1.0）互为同一事实的两种写法 ⇒ 合并为一条
     如实读数「单桶 · 条件路由本就不可用（未分区，非巨桶退化）」。**ok 仍为
     False**（单桶库的一次查询确实是全量扫描——判据未放宽，只把假诊断换成真读数）；
     `expected_scan` 的**数值**仍在返回 dict 里（下游读的是数）。
  ③ `counts == {}` 而库里有节点时返回 `{'ok': True, 'reason': 'empty'}` ⇒ 索引
     分桶表整体缺失被读成「健康」。修复：新增 `total_nodes` 形参（缺省 None）区分
     「真空库」与「有节点但零分桶」。**向后兼容**：缺省 None 时返回与加参数前
     **逐位一致**（下面 3a/3b/3e 用整 dict 相等钉死），既有三个调用点
     （test_p0:101 / bench_axis_domain:156 / bench6_arms:183 只传 counts）行为一字不变。

H9（`md_cg/protect.py::mark`）——节点不存在时裸返回 `None`：
  ④ `None` 与「成功」在调用方眼里都非 dict：`mcp_server._protect_call:1217` 把
     `protect.mark(...)` 的结果直接回给 MCP 客户端 ⇒ 不存在的 node_id 序列化成
     `null`，读成「打标成功」，而 `_write_node` 从未发生（静默假成功）。修复：
     返回 `{"ok": False, "error": "node_not_found", "node_id": node_id}`
     （形态对齐 `trust.set_state` 的同名分支）。成功路径的返回键**不变**
     （node_id / protected / reason）。

守卫（四组 + 源断言 + floor；独立临时根 + 哑 aux 根，绝不触在役库/~/.mdcg）：
  ⓿ 隔离自证；① 巨桶守卫（含真巨桶仍报、30% 边界不报）；② 单桶如实读数；
  ③ 空桶 + total_nodes（含缺省逐位一致）；④ mark 负路由（含与 trust.set_state
  同形、MCP 面透出）；⑤ 源断言 + live floor。

运行：python -X utf8 -m md_cg.test_m3_h9_bucket_health_protect_mark
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

# ── 隔离前置：在任何 md_cg 子模块 import 之前把根指到临时目录（import 期可能把
# aux_root() 冻成常量；且绝不触在役库 D:/... 与真实 ~/.mdcg）。 ──
_TMP = tempfile.mkdtemp(prefix="m3h9_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES"):
    os.environ.pop(_k, None)

from . import protect, routing, trust                # noqa: E402
from .mdcos import MdCGOS                            # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                    # noqa: BLE001
    pass

PASS = FAIL = LIVE = 0
LIVE_FLOOR = 6
FAILS = []

ROOT = os.path.join(_TMP, "cg1")
BODY = ("# 功能名：分桶健康度探针\n"
        "# 生效条件：M3/H9 守卫临时库\n"
        "# 子功能：给沙箱库写入可打标节点\n"
        "# 执行：直接调用 cg.add\n"
        "# 验证方式：本守卫断言\n"
        "# 不适用条件：无\n"
        "守卫探针正文。\n")

_CG = []


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


def _close_all():
    for cg in _CG:
        try:
            cg.close()
        except Exception:                            # noqa: BLE001
            pass


def _cleanup(path) -> bool:
    import gc
    import time
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        gc.collect()
        time.sleep(0.25)
    return not os.path.exists(path)


atexit.register(lambda: (_close_all(), _cleanup(_TMP)))


def _cg():
    cg = MdCGOS(ROOT)
    _CG.append(cg)
    return cg


def _src(rel):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), rel),
              encoding="utf-8") as f:
        return f.read()


def _window(text, start, end):
    i = text.index(start)
    j = text.index(end, i + len(start))
    return text[i:j]


def legacy_empty():
    """加 total_nodes 参数之前的空桶返回（逐位对照基线）。"""
    return {"ok": True, "reason": "empty", "buckets": 0}


def main():
    # ================= ⓿ 隔离自证 =================
    print("【⓿】隔离自证（临时根，不触在役库）")
    cg = _cg()
    check("0a 库根落在本次临时目录内（不指在役库）",
          os.path.abspath(cg.root).startswith(os.path.abspath(_TMP)),
          cg.root, live=True)
    check("0b MDCG_ROOT 亦在临时目录内（import 期不会冻到 ~/.mdcg）",
          os.path.abspath(os.environ["MDCG_ROOT"]).startswith(
              os.path.abspath(_TMP)),
          os.environ["MDCG_ROOT"], live=True)
    nid = cg.add("m3h9_alpha", BODY, layer="knowledge")
    cg.add("m3h9_beta", BODY, layer="knowledge")
    cg.add("m3h9_gamma", BODY, layer="knowledge")
    cg.flush()
    check("0c 沙箱库确有节点（防 fixture 空转）",
          len(cg.index["nodes"]) == 3, len(cg.index["nodes"]), live=True)

    # ================= ① 巨桶判据加 nb > 1 守卫 =================
    print("\n【①】巨桶判据（M3①）")
    one = routing.bucket_health({"cond_a": 100})
    check("1a 单桶 {a:100} 不再报「巨桶」",
          not any("巨桶" in p for p in one["problems"]), str(one["problems"]))
    multi = routing.bucket_health({"cond_a": 80, "cond_b": 10, "cond_c": 10})
    check("1b 多桶真巨桶 {a:80,b:10,c:10} 仍报「巨桶：最大桶占 80.0%」（未放宽）",
          any("巨桶" in p and "80.0%" in p for p in multi["problems"])
          and multi["ok"] is False, str(multi["problems"]))
    edge = routing.bucket_health({"cond_a": 3, "cond_b": 3, "cond_c": 3,
                                  "cond_d": 1})
    check("1c 30% 边界（top/n == 0.30 且期望扫描 28%）两条判据均不触发",
          edge["ok"] is True and edge["problems"] == []
          and edge["max_bucket_share"] == 0.3, str(edge))
    frag = routing.bucket_health({"k1": 1, "k2": 1, "k3": 1, "k4": 1, "k5": 1,
                                  "cond_a": 3})
    check("1d 碎片化判据（nb > 1 + 单例率 > 50%）仍报（同族判据未被误伤）",
          any("碎片化" in p for p in frag["problems"]), str(frag["problems"]))

    # ================= ② 单桶如实读数 =================
    print("\n【②】单桶如实读数（M3②）")
    check("2a 单桶 problems 点名「单桶」+「条件路由……不可用」",
          len(one["problems"]) == 1 and "单桶" in one["problems"][0]
          and "不可用" in one["problems"][0], str(one["problems"]))
    check("2b 单桶 ok 仍为 False（判据未放宽：单桶查询确实是全量扫描）",
          one["ok"] is False, str(one))
    check("2c 单桶的 expected_scan / max_bucket_share 数值面上仍是 1.0（数不丢）",
          one["expected_scan"] == 1.0 and one["max_bucket_share"] == 1.0
          and one["nodes"] == 100 and one["buckets"] == 1, str(one))
    one1 = routing.bucket_health({"cond_a": 1})
    check("2d 单桶单节点 {a:1} 同口径（不因 n==1 走别的分支）",
          len(one1["problems"]) == 1 and "单桶" in one1["problems"][0]
          and "不可用" in one1["problems"][0], str(one1))

    # ================= ③ 空分桶 + total_nodes =================
    print("\n【③】空分桶与 total_nodes（M3③）")
    check("3a 缺省 total_nodes 时空 counts 返回与改动前逐位一致",
          routing.bucket_health({}) == legacy_empty()
          and routing.bucket_health({}, total_nodes=None) == legacy_empty()
          and routing.bucket_health({"cond_a": 0}) == legacy_empty(),
          "%r / %r / %r" % (routing.bucket_health({}),
                            routing.bucket_health({}, total_nodes=None),
                            routing.bucket_health({"cond_a": 0})))
    check("3b 缺省时键集亦未变（不因新参数给空桶路径加键）",
          set(routing.bucket_health({})) == set(legacy_empty()),
          str(sorted(routing.bucket_health({}))))
    check("3c 真空库（total_nodes=0）仍报 ok=True·empty（不误伤空库）",
          routing.bucket_health({}, total_nodes=0) == legacy_empty(),
          str(routing.bucket_health({}, total_nodes=0)))
    bad = routing.bucket_health({}, total_nodes=7)
    check("3d 有节点但零分桶（total_nodes=7）不得再报 ok=True",
          bad["ok"] is False and bad["reason"] == "empty_buckets"
          and bad["buckets"] == 0 and bad["nodes"] == 7
          and any("分区信息缺失" in p for p in bad["problems"]), str(bad))
    check("3e 多桶返回键集与改动前一致（7 键，无新增键）",
          set(multi) == {"ok", "buckets", "nodes", "max_bucket_share",
                         "singleton_ratio", "expected_scan", "problems"},
          str(sorted(multi)))
    live_buckets = dict(cg.index.get("buckets", {}))
    cg.index["buckets"] = {}                       # 只改内存：模拟分桶表整体缺失
    n_nodes = len(cg.index["nodes"])
    lie = routing.bucket_health(cg.index.get("buckets", {}))
    truth = routing.bucket_health(cg.index.get("buckets", {}),
                                  total_nodes=n_nodes)
    cg.index["buckets"] = live_buckets
    check("3f 真库场景：分桶表清空后有节点仍判 ok=False（缺省则复现旧假话）",
          truth["ok"] is False and lie["ok"] is True
          and truth["nodes"] == n_nodes, "%r / %r" % (lie, truth), live=True)
    check("3g 键集对照：有节点零分桶与真空库是两种读数（非「空」的同义）",
          set(truth) != set(legacy_empty())
          and truth["reason"] != legacy_empty()["reason"], str(truth))

    # ================= ④ protect.mark 负路由 =================
    print("\n【④】protect.mark 不存在节点（H9④）")
    res = protect.mark(cg, nid, "M3H9 守卫·显式保护标记")
    check("4a 成功路径既有返回键与值不变（node_id/protected/reason）",
          isinstance(res, dict) and res.get("node_id") == nid
          and res.get("protected") is True
          and res.get("reason") == "M3H9 守卫·显式保护标记", repr(res))
    pro, why = protect.is_protected(cg, nid)
    disk = cg.get(nid)["frontmatter"]
    check("4b 成功路径仍真的打上保护位（内存条目 + 盘上 frontmatter）",
          pro is True and disk.get("protected") is True
          and disk.get("protection_reason") == "M3H9 守卫·显式保护标记",
          "%r / %r" % (pro, disk), live=True)
    miss = protect.mark(cg, "m3h9_不存在", "理由")
    check("4c 不存在节点返回结构化负路由（ok/error/node_id）",
          isinstance(miss, dict) and miss.get("ok") is False
          and miss.get("error") == "node_not_found"
          and miss.get("node_id") == "m3h9_不存在", repr(miss))
    check("4d 不再裸返回 None（None 与成功在调用方不可区分）",
          miss is not None, repr(miss))
    ts = trust.set_state(cg, "m3h9_不存在", "verified")
    check("4e 形态与仓内既有负路由同形（trust.set_state 不存在分支）",
          isinstance(miss, dict) and set(miss) == set(ts)
          and ts.get("error") == "node_not_found", "%r / %r" % (miss, ts))
    odd = protect.mark(cg, None, "理由")
    check("4f 畸形 node_id（None）不裸穿透且同形",
          isinstance(odd, dict) and odd.get("error") == "node_not_found"
          and odd.get("node_id") is None, repr(odd))
    try:
        from .mcp_server import _protect_call
    except Exception as exc:                          # noqa: BLE001
        print("  [INFO] _protect_call 未取到（%s: %s），跳过 MCP 面断言"
              % (type(exc).__name__, exc))
    else:
        mcp = _protect_call(cg, {"action": "mark", "node_id": "m3h9_不存在",
                                 "reason": "理由"})
        check("4g MCP 面 mark 分支对不存在节点透出负路由（不再是 null）",
              isinstance(mcp, dict) and mcp.get("ok") is False
              and mcp.get("error") == "node_not_found", repr(mcp), live=True)

    # ================= ⑤ 源断言 + floor =================
    print("\n【⑤】源断言（单点接线在位）")
    s_routing = _src("routing.py")
    bh = _window(s_routing, "def bucket_health", "\ndef ")
    check("5a 巨桶判据带 nb > 1 守卫（与碎片化判据同形）",
          "if nb > 1 and top / n > 0.30:" in bh, bh[:400])
    check("5b 巨桶/期望扫描在 nb == 1 时合并为单桶如实读数",
          "if nb == 1:" in bh and "单桶" in bh and "elif expected_scan > 0.30:" in bh,
          bh[-600:])
    check("5c 新参数 total_nodes 带缺省值（向后兼容面）",
          "def bucket_health(counts: dict, total_nodes: int = None)" in s_routing,
          bh[:120])
    s_prot = _src("protect.py")
    mk = _window(s_prot, "def mark", "def stats")
    check("5d mark 不存在分支返回 node_not_found 负路由（不再是 None）",
          '"ok": False, "error": "node_not_found", "node_id": node_id' in mk
          and "return None" not in mk, mk[:600])
    check("5e 成功路径返回键未被改动（仍 node_id/protected/reason）",
          'return {"node_id": node_id, "protected": True, "reason": reason}' in mk,
          mk[-300:])
    print("  [INFO] live 断言数 = %d（floor=%d）" % (LIVE, LIVE_FLOOR))
    check("5f live 断言数不低于 floor（防空转绿）", LIVE >= LIVE_FLOOR,
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
    sys.exit(rc)
