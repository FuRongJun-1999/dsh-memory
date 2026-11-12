#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 功能名：UI 产物构建（把 ui/minimal/payload 铺到插件根：web/ · lib/client.js · lib/lib/console_web.mjs · src/lib/console_web.mjs · build-ui.mjs）
# 生效条件：python scripts/build_ui.py [--check] [--root <插件根>]；缺省 root＝仓库根；--check 只校验不写入
# 子功能：①按 ui/minimal/integrity.json 的清单逐文件复制（payload → 插件根）②内容相同则跳过（幂等，不动 mtime）③--check 报告差异而不写 ④清单缺失/文件缺失 fail-closed 并点名
# 执行：读 integrity.json → 逐条比对 payload 与目标 → 不同则写（--check 只报）→ 汇总「写入 N / 跳过 M / 缺失 K」
# 验证方式：md_cg/test_ui_wiring_in_repo.py（仓库清单含接线 + files 含 web/ui + 本脚本幂等 + --check 对干净树返回 0）；也可手跑两次看第二次「写入 0」
# 不适用条件：不负责插件清单注入（`dsh.client` / `exports["./client"]` 已随仓库 package.json 提供）；不校验 DSH 是否加载（那是宿主面）
"""UI 产物构建：把 `ui/minimal/payload/` 铺到插件根（2026-10-27 起接管安装器的「铺文件」职责）。

为什么需要（使用者裁定「把 UI 接线纳入仓库」）：
  此前 `dsh.client` / `exports["./client"]` 由 `ui/minimal/install.ps1` 在**安装时**注入，
  于是 `package.json` 同时扮演两个角色——「仓库发布清单」与「本机 UI 安装态」，
  每次改清单都要重装一次 UI（实测一轮里被迫重装三次）。
  现在：**接线随仓库 package.json 提供**（声明面），本脚本负责**产物面**（把 payload
  铺成 `web/` 与 `lib/client.js`），`npm publish` 前由 `prepublishOnly` 自动执行。

与 install.ps1 的关系：install.ps1 面向「从 npm 包装到本机插件目录」的最终用户；
本脚本面向「仓库自身」与「发布前」。两者铺的文件相同（同一 integrity 清单），互相幂等。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PAYLOAD = os.path.join(REPO, "ui", "minimal", "payload")
MANIFEST = os.path.join(REPO, "ui", "minimal", "integrity.json")


# 生效条件：manifest 路径存在且可 json.load 时返回 (清单 dict, None)；否则返回 (None, 错误文案)。
def load_manifest(path=MANIFEST):
    if not os.path.exists(path):
        return None, "完整性清单缺失：%s" % path
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, "完整性清单解析失败：%s" % exc


# 生效条件：payload 与目标都存在且字节相同返回 True；任一不存在返回 False。
def same_bytes(a, b):
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


# 生效条件：root 为可写目录、清单合法时按 integrity 逐条铺文件，返回 {"written": [...], "skipped": [...], "missing": [...]}；--check 时 written 为空、待写项进 pending。
def build(root=REPO, check=False, manifest=MANIFEST):
    data, err = load_manifest(manifest)
    if err:
        return {"error": err, "written": [], "skipped": [], "missing": [], "pending": []}
    files = data.get("files") or []
    written, skipped, missing, pending = [], [], [], []
    for rec in files:
        rel = str(rec.get("path") or "").replace("/", os.sep)
        if not rel:
            continue
        src = os.path.join(PAYLOAD, rel)
        dst = os.path.join(root, rel)
        if not os.path.exists(src):
            missing.append(rel)
            continue
        if same_bytes(src, dst):
            skipped.append(rel)
            continue
        if check:
            pending.append(rel)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as fs, open(dst, "wb") as fd:
            fd.write(fs.read())
        written.append(rel)
    return {"written": written, "skipped": skipped, "missing": missing,
            "pending": pending, "error": None}


# 生效条件：命令行返回 0 表示「无需变更或已成功写入」；返回 1 表示 --check 有差异或清单/文件缺失（fail-closed）。
def main(argv=None):
    ap = argparse.ArgumentParser(description="把 ui/minimal/payload 铺到插件根（幂等）")
    ap.add_argument("--root", default=REPO, help="插件根（缺省＝仓库根）")
    ap.add_argument("--check", action="store_true", help="只校验不写入")
    a = ap.parse_args(argv)
    res = build(root=a.root, check=a.check)
    if res.get("error"):
        sys.stderr.write("[build_ui] %s\n" % res["error"])
        return 1
    if a.check:
        if res["pending"]:
            print("[build_ui] 待写入 %d 个：%s" % (len(res["pending"]), ", ".join(res["pending"][:6])))
            return 1
        print("[build_ui] 已是最新（跳过 %d 个）" % len(res["skipped"]))
        return 0
    print("[build_ui] 写入 %d / 跳过 %d / 缺失 %d"
          % (len(res["written"]), len(res["skipped"]), len(res["missing"])))
    if res["missing"]:
        sys.stderr.write("[build_ui] 清单里有但 payload 缺：%s\n" % ", ".join(res["missing"]))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())