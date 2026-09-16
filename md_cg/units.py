# -*- coding: utf-8 -*-
"""units.py · 复核单元接线层：蜂巢优先 → 提示配置 → harness 端子代理降级。

定位（与 audit.py 同一条架构约束）：**能力不在认知图内**。本模块不做智能判定，
只做三件事：选通道（probe/plan）→ 派发请求（submit/wait/run）→ 记账（_units.jsonl）。

使用者裁定（2026-09-16，第 17 条精神）：编译器（ccgc）的复核**优先使用蜂巢的
反思单元 / 验证单元**（reflect / verify，与 crosscheck.REFLECT_UNIT/VERIFY_UNIT 同值，
不新造角色名）；蜂巢不可用 → **提示使用者配置**（给出可照做的构建/启动/环境变量命令）；
或经显式 allow_degrade=True 降级到 **harness 端子代理**（宿主 agent 派发，裁决经
crosscheck 同款 verdicts 通道回填）。理由：使用者的复核是昂贵的——重活交给可并行的
外部单元，agent 本体只做编排与记账。

蜂巢契约（真源 hive/README.md + hive/hive_mcp/mcp_server.py；**复制契约不 import**，
保持 md_cg 对 hive 零依赖，与 ccgc「同款语义就地实现防 import 环」惯例一致）：
    jobs 目录   = $HIVE_JOBS_DIR | <repo>/hive/jobs
    serve 判活  = jobs/_serve.json 的 ts（毫秒）距今 < 5s        （同 _serve_alive）
    job 目录    = jobs/<job_id>/{spec.json,status.json,result.json,kill}
    job_id      = h<java_ms>_<uuid6>                             （同 _submit）
    result.json = {"ok":true,"content":...} | {"ok":false,"error":...}
    终态        = done | error | timeout | killed
    拉起 serve  = <repo>/hive/target/release/hive serve --jobs <jobs>（detached）

边界（诚实声明，不猜测）：
    · 本模块**不产生裁决**，只搬运；裁决由外部单元负责。
    · 契约漂移：hive 侧协议若变更，本模块以「无 result / 超时」如实失败，不假装成功。
    · 默认**不自动拉起 serve**（使用者裁定：不可用即提示配置）；autostart=True 才拉起。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid

HIVE, SUBAGENT, CONFIGURE = "hive", "subagent", "configure"
STATES = (HIVE, SUBAGENT, CONFIGURE)

REFLECT, VERIFY = "reflect", "verify"      # 同 crosscheck.REFLECT_UNIT/VERIFY_UNIT
ROLES = (REFLECT, VERIFY)

SERVE_FILE, SPEC_FILE = "_serve.json", "spec.json"
STATUS_FILE, RESULT_FILE, KILL_FILE = "status.json", "result.json", "kill"
LOG_NAME = "_units.jsonl"
TERMINAL_STATES = ("done", "error", "timeout", "killed")
FRESH_S, DEFAULT_TIMEOUT_S, DEFAULT_POLL_S = 5.0, 120, 1.0
DEFAULT_MAX_TOKENS = 2048

ENV_JOBS_DIR, ENV_EXE = "HIVE_JOBS_DIR", "HIVE_EXE"
ENV_MODEL, ENV_API_KEY = "MDCG_UNIT_MODEL", "HIVE_API_KEY"

ACCEPT, REJECT, DEFER, BLINDSPOT = "ACCEPT", "REJECT", "DEFER", "BLINDSPOT"
_VERDICT_MAP = {
    "accept": ACCEPT, "accepted": ACCEPT, "keep": ACCEPT, "pass": ACCEPT,
    "ok": ACCEPT, "approve": ACCEPT,
    "drop": REJECT, "reject": REJECT, "rejected": REJECT, "deny": REJECT, "fail": REJECT,
    "defer": DEFER, "deferred": DEFER, "unsure": DEFER, "unclear": DEFER, "skip": DEFER,
    "blindspot": BLINDSPOT, "blind": BLINDSPOT,
}


def repo_root() -> str:
    """仓库根（md_cg 的上一级）；不用 cwd——cwd 由宿主决定，不可作判据。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def jobs_dir(explicit: str = "") -> str:
    d = explicit or os.environ.get(ENV_JOBS_DIR) or os.path.join(repo_root(), "hive", "jobs")
    return os.path.abspath(d)


def exe_path() -> str:
    exe = os.environ.get(ENV_EXE)
    if exe:
        return exe
    return os.path.join(repo_root(), "hive", "target", "release",
                        "hive.exe" if os.name == "nt" else "hive")


def model_name(explicit: str = "") -> str:
    """复核模型（LLM 委托型执行器的 spec.model 必填）。"""
    return (explicit or os.environ.get(ENV_MODEL) or "").strip()


def serve_state(jobs: str = "", fresh_s: float = FRESH_S) -> dict:
    """serve 判活：只认 _serve.json 心跳新鲜度（同 _serve_alive），不试端口/进程名。"""
    jd = jobs_dir(jobs)
    p = os.path.join(jd, SERVE_FILE)
    out = {"jobs_dir": jd, "heartbeat": p, "exists": os.path.isfile(p),
           "alive": False, "age_s": None, "pid": None, "reason": ""}
    if not out["exists"]:
        out["reason"] = "未见 _serve.json 心跳（serve 未启动或 jobs 目录不对）"
        return out
    try:
        with open(p, encoding="utf-8") as f:
            hb = json.load(f)
    except (OSError, ValueError) as exc:
        out["reason"] = "心跳不可读：%s: %s" % (type(exc).__name__, exc)
        return out
    age = time.time() - ((hb.get("ts") or 0) / 1000.0)
    out.update({"age_s": round(age, 3), "pid": hb.get("pid"), "raw": hb})
    out["alive"] = age < float(fresh_s)
    out["reason"] = "" if out["alive"] else "心跳过期 %.1fs（阈值 %ss）——serve 可能已退出" % (
        age, fresh_s)
    return out


def setup_hint(jobs: str = "", reason: str = "") -> str:
    """不可用时给使用者看的**配置指引**（含降级指引）——提示即责任，须可照着做。"""
    jd = jobs_dir(jobs)
    return ("蜂巢不可用：%s\n"
            "  [A 配置蜂巢（推荐，第 17 条）]\n"
            "     1) cd %s && cargo build --release\n"
            "     2) set %s=<LLM密钥>\n     3) set %s=<复核模型名>\n"
            "     4) 启动：%s serve --jobs \"%s\"（或 hive_spawn 自动拉起）\n"
            "     判活判据：%s 的 ts 距今 < %ss\n"
            "  [B 降级 harness 端子代理]\n"
            "     重发本请求并带 allow_degrade=true：本模块返回复核请求包（prompt），\n"
            "     由宿主子代理执行后经 verdicts 回填裁决。"
            % (reason or "serve 未存活", os.path.dirname(exe_path()), ENV_API_KEY,
               ENV_MODEL, exe_path(), jd, os.path.join(jd, SERVE_FILE), int(FRESH_S)))


def probe(jobs: str = "", model: str = "", fresh_s: float = FRESH_S,
          allow_degrade: bool = False, channel: str = "") -> dict:
    """三级能力探测：hive（可派发）→ configure（提示配置）→ subagent（显式降级）。

    判据只认**心跳 + 模型名**两项硬前提；缺任一即如实降级，绝不用相似度
    （如「hive 目录存在」）冒充可用（资格由条件证据裁决，不由相似度裁决）。
    """
    st = serve_state(jobs, fresh_s)
    mdl = model_name(model)
    if st["alive"] and mdl:
        return {"state": HIVE, "transport": HIVE, "model": mdl, "jobs_dir": st["jobs_dir"],
                "serve": st, "channel": "", "hint": ""}
    why = st["reason"] if not st["alive"] else "serve 存活但未配置复核模型（%s）" % ENV_MODEL
    if allow_degrade:
        return {"state": SUBAGENT, "transport": SUBAGENT, "model": mdl,
                "jobs_dir": st["jobs_dir"], "serve": st,
                "channel": channel or "harness-subagent",
                "hint": "已按 allow_degrade 降级到 harness 端子代理：请把 prompt 交给宿主子代理，"
                        "裁决经 verdicts 回填（蜂巢不可用原因：%s）" % why}
    return {"state": CONFIGURE, "transport": None, "model": mdl,
            "jobs_dir": st["jobs_dir"], "serve": st, "channel": "",
            "hint": setup_hint(jobs, why)}


def plan(jobs: str = "", model: str = "", fresh_s: float = FRESH_S,
         allow_degrade: bool = False, channel: str = "") -> dict:
    """优先级链自描述（供 cg op=ccg action=units 与审计查看）。"""
    p = probe(jobs, model, fresh_s, allow_degrade, channel)
    return {"state": p["state"], "transport": p["transport"], "model": p["model"],
            "jobs_dir": p["jobs_dir"], "serve": p["serve"], "channel": p["channel"],
            "chain": [
                {"order": 1, "transport": HIVE, "action": "派发 reflect/verify 单元并等待 result.json",
                 "when": "jobs/_serve.json 心跳 < %ss 且 %s 已配置" % (int(FRESH_S), ENV_MODEL)},
                {"order": 2, "transport": CONFIGURE, "action": "返回配置指引（不自动拉起、不假装通过）",
                 "when": "蜂巢不可用"},
                {"order": 3, "transport": SUBAGENT, "action": "返回复核请求包，由 harness 端子代理执行并回填",
                 "when": "调用方显式 allow_degrade=True"},
            ],
            "hint": p["hint"]}


# ---------------------------------------------------------------- 派发与收取

def _job_id() -> str:
    """同 _submit：serve 侧按 'h' 前缀识别任务目录。"""
    return "h%d_%s" % (int(time.time() * 1000), uuid.uuid4().hex[:6])


def _log(cg, rec: dict) -> None:
    """留痕 _units.jsonl（对齐 _crosscheck.jsonl / _backfill.jsonl 纪律）。"""
    root = getattr(cg, "root", None) or getattr(getattr(cg, "cg", None), "root", None)
    if not root:
        return
    try:
        rec = dict(rec)
        rec.setdefault("ts", int(time.time() * 1000))
        with open(os.path.join(str(root), LOG_NAME), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def submit(*, prompt: str, role: str = REFLECT, model: str = "", system_prompt: str = "",
           context_files=None, timeout_s: int = DEFAULT_TIMEOUT_S,
           max_tokens: int = DEFAULT_MAX_TOKENS, temperature=None, jobs: str = "",
           actor: str = "", extra: dict = None, cg=None) -> dict:
    """写一条 LLM 委托型 job（spec.json + status.json，形态同 _submit）；只写文件不起进程。"""
    if role not in ROLES:
        return {"ok": False, "error": "未知复核角色：%r（可选 %s）" % (role, list(ROLES))}
    mdl = model_name(model)
    if not mdl:
        return {"ok": False, "error": "未配置复核模型：请设 %s 或显式传 model" % ENV_MODEL}
    if not str(prompt or "").strip():
        return {"ok": False, "error": "prompt 为空"}
    jd, job_id = jobs_dir(jobs), _job_id()
    d = os.path.join(jd, job_id)
    spec = {"model": mdl, "user_prompt": str(prompt), "system_prompt": str(system_prompt or ""),
            "timeout_s": int(timeout_s), "max_tokens": int(max_tokens),
            "role": role, "unit_role": role}
    if context_files:
        spec["context_files"] = list(context_files)
    if temperature is not None:
        spec["temperature"] = temperature
    if extra:
        spec.update(extra)
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, SPEC_FILE), "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False)
        with open(os.path.join(d, STATUS_FILE), "w", encoding="utf-8") as f:
            json.dump({"job_id": job_id, "state": "pending",
                       "created_ts": int(time.time() * 1000), "started_ts": None,
                       "heartbeat_ts": None, "elapsed_s": 0.0, "timeout_s": int(timeout_s),
                       "model": mdl, "pid": None, "error": None}, f, ensure_ascii=False)
    except OSError as exc:
        return {"ok": False, "job_dir": d,
                "error": "job 写入失败：%s: %s" % (type(exc).__name__, exc)}
    _log(cg, {"action": "submit", "job_id": job_id, "role": role, "model": mdl,
              "timeout_s": int(timeout_s), "actor": actor, "prompt_head": str(prompt)[:200]})
    return {"ok": True, "job_id": job_id, "job_dir": d, "spec": spec,
            "unit_role": role, "model": mdl}


def poll(job_id: str, jobs: str = "") -> dict:
    """读 job 终态视图：**以 result.json 出现为终态主判据**，status.json 仅作辅助。"""
    d = os.path.join(jobs_dir(jobs), str(job_id or ""))
    out = {"job_id": job_id, "job_dir": d, "state": "missing", "terminal": False,
           "ok": False, "content": None, "error": None, "status": None}
    if not os.path.isdir(d):
        out["error"] = "job 目录不存在：%s" % d
        return out
    sp = os.path.join(d, STATUS_FILE)
    if os.path.isfile(sp):
        try:
            with open(sp, encoding="utf-8") as f:
                out["status"] = json.load(f)
        except (OSError, ValueError):
            out["status"] = None
    st = (out["status"] or {}).get("state")
    if st:
        out.update({"state": st, "terminal": st in TERMINAL_STATES})
    rp = os.path.join(d, RESULT_FILE)
    if os.path.isfile(rp):
        out["state"] = st or "done"
        out["terminal"] = True
        try:
            with open(rp, encoding="utf-8") as f:
                res = json.load(f)
        except (OSError, ValueError) as exc:
            out["error"] = "result.json 不可读：%s" % type(exc).__name__
            return out
        if isinstance(res, dict):
            out["ok"] = bool(res.get("ok"))
            out["content"] = res.get("content")
            out["error"] = res.get("error") or out["error"]
            out["usage"] = res.get("usage")
            out["model"] = res.get("model")
        else:
            out["ok"], out["content"] = True, res
    return out


def wait(job_id: str, *, jobs: str = "", timeout_s: float = DEFAULT_TIMEOUT_S,
         poll_s: float = DEFAULT_POLL_S) -> dict:
    """阻塞等终态；超时如实返回（不假装成功、不强杀 job）。"""
    t0 = time.time()
    while True:
        cur = poll(job_id, jobs)
        if cur.get("terminal"):
            cur["waited_s"] = round(time.time() - t0, 3)
            return cur
        if (time.time() - t0) >= float(timeout_s):
            cur.update({"terminal": False, "timeout": True, "waited_s": round(time.time() - t0, 3),
                        "error": "等待超时 %.0fs（job 仍在 %s）" % (float(timeout_s),
                                                                  cur.get("state"))})
            return cur
        time.sleep(float(poll_s))


def run(*, prompt: str, role: str = REFLECT, cg=None, actor: str = "",
        wait_s: float = DEFAULT_TIMEOUT_S, **kw) -> dict:
    """submit + wait 组合（阻塞式复核，MCP action=review 主路径）。"""
    sub = submit(prompt=prompt, role=role, cg=cg, actor=actor, **kw)
    if not sub.get("ok"):
        return {"ok": False, "stage": "submit", "error": sub.get("error"), **sub}
    res = wait(sub["job_id"], jobs=kw.get("jobs", ""), timeout_s=wait_s)
    res.update({"stage": "wait", "job_id": sub["job_id"], "unit_role": role,
                "model": sub.get("model")})
    res["ok"] = bool(res.get("ok")) and bool(res.get("content"))
    return res


# ---------------------------------------------------------------- 裁决解析与搬运

_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)


def _json_of(raw):
    """从单元输出抽第一个 JSON 对象/数组（容忍 ```json 围栏与前后噪声）。"""
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    cands = []
    m = _FENCE_RE.search(text)
    if m:
        cands.append(m.group(1))
    cands.append(text)
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if 0 <= i < j:
            cands.append(text[i:j + 1])
    for c in cands:
        try:
            v = json.loads(c)
        except ValueError:
            continue
        if isinstance(v, (dict, list)):
            return v
    return None


def verdict_of(raw) -> dict:
    """单元输出 → 裁决四态；解析不出 → DEFER（不猜测、不当通过）。"""
    data = _json_of(raw)
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else None
    if not isinstance(data, dict):
        return {"verdict": DEFER, "reason": "单元输出无法解析为裁决 JSON",
                "slot_corrections": {}, "raw": str(raw)[:500], "parsed": False}
    word = str(data.get("verdict") or data.get("decision") or data.get("state")
               or data.get("result") or "").strip().lower()
    reason = str(data.get("reason") or data.get("why") or data.get("detail") or "").strip()
    corr = data.get("slot_corrections") or data.get("corrections") or {}
    corr = corr if isinstance(corr, dict) else {}
    got = _VERDICT_MAP.get(word)
    if got is None:
        return {"verdict": DEFER, "slot_corrections": corr, "parsed": True, "raw": str(raw)[:500],
                "reason": "单元未给出可识别的裁决（%r）%s" % (word, ("：" + reason) if reason else "")}
    return {"verdict": got, "reason": reason, "slot_corrections": corr,
            "checks": data.get("checks"), "raw": str(raw)[:500], "parsed": True}


def transport_name(state: str, role: str, job_id: str = "", channel: str = "") -> str:
    """裁决来源标识：**结构上不可能等于编译者**，保证 A 裁定「不得自证」不被误伤。"""
    if state == HIVE:
        return "hive:%s:%s" % (role, job_id or "unknown")
    if state == SUBAGENT:
        return "subagent:%s:%s" % (role, channel or "harness")
    return ""


def to_attest_args(unit: dict, *, state: str = "", role: str = REFLECT, job_id: str = "",
                   channel: str = "", compiled_by: str = "") -> dict:
    """单元裁决 → ccgc.attest(...) 入参（纯函数，离线可测）。

    诚实边界：只做搬运与命名；裁决正确性由外部单元负责，本模块不为其背书。
    """
    unit = unit or {}
    verdict = unit.get("verdict") or DEFER
    verifier = transport_name(state, role, job_id, channel)
    evidence = str(unit.get("reason") or "")
    if unit.get("raw") and not evidence:
        evidence = str(unit["raw"])[:300]
    if job_id:
        evidence = "%s（job=%s）" % (evidence, job_id)
    args = {"verdict": verdict, "verifier": verifier, "evidence": evidence}
    if unit.get("slot_corrections"):
        args["slot_corrections"] = unit["slot_corrections"]
    if compiled_by and verifier and verifier == compiled_by:
        args["self_verify"] = True
    return args


# ---------------------------------------------------------------- 复核请求包

_REFLECT_TPL = """你是认知图记忆节点的**反思单元**（reflect）。下面是一份由 ccgc 编译出的
CCG 六要素候选（功能名/生效条件/子功能/执行/验证方式/不适用条件）。请逐项反思：

1) 六要素是否齐备，是否都能在「对话记录」里找到字面依据；
2) 「生效条件」四槽（场景/时窗/对象/前置）是否与实际适用范围一致，有无过度泛化；
3) 「不适用条件」（拒绝域）是否漏掉了明显该拒的情形；
4) 若有问题，给出**最小修正**（只改该字段，不重写）。

编译产物（JSON）：
{digest}

原始对话记录（真源，引用必须出自此处）：
{dialog}

只输出一个 JSON 对象，不要任何解释文字：
{{"verdict":"accept|drop|defer","reason":"一句话依据","slot_corrections":{{}},
  "checks":[{{"element":"功能名","ok":true,"note":""}}]}}"""

_VERIFY_TPL = """你是独立**验证单元**（verify）。对下面这份 CCG 六要素候选与反思单元的结论
逐条复核：来源是否真实可追溯、结论是否被对话记录支持、修正是否越权（不得新增事实）。

**你只能否决或存疑，不得新增主张、不得改写事实**（可给出 slot_corrections 修正已有槽位）。

候选（JSON）：
{digest}

反思单元结论：
{reflect_rows}

对话记录（真源）：
{dialog}

只输出一个 JSON 对象：
{{"verdict":"accept|drop|defer","reason":"一句话依据","slot_corrections":{{}}}}"""


def _digest_of(digest) -> str:
    if digest is None:
        return "{}"
    if isinstance(digest, str):
        return digest
    for attr in ("to_dict", "as_dict"):
        fn = getattr(digest, attr, None)
        if callable(fn):
            try:
                return json.dumps(fn(), ensure_ascii=False, indent=1)
            except Exception:                                     # noqa: BLE001
                break
    if isinstance(digest, dict):
        return json.dumps(digest, ensure_ascii=False, indent=1)
    return json.dumps({k: v for k, v in vars(digest).items() if not k.startswith("_")},
                      ensure_ascii=False, indent=1, default=str)


def prompt_for(role: str, digest=None, *, dialog: str = "", reflect_rows="") -> str:
    """按角色生成复核请求包正文（reflect/verify 共用一处模板真源）。"""
    tpl = _VERIFY_TPL if role == VERIFY else _REFLECT_TPL
    rows = reflect_rows if isinstance(reflect_rows, str) else json.dumps(
        reflect_rows or [], ensure_ascii=False, indent=1)
    return tpl.format(digest=_digest_of(digest), dialog=str(dialog or "（未提供）")[:6000],
                      reflect_rows=rows[:3000])


def review(*, prompt: str = "", role: str = REFLECT, digest=None, dialog: str = "",
           reflect_rows="", node_id: str = "", jobs: str = "", model: str = "",
           timeout_s: int = DEFAULT_TIMEOUT_S, allow_degrade: bool = False,
           channel: str = "", wait_s: float = DEFAULT_TIMEOUT_S, blocking: bool = True,
           cg=None, actor: str = "", autostart: bool = False) -> dict:
    """复核主入口：**蜂巢优先 → 提示配置 → 端子代理降级**（三态各自如实返回）。

    返回统一形态：{state, role, node_id, transport, unit, attest, prompt, job_id, hint}
    - state=hive     ：已派发；blocking=True 时等终态并给出 unit/attest；否则只给 job_id
    - state=configure：**未派发**，hint 为配置指引（使用者裁定：不可用即提示配置）
    - state=subagent ：**未派发**，返回 prompt 包供宿主子代理执行并回填
    """
    text = prompt or prompt_for(role, digest, dialog=dialog, reflect_rows=reflect_rows)
    pr = probe(jobs, model, allow_degrade=allow_degrade, channel=channel)
    base = {"role": role, "node_id": node_id, "prompt": text,
            "transport": None, "unit": None, "attest": None,
            "job_id": None, "hint": pr.get("hint") or "", "channel": pr.get("channel") or "",
            "degrade": {"channel": channel or "harness-subagent",
                        "how": "宿主子代理执行 prompt → 裁决经 verdicts 回填 attest"}}
    if pr["state"] == SUBAGENT:
        return {"state": SUBAGENT, **base,
                "degrade": {"available": True, "channel": channel or "harness-subagent",
                            "how": "把 prompt 交给宿主子代理，取其 JSON 裁决后调 "
                                   "cg(op=ccg, action=attest, verdict=<accept|drop|defer>, "
                                   "verifier=subagent:<role>:<channel>)"}}
    if pr["state"] == CONFIGURE:
        return {"state": CONFIGURE, **base,
                "degrade": {"available": True, "channel": channel or "harness-subagent",
                            "how": "① 按 hint 配置蜂巢后重试；② 或带 allow_degrade=true 降级子代理"}}
    if autostart and not serve_state(jobs)["alive"]:
        pr["autostart"] = autostart_serve(jobs)
    sub = submit(prompt=text, role=role, jobs=jobs, model=model, timeout_s=timeout_s,
                 cg=cg, actor=actor)
    if not sub.get("ok"):
        return {"state": CONFIGURE, **base, "hint": (pr.get("hint") or "") + "\n" + str(sub.get("error"))}
    out = {"state": HIVE, **base, "job_id": sub["job_id"], "unit_role": role,
           "model": sub.get("model")}
    if not blocking:
        return out
    res = wait(sub["job_id"], jobs=jobs, timeout_s=wait_s)
    unit = verdict_of(res.get("content")) if res.get("ok") else {
        "verdict": DEFER, "reason": res.get("error") or "单元未返回可用结果",
        "slot_corrections": {}, "parsed": False}
    out["unit"] = unit
    out["transport"] = transport_name(HIVE, role, sub["job_id"])
    out["attest"] = to_attest_args(unit, state=HIVE, role=role, job_id=sub["job_id"])
    out["result_ok"] = bool(res.get("ok"))
    out["waited_s"] = res.get("waited_s")
    if not res.get("ok"):
        out["hint"] = "蜂巢 job 未产出有效结果：%s（裁决按 DEFER 处理，未假装通过）" % res.get("error")
    _log(cg, {"action": "review", "job_id": sub["job_id"], "role": role,
              "node_id": node_id, "actor": actor, "unit_verdict": unit.get("verdict"),
              "result_ok": bool(res.get("ok"))})
    return out


# ---------------------------------------------------------------- serve 拉起（显式）

def autostart_serve(jobs: str = "", wait_s: float = 5.0) -> dict:
    """**显式**拉起 serve（默认不启用；使用者裁定：不可用即提示配置）。

    形态同 hive_mcp._ensure_serve：detached + 独立日志，不阻塞调用方。
    """
    jd = jobs_dir(jobs)
    if serve_state(jd)["alive"]:
        return {"started": False, "note": "serve 存活"}
    exe = exe_path()
    if not os.path.isfile(exe):
        return {"started": False, "note": "未找到可执行文件 %s——先 cargo build --release" % exe}
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    try:
        os.makedirs(jd, exist_ok=True)
        with open(os.path.join(jd, "_serve.log"), "ab") as logf:
            subprocess.Popen([exe, "serve", "--jobs", jd], stdout=logf, stderr=logf,
                             stdin=subprocess.DEVNULL, **kwargs)
    except OSError as exc:
        return {"started": False, "note": "拉起失败：%s: %s" % (type(exc).__name__, exc)}
    t0 = time.time()
    while time.time() - t0 < float(wait_s):
        if serve_state(jd)["alive"]:
            return {"started": True, "note": "serve 已拉起"}
        time.sleep(0.1)
    return {"started": True, "note": "serve 已拉起（心跳未就绪，稍后自愈）"}


def doctor(jobs: str = "") -> dict:
    """能力体检（形态对齐 hive_doctor）：判活 + exe + 模型 + 优先级链。"""
    jd = jobs_dir(jobs)
    p = plan(jobs)
    return {"ok": p["state"] == HIVE, "state": p["state"], "jobs_dir": jd,
            "serve_alive": p["serve"]["alive"], "serve_age_s": p["serve"]["age_s"],
            "exe_found": os.path.isfile(exe_path()), "exe_path": exe_path(),
            "model_set": bool(model_name()), "model": p["model"],
            "api_key_set": bool(os.environ.get(ENV_API_KEY)),
            "env": {"HIVE_JOBS_DIR": os.environ.get(ENV_JOBS_DIR, ""),
                    "MDCG_UNIT_MODEL": os.environ.get(ENV_MODEL, "")},
            "chain": p["chain"], "hint": p["hint"]}
