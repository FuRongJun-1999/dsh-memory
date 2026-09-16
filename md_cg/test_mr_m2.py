# -*- coding: utf-8 -*-
"""M2 蜂巢并发自测：级 4 spec 构造/投递/收卷 + 级 5 意见落库（零直写 / 自验禁止）。

真源：docs/记忆评审系统_立项设计与施工交接_20260915.md §5（spec/result 契约）
      §7（反面清单：评审不改知识层 / 意见必过 verify 令牌 / 不确定 DEFER）。

纪律（同 test_mr_m1.py）：
  · **自备数据源**——主测面 = tempfile 合成库 + 仓内 hive release 二进制；
    hive 不存在即 SKIP（外部 clone 下同样全绿），不依赖真源库。
  · **零 LLM**——用确定性假执行器占位 HIVE_EXEC_PY，验证的是并发/文件协议/
    解析/落库全链路，不是模型质量（模型质量属 M3 定位与 M4 治理的评测面）。
  · **零直写实锤**——dry_run 批量跑后认知图指纹逐字节不变。

覆盖：A spec 构造  B 意见解析与格式校验（100% 口径）  C 落库通道与结构性拒绝
      D 真蜂巢端到端（1 包 + 10 包×50 条）  E 边界与负例

运行：python -m md_cg.test_mr_m2
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

from . import conformance as CF
from . import crosscheck as CC
from . import mdcos
from . import tokens as TK
from .mreview import bundle as BD
from .mreview import candidates as CD
from .mreview import pipeline as PL
from .mreview import ruleset as RS

PASS = FAIL = SKIP = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print("  FAIL %s" % label)


def skip(label):
    global SKIP
    SKIP += 1
    print("  SKIP %s" % label)


# ---------------------------- 合成库 ----------------------------

def node(nid, layer="knowledge", **kw):
    rec = {"id": nid, "layer": layer, "path": "%s/%s.md" % (layer, nid),
           "content": "内容 %s" % nid, "content_hash": "hash_%s" % nid, "tags": []}
    rec.update(kw)
    return rec


def mkroot(root, nodes, *, access=(), write_files=True):
    """合成认知图根：索引 + 闸门三日志 + 节点盘文件（M1 同构，独立实现）。"""
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "_index.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes}, f, ensure_ascii=False)
    hp = os.path.join(root, "hippocampus")
    os.makedirs(hp, exist_ok=True)
    for name in ("inbox.jsonl", "decisions.jsonl"):
        with open(os.path.join(hp, name), "w", encoding="utf-8") as f:
            f.write("")
    with open(os.path.join(root, CF.ACCESS_LOG), "w", encoding="utf-8") as f:
        for r in access:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(root, CD.FORGET_LOG), "w", encoding="utf-8") as f:
        f.write("")
    if write_files:
        for r in nodes.values():
            if not r.get("path"):
                continue
            p = os.path.join(root, r["path"])
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(r.get("content", ""))
    return root


VOLATILE_DIRS = ("_index_log",)


def snapshot(root, *, exclude_dirs=()):
    ex = set(exclude_dirs)
    out = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in ex]
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = hashlib.md5(f.read()).hexdigest()
    return out


def _diff(before, after):
    ch = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return "改=%s 增=%s 删=%s" % (ch[:5], sorted(set(after) - set(before))[:5],
                                sorted(set(before) - set(after))[:5])


# ---------------------------- 语料与包 ----------------------------

def pkg_of(n, *, kind="batch", key="g", bid="bM2", layer="knowledge", kinds=()):
    """手工包（与 bundle 输出同形；M2 测的是 spec/收卷/落库，不走候选生成）。"""
    ents = []
    for i in range(n):
        nid = "n%02d" % i
        ents.append({"ref": nid, "node_id": nid, "proposal_id": None,
                     "origin": "assertion", "layer": layer,
                     "tags": ["doc:note"], "role": "knowledge-card",
                     "importance": 0.5, "evidence_count": 1 + (i % 3),
                     "verification_basis": "test" if i % 2 else "",
                     "lifecycle_state": "active", "content_hash": "h_%s" % nid,
                     "issue_kinds": list(kinds) if i % 3 == 0 else [],
                     "evidence": [], "excerpt": "正文摘录 %s" % nid})
    return {"bundle_id": bid, "group_kind": kind, "group_key": key,
            "group_sig_kind": "tmpl", "size": n, "refs": [e["ref"] for e in ents],
            "entries": ents}


def asm_of(pkg, *, mech=(), llm=()):
    return {"bundle_id": pkg["bundle_id"], "group_kind": pkg["group_kind"],
            "group_key": pkg["group_key"], "size": pkg["size"],
            "matched": [], "mechanical": list(mech), "llm": list(llm),
            "mechanical_by_kind": {}, "mechanical_flagged": 0}


# ---------------------------- 假执行器 ----------------------------

#: 确定性假执行器：读 spec.json/context → 写 result.json（零 LLM，零网络）。
#: 三种模式（FAKE_MODE）全部用来打 M2 的判据，不掺模型质量。
FAKE_EXEC = r'''# -*- coding: utf-8 -*-
import json, os, sys

job = sys.argv[1]
with open(os.path.join(job, "spec.json"), encoding="utf-8") as f:
    spec = json.load(f)
bundle = {}
for p in (spec.get("context_files") or []):
    if str(p).endswith(".bundle.json"):
        with open(p, encoding="utf-8") as f:
            bundle = json.load(f)
        break
ents = bundle.get("entries") or []
mode = os.environ.get("FAKE_MODE", "ok")
verdicts = []
for e in ents:
    nid = e.get("node_id")
    kinds = e.get("issue_kinds") or []
    if mode == "bad":
        verdicts.append({"node_id": nid, "verdict": "MAYBE"})
    elif mode == "textform":
        verdicts.append({"node_id": nid, "verdict": "DEFER",
                         "reason": "条件不足，无法确认"})
    elif kinds:
        verdicts.append({"node_id": nid, "verdict": "REJECT",
                         "reason": "来源许可不足（机械层已标注）",
                         "evidence": ",".join(kinds)})
    else:
        verdicts.append({"node_id": nid, "verdict": "ACCEPT",
                         "reason": "机械层无命中，既有基底足以确认适用"})
payload = {"verdicts": verdicts, "summary": "fake:" + mode}
if mode == "textform":
    out = {"ok": True, "content": "```json\n" + json.dumps(payload) + "\n```"}
else:
    out = {"ok": True, "verdicts": payload["verdicts"], "summary": payload["summary"]}
with open(os.path.join(job, "result.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
'''


def write_fake(root):
    os.makedirs(root, exist_ok=True)
    p = os.path.join(root, "fake_exec.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write(FAKE_EXEC)
    return p


# 合规规则库（本测自备，与生产同形态——由部署侧经 MDCG_POLICY_FILE 配置）。
# 根因（第4条取证）：audit._verify_text → _rule_check 在**无规则**时返回 DEFER
# （「无规则不能假装合规」），故规则库缺失会让**每一条**意见转审核队列而落不了盘。
# 这里不是凑空规则（空规则 == 无规则 == 仍 DEFER），而是给出真实判据：
#   forbidden = 机密外泄形态（意见正文绝不应出现）
#   required  = 四要素必须齐（意见正文的核心结构）
POLICY = {"forbidden": [r"(?i)(password|secret|api[_-]?key)\s*[=:]"],
          "required": [r"【内容】", r"【原因】", r"【位置】", r"【验证】"]}


def write_policy(root):
    os.makedirs(root, exist_ok=True)
    p = os.path.join(root, "policy.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(POLICY, f, ensure_ascii=False)
    return p


# ---------------------------- A 组：spec 构造 ----------------------------

def phase_a(tmp):
    print("[A] spec 构造")
    pkg = pkg_of(6, kinds=("weak_source",))
    asm = asm_of(pkg, mech=[{"issue_kind": "weak_source", "ref": "n00",
                             "detail": "verification_basis 为空"}],
                 llm=[{"rule_id": "R-TEMPLATE-FLOW", "check": "template_flow_digits_only",
                       "question": "正文是否只有编号差异？"}])
    ctx_dir = os.path.join(tmp, "ctx_a")
    files = PL.dump_context(pkg, asm, ctx_dir)

    ok(len(files) == 2 and all(os.path.isabs(p) for p in files),
       "A1 dump_context 产两文件且为绝对路径")
    ok(all(os.path.isfile(p) for p in files), "A2 context 文件已落盘")
    back = {}
    for p in files:
        with open(p, encoding="utf-8") as f:
            back[os.path.basename(p)] = json.load(f)
    b1 = [v for k, v in back.items() if k.endswith(".bundle.json")][0]
    r1 = [v for k, v in back.items() if k.endswith(".rules.json")][0]
    ok([e["node_id"] for e in b1["entries"]] == [e["node_id"] for e in pkg["entries"]],
       "A3 context 内节点清单与包一致")
    ok(r1.get("mechanical_by_kind") is not None or "mechanical" in r1,
       "A4 context 内含规则装配结果")

    spec = PL.build_spec(pkg, asm, context_files=files)
    need = {"model", "system_prompt", "user_prompt", "context_files", "timeout_s"}
    ok(need <= set(spec), "A5 spec 契约字段齐备（实得 %s）" % sorted(spec))
    ok(spec["context_files"] == files, "A6 spec.context_files 指向 context 文件")
    ok(all(e["node_id"] in spec["user_prompt"] for e in pkg["entries"]),
       "A7 user_prompt 含全部 node_id（工人不必猜）")
    ok("weak_source" in spec["user_prompt"], "A8 user_prompt 含机械命中")
    ok("R-TEMPLATE-FLOW" in spec["user_prompt"], "A9 user_prompt 含待检问题")
    ok(spec["meta"]["bundle_id"] == pkg["bundle_id"]
       and spec["meta"]["node_ids"] == [e["node_id"] for e in pkg["entries"]],
       "A10 meta 归因信息与包对齐（收卷配对用）")
    ok("不改写任何记忆" in spec["system_prompt"]
       and "DEFER" in spec["system_prompt"],
       "A11 系统提示显式声明零写纪律与不确定即 DEFER")
    ok(spec["temperature"] == 0.0, "A12 默认温度 0（评审要可复现）")


# ---------------------------- B 组：解析与格式校验 ----------------------------

def phase_b(tmp):
    print("[B] 意见解析与格式校验")
    nids = {"n%02d" % i for i in range(4)}

    direct = {"ok": True, "verdicts": [{"node_id": "n00", "verdict": "ACCEPT",
                                        "reason": "r"}], "summary": "s"}
    p1 = PL.parse_opinions(direct)
    ok(p1["ok"] and p1["verdicts"][0]["node_id"] == "n00", "B1 收直写形态 verdicts")

    txt = {"ok": True, "content": "前言\n```json\n%s\n```\n后记"
           % json.dumps({"verdicts": [{"node_id": "n01", "verdict": "DEFER",
                                       "reason": "r"}], "summary": "t"})}
    p2 = PL.parse_opinions(txt)
    ok(p2["ok"] and p2["verdicts"][0]["node_id"] == "n01",
       "B2 收 content 文本形态（```json 围栏）")

    p3 = PL.parse_opinions({"ok": True, "content": "模型啥也没说"})
    ok(not p3["ok"] and "解析" in p3["error"], "B3 垃圾文本 → ok=False 不炸")
    p4 = PL.parse_opinions({"ok": True, "error": "api 超时"})
    ok(not p4["ok"] and "超时" in p4["error"], "B4 工人报错原样透出")

    ok(PL.validate_opinion({"node_id": "n00", "verdict": "accept",
                            "reason": "r"}, nids) is None, "B5 合法意见通过（含小写归一）")
    ok(PL.validate_opinion({"verdict": "ACCEPT", "reason": "r"}, nids) is not None,
       "B6 缺 node_id 被拒")
    ok(PL.validate_opinion({"node_id": "n00", "verdict": "MAYBE", "reason": "r"},
                           nids) is not None, "B7 verdict 越界被拒")
    ok(PL.validate_opinion({"node_id": "n00", "verdict": "ACCEPT"}, nids) is not None,
       "B8 缺 reason 被拒")
    ok(PL.validate_opinion({"node_id": "n00", "verdict": "REJECT", "reason": "r"},
                           nids) is not None, "B9 REJECT 缺 evidence 被拒")
    ok(PL.validate_opinion({"node_id": "zzz", "verdict": "ACCEPT", "reason": "r"},
                           nids) is not None, "B10 node_id 越出本包被拒")

    good = {"node_id": "n00", "verdict": "ACCEPT", "reason": "r"}
    bad = {"node_id": "n01", "verdict": "??", "reason": "r"}
    v = PL.validate_opinions([good, bad, dict(good, node_id="n02")], nids)
    ok(v["total"] == 3 and len(v["valid"]) == 2 and len(v["invalid"]) == 1,
       "B11 混合批量 → valid/invalid 分流正确")
    ok(abs(v["pass_rate"] - 2.0 / 3) < 1e-9, "B12 pass_rate 口径 = valid/total")
    ok(not v["ok"], "B13 有非法即整体 ok=False（不确定即 DEFER，不静默放行）")
    ok(PL.validate_opinions([], nids)["pass_rate"] == 1.0,
       "B14 空集 pass_rate=1.0（分母零的显式约定）")


# ---------------------------- C 组：落库通道 ----------------------------

def _ops():
    return [{"node_id": "n00", "verdict": "ACCEPT", "reason": "机械层无命中"},
            {"node_id": "n01", "verdict": "REJECT", "reason": "来源许可不足",
             "evidence": "verification_basis 为空且无外部佐证"},
            {"node_id": "n02", "verdict": "DEFER", "reason": "条件不足，无法确认"}]


def phase_c(tmp):
    print("[C] 落库通道（verify 令牌 + 结构性拒绝）")
    root = mkroot(os.path.join(tmp, "cgc"), {"k1": node("k1")})
    cg = mdcos.MdCGSecure(root, principal=PL.verifier_principal(actor="applier"))
    pkg = pkg_of(3)

    # C1-C3 自验违例：产出意见者 == 落库裁决者
    before = snapshot(root, exclude_dirs=VOLATILE_DIRS)
    r1 = PL.apply_opinions(cg, pkg, _ops(), reviewer="same-actor",
                           applier="same-actor")
    ok(bool(r1.get("refused")) and r1.get("reason") == "self_verify_disallowed",
       "C1 评审者==落库者 → 自验违例拒绝（实得 %s）" % r1.get("reason"))
    ok(not r1.get("committed"), "C2 自验违例未落库")
    ok(snapshot(root, exclude_dirs=VOLATILE_DIRS) == before,
       "C3 自验违例零写入（认知图指纹不变）")

    # C4-C6 正常落库（verify 令牌 → writepipe 六道闸 → contextual）
    r2 = PL.apply_opinions(cg, pkg, _ops(), reviewer="mreview-worker",
                           applier="mreview-applier", summary="整包结论：1 拒 1 缓")
    moved = (r2.get("response") or {}).get("moved_to")
    ok(r2.get("committed") is True,
       "C4 意见落库 committed=True（实得 committed=%s moved_to=%s detail=%s）"
       % (r2.get("committed"), moved, (r2.get("detail") or "")[:120]))
    ok(r2.get("layer") == PL.OPINION_LAYER == "contextual",
       "C5 落层 = contextual（非知识层）")
    p_node = os.path.join(root, "contextual", str(r2.get("node_id")) + ".md")
    ok(os.path.isfile(p_node), "C6 意见节点已落盘（%s）" % os.path.relpath(p_node, root))
    if os.path.isfile(p_node):
        with open(p_node, encoding="utf-8") as f:
            doc = f.read()
        ok("ACCEPT 1" in doc and "REJECT 1" in doc and "DEFER 1" in doc,
           "C7 正文含裁决分布（四态计数）")
        ok("verification_basis 为空且无外部佐证" in doc, "C8 正文含逐条理由与证据")
        ok("【内容】" in doc and "【位置】" in doc, "C9 正文含四要素")

    # C10 空意见 → 零噪声不落库
    r3 = PL.apply_opinions(cg, pkg, [], reviewer="w", applier="a")
    ok(r3.get("ok") and r3.get("skipped") and not r3.get("committed"),
       "C10 无有效意见 → skipped 不落库（零噪声）")

    # C4b 合规规则库缺失 → 合规闸 DEFER → 转审核队列（诚实降级，不假装落库）
    _saved = os.environ.pop("MDCG_POLICY_FILE", None)
    try:
        r3b = PL.apply_opinions(cg, pkg, _ops(), reviewer="w", applier="a",
                                node_id="mr_opinion_nopolicy")
        ok(not r3b.get("committed") and r3b.get("moved_to") == "review_queue"
           and r3b.get("deferred") is True,
           "C4b 无规则库 → 转审核队列而非落盘（moved_to=%s deferred=%s）"
           % (r3b.get("moved_to"), r3b.get("deferred")))
    finally:
        if _saved is not None:
            os.environ["MDCG_POLICY_FILE"] = _saved

    # C11 越层写入：knowledge 被库层结构性拒绝（§7 反面清单第 1 条）
    r4 = PL.apply_opinions(cg, pkg, _ops(), reviewer="w", applier="a",
                           layer="knowledge")
    ok(bool(r4.get("refused")) and r4.get("reason") == "layer_denied",
       "C11 写 knowledge 层被拒（实得 refused=%s reason=%s）"
       % (r4.get("refused"), r4.get("reason")))
    ok(not os.path.isfile(os.path.join(root, "knowledge", str(r4.get("node_id")) + ".md")),
       "C12 越层写入确未落盘")

    # C13 非法条目被剔除、合法条目照落（不因个别越界全盘丢弃）
    mixed = [{"node_id": "n00", "verdict": "ACCEPT", "reason": "r"},
             {"node_id": "ghost", "verdict": "ACCEPT", "reason": "越包"}]
    nids = {e["node_id"] for e in pkg["entries"]}
    val = PL.validate_opinions(mixed, nids)
    r5 = PL.apply_opinions(cg, pkg, val["valid"], reviewer="w", applier="a",
                           node_id="mr_opinion_mixed", invalid=val["invalid"])
    ok(len(val["valid"]) == 1 and len(val["invalid"]) == 1,
       "C13 越包条目被剔除（1 留 1 剔）")
    ok(r5.get("committed"), "C14 剔除后合法条目照常落库")
    p5 = os.path.join(root, "contextual", "mr_opinion_mixed.md")
    if os.path.isfile(p5):
        with open(p5, encoding="utf-8") as f:
            ok("未落库条目" in f.read(), "C15 正文留痕被剔除条目（可审计）")
    else:
        ok(False, "C15 正文留痕被剔除条目（文件缺失）")

    # C16 dry_run 不写盘
    before2 = snapshot(root, exclude_dirs=VOLATILE_DIRS)
    r6 = PL.apply_opinions(cg, pkg, _ops(), reviewer="w", applier="a",
                           dry_run=True)
    ok(r6.get("dry_run") and not r6.get("committed"), "C16 dry_run 返回标记")
    ok(snapshot(root, exclude_dirs=VOLATILE_DIRS) == before2, "C17 dry_run 零写入")


# ---------------------------- D 组：真蜂巢端到端 ----------------------------

def _start_serve(exe, jobs, fake, workers=2, timeout=25.0, env_extra=None):
    """拉起独立 serve（独立 jobs 目录 + 假执行器，隔离生产 serve）。

    env_extra：额外的 **serve 级**环境（如 FAKE_MODE）。执行器子进程继承 serve
    环境（hive 以 Command::new 启动 exec.py，未 env_clear），故 serve 级注入对
    工人可见；但也因此环境在 serve 启动时即固定——换模式须另起一个 serve。
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["HIVE_EXEC_PY"] = fake
    for _k, _v in (env_extra or {}).items():
        env[str(_k)] = str(_v)
    p = subprocess.Popen([exe, "serve", "--jobs", jobs, "--workers", str(workers)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", env=env)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.isfile(os.path.join(jobs, "_serve.json")):
            time.sleep(0.4)
            return p, True
        if p.poll() is not None:
            return p, False
        time.sleep(0.3)
    return p, False


def _stop_serve(p):
    try:
        p.terminate()
        p.wait(timeout=8)
    except Exception:                                   # noqa: BLE001
        try:
            p.kill()
        except Exception:                               # noqa: BLE001
            pass


def phase_d(tmp, exe):
    print("[D] 真蜂巢端到端")
    if not os.path.isfile(exe):
        skip("hive 二进制不存在（%s）→ D 组跳过（外部 clone 同此路径）" % exe)
        return
    base = os.path.join(tmp, "d")
    jobs = os.path.join(base, "jobs")
    ctx = os.path.join(base, "ctx")
    fake = write_fake(base)
    os.makedirs(base, exist_ok=True)

    nodes = {"n%02d" % i: node("n%02d" % i) for i in range(50)}
    root = mkroot(os.path.join(base, "cg"), nodes)
    cg = mdcos.MdCGSecure(root, principal=PL.verifier_principal(actor="applier"))
    pkg = pkg_of(50, kinds=("weak_source",))
    asm = asm_of(pkg, mech=[{"issue_kind": "weak_source", "ref": "n00",
                             "detail": "verification_basis 为空"}])

    p, ready = _start_serve(exe, jobs, fake)
    ok(ready, "D0 独立 serve 就绪（jobs=%s）" % os.path.relpath(jobs, tmp))
    if not ready:
        _stop_serve(p)
        return
    try:
        # D1 单包全链路
        one = PL.run_package(pkg=pkg, asm=asm, cg=cg, exe=exe, jobs_dir=jobs,
                             ctx_dir=ctx, reviewer="mreview-worker",
                             applier="mreview-applier", timeout_s=120,
                             interval_s=0.3)
        ok(one.get("ok"), "D1 单包 run_package 全链路 ok（stage=%s bundle=%s）"
           % (one.get("stage"), one.get("error") or "-"))
        ok(one.get("pass_rate") == 1.0, "D2 单包意见格式校验 100%%（实得 %s）"
           % one.get("pass_rate"))
        ok((one.get("apply") or {}).get("committed"), "D3 单包意见落库 committed")

        # D4 零直写实锤：dry_run 批量 10 包（50 条/包）→ 认知图指纹不变
        pairs = [(pkg_of(50, bid="b%02d" % i, key="g%02d" % i,
                         kinds=("weak_source",)),
                  asm_of(pkg_of(50, bid="b%02d" % i, key="g%02d" % i))) 
                 for i in range(10)]
        before = snapshot(root, exclude_dirs=VOLATILE_DIRS)
        rep = PL.run_batch(pairs=pairs, cg=cg, exe=exe, jobs_dir=jobs, ctx_dir=ctx,
                           reviewer="mreview-worker", applier="mreview-applier",
                           timeout_s=300, interval_s=0.3, dry_run=True)
        ok(rep["jobs"] == 10 and rep["done"] == 10,
           "D4 10 包并发投递全部 done（jobs=%s done=%s failed=%s）"
           % (rep["jobs"], rep["done"], rep["failed"]))
        ok(rep["pass_rate"] == 1.0,
           "D5 10 包×50 条意见格式校验 100%%（实得 %s，invalid=%s）"
           % (rep["pass_rate"], rep["invalid"]))
        ok(rep["opinions"] == 500,
           "D6 意见条数 == 10×50（实得 %s）" % rep["opinions"])
        ok(snapshot(root, exclude_dirs=VOLATILE_DIRS) == before,
           "D7 worker 零直写：dry_run 批量后认知图指纹逐字节不变")

        # D8 实际落库：仅新增意见节点
        _ctxdir = os.path.join(root, "contextual")
        n_before = (len([f for f in os.listdir(_ctxdir) if f.endswith(".md")])
                    if os.path.isdir(_ctxdir) else 0)
        rep2 = PL.run_batch(pairs=pairs[:3], cg=cg, exe=exe, jobs_dir=jobs,
                            ctx_dir=ctx, reviewer="mreview-worker",
                            applier="mreview-applier", timeout_s=300,
                            interval_s=0.3, dry_run=False)
        n_after = len([f for f in os.listdir(_ctxdir) if f.endswith(".md")])
        ok(rep2["committed"] == 3,
           "D8 3 包实际落库 committed==3（实得 %s）" % rep2["committed"])
        ok(n_after - n_before == 3,
           "D9 认知图仅新增 3 个意见节点（%s→%s）" % (n_before, n_after))
        ok(not os.path.isdir(os.path.join(root, "knowledge"))
           or len([f for f in os.listdir(os.path.join(root, "knowledge"))]) == 50,
           "D10 knowledge 层节点数不变（评审不改知识层）")

        # D11 非法意见（verdict 越界）→ 全数拦截，不落库。
        # 执行器模式是 **serve 级**配置（HIVE_EXEC_PY 与 FAKE_MODE 在 serve 启动
        # 时固定），故反例另起一个独立 serve（独立 jobs + FAKE_MODE=bad），
        # 用完即停——与主 serve 互不干扰，也不碰生产 serve。
        bad_pkg = pkg_of(4, bid="bbad", key="gb")
        bad_jobs = os.path.join(base, "jobs_bad")
        pb, rb = _start_serve(exe, bad_jobs, fake, workers=1,
                              env_extra={"FAKE_MODE": "bad"})
        ok(rb, "D11a 反例 serve（FAKE_MODE=bad）就绪")
        if rb:
            try:
                rep3 = PL.run_batch(pairs=[(bad_pkg, asm_of(bad_pkg))], cg=cg,
                                    exe=exe, jobs_dir=bad_jobs, ctx_dir=ctx,
                                    reviewer="mreview-worker",
                                    applier="mreview-applier", timeout_s=120,
                                    interval_s=0.3, dry_run=False)
                ok(rep3["pass_rate"] == 0.0 and rep3["committed"] == 0,
                   "D11 越界意见全数拦截（pass_rate=%s committed=%s）"
                   % (rep3["pass_rate"], rep3["committed"]))
            finally:
                _stop_serve(pb)
    finally:
        _stop_serve(p)


# ---------------------------- E 组：边界与负例 ----------------------------

def phase_e(tmp):
    print("[E] 边界与负例")
    ok(not PL.read_result(os.path.join(tmp, "nope"), "j1")["ok"],
       "E1 read_result 对不存在 job 返回 ok=False（不炸）")
    if os.path.isfile(PL.hive_exe()):
        r2 = PL.poll(PL.hive_exe(), os.path.join(tmp, "nope"), timeout=20)
        ok(r2.get("ok") is True and int(r2.get("count") or 0) == 0,
           "E2 poll 对空 jobs 目录不炸（ok=True count=0，实得 %s）"
           % {k: r2.get(k) for k in ("ok", "count")})
    ok(PL.hive_exe("X:/custom/hive.exe") == "X:/custom/hive.exe",
       "E3 hive_exe 显式参数优先")
    ok(PL.parse_opinions({"ok": True, "verdicts": []})["ok"], "E4 空 verdicts 可解析")
    ok(not PL.parse_opinions({"ok": True, "verdicts": {}})["ok"],
       "E5 verdicts 非数组被拒（不静默）")
    r = PL.verifier_principal()
    ok("contextual" in (r.layers_allow or []) and "knowledge" not in (r.layers_allow or []),
       "E6 verify 令牌层权限取自 tokens 真源（不含 knowledge）")
    ok(CC.detect_self_verify([{"unit": CC.REFLECT_UNIT, "actor": "x"},
                              {"unit": CC.VERIFY_UNIT, "actor": "y"}]) is False,
       "E7 不同执行者不判自验违例")


# ---------------------------- main ----------------------------

def main(argv=None):
    exe = PL.hive_exe()
    with tempfile.TemporaryDirectory(prefix="mrev_m2_") as tmp:
        # 合规规则库：写路径的 audit 闸要有规则才可能 ACCEPT（无规则恒 DEFER →
        # 意见只会进审核队列）。生产由私有运行时配 MDCG_POLICY_FILE，本测同样
        # 显式配置——否则测不到真实落库链路，只能测到「入队」。
        _saved_policy = os.environ.get("MDCG_POLICY_FILE")
        os.environ["MDCG_POLICY_FILE"] = write_policy(tmp)
        try:
            phase_a(tmp)
            phase_b(tmp)
            phase_c(tmp)
            phase_d(tmp, exe)
            phase_e(tmp)
        finally:
            if _saved_policy is None:
                os.environ.pop("MDCG_POLICY_FILE", None)
            else:
                os.environ["MDCG_POLICY_FILE"] = _saved_policy
    print("\nM2 自测：%d 通过 / %d 失败 / %d 跳过" % (PASS, FAIL, SKIP))
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  - %s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
