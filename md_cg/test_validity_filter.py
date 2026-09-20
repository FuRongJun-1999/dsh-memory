# -*- coding: utf-8 -*-
"""查询侧时效过滤（validity）验收 · GBrain 可借鉴点交接 §3②

【裁决】使用者三处拍板，是本文件全部断言的判据来源：
  ① 候选面**只排已过期**（valid_until 已过）；**未生效（valid_from 未到）保留**。
     依据仓内既有纪律：`scrub` 模块「valid_from 绝不并入 _EXPIRY_KEYS」——
     `not_yet`（尚未开始）与 `expired`（已经失效）语义相反；预约/计划类记忆
     在生效前仍应可召回，故不得用「时间轴上不活跃」一刀切。
  ② 启用默认值 = **opt-in 默认关**（缺省不过滤）：零 rust 镜像义务（保 py↔rust
     零漂移硬承诺）、零 bench 漂移、完全可逆。
  ③ 过滤落在**候选层**（一处过滤全链路生效：search / search_rrf / recall），
     与 session / branch 过滤同构；MCP 面三入口透传。

【覆盖】
  ① `trust.is_expired` 布尔语义（四态→布尔；端点不可解析不猜测）+ scrub 纪律交叉守卫
  ② 候选面：MdCG.search（裸核心）/ MdCGSecure.search（角色面）
  ③ 默认关：缺省口径与启用口径逐条对照（opt-in 可逆性）
  ④ search_rrf：融合面 + query 热缓存分键（validity 不入键会串口径）
  ⑤ recall：RRF 分支 + 非 RRF 分支
  ⑥ 图扩展：零词面交集节点经 edges 扩散可达时同样受 validity 约束
  ⑦ MCP 面三入口透传（cg op=read / mdcg_search / mdcg_recall）

【不适用】写入侧（add 落 valid_from/valid_until 是本项前提，非本项范围）；
  库内真实数据面（当前 13514 节点零有效期，故本项为 opt-in 零漂移）。
"""
import os
import shutil
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows cmd 默认 GBK：测试自带 UTF-8 兜底，不依赖调用方记得加 -X utf8。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import hotcache, mcp_server as MS, scrub, trust
from md_cg.mdcg import MdCG
from md_cg.mdcos import MdCGSecure
from md_cg.security import DEFAULT_SENSITIVITY, Principal

_ok = 0
_bad = []


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[PASS] " + name)
    else:
        _bad.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:220]))


Q = "量子咖啡机萃取压力曲线"          # 罕见词：测试库内确定性命中
PAST, FUT = "2001-01-01", "2099-01-01"


def _princ():
    return Principal(actor="t_validity", clearance=DEFAULT_SENSITIVITY,
                     can_write=True, can_admin=True, role="designer")


def _ids(res):
    """命中集 id 清单。

    口径=**nid 是否在命中集**，而非「结果为空」——全扫兜底返回低分节点
    是检索器既有行为，不属过滤失败。
    """
    out = []
    for r in res or []:
        n = r[0] if isinstance(r, tuple) else r
        if isinstance(n, dict) and isinstance(n.get("node"), dict):
            n = n["node"]        # _cg_call(op=read) 的 {"node": view} 包装
        out.append((n or {}).get("id"))
    return out


def _seed(cg):
    """三态语料：expired / not_yet / unknown + 一条图扩展专用的 expired。"""
    cg.add("mem_now", Q + " 现行规格 9 巴", layer="knowledge",
           verification_basis="test", consistency=False)
    cg.add("mem_old", Q + " 旧版规格已被取代", layer="knowledge",
           verification_basis="test", consistency=False, valid_until=PAST)
    cg.add("mem_future", Q + " 下一代规格预告", layer="knowledge",
           verification_basis="test", consistency=False, valid_from=FUT)
    cg.add("mem_hub", Q + " 主档索引", layer="knowledge",
           verification_basis="test", consistency=False,
           edges=[{"target": "mem_ghost", "relation_type": "causal"}])
    # 词面与 Q 零交集：只能经图扩展（edges）抵达 —— 图扩展绕过候选层时的靶子
    cg.add("mem_ghost", "旁系条目与提问没有任何词面重合", layer="knowledge",
           verification_basis="test", consistency=False, valid_until=PAST)


# ---------------------------------------------------------------- ① 纯函数
def _t1():
    check("①expired → True", trust.is_expired({"valid_until": PAST}) is True)
    check("①not_yet 不算过期（语义相反纪律）",
          trust.is_expired({"valid_from": FUT}) is False)
    check("①active → False",
          trust.is_expired({"valid_from": "2020-01-01",
                            "valid_until": "2030-01-01"}) is False)
    check("①unknown（无时间轴）→ False", trust.is_expired({}) is False)
    check("①None 入参 → False", trust.is_expired(None) is False)
    check("①端点不可解析 → 不猜测（False，不误判为过期）",
          trust.is_expired({"valid_until": "不是时间"}) is False)
    check("①now 显式传入生效",
          trust.is_expired({"valid_until": "2030-01-01"},
                           now=trust.parse_time("2035-01-01")) is True)
    check("①判定序：未来起点优先（not_yet 而非 expired）",
          trust.validity({"valid_from": FUT, "valid_until": PAST})[0] == "not_yet")
    check("①scrub 纪律交叉守卫：valid_from 绝不并入 _EXPIRY_KEYS",
          "valid_from" not in scrub._EXPIRY_KEYS
          and "valid_until" in scrub._EXPIRY_KEYS
          and "valid_from" in scrub._NOT_YET_KEYS,
          str(scrub._EXPIRY_KEYS))
    # ---- 2026-09-19 阶段一：规范键族 + 第三类语义（信念时间）交叉守卫 ----
    check("①阶段一：effective_from 属未生效族、绝不入已结束族",
          "effective_from" in scrub._NOT_YET_KEYS
          and "effective_from" not in scrub._EXPIRY_KEYS,
          str(scrub._EXPIRY_KEYS))
    check("①阶段一：effective_until/expired_at 属已结束族、不入未生效族",
          "effective_until" in scrub._EXPIRY_KEYS
          and "expired_at" in scrub._EXPIRY_KEYS
          and "effective_until" not in scrub._NOT_YET_KEYS
          and "expired_at" not in scrub._NOT_YET_KEYS,
          str(scrub._EXPIRY_KEYS))
    check("①阶段一：believed_at 两族都不入（第三类语义·物理隔离）",
          trust.BELIEVED_FIELD not in scrub._EXPIRY_KEYS
          and trust.BELIEVED_FIELD not in scrub._NOT_YET_KEYS,
          str(scrub._EXPIRY_KEYS))
    check("①键族同步守卫：trust 别名元组 ⊆ scrub 对应键族（两侧禁各自漂移）",
          set(trust.FROM_ALIASES) <= set(scrub._NOT_YET_KEYS)
          and set(trust.UNTIL_ALIASES) <= set(scrub._EXPIRY_KEYS),
          str(trust.FROM_ALIASES) + " / " + str(scrub._NOT_YET_KEYS))
    # ---- 规范键优先、别名回落（双轨读取）----
    check("①规范键优先：effective_from 压过 valid_from",
          trust.validity({"effective_from": FUT,
                          "valid_from": "2020-01-01"})[0] == "not_yet")
    check("①别名回落：仅历史键时照常判定（存量兼容）",
          trust.validity({"valid_from": FUT})[0] == "not_yet")
    check("①规范键不可解析 → 继续回落别名（不因写坏一键而漏判）",
          trust.validity({"effective_until": "坏值",
                          "valid_until": PAST})[0] == "expired")
    check("①believed_at 不参与时效判定（物理隔离·绝不误判）",
          trust.validity({"believed_at": PAST})[0] == "unknown"
          and trust.is_expired({"believed_at": PAST}) is False)
    check("①believed_at 读取器：epoch 值 / 缺字段 None",
          trust.believed_at({"believed_at": PAST}) is not None
          and trust.believed_at({}) is None)
    check("①time_window_msg 点名实际命中键（规范名/历史名各归其位）",
          "effective_from" in trust.time_window_msg({"effective_from": FUT})
          and "valid_from" in trust.time_window_msg({"valid_from": FUT}))


# ------------------------------------------------- ②③ 候选面 + 默认关
def _t2(root_core, root_sec):
    core = MdCG(root_core)
    _seed(core)

    off = _ids(core.search(Q, k=20)[0])
    check("③MdCG.search 默认关：expired 可见（opt-in 可逆）",
          "mem_old" in off, off)
    check("③MdCG.search 默认关：not_yet 可见", "mem_future" in off, off)
    on = _ids(core.search(Q, k=20, validity=True)[0])
    check("②MdCG.search 启用后 expired 剔除", "mem_old" not in on, on)
    check("②MdCG.search 启用后 not_yet 保留", "mem_future" in on, on)
    check("②MdCG.search 启用后 unknown 保留", "mem_now" in on, on)

    sec = MdCGSecure(root_sec, principal=_princ())
    _seed(sec)
    sec_off = _ids(sec.search(Q, k=20)[0])
    check("③Secure.search 默认关：expired 可见", "mem_old" in sec_off, sec_off)
    sec_on = _ids(sec.search(Q, k=20, validity=True)[0])
    check("②Secure.search 启用后 expired 剔除", "mem_old" not in sec_on, sec_on)
    check("②Secure.search 启用后 not_yet 保留",
          "mem_future" in sec_on, sec_on)


# --------------------------- ④ RRF + 缓存分键  ⑤ recall  ⑥ 图扩展
def _t3(root):
    cg = MdCGSecure(root, principal=_princ())
    _seed(cg)
    hotcache.attach(cg)

    off, _ = cg.search_rrf(Q, k=20)
    on, _ = cg.search_rrf(Q, k=20, validity=True)
    check("④search_rrf 默认关：expired 可见", "mem_old" in _ids(off), _ids(off))
    check("④search_rrf 启用后 expired 剔除", "mem_old" not in _ids(on), _ids(on))
    check("④search_rrf 启用后 not_yet 保留", "mem_future" in _ids(on), _ids(on))

    # 缓存分键：两口径必须各自成键，否则第二次调用命中第一次的缓存即串口径
    hc = hotcache.get(cg)
    on2, meta2 = cg.search_rrf(Q, k=20, validity=True)
    off2, meta_off = cg.search_rrf(Q, k=20)
    check("④缓存命中路径仍零 expired（meta.cached 可证命中）",
          "mem_old" not in _ids(on2) and meta2.get("cached") is True,
          "cached=%s ids=%s" % (meta2.get("cached"), _ids(on2)))
    check("④两口径各自成键且互不顶替（默认口径仍见 expired 且命中自身缓存）",
          "mem_old" in _ids(off2) and meta_off.get("cached") is True,
          "off_cached=%s ids=%s" % (meta_off.get("cached"), _ids(off2)))
    check("④缓存中两口径键并存（>=2 条）",
          hc.stats()["query_cache_size"] >= 2, hc.stats())

    # ⑥ 图扩展：零词面交集节点只能经 edges 抵达 —— 前置证据 + 过滤断言
    check("⑥前置证据：不过滤时 ghost 经图扩展可达（零词面交集）",
          "mem_ghost" in _ids(off), _ids(off))
    check("⑥启用后 ghost 被剔除（图扩展不绕过时效过滤）",
          "mem_ghost" not in _ids(on), _ids(on))

    # ⑤ recall 两分支
    p_off = [p.get("id") for p in cg.recall(Q, budget_tokens=6000, k=20)["pack"]]
    check("⑤recall（RRF 分支）默认关：expired 可见", "mem_old" in p_off, p_off)
    p_rrf = [p.get("id") for p in cg.recall(Q, budget_tokens=6000, k=20,
                                            validity=True)["pack"]]
    check("⑤recall（RRF 分支）启用后 expired 剔除", "mem_old" not in p_rrf, p_rrf)
    check("⑤recall（RRF 分支）not_yet 保留", "mem_future" in p_rrf, p_rrf)
    p_lin = [p.get("id") for p in cg.recall(Q, budget_tokens=6000, k=20,
                                            use_rrf=False, validity=True)["pack"]]
    check("⑤recall（非 RRF 分支）启用后 expired 剔除",
          "mem_old" not in p_lin, p_lin)
    check("⑤recall（非 RRF 分支）not_yet 保留", "mem_future" in p_lin, p_lin)


# ------------------------------------------------------------- ⑦ MCP 面
def _t4(root):
    cg = MdCGSecure(root, principal=_princ())
    _seed(cg)

    s_on = MS.call_tool(cg, "mdcg_search",
                        {"query": Q, "k": 20, "validity": True})
    ids_on = [r["node"]["id"] for r in s_on["results"]]
    check("⑦mdcg_search 透传 validity（expired 剔除）",
          "mem_old" not in ids_on, ids_on)
    check("⑦mdcg_search 透传后 not_yet 保留", "mem_future" in ids_on, ids_on)
    s_off = MS.call_tool(cg, "mdcg_search", {"query": Q, "k": 20})
    ids_off = [r["node"]["id"] for r in s_off["results"]]
    check("⑦默认关：mdcg_search 缺省 expired 可见", "mem_old" in ids_off, ids_off)

    rc = MS.call_tool(cg, "mdcg_recall",
                      {"query": Q, "k": 20, "budget_tokens": 6000,
                       "validity": True})
    pids = [p.get("id") for p in rc["pack"]]
    check("⑦mdcg_recall 透传 validity（expired 剔除）",
          "mem_old" not in pids, pids)
    rc_off = MS.call_tool(cg, "mdcg_recall",
                          {"query": Q, "k": 20, "budget_tokens": 6000})
    check("⑦默认关：mdcg_recall 缺省 expired 可见",
          "mem_old" in [p.get("id") for p in rc_off["pack"]], rc_off.get("pack"))

    out = MS._cg_call(cg, {"op": "read", "query": Q, "k": 20, "validity": True})
    oids = _ids(out.get("results") or [])
    check("⑦cg op=read 透传 validity（expired 剔除）", "mem_old" not in oids, oids)
    out_off = MS._cg_call(cg, {"op": "read", "query": Q, "k": 20})
    check("⑦默认关：cg op=read 缺省 expired 可见",
          "mem_old" in _ids(out_off.get("results") or []),
          _ids(out_off.get("results") or []))


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_validity_")
    try:
        _t1()
        _t2(os.path.join(tmp, "core"), os.path.join(tmp, "sec"))
        _t3(os.path.join(tmp, "rrf"))
        _t4(os.path.join(tmp, "mcp"))
    except Exception:
        traceback.print_exc()
        _bad.append("未捕获异常")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nvalidity 验收：%d 通过%s" % (
        _ok, ("，%d 失败：%s" % (len(_bad), "; ".join(_bad))) if _bad else ""))
    return 1 if _bad else 0


if __name__ == "__main__":
    sys.exit(main())
