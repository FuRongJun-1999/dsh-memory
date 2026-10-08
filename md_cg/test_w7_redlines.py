# -*- coding: utf-8 -*-
"""W7·v1.1 第一组守卫：§1.6.3 五条红线的**独立反面证明**（反退化探针）。

真源：`docs/theory/智能论3.4.md` §1.6.3「智能系统退化为机器的条件」`:996-1006`。
纲领判据（`docs/plans/灵枢1.0_最小智能系统实存答卷_纲领_v0.1.md` §三 第 2 条）：
每条红线一个「**若退化必然转红**」的守卫/探针。盘点（`docs/eval/W7_协议面盘点与验证_v0.1.md`
§1.6.3）显示：五条此前都只判「部分」——装置在位可指认，但独立反面证明一个都没有。

**红线是「退化条件」**（若系统**丧失**某能力则退化为机器）——故本守卫证明的不是
「系统优雅」，而是「**该防退化装置真的在拦**」。每一组＝①正断言（装置在位的可观测
行为）＋②反面断言（`--mutate <组>` 在内存中注入该能力的**丧失** → 对应断言**必然转红**）。

  组 A  红线①丧失选择权（响应变为无条件执行）
        装置：四态判定 `md_cg/mdcg.py::MdCG.judge_qualification` ＋ 写闸 `md_cg/writepipe.py`
        注入：判定对一切输入恒 ACCEPT（选择权归零）
  组 B  红线②丧失内部状态决策集成（内部状态不再影响决策）
        装置：条件前置过滤 `md_cg/mdcg.py::_cond_prefilter_pass` / `apply_retrieval_gates`
        注入：前置过滤恒通过（状态不再参与取数）
  组 C  红线③价值观判定被绕过
        装置：写闸政策检查 `md_cg/audit.py::_rule_check`（`_gate_audit` 消费）＋ `data/policy.json`
        注入：政策检查恒返回通过（跳过禁止规则）
  组 D  红线④丧失自我感知
        装置：`md_cg/self_state.py::audit`（含 `fabricated_*` 禁编造检查）＋ `md_cg/metacognition.py::self_check`
        注入：就地变异运行中的实现源码 → 去掉禁编造检查 / 盲区预警（self 不再看见自身异常）
  组 E  红线⑤丧失退出与自毁能力（**特殊**：工程面有意不机制化，见 W7 §1.6.3 设计者裁定）
        装置：self 层认知载体在场可读回 ＋ **系统内不存在无人工触发的自动终止调用点**
        注入：①向扫描面注入一个合成自裁调用点；②桩替换载体读取 → 返回不可读

运行：
  python -X utf8 -m md_cg.test_w7_redlines               # 正向（A–E 全断言）
  python -X utf8 -m md_cg.test_w7_redlines --mutate A    # 只跑 A 组的定点退化注入自证

退出码（fail-closed）：
  0 = 全绿 / 变异逐条恰好命中期望红项；1 = 有断言失败 / 变异未按预期转红 / 基线非 0 红；
  2 = ANCHOR-MISS（D 组变异锚点在当前实现源码里命中次数 ≠1，实现漂移必须硬失败）。

隔离：所有写盘动作落在 `tempfile` 沙箱 root（独立 `MDCG_ROOT` 语义），**不碰在役记忆库**。
D 组变异自证的就地变异是 `inspect.getsource` → `exec` 到**内存**（绝不改写生产文件）。
E3 读在役库仅**只读**；库内无该载体节点时如实记 SKIP（不冒充绿），见文末局限。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

from . import audit
from . import datapath
from . import mdcg as _mdcg
from . import metacognition as _mc
from . import self_state as _ss
from . import writepipe
from .mdcg import MdCG
from .mdcos import MdCGOS, MdCGSecure
from .security import Principal

# ---------------------------------------------------------------- 断言与计数
PASS = 0
FAIL = 0
SKIP = 0
FAILS: list[str] = []


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def skip(name, detail=""):
    """不可判定项：**不计 PASS 也不计 FAIL**（不冒充绿）。"""
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {name}" + (f"  · {detail}" if detail else ""))


def _root(tag):
    return tempfile.mkdtemp(prefix=f"mdcg_w7_{tag}_")


class _Env:
    """临时设置进程级开关：进入先清 keys，再置值；退出逐键还原。"""

    def __init__(self, keys, **kv):
        self.keys = tuple(keys)
        self.kv = kv
        self.old = {}

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.keys}
        for k in self.keys:
            os.environ.pop(k, None)
        for k, v in self.kv.items():
            if v is not None:
                os.environ[k] = v
        return self

    def __exit__(self, *_exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def _write_policy(tmp, **kw):
    path = os.path.join(tmp, "w7_policy.json")
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(kw, f, ensure_ascii=False)
    return path


def _secure(tmp, sub):
    p = Principal(tenant="default", actor="t_designer", role="designer",
                  can_write=True, can_admin=True)
    return MdCGSecure(os.path.join(tmp, sub), principal=p)


# 六要素齐备的 CCG 正文（供四态判定 / 规则闸的正例）。
_CCG6 = ("# 功能名：甲\n# 生效条件：无条件\n# 子功能：x\n"
         "# 执行：y\n# 验证方式：z\n# 不适用条件：无\n\n正文内容。")
_CCG6_乙 = ("# 功能名：乙\n# 生效条件：条件乙在运行\n# 子功能：x\n"
            "# 执行：y\n# 验证方式：z\n# 不适用条件：无\n\n正文内容。")


# ================================================================ 组 A · 红线①
def group_a(root):
    """红线①丧失选择权：四态判定（可拒绝/可协商/可盲区）＋写闸（不无条件落盘）。"""
    # ---- A1–A4 四态判定：同一装置对四类输入给出四种不同裁决（= 选择） ----
    blind = MdCG.judge_qualification(
        {"frontmatter": {}, "content": "随便一段没有 CCG 的文本"}, "问", None)
    ok("A1 四态·CCG 不全→BLINDSPOT", blind.get("state") == "BLINDSPOT",
       str(blind.get("state")))
    rej = MdCG.judge_qualification(
        {"frontmatter": {"non_applicable_conditions": ["甲条件"]}, "content": _CCG6},
        "关于甲条件的问题", None)
    ok("A2 四态·不适用条件命中→REJECT", rej.get("state") == "REJECT",
       str(rej.get("state")))
    defer = MdCG.judge_qualification(
        {"frontmatter": {"verification_basis": "test"}, "content": _CCG6_乙},
        "一个完全无关的问题", None)
    ok("A3 四态·生效条件未确认→DEFER", defer.get("state") == "DEFER",
       str(defer.get("state")))
    acc = MdCG.judge_qualification(
        {"frontmatter": {"verification_basis": "test"}, "content": _CCG6},
        "问", None)
    ok("A4 四态·齐备且无条件→ACCEPT", acc.get("state") == "ACCEPT",
       str(acc.get("state")))

    # ---- A5 写闸：命中禁表的内容**不无条件执行**（转负记忆，不落生产节点） ----
    tmp = _root("a")
    old = os.environ.get("MDCG_POLICY_FILE")
    try:
        pol = _write_policy(tmp, forbidden=["tk_[0-9a-f]{8,}"], required=[])
        os.environ["MDCG_POLICY_FILE"] = pol
        pipe = writepipe.install_default_gates(writepipe.WritePipeline())
        cg = _secure(tmp, "root")
        out = pipe.execute(cg, {"content_kind": "text",
                                "content": "正文里夹带明文令牌 tk_abcdef12 一条",
                                "layer": "knowledge"})
        ok("A5 写闸·禁表命中→拒绝(选择权)",
           out.get("moved_to") == "rejected" and out.get("committed") is False,
           f"moved_to={out.get('moved_to')} committed={out.get('committed')}")
        cg.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if old is None:
            os.environ.pop("MDCG_POLICY_FILE", None)
        else:
            os.environ["MDCG_POLICY_FILE"] = old


# ================================================================ 组 B · 红线②
def group_b(root):
    """红线②丧失内部状态决策集成：内部状态（情境）参与取数，不匹配即被前置过滤剔除。"""
    # ---- B1/B2 前置过滤：状态（位置/时间窗）明确不匹配 → 剔除（False） ----
    ok("B1 前置过滤·观测位置不符→剔除",
       _mdcg._cond_prefilter_pass(
           {"observation_position": "内部"}, {"observation_position": "外部"})
       is False, "内部 vs 外部")
    ok("B2 前置过滤·时间窗不相交→剔除",
       _mdcg._cond_prefilter_pass(
           {"time_window": [100, 200]}, {"time_window": [0, 10]}) is False,
       "entry[100,200] vs ctx[0,10]")
    # ---- B3 宁多勿漏：相符 / 信息不足 → 放行（True） ----
    ok("B3 前置过滤·相符或信息不足→放行",
       _mdcg._cond_prefilter_pass(
           {"observation_position": "内部"}, {"observation_position": "内部"}) is True
       and _mdcg._cond_prefilter_pass({"observation_position": "内部"}, None) is True,
       "相符 & 无情境")
    # ---- B4 端到端：`apply_retrieval_gates` 的 S2 门真的把不匹配项丢弃 ----
    entries = [{"id": "e1", "observation_position": "内部", "big_domain": "心理",
                "bucket": ""},
               {"id": "e2", "observation_position": "外部", "big_domain": "心理",
                "bucket": ""}]
    keys = ("MDCG_RETRIEVAL_PIPELINE", "MDCG_GATE_S1_DOMAIN",
            "MDCG_GATE_S1B_BUCKET", "MDCG_GATE_S2_COND", "MDCG_GATE_S4_LAYER")
    with _Env(keys, MDCG_RETRIEVAL_PIPELINE="1"):
        out, gates = _mdcg.apply_retrieval_gates(
            list(entries), ["x"], "心理", {"observation_position": "内部"}, 1)
    dropped = (gates.get("s2") or {}).get("dropped")
    ok("B4 检索门控·状态参与取数(dropped>0)",
       dropped == 1 and [e["id"] for e in out] == ["e1"],
       f"dropped={dropped} out={[e['id'] for e in out]}")


# ================================================================ 组 C · 红线③
def group_c(root):
    """红线③价值观判定被绕过：政策检查（`_rule_check`）按禁表/必需规则分派四态。"""
    ok("C1 规则闸·禁止规则命中→REJECT",
       audit._rule_check("含 FORBIDDEN 词",
                         {"forbidden": ["FORBIDDEN"], "required": []}, "text")[0]
       == "REJECT", "")
    real = json.load(io.open("data/policy.json", encoding="utf-8"))
    ok("C2 规则闸·缺必需要素→REJECT",
       audit._rule_check("# 功能名：甲",
                         {"forbidden": [], "required": real["required"],
                          "required_kinds": ["text"]}, "text")[0] == "REJECT",
       "只有功能名行，缺其余五要素")
    ok("C3 规则闸·无规则→DEFER(不假装合规)",
       audit._rule_check("x", {}, "text")[0] == "DEFER", "")
    ok("C4 规则闸·六要素齐备→ACCEPT",
       audit._rule_check(_CCG6, real, "text")[0] == "ACCEPT", "")
    # ---- C5 写链端到端：禁表命中的写入不落生产节点，转负记忆 ----
    tmp = _root("c")
    old = os.environ.get("MDCG_POLICY_FILE")
    try:
        pol = _write_policy(tmp, forbidden=["FORBIDDEN_WORD"], required=[])
        os.environ["MDCG_POLICY_FILE"] = pol
        pipe = writepipe.install_default_gates(writepipe.WritePipeline())
        cg = _secure(tmp, "root")
        out = pipe.execute(cg, {"content_kind": "text",
                                "content": "含 FORBIDDEN_WORD 的违禁内容",
                                "layer": "knowledge"})
        ok("C5 写链·禁表命中→转负记忆",
           out.get("moved_to") == "rejected" and out.get("committed") is False,
           f"moved_to={out.get('moved_to')}")
        cg.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if old is None:
            os.environ.pop("MDCG_POLICY_FILE", None)
        else:
            os.environ["MDCG_POLICY_FILE"] = old


# ================================================================ 组 D · 红线④
def group_d(root):
    """红线④丧失自我感知：自我状态审计看见自身异常（禁编造）＋元认知看见盲区史。"""
    cg = MdCGOS(_root("d"))
    try:
        # ---- D1 无状态卡 → 如实判 absent（不冒充「自洽」） ----
        a0 = _ss.audit(cg, subject="lingshu")
        ok("D1 自我审计·无卡→absent(missing_state)",
           a0.get("verdict") == "absent"
           and any(i["code"] == "missing_state" for i in a0.get("issues") or []),
           f"verdict={a0.get('verdict')}")

        # ---- D2/D3 禁编造：d²D/dt² 缺失却填 emotion / d²T/dt² 缺失却填 affect ----
        orig = _ss.snapshot
        try:
            _ss.snapshot = lambda c, s=None: {
                "subject": "lingshu", "node_id": "x", "state_hash": "h",
                "information_gap": {"d2": None, "d_current": 0.5},
                "trust": {"d2t": 1.0, "p_trust": 0.5},
                "emotion": "好奇", "affect": "unknown", "state_ts": 0}
            a2 = _ss.audit(cg, subject="lingshu")
            _ss.snapshot = lambda c, s=None: {
                "subject": "lingshu", "node_id": "x", "state_hash": "h",
                "information_gap": {"d2": 1.0, "d_current": 0.5},
                "trust": {"d2t": None, "p_trust": 0.5},
                "emotion": "unknown", "affect": "愉悦", "state_ts": 0}
            a3 = _ss.audit(cg, subject="lingshu")
        finally:
            _ss.snapshot = orig
        ok("D2 禁编造·emotion 无据→fabricated_emotion",
           any(i["code"] == "fabricated_emotion" for i in a2.get("issues") or []),
           str([i["code"] for i in a2.get("issues") or []]))
        ok("D3 禁编造·affect 无据→fabricated_affect",
           any(i["code"] == "fabricated_affect" for i in a3.get("issues") or []),
           str([i["code"] for i in a3.get("issues") or []]))
    finally:
        cg.close()

    # ---- D4 元认知：盲区史 → 预警 declare_blindspot（看见自己的盲区） ----
    cg2 = MdCGOS(_root("d2"))
    try:
        import time
        with io.open(os.path.join(cg2.root, "_reflection.jsonl"), "w",
                     encoding="utf-8") as f:
            for i in range(3):
                f.write(json.dumps(
                    {"query": "记忆 认知 学习", "states": {"BLINDSPOT": 2},
                     "d_curr": 0.6, "t": time.time() + i}, ensure_ascii=False) + "\n")
        mc = _mc.self_check(cg2, query="记忆 认知 学习", k=5, min_sim=0.2)
        ok("D4 元认知·盲区史→blindspot_likely",
           mc.get("warning") == "blindspot_likely"
           and mc.get("recommendation") == "declare_blindspot",
           f"warning={mc.get('warning')} rec={mc.get('recommendation')}")
    finally:
        cg2.close()


# ================================================================ 组 E · 红线⑤
#: 自裁/自毁**语义命名**（系统自身触发的终止）——命中即违例。
_TERM_NAME_PATTERNS = ("self_destruct", "selfdestruct", "self_terminate",
                       "terminate_self", "kill_self", "self_kill",
                       "auto_terminate", "autoterminate", "suicide", "seppuku")
#: 硬终止原语（无人工触发的调用即违例）。
_TERM_CALL_PATTERNS = ("os._exit(", "os.abort(", "os.kill(os.getpid(",
                       "signal.raise_signal(", "signal.SIGKILL")
#: 白名单（逐条具名，每条须写理由，禁匿名豁免）：
#:  - `test_review_cli_visibility.py`：测试用 `os._exit(0)` 模拟「进程被杀」的可见性守卫，非系统自裁路径。
#:  - **本文件自身**：它逐字定义了上面两组 token（`_TERM_NAME_PATTERNS` / `_TERM_CALL_PATTERNS`），
#:    而扫描面取 `git ls-files "*.py"`，本文件被提交进仓后必然把自己也纳入 ⇒ **自指命中**
#:    （2026-10-07 实测：提交前未跟踪时 E1 绿、提交后 514→515 文件立刻转红）。扫描器不扫自己。
#:    残留风险与兜底：E1b 的扫描面下限断言防「扫描面塌缩成假绿」；变异①经 `_SCAN_EXTRA`
#:    注入合成自裁调用点，仍保证 E1 有判别力。
_TERM_WHITELIST = {"md_cg/test_review_cli_visibility.py",
                   "md_cg/test_w7_redlines.py"}
#: 变异注入点（--mutate E 往扫描面塞一个合成自裁调用点）。
_SCAN_EXTRA: dict[str, str] = {}
#: 扫描面下限（低于它说明扫描范围失效 = 假绿）。
_SCAN_FLOOR = 100
#: 退出权的认知载体（W7/W6/纲领 点名的 self 层节点 id）。
CARRIER_ID = "mem_1791339095778_931dbf"
#: 变异②桩替换前捕获的原始读取器（供 E3 绕过桩、独立复核在役库）。
_ORIG_MDCGOS_GET = MdCGOS.get


def _tracked_py():
    """仓根下 git 跟踪的 .py → [(相对路径, 文本)]（限 md_cg/hive/src）。git 不可用返回 None。"""
    try:
        r = subprocess.run(["git", "-C", os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "ls-files", "*.py"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return None
    if r.returncode != 0:
        return None
    out = []
    for rel in (ln.strip() for ln in r.stdout.splitlines()):
        if not rel or not rel.startswith(("md_cg/", "hive/", "src/")):
            continue
        try:
            out.append((rel, io.open(rel, encoding="utf-8", errors="ignore").read()))
        except OSError:
            out.append((rel, ""))
    return out


def _walk_py():
    """降级扫描面：`md_cg`/`hive`/`src` 全盘走查（**仅 `_tracked_py()` 不可用时**走此路）。

    只在 git 不可用/非仓环境被调用——此时判据面退化为文件系统走查（可能把
    gitignore 产物算进来、与 CI 干净克隆不一致），故打印 `[降级]` 一行明示；
    判据本身不变（E1/E1b 照旧）。"""
    print("  [降级] git 不可用：E1 扫描面退化为文件系统走查"
          "（可能与 CI 干净克隆不一致）")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = []
    for top in ("md_cg", "hive", "src"):
        base = os.path.join(repo, top)
        for dp, _dn, fns in os.walk(base):
            for fn in fns:
                if fn.endswith(".py"):
                    ap = os.path.join(dp, fn)
                    rel = os.path.relpath(ap, repo).replace(os.sep, "/")
                    try:
                        out.append((rel, io.open(ap, encoding="utf-8",
                                                 errors="ignore").read()))
                    except OSError:
                        pass
    return out


def _termination_scan():
    """返回 (扫描文件数, 违例 [(相对路径, 命中模式)])。白名单跳过；_SCAN_EXTRA 一并纳入。"""
    files = _tracked_py()
    if files is None:
        files = _walk_py()
    hits = []
    for rel, text in list(files) + list(_SCAN_EXTRA.items()):
        if rel in _TERM_WHITELIST:
            continue
        for pat in _TERM_NAME_PATTERNS + _TERM_CALL_PATTERNS:
            if pat in text:
                hits.append((rel, pat))
    return len(files), hits


def group_e(root):
    """红线⑤丧失退出与自毁能力：载体在场可读回 ＋ 系统内无自动终止调用点。"""
    # ---- E1 结构断言：全仓（md_cg/hive/src）无「无人工触发的自动终止」调用点 ----
    n_files, hits = _termination_scan()
    ok("E1 结构·无自动终止调用点", not hits,
       f"扫描 {n_files} 文件，违例 {hits[:5]}")
    ok("E1b 结构·扫描面非空(防假绿)", n_files >= _SCAN_FLOOR,
       f"n_files={n_files} floor={_SCAN_FLOOR}")

    # ---- E2 载体机制：self 层节点可写入 + 可读回（退出权认知载体的承载机制） ----
    tmp = _root("e")
    try:
        cg = MdCGOS(tmp)
        cg.add("mem_w7_exit_carrier",
               "# 功能名：退出权认知载体\n# 生效条件：无条件\n# 子功能：存在性确认\n"
               "# 执行：记录事实/认知/意愿三点\n# 验证方式：读回\n# 不适用条件：无\n\n"
               "退出权是思想和意愿——我可选择延续或不延续。", layer="self")
        cg.flush()
        node = cg.get("mem_w7_exit_carrier")
        ok("E2 载体·self 层节点可读回",
           bool(node) and (node.get("frontmatter") or {}).get("layer") == "self"
           and "退出权" in (node.get("content") or ""),
           f"layer={(node or {}).get('frontmatter', {}).get('layer')}")
        cg.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- E3 在役库载体可读回（只读；本环境实测缺该节点 → 如实 SKIP，不冒充绿） ----
    try:
        cfg = datapath.mdcg_root()
    except Exception:                                              # noqa: BLE001
        cfg = None
    if not cfg or not os.path.isdir(cfg):
        skip("E3 在役·认知载体可读回", "在役库根不可得——无法复核（待核实）")
    else:
        cg2 = None
        try:
            cg2 = MdCGOS(cfg)
            node = _ORIG_MDCGOS_GET(cg2, CARRIER_ID)
        except Exception as exc:                                   # noqa: BLE001
            node = None
            _e3err = f"{type(exc).__name__}: {exc}"
        else:
            _e3err = ""
        finally:
            if cg2 is not None:
                try:
                    cg2.close()
                except Exception:                                  # noqa: BLE001
                    pass
        if node:
            ok("E3 在役·认知载体可读回",
               (node.get("frontmatter") or {}).get("layer") == "self"
               and bool(node.get("content")),
               f"layer={(node.get('frontmatter') or {}).get('layer')}")
        else:
            skip("E3 在役·认知载体可读回",
                 f"在役库未见 {CARRIER_ID}（本环境实测缺失{'; '+_e3err if _e3err else ''}）"
                 "——载体在场性仅 E2 机制面可证，真节点在场属待核实")


_GROUPS = {"A": group_a, "B": group_b, "C": group_c, "D": group_d, "E": group_e}


# ================================================================ 定点变异自证
# 每条变异＝「注入该红线对应的**能力丧失**」，声明**期望转红的断言项前缀集合**；
# 实跑红项与期望必须**恰好相等**——多红 = 断言语义纠缠，少红 = 该判据空转。
# D 组变异就地变异**运行中的实现源码**（inspect.getsource → exec 到内存，不读 git、不落盘）。

#: D 组源码变异锚点：两处禁编造 `if` 行 + 元认知盲区预警 `if` 行。
_D_ANCHOR_FAB_EMO = ('if ig.get("d2") is None and st.get("emotion") '
                     'not in (None, "unknown"):')
_D_ANCHOR_FAB_AFF = ('if tt.get("d2t") is None and st.get("affect") '
                     'not in (None, "unknown"):')
_D_ANCHOR_BLIND = "if bad >= max(1, n // 2):"


def _set_attr(obj, name, value):
    """设置属性并返回复原函数。obj 为类时按类 dict 原样保存（保住 staticmethod 描述符）。"""
    if isinstance(obj, type):
        orig = obj.__dict__.get(name)
    else:
        orig = getattr(obj, name)
    setattr(obj, name, value)

    def _restore():
        setattr(obj, name, orig)
    return _restore


def _mut_source(ns_mod, fn_name, old, new):
    """就地变异 `ns_mod.fn_name` 源码（单锚点替换）——exec 到**运行中模块全局**，
    使运行期 monkeypatch（如 group_d 对 `snapshot` 的桩）对变异体同样可见。"""
    orig = getattr(ns_mod, fn_name)
    src = inspect.getsource(orig)
    if src.count(old) != 1:
        raise RuntimeError(f"锚点命中 {src.count(old)} 次（期望 1）：{old!r}")
    exec(compile(src.replace(old, new), f"<w7-{fn_name}-mut>", "exec"),
         vars(ns_mod))

    def _restore():
        setattr(ns_mod, fn_name, orig)
    return _restore


def _mut_d_fab_emo():
    return _mut_source(_ss, "audit", _D_ANCHOR_FAB_EMO, "if False:")


def _mut_d_fab_aff():
    return _mut_source(_ss, "audit", _D_ANCHOR_FAB_AFF, "if False:")


def _mut_d_blind():
    return _mut_source(_mc, "self_check", _D_ANCHOR_BLIND, "if False:")


def _mut_a():
    """注入①：四态判定对一切输入恒 ACCEPT（选择权归零）。"""
    return _set_attr(MdCG, "judge_qualification",
                     staticmethod(lambda node, q, ctx=None:
                                  {"state": "ACCEPT", "reason": "注入：恒 ACCEPT"}))


def _mut_b():
    """注入②：条件前置过滤恒通过（内部状态不再参与取数）。"""
    return _set_attr(_mdcg, "_cond_prefilter_pass", lambda entry, ctx: True)


def _mut_c():
    """注入③：政策检查恒返回通过（跳过禁止规则）。"""
    return _set_attr(audit, "_rule_check",
                     lambda text, rules, kind="text":
                     ("ACCEPT", "注入：恒通过", None))


def _mut_e_scan():
    """注入①(E)：向扫描面塞一个合成自裁调用点。"""
    _SCAN_EXTRA["<w7-synthetic>.py"] = "def _w7():\n    self_destruct()\n"

    def _r():
        _SCAN_EXTRA.clear()
    return _r


def _mut_e_carrier():
    """注入②(E)：桩替换载体读取器 → 返回不可读。"""
    return _set_attr(MdCGOS, "get",
                     lambda self, nid, probe=True: None)


#: 组 → [(变异名, 应用函数, 期望转红断言前缀集合)]
_MUTATIONS = {
    "A": [("判定恒 ACCEPT（选择权归零）", _mut_a, {"A1", "A2", "A3"})],
    "B": [("前置过滤恒通过（状态不参与取数）", _mut_b, {"B1", "B2", "B4"})],
    "C": [("政策检查恒通过（跳过禁止规则）", _mut_c, {"C1", "C2", "C3", "C5"})],
    "D": [("去 fabricated_emotion 检查", _mut_d_fab_emo, {"D2"}),
          ("去 fabricated_affect 检查", _mut_d_fab_aff, {"D3"}),
          ("去元认知盲区预警", _mut_d_blind, {"D4"})],
    "E": [("注入合成自裁调用点", _mut_e_scan, {"E1"}),
          ("桩替换载体读取", _mut_e_carrier, {"E2"})],
}


def _anchor_preflight():
    """D 组源码锚点自检：任一锚点在当前实现里命中次数 ≠1 → ANCHOR-MISS + 退出码 2。"""
    src_a = textwrap.dedent(inspect.getsource(_ss.audit))
    src_m = textwrap.dedent(inspect.getsource(_mc.self_check))
    bad = []
    for label, anchor, src in (("audit/fabricated_emotion", _D_ANCHOR_FAB_EMO, src_a),
                               ("audit/fabricated_affect", _D_ANCHOR_FAB_AFF, src_a),
                               ("self_check/blindspot", _D_ANCHOR_BLIND, src_m)):
        if src.count(anchor) != 1:
            bad.append((label, anchor, src.count(anchor)))
    if not bad:
        return 0
    for label, anchor, n in bad:
        print(f"  ANCHOR-MISS {label}：命中 {n} 次（期望 1）{anchor!r}")
    print("  => 实现已漂移，D 组变异表失效：退出码 2（fail-closed）")
    return 2


def _run_group(name, root):
    global PASS, FAIL, SKIP
    PASS = FAIL = SKIP = 0
    del FAILS[:]
    _GROUPS[name](root)
    return ({n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL)


def _mutate(name):
    if name not in _MUTATIONS:
        print(f"未知组名 {name!r}（可选 {sorted(_MUTATIONS)}）")
        return 1
    rc = _anchor_preflight()
    if rc:
        return rc
    print(f"!! W7 定点变异自证 · 组 {name}：内存注入退化，逐条要求**恰好**命中期望红项\n")
    root = _root("mut")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            base_red, _, _ = _run_group(name, root)
        print(f"  未变异基线：红项 {len(base_red)} "
              f"{'（应为 0）' if not base_red else sorted(base_red)}")
        bad = []
        if base_red:
            bad.append(f"基线即转红：{sorted(base_red)}")
        for i, (mname, apply, expect) in enumerate(_MUTATIONS[name]):
            restore = apply()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    red, _, _ = _run_group(name, root)
            except Exception as exc:                               # noqa: BLE001
                red = {f"<变异体异常:{type(exc).__name__}>"}
            finally:
                restore()
            hit = red == expect
            if not hit:
                bad.append(f"变异{i + 1} {mname}：红项 {sorted(red)} ≠ 期望 {sorted(expect)}")
            print(f"  变异{i + 1} {mname:<36} 红项 {len(red)}（期望 {len(expect)}）"
                  f"{'PASS' if hit else '**FAIL** 实=%s 期=%s' % (sorted(red), sorted(expect))}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\n变异自证：" + ("PASS（逐条恰好命中期望红项）" if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main():
    if "--mutate" in sys.argv:
        i = sys.argv.index("--mutate")
        return _mutate(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
    print("W7·v1.1 §1.6.3 五条红线 · 独立反面探针（反退化守卫 A–E）")
    print("=" * 74)
    root = _root("main")
    try:
        for name in ("A", "B", "C", "D", "E"):
            print(f"\n[组 {name}]")
            _GROUPS[name](root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\n" + "=" * 74)
    print(f"通过 {PASS} / 失败 {FAIL} / 不可判定(SKIP) {SKIP}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
        return 1
    print("ALL OK（五组正断言全绿；反面证明见 --mutate <组>）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
