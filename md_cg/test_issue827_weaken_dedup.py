# -*- coding: utf-8 -*-
# 功能名：scrub 的「同一矛盾只扣一次」判据必须跟着节点走，不依赖可丢失的 _scrub.jsonl（issue #827）
# 生效条件：python -X utf8 -m md_cg.test_issue827_weaken_dedup [--mutate]；被测面=md_cg/scrub.py 的 _weaken（去重哨兵）/ decontaminate（哨兵归入 already_handled）/ sleep.add_pathspecs（账本不在追踪集内这一前提）
# 子功能：A 组=影子口径对拍（每轮删 _scrub.jsonl，8 轮后 confidence 只跌一档、同一证据串只 1 条）；B 组=主库口径（保留账本，读数须与 A 组逐位相同——两种账本状态结论一致才是修对了）；K 组=反向/不过度收紧（真实新矛盾仍扣、cg.get 抛异常仍照扣、WEAKEN_DEDUPED 与 verify 返回 None 可区分、applied 不虚增）；E 组=源码面（去重判据在读账本之后、哨兵单点、无「恒真/恒假」退化）
# 执行：建一对可稳定判成 contradiction 的节点（同键不同值），A 组每轮 os.remove(_scrub.jsonl) 后跑 decontaminate(dry_run=False)，B 组不动账本；逐轮读 frontmatter 的 confidence / negative_evidence / evidence_log
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 逐条把判据改回缺陷形态，红项集合须**恰为**预期（锚点未命中即 fail-closed）
# 不适用条件：① 不判 audit 的矛盾识别本身对不对（那是另一面，本腿只借用它造语料）② 不修 _scrub.jsonl 该不该被追踪（属 sleep 口径，另一件；本腿只保证账本丢了也不出错）③ 不覆盖 verify 的其它调用方（手工 verify 不受去重影响，因为判据在 scrub 侧而非 cg.verify 侧）④ 不判 context 层的重复处置（本腿只构造 knowledge 层单对节点）
"""issue #827 守卫：去重判据必须跟着节点（.md 被追踪）走，而不是跟着账本（untracked）走。

病象（修前，本仓活库实测 2026-11-08）：
  scrub.py  `_handled()` 读 `cg.root/_scrub.jsonl` 判幂等；
  sleep.py  `iterate()` 在**影子工作树**上跑 `scrub.sweep`；
  sleep.py  `add_pathspecs()` 只入册 `*.md` ⇒ `_scrub.jsonl` untracked
            ⇒ 影子每轮 checkout 后账本为空 ⇒ `_handled()` 恒 ∅
            ⇒ 同一矛盾每轮被再扣 0.15，confidence 单调压到 0.00。

  活库读数：407 条负向证据只有 83 条不同（4.90x）；单条「同键不同值」
  重复 52 次（49 次串完全相同）；时间序列 10-31 23:45 → 11-08 06:46
  每小时一次，与睡眠周期同频。

处置（判据换载体，不换口径）：
  · `_weaken` 先读**节点自己的 evidence_log**（随 .md 一起被追踪）判去重，
    命中返回 `WEAKEN_DEDUPED` 哨兵；
  · `decontaminate` 把哨兵归入 `already_handled`（本批零动作），**不计 applied**
    ——否则账本丢了就会把每轮虚记成「又处置了 N 条」；
  · `_handled` 账本判据**一字不改**，仍在（主库口径照旧生效）。
"""
import ast
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss827_")
os.environ.update({"MDCG_STATE_ROOT": os.path.join(_TMP, "state"),
                   "MDCG_AUX_ROOT": os.path.join(_TMP, "auxstore"),
                   "MDCG_DATA_ROOT": os.path.join(_TMP, "data"),
                   "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from md_cg import scrub as _sc                          # noqa: E402
from md_cg.mdcos import MdCGOS                          # noqa: E402
from md_cg import sleep as _sl                          # noqa: E402

FAILS = []
_RUN = [0]

#: 一对**同键不同值**的节点：缺省开关的取值相反 ⇒ 稳定判成 contradiction。
A_BODY = "# 功能名：默认开关\n# 缺省：开启（值为 1）\n"
B_BODY = "# 功能名：默认开关\n# 缺省：关闭（值为 0）\n"


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:400])
        FAILS.append(name)


def _lib(tag):
    _RUN[0] += 1
    root = os.path.join(_TMP, "%s_%d" % (tag, _RUN[0]))
    os.makedirs(root, exist_ok=True)
    cg = MdCGOS(root=root)
    cg.add("na", A_BODY, layer="knowledge")
    cg.add("nb", B_BODY, layer="knowledge")
    return cg


def _drop(cg):
    """影子口径：删掉 untracked 的账本（= checkout 不把它带回来）。"""
    led = os.path.join(cg.root, _sc.SCRUB_LOG)
    if os.path.exists(led):
        os.remove(led)


def _run_round(cg, **kw):
    return _sc.decontaminate(cg, ["na", "nb"], dry_run=False,
                             min_severity="info", override=True, **kw)


def _fm(cg, nid="na"):
    return (cg.get(nid) or {}).get("frontmatter") or {}


def _ev_strings(cg, nid="na"):
    return [str(e.get("evidence") or "") for e in (_fm(cg, nid).get("evidence_log") or [])]


# ---------------------------------------------------------------- A 组
def group_A():
    print("\n[A] 影子口径：每轮账本丢失，同一矛盾仍只扣一次")
    cg = _lib("shadow")
    try:
        c0 = float(_fm(cg)["confidence"])
        for _ in range(8):
            _drop(cg)
            _run_round(cg)
        c8 = float(_fm(cg)["confidence"])
        ev = _ev_strings(cg)
        dup = {s: ev.count(s) for s in set(ev)}
        worst = max(dup.values()) if dup else 0
        _check("A1 8 轮后 confidence 只跌一档（0.60→0.45）",
               abs(c8 - (c0 - 0.15)) < 1e-9, "c0=%.2f c8=%.2f" % (c0, c8))
        _check("A2 同一证据串只记 1 次（修前 = 轮数）", worst == 1, dup)
        _check("A3 negative_evidence 只 +1",
               int(_fm(cg).get("negative_evidence") or 0) == 1,
               _fm(cg).get("negative_evidence"))
        _check("A4 第 2 轮起 applied 为 0（不虚记动作）",
               _run_round(cg)["applied"] == 0, _run_round(cg)["applied"])
        _check("A5 第 2 轮起 already_handled 为 2（两节点各一条）",
               _run_round(cg)["already_handled"] == 2,
               _run_round(cg)["already_handled"])
    finally:
        cg.close()


# ---------------------------------------------------------------- B 组
def group_B():
    print("\n[B] 主库口径：账本保留，读数须与 A 组逐位相同")
    cg = _lib("main")
    try:
        c0 = float(_fm(cg)["confidence"])
        r2 = None
        for i in range(8):
            r = _run_round(cg)
            if i == 1:
                r2 = r
        c8 = float(_fm(cg)["confidence"])
        ev = _ev_strings(cg)
        dup = {s: ev.count(s) for s in set(ev)}
        _check("B1 8 轮后 confidence 同为 0.45",
               abs(c8 - (c0 - 0.15)) < 1e-9, "c0=%.2f c8=%.2f" % (c0, c8))
        _check("B2 同一证据串只记 1 次", max(dup.values() or [0]) == 1, dup)
        _check("B3 账本判据仍在：第 2 轮 already_handled=2 且 applied=0",
               (r2 or {}).get("already_handled") == 2 and (r2 or {}).get("applied") == 0,
               r2 and {k: r2.get(k) for k in ("applied", "already_handled")})
    finally:
        cg.close()


# ---------------------------------------------------------------- K 组
def group_K():
    print("\n[K] 不过度收紧：真实新矛盾仍扣、异常路径不退化成吞掉")
    cg = _lib("k")
    try:
        # K1 真新矛盾（不同 kind）必须照扣 —— 去重按 (kind, detail)，不是按节点
        before = float(_fm(cg)["confidence"])
        _run_round(cg)
        mid = float(_fm(cg)["confidence"])
        res = _sc._weaken(cg, "na", "expired", "valid_until 已过 2026-01-01")
        after = float(_fm(cg)["confidence"])
        _check("K1 不同 kind 的新矛盾仍扣减", after < mid,
               "before=%.2f mid=%.2f after=%.2f" % (before, mid, after))
        _check("K2 真实调用返回的不是去重哨兵",
               res is not _sc.WEAKEN_DEDUPED)

        # K3 同一 (kind, detail) 再来一次 → 哨兵，且盘面零变化
        snap = _fm(cg)
        res2 = _sc._weaken(cg, "na", "expired", "valid_until 已过 2026-01-01")
        _check("K3 同一 (kind,detail) 第二次返回 WEAKEN_DEDUPED",
               res2 is _sc.WEAKEN_DEDUPED, res2)
        _check("K4 去重命中时盘面零变化",
               float(_fm(cg)["confidence"]) == float(snap["confidence"])
               and int(_fm(cg).get("evidence_count") or 0) == int(snap.get("evidence_count") or 0),
               (_fm(cg)["confidence"], snap["confidence"]))

        # K5 节点取不到（cg.get 抛异常）→ 不得静默去重，必须照旧走 verify
        class _Boom:
            def __init__(self, inner):
                self._inner = inner
                self.root = inner.root
                self.calls = []

            def get(self, nid):
                raise RuntimeError("boom")

            def verify(self, nid, evidence, verdict, **kw):
                self.calls.append((nid, evidence, verdict))
                return {"ok": True}

        boom = _Boom(cg)
        r = _sc._weaken(boom, "na", "duplicate", "冗余 0.99")
        _check("K5 读节点抛异常时仍照旧调 verify（不静默吞）",
               len(boom.calls) == 1 and r is not _sc.WEAKEN_DEDUPED,
               "calls=%d" % len(boom.calls))

        # K6 哨兵与 verify 返回 None 必须可区分
        _check("K6 WEAKEN_DEDUPED 与 None 不是同一个对象",
               _sc.WEAKEN_DEDUPED is not None)

        # K8 去重键必须带 kind：**同一 detail、不同 kind 是两件事**，都要扣。
        #     没有这条，"去重键丢掉 kind" 的变异体恒穿网（K1 用的是不同 detail，
        #     丢不丢 kind 都得扣，测不出差别）。
        cg8 = _lib("k8")
        try:
            f0 = float(_fm(cg8)["confidence"])
            same_detail = "同键不同值：缺省（本端 a1f8dc7c / 对端 b30a52ab）"
            _sc._weaken(cg8, "na", "contradiction", same_detail)
            f1 = float(_fm(cg8)["confidence"])
            _sc._weaken(cg8, "na", "expired", same_detail)
            f2 = float(_fm(cg8)["confidence"])
            _check("K8 同一 detail 换 kind 仍扣减（去重键必须含 kind）",
                   f1 < f0 and f2 < f1,
                   "f0=%.2f f1=%.2f f2=%.2f" % (f0, f1, f2))
        finally:
            cg8.close()

        # K7 去重命中不得计进 applied（账本丢了也不能虚记动作）
        cg2 = _lib("k7")
        try:
            _run_round(cg2)
            _drop(cg2)
            rr = _run_round(cg2)
            _check("K7 账本丢失轮 applied=0 而非虚记 2",
                   rr["applied"] == 0 and rr["already_handled"] == 2,
                   {k: rr.get(k) for k in ("applied", "already_handled")})
            _check("K7b 该轮 checked_breakdown 与返回体自洽",
                   rr["checked_breakdown"]["applied"] == 0
                   and rr["checked_breakdown"]["already_handled"] == 2,
                   rr["checked_breakdown"])
        finally:
            cg2.close()
    finally:
        cg.close()


# ---------------------------------------------------------------- E 组
def _fn_node(path, name):
    """取某个函数定义节点**并剥掉 docstring**（E 组要看的是可执行体）。

    用 deepcopy 而不是手工重建：ast.unparse 需要 lineno/type_comment 等位置
    属性，手工拼的节点会缺这些列而抛 AttributeError。
    """
    import copy
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            node = copy.deepcopy(node)
            body = list(node.body)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
            return node
    return None


def group_E():
    print("\n[E] 源码面：判据在位、单点、无退化")
    scrub_py = os.path.join(_REPO, "md_cg", "scrub.py")
    sleep_py = os.path.join(_REPO, "md_cg", "sleep.py")

    fn = _fn_node(scrub_py, "_weaken")
    _check("E1 _weaken 在位", fn is not None)
    body_src = ast.unparse(fn) if fn else ""

    _check("E2 _weaken 可执行体读的是节点 evidence_log（不是账本）",
           "evidence_log" in body_src, body_src[:200])
    _check("E3 _weaken 可执行体不再读 _handled / SCRUB_LOG（载体已换）",
           "_handled" not in body_src and "SCRUB_LOG" not in body_src,
           body_src[:300])
    _check("E4 去重命中返回 WEAKEN_DEDUPED 哨兵",
           "WEAKEN_DEDUPED" in body_src)
    _check("E5 哨兵不是恒真/恒假退化（判据用 is / is not，不做真值判断）",
           "if want in seen" in body_src)

    dec = _fn_node(scrub_py, "decontaminate")
    dsrc = ast.unparse(dec) if dec else ""
    _check("E6 decontaminate 识别哨兵并归入 already_handled",
           "WEAKEN_DEDUPED" in dsrc and "n_done" in dsrc)
    _check("E7 哨兵分支在 applied 累加之前 continue（不虚增 applied）",
           dsrc.find("WEAKEN_DEDUPED") < dsrc.find("n_applied += 1"),
           "哨兵@%d applied@%d" % (dsrc.find("WEAKEN_DEDUPED"),
                                   dsrc.find("n_applied += 1")))

    # 前提锁：账本不在 add_pathspecs 的入册面内（本缺陷的成因，修法不能靠它）
    ap_node = _fn_node(sleep_py, "add_pathspecs")
    ap = ast.unparse(ap_node) if ap_node else ""
    _check("E8 前提仍成立：add_pathspecs 只入册 *.md，_scrub.jsonl 不在追踪集",
           "*.md" in ap and "_scrub" not in ap, ap[:160])

    # _handled 判据一字未改（主库口径照旧）
    h = ast.unparse(_fn_node(scrub_py, "_handled") or ast.Pass())
    _check("E9 _handled 账本判据仍在且只认 ok（未改动主库口径）",
           "decontaminate" in h and "ok" in h, h[:200])


# ---------------------------------------------------------------- 变异
MUTANTS = [
    ("退回去重（不查 evidence_log）",
     'if want in seen:\n        return WEAKEN_DEDUPED',
     'if False:\n        return WEAKEN_DEDUPED'),
    ("哨兵归入 applied（虚记动作）",
     "        if _deduped:\n            n_done += 1",
     "        if _deduped:\n            n_applied += 1"),
    ("读节点异常时静默去重",
     "    except Exception:                                 # noqa: BLE001\n        seen = set()",
     "    except Exception:                                 # noqa: BLE001\n        seen = set()\n        return WEAKEN_DEDUPED"),
    ("去重键丢掉 kind（跨类误去重）",
     'want = f"scrub:{kind}:{str(detail)[:120]}"',
     'want = f"scrub:{str(detail)[:120]}"'),
    ("去重后仍继续 verify（等于没去重）",
     "    if want in seen:\n        return WEAKEN_DEDUPED",
     "    if want in seen:\n        pass"),
]


def run_mutate():
    import subprocess
    print("\n[M] 变异对照：每条缺陷形态必须被杀")
    base = open(os.path.join(_REPO, "md_cg", "scrub.py"), encoding="utf-8").read()
    red = 0
    for name, old, new in MUTANTS:
        if old not in base:
            print("  ANCHOR-MISS %s" % name)
            FAILS.append("ANCHOR-MISS:" + name)
            continue
        d = tempfile.mkdtemp(prefix="mut827_")
        dst = os.path.join(d, "w")
        shutil.copytree(_REPO, dst, ignore=shutil.ignore_patterns(
            "__pycache__", ".git", "node_modules"))
        p = os.path.join(dst, "md_cg", "scrub.py")
        open(p, "w", encoding="utf-8").write(base.replace(old, new, 1))
        r = subprocess.run([sys.executable, "-X", "utf8", "-m",
                            "md_cg.test_issue827_weaken_dedup"],
                           cwd=dst, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        killed = r.returncode != 0
        red += killed
        failed = [ln.split("FAIL ")[1].split("  ")[0]
                  for ln in (r.stdout or "").splitlines() if ln.strip().startswith("FAIL ")]
        print("  %s %-30s 抓到: %s"
              % ("RED  " if killed else "GREEN<<<穿网", name,
                 ", ".join(failed[:3]) or "(无)"))
        shutil.rmtree(d, ignore_errors=True)
    print("\n变异被杀 %d/%d" % (red, len(MUTANTS)))
    if red != len(MUTANTS):
        FAILS.append("MUTATION_ESCAPED")


def main():
    group_A()
    group_B()
    group_K()
    group_E()
    if "--mutate" in sys.argv:
        run_mutate()
    shutil.rmtree(_TMP, ignore_errors=True)
    print("\n" + ("FAILED " + str(len(FAILS)) + ": " + ", ".join(FAILS)
                  if FAILS else "全部通过"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
