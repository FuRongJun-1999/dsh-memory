# -*- coding: utf-8 -*-
"""S8 时间算子探针（阶段二 4.1，脚本式，exit code 定成败）。

用法：python -X utf8 -m md_cg.test_retr_s8_time
覆盖：
- 纯函数：轴归一与封闭枚举、按轴取窗、重叠 vs 端点模式、入参 fail-closed
- 候选层过滤：效力轴 fail-open（缺字段=沉默不是否认）/ 观察轴 fail-closed
  （缺字段=数据异常，须计数可见）
- meta["time_filter"] 审计块；默认关 meta 键集合不变
- 绕开热路径缓存（**读+写双侧**）：缓存键不含时间参数，读侧失守会返回未过滤
  结果、写侧失守会把过滤结果覆盖进缓存让后续默认查询少结果，两者都是静默错答
- stg 四 op 轴感知（observed 缺省逐位兼容 / effective 生效 / 非法轴 fail-closed）
- recall 透传

语料 15 节点（同一正文 token「阿尔法」，保证都被召回，差异只在时间字段）：
  效力组 7：eff_a[100,200] eff_b[300,400] eff_c[150,350] eff_none(无端点)
            eff_halffrom[500,-] eff_halfuntil[-,50] eff_d[1000,1100]
  观察组 7：obs_1000/2000/3000/8000/9000(temporal) obs_win_4k_5k/6k_7k(time_window)
  旧库 1：legacy_noaxis（手工抹掉 temporal 与 time_window → 观察轴不可判定）
"""
import glob
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import hotcache, nodefile, stg, trust          # noqa: E402
from md_cg.mdcg import MdCG                               # noqa: E402
from md_cg.mdcos import MdCGSecure                        # noqa: E402
from md_cg.security import Principal                      # noqa: E402

passed = 0
failed = 0
TEXT = "阿尔法 时间 探针"
QUERY = "阿尔法"
#: 效力轴上**无字段**的节点（按效力轴 fail-open 策略保留）：eff_none + 观察组 7 + 旧库 1
_NO_EFF_AXIS = {"eff_none", "legacy_noaxis",
                "obs_1000", "obs_2000", "obs_3000", "obs_t_8000", "obs_t_9000",
                "obs_win_4k_5k", "obs_win_6k_7k"}


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + detail)


def _ids(results):
    return [r[0]["id"] for r in results]


def _node_file(root, nid):
    hits = glob.glob(os.path.join(root, "**", nid + ".md"), recursive=True)
    return hits[0] if hits else None


def _build(root):
    cg = MdCG(root)
    for nid, kw in (
        ("eff_a", {"effective_from": 100, "effective_until": 200}),
        ("eff_b", {"effective_from": 300, "effective_until": 400}),
        ("eff_c", {"effective_from": 150, "effective_until": 350}),
        ("eff_none", {}),
        ("eff_halffrom", {"effective_from": 500}),
        ("eff_halfuntil", {"effective_until": 50}),
        ("eff_d", {"effective_from": 1000, "effective_until": 1100}),
        ("obs_1000", {"temporal": 1000.0}),
        ("obs_2000", {"temporal": 2000.0}),
        ("obs_3000", {"temporal": 3000.0}),
        ("obs_win_4k_5k", {"condition_space": {"time_window": [4000, 5000]}}),
        ("obs_win_6k_7k", {"condition_space": {"time_window": [6000, 7000]}}),
        ("obs_t_8000", {"temporal": 8000.0}),
        ("obs_t_9000", {"temporal": 9000.0}),
        ("legacy_noaxis", {}),
    ):
        cg.add(nid, TEXT, "knowledge", **kw)
    cg.flush()
    # 旧库形态：手工抹掉观察轴两字段（add 会强制补 time_window，只能改文件模拟）
    p = _node_file(root, "legacy_noaxis")
    fm, content = nodefile.loads(open(p, encoding="utf-8").read())
    fm.pop("temporal", None)
    cs = dict(fm.get("condition_space") or {})
    cs.pop("time_window", None)
    fm["condition_space"] = cs
    open(p, "w", encoding="utf-8").write(nodefile.dumps(fm, content))
    cg.rebuild_index()
    return cg


def main():
    # ================= 1) 纯函数层 =================
    check("轴归一：None → effective；大小写归一；believed 抛 ValueError",
          trust.time_axis_of(None) == "effective"
          and trust.time_axis_of("OBSERVED") == "observed"
          and trust.time_axis_of("effective") == "effective"
          and _raises(ValueError, lambda: trust.time_axis_of("believed")),
          str(trust.TIME_AXES))

    check("重叠模式：有交 True / 无交 False / 候选两端不可解析 False",
          trust.window_match(10, 20, 15, 25) is True
          and trust.window_match(10, 20, 30, 40) is False
          and trust.window_match(None, None, 1, 2) is False)

    check("端点模式：B1 缺省 gte/lte；单端算子不误杀全空",
          trust.window_match(10, 20, 5, 25, "gte", "lte") is True
          and trust.window_match(10, 20, 15, 25, "gte", "lte") is False
          and trust.window_match(10, 20, 5, None, "gte", None) is True
          and trust.window_match(3, 20, 5, None, "gte", None) is False)

    check("入参 fail-closed 四则：未启用 / 孤算子 / 逆序 / 非法轴",
          trust.check_time_args()[:2] == (False, None)
          and trust.check_time_args(start_operator="gte")[2] != ""
          and trust.check_time_args(start_time=300, end_time=100)[2] != ""
          and trust.check_time_args(start_time=100, time_axis="believed")[2] != "")

    check("按轴取窗：观察轴 temporal 优先于 time_window；效力轴别名回落 valid_from",
          trust.time_window_of({"temporal": 7.0,
                                "condition_space": {"time_window": [1, 2]}},
                               "observed") == (7.0, 7.0)
          and trust.time_window_of({"valid_from": 3, "valid_until": 9},
                                   "effective") == (3, 9)
          and trust.time_window_of({}, "effective") == (None, None))

    _kept, _dr, _ms = trust.filter_by_time(
        [{"effective_from": 1, "effective_until": 2}, {}], "effective", 5, 9)
    _kept2, _dr2, _ms2 = trust.filter_by_time([{}], "observed", 5, 9)
    check("轴策略：效力轴缺字段 fail-open 保留；观察轴缺字段 fail-closed 计入 missing",
          _dr == 1 and _ms == 0 and _dr2 == 1 and _ms2 == 1)

    # ================= 2) 建库 =================
    root = tempfile.mkdtemp(prefix="retr_s8_")
    cg = _build(root)

    # 默认关（无时间入参）基线
    # 注：热路径接入点是 `MdCGSecure.search_rrf`，`MdCG.search` **无缓存**——
    # 故「cached 标记」不能在此处取证（否则恒真的弱断言），见第 9 节。
    r0, m0 = cg.search(QUERY, k=20, judge=False, record=False)
    base = sorted(_ids(r0))
    r0b, m0b = cg.search(QUERY, k=20, judge=False, record=False)
    check("默认关：meta 无 time_filter、候选 15 条、二次同口径可复算",
          "time_filter" not in m0 and len(base) == 15
          and sorted(_ids(r0b)) == base,
          "n=%d keys=%s" % (len(base), sorted(m0.keys())))

    # ================= 3) 效力轴（重叠模式）=================
    r1, m1 = cg.search(QUERY, k=20, judge=False, record=False,
                       start_time=150, end_time=250, time_axis="effective")
    ids1 = set(_ids(r1))
    tf1 = m1.get("time_filter") or {}
    check("效力轴重叠：窗内相交保留、窗外剔除、无端点 fail-open 保留",
          {"eff_a", "eff_c", "eff_none"} <= ids1
          and not ({"eff_b", "eff_halffrom", "eff_halfuntil", "eff_d"} & ids1)
          and len(ids1) == 11,
          str(sorted(ids1)))
    check("效力轴：审计块 axis/mode/applied 正确、dropped 与存活数记账自洽",
          tf1.get("axis") == "effective" and tf1.get("mode") == "overlap"
          and tf1.get("applied") is True and tf1.get("dropped") == 4
          and tf1.get("dropped") + len(ids1) == 15
          and tf1.get("start") == 150 and tf1.get("end") == 250,
          str(tf1))

    # ================= 4) 观察轴（窗口语义 + fail-closed）=================
    r2, m2 = cg.search(QUERY, k=20, judge=False, record=False,
                       start_time=2500, end_time=3500, time_axis="observed")
    ids2 = _ids(r2)
    tf2 = m2.get("time_filter") or {}
    check("观察轴：temporal 命中唯一、效力组按观测窗不相交剔除",
          ids2 == ["obs_3000"], str(ids2))
    check("观察轴：无字段节点 fail-closed 并计入 axis_missing",
          tf2.get("axis_missing") == 1 and tf2.get("dropped") == 14
          and tf2.get("dropped") + len(ids2) == 15, str(tf2))

    # ================= 5) 端点模式（单端算子）=================
    r3, m3 = cg.search(QUERY, k=20, judge=False, record=False,
                       start_time=150, start_operator="gte",
                       time_axis="effective")
    ids3 = set(_ids(r3))
    tf3 = m3.get("time_filter") or {}
    # 只给起点算子 → 只筛起点侧：eff_a（起点 100<150）与 eff_halfuntil（起点缺失、
    # 端点模式下该侧不可比较）被剔除；eff_none 与全部观察组/旧库节点在效力轴**无字段**
    # → fail-open 保留（沉默不是否认）。此处非空集本身即旧缺陷（单端算子恒空）的回归证据。
    check("端点模式：单端 gte 只筛起点侧且不返回空集、无该轴字段者 fail-open 保留",
          ids3 == {"eff_b", "eff_c", "eff_d", "eff_halffrom"} | _NO_EFF_AXIS
          and tf3.get("mode") == "endpoint"
          and tf3.get("start_operator") == "gte"
          and tf3.get("dropped") == 2, str(sorted(ids3)))

    # ================= 6) 误用 fail-closed =================
    check("误用三则经库层抛 ValueError（孤算子 / 逆序 / 非法轴）",
          _raises(ValueError, lambda: cg.search(
              QUERY, k=5, judge=False, record=False, start_operator="gte"))
          and _raises(ValueError, lambda: cg.search(
              QUERY, k=5, judge=False, record=False, start_time=300, end_time=100))
          and _raises(ValueError, lambda: cg.search(
              QUERY, k=5, judge=False, record=False, start_time=100,
              time_axis="believed")))

    # ================= 7) stg 四 op 轴感知 =================
    tl_obs = stg.timeline(cg, limit=100, time_axis="observed")
    tl_eff = stg.timeline(cg, limit=100, time_axis="effective")
    check("stg timeline：观察轴 14 条（旧库节点不可判定被跳过）、效力轴 4 条（两端齐备）",
          tl_obs["count"] == 14 and tl_eff["count"] == 4,
          "obs=%s eff=%s" % (tl_obs["count"], tl_eff["count"]))
    check("stg timeline：缺省轴与显式 observed 逐位一致（旧行为兼容）",
          stg.timeline(cg, limit=100)["count"] == tl_obs["count"])

    # 返回结构取证：relation 的时间结果在 ["time"]["relation"]（非顶层 time_relation）
    rel_eff = stg.relation(cg, "eff_a", "eff_b", time_axis="effective")
    rel_obs = stg.relation(cg, "eff_a", "eff_b", time_axis="observed")
    check("stg relation：效力轴取 effective 区间（eff_a before eff_b）；观察轴取写入观测时刻（区间不同）",
          rel_eff["time"]["relation"] == "before"
          and rel_eff["time"]["a"] == (100.0, 200.0)
          and rel_obs["time"]["a"] != (100.0, 200.0),
          "%s / %s" % (rel_eff["time"], rel_obs["time"]))

    an_eff = stg.anchors(cg, time_window=[150, 250], limit=50,
                         time_axis="effective")
    an_obs = stg.anchors(cg, time_window=[150, 250], limit=50,
                         time_axis="observed")
    check("stg anchors：效力轴命中 2（eff_a overlaps + eff_c contains）、观察轴 0",
          an_eff["count"] == 2 and an_obs["count"] == 0,
          "eff=%s obs=%s" % (an_eff["count"], an_obs["count"]))

    check("stg 非法轴 fail-closed（四 op 同源 trust.time_axis_of）",
          _raises(ValueError, lambda: stg.consistency(cg, time_axis="believed"))
          and _raises(ValueError, lambda: stg.relation(
              cg, "eff_a", "eff_b", time_axis="believed")))

    # ================= 8) 关→开→关 默认口径不变 =================
    # 置于 Secure 层操作**之前**：那些调用会记录访问（recall 无法关 record），
    # 可能与基线产生与时间算子无关的差异，污染「首末一致」这一断言。
    r5, m5 = cg.search(QUERY, k=20, judge=False, record=False)
    check("默认口径等价：关→开→关 首末一致且无 time_filter 键",
          sorted(_ids(r5)) == base and "time_filter" not in m5)

    # ================= 9) 热缓存：命中 + 时间算子读/写双侧绕行 =================
    sec = MdCGSecure(root, principal=Principal(
        actor="test-s8", clearance="secret", can_write=True,
        role="designer", auth_mode="local-cli"))
    hotcache.attach(sec)
    _sa, sma = sec.search_rrf(QUERY, k=20, judge=False, record=False)
    _sb, smb = sec.search_rrf(QUERY, k=20, judge=False, record=False)
    check("热缓存：同参二次 search_rrf 命中（cached=True）且结果一致",
          sma.get("cached") is not True and smb.get("cached") is True
          and [r[0]["id"] for r in _sa] == [r[0]["id"] for r in _sb],
          "a=%s b=%s" % (sma.get("cached"), smb.get("cached")))

    # 上一步已把 15 条全量结果写进缓存键（键不含时间参数）。带时间算子的查询
    # 若只绕开「读」而漏掉「写」，则返回的 11 条会把缓存覆盖成子集 —— 故下方
    # 「随后默认查询仍为 15 条」是**写侧绕行**的判别性证据。
    _t1, mt1 = sec.search_rrf(QUERY, k=20, judge=False, record=False,
                              start_time=150, end_time=250,
                              time_axis="effective")
    check("时间算子启用时绕开热缓存：缓存已有 15 条全量，仍返回过滤后 11 条、meta 无 cached",
          "cached" not in mt1 and len(_t1) == 11
          and sorted(r[0]["id"] for r in _t1) == sorted(ids1),
          "n=%d cached=%s" % (len(_t1), mt1.get("cached")))
    _d2, md2 = sec.search_rrf(QUERY, k=20, judge=False, record=False)
    check("时间算子查询不污染缓存（写侧同受绕行约束）：其后默认查询仍为全量 15 条",
          len(_d2) == 15 and md2.get("cached") is True,
          "n=%d cached=%s" % (len(_d2), md2.get("cached")))

    # ================= 10) recall 透传 =================
    out = sec.recall(QUERY, k=20, judge=False, start_time=2500,
                     end_time=3500, time_axis="observed")
    mr = out.get("meta") or {}
    ids_r = [e["id"] for e in (out.get("pack") or [])]
    check("recall 透传：meta 带 time_filter（观察轴）且过滤真实生效",
          (mr.get("time_filter") or {}).get("axis") == "observed"
          and ids_r == ["obs_3000"], str(ids_r))

    # ================= 11) Secure.search 常规路径审计块（MCP cg(op=read) 实走此路）=================
    # 判别性：本节的观测量=「过滤生效 ∧ meta 带审计块」**同时**成立，缺一即 FAIL。
    # 缺陷史（2026-09-20 取证）：候选层过滤已在 `_candidates` 完成（结果正确），但
    # `MdCGSecure.search` 的**常规返回路径**未把 `_time_filter_stat` 交给 `_emit` ——
    # 审计块此前只在 no_candidates 分支落键 → 「过滤确实生效而审计不可见」（静默，
    # 调用方无法区分「未启用」与「启用但候选全 fail-open 保留」）。
    # 只用 `cg.search`（父类，本无此缺口）或 `search_rrf`（另行落键）**均测不到**该缺口，
    # 故单列一节：本节的红/绿随该唯一缺口翻转，是它的判别性守卫。
    _s11, m11 = sec.search(QUERY, k=20, judge=False, record=False,
                           start_time=150, end_time=250, time_axis="effective")
    tf11 = m11.get("time_filter") or {}
    check("Secure.search 常规路径：过滤生效且 meta 带 time_filter（审计块不被吞）",
          sorted(r[0]["id"] for r in _s11) == sorted(ids1)
          and tf11.get("axis") == "effective" and tf11.get("mode") == "overlap"
          and tf11.get("applied") is True and tf11.get("dropped") == 4,
          "n=%d tf=%s" % (len(_s11), tf11))

    _s11b, m11b = sec.search(QUERY, k=20, judge=False, record=False)
    check("Secure.search 默认关：候选不变且 meta 键集合不含 time_filter（默认关零变更）",
          "time_filter" not in m11b and len(_s11b) == 15,
          "n=%d keys=%s" % (len(_s11b), sorted(m11b.keys())))

    print("\ntest_retr_s8: %d 通过 / %d 失败" % (passed, failed))
    return 0 if failed == 0 else 1


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
