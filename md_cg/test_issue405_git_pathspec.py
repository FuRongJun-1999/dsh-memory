# -*- coding: utf-8 -*-
# 功能名：sleep 的入册面与判据面必须与自述对象一致（issue #405）
# 生效条件：python -X utf8 -m md_cg.test_issue405_git_pathspec [--mutate]；被测面＝md_cg/sleep.py 的 add pathspec 单点（add_pathspecs）、§4.5 判据一（history_forbidden_hits 的中缀形态）、reconcile_and_commit 的按根取库与绑定闸
# 子功能：A 组＝层目录内非 .md/临时件不得进入 git 索引（站点 1）；B 组＝判据一必须命中 .tmp- 中缀形态（站点 2，经**他途入册**独立构造）；C 组＝reconcile_and_commit 不得跨根提交（站点 3）；E 组＝结构性（add 单点、pathspecs 既有形态不动、绑定闸覆盖登记）；骨架①② + 双向变异
# 执行：--mutate 时在镜像树里回缺陷（add 用层名）/ 过度（连 .md 也挡掉）/ 判据回退 / 站点 3 回退，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；变异与骨架红项集合须与预期逐项相符
# 不适用条件：**不改写既有历史**（不可逆面：Lead 已裁「不做 filter-branch」；真库现存 3 条 .md 目标的临时件已另立只读取证）；不判 audit_tracking 是否该把「非 .md 被追踪」计红（属判据扩面，需维护者裁——本件只在 E 组登记该观察）；不判 reconcile_gated 是否补绑定闸（它与站点 3 **不同形**：已传 root，见 E05 登记）；不判 Windows 之外 git 版本的 pathspec 语义差异（本机实跑为准）
"""issue #405 守卫：授权面不得宽于应有面，且判据必须覆盖真实命名。

病象（修前）：① `_stage_and_commit` 用 `pathspecs(root)`（**层目录名**）作 `git add` 的
pathspec ⇒ 层目录内的非 `.md` 件（原子写临时件 `.<name>.md.tmp-<rand>`、运行态、手工投放件）
一并入册并提交进 `lib.git` **不可逆历史**；② §4.5 判据一用 `endswith(".tmp")` 判，而真实临时件
的 `.tmp-` 是**中缀** ⇒ 对真实形态零命中（两条机械判据同时报绿）；③ `reconcile_and_commit`
不传 root 取库/影子、且无绑定闸 ⇒ 调用方以为「为 B 根对账」，实际提交到 A 根且 ok=True。

修法：① 新增 add 专用单点 `add_pathspecs`（`:(glob)<层>/**/*.md`），**不动** `pathspecs()` 的
既有形态（`test_sleep.py:220` 钉住它返回层名）；② 判据一补 `FORBIDDEN_INFIXES`（中缀）；
③ 站点 3 按 root 取库/影子 + 接 `_bind_error`（#295 同款）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import _guard_kit as GK       # noqa: E402
from md_cg import sleep as SL            # noqa: E402
from md_cg.mdcos import MdCGOS           # noqa: E402

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss405_")
_Q = chr(34)


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _git(G, *args):
    p = subprocess.run(["git", "--git-dir=" + G] + list(args), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", shell=False,
                       timeout=180)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _fixture(tag, n_md=1, nonmd=()):
    """合成根（含 .md）+ 一个层目录内的非 .md/临时件；返回 (root, state, G, SH)。"""
    base = os.path.join(_TMP, tag)
    root = os.path.join(base, "lib")
    state = os.path.join(base, "state")
    os.makedirs(root, exist_ok=True)
    os.makedirs(state, exist_ok=True)
    cg = MdCGOS(root)
    for i in range(n_md):
        cg.add("n_%d" % i, "# 功能：N%d" % i + chr(10) + "# 执行：无", layer="knowledge")
    cg.flush()
    cg.close()
    for nm in nonmd:
        d = os.path.join(root, "knowledge", os.path.dirname(nm))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(root, "knowledge", nm), "w", encoding="utf-8") as f:
            f.write("非 .md 内容")
    G = os.path.join(state, "sleep", "lib.git")
    SH = os.path.join(state, "sleep", "shadow")
    return root, state, G, SH


print("== A 组：层目录内非 .md / 临时件不得进入 git 索引（站点 1） ==")
_root, _state, _G, _SH = _fixture("a", n_md=1, nonmd=(".junk.md.tmp-k1lled", "raw.bin"))
try:
    _m = SL.materialize(root=_root, git_dir_path=_G, shadow=_SH, ts="A1")
except Exception as _e:          # 缺陷/变异导致异常 ⇒ 如实记成 A01 失败（守卫不得崩掉：
    _m = {"ok": False,            # 崩掉的守卫既不报红也不给读数）
          "error": "%s: %s" % (type(_e).__name__, _e)}
_rc, _ls = _git(_G, "--work-tree=" + _root, "ls-files")
_tracked = [l.strip() for l in _ls.splitlines() if l.strip()]
_check("A01 物化成功（前置）", _m.get("ok") is True, {k: _m.get(k) for k in ("ok", "error")})
_check("A02 索引里**只有 .md**（修前：.junk.md.tmp-k1lled 与 raw.bin 一并入册）",
       bool(_tracked) and all(p.endswith(".md") for p in _tracked), _tracked)
_check("A03 临时件未被追踪（点名断言）",
       not any(".tmp-" in p for p in _tracked), _tracked)
_check("A04 add 的 pathspec 是 .md glob（单点形态）：层名仍在 pathspecs、add 走 add_pathspecs",
       SL.pathspecs(_root) == ["knowledge"]
       and SL.add_pathspecs(_root) == [":(glob)knowledge/**/*.md"],
       (SL.pathspecs(_root), SL.add_pathspecs(_root)))
_check("A05 真源面 .md 仍全部被追踪（不过度收紧）",
       set(SL.source_face_hashes(_root)) <= set(_tracked),
       (sorted(SL.source_face_hashes(_root)), _tracked))

print("== B 组：判据一必须覆盖 .tmp- 中缀（站点 2，独立构造） ==")
_rcb, _outb = _git(_G, "--work-tree=" + _root, "add", "--force",
                   "knowledge/.junk.md.tmp-k1lled")
_rcb2, _cb = _git(_G, "--work-tree=" + _root, "commit", "-m", "他途入册（模拟）")
_hits = SL.history_forbidden_hits(_root, git_dir_path=_G)
_hi = SL.audit_history(_root, git_dir_path=_G)
_check("B01 历史里确实进了该临时件（他途入册的前置成立）",
       any(".tmp-" in p for p in SL.history_paths(_root, git_dir_path=_G)), _hits)
_check("B02 判据一命中 .tmp- 中缀形态（修前：endswith 判 ⇒ 零命中）",
       any(".tmp-" in p for p in _hits), _hits)
_check("B03 audit_history 因该命中而 ok=False（修前两条判据同时报绿）",
       _hi.get("ok") is False, {k: _hi.get(k) for k in ("ok", "hits", "scanned")})

print("== C 组：reconcile_and_commit 不得跨根提交（站点 3） ==")
_rootA, _stateA, _GA, _SHA = _fixture("cA", n_md=1)
_rootB, _stateB, _GB, _SHB = _fixture("cB", n_md=1)
_mA = SL.materialize(root=_rootA, git_dir_path=_GA, shadow=_SHA, ts="C1")
_rc3, _A_commits_before = _git(_GA, "rev-list", "--count", "--all")
_r_rc = SL.reconcile_and_commit(root=_rootB, git_dir_path=_GA, shadow=_SHA,
                                branch=_mA.get("branch"), batch="B轮")
_rc4, _A_commits_after = _git(_GA, "rev-list", "--count", "--all")
_check("C01 前置：A 根物化成功", _mA.get("ok") is True, {k: _mA.get(k) for k in ("ok", "error")})
_check("C02 为 B 根对账、却指向 A 根库 ⇒ 必须拒（绑定闸；修前会提交到 A 且 ok=True）",
       _r_rc.get("ok") is False and "另一个记忆根" in str(_r_rc.get("error")),
       {k: _r_rc.get(k) for k in ("ok", "error", "git_dir")})
_check("C03 A 根的提交数**未**因这次调用前进（不可逆副作用未发生）",
       _A_commits_before == _A_commits_after, (_A_commits_before, _A_commits_after))
# 不显式给库时同理：本例 A/B 两根**同槽**（_slot_root 派生相同）⇒ 解析到同一条 lib.git，
# 正因如此**绑定闸是必需的一道**（否则跨根提交在任何同槽场景下都不可见）。
# C04/C05（**不做隐式端到端**，如实登记原因）：不传 git_dir_path 时按 state_root 解析——实测
# 该解析会落到**全局槽**（`<state_root>/sleep/lib.git`），即「拿真库做实验」，与
# 「不可逆面不擅动」冲突（本守卫首版曾如此调用；已只读核验**真库未被写入**：无 B轮2 提交、
# reflog 未前进）。⇒ 该两条腿**移到 E 组**（那里才有 _S 源码面）做构造性断言。


print("== E 组：结构性 ==")
_S = open(os.path.join(_REPO, "md_cg", "sleep.py"), encoding="utf-8").read()
_check("C04 构造性（自 C 组移入）：git_dir / shadow_dir 均**按 root** 解析（形参含 root、体内分支用它）",
       "def git_dir(explicit: str = None, root: str = None)" in _S
       and "def shadow_dir(explicit: str = None, root: str = None)" in _S
       and "if root:" in _S.split("def git_dir")[1].split("def ")[0]
       and "if root:" in _S.split("def shadow_dir")[1].split("def ")[0])
_check("C05 风险登记：隐式形态会落**全局槽** ⇒ 守卫不跑该 e2e（防拿真库做实验）",
       True)
_check("E01 add 走 add_pathspecs 单点，且**不再**用层名直接 add",
       "aps = add_pathspecs(work_tree)" in _S and "add" + _Q + ", " + _Q + "--" + _Q
       and "add -- " + "*ps" not in _S.replace(chr(10), " "))
_check("E02 pathspecs 形态未被改动（既有裁定 test_sleep.py:220 钉住层名）",
       "def pathspecs(root: str) -> list:" in _S
       and "out.append(layer)" in _S.split("def pathspecs")[1].split("def ")[0])
_check("E03 判据一含中缀常量并参与判定",
       "FORBIDDEN_INFIXES = (" in _S
       and "any(x in base for x in FORBIDDEN_INFIXES)" in _S)
_RC = _S.split("def reconcile_and_commit")[1].split("def ")[0]
_check("E04 站点 3 体内：按 root 取库/影子 + 绑定闸三行俱在（该函数级判据，不数全文件）",
       "G = git_dir_path or git_dir(root=root)" in _RC
       and "S = shadow or shadow_dir(root=root)" in _RC
       and "_be = _bind_error(G, root)" in _RC,
       (_RC.count("_bind_error"), _RC.count("root=root")))
_RG = _S.split("def reconcile_gated")[1].split("def ")[0]
_E05_A = "G = git_dir_path or git_dir(root=root)" in _RG
_E05_B = "_bind_error" not in _RG
_check("E05 同族登记：reconcile_gated 与站点 3 **不同形**（已传 root、无绑定闸）——本件不扩面，只登记",
       _E05_A and _E05_B, (_E05_A, _E05_B))

print("== 骨架①：枚举完备性（add 的 pathspec 形态） ==")


def _discover(texts):
    """守卫自己的枚举：命中「用**裸层名/目录名**作 git add pathspec」的函数。"""
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
            if _Q + "add" + _Q not in seg or "--" not in seg:
                continue
            if "add_pathspecs" in seg or ":(glob)" in seg or "_stage_set" in seg:
                continue
            hits.append((rel, node.lineno))
    return hits


_OLD_ADD = (
    "def _stage_and_commit(g, w, m):" + chr(10)
    + "    ps = pathspecs(w)" + chr(10)
    + "    _git_ok(g, w, " + _Q + "add" + _Q + ", " + _Q + "--" + _Q + ", *ps)" + chr(10)
    + "    return ps")
_NEW_ADD = (
    "def _stage_and_commit(g, w, m):" + chr(10)
    + "    aps = add_pathspecs(w)" + chr(10)
    + "    _git_ok(g, w, " + _Q + "add" + _Q + ", " + _Q + "--" + _Q + ", *aps)" + chr(10)
    + "    return aps")
_ok_e, _det_e = GK.assert_enumeration_complete(
    _discover,
    [("应命中·旧形态（裸层名作 add pathspec）", _OLD_ADD, True, "sleep_old.py"),
     ("不应命中·新形态（.md glob 单点）", _NEW_ADD, False, "sleep_new.py"),
     ("不应命中·无关函数", "def other():" + chr(10) + "    return 1", False, "x.py")])
_check("E06 骨架①枚举完备性（应命中/不应命中两侧）", _ok_e, _det_e)

print("== 骨架② / 变异 ==")
_NL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "sleep.py"),
                                   "rb").read()[:8192] else "\n"


def _j(*lines):
    return _NL.join(lines)


_ADD_HUNK = _j("    aps = add_pathspecs(work_tree)",
               "    if aps:",
               "        _git_ok(git_dir_path, work_tree, " + _Q + "add" + _Q + ", " + _Q + "--" + _Q + ", *aps)")
_ADD_OLDHUNK = _j("    if ps:",
                  "        _git_ok(git_dir_path, work_tree, " + _Q + "add" + _Q + ", " + _Q + "--" + _Q + ", *ps)")
_M1 = ("M1 回缺陷：add 用裸层名（非 .md 件重新入册）", "md_cg/sleep.py",
       # E01 亦红（该变异把单点调用整行去掉 ⇒ 源码面判据如实报警）
       [(_ADD_HUNK, _ADD_OLDHUNK)], ("A02", "A03", "E01"))
# M2 取**过度收紧**方向：glob 写成不匹配 .md 的形态 ⇒ 该入册的 .md 反而进不去
_M2 = ("M2 过度：glob 改 .txt（该入册的 .md 被挡掉）", "md_cg/sleep.py",
       [(_j('                out.append(":(glob)%s/**/*.md" % layer)'),
         _j('                out.append(":(glob)%s/**/*.txt" % layer)'))],
       # A04 亦红（glob 形态断言如实报警：.txt 不是 .md 单点形态）
       ("A01", "A02", "A04", "A05"))
_M3 = ("M3 判据回退：去掉中缀判据（.tmp- 漏报）", "md_cg/sleep.py",
       [(_j("                or any(x in base for x in FORBIDDEN_INFIXES)):"),
         _j("                ):"))], ("B02", "B03", "E03"))
_M4 = ("M4 站点 3 回退：不按 root 取库/影子", "md_cg/sleep.py",
       [(_j("    G = git_dir_path or git_dir(root=root)",
           "    S = shadow or shadow_dir(root=root)",
           "    _be = _bind_error(G, root)          # #295 同款绑定闸（同文件另外四入口均已接）",
           "    if _be:",
           "        return {" + _Q + "ok" + _Q + ": False, " + _Q + "busy" + _Q + ": False, " + _Q + "lock_held" + _Q + ": False,",
           "                " + _Q + "phase" + _Q + ": " + _Q + "reconcile_and_commit" + _Q + ", " + _Q + "error" + _Q + ": _be, " + _Q + "git_dir" + _Q + ": G}"),
         _j("    G = git_dir_path or git_dir()",
            "    S = shadow or shadow_dir()"))], ("C02", "E04"))
_MUTATIONS = (_M1, _M2, _M3, _M4)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss405_mut_")
    for name in ("md_cg", "scripts", "data"):     # data/ ＝ 判据所需的非 .py 数据面
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
                         "md_cg.test_issue405_git_pathspec"],
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
            print(chr(10).join(out.splitlines()[-20:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if any(t.count(o) != 1 for o, _n in pairs):
                bad.append("%s 锚点命中 %s" % (desc, [t.count(o) for o, _n in pairs]))
                print("  ANCHOR-MISS " + desc)
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
            _mirror_build, [("md_cg/sleep.py",
                             _ADD_HUNK.replace("\r\n", "\n"),
                             _ADD_OLDHUNK.replace("\r\n", "\n"))],
            _run_in, ("A02", "A03", "E01"), "md_cg/sleep.py")
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
print("issue #405 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
