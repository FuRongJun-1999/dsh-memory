# -*- coding: utf-8 -*-
"""记忆评审流水线 · 级 4 蜂巢并发对接（spec 构造/投递/收卷）+ 级 5 意见落库治理。

真源：docs/记忆评审系统_立项设计与施工交接_20260915.md §5（spec/result 契约）
      §7（反面清单：评审不直接改知识层 / 意见必过 verify 令牌 / 不确定 DEFER）

五级分工：级 1-3（M1）=候选→捆包→规则装配，产出 (pkg, asm) 对；
        级 4（本模块）=每对 → hive spec → submit → poll 收卷（真并发、文件协议留痕）；
        级 5（本模块）=意见格式校验 → verify 令牌过 writepipe 六道闸落 contextual。

纪律是结构性的，不靠自觉：
  · 评审不改知识层：落库层固定 contextual，verify 令牌 layers_allow 不含 knowledge
    ——库层 require_layer_write 拦截，任何拦截器都绕不过（§7 反面清单第 1 条）。
  · 自验禁止：产出意见者（reflect）与落库裁决者（verify）不得同一 actor，判据
    复用 crosscheck.detect_self_verify（不另造判据，保持真源单一）。
  · 不确定即 DEFER：解析失败/格式越界一律不落库（Precision over noise）。
  · 零写入面：worker 只读 spec/context、只写自己的 result.json；认知图写入只发生在
    收卷后的 apply_opinions（本模块，走 writepipe 通道）。

运行：python -m md_cg.mreview.pipeline --help
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import uuid

from .. import crosscheck as CC
from .. import tokens as TK
from .. import writepipe as WP
from ..security import AccessDenied, Principal
from . import candidates as CD
from . import bundle as BD
from . import ruleset as RS

__all__ = [
    "VERDICTS", "OPINION_LAYER", "DEFAULT_MODEL", "TERMINAL_STATES",
    "hive_exe", "build_packages", "build_prompt", "build_spec", "dump_context",
    "submit", "submit_many", "poll", "wait_jobs", "read_result", "collect",
    "parse_opinions", "validate_opinion", "validate_opinions",
    "verifier_principal", "opinion_doc", "apply_opinions", "run_package",
    "run_batch", "main",
]

# ---- 常量 ----------------------------------------------------------------

VERDICTS = ("ACCEPT", "DEFER", "REJECT", "BLINDSPOT")   # 意见四态（资格裁决同源）
OPINION_LAYER = "contextual"        # verify 令牌 layers_allow=rejected/contextual
OPINION_BASIS = "measurement"       # 意见的验证基底：确定性规则命中 + 复核
TERMINAL_STATES = ("done", "error", "timeout", "killed")
DEFAULT_MODEL = "glm-4-flash"
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

SYSTEM_PROMPT = """你是记忆评审流水线中的【验证单元】。

职责边界（违反即无效）：
1. 只对给定节点清单逐条裁决，不得引入清单外的节点。
2. 只输出意见，不改写任何记忆——你没有写入通道，也不需要。
3. 不确定就 DEFER（硬纪律）：宁可漏判，不可错判。
4. 只有拿得出证据时才 REJECT；说不出证据就 DEFER。
5. ACCEPT 表示「已确认适用」，不是「没发现问题」——正条件无法确认时用 DEFER。

四态语义：
- ACCEPT    已确认适用
- DEFER     条件不足/无法确认（默认落点）
- REJECT    有据否定（冲突/来源许可不足/重复且劣于既有）
- BLINDSPOT 当前观测位置看不见（不是"不知道"，是"这个位置判断不了"）

输出契约（严格 JSON，无额外文字、无 markdown 围栏）：
{"verdicts": [{"node_id": "...", "verdict": "ACCEPT|DEFER|REJECT|BLINDSPOT",
               "reason": "一句话理由", "evidence": "证据（REJECT 必填）"}],
 "summary": "整包一句话结论"}
清单中每个节点都要有一条裁决，一条不多一条不少。"""


# ---- 级 4-A · spec 构造 ---------------------------------------------------

def hive_exe(exe=None) -> str:
    """蜂巢可执行文件：显式参数 > HIVE_EXE > 仓内 release 构建。"""
    if exe:
        return str(exe)
    env = (os.environ.get("HIVE_EXE") or "").strip()
    if env:
        return env
    name = "hive.exe" if os.name == "nt" else "hive"
    return os.path.join(_ROOT, "hive", "target", "release", name)


def _safe(name) -> str:
    return re.sub(r"[^0-9A-Za-z_.\-]", "_", str(name or "pkg"))[:120]


def _dump_json(path: str, obj) -> str:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return path


_ENTRY_KEYS = ("ref", "node_id", "proposal_id", "origin", "layer", "tags", "role",
               "importance", "evidence_count", "verification_basis",
               "lifecycle_state", "content_hash", "issue_kinds", "evidence",
               "excerpt")


def dump_context(pkg: dict, asm: dict, workdir: str, *, entry_limit=64) -> list:
    """包 + 规则装配 → context 文件（**绝对路径**，工人执行期内有效）。

    相对路径的解析基准是 spec.workdir，跨进程易错；绝对路径无歧义。
    """
    os.makedirs(workdir, exist_ok=True)
    base = _safe(pkg.get("bundle_id"))
    bp = os.path.join(workdir, base + ".bundle.json")
    rp = os.path.join(workdir, base + ".rules.json")
    ents = [{k: e.get(k) for k in _ENTRY_KEYS}
            for e in (pkg.get("entries") or [])[:int(entry_limit)]]
    _dump_json(bp, {"bundle_id": pkg.get("bundle_id"),
                    "group_kind": pkg.get("group_kind"),
                    "group_key": pkg.get("group_key"),
                    "size": pkg.get("size"), "entries": ents})
    _dump_json(rp, asm)
    return [bp, rp]


def build_prompt(pkg: dict, asm: dict, *, max_mech=120) -> str:
    """user_prompt：节点清单 + 机械命中 + 待检问题 + 输出要求。"""
    ents = pkg.get("entries") or []
    L = ["【待评包】bundle_id=%s  group=%s/%s  节点数=%d"
         % (pkg.get("bundle_id"), pkg.get("group_kind"),
            pkg.get("group_key"), len(ents)), ""]
    L.append("【节点清单】（仅可裁决以下节点）")
    for i, e in enumerate(ents, 1):
        frag = (e.get("excerpt") or "").strip().replace("\n", " ")[:220]
        L.append("%d) node_id=%s  layer=%s  basis=%s  tags=%s"
                 % (i, e.get("node_id"), e.get("layer"),
                    e.get("verification_basis"),
                    ",".join(e.get("tags") or []) or "-"))
        L.append("   正文摘录：%s" % (frag or "（无正文/正文缺失）"))
        if e.get("issue_kinds"):
            L.append("   机械初筛命中：%s" % ",".join(e["issue_kinds"]))
    L.append("")
    mech = asm.get("mechanical") or []
    if mech:
        L.append("【确定性规则命中】共 %d 条（机械层已给出，只需判断其语义后果）"
                 % len(mech))
        for m in mech[:int(max_mech)]:
            L.append("- [%s] %s :: %s"
                     % (m.get("issue_kind"), m.get("ref") or m.get("node_id"),
                        str(m.get("detail") or m.get("message") or "")[:160]))
    else:
        L.append("【确定性规则命中】无（本包未触发任何机械规则）")
    L.append("")
    llm = asm.get("llm") or []
    if llm:
        L.append("【待你判断的问题】逐项判断，并在 reason 中体现结论：")
        for q in llm[:40]:
            L.append("- (规则 %s / 检查 %s) %s"
                     % (q.get("rule_id"), q.get("check"), q.get("question")))
    L.append("")
    L.append("【输出】严格按 system 中的 JSON 契约，对每个 node_id 给出一条裁决。")
    return "\n".join(L)


def build_spec(pkg: dict, asm: dict, *, context_files=None, model=None,
               timeout_s=600, temperature=0.0, max_tokens=4096) -> dict:
    """(pkg, asm) → hive spec（文件协议的可投递单元）。"""
    nids = [str(e.get("node_id")) for e in (pkg.get("entries") or [])
            if e.get("node_id")]
    return {"model": model or os.environ.get("HIVE_MODEL") or DEFAULT_MODEL,
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt": build_prompt(pkg, asm),
            "context_files": list(context_files or []),
            "timeout_s": int(timeout_s),
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            # 归因元信息（hive 忽略；收卷侧用于配对与审计）
            "meta": {"bundle_id": pkg.get("bundle_id"),
                     "group_kind": pkg.get("group_kind"),
                     "group_key": pkg.get("group_key"),
                     "size": pkg.get("size"), "node_ids": nids}}


def build_packages(*, root=None, sources=None, limit=None, nodes=None,
                   max_per_bundle=50, rules_dir=None, now=None) -> dict:
    """级 1-3 串联：候选 → 捆包 → 规则装配，产出配对的 (pkg, asm) 列表。"""
    c = CD.generate(root, sources=sources or CD.SOURCES, nodes=nodes, limit=limit,
                    with_report=False, now=now)
    b = BD.bundle(c.get("candidates") or [], nodes=nodes, root=root,
                  max_per_bundle=max_per_bundle)
    a = RS.assemble_all(b, rules_dir=rules_dir)
    pairs = []
    for pkg, asm in zip(b.get("bundles") or [], a.get("packages") or []):
        pairs.append((pkg, asm))
    return {"candidates": c, "bundles": b, "assembled": a, "pairs": pairs}


# ---- 级 4-B · 投递 / 收卷 -------------------------------------------------

def _run(argv, *, env=None, timeout=120, cwd=None, stdin_text=None):
    """统一子进程入口：argv 列表 + 显式 UTF-8 + PYTHONUTF8=1，不经 shell（第15条）。"""
    e = dict(os.environ)
    e["PYTHONUTF8"] = "1"
    if env:
        e.update({k: str(v) for k, v in env.items()})
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=e, timeout=timeout, cwd=cwd,
                          input=stdin_text, shell=False)


def _last_json(text: str):
    """stdout 逐行解析取最后一个 JSON 对象（容忍前导日志行）。"""
    for line in reversed((text or "").strip().splitlines()):
        s = line.strip()
        if not s.startswith("{"):
            continue
        try:
            obj = json.loads(s)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def submit(exe: str, jobs_dir: str, spec: dict, *, timeout=120) -> dict:
    """投递单包 spec → {"ok":True,"job_id":...}；失败返回 ok=False + error。"""
    os.makedirs(jobs_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mrev_spec_") as td:
        sp = _dump_json(os.path.join(td, "spec.json"), spec)
        p = _run([exe, "submit", "--spec", sp, "--jobs", jobs_dir], timeout=timeout)
    if p.returncode != 0:
        return {"ok": False, "returncode": p.returncode,
                "error": (p.stderr or p.stdout or "").strip()[:800]}
    d = _last_json(p.stdout)
    if not d:
        return {"ok": False, "error": "submit 输出非 JSON",
                "stdout": (p.stdout or "")[:800]}
    d.setdefault("ok", True)
    return d


def submit_many(exe: str, jobs_dir: str, specs: list, *, timeout=120) -> list:
    """批量投递（hive 侧并发消费；本函数逐条投递并保序配对）。"""
    return [submit(exe, jobs_dir, s, timeout=timeout) for s in specs]


def poll(exe: str, jobs_dir: str, job_id=None, *, timeout=120) -> dict:
    """查询 job 状态（不传 job_id = 列出全部）。"""
    argv = [exe, "poll"]
    if job_id:
        argv.append(str(job_id))
    argv += ["--jobs", jobs_dir]
    p = _run(argv, timeout=timeout)
    if p.returncode != 0:
        return {"ok": False, "returncode": p.returncode,
                "error": (p.stderr or p.stdout or "").strip()[:800]}
    d = _last_json(p.stdout)
    return d or {"ok": False, "error": "poll 输出非 JSON",
                 "stdout": (p.stdout or "")[:800]}


def _job_id(j: dict):
    return j.get("job_id") or j.get("id")


def _job_state(j: dict) -> str:
    """state 读取兼容两种形态（扁平 / status 嵌套）；仅供轮询判终态。"""
    s = j.get("state")
    if s:
        return str(s)
    st = j.get("status")
    if isinstance(st, dict):
        return str(st.get("state") or "")
    return str(st or "")


def wait_jobs(exe: str, jobs_dir: str, job_ids=None, *, timeout_s=900,
              interval_s=1.0, on_tick=None) -> dict:
    """轮询至全部终态（或超时）→ done/failed/pending 三分类 + 原始快照。"""
    want = set(str(x) for x in (job_ids or [])) or None
    deadline = time.time() + max(1.0, float(timeout_s))
    last = {}
    while True:
        r = poll(exe, jobs_dir)
        states = {}
        for j in (r.get("jobs") or []):
            jid = _job_id(j)
            if jid is None:
                continue
            jid = str(jid)
            if want is not None and jid not in want:
                continue
            states[jid] = _job_state(j) or "pending"
            last[jid] = j
        done = sorted(k for k, v in states.items() if v == "done")
        failed = sorted(k for k, v in states.items()
                        if v in TERMINAL_STATES and v != "done")
        pending = sorted(k for k, v in states.items() if v not in TERMINAL_STATES)
        if on_tick:
            on_tick({"states": dict(states), "done": len(done),
                     "pending": len(pending), "failed": len(failed)})
        if not pending:
            if want is None or want <= set(states):
                return {"ok": not failed, "done": done, "failed": failed,
                        "pending": [], "states": states, "jobs": last}
            if time.time() >= deadline:
                miss = sorted(want - set(states))
                return {"ok": False, "done": done, "failed": failed,
                        "pending": miss, "states": states, "jobs": last,
                        "error": "未在超时内观测到 job：%s" % ",".join(miss)}
        if time.time() >= deadline:
            return {"ok": False, "done": done, "failed": failed,
                    "pending": pending, "states": states, "jobs": last,
                    "error": "等待终态超时（%ss）" % timeout_s}
        time.sleep(max(0.05, float(interval_s)))


def read_result(jobs_dir: str, job_id: str) -> dict:
    """读工人产出（job 目录的 result.json）。"""
    p = os.path.join(jobs_dir, str(job_id), "result.json")
    if not os.path.isfile(p):
        return {"ok": False, "error": "result.json 不存在：%s" % p}
    try:
        with open(p, encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": "result.json 读取失败：%s" % exc}
    return obj if isinstance(obj, dict) else {"ok": False, "error": "result 非对象"}


def collect(jobs_dir: str, job_ids) -> dict:
    """按 job_id 收卷（读 result.json），返回 {job_id: result} 保序映射。"""
    return {str(j): read_result(jobs_dir, j) for j in (job_ids or [])}


# ---- 级 5-A · 意见解析与格式校验（校验率 100% 是验收口径）-----------------

def _extract_json(text: str):
    """从模型文本抽 JSON 对象：整体 → ```围栏``` → 首尾大括号切片。"""
    s = (text or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except ValueError:
        pass
    m = re.search(r"```(?:json)?\s*(.+?)```", s, re.S)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except ValueError:
            pass
    i, k = s.find("{"), s.rfind("}")
    if 0 <= i < k:
        try:
            return json.loads(s[i:k + 1])
        except ValueError:
            pass
    return None


def parse_opinions(result: dict) -> dict:
    """result.json → {"ok":True,"verdicts":[...],"summary":...}。

    两形态都能收：
      · 执行器直写 {"ok":true,"verdicts":[...],"summary":...}
      · LLM 文本   {"ok":true,"content":"{...JSON...}"}（exec.py 默认形态）
    """
    if not isinstance(result, dict):
        return {"ok": False, "error": "result 非对象"}
    if result.get("error"):
        return {"ok": False, "error": "工人报错：%s" % result["error"]}
    v = result.get("verdicts")
    summary = result.get("summary") or ""
    if v is None:
        obj = _extract_json(result.get("content") or "")
        if not isinstance(obj, dict):
            return {"ok": False, "error": "未能从 content 中解析 JSON 意见块"}
        v = obj.get("verdicts")
        summary = obj.get("summary") or summary
    if not isinstance(v, list):
        return {"ok": False, "error": "verdicts 非数组（got %s）" % type(v).__name__}
    return {"ok": True, "verdicts": v, "summary": str(summary)}


def _norm_verdict(v):
    s = str(v or "").strip().upper()
    return s if s in VERDICTS else None


def validate_opinion(op, node_ids=None):
    """单条意见格式校验：合法返回 None，非法返回错误串。"""
    if not isinstance(op, dict):
        return "意见非对象"
    nid = str(op.get("node_id") or "").strip()
    if not nid:
        return "缺 node_id"
    if node_ids is not None and nid not in node_ids:
        return "node_id 不属于本包：%s" % nid
    vd = _norm_verdict(op.get("verdict"))
    if vd is None:
        return "verdict 越界：%r" % (op.get("verdict"),)
    if not str(op.get("reason") or "").strip():
        return "缺 reason"
    if vd == "REJECT" and not str(op.get("evidence") or "").strip():
        return "REJECT 缺 evidence（有据才拒）"
    return None


def validate_opinions(verdicts, node_ids=None) -> dict:
    """批量校验：valid/invalid 明细 + 通过率（用于 100% 口径断言）。"""
    total = len(verdicts or [])
    valid, invalid = [], []
    for i, op in enumerate(verdicts or []):
        err = validate_opinion(op, node_ids)
        if err:
            invalid.append({"index": i, "error": err,
                            "node_id": (op.get("node_id")
                                        if isinstance(op, dict) else None)})
            continue
        op = dict(op)
        op["verdict"] = _norm_verdict(op.get("verdict"))
        valid.append(op)
    rate = 1.0 if total == 0 else len(valid) / float(total)
    return {"total": total, "valid": valid, "invalid": invalid,
            "pass_rate": rate, "ok": bool(valid) and not invalid}


# ---- 级 5-B · 落库（verify 令牌 + writepipe 六道闸；不自造通道）-----------

def verifier_principal(*, actor="mreview-verifier", session=None,
                       layers_allow=None, ops_allow=None) -> Principal:
    """验证单元 Principal——角色规格取自 tokens 真源（避免手写漂移）。"""
    spec = TK.role_spec("verify")
    return Principal(actor=actor, clearance=spec.get("clearance_cap") or "internal",
                     can_write=bool(spec.get("can_write")),
                     can_admin=bool(spec.get("can_admin")),
                     role="verify", unit="verify",
                     session=session or ("mrev_" + uuid.uuid4().hex[:12]),
                     layers_allow=list(layers_allow or spec.get("layers_allow") or []),
                     ops_allow=ops_allow, auth_mode="mreview")


def opinion_doc(pkg: dict, opinions: list, *, reviewer: str, summary="",
                invalid=None) -> str:
    """评审意见节点正文（核心修改四要素：内容/原因/位置/验证）。"""
    cnt = {k: 0 for k in VERDICTS}
    for o in opinions:
        cnt[_norm_verdict(o.get("verdict")) or "?"] = \
            cnt.get(_norm_verdict(o.get("verdict")) or "?", 0) + 1
    dist = " / ".join("%s %d" % (k, cnt.get(k, 0)) for k in VERDICTS)
    L = ["# 记忆评审意见 · 包 %s（%s/%s，%d 节点）"
         % (pkg.get("bundle_id"), pkg.get("group_kind"), pkg.get("group_key"),
            len(pkg.get("entries") or [])),
         "来源：级 4 蜂巢并发评审（评审者=%s）" % reviewer,
         "裁决分布：%s" % dist]
    if summary:
        L.append("整包结论：%s" % summary)
    L.append("")
    for o in opinions:
        seg = "- [%s] %s：%s" % (_norm_verdict(o.get("verdict")) or "?",
                                o.get("node_id"),
                                str(o.get("reason") or "").strip())
        ev = str(o.get("evidence") or "").strip()
        if ev:
            seg += "（证据：%s）" % ev[:300]
        L.append(seg)
    if invalid:
        L.append("")
        L.append("【未落库条目】%s" % json.dumps(invalid, ensure_ascii=False))
    L.append("")
    L.append("【内容】级 4 并发评审对包 %s 的逐节点裁决意见。" % pkg.get("bundle_id"))
    L.append("【原因】机械层已过滤确定性缺陷，语义判断留给验证单元；意见落 contextual "
             "供治理层决策——评审不改知识层。")
    L.append("【位置】源包 group=%s/%s（%d 节点）。"
             % (pkg.get("group_kind"), pkg.get("group_key"),
                len(pkg.get("entries") or [])))
    L.append("【验证】机械规则命中 %d 条；意见格式校验 %d/%d 通过（越界条目已剔除）。"
             % (len((pkg.get("_asm") or {}).get("mechanical") or []),
                len(opinions), len(opinions) + len(invalid or [])))
    return "\n".join(L)


def apply_opinions(cg, pkg: dict, opinions: list, *, reviewer, applier,
                   dry_run=False, pipe=None, layer=OPINION_LAYER,
                   importance=0.4, tags=None, node_id=None,
                   summary="", invalid=None) -> dict:
    """落库单包意见（级 5 唯一的写入口）。

    顺序（任一环不过即不落库）：
      1 自验违例检测（评审者 ≠ 落库裁决者，判据复用 crosscheck）
      2 意见非空（全 DEFER 且空 → 不写，零噪声）
      3 verify 令牌 + writepipe 六道闸 + 库层 require_layer_write
      4 合规规则库（部署侧 MDCG_POLICY_FILE）——audit 的 text 验证器在**无规则**
        时恒 DEFER（audit._rule_check「无规则不能假装合规」），意见将转审核队列
        （`moved_to="review_queue"`）而非落盘。这是设计行为不是故障：本函数把
        去向如实透出为 `moved_to` / `deferred`，**不把「入队」报成「落库」**。
    """
    rows = [{"unit": CC.REFLECT_UNIT, "actor": str(reviewer or "")},
            {"unit": CC.VERIFY_UNIT, "actor": str(applier or "")}]
    if CC.detect_self_verify(rows):
        return {"ok": False, "committed": False, "refused": True,
                "reason": "self_verify_disallowed",
                "detail": "评审者与落库裁决者为同一执行者（%s）——自验被拒（§7）"
                          % reviewer}
    if not opinions:
        return {"ok": True, "committed": False, "skipped": True,
                "reason": "no_opinions（无有效意见，零噪声不落库）"}
    nid = node_id or ("mr_opinion_" + _safe(pkg.get("bundle_id")))
    doc = opinion_doc(pkg, opinions, reviewer=str(reviewer), summary=summary,
                      invalid=invalid)
    if dry_run:
        return {"ok": True, "committed": False, "dry_run": True, "node_id": nid,
                "doc_len": len(doc)}
    a = {"node_id": nid, "content": doc, "layer": layer,
         "tags": list(tags or ["cap:记忆评审", "mreview", "opinion",
                               "bundle:" + _safe(pkg.get("bundle_id"))]),
         "importance": float(importance), "verification_basis": OPINION_BASIS,
         "content_kind": "text",
         # 意见是评审产物（contextual），不参与知识层冲突判定：冲突闸若命中会
         # 把意见当冲突源转入审核队列（语义不符），故显式跳过（闸层可关，
         # 库层 require_layer_write 不可关——评审不改知识层的结构约束仍在）。
         "consistency": False}
    try:
        out = (pipe or WP.default_pipeline()).execute(cg, a)
    except AccessDenied as exc:
        # 结构性拒绝（如 layer=knowledge 越出 verify 令牌的 layers_allow）：
        # 如实上报为拒写，不吞异常也不改写写入语义（§7 反面清单第 1 条）。
        return {"ok": False, "committed": False, "refused": True,
                "reason": "layer_denied", "node_id": nid, "layer": layer,
                "detail": "%s: %s" % (type(exc).__name__, exc)}
    except Exception as exc:                            # noqa: BLE001
        return {"ok": False, "committed": False, "refused": False,
                "reason": "write_error", "node_id": nid, "layer": layer,
                "detail": "%s: %s" % (type(exc).__name__, exc)}
    return {"ok": bool(out.get("ok")), "committed": bool(out.get("committed")),
            "moved_to": out.get("moved_to"),
            # 「改了去向但没落盘」（如合规/冲突闸转审核队列、gated 的 DROP/DEFER）
            # 与「落盘」是两种结局：分开报，调用方不必读 response 才能分辨。
            "deferred": bool(out.get("moved_to")) and not out.get("committed"),
            "node_id": nid, "layer": layer, "response": out,
            "doc_len": len(doc)}


# ---- 编排 ----------------------------------------------------------------

def run_package(*, pkg, asm, cg, exe=None, jobs_dir=None, ctx_dir=None,
                reviewer="mreview-worker", applier="mreview-applier",
                model=None, timeout_s=900, interval_s=1.0, dry_run=False,
                keep_jobs=True) -> dict:
    """单包全链路：dump context → submit → wait → parse → validate → apply。"""
    exe = hive_exe(exe)
    jobs_dir = jobs_dir or os.path.join(tempfile.gettempdir(), "mrev_jobs")
    ctx_dir = ctx_dir or os.path.join(tempfile.gettempdir(), "mrev_ctx")
    ctx_files = dump_context(pkg, asm, ctx_dir)
    spec = build_spec(pkg, asm, context_files=ctx_files, model=model,
                      timeout_s=timeout_s)
    sub = submit(exe, jobs_dir, spec)
    if not sub.get("ok") or not _job_id(sub):
        return {"ok": False, "stage": "submit", "error": sub.get("error"),
                "submit": sub, "bundle_id": pkg.get("bundle_id")}
    jid = str(_job_id(sub))
    w = wait_jobs(exe, jobs_dir, [jid], timeout_s=timeout_s,
                  interval_s=interval_s)
    if w.get("failed") or not w.get("done"):
        return {"ok": False, "stage": "wait", "job_id": jid, "wait": w,
                "bundle_id": pkg.get("bundle_id")}
    res = read_result(jobs_dir, jid)
    parsed = parse_opinions(res)
    if not parsed.get("ok"):
        return {"ok": False, "stage": "parse", "job_id": jid, "error":
                parsed.get("error"), "bundle_id": pkg.get("bundle_id")}
    nids = {str(e.get("node_id")) for e in (pkg.get("entries") or [])
            if e.get("node_id")}
    val = validate_opinions(parsed["verdicts"], nids or None)
    pkg2 = dict(pkg, _asm=asm)
    app = apply_opinions(cg, pkg2, val["valid"], reviewer=reviewer,
                         applier=applier, dry_run=dry_run,
                         summary=parsed.get("summary"), invalid=val["invalid"])
    return {"ok": bool(app.get("ok")), "bundle_id": pkg.get("bundle_id"),
            "job_id": jid, "opinions": len(parsed["verdicts"]),
            "valid": len(val["valid"]), "invalid": len(val["invalid"]),
            "pass_rate": val["pass_rate"], "deferred": bool(app.get("deferred")),
            "apply": app, "stages": {"submit": True, "wait": True, "parse": True}}


def run_batch(*, pairs, cg, exe=None, jobs_dir=None, ctx_dir=None,
              reviewer="mreview-worker", applier="mreview-applier", model=None,
              timeout_s=1800, interval_s=1.0, dry_run=False, on_tick=None) -> dict:
    """批量并发：先全投递（hive worker 池并发消费），再统一等候，再逐包落库。

    并发发生在**投递之后**——本函数投递不阻塞，故 N 包的墙钟≈最慢一包。
    """
    exe = hive_exe(exe)
    jobs_dir = jobs_dir or os.path.join(tempfile.gettempdir(), "mrev_jobs")
    ctx_dir = ctx_dir or os.path.join(tempfile.gettempdir(), "mrev_ctx")
    os.makedirs(jobs_dir, exist_ok=True)
    staged, posted, jids = [], [], []
    for pkg, asm in pairs:
        ctx_files = dump_context(pkg, asm, ctx_dir)
        spec = build_spec(pkg, asm, context_files=ctx_files, model=model,
                          timeout_s=timeout_s)
        sub = submit(exe, jobs_dir, spec)
        staged.append({"bundle_id": pkg.get("bundle_id"), "pkg": pkg,
                       "asm": asm, "submit": sub})
        if sub.get("ok") and _job_id(sub):
            jid = str(_job_id(sub))
            jids.append(jid)
            posted.append(staged[-1])
    w = wait_jobs(exe, jobs_dir, jids, timeout_s=timeout_s,
                  interval_s=interval_s, on_tick=on_tick)
    by_jid = {}
    for i, s in enumerate(staged):
        if s["submit"].get("ok") and _job_id(s["submit"]):
            by_jid[str(_job_id(s["submit"]))] = s
    results, ok_n, valid_n, invalid_n, applied_n, deferred_n = [], 0, 0, 0, 0, 0
    for jid in jids:
        s = by_jid.get(jid) or {}
        pkg, asm = s.get("pkg") or {}, s.get("asm") or {}
        state = (w.get("states") or {}).get(jid)
        if state != "done":
            results.append({"ok": False, "bundle_id": pkg.get("bundle_id"),
                            "job_id": jid, "stage": "wait", "state": state})
            continue
        res = read_result(jobs_dir, jid)
        parsed = parse_opinions(res)
        if not parsed.get("ok"):
            results.append({"ok": False, "bundle_id": pkg.get("bundle_id"),
                            "job_id": jid, "stage": "parse",
                            "error": parsed.get("error")})
            continue
        nids = {str(e.get("node_id")) for e in (pkg.get("entries") or [])
                if e.get("node_id")}
        val = validate_opinions(parsed["verdicts"], nids or None)
        app = apply_opinions(cg, dict(pkg, _asm=asm), val["valid"],
                             reviewer=reviewer, applier=applier,
                             dry_run=dry_run, summary=parsed.get("summary"),
                             invalid=val["invalid"])
        ok_n += 1
        valid_n += len(val["valid"])
        invalid_n += len(val["invalid"])
        applied_n += 1 if app.get("committed") else 0
        deferred_n += 1 if app.get("deferred") else 0
        results.append({"ok": bool(app.get("ok")),
                        "bundle_id": pkg.get("bundle_id"), "job_id": jid,
                        "opinions": len(parsed["verdicts"]),
                        "valid": len(val["valid"]), "invalid": len(val["invalid"]),
                        "pass_rate": val["pass_rate"],
                        "deferred": bool(app.get("deferred")), "apply": app})
    total_op = valid_n + invalid_n
    return {"ok": all(r.get("ok") for r in results) and bool(results),
            "jobs": len(jids), "submitted": len(posted),
            "done": len(w.get("done") or []), "failed": w.get("failed") or [],
            "packages": len(results), "opinions": total_op,
            "valid": valid_n, "invalid": invalid_n,
            "pass_rate": (1.0 if total_op == 0 else valid_n / float(total_op)),
            "committed": applied_n, "deferred": deferred_n,
            "results": results, "wait": w}


# ---- CLI -----------------------------------------------------------------

def main(argv=None):                                        # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(prog="python -m md_cg.mreview.pipeline",
                                 description="记忆评审 级4 蜂巢并发 + 级5 落库")
    ap.add_argument("--root", default=None, help="认知图根（缺省 MDCG_ROOT）")
    ap.add_argument("--packages", type=int, default=10, help="试跑包数（0=全部）")
    ap.add_argument("--jobs", default=None, help="hive jobs 目录（隔离生产）")
    ap.add_argument("--ctx", default=None, help="context 文件目录")
    ap.add_argument("--hive", default=None, help="hive 可执行文件")
    ap.add_argument("--model", default=None, help="模型名")
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--reviewer", default="mreview-worker")
    ap.add_argument("--applier", default="mreview-applier")
    ap.add_argument("--dry-run", action="store_true", help="只校验不落库")
    ap.add_argument("--apply", action="store_true", help="实际落库（缺省不写）")
    a = ap.parse_args(argv)
    from .. import mdcos
    root = a.root or os.environ.get("MDCG_ROOT")
    if not root:
        raise SystemExit("缺少 --root 或 MDCG_ROOT（拒绝在未知根上运行）")
    cg = mdcos.MdCGSecure(root, principal=verifier_principal(actor=a.applier))
    built = build_packages(root=root, limit=None)
    pairs = built["pairs"][:a.packages] if a.packages else built["pairs"]
    rep = run_batch(pairs=pairs, cg=cg, exe=a.hive, jobs_dir=a.jobs,
                    ctx_dir=a.ctx, reviewer=a.reviewer, applier=a.applier,
                    model=a.model, timeout_s=a.timeout,
                    dry_run=(a.dry_run or not a.apply))
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(main())
