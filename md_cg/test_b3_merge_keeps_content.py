# -*- coding: utf-8 -*-
# 功能名：B3 合并面「新正文去向」+ ⑤ 条件槽空值语义哨兵 守卫
# 生效条件：forgetting.reinforce 有 content/session 槽（:248）、mdcos.remember_gated
#           的 MERGE 分支传 content（:3475）、DROP 分支走 forgetting.record_drop
#           （:3490 附近）、mdcos._ccg_field 对 _COND_FIELDS 做空值化（:160 区）、
#           mdcos._declared_conditions._push 过 _is_null_condition、mdcos.check_consistency
#           剔除入参哨兵；沙箱条件：MDCG_ROOT / MDCG_AUX_ROOT / MDCG_MASTER_KEY 全指向
#           tempfile.mkdtemp 建的独立目录，绝不触在役库。
# 子功能：① knowledge 层近重复第二次写入的**新值必须落库**（MERGE 侧：聚合行进目标
#           正文 + 返回体带 content_sink 去向；DROP 侧：全文与去向落 _forgetting.jsonl
#           + 返回体带 dropped 去向单；加密级不落明文）；② reinforce 缺省 content=None
#           与改动前逐位一致（既有调用零破坏）；③ 聚合幂等（同文再写零追加）；
#           ④ H3 跨会话合并把双方归属并列落 fm（session 保留 + merge_sources）；
#           ⑤ CCG 哨兵「# 不适用条件：无」不再当真实条件：逐字相同的两节点不再判
#           condition_clash、不建工单，而真互斥仍判冲突（防放宽）。
# 执行：python -X utf8 -m md_cg.test_b3_merge_keeps_content
#       python -X utf8 -m md_cg.test_b3_merge_keeps_content --drop-fix=merge
#       python -X utf8 -m md_cg.test_b3_merge_keeps_content --drop-fix=drop
#       python -X utf8 -m md_cg.test_b3_merge_keeps_content --drop-fix=sentinel
#       python -X utf8 -m md_cg.test_b3_merge_keeps_content --drop-fix=conv_session
#       python -X utf8 -m md_cg.test_b3_merge_keeps_content --drop-fix=index
# 验证方式：本文件自跑（自带断言计数与退出码 rc=0/1）；定点变异自证见 --drop-fix
#           （把修复逐点抽回改动前语义 → 本守卫必红，且红项必须覆盖预期集合）。
# 不适用条件：情感交互｜闲聊｜纯查询无改动；CONVERGE（contextual 层同构聚合）的
#           80 字截断属同族第二处（本轮已一并收口为同一单点，见组 F 断言）；
#           mdcg.add 直连 consistency.check 的入参哨兵（mdcg.py:1785，非本席文件）
#           不在本守卫面内。
# 2026-09-30 补强（复核员实测的覆盖缺口，两条）：
#   · F5 —— mdcos.py:3466-3468 CONVERGE 分支调 writelimit.converge_into 时的
#     `session=_writer_session(self, kw)` 接线，此前无断言覆盖（源码级抽掉实参
#     后本守卫全绿）。F5 钉住写盘 fm 的归属面（merge_sources）。
#   · C4 —— forgetting.reinforce 的索引更新段此前只镜像 importance / lifecycle
#     state / protected，不同步 merge_sources（与 writelimit.converge_into :257
#     不同口径）。C4 钉住「写盘后同进程读 cg.index 即见新值」。
"""B3 + ⑤ 守卫：合并面不许静默吞正文，条件槽的哨兵不许当真实条件。

缺陷（修复前，探针读数）：
  · B3：knowledge 层「近重复但关键值不同」的第二次写入，新正文 100% 丢弃——
    MERGE 侧 `reinforce` 没有 content 槽、写回 `node.get("content")`（既有正文），
    新值全库 0 命中、目标正文逐字节未变（只 importance+0.05/merge_count+1）；
    DROP 侧（`assess` :214 的 internal_deterministic ∧ dup≥0.60 **先于** MERGE）
    连目标都不强化，新正文零去向。
  · ⑤：CCG 哨兵「# 不适用条件：无」被原样收成负条件词，单字词「无」是既有生效
    条件「…；约束：无」的子串 ⇒ `_weighted_coverage` 恒 1.0 ≥ CLASH_HIGH(0.6)
    ⇒ 任意两个带该哨兵的节点无条件 condition_clash——**连逐字相同也判 DEFER 并
    建工单**（实测 conflict_strength=1.0）。

本守卫的判别力锚点（每条都可被 --drop-fix 逐点打红）：
  A 组 MERGE 侧：新值落库 / 聚合行进目标正文（行号可指）/ 返回体带去向 / 语义未变
     （merge_count+1、importance+0.05、不新增节点）/ 幂等零追加 / content=None 逐位一致。
  B 组 DROP 侧：分支仍判 DROP（未被改成 MERGE）+ 目标未被强化 + 返回体带 trace_id +
     留痕行含新正文全文（可检索）+ 加密级不落明文。
  C 组 H3：跨会话合并 → 目标 fm.session 保留 + fm.merge_sources 记新写入方 + 新值落库。
  D 组 ⑤：哨兵逐字相同 → ACCEPT/strength 0/无工单；真互斥 → 仍判冲突（防放宽）；
     判据正反例（无/无。/（无）/None/空串/无依赖 命中；无法确定/无缓存场景/无持久化介质
     不命中）；fm 列表形态与入参列表形态同口径；非条件字段不受影响。
  F 组 CONVERGE 第二处：contextual 层同构聚合的新值落在 80 字外也不再丢（同单点）。

沙箱（硬约束）：一切读写都在 tempfile.mkdtemp 内；跑完 rmtree。绝不碰在役库。
"""
import json
import os
import shutil
import sys
import tempfile
import time

# 沙箱必须在**任何** md_cg 子模块 import 之前设好（crypto.MASTER_FILE 在模块
# 导入时求值）。
_SANDBOX = tempfile.mkdtemp(prefix="b3merge_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SANDBOX
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)

# 三档自治批次②（2026-10-02）**夹具隔离**：本守卫考的不是档位面（档位守卫 =
# md_cg/test_autonomy_modes.py），故显式置 full 档——回到改动前「动作直落」的
# 行为，使本文件的断言意图（合并/覆写/软删真的发生）逐条不变；env 键名从唯一
# 真源表取（本文件不构成第二处字面量）。
from . import autonomy_modes as _autonomy_modes          # noqa: E402
os.environ[_autonomy_modes.AUTONOMY_ENV_KEYS["mode"]] = "full"

from . import consistency, forgetting, mdcos, writelimit      # noqa: E402
from .mdcos import MdCGOS                                     # noqa: E402

_OK = 0
_BAD = []
_RUN = [0]                    # 轮次计数：每轮 _run_all 用独立子根（见 _mk）

# 近重复对：只差一个端口号（关键值）
PORT_A = "9090"
PORT_B = "9595"


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _body(port):
    """六要素 + 正文的 CCG 文本（正文行含关键值 port）。"""
    return ("# 功能名：部署面端口约定\n"
            "# 生效条件：载体/位置：prod 集群；时间：2026-09-30 起；"
            "方法：部署清单核对；约束：无\n"
            "# 子功能：登记各服务监听端口\n"
            "# 执行：核对 manifest 的 ports 段\n"
            "# 验证方式：test\n"
            "# 不适用条件：无\n"
            "\n网关监听端口 8080/HTTP；管理面监听端口 8081/HTTP；"
            f"指标面监听端口 {port}/HTTP；日志面监听端口 9091/HTTP；"
            "链路面监听端口 9092/HTTP\n")


SENT_A = _body(PORT_A)
SENT_B = _body(PORT_B)
# 真负条件的对照体（哨兵换成真实条件）
REAL_A = SENT_A.replace("# 不适用条件：无", "# 不适用条件：本地开发环境")


def _mk(tag):
    # 每轮 _run_all 用独立子根：--drop-fix 会连跑「变异态 + 恢复态」两轮，
    # 共用目录会让第二轮读到第一轮的盘面/限流状态（实测 F1 假红）。
    return MdCGOS(os.path.join(_SANDBOX, "lib_%s_r%d" % (tag, _RUN[0])),
                  autoflush=0)


def _lib_hits(cg, needle):
    """全库节点正文里字面含 needle 的节点 id（判据：新值在库里可被检索）。"""
    return sorted(n for n in cg.index["nodes"]
                  if needle in ((cg.get(n) or {}).get("content") or ""))


def _log_rows(cg, trace_id=None):
    p = os.path.join(cg.root, forgetting.LOG_FILE)
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if trace_id is None or r.get("trace_id") == trace_id:
                out.append(r)
    return out


# ---------------------------------------------------------------- A 组：MERGE 侧
def group_a():
    print("\n[A] MERGE 侧（knowledge 层近重复，role=user）：新正文去向")
    cg = _mk("merge")
    cg.session = "sess_merge"
    cg.add("k_base", SENT_A, layer="knowledge")
    n_before = len(cg.index["nodes"])
    fm_before = dict(cg.get("k_base")["frontmatter"])
    r = cg.remember_gated("k_second", SENT_B, layer="knowledge", role="user")

    _check("A1 近重复第二次写入仍判 MERGE（合并语义未变）",
           r.get("verdict") == "MERGE" and r.get("merged_into") == "k_base",
           repr(r.get("verdict")))
    _check("A2 新值在库中可检索（全库字面命中 = [目标节点]）",
           _lib_hits(cg, PORT_B) == ["k_base"], str(_lib_hits(cg, PORT_B)))
    rein = r.get("reinforced") or {}
    sink = rein.get("content_sink") or {}
    body = (cg.get("k_base") or {}).get("content") or ""
    _check("A3 聚合行落进目标正文（返回体给的 line 逐字在正文中）",
           bool(sink.get("line")) and sink["line"] in body,
           "line=%r" % (sink.get("line"),))
    # line_no 必须先做**有界**检查再索引：真实回归（正文回写成旧正文）下
    # line_no 指向旧正文之外，直接索引会抛 IndexError 裸崩——红项被截断、
    # 后续组整段不跑（守卫员独立变异实测）。有界检查把「越界」变成干净的 FAIL。
    _ln = int(sink.get("line_no") or 0)
    _lines = body.splitlines()
    _check("A4 返回体显式带去向（节点/行/行号，可定位）",
           sink.get("node_id") == "k_base" and sink.get("action") == "appended"
           and 1 <= _ln <= len(_lines)
           and sink["line"] == _lines[_ln - 1],
           json.dumps(sink, ensure_ascii=False)[:160])
    _check("A5 MERGE 既有语义未变（不新增节点 / importance+0.05 / merge_count+1）",
           len(cg.index["nodes"]) == n_before
           and abs(float(rein.get("importance") or 0)
                   - (float(fm_before.get("importance") or 0.5) + 0.05)) < 1e-9
           and int(rein.get("merge_count") or 0) == 1,
           json.dumps(rein, ensure_ascii=False)[:120])
    # 幂等：同文再写一次 → 零追加（正文长度不变、merge_count 仍 +1）
    len1 = len(body)
    r2 = cg.remember_gated("k_third", SENT_B, layer="knowledge", role="user")
    body2 = (cg.get("k_base") or {}).get("content") or ""
    _check("A6 聚合幂等：同文再写零追加（正文长度不变）",
           r2.get("verdict") == "MERGE" and len(body2) == len1,
           "%d -> %d" % (len1, len(body2)))
    # 缺省 content=None：与改动前逐位一致（既有调用零破坏）
    cg.add("k_plain", SENT_A, layer="knowledge")
    raw_before = (cg.get("k_plain") or {}).get("content")
    out = forgetting.reinforce(cg, "k_plain")
    raw_after = (cg.get("k_plain") or {}).get("content")
    _check("A7 reinforce 缺省 content=None：正文逐位不变（既有调用零破坏）",
           raw_after == raw_before and (out or {}).get("content_sink", {})
           .get("action") == "not_provided",
           "before=%r after=%r" % (raw_before[:40], raw_after[:40]))
    return cg


# ---------------------------------------------------------------- B 组：DROP 侧
def group_b():
    print("\n[B] DROP 侧（internal_deterministic ∧ dup≥0.60）：新正文去向")
    cg = _mk("drop")
    cg.session = "sess_drop"
    cg.add("d_base", SENT_A, layer="knowledge")
    imp0 = float(cg.get("d_base")["frontmatter"].get("importance") or 0)
    r = cg.remember_gated("d_second", SENT_B, layer="knowledge",
                          role="command")
    _check("B1 内部确定性来源仍判 DROP（:214 分支先于 MERGE，未被改成 MERGE）",
           r.get("verdict") == "DROP", repr(r.get("verdict")))
    fmd = cg.get("d_base")["frontmatter"]
    _check("B2 DROP 未强化目标（importance 不变 / 无 merge_count）",
           abs(float(fmd.get("importance") or 0) - imp0) < 1e-9
           and not fmd.get("merge_count"),
           "imp=%s mc=%s" % (fmd.get("importance"), fmd.get("merge_count")))
    drop = r.get("dropped") or {}
    _check("B3 返回体带去向单（trace_id / 留痕文件 / sha1 / 是否留全文）",
           bool(drop.get("trace_id")) and drop.get("kept_in") == forgetting.LOG_FILE
           and bool(drop.get("content_sha1")) and drop.get("content_kept") is True,
           json.dumps(drop, ensure_ascii=False)[:160])
    rows = _log_rows(cg, drop.get("trace_id"))
    _check("B4 去向留痕可检索：该 trace_id 行含新正文全文（含关键新值）",
           len(rows) == 1 and PORT_B in (rows[0].get("dropped_content") or "")
           and rows[0].get("duplicate_with") == "d_base",
           json.dumps(rows[:1], ensure_ascii=False)[:160])
    _check("B5 留痕带会话/主体归属（谁写的、从哪个目标旁落）",
           rows and rows[0].get("session") == "sess_drop"
           and bool(rows[0].get("actor")),
           json.dumps(rows[:1], ensure_ascii=False)[:120])
    # 加密级：明文不落留痕（与写面 fail-closed 同口径）
    cg2 = _mk("drop_sec")
    cg2.add("s_base", SENT_A, layer="knowledge")
    from .mdcos import MdCGSecure
    from .security import Principal
    sec = MdCGSecure(os.path.join(_SANDBOX, "lib_secure_r%d" % _RUN[0]),
                     principal=Principal(tenant="t1", actor="alice",
                                         role="designer", clearance="secret",
                                         can_write=True, can_admin=True),
                     master_key=os.urandom(32))
    sec.add("s_base", SENT_A, layer="knowledge")
    rs = sec.remember_gated("s_second", SENT_B, layer="knowledge",
                            role="command", sensitivity="private")
    drops = rs.get("dropped") or {}
    srows = _log_rows(sec, drops.get("trace_id"))
    raw_log = ""
    p = os.path.join(sec.root, forgetting.LOG_FILE)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            raw_log = f.read()
    _check("B6 加密级（private）DROP：明文不落留痕（只留摘要/长度）",
           rs.get("verdict") == "DROP" and drops.get("content_kept") is False
           and bool(drops.get("redacted_reason"))
           and PORT_B not in raw_log
           and srows and srows[0].get("content_chars"),
           "kept=%s raw_has_new=%s" % (drops.get("content_kept"),
                                       PORT_B in raw_log))
    return cg


# ---------------------------------------------------------------- C 组：H3
def group_c():
    print("\n[C] H3 跨会话合并：双方归属并列落 fm（不按会话切分合并判定）")
    cg = _mk("sess")
    cg.session = "sess_A"
    cg.add("c_a", SENT_A, layer="knowledge")
    fm0 = cg.get("c_a")["frontmatter"]
    cg.session = "sess_B"
    r = cg.remember_gated("c_b", SENT_B, layer="knowledge", role="user")
    fm1 = cg.get("c_a")["frontmatter"]
    _check("C1 跨会话近重复仍并入（合并判定不看会话，是既有设计）",
           r.get("verdict") == "MERGE" and r.get("merged_into") == "c_a",
           repr(r.get("verdict")))
    _check("C2 目标原归属保留 + 新写入方并列记入 fm.merge_sources",
           fm1.get("session") == fm0.get("session") == "sess_A"
           and [x.get("session") for x in (fm1.get("merge_sources") or [])]
           == ["sess_B"],
           json.dumps(fm1.get("merge_sources"), ensure_ascii=False))
    _check("C3 当前会话的新内容不消失（新值落库可检索）",
           PORT_B in ((cg.get("c_a") or {}).get("content") or ""),
           str(_lib_hits(cg, PORT_B)))
    # C4（2026-09-30 补强）：索引镜像不对称——reinforce 此前只把 importance /
    # lifecycle state / protected 同步进内存索引条目，**不镜像 merge_sources**，
    # 于是盘面 fm 已记新写入方而同进程 `cg.index[目标]` 读到 None（直到索引
    # 重载），与 converge_into 侧的镜像（writelimit.py:257）不同口径，也与
    # 「写盘后标脏、同进程读到新值」的 C-1/N133 既有纪律不一致。断言打在可
    # 观察结果（索引条目本身）上，不看在哪个函数里写了哪一行。
    idx_c = ((cg.index.get("nodes") or {}).get("c_a")) or {}
    _check("C4 索引条目同步镜像 merge_sources（同进程读 cg.index 即见新值）",
           [x.get("session") for x in (idx_c.get("merge_sources") or [])]
           == ["sess_B"],
           json.dumps(idx_c.get("merge_sources"), ensure_ascii=False))
    return cg


# ---------------------------------------------------------------- D 组：⑤ 哨兵
def group_d():
    print("\n[D] ⑤ 条件槽空值语义哨兵：不再无条件 condition_clash")
    # D1 逐字相同 + 哨兵 → ACCEPT（修前：DEFER + strength 1.0 + 建工单）
    cg = _mk("sent")
    cg.add("z_a", SENT_A, layer="knowledge")
    vd = consistency.check(cg, SENT_A, layer="knowledge", auto_flywheel=True)
    _check("D1 逐字相同 + 哨兵 → ACCEPT（无冲突 / 无工单）",
           vd.get("verdict") == "ACCEPT"
           and float(vd.get("conflict_strength") or 0) == 0.0
           and not vd.get("unresolved_id")
           and not (vd.get("conflicts") or []),
           "%s strength=%s unresolved=%s" % (vd.get("verdict"),
                                             vd.get("conflict_strength"),
                                             vd.get("unresolved_id")))
    # D2 真负条件对照：逐字相同仍 ACCEPT（与 D1 同口径，防「只在哨兵上放行」）
    cg2 = _mk("sent_real")
    cg2.add("z_a", REAL_A, layer="knowledge")
    vd2 = consistency.check(cg2, REAL_A, layer="knowledge", auto_flywheel=True)
    _check("D2 对照：真负条件 + 逐字相同 → ACCEPT（两例同口径）",
           vd2.get("verdict") == "ACCEPT",
           "%s strength=%s" % (vd2.get("verdict"),
                               vd2.get("conflict_strength")))
    # D3 真互斥防放宽：新负条件覆盖既有生效条件 → 仍判冲突（REJECT/DEFER）
    vd3 = consistency.check(
        cg2, REAL_A.replace("# 不适用条件：本地开发环境",
                            "# 不适用条件：载体/位置：prod 集群"),
        layer="knowledge", auto_flywheel=True)
    _check("D3 防放宽：真互斥（负条件覆盖既有生效条件）仍判冲突",
           vd3.get("verdict") in ("REJECT", "DEFER")
           and float(vd3.get("conflict_strength") or 0) >= consistency.CLASH_HIGH,
           "%s strength=%s" % (vd3.get("verdict"),
                               vd3.get("conflict_strength")))
    # D4 判据正反例
    pos_cases = ["无", "无。", "无.", "（无）", "(无)", "None", "", "   ",
                 "无依赖", "-", "—", None, "不适用"]
    neg_cases = ["无法确定", "无缓存场景", "无持久化介质", "问完全无关主题",
                 "本地开发环境"]
    _check("D4a 空值语义正例全部命中（无/无。/（无）/None/空串/无依赖…）",
           all(mdcos._is_null_condition(x) for x in pos_cases),
           str([x for x in pos_cases if not mdcos._is_null_condition(x)]))
    _check("D4b 真实条件反例全部不命中（不做语义猜测）",
           not any(mdcos._is_null_condition(x) for x in neg_cases),
           str([x for x in neg_cases if mdcos._is_null_condition(x)]))
    # D5 fm 列表形态同口径（mdcg.add :1898 会把 CCG 哨兵结构化进 fm）
    fm_list = {"non_applicable_conditions": ["无"]}
    _push_pos, _push_neg = mdcos._declared_conditions(fm_list, SENT_A)
    _check("D5 fm.non_applicable_conditions=[\"无\"] 同口径空值化（既有侧）",
           _push_neg == [], str(_push_neg))
    # D6 CCG 行形态：修点落在取值单点（consistency._new_terms 经 _prims 委托）
    _check("D6a _ccg_field 对条件字段空值化、对非条件字段不动（收口范围）",
           mdcos._ccg_field(SENT_A, "不适用条件") == ""
           and mdcos._ccg_field(SENT_A, "生效条件") != ""
           and mdcos._ccg_field("# 执行：无\n正文", "执行") == "无",
           "_ccg(不适用)=%r _ccg(执行)=%r" % (
               mdcos._ccg_field(SENT_A, "不适用条件"),
               mdcos._ccg_field("# 执行：无\n正文", "执行")))
    from .consistency import _new_terms
    _check("D6b 新节点侧（_new_terms）不再收哨兵（委托同一读点）",
           _new_terms(SENT_A, None, None)[1] == [],
           str(_new_terms(SENT_A, None, None)))
    # D7 入参列表形态同口径（mdcos.check_consistency 是 consistency.check 的唯一
    #    工具面/写链入口；mdcg.py:1785 的直连不在本席文件面内，见守卫头注）
    cg3 = _mk("sent_param")
    cg3.add("z_a", SENT_A, layer="knowledge")
    vd_sent = cg3.check_consistency(SENT_A, layer="knowledge",
                                    non_applicable_conditions=["无"])
    vd_none = cg3.check_consistency(SENT_A, layer="knowledge",
                                    non_applicable_conditions=None)
    _check("D7 入参哨兵列表与不传等价（上游收口，判据不落在阈值上）",
           vd_sent.get("verdict") == vd_none.get("verdict") == "ACCEPT"
           and float(vd_sent.get("conflict_strength") or 0) == 0.0,
           "%s/%s" % (vd_sent.get("verdict"), vd_none.get("verdict")))
    return cg3


# ---------------------------------------------------------------- F 组：CONVERGE
def group_f():
    print("\n[F] CONVERGE（contextual 同构聚合）：新值落在 80 字外也不丢")
    cg = _mk("conv")
    long_a = ("# 功能名：批次流水核对报告\n端口清单：" +
              "、".join("p%d" % i for i in range(1, 60)) +
              f"；尾值 {PORT_A}\n")
    # F5 前置：目标节点与第二个写入方**用不同会话**写（若同会话，merges_sources
    # 里的值与目标自身 fm.session 无从区分，断言就没有判别力了）。
    cg.session = "sess_conv_a"
    r1 = cg.remember_gated("cv_1", long_a, layer="contextual", role="user")
    cg.session = "sess_conv_b"
    r2 = cg.remember_gated("cv_2", long_a.replace(PORT_A, PORT_B),
                           layer="contextual", role="user")
    body = (cg.get("cv_1") or {}).get("content") or ""
    _check("F1 同构聚合仍判 CONVERGE→MERGE（既有语义未变）",
           r1.get("verdict") == "ACCEPT" and r2.get("verdict") == "MERGE"
           and r2.get("merged_into") == "cv_1",
           "%s/%s" % (r1.get("verdict"), r2.get("verdict")))
    _check("F2 新值（在 80 字外）落进目标正文（旧口径在此丢值）",
           PORT_B in body, "hits=%s" % _lib_hits(cg, PORT_B))
    _check("F3 聚合幂等：同文再写零追加",
           (lambda before: (cg.remember_gated("cv_3",
                                              long_a.replace(PORT_A, PORT_B),
                                              layer="contextual",
                                              role="user")
                            and len((cg.get("cv_1") or {}).get("content")
                                    or "") == before))(len(body)),
           "len=%d" % len(body))
    _check("F4 单点：converge_into 与 reinforce 共用同一聚合行实现",
           "forgetting.aggregate_line" in _src_of("writelimit.py")
           and "forgetting.aggregate_line" in _src_of("forgetting.py"),
           "两处实现点必须同源")
    # F5（2026-09-30 补强）：CONVERGE 落点的 session 接线。mdcos.py:3468 调用
    # converge_into 时传 `session=_writer_session(self, kw)`；复核员实测**抽掉
    # 该实参后本守卫全绿**——即该接线此前无覆盖。断言打在可观察结果（写盘 fm
    # 的归属字段）上：目标自身 fm.session 保持第一个写入方不动，第二个写入方
    # 的 session 并列落进 fm.merge_sources（单点 note_source 的产出）。
    fm_cv = (cg.get("cv_1") or {}).get("frontmatter") or {}
    srcs = [x.get("session") for x in (fm_cv.get("merge_sources") or [])]
    _check("F5 CONVERGE 落点：新写入方 session 并列落目标 fm.merge_sources"
           "（目标自身归属不动）",
           fm_cv.get("session") == "sess_conv_a" and srcs
           and set(srcs) == {"sess_conv_b"},
           "fm.session=%r merge_sources=%s" % (
               fm_cv.get("session"),
               json.dumps(fm_cv.get("merge_sources"), ensure_ascii=False)))
    return cg


def _src_of(name):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read().replace("\r\n", "\n")


# ---------------------------------------------------------------- 变异（自证）
def _pre_fix_aggregate_line(body, content, stamp=None):
    """改动前语义：新正文不进正文（返回 None = 只改 fm）。"""
    return None, None, None


def _pre_fix_record_drop(cg, content, node_id, **kw):
    """改动前语义：只记一行元数据日志，新正文零去向。"""
    forgetting.log(cg, {"t": time.time(), "node_id": node_id,
                        "layer": kw.get("layer"), "verdict": "DROP",
                        "reason": "确定性内部产生且冗余（低熵噪音，不编码）",
                        "actor": kw.get("actor")})
    return {}


def _pre_fix_null_condition(value):
    """改动前语义：无空值语义判据（哨兵原样当真实条件）。"""
    return False


def _pre_fix_conv_session():
    """改动前语义：CONVERGE 落点不往下传新写入方 session——等价于抽掉
    mdcos.py:3468 的 `session=_writer_session(self, kw)` 实参（复核员实测该
    实参可静默抽掉）。补丁只截断该实参，落库动作原样保留。"""
    _orig = writelimit.converge_into

    def patched(cg, target, content, override=False, actor=None,
                session=None, **kw):
        return _orig(cg, target, content, override=override, actor=actor,
                     session=None, **kw)

    writelimit.converge_into = patched


def _pre_fix_index_mirror():
    """改动前语义：reinforce 的内存索引条目不同步 merge_sources（盘面 fm 已记
    新写入方、同进程 `cg.index[目标]` 读到 None，直到索引重载）——等价于抽掉
    forgetting.py 索引更新段里的镜像两行。"""
    _orig = forgetting.reinforce

    def patched(cg, node_id, *a, **kw):
        out = _orig(cg, node_id, *a, **kw)
        e = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(node_id)
        if isinstance(e, dict):
            e.pop("merge_sources", None)
        return out

    forgetting.reinforce = patched


_MUTATIONS = {
    # 名称: (打补丁, 必须转红的断言名)
    "merge": (lambda: setattr(forgetting, "aggregate_line",
                              _pre_fix_aggregate_line),
              ["A2", "A3", "A4", "C3", "F2"]),
    "drop": (lambda: setattr(forgetting, "record_drop",
                             _pre_fix_record_drop),
             ["B3", "B4"]),
    "sentinel": (lambda: setattr(mdcos, "_is_null_condition",
                                 _pre_fix_null_condition),
                 ["D1", "D4a", "D5", "D6a", "D6b", "D7"]),
    # 2026-09-30 补强两处复核员实测的覆盖缺口
    "conv_session": (_pre_fix_conv_session, ["F5"]),
    "index": (_pre_fix_index_mirror, ["C4"]),
}
for _k, (_fn, _want) in _MUTATIONS.items():
    _MUTATIONS[_k] = (_fn, _want)


def _run_all():
    global _OK, _BAD
    _RUN[0] += 1
    _OK, _BAD = 0, []
    group_a()
    group_b()
    group_c()
    group_d()
    group_f()
    return _OK, list(_BAD)


def _snapshot_fix():
    return {"aggregate_line": forgetting.aggregate_line,
            "record_drop": forgetting.record_drop,
            "_is_null_condition": mdcos._is_null_condition,
            "converge_into": writelimit.converge_into,
            "reinforce": forgetting.reinforce}


def _restore_fix(snap):
    forgetting.aggregate_line = snap["aggregate_line"]
    forgetting.record_drop = snap["record_drop"]
    mdcos._is_null_condition = snap["_is_null_condition"]
    writelimit.converge_into = snap["converge_into"]
    forgetting.reinforce = snap["reinforce"]


def main(argv):
    which = None
    for a in argv:
        if a.startswith("--drop-fix"):
            which = a.split("=", 1)[1] if "=" in a else "all"
    if which is None:
        ok, bad = _run_all()
        print("\n==== B3/⑤ 守卫（MERGE 去向 + 哨兵）：%d 通过%s ====" % (
            ok, "，%d 失败：%s" % (len(bad), "; ".join(bad)) if bad else ""))
        return 1 if bad else 0
    names = list(_MUTATIONS) if which == "all" else [which]
    rc = 0
    print("\n=== 定点变异自证（抽掉修复 → 守卫必红 → 恢复 → 转绿）===")
    for name in names:
        if name not in _MUTATIONS:
            print("  未知变异 %r（可选：%s）" % (name, sorted(_MUTATIONS)))
            return 2
        patch, want = _MUTATIONS[name]
        snap = _snapshot_fix()
        patch()
        ok, bad = _run_all()
        hit = [n for n in want if any(b.split()[0] == n or
                                      b.startswith(n) for b in bad)]
        missed = [n for n in want if n not in hit]
        print("  [%s] 红项 %d 个：%s" % (name, len(bad), "; ".join(bad) or "（无）"))
        if missed or not bad:
            print("  FAIL 变异 %s 未打红预期断言：%s" % (name, missed or "全绿"))
            rc = 1
        else:
            print("  ok   变异 %s 打红预期断言 %d 项（判别力自证）"
                  % (name, len(hit)))
        _restore_fix(snap)
        ok2, bad2 = _run_all()
        if bad2:
            print("  FAIL 变异 %s 恢复后未转绿，残余红项：%s" % (name, bad2))
            rc = 1
        else:
            print("  ok   变异 %s 恢复后转绿（%d 通过，无残余）" % (name, ok2))
    return rc


if __name__ == "__main__":
    try:
        _rc = main(sys.argv[1:])
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(_rc)
