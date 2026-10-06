# -*- coding: utf-8 -*-
"""md_cg · P6 验收：离线固化（反思单元 → 白箱闸门 → 验证单元 → 固化）

运行：python -X utf8 -m md_cg.test_p6_consolidate                     # 正常跑（含 R 组）
      python -X utf8 -m md_cg.test_p6_consolidate --mutation-baseline # R 组定点变异自证

验证口径（对齐工作纪律第 3/5 条「不猜测、未经验证不固化」）：
  1. 候选解析：JSON 容错 + 字段别名（子内容→子功能）
  2. grounding：幻觉候选被拦截（正文无据即 REJECT）
  3. replay：正例召回 / 负例分离 / 无冲突；负条件自否定正文 → 拒绝
  4. 验证单元裁决：**只能否决、不能新增**；全否 → REJECT
  5. 角色配置：反思=DeepSeek、验证=GLM，且凭证不跨厂商挪用
  6. 全链路：dry-run 不写盘；apply 写盘；四要素 + 验证方式落盘；provenance 可审计
  7. 索引一致性：新增 `# 不适用条件：`/`# 验证方式：` 后索引同步
  8. 幂等 + 不覆盖人工既有字段
  9. 验证单元不可用 → DEFER（不写盘）；--no-verify 降级可跑通
 10. 验证方式补全（零 LLM）+ 与生产 _path_semantic 的一致性回归
 11. （R 组）issue #64 修复守卫：replay_check 撤销「负条件一票否决」、consolidate
     主流程「负条件两态拦截」（neg_absent / neg_dropped_all）、CLI 两角色
     max-tokens/timeout 单设——附定点变异自证（`--mutation-baseline`）。
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

from . import consolidate as _consolidate_mod
from . import nodefile
from .consolidate import (BASIS_TEMPLATE, REFLECT_ROLE, VERIFY_ROLE, _cli,
                          body_text, consolidate, existing_fields,
                          fill_verification_basis, grounding_filter,
                          grounding_score, narrow_by_verdict, parse_candidate,
                          parse_verdict, replay_check, role_config)
from .mdcg import expand_query_terms_weighted
from .mdcos import MdCGOS, _neg_hit, _weighted_coverage

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


# 待补节点：只有功能名 + 正文，四要素全缺
BODY = ("# 功能名：微分方程应用\n"
        "微分方程应用：建模与求解，使用数值方法迭代求解，需给定边界条件\n")

# 反思单元候选：三条有据 + 一条域外负条件（与正文共享「边界条件」但整体域外）
CAND = {
    "生效条件": ["微分方程", "数值方法"],
    "子功能": ["建模", "求解"],
    "执行": "使用数值方法迭代求解",
    "不适用条件": ["边界条件缺失"],
}
CAND_JSON = json.dumps(CAND, ensure_ascii=False)
REFLECT_MODEL = "deepseek-flash"   # 与 ROLE_DEFAULT_MODEL 同步（v0.5 §1；限时旧 id 已下架）
VERIFY_MODEL = "glm-5.3-flash"
BASIS = BASIS_TEMPLATE.format(reflect=REFLECT_MODEL, verify=VERIFY_MODEL)


def fake_reflect(prompt):
    """反思单元：带代码围栏，检验解析容错。"""
    return "```json\n" + CAND_JSON + "\n```"


def make_verify(drop=(), keep=None, extra=None):
    """构造验证单元：默认全部放行；可指定删除/收窄/额外字段。"""
    def _fn(prompt):
        out = {}
        for f, v in CAND.items():
            terms = v if isinstance(v, list) else [v]
            if keep is not None and f in keep:
                out[f] = {"keep": list(keep[f]), "drop": [],
                          "reason": "收窄"}
            else:
                out[f] = {"keep": [t for t in terms if t not in drop],
                          "drop": [t for t in terms if t in drop],
                          "reason": "逐条核验"}
        if extra:
            out.update(extra)
        return json.dumps(out, ensure_ascii=False)
    return _fn


fake_verify = make_verify()


def new_root(n=1):
    root = tempfile.mkdtemp(prefix="mdcg_p6_")
    cg = MdCGOS(root)
    for i in range(n):
        cg.add(f"n{i + 1}", BODY, tags=["数学"])
    cg.flush()
    rel = {f"n{i + 1}": cg.get(f"n{i + 1}")["path"] for i in range(n)}
    cg.close()
    return root, rel


# ==========================================================================
# R 组：issue #64 修复守卫（2026-10-06）
# ==========================================================================
#
# 缺陷（外部报告 angel12538 对 v0.7.5 实测；编排侧隔离库独立复现）：
#   A 类① `consolidate.replay_check` 的 pos_recall 带 `and not _neg_hit(tw_pos, neg_terms)`
#         ——「生效条件任一词整词出现在不适用条件里」一票判负。而负条件描述的是
#         **邻近易混情境**，与生效条件共享领域主题词是结构必然（不共享主题词就
#         谈不上「邻近」）⇒ 合格负条件被大量误杀。自否定职责已由 no_conflict
#         （覆盖率口径，<0.5 才算互相覆盖）承担——两者同意图而前者更严。
#   B 类   `consolidate` 主流程把 grounding 删光后的空 neg 交给 replay_check，命中其
#         `else: neg_separated = True` 短路 ⇒「负条件被删光/未产出」被翻译成「通过」
#         ⇒ 缺「不适用条件」要素的节点落盘并携带 verification_basis 声明。
#
# 定点变异自证（`python -X utf8 -m md_cg.test_p6_consolidate --mutation-baseline`，
# 与 test_neg_condition_hits 同口径）：每一处修复判据都必须有变异把它打红，且
# **红项数恰好等于** _MUTATIONS 登记的预期数（多红说明断言串扰、少红说明该判据
# 无判别力——两种都判 FAIL）。变异锚点为**本文件内联的源码文本**，不读 git HEAD
# （基线绑提交即失效，本仓已有两次教训）。锚点漂移（实现改了而本表未同步）→
# 报 ANCHOR-MISS，退出码 2（fail-closed）——守卫静默失效比守卫失败更危险。
# R6 走 subprocess 跑**盘上模块**的 `--help`，内存态变异打不到它，故不登记变异腿；
# 其判别力由「四个参数名逐一断言」承担（删任一参数即红）。

# R1/R2 样本（A 类①）：读数经编排侧探针独立标定——
#   ② 负条件对正文覆盖率 = 0.402、③ 生效条件对负条件文本覆盖率 = 0.37（均 < 0.5，
#   未触发），① 一票否决为唯一杀手；撤销前 replay_check 判 {pos_recall: False, ok: False}。
R_POS = ["海边甜品店 招牌蛋糕 做法"]
R_NEG = ["海边甜品店 的其它蛋糕 冷藏流程"]
R_BODY = "海边甜品店招牌蛋糕做法：奶油打发后低温烘焙，成品当日冷藏保存。"

# R2 自否定样本：生效条件与不适用条件整条互相覆盖 → no_conflict 必须拦住
R_POS2 = ["海边甜品店 招牌蛋糕"]
R_NEG2 = ["海边甜品店 招牌蛋糕"]

# R3/R4 打桩候选：负条件域外（与正文零 bigram 支撑 → grounding 全删）
R_CAND_DROP = {
    "生效条件": ["微分方程", "数值方法"],
    "子功能": ["建模", "求解"],
    "执行": "使用数值方法迭代求解",
    "不适用条件": ["量子色动力学格点规范场论"],
}
R_CAND_ABSENT = {k: v for k, v in R_CAND_DROP.items() if k != "不适用条件"}


def _legacy_pos_recall(pos_terms, neg_terms, body):
    """A 类① 撤销**前**的 pos_recall 原文（issue #64 前）——仅用于「样本确实踩中
    旧缺陷」的红基线自证，不参与生产：生产判据单点在 consolidate.replay_check。"""
    pos_text = " ".join(pos_terms or [])
    tw_pos = expand_query_terms_weighted(pos_text) if pos_text else {}
    return bool(pos_text) and _weighted_coverage(tw_pos, body) > 0.0 \
        and not _neg_hit(tw_pos, neg_terms)


def _const_reflect(cand):
    """打桩反思单元：恒返回同一候选（隔离「负条件两态」这一变量）。"""
    return lambda prompt: json.dumps(cand, ensure_ascii=False)


class _HttpSpy:
    """打桩 http_llm：记录两角色**实收**的 (max_tokens, timeout) 并返回可解析输出。

    用于 R6 的透传行为面：CLI 参数是否真被喂到 reflect/verify 两侧（而不只是
    出现在 --help 文本里）。
    """

    def __init__(self, cand):
        self.calls = []
        self.cand = cand

    def __call__(self, prompt, model=None, base=None, key=None, role=None,
                 timeout=120, max_tokens=None):
        self.calls.append({"role": role, "max_tokens": max_tokens,
                           "timeout": timeout})
        if role == VERIFY_ROLE:
            return "{}"
        return json.dumps(self.cand, ensure_ascii=False)


def _swap_http_llm(fake):
    """把 http_llm 换成打桩替身，返回还原函数。

    同时覆盖两个全局面：模块面，以及**当前 _cli**（可能是内存变异版）的
    __globals__——变异版的命名空间是 exec 快照，只 patch 模块属性它看不到，
    会漏到真网络调用。
    """
    holders = [vars(_consolidate_mod)]
    g = getattr(globals().get("_cli"), "__globals__", None)
    if isinstance(g, dict) and g is not vars(_consolidate_mod):
        holders.append(g)
    saved = [(h, h.get("http_llm")) for h in holders]
    for h in holders:
        h["http_llm"] = fake

    def restore():
        for h, old in saved:
            h["http_llm"] = old
    return restore


def _r_run(verbose=True):
    """跑 R1-R6，返回失败项名单。verbose=False 时静默（变异自证复用，不污染全局计数）。"""
    fails = []

    def ck(name, cond, detail=""):
        if not cond:
            fails.append(name)
        if verbose:
            check(name, cond, detail)

    def sec(title):
        if verbose:
            print(title)

    # ---- R1 撤销负条件一票否决（A 类①复现样本）----
    sec("\n== R1 撤销负条件一票否决（A 类①复现样本）==")
    r1 = replay_check(R_POS, R_NEG, R_BODY)
    ck("R1a 复现样本 pos_recall=True（恢复一票否决因子即转 False）",
       r1.get("pos_recall") is True, str(r1))
    ck("R1b 复现样本 ok=True（②=0.402 / ③=0.37 均未触发，①原为唯一杀手）",
       r1.get("ok") is True, str(r1))
    ck("R1c 红基线可复现：同一输入在撤销前的 pos_recall 原文下判负（样本有效性）",
       _legacy_pos_recall(R_POS, R_NEG, R_BODY) is False)

    # ---- R2 自否定职责由 no_conflict 承担（③兜底不退化）----
    sec("\n== R2 自否定由 no_conflict 承担（撤销①不得放宽自否定）==")
    r2 = replay_check(R_POS2, R_NEG2, R_BODY)
    ck("R2a 生效条件整条覆盖不适用条件 → no_conflict=False",
       r2.get("no_conflict") is False, str(r2))
    ck("R2b 自否定样本 ok=False（撤销①不等于放过自否定）",
       r2.get("ok") is False, str(r2))
    ck("R2c 自否定样本 pos_recall 仍成立（召回不再被负条件一票否决，由③兜底）",
       r2.get("pos_recall") is True, str(r2))

    # ---- R3 态1：负条件被 grounding 删光 → 全链 REJECT ----
    sec("\n== R3 态1（neg_dropped_all）：负条件被 grounding 删光 → 全链 REJECT ==")
    root, rel = new_root(1)
    try:
        p = os.path.join(root, rel["n1"])
        before = open(p, encoding="utf-8").read()
        rep = consolidate(root, apply=True, reflect_fn=_const_reflect(R_CAND_DROP),
                          verify_fn=lambda prompt: "{}", require_verify=True)
        fm, content = nodefile.loads(open(p, encoding="utf-8").read())
        ck("R3a 删光态 → rejected=1（修复前 accepted=1 直接落盘）",
           rep["rejected"] == 1, str(rep["reasons"]))
        ck("R3b reasons 记 neg_dropped_all=1",
           rep["reasons"].get("neg_dropped_all") == 1, str(rep["reasons"]))
        ck("R3c 不写盘（written=0 且盘上内容逐字未变）",
           rep["written"] == 0 and open(p, encoding="utf-8").read() == before,
           "written=%s" % rep["written"])
        ck("R3d 盘上节点无 llm_consolidation 键（未携带 grounding/replay 声明落盘）",
           "llm_consolidation" not in fm, str(sorted(fm)))
        smp = (rep["samples"] or [{}])[0]
        ck("R3e samples 带 reason=neg_dropped_all 且 replay=None（可观测面）",
           smp.get("reason") == "neg_dropped_all" and smp.get("replay") is None,
           str(smp))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---- R4 态2：候选未产出负条件 → 全链 REJECT ----
    sec("\n== R4 态2（neg_absent）：候选无「不适用条件」键 → 全链 REJECT ==")
    root, rel = new_root(1)
    try:
        p = os.path.join(root, rel["n1"])
        before = open(p, encoding="utf-8").read()
        rep = consolidate(root, apply=True, reflect_fn=_const_reflect(R_CAND_ABSENT),
                          verify_fn=lambda prompt: "{}", require_verify=True)
        fm, content = nodefile.loads(open(p, encoding="utf-8").read())
        ck("R4a 未产出态 → rejected=1（修复前 accepted=1 直接落盘）",
           rep["rejected"] == 1, str(rep["reasons"]))
        ck("R4b reasons 记 neg_absent=1",
           rep["reasons"].get("neg_absent") == 1, str(rep["reasons"]))
        ck("R4c 不写盘（written=0 且盘上内容逐字未变）",
           rep["written"] == 0 and open(p, encoding="utf-8").read() == before,
           "written=%s" % rep["written"])
        ck("R4d 盘上节点无 llm_consolidation 键",
           "llm_consolidation" not in fm, str(sorted(fm)))
        smp = (rep["samples"] or [{}])[0]
        ck("R4e samples 带 reason=neg_absent 且 replay=None（可观测面）",
           smp.get("reason") == "neg_absent" and smp.get("replay") is None, str(smp))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---- R5 不误伤：合法候选（含域外负条件）照常 ACCEPT ----
    sec("\n== R5 不误伤：合法候选全链照常 ACCEPT ==")
    root, rel = new_root(1)
    try:
        p = os.path.join(root, rel["n1"])
        rep = consolidate(root, apply=True, reflect_fn=fake_reflect,
                          verify_fn=fake_verify, reflect_model=REFLECT_MODEL,
                          verify_model=VERIFY_MODEL, verification_basis=BASIS)
        fm, content = nodefile.loads(open(p, encoding="utf-8").read())
        ck("R5a 合法候选 → accepted=1 / written=1",
           rep["accepted"] == 1 and rep["written"] == 1, str(rep["reasons"]))
        ck("R5b 合法候选 replay.ok=True（两态拦截不误伤合格负条件）",
           ((fm.get("llm_consolidation") or {}).get("replay") or {}).get("ok") is True,
           str((fm.get("llm_consolidation") or {}).get("replay")))
        ck("R5c 负条件照常落盘（正文含「# 不适用条件」行）", "# 不适用条件" in content)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---- R6 CLI：两角色 max-tokens/timeout 可分别单设 ----
    sec("\n== R6 CLI：--reflect/--verify-max-tokens、--reflect/--verify-timeout ==")
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "md_cg.consolidate", "--help"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=repo_root, env=env)
    flat = (proc.stdout or "") + (proc.stderr or "")
    ck("R6a `python -m md_cg.consolidate --help` 退出码 0",
       proc.returncode == 0, "rc=%s :: %s" % (proc.returncode, flat[:120]))
    for flag in ("--reflect-max-tokens", "--verify-max-tokens",
                 "--reflect-timeout", "--verify-timeout"):
        ck("R6 帮助含参数 %s" % flag, flag in flat)

    # 透传行为面（打桩 http_llm 记录两角色实收参数）：单设优先、缺省回落共用值
    spy = _HttpSpy(CAND)
    restore_http = _swap_http_llm(spy)
    saved_keys = {k: os.environ.get(k)
                  for k in ("MDCG_REFLECT_KEY", "MDCG_VERIFY_KEY")}
    root, rel = new_root(1)
    try:
        os.environ["MDCG_REFLECT_KEY"] = "k-reflect"
        os.environ["MDCG_VERIFY_KEY"] = "k-verify"
        with contextlib.redirect_stdout(io.StringIO()):
            _cli(["--root", root, "--max-tokens", "5000", "--timeout", "7",
                  "--reflect-max-tokens", "7000", "--reflect-timeout", "3",
                  "--verify-max-tokens", "6000", "--verify-timeout", "9"])
        by_role = {c["role"]: c for c in spy.calls}
        ck("R6b 反思单元实收单设预算/超时（--reflect-max-tokens=7000 / --reflect-timeout=3）",
           by_role.get(REFLECT_ROLE, {}).get("max_tokens") == 7000
           and by_role.get(REFLECT_ROLE, {}).get("timeout") == 3.0, str(spy.calls))
        ck("R6c 验证单元实收单设预算/超时（--verify-max-tokens=6000 / --verify-timeout=9）",
           by_role.get(VERIFY_ROLE, {}).get("max_tokens") == 6000
           and by_role.get(VERIFY_ROLE, {}).get("timeout") == 9.0, str(spy.calls))
        spy.calls.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            _cli(["--root", root, "--max-tokens", "5000", "--timeout", "7"])
        fell = {c["role"]: c for c in spy.calls}
        ck("R6d 角色级参数缺省回落共用缺省（两角色都实收 5000 / 7.0）",
           fell.get(REFLECT_ROLE, {}).get("max_tokens") == 5000
           and fell.get(REFLECT_ROLE, {}).get("timeout") == 7.0
           and fell.get(VERIFY_ROLE, {}).get("max_tokens") == 5000
           and fell.get(VERIFY_ROLE, {}).get("timeout") == 7.0, str(spy.calls))
    finally:
        restore_http()
        for k, v in saved_keys.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(root, ignore_errors=True)

    return fails


# 定点变异表：逐处把本轮修复的判据改坏/改回，R 组必须转红且**红项数恰好等于**
# 登记值（多红 = 断言串扰、少红 = 判据无判别力，两者都判 FAIL）。锚点 = 源码文本
# （内联基线，不读 git HEAD）；锚点缺失/不唯一 → ANCHOR-MISS → 退出码 2。
# 预期红项数 = 实跑登记（2026-10-06 首跑，R 组子项名）：
#   ① → R1a、R1b、R2c（3 项：撤销判据的直接面）
#   ②a → R4b、R4e（2 项：neg_absent 专属计数与可观测面）
#   ②b → R3a、R3b、R3c、R3d、R3e（5 项：neg_dropped_all 全链不落盘）
#   ②ab（两态全删）→ R3 五项 + R4 五项（10 项：两态各自失守）
#   ③a → R6b（1 项：反思侧透传面）
#   ③b → R6c（1 项：验证侧透传面）
# 登记值是**锁**：实测多红（断言串扰）或少红（判据无判别力）都判 FAIL。
_MUTATIONS = (
    ("① 恢复负条件一票否决（replay_check.pos_recall）", "replay_check", (
        ("pos_recall = bool(pos_text) and _weighted_coverage(tw_pos, body) > 0.0",
         "pos_recall = bool(pos_text) and _weighted_coverage(tw_pos, body) > 0.0 \\\n"
         "        and not _neg_hit(tw_pos, neg_terms)"),
    ), 3),
    ("②a neg_absent 两态拦截失效（consolidate）", "consolidate", (
        ("if not neg_cand:", "if False:"),
    ), 2),
    ("②b neg_dropped_all 两态拦截失效（consolidate）", "consolidate", (
        ("if not neg:", "if False:"),
    ), 5),
    ("②ab 两态拦截整体删除（consolidate）", "consolidate", (
        ("if not neg_cand:", "if False:"),
        ("if not neg:", "if False:"),
    ), 10),
    ("③a 反思单元未透传单设预算/超时（_cli 回落共用值）", "_cli", (
        ("max_tokens=refl_mt, timeout=refl_to",
         "max_tokens=a.max_tokens, timeout=a.timeout"),
    ), 1),
    ("③b 验证单元未透传单设预算/超时（_cli 回落共用值）", "_cli", (
        ("max_tokens=ver_mt, timeout=ver_to",
         "max_tokens=a.max_tokens, timeout=a.timeout"),
    ), 1),
)


def _anchor_report():
    """检查所有变异锚点在实现源码中是否**唯一**存在；返回问题描述清单（空 = 全在）。

    锚点漂移（实现改了而本表未同步）意味着变异腿空转 ⇒ 守卫判别力静默失效，
    故调用方以退出码 2 fail-closed。
    """
    bad = []
    for name, fn_name, pairs, _expect in _MUTATIONS:
        src = inspect.getsource(getattr(_consolidate_mod, fn_name))
        for old, _new in pairs:
            n = src.count(old)
            if n != 1:
                bad.append("%s :: 锚点出现 %d 次（应为 1）:: %r"
                           % (name, n, old[:60]))
    return bad


def _mutate(fn_name, pairs):
    """把 fn_name 的源码按 pairs 替换后 exec 出新函数（只在内存里，不落任何文件）。"""
    mod = _consolidate_mod
    src = inspect.getsource(getattr(mod, fn_name))
    for old, new in pairs:
        src = src.replace(old, new, 1)
    ns = dict(vars(mod))
    exec(compile(src, "<mut_%s>" % fn_name, "exec"), ns)
    return ns[fn_name]


def _mutation_baseline() -> int:
    """定点变异自证：逐处变异本轮修复的判据，R 组必须转红且红项数恰等于登记值。"""
    print("!! 定点变异自证：逐处变异本轮修复的判据，R 组应当转红"
          "（红项数须恰好等于登记值）\n")
    with contextlib.redirect_stdout(io.StringIO()):
        base = _r_run(verbose=False)
    print("  未变异基线：红项=%d%s" % (len(base), ("（须为 0）" + "、".join(base)) if base else "（须为 0）"))
    bad = []
    if base:
        bad.append("未变异基线即红")
    for name, fn_name, pairs, expect in _MUTATIONS:
        old_live = globals()[fn_name]
        globals()[fn_name] = _mutate(fn_name, pairs)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                fails = _r_run(verbose=False)
        finally:
            globals()[fn_name] = old_live
        if len(fails) == expect:
            verdict = "一致（有判别力）"
        elif not fails:
            verdict = "**仍全绿 = 该判据无判别力**"
        else:
            verdict = "**红项数不符（实测 %d ≠ 登记 %d）**" % (len(fails), expect)
        print("  变异「%s」→ 红项=%d（登记 %d）%s：%s"
              % (name, len(fails), expect, verdict, "、".join(fails)))
        if len(fails) != expect:
            bad.append(name)
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都有变异把它打红）" if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main():
    # ANCHOR-MISS 预检（fail-closed）：变异锚点是 R 组判别力的底座——实现漂移而
    # 基线表未同步时守卫会静默失效；故先检锚点，漂移即以退出码 2 失败，不静默。
    miss = _anchor_report()
    if miss:
        print("ANCHOR-MISS：守卫变异锚点在实现源码中缺失或不唯一"
              "（实现已漂移，本守卫基线表未同步）——fail-closed，退出码 2：")
        for m in miss:
            print("  · " + m)
        return 2
    if "--mutation-baseline" in sys.argv:
        return _mutation_baseline()

    # ---------------- 1. 候选解析 ----------------
    print("\n【1】候选解析（JSON 容错 + 字段别名）")
    c = parse_candidate("```json\n" + CAND_JSON + "\n```")
    check("解析带围栏的 JSON", c.get("生效条件") == ["微分方程", "数值方法"], str(c.get("生效条件")))
    c2 = parse_candidate('前置说明 {"子内容": ["甲","乙"], "如何执行": "先做甲", '
                         '"适用条件": ["丙"], "不适用条件": ["丁"]} 后置说明')
    check("别名：子内容→子功能", c2.get("子功能") == ["甲", "乙"], str(c2.get("子功能")))
    check("别名：如何执行→执行", c2.get("执行") == "先做甲", str(c2.get("执行")))
    check("别名：适用条件→生效条件", c2.get("生效条件") == ["丙"], str(c2.get("生效条件")))
    check("垃圾输入 → 空字典", parse_candidate("这不是 JSON") == {})
    check("超长候选被丢弃", parse_candidate('{"执行": "' + "长" * 60 + '"}') == {})

    # ---------------- 2. grounding：幻觉拦截 ----------------
    print("\n【2】grounding 支撑度（正文无据即幻觉）")
    check("有据短语支撑度 = 1.0", grounding_score("微分方程", BODY) == 1.0,
          str(grounding_score("微分方程", BODY)))
    check("幻觉短语支撑度 = 0.0", grounding_score("拉普拉斯变换", BODY) == 0.0,
          str(grounding_score("拉普拉斯变换", BODY)))
    kept, gdet = grounding_filter(
        {"生效条件": ["微分方程", "拉普拉斯变换"], "执行": "使用数值方法迭代求解"}, BODY)
    check("grounding 丢弃幻觉、保留有据",
          kept.get("生效条件") == ["微分方程"] and "拉普拉斯变换" not in str(kept),
          str(kept.get("生效条件")))
    check("grounding 明细可审计", gdet["生效条件"]["scores"]["拉普拉斯变换"] == 0.0,
          str(gdet["生效条件"]["scores"]))
    check("无据字段整体被丢弃",
          "执行" not in grounding_filter({"执行": "完全无关的编造内容"}, BODY)[0])
    check("body_text 剥离 CCG 声明行（声明不是正文）",
          body_text("# 功能名：甲\n# 不适用条件：乙\n丙丁\n") == "丙丁\n",
          repr(body_text("# 功能名：甲\n# 不适用条件：乙\n丙丁\n")))

    # ---------------- 3. replay：条件稳定性 ----------------
    print("\n【3】replay 回放（正例召回 + 负例分离 + 无冲突）")
    ok = replay_check(["微分方程", "数值方法"], ["边界条件缺失"], BODY)
    check("合法候选 → replay 通过", ok["ok"] is True, str(ok))
    check("  正例召回成立", ok["pos_recall"] is True)
    check("  负例分离成立", ok["neg_separated"] is True)
    bad_neg = replay_check(["建模"], ["使用数值方法迭代求解"], BODY)
    check("负条件与正文强相关 → 拒绝", bad_neg["neg_separated"] is False, str(bad_neg))
    conflict = replay_check(["微分方程"], ["微分方程"], BODY)
    check("生效/不适用互相覆盖 → 拒绝", conflict["no_conflict"] is False, str(conflict))

    # ---------------- 4. 验证单元：只能否决 ----------------
    print("\n【4】验证单元裁决（只能否决、不能新增）")
    v = parse_verdict(json.dumps({"生效条件": {"keep": ["微分方程"], "drop": ["数值方法"],
                                               "reason": "无据"}, "子功能": ["建模"]},
                                 ensure_ascii=False))
    check("裁决解析：dict 形态", v["生效条件"]["keep"] == ["微分方程"]
          and v["生效条件"]["drop"] == ["数值方法"], str(v["生效条件"]))
    check("裁决解析：数组形态 = 全 keep", v["子功能"]["keep"] == ["建模"]
          and v["子功能"]["has_keep"] is True, str(v["子功能"]))
    check("裁决解析：垃圾输入 → 空", parse_verdict("nope") == {})

    n_kept, n_drop = narrow_by_verdict(
        {"生效条件": ["A", "B", "C"], "子功能": ["X"], "执行": "E"},
        {"生效条件": {"keep": ["A", "Z"], "drop": ["B"], "has_keep": True,
                      "reason": "r"}})
    check("keep 取交集（无法新增 Z）", n_kept["生效条件"] == ["A"], str(n_kept))
    check("drop 生效", "B" in n_drop["生效条件"]["terms"], str(n_drop))
    check("未表态字段保留（沉默≠否决）", n_kept.get("子功能") == ["X"]
          and n_kept.get("执行") == "E")
    only_drop, _ = narrow_by_verdict(
        {"生效条件": ["A", "B"]},
        {"生效条件": {"drop": ["B"], "has_keep": False, "reason": ""}})
    check("只给 drop 时不误删", only_drop["生效条件"] == ["A"], str(only_drop))
    all_no, _ = narrow_by_verdict(
        {"生效条件": ["A"]},
        {"生效条件": {"keep": [], "has_keep": True, "reason": "全否"}})
    check("显式空 keep → 全部否决", all_no == {}, str(all_no))
    check("验证单元凭空新增的条目不会落地",
          "凭空新增" not in str(narrow_by_verdict(
              {"子功能": ["建模"]},
              {"子功能": {"keep": ["建模", "凭空新增"], "has_keep": True}})[0]))

    # ---------------- 5. 角色配置 ----------------
    print("\n【5】角色配置（反思=DeepSeek / 验证=GLM，凭证不跨厂商）")
    saved = {k: os.environ.pop(k, None) for k in (
        "MDCG_LLM_KEY", "MDCG_LLM_MODEL", "MDCG_LLM_BASE", "MDCG_REFLECT_MODEL",
        "MDCG_REFLECT_BASE", "MDCG_REFLECT_KEY", "MDCG_VERIFY_MODEL",
        "MDCG_VERIFY_BASE", "MDCG_VERIFY_KEY", "ZHIPU_API_KEY", "ZHIPUAI_API_KEY",
        "GLM_API_KEY", "BIGMODEL_API_KEY", "DEEPSEEK_API_KEY")}
    try:
        os.environ["DEEPSEEK_API_KEY"] = "sk-fake-deepseek"
        check("反思单元默认模型", role_config(REFLECT_ROLE)[0] == REFLECT_MODEL,
              role_config(REFLECT_ROLE)[0])
        check("验证单元默认模型", role_config(VERIFY_ROLE)[0] == VERIFY_MODEL,
              role_config(VERIFY_ROLE)[0])
        check("反思单元可用 DeepSeek 凭证",
              role_config(REFLECT_ROLE)[2] == "sk-fake-deepseek")
        check("验证单元**不**挪用 DeepSeek 凭证",
              role_config(VERIFY_ROLE)[2] is None, str(role_config(VERIFY_ROLE)[2]))
        check("验证单元默认网关为智谱",
              "bigmodel" in role_config(VERIFY_ROLE)[1], role_config(VERIFY_ROLE)[1])
        os.environ["ZHIPU_API_KEY"] = "sk-fake-glm"
        check("验证单元识别 ZHIPU_API_KEY 别名",
              role_config(VERIFY_ROLE)[2] == "sk-fake-glm")
        os.environ["MDCG_REFLECT_MODEL"] = "deepseek-v4-pro"
        check("环境变量可覆盖默认模型",
              role_config(REFLECT_ROLE)[0] == "deepseek-v4-pro")
    finally:
        for k, val in saved.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val

    # ---------------- 6. 全链路 ----------------
    print("\n【6】全链路（dry-run 不写盘 → apply 写盘）")
    root, rel = new_root(1)
    try:
        node_path = os.path.join(root, rel["n1"])
        with open(node_path, encoding="utf-8") as f:
            before = f.read()
        check("初始节点四要素全缺", len(existing_fields(*nodefile.loads(before))) == 0)

        rep = consolidate(root, reflect_fn=fake_reflect, verify_fn=fake_verify,
                          reflect_model=REFLECT_MODEL, verify_model=VERIFY_MODEL,
                          verification_basis=BASIS)
        check("dry-run 判定 ACCEPT", rep["accepted"] == 1, str(rep["accepted"]))
        check("dry-run 不写盘", rep["written"] == 0
              and open(node_path, encoding="utf-8").read() == before)
        check("报告记录双模型",
              rep["reflect"] and rep["verify"]
              and rep["reflect_model"] == REFLECT_MODEL
              and rep["verify_model"] == VERIFY_MODEL, str(rep["reflect_model"]))

        rep2 = consolidate(root, apply=True, reflect_fn=fake_reflect,
                           verify_fn=fake_verify, reflect_model=REFLECT_MODEL,
                           verify_model=VERIFY_MODEL, verification_basis=BASIS)
        check("apply 写盘 1 个节点", rep2["written"] == 1, str(rep2["written"]))
        fm, content = nodefile.loads(open(node_path, encoding="utf-8").read())
        cm = (fm.get("state_attributes") or {}).get("comment") or {}
        check("生效条件落盘", cm.get("生效条件") == "微分方程；数值方法", str(cm.get("生效条件")))
        check("子功能落盘", cm.get("子功能") == "建模；求解", str(cm.get("子功能")))
        check("执行落盘", cm.get("执行") == "使用数值方法迭代求解", str(cm.get("执行")))
        check("不适用条件落盘", cm.get("不适用条件") == "边界条件缺失", str(cm.get("不适用条件")))
        check("正文写入 CCG 行", all(f"# {f}：" in content for f in
                                ("生效条件", "子功能", "执行", "不适用条件")))
        check("验证方式落盘", cm.get("验证方式") == BASIS, str(cm.get("验证方式")))
        check("验证方式写入正文", f"# 验证方式：{BASIS}" in content)
        check("frontmatter 枚举落到 other", fm.get("verification_basis") == "other",
              str(fm.get("verification_basis")))
        check("frontmatter.non_applicable_conditions 同步",
              fm.get("non_applicable_conditions") == ["边界条件缺失"],
              str(fm.get("non_applicable_conditions")))
        prov = fm.get("llm_consolidation") or {}
        check("provenance 记录双模型与哈希",
              prov.get("reflect", {}).get("model") == REFLECT_MODEL
              and prov.get("verify", {}).get("model") == VERIFY_MODEL
              and bool(prov.get("source_hash"))
              and bool(prov.get("reflect", {}).get("prompt_hash"))
              and bool(prov.get("verify", {}).get("prompt_hash")),
              str({k: prov.get(k, {}).get("model") for k in ("reflect", "verify")}))
        check("provenance 不含正文载荷（只存哈希）",
              "微分方程应用：建模" not in json.dumps(prov, ensure_ascii=False))
        check("CCG 完整度提升（含验证方式）",
              nodefile.ccg_completeness(content)["complete"] is True,
              str(nodefile.ccg_completeness(content)["required_present"]))

        # ---------------- 7. 索引一致性 ----------------
        print("\n【7】索引一致性（正文变更后重建）")
        cg2 = MdCGOS(root)
        e = cg2.index["nodes"].get("n1") or {}
        check("has_neg_conditions 已同步", e.get("has_neg_conditions") is True,
              str(e.get("has_neg_conditions")))
        check("content_hash 已更新", e.get("content_hash") != "", str(e.get("content_hash")))
        cg2.close()

        # ---------------- 8. 幂等 + 不覆盖 ----------------
        print("\n【8】幂等与「不覆盖人工既有字段」")
        rep3 = consolidate(root, apply=True, reflect_fn=fake_reflect,
                           verify_fn=fake_verify, verification_basis=BASIS)
        check("二次运行幂等（无新增）",
              rep3["accepted"] == 0 and rep3["skipped_complete"] >= 1,
              f"accepted={rep3['accepted']} skipped={rep3['skipped_complete']}")

        fm, content = nodefile.loads(open(node_path, encoding="utf-8").read())
        cm = fm["state_attributes"]["comment"]
        cm["执行"] = "人工写的执行方式"
        cm.pop("子功能", None)
        content = "\n".join(l for l in content.split("\n")
                            if not l.strip().startswith("# 执行")
                            and not l.strip().startswith("# 子功能"))
        with open(node_path, "w", encoding="utf-8") as f:
            f.write(nodefile.dumps(fm, content))
        rep_m = consolidate(root, apply=True, reflect_fn=fake_reflect,
                            verify_fn=fake_verify, verification_basis=BASIS)
        check("已写入的声明行不干扰 replay（回归）",
              rep_m["accepted"] == 1, str(rep_m["reasons"]))
        fm2, _ = nodefile.loads(open(node_path, encoding="utf-8").read())
        cm2 = fm2["state_attributes"]["comment"]
        check("人工字段不被覆盖", cm2.get("执行") == "人工写的执行方式", str(cm2.get("执行")))
        check("缺失字段被补齐", cm2.get("子功能") == "建模；求解", str(cm2.get("子功能")))

        # ---------------- 9. 一致性回归 ----------------
        print("\n【9】一致性回归：固化结果驱动生产 _path_semantic")
        cg3 = MdCGOS(root)
        cands = cg3._candidates()
        sem = {n["id"]: s for n, s in cg3._path_semantic("微分方程", cands)}
        sem_neg = {n["id"] for n, _ in cg3._path_semantic("边界条件缺失", cands)}
        check("正例：生效条件 → 生产路召回本节点", "n1" in sem, str(sem))
        check("负例：不适用条件 → 生产路条件级剔除", "n1" not in sem_neg, str(sem_neg))
        rrf = cg3.search_rrf("微分方程")
        check("默认四路 RRF 仍可用（未受影响）",
              isinstance(rrf, tuple) and len(rrf) == 2, str(type(rrf)))
        cg3.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---------------- 10. 验证单元不可用 → DEFER ----------------
    print("\n【10】验证单元不可用 → DEFER（纪律 5：未经验证不固化）")
    root, rel = new_root(1)
    try:
        node_path = os.path.join(root, rel["n1"])
        before = open(node_path, encoding="utf-8").read()
        rep = consolidate(root, apply=True, reflect_fn=fake_reflect,
                          reflect_model=REFLECT_MODEL, require_verify=True)
        check("无验证单元 → 全部 DEFER",
              rep["deferred"] == 1 and rep["accepted"] == 0, str(rep["reasons"]))
        check("DEFER 原因为 verify_unavailable",
              "verify_unavailable" in rep["reasons"], str(rep["reasons"]))
        check("DEFER 不写盘", open(node_path, encoding="utf-8").read() == before)
        rep2 = consolidate(root, apply=True, reflect_fn=fake_reflect,
                           require_verify=False)
        check("--no-verify 降级可跑通", rep2["accepted"] == 1 and rep2["written"] == 1,
              str(rep2["reasons"]))
        fm3, _ = nodefile.loads(open(node_path, encoding="utf-8").read())
        check("provenance 标记验证单元 skipped",
              fm3["llm_consolidation"]["verify"].get("status") == "skipped",
              str(fm3["llm_consolidation"]["verify"]))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---------------- 11. 验证单元全否 → REJECT ----------------
    print("\n【11】验证单元否决全部候选 → REJECT")
    root, rel = new_root(1)
    try:
        node_path = os.path.join(root, rel["n1"])
        before = open(node_path, encoding="utf-8").read()
        rep = consolidate(root, apply=True, reflect_fn=fake_reflect,
                          verify_fn=make_verify(drop=(
                              "微分方程", "数值方法", "建模", "求解",
                              "使用数值方法迭代求解", "边界条件缺失")))
        check("全否 → REJECT", rep["rejected"] == 1 and rep["accepted"] == 0,
              str(rep["reasons"]))
        check("REJECT 原因为 verify_rejected",
              "verify_rejected" in rep["reasons"], str(rep["reasons"]))
        check("REJECT 不写盘", open(node_path, encoding="utf-8").read() == before)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---------------- 12. 验证方式补全（零 LLM） ----------------
    print("\n【12】验证方式补全（零 LLM 成本）")
    root, rel = new_root(2)
    try:
        rep = fill_verification_basis(root, BASIS, apply=False)
        check("dry-run 只统计不写盘",
              rep["targeted"] == 2 and rep["written"] == 0, str(rep))
        rep2 = fill_verification_basis(root, BASIS, apply=True)
        check("apply 补齐 2 个节点", rep2["written"] == 2, str(rep2["written"]))
        fm4, content4 = nodefile.loads(
            open(os.path.join(root, rel["n1"]), encoding="utf-8").read())
        check("验证方式写入正文与 comment",
              f"# 验证方式：{BASIS}" in content4
              and (fm4["state_attributes"]["comment"]).get("验证方式") == BASIS)
        check("验证方式计入 CCG 完整度",
              "验证方式" in nodefile.ccg_completeness(content4)["required_present"])
        rep3 = fill_verification_basis(root, BASIS, apply=True)
        check("已有验证方式 → 跳过（幂等）",
              rep3["written"] == 0 and rep3["skipped_present"] == 2, str(rep3))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---------------- 13. issue #24 修复（max_tokens 解析链 + 响应面校验） --------
    # 能红说明：回退 http_llm 硬编码 1200 / 删除 _extract_content 校验时，
    # 本节断言即红（DEFAULT_MAX_TOKENS 被改小于 200000 同红）。
    print("\n【13】issue #24：max_tokens 三级解析 + 假成功拦截")
    from .consolidate import (DEFAULT_MAX_TOKENS, MAX_TOKENS_ENV, ROLE_DEFAULT_MODEL,
                              _extract_content, resolve_max_tokens)
    check("标准锁定：DEFAULT_MAX_TOKENS=200000（子代理配置标准 v0.5 §1）",
          DEFAULT_MAX_TOKENS == 200000, str(DEFAULT_MAX_TOKENS))
    check("标准锁定：reflect 默认模型=deepseek-flash（限时 id 已下架）",
          ROLE_DEFAULT_MODEL[REFLECT_ROLE] == "deepseek-flash",
          ROLE_DEFAULT_MODEL[REFLECT_ROLE])
    check("解析链：显式参数优先",
          resolve_max_tokens(4096) == 4096)
    saved_env = os.environ.get(MAX_TOKENS_ENV)
    try:
        os.environ[MAX_TOKENS_ENV] = "16000"
        check("解析链：env 次之",
              resolve_max_tokens(None) == 16000)
        os.environ[MAX_TOKENS_ENV] = "not-a-number"
        check("解析链：非法 env 回落默认（不炸批处理）",
              resolve_max_tokens(None) == DEFAULT_MAX_TOKENS)
        os.environ[MAX_TOKENS_ENV] = "0"
        check("解析链：非正 env 回落默认",
              resolve_max_tokens(None) == DEFAULT_MAX_TOKENS)
    finally:
        if saved_env is None:
            os.environ.pop(MAX_TOKENS_ENV, None)
        else:
            os.environ[MAX_TOKENS_ENV] = saved_env

    def _bad(name, data, expect_frag):
        try:
            _extract_content(data, "m", 1234)
            check(name, False, "未抛错")
        except RuntimeError as e:
            check(name, expect_frag in str(e) and "max_tokens=1234" in str(e),
                  str(e)[:120])

    _bad("坏形态1：choices 空", {"choices": []}, "无 choices")
    _bad("坏形态2：预算截断",
         {"choices": [{"finish_reason": "length",
                       "message": {"content": ""}}],
          "usage": {"completion_tokens": 1200}},
         "预算耗尽")
    _bad("坏形态3：空 content 假成功",
         {"choices": [{"finish_reason": "stop", "message": {"content": ""}}],
          "usage": {"completion_tokens": 1230}},
         "假成功")
    check("好形态：正常 content 放行",
          _extract_content({"choices": [{"finish_reason": "stop",
                                         "message": {"content": "ok"}}]},
                           "m", 999) == "ok")

    # ---------------- R. issue #64 修复守卫 ----------------
    print("\n【R】issue #64 修复守卫（replay_check 撤销一票否决 / 负条件两态拦截 / CLI 参数）")
    _r_run(verbose=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + ", ".join(FAILS))
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
