# -*- coding: utf-8 -*-
# 功能名：待审队列的**积压可观测**与受门禁的治理入口（issue #71；#69 单点化）
# 生效条件：python -X utf8 -m md_cg.test_issue71_queue_backlog [--mutate]；被测面＝md_cg/mdcos.py 的 review_backlog / review_preview / review_search / pending_body+pending_digest（#69 单点）、mcp_server 的 review action 分派、review_cli 的摘要委派
# 子功能：A 组＝积压可观测（条数/最老龄/分桶，读数与夹具独立算得的真值逐项相等）；B 组＝按权限过滤（低权不得见高密级条目的计数与命中）；C 组＝dry-run 零副作用；D 组＝不改 cg.search 默认语义 + 受门禁独立入口；E 组＝单点面与 op 表一致（含实跑 scripts/check_op_table_parity.py）；骨架①② + 双向变异
# 执行：--mutate 时在镜像树里回缺陷（分级绕过可见性）/ 过度（可见集恒空）/ 只加壳不接线（摘要不委派单点），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；变异与骨架红项集合须与预期逐项相符
# 不适用条件：**不改 #69 保留契约**（现行＝裁决甲「保原文可追溯」，本件只做「正文取数单点化」，语义零变更；乙/丙 的代价已报 Lead）；**批量 accept/reject 未实现**（需 can_admin，属授权面，本批只做 dry-run）；不判 kind=mutation 分桶（构造变更单需走三档自治出单链）；不判会话隔离位过滤（B 组只覆盖密级位；会话位由 security.visible_to 同一实现负责，另有守卫）；不判 CLI 新子命令（本件接线到 MCP action + 委派单点）
"""issue #71 守卫：积压必须**可观测**，治理入口必须**按权限过滤**且**不改默认读语义**。

病象（修前）：pending 提案不进索引（cg.search 走索引 ⇒ 召回 0——实测其返回是 (rows, meta)
二元组，len(...)==2 **不是**命中数，本守卫 D 组按返回值形状断言）；核心面（cg(op=review,
action=…)）没有按龄/来源/密级/kind 的分级汇总，也没有 dry-run 预览与受门禁的待审检索入口。

修法：① review_backlog()——条数 + 最老龄 + 按龄/密级/层/kind/来源分桶，样本走
_review_list_visible()（与 cg(op=info) 的 review_pending 同一可见性面 ⇒ 计数随身份）；
② review_preview()——dry-run（零副作用）；③ review_search()——受门禁的独立检索入口
（**不改 cg.search 默认语义**）；④ pending_body/pending_digest＝#69 正文/摘要取数**单点**，
review_cli._brief 委派它（将来契约改乙/丙只改一处）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import _guard_kit as GK           # noqa: E402
from md_cg import mdcos as MC                # noqa: E402
from md_cg.mdcos import MdCGOS, MdCGSecure   # noqa: E402
from md_cg.security import Principal          # noqa: E402

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss71_")
_NL = chr(10)
_TOKEN = "hunter2-SECRET-TOKEN"
_HOUR = 3600.0
_DAY = 86400.0


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _body(tag):
    return _NL.join(["# 功能：" + tag, "# 执行：口令 " + _TOKEN,
                     "# 验证方式：test", "# 不适用条件：无"])


def _queue_path(root):
    return os.path.join(root, "hippocampus", "inbox.jsonl")


def _propose(cg, node_id, tag, sensitivity=None, session=None):
    kw = {"layer": "knowledge"}
    if sensitivity:
        kw["sensitivity"] = sensitivity
    if session:
        kw["session"] = session
    return cg.propose(node_id, _body(tag), **kw)


def _set_age(root, pid, age_s, now=None):
    """夹具侧直接改写队列记录的 t（置指定龄）——真值由本守卫独立算得，不读被测函数输出。"""
    p = _queue_path(root)
    rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    for r in rows:
        if r.get("pid") == pid:
            r["t"] = (now if now is not None else time.time()) - age_s
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + _NL)


print("== A 组：积压可观测（条数 + 最老龄 + 分桶；真值由夹具独立算得） ==")
_rootA = os.path.join(_TMP, "a")
os.makedirs(_rootA, exist_ok=True)
_NOW = 1800000000.0
_cgA = MdCGOS(_rootA, autoflush=0)
_p1 = _propose(_cgA, "n_1", "两小时前", sensitivity="internal")
_p2 = _propose(_cgA, "n_2", "三天前", sensitivity="private")
_p3 = _propose(_cgA, "n_3", "十天前", sensitivity="private")
_cgA.close()
_set_age(_rootA, _p1, 2 * _HOUR, now=_NOW)
_set_age(_rootA, _p2, 3 * _DAY, now=_NOW)
_set_age(_rootA, _p3, 10 * _DAY, now=_NOW)
_cgA2 = MdCGOS(_rootA, autoflush=0)
_bl = _cgA2.review_backlog(now=_NOW)
_check("A01 条数：pending == 3（夹具三条）", _bl.get("pending") == 3, _bl.get("pending"))
_check("A02 最老龄：oldest_age_s == 10 天（夹具最大龄）",
       abs(float(_bl.get("oldest_age_s") or 0) - 10 * _DAY) < 1.0, _bl.get("oldest_age_s"))
_check("A03 最老 pid 点名正确（夹具第三条）", _bl.get("oldest_pid") == _p3,
       (_bl.get("oldest_pid"), _p3))
_check("A04 按龄分桶：2h/3d/10d ⇒ lt_1h=0, lt_1d=1, lt_7d=1, gte_7d=1",
       _bl.get("by_age") == {"lt_1h": 0, "lt_1d": 1, "lt_7d": 1, "gte_7d": 1},
       _bl.get("by_age"))
_check("A05 按密级分桶：internal=1, private=2",
       _bl.get("by_sensitivity") == {"internal": 1, "private": 2},
       _bl.get("by_sensitivity"))
_check("A06 按层 knowledge=3；按 kind proposal=3",
       _bl.get("by_layer") == {"knowledge": 3}
       and _bl.get("by_kind") == {"proposal": 3},
       (_bl.get("by_layer"), _bl.get("by_kind")))
_cgA2.close()

print("== B 组：按权限过滤（低权不得见高密级条目） ==")
_rootB = os.path.join(_TMP, "b")
os.makedirs(_rootB, exist_ok=True)
# 三者**同一会话**（s1）：本组要单变量地测「密级位」，不能把会话位混进来——队列面是
# 「clearance x sensitivity 且 会话绑定」的同一可见性单点（实测：会话不同则一律看不到）。
_w = MdCGSecure(_rootB, principal=Principal(tenant="t1", actor="alice",
                                          role="designer", clearance="secret",
                                          session="s1"),
                autoflush=0)
_pid_priv = _propose(_w, "b_priv", "私密", sensitivity="private")
_w.close()
_hi = MdCGSecure(_rootB, principal=Principal(tenant="t1", actor="alice",
                                           role="designer", clearance="secret",
                                           session="s1"),
                 autoflush=0)
_lo = MdCGSecure(_rootB, principal=Principal(tenant="t1", actor="bob",
                                         role="reflect", clearance="internal",
                                         session="s1"),
                 autoflush=0)
_bl_hi, _bl_lo = _hi.review_backlog(), _lo.review_backlog()
_check("B01 高权（secret）看得到：pending >= 1", (_bl_hi.get("pending") or 0) >= 1,
       _bl_hi.get("pending"))
_check("B02 低权（internal）看不到：pending == 0（与 cg(op=info) 同一可见性面）",
       _bl_lo.get("pending") == 0, _bl_lo.get("pending"))
_check("B03 低权分桶里不出现该密级（不做计数泄漏）",
       "private" not in (_bl_lo.get("by_sensitivity") or {}),
       _bl_lo.get("by_sensitivity"))
_check("B04 低权检索命中为 0（受门禁入口同样按可见性过滤）",
       _lo.review_search(_TOKEN).get("hits") == [],
       _lo.review_search(_TOKEN).get("hits"))
_check("B05 高权检索命中 >= 1（对有权者可查）",
       len(_hi.review_search(_TOKEN).get("hits") or []) >= 1)

print("== C 组：dry-run 零副作用 ==")
_dec_path = os.path.join(_rootB, "hippocampus", "decisions.jsonl")
_before_dec = (os.path.getsize(_dec_path) if os.path.exists(_dec_path) else 0)
_before_pend = _hi.review_stats().get("pending")
_pv = _hi.review_preview(limit=10)
_after_dec = (os.path.getsize(_dec_path) if os.path.exists(_dec_path) else 0)
_after_pend = _hi.review_stats().get("pending")
_check("C01 dry_run 标记为真且给出清单与计数",
       _pv.get("dry_run") is True and isinstance(_pv.get("would"), list)
       and _pv.get("total") == len(_pv.get("would")),
       {k: _pv.get(k) for k in ("dry_run", "total", "counts")})
_check("C02 零副作用：decisions.jsonl 未增长、pending 数不变",
       _before_dec == _after_dec and _before_pend == _after_pend,
       (_before_dec, _after_dec, _before_pend, _after_pend))
_check("C03 预览按筛选生效：kind=mutation 不匹配 ⇒ total==0",
       _hi.review_preview(kind="mutation").get("total") == 0)

print("== D 组：不改 cg.search 默认语义 + 受门禁独立入口 ==")
_sres = _hi.search(_TOKEN)
_rows = _sres[0] if isinstance(_sres, tuple) else _sres
_check("D01 cg.search 仍召回不到 pending（返回 (rows, meta) 二元组；rows == []）",
       isinstance(_sres, tuple) and list(_rows) == [],
       (type(_sres).__name__,))
_check("D02 独立入口可查（显式 opt-in）：hits >= 1 且带 pid/摘要",
       len(_hi.review_search(_TOKEN).get("hits") or []) >= 1
       and all(h.get("pid") and h.get("digest") is not None
               for h in _hi.review_search(_TOKEN)["hits"]))
_check("D03 默认不吐正文（摘要面检索）：hit 里无 content 字段",
       all("content" not in h for h in _hi.review_search(_TOKEN)["hits"]))
_check("D04 include_content=True 才带正文，且取值与 #69 单点同源",
       all(h.get("content") == MC.pending_body({"content": h.get("content")})
           for h in _hi.review_search(_TOKEN, include_content=True)["hits"]))
_hi.close()
_lo.close()

print("== E 组：单点面与 op 表一致 ==")
_MCS = open(os.path.join(_REPO, "md_cg", "mdcos.py"), encoding="utf-8").read()
_CLI = open(os.path.join(_REPO, "md_cg", "review_cli.py"), encoding="utf-8").read()
_SRV = open(os.path.join(_REPO, "md_cg", "mcp_server.py"), encoding="utf-8").read()
_check("E01 #69 单点唯一：pending_body / pending_digest 各恰一处定义",
       len(re.findall(r"def pending_body\(", _MCS)) == 1
       and len(re.findall(r"def pending_digest\(", _MCS)) == 1)
_check("E02 CLI 摘要**委派**单点：_brief 体内只调 pending_digest，无第二份截断实现",
       "return pending_digest(rec, width)" in _CLI
       and _CLI.count("content") > 0 and "text[:width]" not in _CLI)
_check("E03 op 表列出三个新 action（description 与实现一致）",
       "list|decide|rounds|stats|backlog|preview|search" in _SRV)
_FALLBACK = "return cg.review_decide(a.get(" + chr(34) + "pid" + chr(34)
_E04_OK = True
for _act in ("backlog", "preview", "search"):
    if _SRV.index(chr(34) + _act + chr(34)) > _SRV.index(_FALLBACK):
        _E04_OK = False
_check("E04 分派在**兜底之前**：三个 action 的匹配行都出现在 review_decide 兜底行之前",
       _E04_OK)
_PAR = os.path.join(_REPO, "scripts", "check_op_table_parity.py")
_pr = subprocess.run([sys.executable, "-X", "utf8", _PAR], cwd=_REPO,
                     capture_output=True, text=True, encoding="utf-8",
                     errors="replace", shell=False, timeout=600)
_check("E05 跨面契约守卫（**脚本入口** scripts/check_op_table_parity.py）实跑 rc=0",
       _pr.returncode == 0, (_pr.stdout or "").strip()[-160:])

print("== 骨架①：枚举完备性（分级面是否绕过可见性） ==")


def _discover(texts):
    """守卫自己的枚举：命中「按龄/密级汇总队列但**绕过可见性面**」的实现。"""
    import ast as _ast
    hits = []
    for rel, src in texts.items():
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.FunctionDef):
                continue
            seg = _ast.get_source_segment(src, node) or ""
            if "by_age" not in seg and "oldest_age" not in seg:
                continue
            if "_review_list_visible" in seg or "review_list()" in seg:
                continue
            hits.append((rel, node.lineno))
    return hits


_OLD_AGG = _NL.join(["def backlog(cg):", "    rows = cg._inbox_records()",
                     "    by_age = {}", "    oldest_age = 0.0",
                     "    return by_age, oldest_age"])
_NEW_AGG = _NL.join(["def backlog(cg):", "    rows = cg._review_list_visible()",
                     "    by_age = {}", "    oldest_age = 0.0",
                     "    return by_age, oldest_age"])
_ok_e, _det_e = GK.assert_enumeration_complete(
    _discover,
    [("应命中·旧形态（绕过可见性直接汇总队列）", _OLD_AGG, True, "agg_old.py"),
     ("不应命中·新形态（走可见性面）", _NEW_AGG, False, "agg_new.py"),
     ("不应命中·无关函数", "def other():" + _NL + "    return 1", False, "x.py")])
_check("E06 骨架①枚举完备性（应命中/不应命中两侧）", _ok_e, _det_e)

print("== 骨架② / 变异 ==")
_MNL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "mdcos.py"),
                                    "rb").read()[:8192] else "\n"


def _jm(*lines):
    return _MNL.join(lines)


# 判据行在**两个**新方法里同形出现 ⇒ 锚点必须带**上下文行**才唯一（单行会命中 2 次，实测踩过）。
_BL_CTX = _jm("        now = float(now if now is not None else time.time())",
              "        rows = list(self._review_list_visible() or [])")
_SR_CTX = _jm("        q = str(query or " + chr(34) + chr(34) + ").strip().lower()",
              "        rows = list(self._review_list_visible() or [])")
_VIS_BYPASS = "        rows = list(self._inbox_records() or [])   # 变异：绕过可见性"
_VIS_EMPTY = "        rows = []   # 变异：可见集恒空（过度收紧）"


def _swap(pair, replacement):
    """把「上下文两行」的第二行换成变异行（保第一行，避免动到别处）。"""
    head = pair.split(_MNL)[0]
    return (pair, head + _MNL + replacement)


_M1 = ("M1 回缺陷：分级绕过可见性（低权从计数即见高密级条目）", "md_cg/mdcos.py",
       # 实测：B04 亦红（低权检索经绕过路径拿到了命中）——正是本变异要暴露的面
       [_swap(_BL_CTX, _VIS_BYPASS), _swap(_SR_CTX, _VIS_BYPASS)], ("B02", "B03", "B04"))
_M2 = ("M2 过度收紧：可见集恒空（谁也别想看）", "md_cg/mdcos.py",
       # 实测：A05/A06 亦红（可见集恒空 ⇒ 分桶全空）
       [_swap(_BL_CTX, _VIS_EMPTY)], ("A01", "A02", "A03", "A04", "A05", "A06", "B01"))
_CLI_BRIEF = _jm("    return pending_digest(rec, width)")
_CLI_OLD = _jm("    text = (rec.get(" + chr(34) + "content" + chr(34) + ") or " + chr(34) + chr(34) + ").replace(" + chr(34) + chr(92) + "n" + chr(34) + ", " + chr(34) + " " + chr(34) + ")",
               "    return text[:width] + (" + chr(34) + "…" + chr(34) + " if len(text) > width else " + chr(34) + chr(34) + ")")
_M3 = ("M3 只加壳不接线：CLI 摘要不再委派单点（第二份截断实现回归）", "md_cg/review_cli.py",
       [(_CLI_BRIEF, _CLI_OLD)], ("E02",))
_MUTATIONS = (_M1, _M2, _M3)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss71_mut_")
    for name in ("md_cg", "scripts", "data"):     # data/ = 判据所需的非 .py 数据面
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env.update({"PYTHONPATH": tree, "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue71_queue_backlog"],
                        cwd=tree, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(_NL.join(out.splitlines()[-20:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if any(t.count(o) != 1 for o, _n in pairs):
                bad.append(desc)
                print("  ANCHOR-MISS " + desc + " " + str([t.count(o) for o, _n in pairs]))
                continue
            bak = t
            for o, n in pairs:
                t = t.replace(o, n, 1)
            open(p, "w", encoding="utf-8", newline="").write(t)
            for r, dd, ff in os.walk(tree):
                if os.path.basename(r) == "__pycache__":
                    shutil.rmtree(r, ignore_errors=True)
            rc2, reds2, _o2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s 红项=%d 指定命中=%d/%d" % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s 实际=%s 期望=%s rc=%d" % (desc, hit, sorted(exp), rc2))
                for r in reds2[:6]:
                    print("        FAIL " + r)
        ok_r, det_r = GK.assert_revert_reddens(
            # 骨架② 需要 3 元组 (rel, old, new)（2 元组会 ValueError；实测踩过）
            _mirror_build, [("md_cg/mdcos.py",
                             p[0].replace("\r\n", "\n"),
                             p[1].replace("\r\n", "\n"))
                            for p in (_swap(_BL_CTX, _VIS_BYPASS),
                                      _swap(_SR_CTX, _VIS_BYPASS))],
            # 实测：回退两个站点的可见性面 ⇒ B02/B03/B04 三红
            _run_in, ("B02", "B03", "B04"), "md_cg/mdcos.py")
        print("  骨架②回退即红：%s %s" % ("OK" if ok_r else "MISMATCH",
                                          json.dumps(det_r, ensure_ascii=False)[:200]))
        if not ok_r:
            bad.append("骨架②未按预期转红")
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


shutil.rmtree(_TMP, ignore_errors=True)
print("")
print("issue #71 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())