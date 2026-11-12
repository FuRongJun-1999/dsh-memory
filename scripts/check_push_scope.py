#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_push_scope —— 共享检出下 push 越权的**纯判据**（只读 git，零行为变更）

为什么要它
    共享检出里 「git push <remote> HEAD:main」 推的不是「我这一笔」，而是
    「<remote>/<branch>..HEAD」 上的**全部**提交——同检出里别人「未推送 / 待裁定 /
    未决」的提交会被一并带上远端（已发生一例：49965119 搭车进 main）。
    本脚本把那条 range 逐笔摊开，并给每笔标注归属与授权提示，供人/机在 push 前判。

判据（只读）
    对 「git log <remote>/<branch>..HEAD」 逐笔给出 sha / 作者 / 时间 / 主题，并标注：
      · markers          —— 主题或正文命中「待裁定/待裁/未决/未推送/未提交/暂缓/挂起/WIP/
                            DO NOT MERGE/HOLD」等标记（正则见 MARKER_RE）
      · mine             —— 作者邮箱 == 本地 user.email（本端产出）
      · on_first_parent  —— 在 --first-parent 链上（本分支直接产出；否则经 merge 并入）
      · merge            —— 合并提交（父数 > 1）
    另附工作区未提交改动清单（git status --porcelain）——推之前应知。

退出码（机器可判，**绝不静默退 0**）
    0 = 无可推提交（<remote>/<branch>..HEAD 为空）
    1 = 有可推提交，逐笔均无待裁定标记 —— **仍需逐笔确认（默认 fail-closed）**
    3 = 有可推提交，且至少一笔带待裁定/未决/未推送标记（搭车高风险，须先处置）
    2 = 检出异常（非 git 工作树 / 基线 ref 不存在 / git 调用失败）

只读保证
    本脚本不做任何写操作：不改 index、不改工作树、不改任何 ref。
    --fetch 是**唯一的写操作**（仅刷新 remote-tracking ref），**默认关闭**。
    不 fetch 时读数基于**本地缓存的** remote-tracking ref，可能陈旧——输出与 JSON 里
    均有 stale_notice 字段显式标注；要新鲜读数请显式 --fetch。

用法
    python -X utf8 scripts/check_push_scope.py
    python -X utf8 scripts/check_push_scope.py --remote origin --branch main
    python -X utf8 scripts/check_push_scope.py --json
    python -X utf8 scripts/check_push_scope.py --repo <path> --fetch
"""
import argparse
import json
import os
import re
import subprocess
import sys

# 待裁定 / 未决 / 未推送 一族的字面标记（大小写不敏感）
MARKER_RE = re.compile(
    r"(待裁定|待裁|未决|未推送|未提交|暂缓|挂起|待定|"
    r"DO[ _-]?NOT[ _-]?MERGE|DONTMERGE|WIP\b|HOLD\b)", re.I)

_REC = "\x1e"
_FLD = "\x1f"
_LOG_FMT = _FLD.join(["%H", "%h", "%an", "%ae", "%aI", "%s", "%b", "%p"]) + _REC

EXIT_OK = 0
EXIT_REVIEW = 1
EXIT_ERROR = 2
EXIT_TAINTED = 3

STALE_NOTICE = ("读数基于**本地缓存**的 remote-tracking ref（本次未 --fetch），"
                "远端可能已更新；要新鲜读数请显式 --fetch")

_EXIT_MEANING = {
    EXIT_OK: "无可推提交",
    EXIT_REVIEW: "有可推提交，逐笔均无待裁定标记 —— 仍需逐笔确认（默认 fail-closed）",
    EXIT_TAINTED: "有可推提交且含待裁定/未决/未推送标记 —— 搭车高风险，须先处置",
    EXIT_ERROR: "检出异常",
}


def _git(repo, args):
    """跑一条 git 命令；返回 (rc, stdout, stderr)。调用方决定是否写操作。"""
    try:
        p = subprocess.run(["git", "-C", repo] + list(args),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
    except Exception as exc:                      # 解释器缺失 / 超时 / 权限
        return 127, "", "%s: %s" % (type(exc).__name__, exc)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def _describe(sha, short, author, email, date, subject, body, parents, first_parent, me):
    """把一笔提交整理成带归属/授权提示的记录（纯函数，便于定点变异与断言）。"""
    markers = sorted({m.group(0) for m in MARKER_RE.finditer(subject + "\n" + body)})
    return {
        "sha": sha,
        "short": short,
        "author": author,
        "email": email,
        "date": date,
        "subject": subject,
        "markers": markers,
        "mine": bool(me) and email.strip().lower() == me,
        "on_first_parent": sha in first_parent,
        "parents": list(parents),
        "merge": len(parents) > 1,
    }


def _exit_code(commits):
    """退出码语义（与模块 docstring 同源）：0 无可推 / 1 有可推须逐笔确认 / 3 含待裁定标记。"""
    if not commits:
        return EXIT_OK
    if any(c["markers"] for c in commits):
        return EXIT_TAINTED
    return EXIT_REVIEW


def collect(repo, remote, branch, do_fetch=False):
    """采集判据读数；成功返回 (info, "")，失败返回 (None, 原因)。"""
    info = {"repo": os.path.abspath(repo), "remote": remote, "branch": branch,
            "fetched": False, "warnings": [], "commits": [], "dirty": [],
            "stale_notice": None}

    rc, out, err = _git(repo, ["rev-parse", "--is-inside-work-tree"])
    if rc != 0 or out != "true":
        return None, "非 git 工作树（%s）" % (err or out or "rc=%d" % rc)

    rc, cur, _e = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    info["current_branch"] = cur if rc == 0 else ""
    if not branch:
        branch = cur or "main"
        info["branch"] = branch

    if do_fetch:
        # 唯一的写操作：显式开启才做
        rc, _out, err = _git(repo, ["fetch", "--no-tags", remote])
        info["fetched"] = (rc == 0)
        if rc != 0:
            info["warnings"].append("fetch %s 失败：%s" % (remote, err[:200]))
    else:
        info["stale_notice"] = STALE_NOTICE

    base_ref = "%s/%s" % (remote, branch)
    rc, base_sha, err = _git(repo, ["rev-parse", "--verify", "--quiet",
                                    base_ref + "^{commit}"])
    if rc != 0 or not base_sha:
        return None, "基线 ref 不存在：%s（未 fetch 或远端无此分支）" % base_ref

    rc, head_sha, err = _git(repo, ["rev-parse", "--verify", "--quiet", "HEAD^{commit}"])
    if rc != 0 or not head_sha:
        return None, "HEAD 不可解析（%s）" % (err or "rc=%d" % rc)

    info["base_ref"] = base_ref
    info["base_sha"] = base_sha
    info["head_sha"] = head_sha
    rng = "%s..%s" % (base_ref, head_sha)

    rc, raw, err = _git(repo, ["log", "--format=" + _LOG_FMT, rng])
    if rc != 0:
        return None, "git log 失败（%s）" % (err or "rc=%d" % rc)

    _rc, fp_out, _e = _git(repo, ["rev-list", "--first-parent", rng])
    first_parent = {x for x in fp_out.splitlines() if x}

    _rc, me, _e = _git(repo, ["config", "user.email"])
    me = (me or "").strip().lower()

    commits = []
    for chunk in raw.split(_REC):
        chunk = chunk.strip("\r\n")
        if not chunk:
            continue
        f = chunk.split(_FLD)
        if len(f) < 8:
            continue
        sha, short, an, ae, adate, subj, body, parents_s = f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7]
        plist = [p for p in parents_s.split() if p]
        commits.append(_describe(sha, short, an, ae, adate, subj, body, plist,
                                 first_parent, me))

    _rc, st, _e = _git(repo, ["status", "--porcelain"])
    info["dirty"] = [line for line in st.splitlines() if line.strip()]

    info["commits"] = commits
    info["me"] = me
    info["ahead"] = len(commits)
    info["exit_code"] = _exit_code(commits)
    return info, ""


def _render(info, stream):
    """人读呈现：先摆 range，再逐笔，最后退出码语义。"""
    w = stream.write
    w("push 范围判据：%s..HEAD\n" % info["base_ref"])
    w("  repo=%s  branch=%s  HEAD=%s  基线=%s\n"
      % (info["repo"], info["branch"], info["head_sha"][:8], info["base_sha"][:8]))
    if info.get("stale_notice"):
        w("  ! %s\n" % info["stale_notice"])
    for warn in info.get("warnings") or []:
        w("  ! %s\n" % warn)
    if info.get("fetched"):
        w("  （已 --fetch：remote-tracking ref 已刷新）\n")
    n = info["ahead"]
    if n == 0:
        w("领先 0 笔 —— 无可推提交\n")
    else:
        tainted = sum(1 for c in info["commits"] if c["markers"])
        w("领先 %d 笔%s：\n" % (n, ("，其中 %d 笔带待裁定标记" % tainted) if tainted else ""))
        for i, c in enumerate(info["commits"], 1):
            w("  [%d] %s  %s  %s <%s>\n      %s\n"
              % (i, c["short"], c["date"], c["author"], c["email"], c["subject"]))
            tags = ["标记：%s" % ("、".join(c["markers"]) if c["markers"] else "无"),
                    "本端产出：%s" % ("是" if c["mine"] else "否"),
                    "分支主线：%s" % ("是" if c["on_first_parent"] else "否（经 merge 并入）")]
            if c["merge"]:
                tags.append("合并提交")
            w("      " + " ｜ ".join(tags) + "\n")
    if info["dirty"]:
        w("工作区未提交改动 %d 项（推送前应知）：\n" % len(info["dirty"]))
        for line in info["dirty"][:20]:
            w("  %s\n" % line)
        if len(info["dirty"]) > 20:
            w("  … 其余 %d 项略\n" % (len(info["dirty"]) - 20))
    else:
        w("工作区无未提交改动\n")
    w("退出码 %d：%s\n" % (info["exit_code"], _EXIT_MEANING[info["exit_code"]]))
    w("（本脚本不推送、不修改任何状态）\n")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="共享检出下 push 越权的纯判据（只读 git；退出码 0/1/3/2）")
    ap.add_argument("--repo", default=os.getcwd(), help="仓路径（默认当前目录）")
    ap.add_argument("--remote", default="origin", help="远端名（默认 origin）")
    ap.add_argument("--branch", default="", help="分支名（默认当前分支）")
    ap.add_argument("--json", action="store_true", help="输出结构化 JSON")
    ap.add_argument("--fetch", action="store_true",
                    help="刷新 remote-tracking ref（唯一写操作，默认关闭）")
    args = ap.parse_args(argv)

    info, why = collect(args.repo, args.remote, args.branch, do_fetch=args.fetch)
    if info is None:
        payload = {"ok": False, "error": why, "repo": os.path.abspath(args.repo),
                   "remote": args.remote, "branch": args.branch,
                   "exit_code": EXIT_ERROR, "exit_meaning": _EXIT_MEANING[EXIT_ERROR]}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=1))
        else:
            print("检出异常：%s" % why, file=sys.stderr)
            print("（本脚本不推送、不修改任何状态）", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        payload = dict(info)
        payload["ok"] = True
        payload["exit_meaning"] = _EXIT_MEANING[info["exit_code"]]
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        _render(info, sys.stdout)
    return info["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
