# -*- coding: utf-8 -*-
"""test_ignore_face —— 忽略面守卫：`.zcode/` 顶层内容必须被忽略 + 入库件不得被忽略

背景（A8，2026-10-05 使用者裁决「加规则」）：`.zcode/` 顶层内容（会话计划 / 探针 /
复核草稿 / 工作流定义与运行记录 / 提交信息模板）此前未被任何忽略规则覆盖——
`git status --porcelain` 见 `?? .zcode/`、`git add -A -n` 会把**含本机路径字面量**的
工具产物列进提交面（此前全靠收尾时逐文件显式 add 规避，属纪律而非机制）。
修法＝根 `.gitignore` 加覆盖 `.zcode/` 的规则；其下 `workflow-drafts/` 与
`workflow-runs/` 的内嵌 `.gitignore`（`*`）继续生效（更靠近路径者优先级更高）。

断言面（行为断言：真跑 `git check-ignore` / `git status` / `git add -n`，不做源码
文本匹配；L1/L3 用的是**合成路径**——判据是规则面，check-ignore 不要求路径存在，
故本守卫与「本机此刻恰好有哪些草稿」解耦）：
  前提   仓内可跑 git（`rev-parse --is-inside-work-tree`）——不可用时 SKIP 全组并
         如实报「未核对」，不伪装通过
  L1     `.zcode/` 顶层各面（plans/ probes/ review/ workflows/ 顶层文件/ 将来新增
         子目录）逐条被忽略，且**匹配来源 = 根 `.gitignore` 的 `/.zcode/` 规则**
  L2     修复意图（防「规则写了但没生效」——锚点写错/被后置 `!` 抵消）：`git add -A -n`
         输出零 `.zcode/` 路径
  L3     相容性：两处内嵌忽略面继续生效（起草稿 `.dwf.ts` / 运行记录仍被忽略）
  L4     通用不变量（补严，防将来新规则误伤入库面）：`--no-index` 口径下 `git ls-files`
         的每一件都不得被忽略规则命中；且 `.zcode/` 下零追踪件（顶收规则不会遮住
         已入库件）、当前 `.zcode/` 下所有未跟踪项均被忽略（逐项点名，非抽样）

运行：python -X utf8 scripts/test_ignore_face.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RULE = "/.zcode/"

passed = failed = skipped = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail).replace("\n", " | ")[:300])


def skip(name, why):
    global skipped
    skipped += 1
    print("  [SKIP] %s（%s）" % (name, why))


# 生效条件：以 REPO 为 cwd 跑 git 子命令（显式 argv、core.quotepath=false 保中文路径原样、encoding=utf-8/errors=replace），stdin_text 非 None 时作为输入喂入；返回 CompletedProcess（不检查返回码——由调用点判定）。
def _git(args, stdin_text=None):
    return subprocess.run(["git", "-c", "core.quotepath=false"] + args, cwd=REPO,
                          input=stdin_text, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


# 生效条件：paths 非空时跑 `git check-ignore -v -- <paths>`，对每行 `source:line:pattern<TAB>path` 拆出 (path → "source:line:pattern") 收入 dict；无命中/空输入返回空 dict。
def _ignored(paths):
    if not paths:
        return {}
    out = {}
    for line in (_git(["check-ignore", "-v", "--"] + list(paths)).stdout or "").splitlines():
        if "\t" in line:
            src, path = line.split("\t", 1)
            out[path] = src
    return out


# 生效条件：prov 为 "source:line:pattern" 时，三段齐全且 source 为根 .gitignore、pattern 恰为模块常量 RULE 返回 True，其余 False。
def _from_root_rule(prov):
    parts = (prov or "").split(":")
    return len(parts) >= 3 and parts[0] == ".gitignore" and parts[-1] == RULE


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("[0] 前提：仓内可跑 git")
    r = _git(["rev-parse", "--is-inside-work-tree"])
    if r.returncode != 0 or (r.stdout or "").strip() != "true":
        skip("L1–L4", "非 git 工作树（%s）" % (r.stderr or "").strip()[:120])
        print("\n%d passed, %d failed, %d skipped（未核对：忽略面未能机械校验）"
              % (passed, failed, skipped))
        return 0
    check("前提：git 工作树可用", True)

    print("[1] `.zcode/` 顶层各面（合成路径）被忽略，来源=根 .gitignore 的 %s" % RULE)
    faces = [".zcode/commit-msg-v3.txt", ".zcode/plans/x.md",
             ".zcode/probes/u_probe.py", ".zcode/review/x.md",
             ".zcode/workflows/y.dwf.ts", ".zcode/将来新增的会话/z.md"]
    ign = _ignored(faces)
    for p in faces:
        check("被忽略：%s" % p, p in ign, sorted(ign))
        check("  来源=根 .gitignore 的 %s：%s" % (RULE, p), _from_root_rule(ign.get(p)),
              ign.get(p))

    print("[2] 修复意图：`git add -A -n` 零 `.zcode/` 路径（规则生效，非仅写在纸上）")
    adds = ( _git(["add", "-A", "-n"]).stdout or "").splitlines()
    hits = [ln for ln in adds if ".zcode/" in ln]
    check("git add -A -n 输出无 `.zcode/` 路径", not hits, hits[:6])

    print("[3] 相容性：内嵌忽略面（workflow-drafts / workflow-runs）继续生效")
    for p in (".zcode/workflow-drafts/x.dwf.ts", ".zcode/workflow-runs/x.json"):
        check("仍被忽略：%s" % p, p in _ignored([p]))

    print("[4] 通用不变量与逐项点名（防误伤入库面 / 防漏项）")
    tracked = [ln for ln in (_git(["ls-files"]).stdout or "").splitlines() if ln]
    matched = {}
    for line in (_git(["check-ignore", "--no-index", "-v", "--stdin"],
                      stdin_text="\n".join(tracked)).stdout or "").splitlines():
        if "\t" in line:
            src, path = line.split("\t", 1)
            matched[path] = src
    check("入库件零命中忽略规则（--no-index 口径；新规则不得遮住入库面）",
          not matched, list(matched.items())[:4])
    check("`.zcode/` 下零追踪件（顶收规则不会遮住已入库件）",
          not [p for p in tracked if p.startswith(".zcode/")],
          [p for p in tracked if p.startswith(".zcode/")][:4])
    untracked = [ln[3:].strip() for ln in
                 (_git(["status", "--porcelain", "-uall", "--", ".zcode"]).stdout
                  or "").splitlines() if ln.startswith("?? ")]
    missed = [p for p in untracked if p not in _ignored(untracked)]
    check("`.zcode/` 下所有未跟踪项均被忽略（逐项点名：%d 件）" % len(untracked),
          not missed, missed)

    print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
