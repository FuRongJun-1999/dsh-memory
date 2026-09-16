# -*- coding: utf-8 -*-
"""全库文档相对链接巡检（防「文件移位后相对路径未同步」的断链复发）。

背景（2026-09-16 第 4 条根因取证）：外部评审实测全库 118 条 md 相对链接中 8 条
断链，根因两类——

  ① 投影管线基准错误：`cogmap_sync._mdlink` 以**仓根**为基准生成链接，落到
     `docs/mdcg/` 文档里被 GitHub/浏览器按**文档所在目录**解析 → 必断
     （已修：新增 `_rel_from_root` + `doc_dir` 形参）。
  ② 手写区无守卫：`cogmap_sync check` 只守 README 与功能调用映射表两文档的
     标记段及其链接，其余文档（如 `docs/mdcg/README详细版_v0.4.5.md`、
     规划文档互链）零覆盖 → 文件下移一层后链接静默失效。

本脚本补第 ② 类的通用守卫，并复用管线白名单（`cogmap_sync.FILE_LINK_ALLOWLIST`，
单一真源）以区分「真断链」与「刻意的本地专属链接」。

三态记账（避免口径混淆）：
  OK        目标存在且在库（git 受管或目录下有待管文件）
  ALLOWED   目标在库外/未入库，但有登记理由（链接语义 =「本地会有此文件」）
  BROKEN    目标在本机不存在                     → 失败（真断链）
  UNTRACKED 目标存在但未入库（gitignore）        → 失败（外部 clone 必断）

只扫 git 受管 `.md`（=外部 clone 能看到的集合）；跳过 http(s)/mailto/tel/data/纯锚点；
含 `[]*<>{}` 的目标视为非路径形态（正则/公式/模板占位，如实测化学式 `fkd[I]/kt`）。

用法：python scripts/link_check.py        # 退出码 0=无断链；1=有 BROKEN/UNTRACKED
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK = re.compile(r"\]\(([^)\s]+?)(?:\s+\"[^\"]*\")?\)")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:", "#")
NON_PATH_CHARS = "[]*<>{}"


def _git(args):
    # core.quotepath=false：否则非 ASCII 路径被八进制转义，tracked 集合无法匹配
    r = subprocess.run(["git", "-c", "core.quotepath=false"] + args, cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", shell=False)
    return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


def _allowlist():
    """复用管线白名单（单一真源）。导入失败时返回空集并提示——避免静默改变口径。"""
    try:
        import cogmap_sync
        return set(getattr(cogmap_sync, "FILE_LINK_ALLOWLIST", {}) or {})
    except Exception as exc:  # pragma: no cover - 仅在非常规调用方式下触发
        print("警告：未能载入 cogmap_sync.FILE_LINK_ALLOWLIST（%s）；"
              "白名单链接将按普通链接判定" % exc)
        return set()


def _tracked_ok(relcand, tracked):
    """目标为目录时，只要其下有受管文件即视为已入库。"""
    if relcand in tracked:
        return True
    prefix = relcand.rstrip("/") + "/"
    return any(p.startswith(prefix) for p in tracked)


def scan():
    files = _git(["ls-files", "*.md"])
    tracked = set(_git(["ls-files"]))
    allowed = _allowlist()
    broken, untracked, non_path = [], [], []
    n_ok = n_allowed = 0
    for rel in files:
        path = os.path.join(REPO, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        for m in LINK.finditer(text):
            raw = m.group(1).strip()
            if raw.startswith(SKIP_SCHEMES):
                continue
            target = raw.split("#", 1)[0].strip()
            line = text[:m.start()].count("\n") + 1
            if not target or any(ch in target for ch in NON_PATH_CHARS):
                non_path.append((rel, line, raw))
                continue
            if target.startswith("/"):
                cand = os.path.normpath(os.path.join(REPO, target.lstrip("/")))
            else:
                cand = os.path.normpath(os.path.join(os.path.dirname(path), target))
            relcand = os.path.relpath(cand, REPO).replace("\\", "/")
            if relcand in allowed or target in allowed:
                n_allowed += 1
            elif not os.path.exists(cand):
                broken.append((rel, line, raw, relcand))
            elif not _tracked_ok(relcand, tracked):
                untracked.append((rel, line, raw, relcand))
            else:
                n_ok += 1
    return {"files": files, "broken": broken, "untracked": untracked,
            "non_path": non_path, "ok": n_ok, "allowed": n_allowed}


def main():
    res = scan()
    n = res["ok"] + res["allowed"] + len(res["broken"]) + len(res["untracked"])
    print("扫描受管 md：%d 个；判定链接：%d 条（跳过非路径形态 %d 条）"
          % (len(res["files"]), n, len(res["non_path"])))
    print("  OK=%d  ALLOWED=%d  BROKEN=%d  UNTRACKED=%d"
          % (res["ok"], res["allowed"], len(res["broken"]), len(res["untracked"])))
    for rel, line, raw, c in res["broken"]:
        print("  [BROKEN]    %s:%d -> %s  (解析=%s)" % (rel, line, raw, c))
    for rel, line, raw, c in res["untracked"]:
        print("  [UNTRACKED] %s:%d -> %s  (解析=%s)" % (rel, line, raw, c))
    if res["broken"] or res["untracked"]:
        print("\n结论：存在断链——相对链接须按**文档所在目录**解析（与 GitHub 一致）；"
              "确有理由的「本地才有」链接请登记 cogmap_sync.FILE_LINK_ALLOWLIST。")
        return 1
    print("\n结论：全部相对链接可达（相对路径按文档所在目录解析）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
