# -*- coding: utf-8 -*-
"""datapath.py · 灵枢数据根解析（记忆写入路径可配置）

解析优先级（高 → 低）：
  1. 环境变量 `MDCG_DATA_ROOT`（数据根）／ `MDCG_ROOT`（认知图根）
  2. 用户可编辑的路径文件 `<插件仓>/data/paths.json` 的 "data_root" / "root"
  3. 默认：`<插件仓>/data`（**自身仓库**，与进程 cwd 解耦）

为什么默认锚定「插件仓自身」而不是 `data/mdcg` 相对路径：
  相对路径随进程 cwd 漂移——node 侧插件与 python 侧脚本 cwd 不同
  （历史事故：DSH 进程 cwd 在私有库目录时，记忆真源落到 `AEIS/data/mdcg`，
  与插件仓内的 `data/` 分裂成两处）。锚定 `__file__` 后默认值稳定。

设计边界：
  - 本模块只决定「**新写入去哪**」，不搬运、不改写既有数据。
    已有库（如 [私有库根]/`AEIS/data/mdcg`/data/mdcg）继续由其配置显式指定即可。
  - 纯标准库、无包内相对导入——可被 `sys.path` 以顶层模块方式加载，
    绕开 `md_cg/__init__.py` 的重依赖。

用法：
  from datapath import data_root, mdcg_root, state_dir   # scripts/ 内
  python md_cg/datapath.py                 # 打印当前解析结果
  python md_cg/datapath.py --set-root D:/x/data   # 写入 paths.json（用户可改）
"""
from __future__ import annotations

import json
import os

ENV_DATA_ROOT = "MDCG_DATA_ROOT"
ENV_MDCG_ROOT = "MDCG_ROOT"


# 生效条件：无入参，恒返回本文件 __file__ 绝对路径上溯两级得到的插件仓根目录。
def plugin_root() -> str:
    """插件仓根目录（本文件位于 <root>/md_cg/datapath.py）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 生效条件：无入参，恒返回 plugin_root() 下 "data/paths.json" 的拼接路径，不受 data_root() 取值影响。
def paths_file() -> str:
    """用户可编辑的路径配置文件——固定在插件仓 `data/paths.json`。

    固定锚点（不受 data_root 自身取值影响），保证「配置读取」不会
    与「配置结果」互相依赖。
    """
    return os.path.join(plugin_root(), "data", "paths.json")


# 生效条件：无入参；paths_file() 的 JSON 顶层为 dict 时返回该 dict，JSON 解析或读取抛任何异常、或顶层非 dict 时返回 {}。
def _user_paths() -> dict:
    try:
        with open(paths_file(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# 生效条件：无入参，恒返回 plugin_root() 下 "data" 的拼接路径。
def default_data_root() -> str:
    """默认数据根 = 插件仓自身 data/。"""
    return os.path.join(plugin_root(), "data")


# 生效条件：无入参；ENV_DATA_ROOT 环境变量为非空真值时返回其 abspath，为空串/未设时若 paths.json 的 "data_root" 为真值则按其是否为绝对路径决定直接 abspath 还是拼 plugin_root() 后 abspath，该键缺失或为假值时回落 default_data_root()。
def data_root() -> str:
    """数据根（记忆/账本/运行态的父目录）。"""
    env = os.environ.get(ENV_DATA_ROOT)
    if env:
        return os.path.abspath(env)
    cfg = _user_paths().get("data_root")
    if cfg:
        return os.path.abspath(cfg) if os.path.isabs(cfg) else \
            os.path.abspath(os.path.join(plugin_root(), cfg))
    return default_data_root()


# 生效条件：无入参；ENV_MDCG_ROOT 环境变量为非空真值时返回其 abspath，为空串/未设时若 paths.json 的 "root" 为真值则按其是否为绝对路径决定直接 abspath 还是拼 plugin_root() 后 abspath，该键缺失或为假值时返回 data_root() 下 "mdcg" 的拼接路径。
def mdcg_root() -> str:
    """认知图（记忆唯一真源）根目录。"""
    env = os.environ.get(ENV_MDCG_ROOT)
    if env:
        return os.path.abspath(env)
    cfg = _user_paths().get("root")
    if cfg:
        return os.path.abspath(cfg) if os.path.isabs(cfg) else \
            os.path.abspath(os.path.join(plugin_root(), cfg))
    return os.path.join(data_root(), "mdcg")


# 生效条件：parts 非空时路径为 data_root() 与各 part 的 join，parts 为空时路径即 data_root()；create 为真值（默认 True）时对该路径 makedirs(exist_ok=True)，create 为假值时只返回路径不建目录。
def state_dir(*parts: str, create: bool = True) -> str:
    """运行态子目录（日志/队列/草稿…），默认挂在数据根下。"""
    p = os.path.join(data_root(), *parts) if parts else data_root()
    if create:
        os.makedirs(p, exist_ok=True)
    return p


# 生效条件：name 依次拼成 data_root()/name、plugin_root()/name、dirname(plugin_root())/[私有归档根]/_archive/ctp-aeis-data/name 三个候选，仅保留其中 os.path.isfile 为真的项并按此顺序返回列表。
def archive_root() -> str | None:
    """私有侧归档根（公开仓不含私有库名）：本机配置提供，未配置则没有该候选。

    取值顺序：环境变量 MDCG_ARCHIVE_ROOT -> 插件仓同级的 .mdcg_archive_root 文件内容。
    """
    value = os.environ.get("MDCG_ARCHIVE_ROOT", "").strip()
    if value:
        return value
    marker = os.path.join(os.path.dirname(plugin_root()), ".mdcg_archive_root")
    if os.path.isfile(marker):
        try:
            with open(marker, "r", encoding="utf-8") as fh:
                text = fh.read().strip()
        except OSError:
            return None
        return text or None
    return None


def legacy_candidates(name: str) -> list:
    """历史位置候选（只读兼容：三仓分离前的校验缓存等）。

    仅用于「读旧件」，顺序：数据根 → 插件仓根 → 归档区。
    """
    out = [os.path.join(data_root(), name),
           os.path.join(plugin_root(), name)]
    archive = archive_root()
    if archive is not None:
        out.append(os.path.join(archive, "_archive", "ctp-aeis-data", name))
    return [p for p in out if os.path.isfile(p)]


# 生效条件：name 对应的 legacy_candidates(name) 列表非空时返回其首个元素，为空列表时返回 None。
def find_existing(name: str) -> str | None:
    """在数据根/插件仓/归档区中找已存在的同名文件，找不到返回 None。"""
    hits = legacy_candidates(name)
    return hits[0] if hits else None


# 生效条件：无入参；恒返回含 plugin_root/data_root/mdcg_root/default_data_root/is_default/source/paths_file/data_root_exists/mdcg_root_exists 的字典，其中 source 按 ENV_DATA_ROOT 非空取 "env:MDCG_DATA_ROOT" → 否则 ENV_MDCG_ROOT 非空取 "env:MDCG_MDCG_ROOT" → 否则 _user_paths() 为非空 dict 取 "paths.json" → 否则取 "default"。
def describe() -> dict:
    """当前解析结果的完整快照（供心跳/日志留痕）。"""
    dr = data_root()
    mr = mdcg_root()
    return {
        "plugin_root": plugin_root(),
        "data_root": dr,
        "mdcg_root": mr,
        "default_data_root": default_data_root(),
        "is_default": (os.path.normcase(dr) ==
                       os.path.normcase(default_data_root())),
        "source": ("env:" + ENV_DATA_ROOT if os.environ.get(ENV_DATA_ROOT)
                   else ("env:" + ENV_MDCG_ROOT if os.environ.get(ENV_MDCG_ROOT)
                         else ("paths.json" if _user_paths() else "default"))),
        "paths_file": paths_file(),
        "data_root_exists": os.path.isdir(dr),
        "mdcg_root_exists": os.path.isdir(mr),
    }


# 生效条件：path 为传入字符串（写入前反斜杠替换为 "/"），key 默认 "data_root"（传入时写入该键名）；先确保 paths_file() 的父目录存在，读取 _user_paths()（异常时为 {}）并补 "_comment"，再以该内容覆写 paths_file() 并返回该路径。
def set_user_root(path: str, key: str = "data_root") -> str:
    """把用户选择的路径写入 paths.json（不存在则创建）。返回文件路径。"""
    pf = paths_file()
    os.makedirs(os.path.dirname(pf), exist_ok=True)
    d = _user_paths()
    d.setdefault("_comment",
                 "灵枢记忆写入路径（用户可改）。删掉本文件即回落到插件仓自身 data/。")
    d[key] = path.replace("\\", "/")
    with open(pf, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return pf


if __name__ == "__main__":
    import argparse
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="灵枢数据根解析与设置")
    ap.add_argument("--set-root", metavar="PATH",
                    help="把数据根写入 <插件仓>/data/paths.json（用户可改）")
    ap.add_argument("--set-mdcg-root", metavar="PATH",
                    help="把认知图根写入 <插件仓>/data/paths.json")
    a = ap.parse_args()
    if a.set_root:
        print("written:", set_user_root(a.set_root, "data_root"))
    if a.set_mdcg_root:
        print("written:", set_user_root(a.set_mdcg_root, "root"))
    print(json.dumps(describe(), ensure_ascii=False, indent=2))