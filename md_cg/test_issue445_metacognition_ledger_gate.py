# -*- coding: utf-8 -*-
# 功能名：元认知读面与台账的密级收口守卫（#445 反思台账 / #426-D self_check 查询原文）
# 生效条件：python -u -X utf8 -m md_cg.test_issue445_metacognition_ledger_gate [--mutate]；
#   被测面＝md_cg/metacognition.py 的 _can_read_record / _redact_query / _reflections /
#   _log / self_check / blindspots / history（真实 MdCGSecure 实例 + 临时 root）
# 子功能：A self_check 不回原文 · B blindspots 不回原文 · C history 不回原文 ·
#   D 台账不落原文（只落摘要）· E 不可写身份不得追加台账 · G 无身份模型（纯 MdCGOS）
#   既有读数不变 · I 记录缺 sensitivity ⇒ 非设计者 fail-closed ·
#   J **第四读面** autonomy.proposals（经 cg(op=insight, action=explore) 暴露）不回原文
# 执行：默认跑全部腿并做源码锚点自检（锚点缺失 ⇒ exit 2，fail-closed）；
#   --mutate 时在镜像树里逐条撤闸，守卫必须按指定项转红
# 验证方式：全部 PASS 且 --mutate 每条变异的红项集合与预期逐项相符 ⇒ 退出码 0
# 不适用条件：① 不改写历史文件——升级前已明文落盘的 `_reflection.jsonl` 仍含原文
#   （写面在 md_cg/mdcg.py::reflect，不在本单元授权文件内，已按 NEED_FILE 上报）；
#   ② 不覆盖 `_metacognition.jsonl` 的物理轮转/清理；③ 不判 trace/trust/calibration
#   三个纯数值面的**数值正确性**（它们的数据源已随 `_reflections` 一并按可见性过滤，
#   本腿只判「低权读者不再拿到任何记录 ⇒ 三面退化为空/insufficient_data」这一事）。
"""issue #445 / #426-D 守卫：查询原文不得经元认知读面回流，台账不得落原文。

病象（修前实测，见 `.tmp/U04/probe_445_426d.py` 与复核探针 `.tmp/review_u04/probe_output_role.py`）：
  · 访客（无令牌，clearance=internal, can_write=False）
    - `mdcg_metacognition self_check` 的 `similar_history[].query` 回出属主原文；
    - `history` 逐条回 `{"op":"self_check","query":<原文>}`；
    - 每次 self_check 还往 `_metacognition.jsonl` **持久追加**（10 次 ≈ +60KB）。
  · role=output（clearance=internal, can_write=False, ops 含 insight）经
    `cg(op=insight, action=explore)` 拿到 `proposals[].query` 原文——**第四读面**
    （autonomy.proposals 直读 `metacognition._reflections`）。首版只堵了前三面，
    复核打回后把判据收到**台账唯一读取点** `_reflections`，第四面自动继承。
  · `_reflection.jsonl` 明文存 `reflect()` 的 query（写面在 mdcg.py，不在本单元授权面）。

修法（判据单点，均落在 md_cg/metacognition.py）：
  · `_can_read_record(cg, rec)` —— 台账记录读可见性单点：无身份模型/设计者不设限；
    记录缺 `sensitivity` 键 ⇒ **fail-closed 不可读**（与 consistency_history 对
    「升级前无 sensitivity 键旧记录」的处置同口径；`reflect()` 恒不写该键 ⇒ 对
    非设计者即全量 fail-closed）；有密级 ⇒ 委派 `security.visible_to`
    （= `cg._readable`，clearance × 密级 ∧ 会话绑定）。
  · `_reflections(cg)` —— **台账唯一读取点**，在这里过滤：trace / trust /
    blindspots / self_check / autonomy.proposals **五个消费面**一并继承，
    不在各面各写一份判据（本仓反复栽过的「同一判据两份」形态）。
  · `_redact_query(rec)` —— `_metacognition.jsonl` 读面去原文（该台账有自己的
    读取点 `history`，不在 `_reflections` 路径上）。
  · `_log` —— 台账只落 `query_digest`(sha1 前 8 位) + `query_len`；`can_write=False`
    的身份**不写盘**（只算不留痕）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="iss445_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore", "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
for _k in ("MDCG_TOKEN", "MDCG_VERIFY_KEY"):
    os.environ.pop(_k, None)

from md_cg import metacognition as mc                     # noqa: E402
from md_cg import mcp_server as ms                        # noqa: E402
from md_cg.mdcg import STATE_BLINDSPOT                    # noqa: E402
from md_cg.mdcos import MdCGOS, MdCGSecure               # noqa: E402
from md_cg.security import Principal                      # noqa: E402
from md_cg.tokens import role_spec                        # noqa: E402

PASSED, FAILS = [], []
Q = "PRIVQ999 我确诊重度抑郁 在服用舍曲林 律师李四 离婚诉讼"
NEEDLE = "舍曲林"


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


def _mk(root, role, clearance, can_write, can_admin, session=None, ops=None,
        layers=None, auth_mode="direct"):
    return MdCGSecure(root, principal=Principal(
        role=role, clearance=clearance, can_write=can_write,
        can_admin=can_admin, session=session, ops_allow=ops,
        layers_allow=layers, auth_mode=auth_mode), autoflush=1)


def _blind(q, state=STATE_BLINDSPOT):
    return [({"id": "x", "frontmatter": {}, "content": "", "path": "x"},
             1.0, {"state": state})]


def group_a():
    print("\n[A] self_check 读面：低权读者拿不到原文")
    own = _mk(_TMP + "/a", "designer", "private", True, True)
    g = role_spec("guest")
    guest = _mk(_TMP + "/a", "guest", "internal", False, False,
                ops=g["ops_allow"], layers=g["layers_allow"],
                auth_mode="anonymous")
    own.self_check(Q)
    own.reflect(Q, _blind(Q))
    sc = guest.self_check("PRIVQ999 我确诊重度抑郁")
    hist = sc.get("similar_history") or []
    _check("A1 访客 self_check 的 similar_history 不含原文",
           NEEDLE not in str(sc), str(sc)[:200])
    _check("A2 访客的相似历史为空（不可见记录连 similarity/计数都不回）",
           hist == [] and sc.get("prior_attempts") == 0,
           str({k: sc.get(k) for k in ("prior_attempts", "similar_history")})[:200])
    _check("A3 属主 self_check 仍读得到原文（反向腿：不过度关闭）",
           NEEDLE in str(own.self_check("PRIVQ999 我确诊重度抑郁")),
           str(own.self_check("PRIVQ999 我确诊重度抑郁"))[:200])
    own.close()
    guest.close()


def group_b():
    print("\n[B] blindspots 读面：低权读者拿不到原文")
    own = _mk(_TMP + "/b", "designer", "private", True, True)
    g = role_spec("guest")
    guest = _mk(_TMP + "/b", "guest", "internal", False, False,
                ops=g["ops_allow"], layers=g["layers_allow"],
                auth_mode="anonymous")
    own.reflect(Q, _blind(Q))
    own.reflect(Q, _blind(Q))
    b_own = mc.blindspots(own)
    b_g = mc.blindspots(guest)
    _check("B1 属主 blindspots 仍聚合出该盲区（反向腿：不过度关闭）",
           b_own.get("n_queries") == 1
           and NEEDLE in str(b_own.get("items") or []),
           str(b_own.get("items"))[:200])
    _check("B2 访客 blindspots 不含原文",
           NEEDLE not in str(b_g), str(b_g)[:200])
    _check("B3 访客 blindspots 连条目也不聚合（不可见记录不进计数）",
           b_g.get("n_queries") == 0, str(b_g.get("n_queries")))
    own.close()
    guest.close()


def group_c():
    print("\n[C] history 读面：低权读者拿不到原文")
    own = _mk(_TMP + "/c", "designer", "private", True, True)
    g = role_spec("guest")
    guest = _mk(_TMP + "/c", "guest", "internal", False, False,
                ops=g["ops_allow"], layers=g["layers_allow"],
                auth_mode="anonymous")
    own.self_check(Q)
    own.reflect(Q, _blind(Q))
    h_g = mc.history(guest)
    h_o = mc.history(own)
    _check("C1 访客 history 不含原文", NEEDLE not in str(h_g), str(h_g)[:200])
    _check("C2 访客 history 记录被去原文（query_redacted，无 query/摘要）",
           bool(h_g.get("records")) and all(
               r.get("query_redacted") and "query" not in r
               and "query_digest" not in r for r in h_g["records"]),
           str(h_g["records"])[:200])
    _check("C3 属主 history 仍读到全部记录（台账治本：原文只在调用方上下文）",
           bool(h_o.get("records")) and all(
               "query_digest" in r and "query" not in r for r in h_o["records"]),
           str(h_o["records"])[:200])
    sc_o = own.self_check("PRIVQ999 我确诊重度抑郁")
    _check("C4 属主经 self_check 仍读得到原文（反向腿：_reflection 面不过度关闭）",
           NEEDLE in str(sc_o), str(sc_o)[:200])
    own.close()
    guest.close()


def group_j():
    print("\n[J] 第四读面 autonomy.proposals（cg op=insight action=explore）不回原文")
    own = _mk(_TMP + "/j", "designer", "private", True, True)
    sp = role_spec("output")
    out_cg = _mk(_TMP + "/j", "output", "internal", False, False,
                 ops=sp["ops_allow"], layers=sp["layers_allow"],
                 auth_mode="direct")
    own.reflect(Q, _blind(Q))
    own.reflect(Q, _blind(Q))
    r_out = ms._dispatch(out_cg, "cg", {"op": "insight", "action": "explore"})
    r_own = ms._dispatch(own, "cg", {"op": "insight", "action": "explore"})
    _check("J1 role=output 经 cg(op=insight, action=explore) 拿不到原文",
           NEEDLE not in str(r_out), str(r_out)[:300])
    _check("J2 output 的 proposals 为空（不可见记录不进聚合）",
           (r_out.get("proposals") or []) == [] and r_out.get("n_signals") == 0,
           str({"n_signals": r_out.get("n_signals"),
                "n_proposals": len(r_out.get("proposals") or [])}))
    _check("J3 属主同一入口仍拿到提案与原 query（反向腿：功能未关）",
           NEEDLE in str(r_own) and len(r_own.get("proposals") or []) >= 1,
           str(r_own)[:300])
    _check("J4 低权读者的 trace/trust 一并退化为空（同一读取点的连带面，如实登记）",
           mc.trace(out_cg).get("ok") is False
           and mc.trust(out_cg).get("p_gap") is None,
           str({"trace": mc.trace(out_cg).get("reason"),
                "p_gap": mc.trust(out_cg).get("p_gap")}))
    own.close()
    out_cg.close()


def group_d():
    print("\n[D] 台账不落原文（_metacognition.jsonl 只落摘要）")
    own = _mk(_TMP + "/d", "designer", "private", True, True)
    own.self_check(Q)
    own.close()
    p = os.path.join(_TMP + "/d", "_metacognition.jsonl")
    raw = open(p, encoding="utf-8").read()
    _check("D1 台账文件不含查询原文", NEEDLE not in raw, raw[:200])
    _check("D2 台账含不可逆摘要 query_digest（sha1 前 8 位）",
           mc._digest(Q) in raw and '"query_digest"' in raw, raw[:200])
    _check("D3 台账含 query_len（长度可审计、原文不可逆）",
           '"query_len"' in raw, raw[:200])


def group_e():
    print("\n[E] 不可写身份不得持久追加台账（#426-D D3 灌盘面）")
    g = role_spec("guest")
    guest = _mk(_TMP + "/e", "guest", "internal", False, False,
                ops=g["ops_allow"], layers=g["layers_allow"],
                auth_mode="anonymous")
    p = os.path.join(_TMP + "/e", "_metacognition.jsonl")
    n0 = os.path.getsize(p) if os.path.exists(p) else 0
    for _ in range(5):
        guest.self_check("灌" * 2000)
    n1 = os.path.getsize(p) if os.path.exists(p) else 0
    _check("E1 访客 5 次 self_check 后台账字节数不变", n0 == n1,
           "%d -> %d" % (n0, n1))
    _check("E2 访客 self_check 仍返回 ok（只算不写，功能保留）",
           guest.self_check("探针") .get("ok") is True)
    guest.close()


def group_g():
    print("\n[G] 无身份模型（纯 MdCGOS）既有读数不变")
    cg = MdCGOS(_TMP + "/g")
    cg.reflect("量子纠缠退相干时间", _blind("x"))
    cg.reflect("量子纠缠退相干时间", _blind("x"))
    bs = cg.metacognition_blindspots()
    _check("G1 MdCGOS blindspots 仍聚合 query（无 principal ⇒ 不设限）",
           bs.get("n_queries") == 1
           and bs["items"][0].get("query") == "量子纠缠退相干时间",
           str(bs.get("items"))[:200])
    cg.self_check("量子纠缠退相干时间")
    h = cg.metacognition_history()
    _check("G2 MdCGOS history 记录仍可取（无 principal ⇒ 原样）",
           bool(h.get("records")) and "query_digest" in h["records"][0],
           str(h["records"])[:200])
    cg.close()


def group_i():
    print("\n[I] 记录缺 sensitivity 键 ⇒ 非设计者一律去原文（fail-closed）")
    root = _TMP + "/i"
    os.makedirs(root, exist_ok=True)
    import json
    with open(os.path.join(root, "_reflection.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"t": 1.0, "query": Q, "d_curr": 1.0,
                            "states": {"BLINDSPOT": 3}},
                           ensure_ascii=False) + "\n")
    rec = {"t": 2.0, "query": Q, "d_curr": 1.0, "states": {"BLINDSPOT": 3}}
    with open(os.path.join(root, "_metacognition.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    g = role_spec("guest")
    guest = _mk(root, "guest", "internal", False, False,
                ops=g["ops_allow"], layers=g["layers_allow"],
                auth_mode="anonymous")
    own = _mk(root, "designer", "private", True, True)
    _check("I1 缺键旧记录对低权读者不可读（_can_read_record=False）",
           mc._can_read_record(guest, rec) is False)
    _check("I2 缺键旧记录对设计者仍可读（_can_read_record=True）",
           mc._can_read_record(own, rec) is True)
    _check("I3 低权读者 history 对该记录去原文",
           NEEDLE not in str(mc.history(guest)), str(mc.history(guest))[:200])
    guest.close()
    own.close()


def _anchor_check():
    """源码锚点自检：修复的关键字面量不在源码 ⇒ exit 2（fail-closed）。"""
    mc_src = open(os.path.join(_REPO, "md_cg", "metacognition.py"),
                  encoding="utf-8").read()
    missing = [a for a in ("_can_read_record", "_redact_query", "query_digest",
                           "query_redacted", "visible_to")
               if a not in mc_src]
    if missing:
        print("ANCHOR-MISS md_cg/metacognition.py: %s" % missing)
        return 2
    return 0


# ================================================= M 组：反向腿②（定点变异）
_MUTATIONS = (
    ("M1 撤 `_reflections` 的可见性过滤（台账唯一读取点回到原形态）",
     "md_cg/metacognition.py",
     (("    return [r for r in read_jsonl(path) if _can_read_record(cg, r)]",
       "    return list(read_jsonl(path))  # M1 撤台账唯一读取点的可见性过滤"),),
     # 台账唯一读取点被撤 ⇒ 五个消费面同时漏：A1/A2（self_check）、B2/B3（blindspots）、
     # J1/J2（autonomy.proposals 第四读面）、J4（trace/trust 连带面）。
     # 这正是复核打回的那条：首版只在各面各写判据，autonomy 面漏掉。
     ("A1", "A2", "B2", "B3", "J1", "J2", "J4")),
    ("M2 撤「缺 sensitivity 键 ⇒ fail-closed」（改为缺键即放行，复刻 #447 的 fail-open 形态）",
     "md_cg/metacognition.py",
     (("    if not sens:" + chr(10)
       + "        return False                      # 密级不可判 ⇒ fail-closed（宁可少读）",
       "    if not sens:" + chr(10)
       + "        return True                       # M2 缺键即放行（fail-open）"),),
     # 反思台账恒无 sensitivity 键（reflect() 不写该键）⇒ 撤 fail-closed 后
     # 非设计者又能读到全部反思记录：A1/A2、B2/B3、J1/J2、J4 一并转红；
     # C2/I1/I3 同红是**同一判据单点**的必然后果（`history` 读的
     # `_metacognition.jsonl` 同样按记录自带 sensitivity 判，缺键即放行）——
     # 与 M3（只撤 history 的过滤调用）在 C2/I3 上重叠，这是「判据在单点」
     # 的真实形状，不是红项串台：M2 撤的是**判据条件**，M3 撤的是**调用点**。
     ("A1", "A2", "B2", "B3", "C2", "I1", "I3", "J1", "J2", "J4")),
    ("M3 撤 history 读面过滤",
     "md_cg/metacognition.py",
     (("    recs = [r if _can_read_record(cg, r) else _redact_query(r) for r in recs]",
       "    pass  # M3 撤 history 读面过滤"),),
     # C2/I3 同红：C2 = 去原文标记消失；I3 = 缺 sensitivity 键的旧记录原样回原文。
     # C1 仍绿是**台账治本**的读数（`_metacognition.jsonl` 只落摘要，撤读面过滤也
     # 拿不到原文）——两腿分工：C1 判「盘面有没有原文」，C2/I3 判「读面有没有闸」。
     ("C2", "I3")),
    ("M4 台账回退为落原文",
     "md_cg/metacognition.py",
     (("    if \"query\" in rec:" + chr(10)
       + "        _q = rec.pop(\"query\")" + chr(10)
       + "        rec[\"query_digest\"] = _digest(_q)" + chr(10)
       + "        rec[\"query_len\"] = len(str(_q or \"\"))" + chr(10)
       + "        rec[\"query_redacted\"] = True",
       "    pass  # M4 台账回退为落原文"),),
     # D1/D2/D3 = 台账盘面三判据；C3/G2 = 反向腿（属主与 MdCGOS 都要求摘要在场）。
     ("C3", "D1", "D2", "D3", "G2")),
    ("M5 撤不可写身份的台账写闸",
     "md_cg/metacognition.py",
     (("    if _p is not None and not getattr(_p, \"can_write\", True):" + chr(10)
       + "        return rec",
       "    pass  # M5 撤不可写身份的台账写闸"),),
     ("E1",)),
)

def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss445_mut_")
    for name in ("md_cg", "lib"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
              "MDCG_EXPORT_ROOT", "MDCG_INGEST_ROOT", "MDCG_TOKEN",
              "MDCG_TOKEN_FILE", "MDCG_VERIFY_KEY"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-u", "-X", "utf8", "-m",
                         "md_cg.test_issue445_metacognition_ledger_gate"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _apply_text(text, rel, pairs):
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _mutate():
    print("!! 反向腿②：逐条撤闸，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）"
              % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-20:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            for root, _dd, _ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:10]:
                    print("        FAIL " + r)
        print("反向腿②：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    print("== #445/#426-D 元认知读面与台账密级收口守卫 ==")
    try:
        _rc = _anchor_check()
        if _rc:
            return _rc
        group_a()
        group_b()
        group_c()
        group_j()
        group_d()
        group_e()
        group_g()
        group_i()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print("=" * 68)
    print("#445/#426-D 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
