# -*- coding: utf-8 -*-
"""scripts/check_placeholder_leak.py —— 占位符泄漏守卫（fail-closed）

# 功能名：占位符泄漏守卫——扫文本产物里**未替换的构造占位符**（命中即退出码 1）
# 生效条件：凡交付 .md/.py/.json/.html 产物前；凡把长文本经占位符构造再落盘时；
#           凡接入 pre-commit / resolve 链时。触发语=占位符泄漏、落盘前自检。
# 子功能：① 扫给定根（判据面**默认限定 git 追踪面**，见 issue #200）② 命中即逐处点名
#         （文件:行:列 + 上下文）③ 退出码 fail-closed（命中=1）
#         ④ **不自指**（占位符由字符拼出，源码里不出现字面量）
# 执行：python -X utf8 scripts/check_placeholder_leak.py [--root DIR ...] [--exclude PATH ...]
#       [--include-untracked] [--list-surface] [--selftest]
# 验证方式：含泄漏的临时树上跑 ⇒ 退出码 1 且逐处点名；本仓跑 ⇒ 退出码 0 并打印扫描面与排除项；
#          `--selftest` ⇒ 正/反例覆盖各判据分支（含 fail-closed），抓不到或假绿即退出 1
# 2026-10-17 修（本笔）：
#   ① 同一行**多处**占位符只记第一处（`line.find` 只取一次）⇒ 改为循环 find，兑现「逐处点名」；
#   ② 不存在的根 / 空判据面（0 个文件）原返回 0「零命中 ✓」⇒ 假绿；改为 fail-closed 退出 2；
#   ③ 新增 `--selftest`（本笔之前该件**无任何自证入口**，被 check_guard_coverage 登记为孤儿例外）。
# 不适用条件：不适用于 _protected_history 等**审计快照**（默认排除——记录的是当时真实状态，
#            改了毁审计）；不适用于 hive/jobs 运行态记录与提交信息里**引用**该字样处
#            （那是引用不是泄漏）；不适用于**未追踪**的复审/临时文档（见 issue #200）。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile

#: 节标记（用字符拼出，**避免源码里出现字面占位符** ⇒ 守卫不自指）。
_SEC = "\u00a7"

#: 需要守的占位符（构造长文本时的临时记号；落盘前必须全部替换）。
PLACEHOLDERS = (_SEC + "BT" + _SEC, _SEC + "NL" + _SEC)

#: 默认不扫的**路径前缀**（相对根）——**逐条有理由**，不是「看不见就算了」。
DEFAULT_EXCLUDE = (
    ".git", "node_modules", "target", "__pycache__", "dist", "build", ".venv",
    ".tmp",
    "hive/jobs",           # 蜂巢运行态记录：会**引用**占位符字样（如提交信息原文）
    "_protected_history",  # 审计快照：记录当时真实状态，改了反而毁审计
    "trash",               # 软删区
    "_md_cg_p27",          # 非活动实验库（历史遗留，待使用者裁定）
)

#: 只扫这些后缀（文本产物）。
SUFFIXES = (".md", ".py", ".json", ".html", ".yml", ".yaml", ".txt", ".ts", ".js")

#: 判据面默认**限定 git 追踪面**（issue #200）。
#:
#: 根因：本守卫原本 os.walk 整个文件系统，于是**任何「描述该守卫自身」的文档都会
#: 让它转红** —— 因为这类文档必须**引用占位符字面量**作为示例（自我指涉不可避免，
#: 不是文档写错）。实测：把一个 42 份复审报告的**未追踪**目录放进仓库树 ⇒ 4 处命中，
#: 全部来自报告本身；移出后立即恢复 0 命中。
#:
#: 修法：判据面 = git ls-files 的文本件。未追踪的复审/临时文档不再污染判据；
#: 而**追踪进仓库的文档**若引用占位符仍会被抓 —— 那是应该抓的。
#: 需要「新写但还没 add 的发布件」也入判据时，显式加 --include-untracked。
TRACKED_BY_DEFAULT = True


def _git_tracked(root: str):
    """git 追踪面（相对 root 的路径列表）；**不可用返回 None**（调用方须响亮回退）。"""
    try:
        chk = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                             cwd=root, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        if chk.returncode != 0 or (chk.stdout or "").strip() != "true":
            return None
        p = subprocess.run(["git", "ls-files", "-z"], cwd=root,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
    except Exception:                                          # noqa: BLE001
        return None
    if p.returncode != 0:
        return None
    return [x for x in (p.stdout or "").split("\0") if x]


def _excluded(rel: str, exclude) -> bool:
    rel = rel.replace(os.sep, "/")
    for ex in exclude:
        ex = ex.replace(os.sep, "/").strip("/")
        if rel == ex or rel.startswith(ex + "/") or ("/" + ex + "/") in ("/" + rel):
            return True
    return False


def _scan_file(path: str, rel: str):
    """扫单个文件 → [(相对路径, 行号, 列号, 占位符, 该行前 120 字)]。

    ★ 2026-10-17 修：同一行有**多处**占位符时，旧实现 `line.find(ph)` 只记第一处
      （实测：一行两个占位符只报 1 处，总数少算）⇒ 改为循环 find，
      兑现 docstring 里「逐处点名」的承诺。
    """
    hits = []
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for ln, line in enumerate(fh, 1):
                for ph in PLACEHOLDERS:
                    start = 0
                    while True:
                        col = line.find(ph, start)
                        if col < 0:
                            break
                        hits.append((rel.replace(os.sep, "/"), ln, col + 1, ph,
                                     line.strip()[:120]))
                        start = col + len(ph)
    except Exception:                                          # noqa: BLE001
        pass
    return hits


def scan(root: str, exclude, tracked: bool = True):
    """扫 root → (hits, 判据面口径, **实际扫到的文件数**)。

    ★ 2026-10-17 补：第三个返回值是「判据面大小」——空判据面（0 个文件）不得
      当成「零命中 ✓」（fail-closed；见 main）。
    """
    hits = []
    n_files = 0
    root = os.path.abspath(root)
    files = _git_tracked(root) if tracked else None
    if files is not None:
        for rel in files:
            rel = rel.replace(os.sep, "/")
            if not rel.endswith(SUFFIXES):
                continue
            if _excluded(rel, exclude):
                continue
            n_files += 1
            hits.extend(_scan_file(os.path.join(root, rel), rel))
        return hits, "tracked", n_files
    for dp, dn, fn in os.walk(root):
        rel_dir = os.path.relpath(dp, root)
        dn[:] = [d for d in dn if not _excluded(os.path.join(rel_dir, d), exclude)]
        if _excluded(rel_dir, exclude):
            continue
        for f in fn:
            if not f.endswith(SUFFIXES):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root)
            if _excluded(rel, exclude):
                continue
            n_files += 1
            hits.extend(_scan_file(p, rel))
    return hits, "filesystem", n_files


def _git_run(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)


def _make_repo(path, files):
    """建临时 git 仓并提交给定文件；`files={}` ⇒ 空仓（无提交）。"""
    os.makedirs(path, exist_ok=True)
    r = _git_run(path, "init", "-q")
    if r.returncode != 0:
        raise RuntimeError("git init 失败：%s" % (r.stderr or r.stdout))
    for rel, text in files.items():
        p = os.path.join(path, rel)
        parent = os.path.dirname(p)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with io.open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    if not files:
        return
    _git_run(path, "add", "-A")
    r = _git_run(path, "-c", "user.name=selftest",
                 "-c", "user.email=selftest@example.com", "commit", "-qm", "selftest")
    if r.returncode != 0:
        raise RuntimeError("git commit 失败：%s" % (r.stderr or r.stdout))


def _scan_quiet(*args):
    """跑 main 并吞掉打印 → (退出码, 输出)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(list(args))
    return rc, buf.getvalue()


def selftest() -> int:
    """仪器自证：每类判据喂正例/反例；**抓不到或假绿就红**。

    覆盖的判据分支（2026-10-17 补）：
      ① 单处泄漏被抓；② **同一行多处**全部点名（修前只记第一处）；
      ③ 排除前缀生效；④ 默认判据面不含未追踪，`--include-untracked` 口径能抓到；
      ⑤ 有泄漏 ⇒ 1；⑥ `--list-surface` ⇒ 0（诊断）；⑦ **不存在的根 ⇒ 2**（修前假绿 0）；
      ⑧ **空判据面 ⇒ 2**（修前假绿 0）；⑨ 真干净 ⇒ 0；⑩ 守卫自身源码零命中。
    """
    ph = PLACEHOLDERS[0]
    passed = failed = 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print("  [PASS] " + name)
        else:
            failed += 1
            print("  [FAIL] " + name + ("  —— " + detail if detail else ""))

    base = tempfile.mkdtemp(prefix="phs_selftest_")
    try:
        repo = os.path.join(base, "repo")
        _make_repo(repo, {
            "hit.md": "ok " + ph + "\n",
            "dupe.md": ph + " / " + ph + "\n",
            "clean.md": "clean\n",
            "trash/skip.md": ph + "\n",
        })
        with io.open(os.path.join(repo, "untracked.md"), "w", encoding="utf-8") as f:
            f.write(ph + "\n")

        hits, surface, n = scan(repo, set(DEFAULT_EXCLUDE))
        by_file = {}
        for rel, _ln, _col, _p, _ctx in hits:
            by_file[rel] = by_file.get(rel, 0) + 1
        check("判据面=tracked", surface == "tracked", surface)
        check("文件数=3（trash 排除、untracked 不计）", n == 3, "n=%d" % n)
        check("单处文件命中 1", by_file.get("hit.md") == 1, str(by_file))
        check("同一行两处全部点名（修前只记 1）", by_file.get("dupe.md") == 2, str(by_file))
        check("排除前缀生效（trash/skip.md 不计）", "trash/skip.md" not in by_file,
              str(by_file))
        check("默认判据面不含未追踪", "untracked.md" not in by_file, str(by_file))

        hits2, _surface2, _n2 = scan(repo, set(DEFAULT_EXCLUDE), tracked=False)
        check("--include-untracked 口径能抓到未追踪",
              "untracked.md" in {h[0] for h in hits2})

        rc, _out = _scan_quiet("--root", repo)
        check("有泄漏 ⇒ 退出码 1", rc == 1, "rc=%d" % rc)
        rc, _out = _scan_quiet("--root", repo, "--list-surface")
        check("--list-surface ⇒ 退出码 0（诊断用）", rc == 0, "rc=%d" % rc)

        rc, _out = _scan_quiet("--root", os.path.join(repo, "no_such_root"))
        check("不存在的根 ⇒ 退出码 2（修前假绿 0）", rc == 2, "rc=%d" % rc)

        empty = os.path.join(base, "empty_repo")
        _make_repo(empty, {})
        rc, _out = _scan_quiet("--root", empty)
        check("空判据面 ⇒ 退出码 2（修前假绿 0）", rc == 2, "rc=%d" % rc)

        toml_only = os.path.join(base, "toml_only")
        _make_repo(toml_only, {"notes.toml": "x\n"})     # 不在 SUFFIXES ⇒ 空判据面
        rc, _out = _scan_quiet("--root", toml_only)
        check("只有非判据后缀 ⇒ 退出码 2（空判据面，不假绿）", rc == 2, "rc=%d" % rc)

        clean = os.path.join(base, "clean_repo")
        _make_repo(clean, {"clean.md": "clean\n"})
        rc, _out = _scan_quiet("--root", clean)
        check("真干净 ⇒ 退出码 0", rc == 0, "rc=%d" % rc)

        own = _scan_file(os.path.abspath(__file__), "check_placeholder_leak.py")
        check("守卫自身源码零命中（不自指）", own == [], str(own[:2]))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("占位符守卫自证：%d 通过 / %d 失败" % (passed, failed))
    print("自证结论：%s" % ("通过（每条判据都喂了负例）" if not failed
                          else "未通过 —— 守卫有盲区，不当绿"))
    return 0 if not failed else 1


def main(argv=None):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="占位符泄漏守卫（命中即退出码 1）")
    ap.add_argument("--root", action="append", default=None, help="扫描根（可多次；缺省=本仓根）")
    ap.add_argument("--exclude", action="append", default=None, help="额外排除的路径前缀（可多次）")
    ap.add_argument("--include-untracked", action="store_true",
                    help="判据面含未追踪文件（旧行为；issue #200 的缺陷形态）")
    ap.add_argument("--list-surface", action="store_true",
                    help="只打印判据面口径与文件数，不判红（诊断用）")
    ap.add_argument("--selftest", action="store_true",
                    help="★ 仪器自证：正/反例覆盖各判据分支（含 fail-closed）")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    roots = args.root or [here]
    bad = [r for r in roots if not os.path.isdir(r)]
    if bad:
        print("!! 扫描根不存在：%s —— 判据面无法确认；按 fail-closed 退出 2"
              % ", ".join(bad))
        return 2
    exclude = set(DEFAULT_EXCLUDE) | set(args.exclude or ())
    want_tracked = TRACKED_BY_DEFAULT and not args.include_untracked
    total = 0
    scanned = 0
    surfaces = []
    empty = []
    for r in roots:
        hits, surface, n = scan(r, exclude, tracked=want_tracked)
        surfaces.append((r, surface, n))
        scanned += n
        if n == 0:
            empty.append(r)
        total += len(hits)
        if hits:
            print("!! 占位符泄漏 %d 处（%s，判据面=%s）" % (len(hits), r, surface))
            for rel, ln, col, ph, ctx in hits:
                print("   %s:%d:%d  %s   | %s" % (rel, ln, col, ph, ctx))
    if args.list_surface:
        for r, surface, n in surfaces:
            print("判据面：%s -> %s（%d 个文件）%s"
                  % (r, surface, n, "  [空判据面]" if n == 0 else ""))
        return 0
    if total:
        print("=> 共 %d 处未替换占位符：落盘前必须全部替换（退出码 1）" % total)
        return 1
    if empty:
        print("!! 判据面为空：%s —— 0 个文件被扫 ⇒ **未验证，不当绿**（退出码 2）"
              % ", ".join(empty))
        return 2
    print("占位符守卫：%d 个根零命中 ✓（共扫 %d 个文件）" % (len(roots), scanned))
    for r, surface, _n in surfaces:
        print("   判据面：%s" % surface)
        if surface == "filesystem":
            print("   !! 回退告警：%s 不在 git 工作树内（或 git 不可用），"
                  "本次按**全盘 walk** 判据 —— 未追踪文档会污染判据（issue #200）" % r)
    print("   排除前缀：%s" % ",".join(sorted(exclude)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
