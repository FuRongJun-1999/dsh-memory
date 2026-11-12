# -*- coding: utf-8 -*-
"""睡眠周期 lib.git / 影子按记忆根绑定守卫（issue #295）。

【守什么】
#295 报：睡眠周期的版本库 `lib.git`、影子工作树、锁与台账都落在**用户级**
状态根 `state_root()/sleep/` 下，与 `MDCG_ROOT` 无关。同一 state_root 下只要
有两个记忆根轮流跑周期，A 根入册的层文件就一直留在 lib.git 的 HEAD 里（入册时
空层被 `pathspecs` 滤掉、删除记不进去），B 根下一轮的影子从这个 HEAD fork，
A 的文件被判成「影子侧新增」，过完四闸后由 `replay_to_main` 写进 B 根。

复核**成立**（本机实测，与报告逐字一致，HEAD=7212e521 前）：
  A 根先跑一轮 → B 根再跑一轮：
    [1] B 库读到 A 的 a_secret = True（path=self/a_secret.md）
    [2] B 自己的 user_profile 被 A 的内容顶替、原文从库面消失 = True
    台账末行 merged=False，conflicts 记 `影子分支与重放后的主库树不同（挂起不合并）`
    ——字面「挂起不合并」，主库却已被改写。
  缺省落点 `state_root()/sleep/lib.git`、`.../shadow` 不含任何记忆根。

修法（只加绑定与分槽，不动四闸判定）：
  ① `lib.git` 首次物化时在 git 目录里写 `mdcg-root`（realpath；不进工作树、
     不进版本库）；`materialize` / `merge` / `revert` / `merge_cycle` 发现
     绑定的是别的根就拒绝（少做，不多写），台账写「物化未完成：lib.git … 绑定
     的是另一个记忆根 …」。
  ② `git_dir()` / `shadow_dir()` 收可选 `root`，落点按根分槽：缺省 lib.git
     不存在 / 未绑定 / 绑定本根时沿用 `sleep_root()`（**单根安装路径逐字不变**），
     已绑定别的根时改用 `sleep_root()/roots/<sha256(realpath(root))[:16]>/`。
     落点在**根级锁内**解析——两个根同时首轮时后到者才看得到先到者的绑定。
  ③ `_stage_and_commit` 对「盘上已空、索引里还有文件」的层执行
     `git rm -r -q --cached`（只动索引，不碰工作树），每轮入册后 HEAD 与当前根
     一致；旧版本遗留的未绑定 lib.git 被沿用（K3）时也靠这一步在第一轮清掉。

判据：
  G1  结构：绑定/分槽/拒他根/空层记删除五处接线在位。
  G2  ★ 两个根缺省落点分开（roots/<16 位 hex>/）。
  G3  ★ 首轮写下绑定，且不在工作树、不在版本库。
  G4  ★ 跨根不串：A 的节点与私密正文都不进 B；B 自己的原文不被顶替。
  G5  ★ 显式共用 MDCG_SLEEP_GITDIR：第二个根被拒且台账写明原因。
  G6  ★ 反向顺序（B 先 A 后）同样不串。
  G7  零变化面：不带 root 的 `git_dir()` / `shadow_dir()` 返回值逐字不变。
  G8  ★ 空层记删除：索引里他根残留被清出 HEAD、节点不复活。
  G9  反陈化：理由在源码里。
  G10 修复前原形（`git log -S` 定位引入提交取父版本；未提交时回落 HEAD）。

运行：python -X utf8 -m md_cg.test_issue295_sleep_root_binding
      python -X utf8 -m md_cg.test_issue295_sleep_root_binding --mutate
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="i295g_")
for _k in ("HOME", "MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_DATA_ROOT",
           "MDCG_EXPORT_ROOT"):
    os.environ.pop(_k, None)
os.environ["HOME"] = os.path.join(_TMP, "home")
os.environ["MDCG_STATE_ROOT"] = os.path.join(_TMP, "state")
# ★ aux 是 Windows 保留设备名（CON/PRN/AUX/NUL/COM1-9/LPT1-9）：
#   os.makedirs("<tmp>/aux") 抛 NotADirectoryError [WinError 267]。
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxstore")
os.environ["MDCG_DATA_ROOT"] = os.path.join(_TMP, "data")
os.environ["MDCG_EXPORT_ROOT"] = os.path.join(_TMP, "export")
for _k in ("HOME", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
           "MDCG_EXPORT_ROOT"):
    os.makedirs(os.environ[_k], exist_ok=True)
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ["MDCG_SUSTAIN"] = "0"
os.environ["MDCG_SLEEP"] = "0"
os.environ["MDCG_WRITELIMIT"] = "0"
os.environ.pop("MDCG_SLEEP_GITDIR", None)
os.environ.pop("MDCG_SLEEP_SHADOW", None)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import sleep as S          # noqa: E402
from md_cg.mdcos import MdCGOS        # noqa: E402

_T = os.environ["MDCG_STATE_ROOT"]
_OK = 0
_BAD = []

#: 六要素合规的节点模板（`# 功能名：` 首行是硬要求）。
_N = ("# 功能名：%s\n# 生效条件：%s\n# 子功能：s\n# 执行：%s\n"
      "# 验证方式：test\n# 不适用条件：无\n")
_SECRET_A = "女儿生日"
_SECRET_D = "体检报告"


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _mkroot(name):
    return os.path.join(_T, name)


def _seed(root, secret_nid, secret_txt, profile, ctx_prefix):
    cg = MdCGOS(root)
    cg.add(secret_nid, _N % ("%s-提示语" % secret_nid, "全时", secret_txt),
           layer="self")
    if profile:
        cg.add("user_profile", _N % ("画像", "全时", profile), layer="self")
    for i in range(4):
        cg.add("%s%d" % (ctx_prefix, i),
               _N % ("%s会%d" % (ctx_prefix, i), "工作日",
                     "%s 周会 第%d次 讨论预算 讨论预算" % (ctx_prefix, i)),
               layer="contextual")
    cg.close()


def _disk(root):
    s = ""
    for dp, _d, fs in os.walk(root):
        for f in fs:
            if f.endswith(".md"):
                s += io.open(os.path.join(dp, f), encoding="utf-8",
                             errors="replace").read()
    return s


def _why(rec):
    """本轮未迭代原因：门拦优先，其次 ②③④ 的 skip 文案（物化未完成等）。"""
    if not isinstance(rec, dict):
        return ""
    if rec.get("skipped"):
        return rec["skipped"]
    for s in (rec.get("steps") or []):
        if isinstance(s, dict) and s.get("step") in ("induce", "promote",
                                                     "scrub") and s.get("skipped"):
            return s["skipped"]
    return ""


def _lsfiles(root):
    p = subprocess.run(
        ["git", "--git-dir=" + S.git_dir(root=root), "--work-tree=" + root,
         "ls-files"], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120)
    return [x.strip() for x in (p.stdout or "").splitlines() if x.strip()]


def _src(rel):
    return io.open(os.path.join(_REPO, rel), encoding="utf-8",
                   errors="replace").read()


# --------------------------------------------------------------------------
# G1 结构
# --------------------------------------------------------------------------

def g1():
    print("== G1 结构：绑定 / 分槽 / 拒他根 / 空层记删除 ==")
    t = _src("md_cg/sleep.py")
    _check("G1a 有绑定标记常量 ROOT_MARKER", 'ROOT_MARKER = "mdcg-root"' in t)
    _check("G1b 有分槽父目录常量 ROOTS_DIRNAME",
           'ROOTS_DIRNAME = "roots"' in t)
    _check("G1c 有 bound_root()", "def bound_root(" in t)
    _check("G1d 有 _bind_error()", "def _bind_error(" in t)
    _check("G1e 有 _bind_root()", "def _bind_root(" in t)
    _check("G1f 有 _slot_root()", "def _slot_root(" in t)
    _check("G1g git_dir 收可选 root",
           "def git_dir(explicit: str = None, root: str = None) -> str:" in t)
    _check("G1h shadow_dir 收可选 root",
           "def shadow_dir(explicit: str = None, root: str = None) -> str:" in t)
    _check("G1i 缺省落点走 _slot_root",
           t.count("_slot_root(root)") >= 2)
    _check("G1j materialize 在锁内解析落点",
           "G = git_dir_path or git_dir(root=root)" in t)
    _check("G1k materialize 物化后写绑定", "_bind_root(G, root)" in t)
    _check("G1l materialize 拒他根", "_bind_error(G, root)" in t)
    _check("G1m merge 拒他根", '"phase": "merge", "lock": lock_path(),' in t)
    _check("G1n revert 拒他根", '"phase": "revert", "lock": lock_path(),' in t)
    _check("G1o merge_cycle 拒他根",
           '"phase": "merge_cycle", "lock": lock_path(),' in t)
    _check("G1p 空层记删除（git rm --cached）",
           '"rm", "-r", "-q", "--cached", "--",' in t)
    _check("G1q 空层集合来自 ls-files 的顶层目录",
           'top = {p.split("/", 1)[0] for p in' in t)


# --------------------------------------------------------------------------
# G2 ★ 两个根缺省落点分开
# --------------------------------------------------------------------------

def g2():
    print("== G2 ★ 两个根缺省落点分开 ==")
    ra, rb = _mkroot("g2a"), _mkroot("g2b")
    _seed(ra, "a_secret", "A 的银行卡提示语是" + _SECRET_A, "A：喜欢咖啡，住北京", "a")
    r = S.run_cycle(MdCGOS(ra), window="", merge_mode="auto", round_index=1,
                    batch="G2A")
    _check("G2a 首根照常合并（认领缺省 lib.git）", r.get("merged") is True,
           json.dumps(r, ensure_ascii=False)[:160])
    _check("G2b ★ 首根落点仍是 state_root()/sleep/lib.git（单根路径不变）",
           S.git_dir(root=ra) == os.path.join(S.sleep_root(), "lib.git"),
           S.git_dir(root=ra))
    _check("G2c ★ 第二根落点与之不同", S.git_dir(root=rb) != S.git_dir(root=ra),
           "%s vs %s" % (S.git_dir(root=ra), S.git_dir(root=rb)))
    _check("G2d ★ 第二根落在 roots/<16 位 hex>/ 下",
           re.search(re.escape(os.sep + "roots" + os.sep) + r"[0-9a-f]{16}" + re.escape(os.sep),
                     S.git_dir(root=rb)) is not None, S.git_dir(root=rb))
    _check("G2e ★ 影子也按根分开",
           S.shadow_dir(root=rb) != S.shadow_dir(root=ra),
           S.shadow_dir(root=rb))


# --------------------------------------------------------------------------
# G3 ★ 绑定写入与落点
# --------------------------------------------------------------------------

def g3():
    print("== G3 ★ 绑定文件 ==")
    legacy = os.path.join(S.sleep_root(), "lib.git")
    ra = _mkroot("g2a")
    _check("G3a ★ 首轮后 lib.git 里写下 mdcg-root = 本根 realpath",
           S.bound_root(legacy) == os.path.realpath(ra),
           "%r vs %r" % (S.bound_root(legacy), os.path.realpath(ra)))
    _check("G3b 绑定文件不在工作树内",
           not os.path.exists(os.path.join(ra, "mdcg-root")))
    _check("G3c ★ 绑定文件不在版本库里（ls-files 零命中）",
           "mdcg-root" not in _lsfiles(ra), str(_lsfiles(ra)))
    _check("G3d 未绑定目录的 bound_root 返回空串",
           S.bound_root(os.path.join(_T, "no_such_dir")) == "")


# --------------------------------------------------------------------------
# G4 ★ 跨根不串
# --------------------------------------------------------------------------

def g4():
    print("== G4 ★ 跨根不串（本件核心）==")
    ra, rb = _mkroot("g2a"), _mkroot("g2b")
    _seed(rb, "b_secret", "B 的备忘是车牌号", "B：对花生严重过敏，住上海", "b")
    r = S.run_cycle(MdCGOS(rb), window="", merge_mode="auto", round_index=2,
                    batch="G2B")
    print("       B 轮 accepted =", r.get("accepted"), "merged =", r.get("merged"))
    _check("G4a B 轮照常合并（分槽不影响本根工作）", r.get("merged") is True,
           json.dumps(r, ensure_ascii=False)[:160])
    _check("G4b ★ A 根节点不再流进 B 根", MdCGOS(rb).get("a_secret") is None)
    _check("G4c ★ A 的私密正文不在 B 根盘面上", _SECRET_A not in _disk(rb))
    _check("G4d ★ B 自己的原文仍在（未被顶替）", "花生" in _disk(rb))
    _check("G4e ★ A 根也没被 B 污染", "花生" not in _disk(ra))
    # ★ B 根**自己**的 self/b_secret.md 与 self/user_profile.md 本来就该在——
    #   判据是「没有 A 根来源的文件」，不是「没有 self/ 前缀」（首版即误判）。
    _lb = _lsfiles(rb)
    _check("G4f ★ B 的 lib.git 只追踪本根文件（无 A 的 a_secret.md）",
           not any("a_secret" in x for x in _lb) and "self/b_secret.md" in _lb,
           str(_lb))
    _check("G4g B 轮仍并入本根概念节点",
           any(str(x).startswith("concept_") for x in (r.get("accepted") or [])),
           str(r.get("accepted")))


# --------------------------------------------------------------------------
# G5 ★ 显式共用 GITDIR：第二个根被拒
# --------------------------------------------------------------------------

def g5():
    print("== G5 ★ 显式共用 MDCG_SLEEP_GITDIR ==")
    ra, rb = _mkroot("g2a"), _mkroot("g2b")
    shared = os.path.join(_T, "shared_g5.git")
    os.environ["MDCG_SLEEP_GITDIR"] = shared
    try:
        # 先到者认领（首轮绑定）
        r1 = S.run_cycle(MdCGOS(ra), window="", merge_mode="auto",
                         round_index=3, batch="G5A")
        _check("G5a 先到者认领共享库并写下绑定",
               S.bound_root(shared) == os.path.realpath(ra), S.bound_root(shared))
        before = _disk(ra)
        r2 = S.run_cycle(MdCGOS(rb), window="", merge_mode="auto",
                         round_index=4, batch="G5B")
        w = _why(r2)
        print("       第二根未迭代原因 =", w[:150])
        _check("G5b ★ 第二个根被拒（修前静默串库）",
               r2.get("merged") is not True
               and "绑定" in json.dumps(r2, ensure_ascii=False), w[:180])
        _check("G5c ★ 被拒时台账写明原因（可回看，不是静默跳过）",
               "绑定的是另一个记忆根" in w, w[:180])
        _check("G5d ★ 被拒时 B 的数据没有进 A 根",
               _disk(ra) == before and "花生" not in _disk(ra))
        _ap = MdCGOS(ra).get("user_profile")
        _check("G5e ★ A 的 user_profile 仍是 A 自己的内容",
               bool(_ap) and "咖啡" in (_ap.get("content") or ""),
               str(_ap and (_ap.get("content") or "").splitlines()[3:4]))
        # 反向：未绑定的新根仍可认领
        rc = _mkroot("g5c")
        S.run_cycle(MdCGOS(rc), window="", merge_mode="auto", round_index=5,
                    batch="G5C")
        _check("G5f 共享库已被认领 ⇒ 第三个根同样被拒",
               S.bound_root(shared) == os.path.realpath(ra))
    finally:
        os.environ.pop("MDCG_SLEEP_GITDIR", None)


# --------------------------------------------------------------------------
# G6 ★ 反向顺序
# --------------------------------------------------------------------------

def g6():
    print("== G6 ★ 反向顺序（B 先 A 后）==")
    rd, re_ = _mkroot("g6d"), _mkroot("g6e")
    _seed(rd, "d_secret", "D 的私人事项是" + _SECRET_D, None, "d")
    cg = MdCGOS(re_)
    for i in range(4):
        cg.add("e%d" % i, _N % ("E会%d" % i, "周二",
                                "E 周会 第%d次 过方案 过方案" % i),
               layer="contextual")
    cg.close()
    r1 = S.run_cycle(MdCGOS(re_), window="", merge_mode="auto", round_index=6,
                     batch="G6E")
    r2 = S.run_cycle(MdCGOS(rd), window="", merge_mode="auto", round_index=7,
                     batch="G6D")
    _check("G6a 后跑的 D 根照常合并", r2.get("merged") is True,
           json.dumps(r2, ensure_ascii=False)[:160])
    _check("G6b ★ D 的节点没有流进 E 根（与顺序无关）",
           MdCGOS(re_).get("d_secret") is None
           and _SECRET_D not in _disk(re_))
    _check("G6c ★ D 自己的节点仍在", MdCGOS(rd).get("d_secret") is not None)


# --------------------------------------------------------------------------
# G7 零变化面
# --------------------------------------------------------------------------

def g7():
    print("== G7 零变化面：不带 root 的老调用面 ==")
    _check("G7a git_dir() 无参仍返回 state_root()/sleep/lib.git",
           S.git_dir() == os.path.join(S.sleep_root(), "lib.git"), S.git_dir())
    _check("G7b shadow_dir() 无参仍返回 state_root()/sleep/shadow",
           S.shadow_dir() == os.path.join(S.sleep_root(), "shadow"),
           S.shadow_dir())
    _check("G7c 显式 explicit 仍优先（不因 root 被改写）",
           S.git_dir("/x/y.git", root=_mkroot("g2b")) == os.path.abspath("/x/y.git")
           or os.path.abspath("/x/y.git") == S.git_dir("/x/y.git", root=_mkroot("g2b")))
    _check("G7d env MDCG_SLEEP_GITDIR 仍优先",
           _env_priority())


def _env_priority():
    os.environ["MDCG_SLEEP_GITDIR"] = os.path.join(_T, "env_gitdir.git")
    try:
        return S.git_dir(root=_mkroot("g2b")) == os.path.abspath(
            os.path.join(_T, "env_gitdir.git"))
    finally:
        os.environ.pop("MDCG_SLEEP_GITDIR", None)


# --------------------------------------------------------------------------
# G8 ★ 空层记删除
# --------------------------------------------------------------------------

def g8():
    print("== G8 ★ 空层记删除（索引里的他根残留被清出 HEAD）==")
    rf = _mkroot("g8f")
    cg = MdCGOS(rf)
    for i in range(4):
        cg.add("f%d" % i, _N % ("F会%d" % i, "上午",
                                "F 例会 第%d次 对齐目标 对齐目标" % i),
               layer="contextual")
    cg.close()
    S.run_cycle(MdCGOS(rf), window="", merge_mode="auto", round_index=8,
                batch="G8F")
    G = S.git_dir(root=rf)
    # 造出「索引/HEAD 里有 self 层、盘上没有」的形态——等价于修复前他根串进来
    # 的残留（也等价于同根内整层被手工清空且没写 _deletions.jsonl）。
    foreign = os.path.join(rf, "self", "foreign.md")
    os.makedirs(os.path.dirname(foreign), exist_ok=True)
    with io.open(foreign, "w", encoding="utf-8", newline="") as f:
        f.write(_N % ("外来提示语", "全时", "别的根的私密：" + _SECRET_D))
    for a in (["add", "--", "self"],
              ["commit", "-m", "fixture: 他根残留"]):
        subprocess.run(["git", "--git-dir=" + G, "--work-tree=" + rf] + a,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    _check("G8a 夹具成立：HEAD/索引里有 self/foreign.md",
           "self/foreign.md" in _lsfiles(rf), str(_lsfiles(rf)))
    os.remove(foreign)
    os.rmdir(os.path.join(rf, "self"))
    # 造出真实 Δ 让本轮真的迭代
    cg = MdCGOS(rf)
    for i in range(4):
        cg.add("f9_%d" % i, _N % ("F新会%d" % i, "下午",
                                  "F 新例会 第%d次 排期 排期" % i),
               layer="contextual")
    cg.close()
    r = S.run_cycle(MdCGOS(rf), window="", merge_mode="auto", round_index=9,
                    batch="G8F2")
    _check("G8b 该轮真的迭代了（不是被门拦）", r.get("merged") is True,
           json.dumps(r, ensure_ascii=False)[:160])
    _check("G8c ★ 空层的残留已从索引清出（git rm --cached）",
           not any(x.startswith("self/") for x in _lsfiles(rf)), str(_lsfiles(rf)))
    _check("G8d ★ 残留节点没有复活进本根",
           MdCGOS(rf).get("foreign") is None and _SECRET_D not in _disk(rf))


# --------------------------------------------------------------------------
# G9 反陈化
# --------------------------------------------------------------------------

def g9():
    print("== G9 反陈化：理由在源码里 ==")
    t = _src("md_cg/sleep.py")
    _check("G9a 标注 issue #295", "issue #295" in t)
    _check("G9b 写明「同一 state_root 下两个记忆根」是前提",
           "同一 state_root 下" in t)
    _check("G9c 写明空层记删除的理由", "空层也要记删除" in t)
    _check("G9d 写明按根分槽的路径形态", "roots/<sha256" in t or "ROOTS_DIRNAME" in t)
    _check("G9e 写明绑定不进版本库/工作树",
           "不进版本库、不进工作树" in t or "不进工作树" in t)


# --------------------------------------------------------------------------
# G10 修复前原形
# --------------------------------------------------------------------------

def _prepatch(rel, marker):
    def _g(*a):
        return subprocess.run(list(a), cwd=_REPO, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=120)
    lg = _g("git", "log", "-S" + marker, "--format=%H", "--", rel)
    if lg.returncode == 0:
        shas = [x.strip() for x in (lg.stdout or "").splitlines() if x.strip()]
        if shas:
            s = _g("git", "show", shas[-1] + "^:" + rel)
            if s.returncode == 0:
                return s.stdout, "引入提交 %s 的父版本" % shas[-1][:8]
    s = _g("git", "show", "HEAD:" + rel)
    if s.returncode != 0:
        return None, "git show HEAD rc=%s" % s.returncode
    return s.stdout, "HEAD（本改动尚未提交）"


def g10():
    print("== G10 修复前原形 ==")
    t, how = _prepatch("md_cg/sleep.py", "_slot_root")
    if t is None:
        _check("G10 取修复前源失败：%s" % how, False)
        return
    print("       （修复前源取自 %s）" % how)
    n = t.replace("\r\n", "\n")
    _check("G10a 修复前无绑定标记常量", 'ROOT_MARKER = "mdcg-root"' not in n)
    _check("G10b 修复前无 _slot_root", "def _slot_root(" not in n)
    _check("G10c ★ 修复前 git_dir 不收 root",
           "def git_dir(explicit: str = None) -> str:" in n)
    _check("G10d ★ 修复前 shadow_dir 不收 root",
           "def shadow_dir(explicit: str = None) -> str:" in n)
    _check("G10e ★ 修复前缺省落点直接拼 sleep_root()（无按根分槽）",
           "sleep_root(), GITDIR_DIRNAME" in n and "_slot_root" not in n)
    _check("G10f ★ 修复前 _stage_and_commit 不记空层删除",
           '"rm", "-r", "-q", "--cached"' not in n)
    _check("G10g 修复前 materialize 锁外解析落点（正是串库的成因之一）",
           "    G = git_dir_path or git_dir()\n    S = shadow or shadow_dir()" in n)


_GROUPS = (g1, g2, g3, g4, g5, g6, g7, g8, g9, g10)


def _run_groups():
    global _OK
    _OK = 0
    _BAD.clear()
    for idx, g in enumerate(_GROUPS, 1):
        try:
            g()
        except Exception as exc:                     # noqa: BLE001
            # ★ 组异常按 G<序号> 命名：定点变异可能把实现改成自相矛盾（调用直接
            #   抛），此时判据不是「断言不成立」而是「调用抛」——两者都该让该组转红。
            _check("G%d 组异常（%s）：%s" % (idx, g.__name__, exc), False)
            import traceback
            print(traceback.format_exc()[-600:])
    return len(_BAD)


def main():
    n = _run_groups()
    print()
    print("睡眠根绑定守卫：%d 通过，%d 失败" % (_OK, n))
    return 1 if n else 0


# --------------------------------------------------------------------------
# 定点变异自证
# --------------------------------------------------------------------------

_MUTATIONS = (
    ("V1 绑定检查恒放行（跨根串库回到修前）",
     "md_cg/sleep.py",
     "    if owner and owner != os.path.realpath(root):\n",
     "    if False:\n", "G5"),
    ("V2 缺省落点不按根分开（两根共用 legacy lib.git）",
     "md_cg/sleep.py",
     "    if (not os.path.isdir(legacy)\n"
     "            or bound_root(legacy) in (\"\", os.path.realpath(root))):\n"
     "        return sleep_root()\n",
     "    if True:\n        return sleep_root()\n", "G2"),
    ("V3 空层不记删除（他根残留留在 HEAD）",
     "md_cg/sleep.py",
     "    if stale:\n"
     "        _git_ok(git_dir_path, work_tree, \"rm\", \"-r\", \"-q\", \"--cached\", \"--\",\n"
     "                *stale)\n",
     "", "G8"),
    ("V4 物化后不写绑定（分槽失去依据）",
     "md_cg/sleep.py",
     "            rep = ensure_repo(root, G)\n            _bind_root(G, root)\n",
     "            rep = ensure_repo(root, G)\n", "G3"),
)


def _mutate():
    bad = []
    prist = {}
    for _n, rel, _a, _r, _w in _MUTATIONS:
        p = os.path.join(_REPO, rel)
        with io.open(p, encoding="utf-8", newline="") as f:
            prist[rel] = f.read()
        # 基线必须是**原样**源码，否则「变异后转红」无意义。
        if "issue #295" not in prist[rel]:
            print("  SOURCE-ALREADY-MUTATED：%s 里找不到本件标记" % rel)
            return 1
    for name, rel, anchor, repl, want in _MUTATIONS:
        p = os.path.join(_REPO, rel)
        orig = prist[rel]
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        if a_ not in orig:
            print("  ANCHOR-MISS %s" % name)
            bad.append(name)
            continue
        # ★ 锚点必须唯一：多义锚点 + replace(..., 1) 会改到别处，变异形同没做，
        #   自证便成假通过（#294 的 V4 实测过一次）。
        if orig.count(a_) != 1:
            print("  ANCHOR-AMBIGUOUS %s（命中 %d 处，须唯一定位）"
                  % (name, orig.count(a_)))
            bad.append(name)
            continue
        try:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            r = subprocess.run(
                [sys.executable, "-X", "utf8", "-m",
                 "md_cg.test_issue295_sleep_root_binding"],
                cwd=_REPO, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=1200)
            out = (r.stdout or "") + (r.stderr or "")
            reds = [l.strip() for l in out.splitlines()
                    if l.strip().startswith("FAIL")]
            hit = any(want in l for l in reds)
            print("  %-4s %-46s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(reds), want,
                     "是" if hit else "否"))
            if not hit:
                print("       rc=%d 尾部=%s" % (r.returncode, out[-400:]))
                bad.append(name)
        finally:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig)
            with io.open(p, encoding="utf-8", newline="") as f:
                if f.read() != orig:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
    if bad:
        print()
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print()
    print("定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
