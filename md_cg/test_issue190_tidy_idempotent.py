# -*- coding: utf-8 -*-
"""整理巡检幂等守卫（issue #190）。

【守什么】
#190 报：MCP 常驻循环缺省每 6h 调 writelimit.tidy_contextual(apply=True)，而它
**不认已整理过的成员**——同一组同模板 contextual 记忆每轮都被再列一遍，保留节点
正文再追加一段「# 整理聚合」、merge_count 再加一遍，成员再降权一次
（0.6→0.3→0.15→0.1）、文件再重写一次。带「# 功能名：X」标题的组会一直这样下去，
保留节点正文线性增长无上限；无标题短记忆则每轮把一个已收敛成员提升成新的保留节点
再追加一遍，直到组里不足 3 条。

复核成立（改前实测，逐字读数见 delivery-20261013/PR190/repro_before.txt，
源 sha256 9cd14ea40d7c21d048306d01fa20aa77f56dbea7ead61a50148f7482f10f1090）：
直造存量同构组（A 无标题短记忆×5 + B 带标题长正文×5，均 importance=0.6）连跑
3 轮 apply=True ⇒
  round1 applied_count=8  变化文件=10  A keep 26→224B merge_count 0→4
  round2 applied_count=7  变化文件=9   B keep 1397→2039B merge_count 4→8
  round3 applied_count=6  变化文件=8   B keep 2039→2681B merge_count 8→12
  成员 importance 0.6→0.3→0.15→0.1（每轮再降一次）

病灶：tidy_contextual 的分组循环只看 layer=="contextual" + template_signature
非空，**没有任何「这节点已整理过」的判据**；已打 tidy:converged / 已置
lifecycle_state="converged" 的成员下一轮照旧入组、照旧 _demote、照旧被写进保留
节点的成员清单。

修法（writelimit.py，最小改动；不新增字段、不改既有键与语义）：
  ① 模块级真源常量 TIDY_TAG = "tidy:converged"，_demote 改用它（带引号字面量
     全文件只剩定义处 1 处）；
  ② 新增纯函数 _already_tidied(e)：tags 含 TIDY_TAG 或
     frontmatter[lifecycle.STATE_FIELD]=="converged" 即为已整理——两者都是修复前
     就已落盘的既有标记，故历史存量天然被认账，无需迁移；
  ③ tidy_contextual 扫描阶段命中即 continue（不进组、不降权、不重写保留节点）；
  ④ 返回 dict 新增键 already_tidied（跳过计数），其余键与语义不变
     （sustain._tick_tidy 消费的 t/scanned/groups/members/applied_count 全在）。
改后实测（逐字读数见 repro_after.txt，源 sha256
65558eedaca089c354f29c534a42477268f4f4c1deda41f4547d7d3c2d8d5f2f）：round1 同改前；
round2/3 planned=[]、applied=[]、applied_count 缺省、**cg.root 全树 0 个文件变化**、
A/B keep 与成员 importance/merge_count 逐字节冻结、节点总数恒 10。

判据：
  S1  结构：TIDY_TAG 单一真源（带引号字面量恰好 1 处）、_already_tidied 纯函数且
      缺字段不抛、无新增第三方依赖、docstring 写明幂等口径与新键。
  S2  ★ 判别力锚：从 git 取**修复前**的 writelimit.py（git log -S 定位引入提交取
      父版本；未提交时回落 HEAD；再逐版本回落「首个不含 _already_tidied 的版本」），
      在同一夹具上连跑 3 轮 ⇒ 改前**确实不幂等**（第 2/3 轮仍有 applied、文件仍在
      变）。取不到修复前源 ⇒ ANCHOR-MISS，退出码 2。
  S3  ★ 幂等核心：连跑 3 轮 apply=True ⇒ 第 2/3 轮 planned=[]/applied=[]/
      applied_count 缺省或 0、**cg.root 全树逐字节不变**、groups==0、
      already_tidied==8、scanned==10。
  S4  第 1 轮确实整理且此后有界：保留节点正文含「整理聚合」与成员 id，读数与改前
      第 1 轮一致（A 224B/9 行/merge_count=4，B 1397B/10 行/4），第 2/3 轮不再变。
  S5  成员降权一次性 + 契约 + 下限：0.6→0.3、tags 含 tidy:converged、
      lifecycle_state=="converged"；第 2/3 轮不再降；0.05 的成员落 0.1（max 下限）。
  S6  存量兼容 + 永不删除：预置「只有 tag」「只有 state」两种历史存量 ⇒ 不报错、
      不再整理、文件逐字节不变、importance 不再减半；两轮后节点 id 集合不变。
  S7  dry-run 零落盘：未整理夹具上 apply=False ⇒ planned 非空、applied 空、盘上
      逐字节不变；整理完再 dry ⇒ groups==0、already_tidied==8、盘上仍不变。
  S8  公开契约：apply/dry 返回键 ⊇ 改前键集（apply 路径新增键只有
      already_tidied）；SustainLoop._tick_tidy 真实调用两次不抛，第 1 次落盘、
      第 2 次零落盘（常驻循环消费面兼容）。
  S9  min_group 与 protected：2 条同模板不 planned；protected 成员不降权、tags
      不变、不计入 applied_count。
  S10 不过度冻结：整理完后再到 3 条同模板新节点 ⇒ 仍会被整理（并入既有保留节点
      wl_b0、converged==3、merge_count 4→7），且并入后再次整理仍零落盘。

运行：python -X utf8 -m md_cg.test_issue190_tidy_idempotent
      python -X utf8 -m md_cg.test_issue190_tidy_idempotent --mutate
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import traceback

_TMP = tempfile.mkdtemp(prefix="i190g_")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import autonomy_modes                     # noqa: E402

# 夹具隔离（同 test_writelimit 的口径）：本守卫考的是读侧整理幂等，不是自治档位；
# 显式置 full 档，让 remember_gated 的写入行为回到「动作直落」。
os.environ[autonomy_modes.AUTONOMY_ENV_KEYS["mode"]] = "full"

from md_cg import lifecycle, writelimit             # noqa: E402
from md_cg.mdcos import MdCGOS                       # noqa: E402

WL = os.path.join(_REPO, "md_cg", "writelimit.py")
PREFIX_MOD = "md_cg._writelimit_prefix190"

# 改前（修复前）tidy_contextual 返回 dict 的键集——从 repro_before.txt 逐字抄来，
# 用作「公开契约不破」的比对基准。
ORIG_APPLY_KEYS = ("t", "actor", "scanned", "groups", "members", "apply",
                   "planned", "applied", "applied_count")
ORIG_DRY_KEYS = ("t", "actor", "scanned", "groups", "members", "apply",
                 "planned", "applied")

_OK = 0
_BAD = []
_SEEN = set()
_N = [0]
_ANCHOR_MISS = []
_PREFIX_INFO = []


def _check(cid, cond, detail=""):
    global _OK
    # 判据 id = 首段（"S3.2 ★ 第 2/3 轮..." → "S3.2"），_GROUPS 按 id 前缀核对是否
    # 真的执行过（防断言组提前中断/静默跳过）。
    cid = cid.split()[0]
    _SEEN.add(cid)
    if cond:
        _OK += 1
        print("  ok   %s" % cid)
    else:
        _BAD.append(cid)
        print("  FAIL %s  %s" % (cid, detail))


# ---------------------------------------------------------------- 夹具与读数

def _mkcg(tag):
    _N[0] += 1
    root = os.path.join(_TMP, "%s_%d" % (tag, _N[0]))
    os.makedirs(root, exist_ok=True)
    return MdCGOS(root)


def _seed(cg, prefix, n, titled, importance=0.6, imps=None,
          tmpl="巡检批次%d收官记忆"):
    """直造存量同构组（照 test_writelimit H 节口径：gated=False 直写）。

    importance 缺省 0.6：<0.7 避开 add 的自动保护位——protected 成员会被 tidy
    跳过，读不到降权读数（实测 importance=0.9 落 protected=True）。
    """
    ids = []
    for i in range(n):
        nid = "%s%d" % (prefix, i)
        body = tmpl % i
        content = ("# 功能名：%s\n" % body + "正文段落" * 60) if titled else body
        imp = importance if imps is None else imps[i]
        cg.remember_gated(nid, content, layer="contextual", gated=False,
                          importance=imp)
        ids.append(nid)
    return ids


def _scenario_ab(tag):
    """存量同构组：A 无标题短记忆×5 + B 带标题长正文×5（均 importance=0.6）。"""
    cg = _mkcg(tag)
    a = _seed(cg, "wl_a", 5, False)
    # B 组标题体与复现脚本逐字一致（"# 功能名：批次N收官记忆"），故第 1 轮保留节点
    # 读数与 repro_before/after.txt 的 1397B/10 行/merge_count=4 可比对。
    b = _seed(cg, "wl_b", 5, True, tmpl="批次%d收官记忆")
    return cg, a, b


def _files(cg):
    """节点文件 sha256（只算 index 里的节点文件）。"""
    out = {}
    for nid, e in list(cg.index["nodes"].items()):
        p = os.path.join(cg.root, e["path"])
        try:
            out[nid] = hashlib.sha256(open(p, "rb").read()).hexdigest()
        except OSError as exc:
            out[nid] = "ERR:%s" % exc
    return out


def _tree(cg):
    """cg.root 下**全部**文件的 sha256（含索引/日志/锁文件）。"""
    out = {}
    for dirpath, _dirs, fns in os.walk(cg.root):
        for fn in fns:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, cg.root).replace("\\", "/")
            try:
                out[rel] = hashlib.sha256(open(p, "rb").read()).hexdigest()
            except OSError as exc:
                out[rel] = "ERR:%s" % exc
    return out


def _diff(before, after):
    return sorted(k for k in set(list(before) + list(after))
                  if before.get(k) != after.get(k))


def _snap(cg, nid):
    e = cg.get(nid) or {}
    fm = e.get("frontmatter") or {}
    body = e.get("content") or ""
    return {"bytes": len(body.encode("utf-8")),
            "lines": body.count("\n") + 1,
            "merge_count": int(fm.get("merge_count") or 0),
            "importance": fm.get("importance"),
            "state": fm.get(lifecycle.STATE_FIELD),
            "tags": list(fm.get("tags") or [])}


def _patch(cg, nid, **fields):
    """就地把节点的 frontmatter 字段改掉（用于注入历史存量标记）。"""
    e = cg.get(nid) or {}
    fm = dict(e.get("frontmatter") or {})
    fm.update(fields)
    cg._write_node(nid, os.path.join(cg.root, e["path"]), fm,
                   e.get("content") or "")
    entry = cg.index["nodes"].get(nid)
    if entry is not None:
        entry.update({"tags": fm.get("tags"),
                      "importance": fm.get("importance"),
                      lifecycle.STATE_FIELD: fm.get(lifecycle.STATE_FIELD)})


def _read_wl():
    with io.open(WL, encoding="utf-8", newline="") as f:
        return f.read()


# ---------------------------------------------------------------- S1 结构

def s1():
    print("== S1 结构：单一真源 / 纯函数 / 无新依赖 / docstring ==")
    src = _read_wl()
    _check('S1.1 模块级真源常量 TIDY_TAG == "tidy:converged"',
           getattr(writelimit, "TIDY_TAG", None) == "tidy:converged",
           repr(getattr(writelimit, "TIDY_TAG", None)))
    n_lit = src.count('"tidy:converged"')
    _check("S1.2 带引号字面量全文件恰好 1 处（_demote 与判据都走常量）",
           n_lit == 1, "count=%d" % n_lit)

    fn = getattr(writelimit, "_already_tidied", None)
    cases = [({}, False),
             ({"frontmatter": None}, False),
             ({"frontmatter": {"tags": None}}, False),
             ({"frontmatter": {"tags": ["tidy:converged"]}}, True),
             ({"frontmatter": {"lifecycle_state": "converged"}}, True),
             ({"frontmatter": {"lifecycle_state": "active", "tags": []}}, False)]
    ok = callable(fn)
    detail = []
    if not ok:
        detail.append("_already_tidied 缺失或不可调用")
    else:
        for e, want in cases:
            try:
                got = bool(fn(e))
            except Exception as exc:                     # noqa: BLE001
                got = "EXC:%s" % exc
            if got is not want:
                ok = False
                detail.append("%r→%r(期望%r)" % (e, got, want))
    _check("S1.3 _already_tidied 纯函数且语义正确（缺 frontmatter/tags 不抛）",
           ok, "；".join(detail))

    mods = set(re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", src, re.M))
    allowed = {"__future__", "hashlib", "json", "os", "re", "time",
               "lifecycle", "protect", "fsutil"}
    _check("S1.4 无新增第三方依赖（顶层 import 全在既有白名单内）",
           mods <= allowed, "多出=%s" % sorted(mods - allowed))

    doc = writelimit.tidy_contextual.__doc__ or ""
    mdoc = writelimit.__doc__ or ""
    _check("S1.5 docstring 写明幂等口径与新键 already_tidied（模块级 + 函数级）",
           "幂等" in doc and "already_tidied" in doc
           and "幂等" in mdoc and "already_tidied" in mdoc)


# ---------------------------------------------------------------- S2 判别力锚

def _git(*args):
    try:
        p = subprocess.run(("git",) + args, cwd=_REPO, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60)
        return p.returncode, p.stdout
    except Exception:                                    # noqa: BLE001
        return 1, b""


def _prefix_source():
    """取修复前的 md_cg/writelimit.py 源码，返回 (text, rev) 或 (None, None)。"""
    f = "md_cg/writelimit.py"
    revs = []
    rc, out = _git("log", "-S", "_already_tidied", "--format=%H", "--", f)
    if rc == 0:
        hits = [x for x in out.decode("utf-8", "replace").split() if x]
        if hits:
            rc2, out2 = _git("rev-parse", hits[0] + "^")
            if rc2 == 0:
                revs.append(out2.decode("utf-8", "replace").strip())
    rc, out = _git("log", "--format=%H", "--", f)
    if rc == 0:
        revs += [x for x in out.decode("utf-8", "replace").split() if x]
    revs.append("HEAD")
    for rev in revs:
        if not rev:
            continue
        rc, blob = _git("show", "%s:%s" % (rev, f))
        # 逐版本回落：只要该版本里没有 _already_tidied，它就是「修复前」。
        if rc == 0 and blob and b"_already_tidied" not in blob:
            return blob.decode("utf-8"), rev
    return None, None


def _load_src_as_module(text, modname):
    """把一段 writelimit.py 源码按包内子模块加载（相对 import 走 md_cg 包）。"""
    path = os.path.join(_TMP, modname.rsplit(".", 1)[-1] + ".py")
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def s2():
    print("== S2 判别力锚：修复前源在同一夹具上确实不幂等 ==")
    src, rev = _prefix_source()
    if not src:
        print("  ANCHOR-MISS S2.1 取不到修复前的 md_cg/writelimit.py（git 不可用？）")
        _ANCHOR_MISS.append("S2")
        _check("S2.1 取到修复前源（git）", False, "ANCHOR-MISS")
        return
    sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
    _PREFIX_INFO.append("修复前源 rev=%s sha256=%s" % (rev, sha))
    print("  修复前源 rev=%s sha256=%s" % (rev, sha))
    _check("S2.1 取到修复前源（git %s，且确实不含幂等判据）" % rev[:8],
           "_already_tidied" not in src and "TIDY_TAG" not in src)
    mod = _load_src_as_module(src, PREFIX_MOD)
    cg, A, B = _scenario_ab("s2")
    f0 = _files(cg)
    r1 = mod.tidy_contextual(cg, apply=True, min_group=3)
    f1 = _files(cg)
    r2 = mod.tidy_contextual(cg, apply=True, min_group=3)
    f2 = _files(cg)
    r3 = mod.tidy_contextual(cg, apply=True, min_group=3)
    f3 = _files(cg)
    _check("S2.2 改前第 1 轮确实整理（applied_count==8、10 个节点文件全变）",
           r1.get("applied_count") == 8 and len(_diff(f0, f1)) == 10,
           "applied_count=%s diff=%d" % (r1.get("applied_count"),
                                         len(_diff(f0, f1))))
    _check("S2.3 ★ 改前第 2 轮仍在写（applied 非空且文件变化）",
           bool(r2.get("applied")) and bool(_diff(f1, f2)),
           "applied=%s diff=%d" % (r2.get("applied"), len(_diff(f1, f2))))
    _check("S2.4 ★ 改前第 3 轮仍在写（applied 非空且文件变化）",
           bool(r3.get("applied")) and bool(_diff(f2, f3)),
           "applied=%s diff=%d" % (r3.get("applied"), len(_diff(f2, f3))))
    _check("S2.5 改前第 3 轮保留节点正文比第 1 轮长（无上限增长）",
           _snap(cg, B[0])["bytes"] > 1397,
           "B keep bytes=%d" % _snap(cg, B[0])["bytes"])


# ---------------------------------------------------------------- S3 幂等核心

def s3():
    print("== S3 幂等核心：第 2/3 轮零落盘 ==")
    cg, A, B = _scenario_ab("s3")
    files0, tree0 = _files(cg), _tree(cg)
    r1 = writelimit.tidy_contextual(cg, apply=True, min_group=3)
    files1, tree1 = _files(cg), _tree(cg)
    r2 = writelimit.tidy_contextual(cg, apply=True, min_group=3)
    files2, tree2 = _files(cg), _tree(cg)
    r3 = writelimit.tidy_contextual(cg, apply=True, min_group=3)
    files3, tree3 = _files(cg), _tree(cg)
    _check("S3.0 第 1 轮确实整理（applied_count==8、10 个节点文件全变）",
           r1.get("applied_count") == 8 and len(_diff(files0, files1)) == 10,
           "applied_count=%s diff=%d" % (r1.get("applied_count"),
                                         len(_diff(files0, files1))))
    _check("S3.1 第 2/3 轮 planned 为空且 applied 为空",
           r2.get("planned") == [] and r2.get("applied") == []
           and r3.get("planned") == [] and r3.get("applied") == [],
           "r2=%s r3=%s" % (r2.get("applied"), r3.get("applied")))
    _check("S3.2 ★ 第 2/3 轮 cg.root 全树逐字节不变（%d 个文件）" % len(tree1),
           tree1 == tree2 and tree2 == tree3,
           "r2 变=%s r3 变=%s" % (_diff(tree1, tree2), _diff(tree2, tree3)))
    _check("S3.3 第 2/3 轮 groups==0、already_tidied==8、scanned==10",
           (r2.get("groups"), r2.get("already_tidied"), r2.get("scanned"))
           == (0, 8, 10)
           and (r3.get("groups"), r3.get("already_tidied"), r3.get("scanned"))
           == (0, 8, 10),
           "r2=%s/%s/%s r3=%s/%s/%s" % (r2.get("groups"),
                                        r2.get("already_tidied"),
                                        r2.get("scanned"), r3.get("groups"),
                                        r3.get("already_tidied"),
                                        r3.get("scanned")))
    _check("S3.4 第 2/3 轮 applied_count 缺省或 0（sustain 用 .get(...,0) 读）",
           r2.get("applied_count", 0) == 0 and r3.get("applied_count", 0) == 0,
           "%s/%s" % (r2.get("applied_count"), r3.get("applied_count")))


# ---------------------------------------------------------------- S4 保留节点有界

def s4():
    print("== S4 保留节点有界：正文与 merge_count 第 2/3 轮不再增长 ==")
    cg, A, B = _scenario_ab("s4")
    writelimit.tidy_contextual(cg, apply=True, min_group=3)
    body_a = (cg.get(A[0]) or {}).get("content") or ""
    body_b = (cg.get(B[0]) or {}).get("content") or ""
    ka1, kb1 = _snap(cg, A[0]), _snap(cg, B[0])
    _check("S4.1 第 1 轮保留节点收编成员清单（含「整理聚合」与成员 id）",
           "整理聚合" in body_a and "wl_a1" in body_a
           and "整理聚合" in body_b and "wl_b1" in body_b)
    _check("S4.2 第 1 轮读数与改前一致（A 224B/9 行/4；B 1397B/10 行/4）",
           (ka1["bytes"], ka1["lines"], ka1["merge_count"]) == (224, 9, 4)
           and (kb1["bytes"], kb1["lines"], kb1["merge_count"]) == (1397, 10, 4),
           "A=%s B=%s" % (ka1, kb1))
    writelimit.tidy_contextual(cg, apply=True, min_group=3)
    writelimit.tidy_contextual(cg, apply=True, min_group=3)
    ka3, kb3 = _snap(cg, A[0]), _snap(cg, B[0])
    _check("S4.3 ★ 第 2/3 轮后保留节点 bytes/lines/merge_count 逐字不变",
           ka3 == ka1 and kb3 == kb1, "A=%s B=%s" % (ka3, kb3))


# ---------------------------------------------------------------- S5 降权一次性

def s5():
    print("== S5 成员降权一次性 + 契约 + 下限 ==")
    cg, A, B = _scenario_ab("s5")
    writelimit.tidy_contextual(cg, apply=True, min_group=3)
    m1 = [_snap(cg, x) for x in A[1:]]
    _check("S5.1 第 1 轮成员 0.6→0.3 + tags 含 tidy:converged + state==converged",
           all(x["importance"] == 0.3 and "tidy:converged" in x["tags"]
               and x["state"] == "converged" for x in m1), str(m1))
    writelimit.tidy_contextual(cg, apply=True, min_group=3)
    writelimit.tidy_contextual(cg, apply=True, min_group=3)
    m3 = [_snap(cg, x) for x in A[1:]]
    _check("S5.2 ★ 第 2/3 轮不再降权（仍 0.3，不是 0.15/0.1）",
           all(x["importance"] == 0.3 for x in m3),
           str([x["importance"] for x in m3]))

    cg2 = _mkcg("s5floor")
    ids = _seed(cg2, "wl_f", 3, False, importance=0.05)
    pre = _snap(cg2, ids[1])["importance"]
    writelimit.tidy_contextual(cg2, apply=True, min_group=3)
    f = [_snap(cg2, x)["importance"] for x in ids[1:]]
    _check("S5.3 importance 下限 0.1（0.05×0.5=0.025 → 0.1）",
           pre == 0.05 and all(x == 0.1 for x in f), "pre=%s post=%s" % (pre, f))


# ---------------------------------------------------------------- S6 存量兼容

def s6():
    print("== S6 存量兼容 + 永不删除 ==")
    cg = _mkcg("s6")
    u = _seed(cg, "wl_u", 3, False)                       # 未整理组
    h1 = _seed(cg, "wl_h", 3, False, tmpl="历史批次%d收官记忆")
    h2 = _seed(cg, "wl_hx", 3, True, tmpl="旧标题批次%d收官记忆")
    # 注入修复前就已落盘的历史标记（模拟老库存量）
    for nid in h1:
        _patch(cg, nid, tags=["tidy:converged"], importance=0.3)
    for nid in h2:
        _patch(cg, nid, tags=[], importance=0.3,
               **{lifecycle.STATE_FIELD: "converged"})
    ids0 = set(cg.index["nodes"])
    hfiles0 = {nid: _files(cg)[nid] for nid in h1 + h2}
    hsnap0 = {nid: _snap(cg, nid) for nid in h1 + h2}
    r1 = writelimit.tidy_contextual(cg, apply=True, min_group=3)
    hfiles1 = {nid: _files(cg)[nid] for nid in h1 + h2}
    hsnap1 = {nid: _snap(cg, nid) for nid in h1 + h2}
    _check("S6.1 历史存量被认账：只整理未整理组（groups==1、already_tidied==6）",
           r1.get("groups") == 1 and r1.get("already_tidied") == 6,
           "groups=%s already_tidied=%s" % (r1.get("groups"),
                                            r1.get("already_tidied")))
    _check("S6.2 ★ 历史存量不再整理：文件逐字节不变、importance 不再减半",
           hfiles0 == hfiles1 and hsnap0 == hsnap1
           and all(_snap(cg, n)["importance"] == 0.3 for n in h1 + h2),
           "变=%s" % _diff(hfiles0, hfiles1))
    body_u = (cg.get(u[0]) or {}).get("content") or ""
    _check("S6.3 未整理组照常整理（applied_count>=2、keep 收编清单）",
           r1.get("applied_count", 0) >= 2 and "整理聚合" in body_u,
           "applied_count=%s" % r1.get("applied_count"))
    writelimit.tidy_contextual(cg, apply=True, min_group=3)
    _check("S6.4 永不删除：两轮后节点 id 集合与初始完全一致（%d 个）"
           % len(ids0), set(cg.index["nodes"]) == ids0,
           "差集=%s" % sorted(ids0 ^ set(cg.index["nodes"])))


# ---------------------------------------------------------------- S7 dry-run

def s7():
    print("== S7 dry-run 零落盘 ==")
    cg, A, B = _scenario_ab("s7")
    t0 = _tree(cg)
    dry = writelimit.tidy_contextual(cg, apply=False)
    t1 = _tree(cg)
    _check("S7.1 ★ apply=False 只盘点不动盘（planned 非空、applied 空、全树不变）",
           bool(dry.get("planned")) and dry.get("applied") == []
           and dry.get("groups") == 2 and t0 == t1, "变=%s" % _diff(t0, t1))
    writelimit.tidy_contextual(cg, apply=True, min_group=3)
    t2 = _tree(cg)
    dry2 = writelimit.tidy_contextual(cg, apply=False)
    t3 = _tree(cg)
    _check("S7.2 ★ 整理后 dry：groups==0、already_tidied==8、全树仍不变",
           dry2.get("groups") == 0 and dry2.get("already_tidied") == 8
           and t2 == t3,
           "groups=%s already_tidied=%s 变=%s"
           % (dry2.get("groups"), dry2.get("already_tidied"), _diff(t2, t3)))


# ---------------------------------------------------------------- S8 公开契约

def s8():
    print("== S8 公开契约：返回键 + sustain 消费面 ==")
    cg, A, B = _scenario_ab("s8")
    dry = writelimit.tidy_contextual(cg, apply=False)
    out = writelimit.tidy_contextual(cg, apply=True, min_group=3)
    _check("S8.1a dry 返回键 ⊇ 改前 dry 键集", all(k in dry for k in ORIG_DRY_KEYS),
           "缺=%s" % [k for k in ORIG_DRY_KEYS if k not in dry])
    # 键集与 already_tidied 语义各用**独立**夹具：若共用上面这个 cg，前一次调用的
    # 副作用会串味（例如「dry 也落盘」这类变异会把与它无关的键集判据一起打红，
    # 变成语义纠缠）。独立夹具让每条判据只测它自己声明的东西。
    cg_k = _mkcg("s8keys")
    _seed(cg_k, "wl_c", 5, False)
    out_k = writelimit.tidy_contextual(cg_k, apply=True, min_group=3)
    _check("S8.1b apply 返回键 ⊇ 改前 apply 键集",
           all(k in out_k for k in ORIG_APPLY_KEYS),
           "缺=%s" % [k for k in ORIG_APPLY_KEYS if k not in out_k])
    _check("S8.1c apply 路径新增键只有 already_tidied",
           set(out_k) - set(ORIG_APPLY_KEYS) == {"already_tidied"},
           "多出=%s" % sorted(set(out_k) - set(ORIG_APPLY_KEYS)))
    cg_d = _mkcg("s8dry")
    _seed(cg_d, "wl_d", 5, False)
    dry0 = writelimit.tidy_contextual(cg_d, apply=False)
    cg_s, A_s, B_s = _scenario_ab("s8skip")
    w1 = writelimit.tidy_contextual(cg_s, apply=True, min_group=3)
    w2 = writelimit.tidy_contextual(cg_s, apply=True, min_group=3)
    _check("S8.1d already_tidied 语义=跳过计数（未整理 0、整理后 8）",
           dry0.get("already_tidied") == 0 and w1.get("already_tidied") == 0
           and w2.get("already_tidied") == 8,
           "dry0=%s w1=%s w2=%s" % (dry0.get("already_tidied"),
                                    w1.get("already_tidied"),
                                    w2.get("already_tidied")))

    from md_cg.sustain import SustainLoop               # noqa: E402
    cg2, A2, B2 = _scenario_ab("s8b")
    lp = SustainLoop(cg2, name="i190g", auto_tidy=True, tidy_interval=111.0,
                     d=os.path.join(cg2.root, "_sustain"))
    lp._tick_tidy()
    rec = lp.last_tidy or {}
    _check("S8.2 SustainLoop._tick_tidy 第 1 次不抛、last_tidy 键齐全（消费面兼容）",
           rec.get("applied_count") == 8 and rec.get("groups") == 2
           and rec.get("members") == 8 and rec.get("scanned") == 10
           and len(lp.tidys) == 1, str(rec))
    lp._tick_tidy()
    rec2 = lp.last_tidy or {}
    _check("S8.3 ★ 常驻循环第 2 次 _tick_tidy 零落盘（applied_count==0、groups==0）",
           rec2.get("applied_count") == 0 and rec2.get("groups") == 0
           and len(lp.tidys) == 2, str(rec2))
    lp.stop()


# ---------------------------------------------------------------- S9 min_group/protected

def s9():
    print("== S9 min_group 与 protected 跳过 ==")
    cg = _mkcg("s9two")
    _seed(cg, "wl_two", 2, False)
    t0 = _tree(cg)
    r = writelimit.tidy_contextual(cg, apply=True, min_group=3)
    t1 = _tree(cg)
    _check("S9.1 min_group=3：2 条同模板不 planned、零落盘",
           r.get("groups") == 0 and r.get("applied") == [] and t0 == t1,
           "groups=%s 变=%s" % (r.get("groups"), _diff(t0, t1)))

    cg2 = _mkcg("s9prot")
    ids = _seed(cg2, "wl_k", 3, False, imps=[0.6, 0.6, 0.8])
    prot = _snap(cg2, ids[2])
    _check("S9.0 夹具前置：importance=0.8 落 protected=True",
           prot["importance"] == 0.8 and prot["tags"] == []
           and (cg2.get(ids[2]) or {}).get("frontmatter", {}).get("protected")
           is True, str(prot))
    r2 = writelimit.tidy_contextual(cg2, apply=True, min_group=3)
    prot2 = _snap(cg2, ids[2])
    _check("S9.2 protected 成员不降权、tags 不变、不计入 applied_count",
           prot2 == prot and r2.get("applied_count") == 1
           and _snap(cg2, ids[1])["importance"] == 0.3,
           "prot=%s applied_count=%s" % (prot2, r2.get("applied_count")))


# ---------------------------------------------------------------- S10 不过度冻结

def s10():
    print("== S10 不过度冻结：整理后再到 3 条同模板新节点仍会被整理 ==")
    cg, A, B = _scenario_ab("s10")
    writelimit.tidy_contextual(cg, apply=True, min_group=3)
    b0 = _snap(cg, B[0])
    new = _seed(cg, "wl_n", 3, True, tmpl="批次%d收官记忆")
    r2 = writelimit.tidy_contextual(cg, apply=True, min_group=3)
    b1 = _snap(cg, B[0])
    # 新到的 3 条与 B 组同模板 ⇒ 并入**既有**保留节点 wl_b0（它仍是该签名组里
    # 最早的活跃节点），而不是另立 keep——这是「新成员照常整理」的判据；
    # 同时它必须只被扩写一次，之后再次整理零落盘（不因新成员回到每轮重写）。
    _check("S10.1 ★ 新到 3 条同模板节点仍被整理（groups==1、并入既有 keep wl_b0、converged==3）",
           r2.get("groups") == 1
           and [(a["keep"], a["converged"]) for a in r2.get("applied") or []]
           == [("wl_b0", 3)],
           "groups=%s applied=%s" % (r2.get("groups"), r2.get("applied")))
    _check("S10.2 ★ 既有保留节点只被扩写一次（bytes/lines 增、merge_count 4→7）",
           b1["bytes"] > b0["bytes"] and b1["lines"] > b0["lines"]
           and b1["merge_count"] == 7, "%s → %s" % (b0, b1))
    _check("S10.3 三条新成员被降权（0.6→0.3）",
           all(_snap(cg, x)["importance"] == 0.3 for x in new),
           "new=%s" % [_snap(cg, x)["importance"] for x in new])
    t2 = _tree(cg)
    r3 = writelimit.tidy_contextual(cg, apply=True, min_group=3)
    t3 = _tree(cg)
    _check("S10.4 ★ 并入新成员后再次整理仍零落盘（planned/applied 空、全树不变）",
           r3.get("planned") == [] and r3.get("applied") == [] and t2 == t3,
           "applied=%s 变=%s" % (r3.get("applied"), _diff(t2, t3)))


_GROUPS = (
    (s1, ("S1.1", "S1.2", "S1.3", "S1.4", "S1.5")),
    (s2, ("S2.1", "S2.2", "S2.3", "S2.4", "S2.5")),
    (s3, ("S3.0", "S3.1", "S3.2", "S3.3", "S3.4")),
    (s4, ("S4.1", "S4.2", "S4.3")),
    (s5, ("S5.1", "S5.2", "S5.3")),
    (s6, ("S6.1", "S6.2", "S6.3", "S6.4")),
    (s7, ("S7.1", "S7.2")),
    (s8, ("S8.1a", "S8.1b", "S8.1c", "S8.1d", "S8.2", "S8.3")),
    (s9, ("S9.0", "S9.1", "S9.2")),
    (s10, ("S10.1", "S10.2", "S10.3", "S10.4")),
)


def _run_groups():
    global _OK
    _OK = 0
    _BAD.clear()
    _SEEN.clear()
    for g, ids in _GROUPS:
        try:
            g()
        except Exception as exc:                         # noqa: BLE001
            print("  断言组 %s 抛异常：%s" % (g.__name__, exc))
            print(traceback.format_exc()[-600:])
        for cid in ids:
            if cid not in _SEEN:
                _SEEN.add(cid)
                _BAD.append(cid)
                print("  FAIL %s  未执行（断言组提前中断/静默跳过）" % cid)
    return len(_BAD)


def main():
    print("整理巡检幂等守卫（issue #190）")
    print("writelimit.py sha256=%s" % hashlib.sha256(
        open(WL, "rb").read()).hexdigest())
    for line in _PREFIX_INFO:
        print(line)
    n = _run_groups()
    print()
    if _ANCHOR_MISS:
        print("ANCHOR-MISS：%s（取不到修复前源，判别力无法自证）"
              % "、".join(_ANCHOR_MISS))
    print("整理巡检幂等守卫（issue #190）：通过 %d / 失败 %d" % (_OK, n))
    if _ANCHOR_MISS:
        return 2
    return 1 if n else 0


# ---------------------------------------------------------------- 定点变异自证

_MUTATIONS = (
    ("V1 幂等判据被短路（#190 病象回归）",
     "        if _already_tidied(e):\n",
     "        if _already_tidied(e) and False:\n",
     # 期望红项=幂等判据失效的全部下游读数：第 2/3 轮仍在写（S3.*）、保留节点
     # 继续增长（S4.3）、成员继续降权（S5.2）、历史存量不被认账（S6.1/S6.2）、
     # 整理后 dry 仍报组（S7.2）、跳过计数恒 0（S8.1d）、常驻循环第 2 次仍落盘
     # （S8.3）、新成员并入时整组重并（S10.1/S10.2/S10.4）。S10.3 仍绿（降权本身
     # 没坏），S3.0/S4.2/S5.1/S5.3/S9.* 仍绿（第 1 轮行为与跳过面无关）。
     ("S3.1", "S3.2", "S3.3", "S3.4", "S4.3", "S5.2", "S6.1", "S6.2",
      "S7.2", "S8.1d", "S8.3", "S10.1", "S10.2", "S10.4")),
    ("V2 成员不再打 tidy:converged tag",
     "    if TIDY_TAG not in tags:\n        tags.append(TIDY_TAG)\n",
     "    if False:\n        tags.append(TIDY_TAG)\n",
     ("S5.1",)),
    ("V3 单一真源退化（_demote 内改用字面量）",
     "    if TIDY_TAG not in tags:\n        tags.append(TIDY_TAG)\n",
     '    if "tidy:converged" not in tags:\n'
     '        tags.append("tidy:converged")\n',
     ("S1.2",)),
    ("V4 dry-run 也落盘（apply 判据被摘）",
     "    if not apply or not planned:\n",
     "    if not planned:\n",
     ("S7.1",)),
    ("V5 降权丢掉 0.1 下限",
     'round(max(0.1, float(fm.get("importance", 0.5)',
     'round(max(0.0, float(fm.get("importance", 0.5)',
     ("S5.3",)),
    ("V6 protected/immutable 成员不再跳过",
     '            if mfm.get("protected") or mfm.get("immutable"):\n',
     "            if False:\n",
     ("S9.2",)),
)


def _reload():
    import md_cg.writelimit as _w
    # 变异若与上一版**等长**且落在同一个 mtime 秒内，Python 会按
    # (mtime_seconds, size) 判定 __pycache__ 里的 .pyc「仍然有效」，reload 于是
    # 加载陈旧字节码（实测 V5：max(0.1,→max(0.0, 等长，S5.3 假绿）。故先删缓存
    # 再 reload，并用 _live_ok() 事后核对变异确实进了内存。
    try:
        cache = importlib.util.cache_from_source(_w.__file__)
        if os.path.exists(cache):
            os.remove(cache)
    except Exception:                                    # noqa: BLE001
        pass
    importlib.invalidate_caches()
    importlib.reload(_w)
    globals()["writelimit"] = _w


def _live_ok():
    """内存里的 writelimit 是否就是盘上那份变异源码编译出来的（防空转变异）。"""
    src = _read_wl()
    ns = {"__name__": "md_cg._i190live", "__package__": "md_cg", "__file__": WL}
    try:
        exec(compile(src, WL, "exec"), ns)               # noqa: S102
    except Exception as exc:                             # noqa: BLE001
        return "COMPILE-FAIL:%s" % exc
    for name, obj in ns.items():
        cur = getattr(writelimit, name, None)
        if callable(obj) and callable(cur) \
                and getattr(obj, "__code__", None) is not None \
                and getattr(cur, "__code__", None) is not None \
                and obj.__code__.co_code != cur.__code__.co_code:
            return "STALE:%s" % name
    return ""


def _mutate():
    bad = []
    with io.open(WL, encoding="utf-8", newline="") as f:
        pristine = f.read()
    if "_already_tidied" not in pristine:
        print("  SOURCE-ALREADY-MUTATED：writelimit.py 缺 _already_tidied")
        return 1
    for name, anchor, repl, want in _MUTATIONS:
        with io.open(WL, encoding="utf-8", newline="") as f:
            orig = f.read()
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        try:
            if a_ not in orig:
                print("  ANCHOR-MISS %s" % name)
                _ANCHOR_MISS.append(name)
                bad.append(name)
                continue
            with io.open(WL, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            _reload()
            stale = _live_ok()
            if stale:
                print("  LIVE-CHECK-FAIL %s：%s（变异未进入内存，本次读数不可信）"
                      % (name, stale))
                bad.append(name)
                continue
            _run_groups()
            reds = sorted(set(_BAD))
            want_s = sorted(set(want))
            ok = reds == want_s
            print("  变异 %s" % name)
            print("       期望红项=%s" % (",".join(want_s) or "（无）"))
            print("       实测红项=%s" % (",".join(reds) or "（无）"))
            print("       %s" % ("OK 恰好命中" if ok else "BAD 红项集合不符"))
            if not ok:
                bad.append(name)
        finally:
            with io.open(WL, "w", encoding="utf-8", newline="") as f:
                f.write(pristine)
            with io.open(WL, encoding="utf-8", newline="") as f:
                if f.read() != pristine:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
            _reload()
    if bad:
        print()
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        if _ANCHOR_MISS:
            print("ANCHOR-MISS：%s" % "、".join(_ANCHOR_MISS))
            return 2
        return 1
    print()
    print("定点变异自证：PASS（每条变异恰好打红期望判据集合）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
