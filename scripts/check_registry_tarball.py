#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_registry_tarball.py — 注册表条目 tarball 版本一致性门禁。

门禁对象：本地 awesome-dsh-plugin 副本中本插件的注册表条目
（data/plugins/FuRongJun-1999__dsh-memory.yml）。条目若声明 tarball，
其文件名中的版本必须 == 仓库根 package.json 的 version；条目未声明 tarball
视为通过——npm 已发布时市场回退到 npm 安装命令，优于把用户交给旧版本预构建包。

为什么需要（2026-09-18 实例）：GitHub release 只有 v0.3.0 附了 .tgz，其后
v0.4.5/v0.4.7/v0.4.8 均无资产，而条目一直 pin 在 v0.3.0 → 同一条目内
version=0.4.8（npm 侧）与 tarball=v0.3.0 自相矛盾，消费者按 tarball 装到的
是 0.3.0。上游 scripts/probe-tarballs.mjs 只判「URL 是否还能解析」，不判
「版本是否当前」，故该缺口由本门禁补齐。

用法（argv 列表，不经 shell；PYTHONUTF8=1 由调用方或本脚本内的 subprocess 约定）：
  python scripts/check_registry_tarball.py                 # 检查真实条目
  python scripts/check_registry_tarball.py --entry P --package Q   # 供回放断言
退出码：0 通过（含 skipped）｜1 版本不一致｜2 读取/用法错误
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ENTRY = os.path.join(
    _REPO, "awesome-dsh-plugin", "data", "plugins", "FuRongJun-1999__dsh-memory.yml"
)
DEFAULT_PACKAGE = os.path.join(_REPO, "package.json")

_TARBALL_RE = re.compile(r"^tarball:[ \t]*(\S+)[ \t]*$", re.M)
_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


# 生效条件：path 指向的文件按 UTF-8 可读且为含 "version" 键的 JSON 对象时返回该键的值（缺该键抛 KeyError，非 JSON 抛 ValueError，打不开抛 OSError，源码均未捕获）。
def read_package_version(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)["version"]


# 生效条件：path 指向文件读出的全文经 _TARBALL_RE.search 命中时返回捕获组 1，无任何匹配时返回 None。
def read_entry_tarball(path):
    """返回条目声明的 tarball URL；未声明返回 None。"""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    match = _TARBALL_RE.search(text)
    return match.group(1) if match else None


# 生效条件：url 以 "/" 切分取末段、末段若以 ".tgz" 结尾则去掉该 4 字符后，_VERSION_RE.findall 有匹配时返回最后一个匹配串，无匹配时返回 None。
def version_in_asset(url):
    """从 tarball URL 文件名里取版本；取不到返回 None。"""
    name = url.rsplit("/", 1)[-1]
    if name.endswith(".tgz"):
        name = name[:-4]
    found = _VERSION_RE.findall(name)
    return found[-1] if found else None


# 生效条件：entry_path 非文件时 require_entry 为真返回 (2,'error')、为假返回 (0,'skipped')；entry_path 为文件而 package_path 非文件返回 (2,'error')；两者为文件时 read_package_version/read_entry_tarball 抛 OSError/ValueError/KeyError 返回 (2,'error')，tarball 未声明返回 (0,'ok')，文件名取不到版本或取的版本 != package.json 的 version 返回 (1,'mismatch')，相等返回 (0,'ok')。
def check(entry_path, package_path, require_entry=False):
    """返回 (code, status, detail)。"""
    if not os.path.isfile(entry_path):
        if require_entry:
            return 2, "error", "条目文件不存在：%s" % entry_path
        return 0, "skipped", "本地无条目文件（未检出 awesome-dsh-plugin）：%s" % entry_path
    if not os.path.isfile(package_path):
        return 2, "error", "package.json 不存在：%s" % package_path
    try:
        version = read_package_version(package_path)
        tarball = read_entry_tarball(entry_path)
    except (OSError, ValueError, KeyError) as exc:
        return 2, "error", "读取失败：%s" % exc
    if tarball is None:
        return 0, "ok", "条目未声明 tarball（市场回退 npm 安装，包版本 %s）" % version
    asset_version = version_in_asset(tarball)
    if asset_version is None:
        return 1, "mismatch", "tarball 文件名不含版本号：%s（包版本 %s）" % (tarball, version)
    if asset_version != version:
        return 1, "mismatch", "tarball 版本 %s != 包版本 %s（tarball=%s）" % (
            asset_version,
            version,
            tarball,
        )
    return 0, "ok", "tarball 版本与包版本一致：%s" % version


# 生效条件：argv 为 None 时由 argparse 读取 sys.argv[1:]、否则按 argv 解析 --entry/--package/--require-entry/--json（前两者缺省为 DEFAULT_ENTRY/DEFAULT_PACKAGE），随后以 check(args.entry, args.package, args.require_entry) 的返回值按 --json 打印 JSON 或文本行并返回该 code。
def main(argv=None):
    parser = argparse.ArgumentParser(description="注册表条目 tarball 版本一致性门禁")
    parser.add_argument("--entry", default=DEFAULT_ENTRY, help="注册表条目 yml 路径")
    parser.add_argument("--package", default=DEFAULT_PACKAGE, help="package.json 路径")
    parser.add_argument(
        "--require-entry",
        action="store_true",
        help="条目文件缺失时视为错误（默认跳过，避免依赖本地检出状态）",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    code, status, detail = check(args.entry, args.package, args.require_entry)
    if args.json:
        print(json.dumps({"status": status, "detail": detail}, ensure_ascii=False))
    else:
        print("REGISTRY_TARBALL %s | %s" % (status.upper(), detail))
    return code


if __name__ == "__main__":
    sys.exit(main())
