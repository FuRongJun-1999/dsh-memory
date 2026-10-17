# -*- coding: utf-8 -*-
# 功能名：反思台账与元认知读面不得携带查询原文（issue #445）
# 生效条件：python -X utf8 -m md_cg.test_issue445_reflection_no_plaintext [--mutate]；被测面=md_cg/mdcg.py 的 reflect() 落盘副本 + md_cg/metacognition.py 的 self_check/blindspots/history 读面
# 子功能：A 组=secret 身份 reflect 后——①台面 _reflection.jsonl 无原文（只有 q_sha/q_key/q_len）②回执仍回显（#298 同款纪律）③④⑤访客降级身份经 mdcg_metacognition 同一 dispatch（self_check 半句/整句、blindspots、report）读不到原文⑥留痕面 _metacognition.jsonl 同口径；G 组=反向腿（作者精确读回：prior_attempts/similarity=1.0/盲区簇计数——不一刀切）；L 组=旧档 fail-closed（升级前明文 query 键在读面折算指纹，任何身份不回落）；E 组=单点钉子（落盘 pop、读面键形、留痕键形）
# 执行：--mutate 时把实现改回修前形态（落盘回明文 / blindspots 回原文 / self_check 留痕回原文），守卫必须转红并点名
# 验证方式：全部 PASS 即通过；--mutate 下变异的「指定命中」须与预期一致（不多不少）
# 不适用条件：不判 _consistency.jsonl（#298 已收口）；不判 scrub 证据串（#444）；不判历史文件清洗（本件不改写盘上旧明文——轮转/清理由维护者裁定，与 #298 同界）；不判 explore/predict/goal_gen/blindspot_tickets 的票据语义（它们消费同一指纹口径，由各自测试守卫）；不覆盖 restricted 档（机制同一）
"""issue #445 守卫：reflect() 把查询原文逐字落 `_reflection.jsonl`（库根明文面），
而 metacognition 读面（self_check/blindspots）不认身份——低 clearance 身份可把
高档身份 reflect 过的查询整句读回（self_check 半句模糊猜测即钓出全句；
blindspots 直接整句返回）。修后两层各自独立生效：
① 落盘去原文（mdcg.reflect）：台账只记不可逆摘要 q_sha（原文 sha1 前 8 位，
精确匹配键）/ q_key（归一前缀的 sha1 前 8 位，邻域聚合键）/ q_len；回执
一字不动（原文留在调用方上下文——与 #298「只改落盘副本」同一纪律）。
② 读面指纹化（metacognition）：self_check 的 similar_history 只带
q_sha/q_key/q_len + similarity/states/d_curr（新档按 q_sha 精确匹配
similarity=1.0——同一字符串的 jaccard 恒 1.0，非编造；旧档 jaccard 渐变
保留，原文用完即弃）；blindspots 簇键=q_key、条目不回落原文；history 与
self_check 自身的留痕（_metacognition.jsonl）同口径。元认知模块因此**全程
不接触身份判据**——不是把 clearance 接进来，而是让原文根本不进台账/读面。
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss445_")
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore", "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_MASTER_KEY": "dd" * 32})
from md_cg.mdcos import MdCGSecure, MdCGOS  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg import metacognition  # noqa: E402
from md_cg import mcp_server as ms  # noqa: E402
from md_cg.fsutil import append_jsonl  # noqa: E402

_QMARK = "PRIVQ445R7"                       # 查询原文标记（issue ① 泄漏物）
_QFULL = "我在服用舍曲林治疗重度抑郁别让公司知道 " + _QMARK
_QHALF = "我在服用舍曲林治疗重度抑郁"          # 修前的钓句探针（前半句）
_LMARK = "LEGACY445M2"                       # 旧档（升级前明文）标记
_LFULL = "升级前的明文查询历史 " + _LMARK
_FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        _FAILS.append(name)


def _designer(sub):
    """高档身份（issue 复现口径：designer / secret / 管理员）。"""
    return MdCGSecure(os.path.join(_TMP, sub),
                      principal=Principal(role="designer", clearance="secret",
                                          can_write=True, can_admin=True),
                      autoflush=1)


def _guest(sub):
    """低档身份（issue ③：record / internal / 非管理员、无令牌降级面）。"""
    return MdCGSecure(os.path.join(_TMP, sub),
                      principal=Principal(role="record", clearance="internal",
                                          can_write=False, can_admin=False),
                      autoflush=1)


def _read(p):
    try:
        return open(p, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def _hits(root, mark):
    """库根内含 mark 的文件清单（④ 全库扫描口径）。"""
    out = []
    for dp, _dn, fs in os.walk(root):
        for fn in fs:
            if mark in _read(os.path.join(dp, fn)):
                out.append(os.path.relpath(os.path.join(dp, fn), root))
    return out


def _blind_result(state="BLINDSPOT"):
    """单条检索结果（与 p12 的 _r 同构——精确控制资格态）。"""
    return [({"id": "x", "frontmatter": {}, "content": "", "path": "x"},
             1.0, {"state": state})]


def _mc_face(cg, action, **kw):
    """走 mdcg_metacognition 的同一 dispatch（ms._metacognition_call）。"""
    return ms._metacognition_call(cg, dict(action=action, **kw))


# ---------------------------------------------------------------- A 组场景
print("== A 组：secret reflect 后，台面/读面/留痕面全程无查询原文 ==")
_cg = _designer("brainA")
_cg.add("priv1", "# 功能名：口令\n# 执行：set\n\n正文：私密节点本体 " + _QMARK
        + " 只应存在于密文里", layer="contextual", sensitivity="private")
_receipt = _cg.reflect(_QFULL, _blind_result("BLINDSPOT"), "确认无泄漏")
_refl_txt = _read(os.path.join(_cg.root, "_reflection.jsonl"))

_check("A0 前提：反思确实落账且命中 BLINDSPOT（非空转）",
       _receipt.get("states", {}).get("BLINDSPOT") == 1
       and len(_refl_txt.splitlines()) >= 1,
       {"states": _receipt.get("states"), "lines": len(_refl_txt.splitlines())})
_check("A1 台账不落原文：_reflection.jsonl 无查询标记且带指纹三键",
       _QMARK not in _refl_txt and "q_sha" in _refl_txt
       and "q_key" in _refl_txt and "q_len" in _refl_txt,
       _refl_txt[-200:])
_check("A2 回执一字不动：reflect 返回体仍回显调用方自己的查询（#298 同款）",
       _receipt.get("query") == _QFULL)

_author_sc = _mc_face(_cg, "self_check", query=_QFULL, k=5)
_meta_txt = _read(os.path.join(_cg.root, "_metacognition.jsonl"))
_guest = _guest("brainA")
_sc_half = _mc_face(_guest, "self_check", query=_QHALF, k=5)
_sc_full = _mc_face(_guest, "self_check", query=_QFULL, k=5)
_bs_guest = _mc_face(_guest, "blindspots", limit=20)
_rep_guest = _mc_face(_guest, "report", window=50)
_hist_guest = _mc_face(_guest, "history", limit=100)

_check("A3 修复点①：访客 self_check 半句钓句读不到原文（similar_history 不回落）",
       _QMARK not in repr(_sc_half), repr(_sc_half)[-200:])
_check("A3b 整句探针同样只回指纹：历史条目无原文（顶层 query 是访客自己的输入，合法回显）",
       _QMARK not in repr(_sc_full.get("similar_history"))
       and (_sc_full.get("similar_history") == [] or all(
           "query" not in h and h.get("q_sha") and h.get("q_len") is not None
           for h in _sc_full["similar_history"])),
       repr(_sc_full.get("similar_history"))[-200:])
_check("A4 修复点②：访客 blindspots 条目只带指纹（q_key）与计数，无原文",
       _QMARK not in repr(_bs_guest)
       and bool(_bs_guest.get("items"))
       and all("query" not in it and it.get("q_key")
               for it in _bs_guest["items"]),
       repr(_bs_guest.get("items"))[:200])
_check("A5 汇总面 report 只回聚合（trace/calibration/blindspots/trust）",
       _QMARK not in repr(_rep_guest), repr(_rep_guest)[:120])
_check("A6 修复点③：留痕面 _metacognition.jsonl 只记 q_sha/q_len（作者侧同口径）",
       _QMARK not in _meta_txt and "q_sha" in _meta_txt
       and '"query"' not in _meta_txt,
       _meta_txt[-200:])
_check("A6b 访客 history 面读回留痕同样无原文（条数与顺序不变）",
       _QMARK not in repr(_hist_guest)
       and all("query" not in r for r in _hist_guest.get("records") or []),
       repr(_hist_guest.get("records"))[-160:])

_node = _guest.get("priv1")
_files_q = _hits(os.path.join(_TMP, "brainA"), _QMARK)
_check("A7 对照：密级闸本身正常（guest get(priv1)=None）且全库扫描无明文查询落点",
       _node is None and not _files_q, {"get": _node, "hits": _files_q})

# ---------------------------------------------------------------- G 组反向腿
print("== G 组：反向腿——作者身份自己仍能精确读回（不一刀切关功能） ==")
_check("G1 作者 self_check 同查询精确命中：similarity=1.0、prior≥1、states 可读",
       _author_sc.get("ok") is True
       and _author_sc.get("prior_attempts", 0) >= 1
       and bool(_author_sc.get("similar_history"))
       and all(h.get("similarity") == 1.0
               and h.get("states", {}).get("BLINDSPOT") == 1
               and h.get("q_sha") == metacognition.q_fp(_QFULL)
               for h in _author_sc["similar_history"]),
       repr(_author_sc.get("similar_history"))[-200:])
_bs_author = _mc_face(_cg, "blindspots", limit=20)
_check("G2 作者 blindspots 簇仍在：q_key 指纹即簇键、BLINDSPOT 计数保留",
       any(it.get("q_key") == metacognition.q_key_fp(_QFULL)
           and it.get("blindspot", 0) >= 1
           for it in _bs_author.get("items") or []),
       repr(_bs_author.get("items"))[:200])
_sc_other = _mc_face(_cg, "self_check", query="完全无关的全新问题 zzz445", k=5)
_check("G3 无关查询照旧 no_prior（匹配语义未被指纹化破坏）",
       _sc_other.get("warning") == "no_prior"
       and _sc_other.get("recommendation") == "search_then_decide",
       _sc_other.get("recommendation"))

# ---------------------------------------------------------------- L 组旧档
print("== L 组：旧档（升级前明文 query 键）读面 fail-closed 折算指纹 ==")
append_jsonl(os.path.join(_cg.root, "_reflection.jsonl"),
             {"t": 1792125639.19, "query": _LFULL, "d_prev": 1.0, "d_curr": 0.6,
              "d2": 0.0, "states": {"BLINDSPOT": 2}, "n_results": 1,
              "feedback": None})
_sc_legacy = _mc_face(_guest, "self_check", query=_LFULL, k=5)
_bs_legacy = _mc_face(_guest, "blindspots", limit=20)
_check("L1 旧档 self_check：jaccard 腿保留（相似度可算）但历史条目不回落原文",
       _LMARK not in repr(_sc_legacy.get("similar_history"))
       and bool(_sc_legacy.get("similar_history"))
       and all("query" not in h and h.get("q_sha")
               == metacognition.q_fp(_LFULL)
               for h in _sc_legacy["similar_history"]),
       repr(_sc_legacy.get("similar_history"))[-200:])
_check("L2 旧档 blindspots：簇键折算成 q_key 指纹（分组语义不变）、无原文",
       _LMARK not in repr(_bs_legacy)
       and any(it.get("q_key") == metacognition.q_key_fp(_LFULL)
               and it.get("blindspot", 0) >= 2
               for it in _bs_legacy.get("items") or []),
       repr(_bs_legacy.get("items"))[:200])
_base_cg = MdCGOS(os.path.join(_TMP, "brainA"))
_sc_base = metacognition.self_check(_base_cg, _LFULL, k=5)
_check("L3 单点统一：纯基类（无身份模型）读面同样不回落原文",
       _LMARK not in repr(_sc_base.get("similar_history"))
       and all("query" not in h for h in _sc_base.get("similar_history") or []),
       repr(_sc_base.get("similar_history"))[-160:])
_meta_log = os.path.join(_cg.root, "_metacognition.jsonl")
append_jsonl(_meta_log, {"op": "self_check", "query": _LFULL,
                         "prior_attempts": 1, "t": 1792125640.0})
_hist_face = metacognition.history(_base_cg, limit=100)
_check("L4 旧档 history 留痕读面：折算 q_sha/q_len，条数与顺序不变",
       all("query" not in r and any(k in r for k in ("q_sha", "op"))
           for r in _hist_face.get("records") or [])
       and _hist_face.get("n") == len(_hist_face.get("records") or [])
       and _LMARK not in repr(_hist_face),
       repr(_hist_face.get("records"))[-160:])

# ---------------------------------------------------------------- E 组单点
print("== E 组：单点钉子 ==")
import inspect  # noqa: E402

_reflect_src = inspect.getsource(_cg.reflect)
_selfcheck_src = inspect.getsource(metacognition.self_check)
_blindspots_src = inspect.getsource(metacognition.blindspots)
_check("E1 reflect 落盘副本经指纹单点（pop 原文 + q_fp/q_key_fp），回执键保留",
       'on_disk.pop("query", None)' in _reflect_src
       and "_mc.q_fp(_qc)" in _reflect_src
       and "_mc.q_key_fp(_qc)" in _reflect_src
       and '"query": query,' in _reflect_src)
_check("E2 self_check similar_history 键形=指纹（q_sha 打头），原文键不得回来",
       'hist.append({"q_sha": hsha' in _selfcheck_src
       and '"query": r.get("query")' not in _selfcheck_src
       and '_jaccard(q, rq)' in _selfcheck_src)
_check("E3 blindspots 簇键=q_key 指纹 setdefault 单点，query 值键不得回来",
       'agg.setdefault(key, {"q_key": key' in _blindspots_src
       and '"query": q' not in _blindspots_src)
_check("E4 self_check 留痕只记指纹（q_sha 打头），原文键不得回 _metacognition.jsonl",
       '_log(cg, {"op": "self_check", "q_sha": q_sha' in _selfcheck_src
       and '_log(cg, {"op": "self_check", "query"' not in _selfcheck_src,
       "(顶层 query 回显是调用方自己的输入，不算留痕面)")

for _c in (_cg, _guest, _base_cg):
    try:
        _c.close()
    except Exception:                                          # noqa: BLE001
        pass
shutil.rmtree(_TMP, ignore_errors=True)

print("")
if _FAILS:
    print("issue #445 结果：%d 失败" % len(_FAILS))
else:
    print("issue #445 结果：全部通过")

# ---------------------------------------------------------------- 定点变异
# 锚点按换行符构造，_mutate 里按目标文件实际行尾折算。
_MUTATIONS = (
    ("V1 reflect 落盘副本改回整份回执（query 原文回台账，回到 #445 修前）",
     "md_cg/mdcg.py",
     '        on_disk = dict(reflection)\n'
     '        on_disk.pop("query", None)\n'
     '        _qc = _mc._q_canon(query)\n'
     '        on_disk["q_len"] = len(_qc)\n'
     '        if _qc:\n'
     '            on_disk["q_sha"] = _mc.q_fp(_qc)\n'
     '            on_disk["q_key"] = _mc.q_key_fp(_qc)',
     '        on_disk = reflection',
     ("A1", "A7", "E1")),
    ("V2 blindspots 簇键/条目改回明文 query（回到 #445 修前）",
     "md_cg/metacognition.py",
     '        sha, key, qlen = _r_qmeta(r)\n'
     '        if not key or not qlen:\n'
     '            continue\n'
     '        a = agg.setdefault(key, {"q_key": key, "q_sha": sha, "q_len": qlen,\n'
     '                                 "blindspot": 0, "defer": 0,\n'
     '                                 "samples": 0, "last_t": 0.0})',
     '        q = str(r.get("query") or "").strip()\n'
     '        if not q:\n'
     '            continue\n'
     '        k = _key(q)\n'
     '        a = agg.setdefault(k, {"query": q, "blindspot": 0, "defer": 0,\n'
     '                               "samples": 0, "last_t": 0.0})',
     ("A4", "G2", "L2", "E3")),
    ("V3 self_check 留痕改回明文 query（_metacognition.jsonl 回原文，回到 #445 修前）",
     "md_cg/metacognition.py",
     '    _log(cg, {"op": "self_check", "q_sha": q_sha, "q_len": len(q),\n'
     '              "prior_attempts": n,\n'
     '              "prior_d": out["prior_d"], "warning": warning,\n'
     '              "recommendation": rec_code})',
     '    _log(cg, {"op": "self_check", "query": q, "prior_attempts": n,\n'
     '              "prior_d": out["prior_d"], "warning": warning,\n'
     '              "recommendation": rec_code})',
     # A6b（读面折算）此时**保持绿**：留痕写回原文但 history 读面兜底折算——
     # 纵深防御被如实观测，不把 A6b 计入本变异的期望红。
     ("A6", "A7", "E4")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss445_mut_")
    src = os.path.join(_REPO, "md_cg")
    if os.path.isdir(src):
        shutil.copytree(src, os.path.join(dst, "md_cg"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue445_reflection_no_plaintext"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1200)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把实现改回修前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            raw = open(p, "rb").read()
            _nl = "\r\n" if b"\r\n" in raw[:8192] else "\n"
            t = raw.decode("utf-8")
            old = old.replace("\n", _nl)
            new = new.replace("\n", _nl)
            if t.count(old) != 1:
                bad.append("%s —— 锚点命中 %d 次" % (desc, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [r for r in reds2 if r.startswith(exp)]
            if rc2 != 0 and len(hit) == len(exp) and len(hit) == len(reds2):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
        return 0
    return 0 if not _FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
