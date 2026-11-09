"""
test_t64a_dedup.py — E-T64a t1 同日同决策去重合并验收（灵枢写路径）

accept 契约（不许破坏）：
  1. 判定面语义不倒退：judgment_rules.judge_text 对既有 t09a/t11a/t18a 代表
     样本判定一字不变；_PRIORITY 次序不动（本测试只读判定面，不改动它）。
  2. 4 条钉存样本 + 3 条纯保持样本一条不误并。
  3. 默认关回归：MDCG_JUDGMENT 未设或显式 0 时，两条近重复文本仍按原样成
     两个节点（逐字节与接线前一致，fm 无合并字段夹带）。

去重口径（写路径）：仅当两条**同一天**（同一 UTC 日期，见 mdcg.dedup_day_key）
写入的文本满足「同一决策、后一条只比前一条多后半句」时判重：
  · 纯前缀：前一条去首尾空白后是后一条的字符串前缀；
  · 句前缀：按句切分后前一条的句子序列是后一条句子序列的前缀。
判中时不新建节点：正文更新为较长那条，fm 记 merged_from / merge_count，
add 返回既有节点 id（合并信号）。跨天不判（隔天同句仍两条）。

运行：cd D:\\wook\\lingshu-src && python -X utf8 -m md_cg.test_t64a_dedup
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg import judgment_rules as jr          # noqa: E402
from md_cg import mdcg                          # noqa: E402
from md_cg.mdcos import MdCGOS                  # noqa: E402

passed = failed = 0
_ENV_KEY = "MDCG_JUDGMENT"
_ENV_PREV = os.environ.pop(_ENV_KEY, None)      # 本测试全程自管开关状态

DAY = 1767225600.0                               # 2026-01-01T00:00:00Z（UTC）
NEXT_DAY = DAY + 86400.0                         # 2026-01-02（跨天边界）

#: 去重合并字段（mdcg.py 实现自定值；本测试按实现断言）。
_MERGE_COUNT = mdcg.DEDUP_MERGE_COUNT_FIELD      # "merge_count"
_MERGED_FROM = mdcg.DEDUP_MERGED_FROM_FIELD      # "merged_from"

#: ① 判重合并样本：『同一决策、后一条只比前一条多后半句』。
PREFIX_PAIR = ("决定：把索引改成倒排",
               "决定：把索引改成倒排，因为查询快")
PREFIX_CHAIN = ("决定：把索引改成倒排",
                "决定：把索引改成倒排，因为查询快",
                "决定：把索引改成倒排，因为查询快，而且索引分裂瓶颈也解决了")
SENT_PAIR = ("今天决定用 SQLite",
             "今天决定用 SQLite，因为它零配置")
SENT_BOUNDARY = ("今天决定用 SQLite。",
                 "今天决定用 SQLite！明天再对比。")

#: ② 不该合并的边界样本。
CROSS_DAY_PAIR = PREFIX_PAIR                     # 跨天同句 → 两条
HEAD_DIFF = ("A 决定用 SQLite", "B 决定用 SQLite")   # 只差前半句
UNRELATED = ("今天天气不错", "决定：把索引改成倒排")  # 完全无关
DECISION_DIFF = ("决定用 SQLite", "决定用 Postgres")  # 后半句是不同决策
IDENTICAL = ("决定：把索引改成倒排", "决定：把索引改成倒排")  # 同句无后半句

#: ③ 契约样本：t09a/t11a/t18a 代表样本（judge + verdict 与既有期望一致）。
T09A_SAMPLES = (("给我生成一份PDF", "J7", jr.DROP),
                ("把数据导出来给我", "J7", jr.DROP))
T11A_SAMPLES = (("npm error code ELIFECYCLE", "J9", jr.DROP),
                ("收到收到", "J9", jr.DROP))
T18A_SAMPLES = (("今天把 report.pdf 生成一下", "J7", jr.DROP),
                ("我讨厌你先讲道理，先接住我的情绪再说", "J1", jr.KEEP))

#: ④ 钉存样本（t09a PINS）与纯保持样本（t09a PURE_KEEP）——一条不误并。
PINS = ("帮我记住我的生日是5月20日",
        "记一下我的邮箱是 a@b.com",
        "记住：项目名是 wook",
        "以后叫我小R")
PURE_KEEPS = ("我主力语言是 Python，讨厌过度抽象",
              "我的生日是5月20日",
              "项目名是 wook")


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:300])


def _fm_of(cg, nid):
    """node_id 的 frontmatter；节点缺席（ID 为假 / get 为空）返回 None。"""
    if not nid:
        return None
    try:
        got = cg.get(nid)
    except Exception:
        return None
    if not got:
        return None
    return got.get("frontmatter")


def _body_of(cg, nid):
    """node_id 的正文（去首尾空白）；节点缺席返回 None。"""
    try:
        got = cg.get(nid)
    except Exception:
        return None
    if not got:
        return None
    return (got.get("content") or "").strip()

def _mk_cg():
    return MdCGOS(tempfile.mkdtemp(prefix="mdcg_t64a_"))


def _node_count(cg):
    return len((cg.index.get("nodes") or {}))


# ---------------------------------------------------------------------------
# [A] 判重合并：同日同决策、只差后半句 → 并入既有节点（不新建，返回既有 id）
# ---------------------------------------------------------------------------

def test_a_merge():
    print("[A] 判重合并：同日同决策前缀/句前缀 → 并入既有节点")
    _env_prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"
    try:
        # ---- ① 纯前缀链：'决定：把索引改成倒排' → +'，因为查询快'
        #        → +'，而且索引分裂瓶颈也解决了'（链式并入同一节点）----
        kg = _mk_cg()
        r1 = kg.add("a1", PREFIX_PAIR[0], created_at=DAY)
        check("第一条照常新建：返回自身 id", r1 == "a1", "r1=%r" % (r1,))
        r2 = kg.add("a2", PREFIX_PAIR[1], created_at=DAY)
        check("第二条判中合并：add 返回**既有**节点 id（合并信号）",
              r2 == "a1", "r2=%r（期望复用 a1，而非新建 a2）" % (r2,))
        check("节点总数仍为 1（未新建第二个节点）",
              _node_count(kg) == 1, "nodes=%d" % _node_count(kg))
        check("正文已并入较长那条（'%s'）" % PREFIX_PAIR[1],
              _body_of(kg, "a1") == PREFIX_PAIR[1],
              repr(_body_of(kg, "a1")))
        fm1 = _fm_of(kg, "a1") or {}
        check("fm 记录合并来源：merged_from 含被并入的 a2",
              list(fm1.get(_MERGED_FROM) or []) == ["a2"],
              str(fm1.get(_MERGED_FROM)))
        check("fm 记录合并计数：merge_count == 1",
              int(fm1.get(_MERGE_COUNT) or 0) == 1,
              str(fm1.get(_MERGE_COUNT)))

        # ---- ② 链式合并：第三条再并入同一节点，计数递增 ----
        r3 = kg.add("a3", PREFIX_CHAIN[2], created_at=DAY)
        check("第三条（更长）仍并入 a1 而非新建",
              r3 == "a1" and _node_count(kg) == 1, "r3=%r nodes=%d"
              % (r3, _node_count(kg)))
        fm1b = _fm_of(kg, "a1") or {}
        check("链式合并正文 = 第三条较长文本",
              _body_of(kg, "a1") == PREFIX_CHAIN[2],
              repr(_body_of(kg, "a1")))
        check("链式合并 merge_count 递增为 2 且 merged_from 追加 a3",
              int(fm1b.get(_MERGE_COUNT) or 0) == 2
              and list(fm1b.get(_MERGED_FROM) or []) == ["a2", "a3"],
              "count=%r from=%r" % (fm1b.get(_MERGE_COUNT),
                                    fm1b.get(_MERGED_FROM)))
        shutil.rmtree(kg.root, ignore_errors=True)

        # ---- ③ 句前缀：'今天决定用 SQLite' → +'，因为它零配置' ----
        kg2 = _mk_cg()
        s1 = kg2.add("b1", SENT_PAIR[0], created_at=DAY)
        s2 = kg2.add("b2", SENT_PAIR[1], created_at=DAY)
        check("句前缀样本同样合并（返回 b1，总节点 1）",
              s2 == s1 == "b1" and _node_count(kg2) == 1,
              "s1=%r s2=%r nodes=%d" % (s1, s2, _node_count(kg2)))
        fmb = _fm_of(kg2, "b1") or {}
        check("句前缀样本正文并入较长那条 + merge_count 记录",
              _body_of(kg2, "b1") == SENT_PAIR[1]
              and int(fmb.get(_MERGE_COUNT) or 0) == 1,
              repr(_body_of(kg2, "b1")))
        shutil.rmtree(kg2.root, ignore_errors=True)

        # ---- ④ 真句边界：前一条以句号收尾，后一条多了整句 ----
        kg3 = _mk_cg()
        t1 = kg3.add("c1", SENT_BOUNDARY[0], created_at=DAY)
        t2 = kg3.add("c2", SENT_BOUNDARY[1], created_at=DAY)
        check("按句切分前缀（句号边界）同样合并，未新建",
              t2 == t1 == "c1" and _node_count(kg3) == 1
              and _body_of(kg3, "c1") == SENT_BOUNDARY[1],
              "t1=%r t2=%r nodes=%d body=%r"
              % (t1, t2, _node_count(kg3), _body_of(kg3, "c1")))
        shutil.rmtree(kg3.root, ignore_errors=True)
    finally:
        if _env_prev is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = _env_prev


# ---------------------------------------------------------------------------
# [B] 不该合并的边界：跨天 / 只差前半句 / 无关 / 不同决策 / 同句无后半句
# ---------------------------------------------------------------------------

def _two_nodes_case(label, first, second, ts_first=DAY, ts_second=DAY,
                    nid1="x1", nid2="x2"):
    """同日/异日写两条 → 必须仍是 2 个节点、第二条返回自身 id、无合并字段。"""
    cg = _mk_cg()
    try:
        r1 = cg.add(nid1, first, created_at=ts_first)
        r2 = cg.add(nid2, second, created_at=ts_second)
        check("%s：两条各自成节点（2 个，未合并且未新建串扰）" % label,
              r1 == nid1 and r2 == nid2 and _node_count(cg) == 2,
              "r1=%r r2=%r nodes=%d" % (r1, r2, _node_count(cg)))
        fm1 = _fm_of(cg, nid1) or {}
        fm2 = _fm_of(cg, nid2) or {}
        check("  └ 两条 fm 均无合并字段夹带（merge_count/merged_from 缺席）",
              _MERGE_COUNT not in fm1 and _MERGE_COUNT not in fm2
              and _MERGED_FROM not in fm1 and _MERGED_FROM not in fm2,
              "fm1=%s fm2=%s" % (fm1, fm2))
        check("  └ 正文各自保持原文（未串改）",
              _body_of(cg, nid1) == first.strip()
              and _body_of(cg, nid2) == second.strip(),
              "body1=%r body2=%r" % (_body_of(cg, nid1), _body_of(cg, nid2)))
    finally:
        shutil.rmtree(cg.root, ignore_errors=True)


def test_b_no_merge():
    print("[B] 不该合并的边界：跨天 / 只差前半句 / 无关 / 不同决策 / 同句")
    _env_prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"               # 去重开关开启下断言不合并边界
    try:
        _two_nodes_case("跨天同句（隔天写同样两句）",
                        CROSS_DAY_PAIR[0], CROSS_DAY_PAIR[1],
                        ts_first=DAY, ts_second=NEXT_DAY)
        _two_nodes_case("只差前半句（A/B 决定用 SQLite）",
                        HEAD_DIFF[0], HEAD_DIFF[1])
        _two_nodes_case("完全无关同日两条", UNRELATED[0], UNRELATED[1])
        _two_nodes_case("后半句是不同决策（SQLite vs Postgres）",
                        DECISION_DIFF[0], DECISION_DIFF[1])
        _two_nodes_case("同日同句（无后半句可并入）",
                        IDENTICAL[0], IDENTICAL[1])
        check("同日口径显式断言：DAY 与 NEXT_DAY 是不同 UTC 日期、DAY 与 DAY+1 同一天",
              mdcg.dedup_day_key(DAY) != mdcg.dedup_day_key(NEXT_DAY)
              and mdcg.dedup_day_key(DAY) == mdcg.dedup_day_key(DAY + 1.0),
              "%s vs %s" % (mdcg.dedup_day_key(DAY), mdcg.dedup_day_key(NEXT_DAY)))
    finally:
        if _env_prev is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = _env_prev


# ---------------------------------------------------------------------------
# [C] 契约不倒退：判定面样本一字不变 + 钉存/纯保持样本一条不误并
# ---------------------------------------------------------------------------

def test_c_contract():
    print("[C] 契约不倒退：判定面判定不变 + 钉存/纯保持不误并")
    # ---- ① judge_text 对既有 t09a/t11a/t18a 代表样本判定不变 ----
    for label, samples in (("t09a", T09A_SAMPLES), ("t11a", T11A_SAMPLES),
                           ("t18a", T18A_SAMPLES)):
        for t, judge, state in samples:
            v = jr.judge_text(t)
            check("%s 代表样本判定不变：%s → %s/%s" % (label, t, judge, state),
                  v.get("judge") == judge and v.get("state") == state,
                  jr.explain(v))
    check("_PRIORITY 次序不动（与既有接线段一字不差）",
          jr._PRIORITY == ("J9", "J7", "J8", "J11", "J10",
                           "J1", "J2", "J3", "J4", "J5", "J6"),
          str(jr._PRIORITY))

    # ---- ② 钉存样本（4）+ 纯保持样本（3）：同日重写仍各 1 节点，不误并 ----
    _env_prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"
    kg = _mk_cg()
    try:
        kept = []
        for i, t in enumerate(PINS + PURE_KEEPS):
            nid = "t64a_keep_%d" % i
            kg.add(nid, t, created_at=DAY)
        for i, t in enumerate(PINS + PURE_KEEPS):
            nid = "t64a_keep_%d" % i
            kg.add(nid, t, created_at=DAY + 1.0)   # 同日（同一天）重写
        for i, t in enumerate(PINS + PURE_KEEPS):
            nid = "t64a_keep_%d" % i
            fm = _fm_of(kg, nid) or {}
            check("同日重写后仍各只 1 节点且无合并字段：%s" % t,
                  _node_count(kg) == len(PINS + PURE_KEEPS)
                  and _MERGE_COUNT not in fm and _MERGED_FROM not in fm,
                  "nodes=%d fm=%s" % (_node_count(kg), fm))
            kept.append(nid)
        # ---- ③ 钉存两条不同内容必须仍是 2 个节点 ----
        kg2 = _mk_cg()
        p1 = kg2.add("pinA", PINS[0], created_at=DAY)
        p2 = kg2.add("pinB", PINS[1], created_at=DAY)
        check("钉存两条不同内容（'%s' / '%s'）仍是 2 个节点且未误并"
              % (PINS[0], PINS[1]),
              p1 == "pinA" and p2 == "pinB" and _node_count(kg2) == 2
              and _MERGE_COUNT not in (_fm_of(kg2, "pinA") or {})
              and _MERGE_COUNT not in (_fm_of(kg2, "pinB") or {}),
              "p1=%r p2=%r nodes=%d" % (p1, p2, _node_count(kg2)))
        shutil.rmtree(kg2.root, ignore_errors=True)
        # ---- ④ 纯保持 '我的生日是5月20日' vs 钉存 '帮我记住我的生日是5月20日'
        #        前缀危险对：不可因前缀关系把纯保持并进钉存 ----
        kg3 = _mk_cg()
        k1 = kg3.add("keepBr", "我的生日是5月20日", created_at=DAY)
        k2 = kg3.add("pinB2", "帮我记住我的生日是5月20日", created_at=DAY)
        check("前缀危险对（纯保持/钉存同头）不误并：仍 2 个节点各自原文",
              k1 == "keepBr" and k2 == "pinB2" and _node_count(kg3) == 2
              and _body_of(kg3, "keepBr") == "我的生日是5月20日"
              and _body_of(kg3, "pinB2") == "帮我记住我的生日是5月20日",
              "k1=%r k2=%r nodes=%d" % (k1, k2, _node_count(kg3)))
        shutil.rmtree(kg3.root, ignore_errors=True)
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)
        if _env_prev is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = _env_prev


# ---------------------------------------------------------------------------
# [D] 默认关回归：未设 / 显式 0 → 同日近重复两条仍成 2 个节点，无合并字段
# ---------------------------------------------------------------------------

def _off_case(label):
    """默认关口径：同日近重复两条照常成 2 个节点，fm 无合并字段夹带。"""
    cg = _mk_cg()
    try:
        r1 = cg.add("o1", PREFIX_PAIR[0], created_at=DAY)
        r2 = cg.add("o2", PREFIX_PAIR[1], created_at=DAY)
        check("%s 同日近重复两条仍成 2 个节点（返回各自 id）" % label,
              r1 == "o1" and r2 == "o2" and _node_count(cg) == 2,
              "r1=%r r2=%r nodes=%d" % (r1, r2, _node_count(cg)))
        fm1 = _fm_of(cg, "o1") or {}
        fm2 = _fm_of(cg, "o2") or {}
        check("  └ 两条 fm 均无合并字段夹带（默认关零行为）",
              _MERGE_COUNT not in fm1 and _MERGE_COUNT not in fm2
              and _MERGED_FROM not in fm1 and _MERGED_FROM not in fm2,
              "fm1=%s fm2=%s" % (fm1, fm2))
    finally:
        shutil.rmtree(cg.root, ignore_errors=True)


def test_d_default_off():
    print("[D] 默认关回归：MDCG_JUDGMENT 未设 / 显式 0 → 与接线前逐字节一致")
    os.environ.pop(_ENV_KEY, None)
    _off_case("未设")

    os.environ[_ENV_KEY] = "0"
    try:
        _off_case("显式0")
    finally:
        os.environ.pop(_ENV_KEY, None)


def main():
    print("===== md_cg.test_t64a_dedup（E-T64a t1 同日同决策去重合并验收） =====")
    test_a_merge()
    test_b_no_merge()
    test_c_contract()
    test_d_default_off()
    print("==== t64a dedup：%d 通过，%d 失败 ====" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())