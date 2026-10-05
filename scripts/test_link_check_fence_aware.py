# -*- coding: utf-8 -*-
"""test_link_check_fence_aware —— link_check「代码跨度」感知守卫（围栏块 + 行内代码）

背景（本仓实测自伤一次）：`scripts/link_check.py` 的链接扫描把**围栏代码块内**与
**行内代码（反引号跨度）内**写出的 Markdown 链接形态（方括号标注紧跟圆括号路径）
一视同仁当真实相对链接——报告/文档正文里写出该形态（示例、伪码、模板占位）即被判
BROKEN，整条 gate 链 GATE_EXIT=1：判据本身没错，是**扫描面把「示例」误当「引用」**。

使用者裁决的修法方向：**只排除代码跨度**，判据（围栏外真链接判 broken）不动。

守卫断言面（行为断言：把样例喂给被测实现，读它 stdout 的 BROKEN/OK 记账与退出码，
不做源码文本匹配）：
  前提   夹具面可用：临时 git 仓建立 + `git ls-files *.md` 恰见样例与目标两件
  L1     ① 围栏代码块内（``` 与 ~~~ 两种定界符）的链接形态 → 不计入 BROKEN
  L2     ② 行内代码（反引号跨度）里的同形态 → 不计入 BROKEN
  L3     ③ 围栏外的真断链 → 仍计入 BROKEN，且报出的**行号 = 源文件真实行号**
         （收窄扫描面不得移动偏移/行号——「整段删除文本」式实现会在此腿现形）
  L4     ④ 围栏外的真可达链接 → 计数恰为 OK=1 / ALLOWED=0 / UNTRACKED=0
  L5     判据未放宽：BROKEN 恰 1 条（只有 ③），进程退出码 = 1
         （「跳过整个文件」「一遇反引号即停扫」式假绿会被 L4/L5 抓）
  L6     红基线自证：`git show HEAD:scripts/link_check.py` 物化副本喂同一样例，应仍见
         ① ② 被判 BROKEN——证明本守卫盯的缺陷真实存在、断言非空转；HEAD 已含修复
         （本改动入库后）时本腿 SKIP（红基线只在该改动提交前可复现）

为什么用「临时 git 仓 + 实现副本」：被测脚本 `REPO` 由自身位置推出（
`dirname(dirname(__file__))`），链接面取自 `git ls-files *.md`——只有把副本放进
临时仓，样例面才是**受控的**（真仓的 2000+ 件 md 会让断言随仓面漂移）。
夹具内不放 `cogmap_sync.py`，故 `_allowlist()` 走导入失败分支返回空集——白名单面
（现为空字典 `FILE_LINK_ALLOWLIST = {}`）不影响判定，计数可写死。

用法（任意 cwd）：
  python -X utf8 scripts/test_link_check_fence_aware.py               # 测工作树版
  python -X utf8 scripts/test_link_check_fence_aware.py --impl head   # 红基线：HEAD 版
  python -X utf8 scripts/test_link_check_fence_aware.py --impl <path> # 指定实现副本
退出码：0 = 全部断言通过；1 = 有失败（L1/L2 红即「误判面仍在」）。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_IMPL = os.path.join(HERE, "link_check.py")

# 输出解析（口径 = link_check.main() 的打印格式；变了即这里失配 → 前提腿会红）
_RE_BROKEN = re.compile(r"^\s*\[(BROKEN|UNTRACKED)\]\s+(\S+):(\d+)\s+->\s+(\S+)\s+\(解析=")
_RE_COUNTS = re.compile(r"OK=(\d+)\s+ALLOWED=(\d+)\s+BROKEN=(\d+)\s+UNTRACKED=(\d+)")

passed = failed = skipped = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  "
              + str(detail).replace("\n", " | ")[:400])


def skip(name, why):
    global skipped
    skipped += 1
    print("  [SKIP] %s（%s）" % (name, why))


# ---------------------------------------------------------------- 样例夹具
# 锚 = 链接的 raw 目标串（断言按锚定位，不写死行号——行号由样例自身推出）
FENCE_ANCHORS = ("../no_such_fence_target.md", "no_such_fence_target_2.md")
INLINE_ANCHOR = "../no_such_inline_target.md"
BROKEN_ANCHOR = "../fence_guard_really_broken_target.md"
OK_ANCHOR = "fence_guard_existing_target.md"

_SAMPLE_LINES = [
    "# 样例：link_check 代码跨度夹具（本文件由守卫生成于临时仓，不入库）",
    "",
    "① 围栏代码块内的相对链接形态（示例，不是引用）：",
    "",
    "```python",
    "# 伪码注释：见 [示例](../no_such_fence_target.md)",
    "```",
    "",
    "①b 另一种围栏定界符（~~~）：",
    "",
    "~~~text",
    "[示例二](no_such_fence_target_2.md)",
    "~~~",
    "",
    "② 行内代码跨度里的同形态：`[行内示例](../no_such_inline_target.md)` 与"
    " `` `反引号` ``。",
    "",
    "③ 围栏外的真断链：[真断链](../fence_guard_really_broken_target.md)",
    "",
    "④ 围栏外的真可达：[真可达](fence_guard_existing_target.md)",
    "",
]
SAMPLE = "\n".join(_SAMPLE_LINES)


# 生效条件：锚在样例行列表命中的 1 基行号——恰命中 1 行时返回该行号；命中 0 行或多行时抛 AssertionError（夹具自身的前提，不静默取首行）。
def _line_of(anchor):
    """锚在样例中的 1 基行号（恰好命中一行）。"""
    hits = [i for i, ln in enumerate(_SAMPLE_LINES, 1) if anchor in ln]
    if len(hits) != 1:
        raise AssertionError("夹具锚 %r 命中 %d 行（应为 1）" % (anchor, len(hits)))
    return hits[0]


# 生效条件：以 workroot 为根建临时 git 仓（docs/sample.md 样例 + docs/fence_guard_existing_target.md 目标 + scripts/link_check.py=impl 副本），git init 与 git add -A 均 rc=0 时返回 (仓目录, "")；任一步失败返回 (None, 原因串)。
def _mk_fixture(workroot, impl):
    """临时 git 仓 + 样例 md + 目标文件 + 被测实现副本。"""
    repo = os.path.join(workroot, "repo")
    docs = os.path.join(repo, "docs")
    scripts = os.path.join(repo, "scripts")
    os.makedirs(docs)
    os.makedirs(scripts)

    def _w(p, text):
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    _w(os.path.join(docs, "sample.md"), SAMPLE)
    _w(os.path.join(docs, "fence_guard_existing_target.md"),
       "# 目标文件（④ 真可达链接的落点）\n")
    shutil.copyfile(impl, os.path.join(scripts, "link_check.py"))
    for argv in (["git", "init", "-q"],
                 ["git", "-c", "core.autocrlf=false", "add", "-A"]):
        r = subprocess.run(argv, cwd=repo, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return None, "%s → rc=%s %s" % (" ".join(argv), r.returncode,
                                            (r.stderr or "").strip()[:200])
    return repo, ""


# 生效条件：以 workroot 建夹具（见 _mk_fixture）并子进程直跑其中 scripts/link_check.py（cwd=夹具仓、PYTHONPATH 摘除、PYTHONUTF8=1、显式 utf-8），返回 (res, "")——res={rc, out, broken, untracked, counts, files}；夹具建立失败时返回 (None, 原因串)。
def _run_case(workroot, impl):
    """建夹具并跑一次被测实现（行为面：stdout 记账 + 退出码 + ls-files 面）。"""
    repo, err = _mk_fixture(workroot, impl)
    if repo is None:
        return None, err
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)      # 白名单导入面留空（夹具内无 cogmap_sync）
    env["PYTHONUTF8"] = "1"
    r = subprocess.run([sys.executable, "-X", "utf8",
                        os.path.join(repo, "scripts", "link_check.py")],
                       cwd=repo, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=300)
    out = (r.stdout or "") + (r.stderr or "")
    broken, untracked = [], []
    for line in (r.stdout or "").splitlines():
        m = _RE_BROKEN.match(line)
        if m:
            item = (m.group(2), int(m.group(3)), m.group(4))
            (broken if m.group(1) == "BROKEN" else untracked).append(item)
    m = _RE_COUNTS.search(out)
    ls = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "*.md"],
                        cwd=repo, capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    files = [ln.strip() for ln in (ls.stdout or "").splitlines() if ln.strip()]
    return {"rc": r.returncode, "out": out, "broken": broken,
            "untracked": untracked,
            "counts": tuple(int(g) for g in m.groups()) if m else None,
            "files": sorted(files)}, ""


# 生效条件：在 REPO 下取 git show HEAD:scripts/link_check.py，rc=0 且输出非空时写入 tmp 下 link_check_head.py 并返回 (路径, "")；否则返回 (None, 原因串)。
def _materialize_head(tmp):
    """物化 HEAD 版 link_check.py（红基线取用）。"""
    r = subprocess.run(["git", "-c", "core.quotepath=false", "show",
                        "HEAD:scripts/link_check.py"],
                       cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None, ("git show 失败 rc=%s %s"
                      % (r.returncode, (r.stderr or "").strip()[:200]))
    p = os.path.join(tmp, "link_check_head.py")
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(r.stdout)
    return p, ""


def main():
    global passed, failed
    ap = argparse.ArgumentParser(description="link_check 代码跨度感知守卫（行为断言）")
    ap.add_argument("--impl", default=None,
                    help="被测实现：缺省=工作树 scripts/link_check.py；"
                         "head=HEAD 版（红基线取证）；或一个 .py 路径")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    impl_given = args.impl is not None
    with tempfile.TemporaryDirectory() as tmp:
        if args.impl is None:
            impl = DEFAULT_IMPL
        elif args.impl == "head":
            impl, why = _materialize_head(tmp)
            if impl is None:
                print("取不到 HEAD 版：%s" % why)
                return 1
        else:
            impl = os.path.abspath(args.impl)
            if not os.path.isfile(impl):
                print("--impl 指向的文件不存在：%s" % impl)
                return 1

        print("[1] 前提：夹具面（临时 git 仓 + 样例 md；实现=%s）" % impl)
        res, err = _run_case(os.path.join(tmp, "main"), impl)
        if res is None:
            check("前提 夹具建立（git init / git add -A）", False, err)
            print("\n%d passed, %d failed, %d skipped"
                  % (passed, failed, skipped))
            return 1
        check("前提 夹具面：ls-files *.md 恰见样例与目标两件",
              res["files"] == ["docs/fence_guard_existing_target.md",
                               "docs/sample.md"], res["files"])
        check("前提 记账行可解析（OK/ALLOWED/BROKEN/UNTRACKED）",
              res["counts"] is not None, res["out"][-300:])

        print("[2] 主腿：样例四例（①围栏内 ②行内代码 ③围栏外真断链 ④围栏外真可达）")
        raws = {raw for _rel, _ln, raw in res["broken"]}
        by_raw = {}
        for rel, ln, raw in res["broken"]:
            by_raw.setdefault(raw, []).append((rel, ln))
        fence_hit = [a for a in FENCE_ANCHORS if a in raws]
        check("L1 ① 围栏代码块内（```/~~~）不计入 BROKEN", not fence_hit,
              "被判 BROKEN：%s" % fence_hit)
        check("L2 ② 行内代码跨度内不计入 BROKEN", INLINE_ANCHOR not in raws,
              "被判 BROKEN：%s" % (INLINE_ANCHOR in raws))
        b_hits = by_raw.get(BROKEN_ANCHOR) or []
        check("L3 ③ 围栏外真断链仍计入 BROKEN（恰一条）", len(b_hits) == 1,
              "命中 %s ｜ 全部 BROKEN=%s" % (b_hits, sorted(raws)))
        check("L3b ③ 行号 = 源文件真实行号（%d）——收窄扫描面不得移动偏移"
              % _line_of(BROKEN_ANCHOR),
              bool(b_hits) and b_hits[0][1] == _line_of(BROKEN_ANCHOR), b_hits)
        check("L4 ④ 围栏外真可达：计数恰为 OK=1/ALLOWED=0/BROKEN=1/UNTRACKED=0",
              res["counts"] == (1, 0, 1, 0) and not res["untracked"],
              "counts=%s untracked=%s" % (res["counts"], res["untracked"]))
        check("L5 判据未放宽：BROKEN 恰 1 条且退出码=1（真断链仍红）",
              bool(res["counts"]) and res["counts"][2] == 1 and res["rc"] == 1,
              "rc=%s counts=%s" % (res["rc"], res["counts"]))

        print("[3] L6 红基线自证：HEAD 版对同一样例仍应误判 ① ②")
        if impl_given:
            skip("L6", "已显式指定被测实现（--impl），红基线自证只对工作树版做")
        else:
            head, why = _materialize_head(tmp)
            if head is None:
                skip("L6", "取不到 HEAD 版：%s" % why)
            else:
                hres, herr = _run_case(os.path.join(tmp, "head"), head)
                if hres is None:
                    check("L6 红基线自证（HEAD 版跑样例）", False, herr)
                else:
                    hraws = {raw for _rel, _ln, raw in hres["broken"]}
                    old_hit = [a for a in FENCE_ANCHORS if a in hraws]
                    old_inline = INLINE_ANCHOR in hraws
                    if not old_hit and not old_inline:
                        skip("L6", "HEAD 版已不再误判 ① ②（修复已入库）"
                                    "——红基线只在本改动提交前可复现")
                    else:
                        check("L6 红基线可复现：HEAD 版把 ① ② 判为 BROKEN",
                              bool(old_hit) and old_inline,
                              "HEAD 命中 ①=%s ②=%s" % (old_hit, old_inline))

    print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
