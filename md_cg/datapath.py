# -*- coding: utf-8 -*-
"""datapath.py · 灵枢数据根解析（记忆写入路径可配置）

解析优先级（高 → 低）：
  1. 环境变量 `MDCG_DATA_ROOT`（数据根）／ `MDCG_ROOT`（认知图根）
  2. 用户可编辑的路径文件 `<插件仓>/data/paths.json` 的 "data_root" / "root"
  3. 默认：`<插件仓>/data`（**自身仓库**，与进程 cwd 解耦）

为什么默认锚定「插件仓自身」而不是 `data/mdcg` 相对路径：
  相对路径随进程 cwd 漂移——node 侧插件与 python 侧脚本 cwd 不同
  （历史事故：DSH 进程 cwd 在 AEIS 时，记忆真源落到 `AEIS/data/mdcg`，
  与插件仓内的 `data/` 分裂成两处）。锚定 `__file__` 后默认值稳定。

设计边界：
  - 本模块只决定「**新写入去哪**」，不搬运、不改写既有数据。
    已有库（如 `AEIS/data/mdcg`）继续由其配置显式指定即可。
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


def plugin_root() -> str:
    """插件仓根目录（本文件位于 <root>/md_cg/datapath.py）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def paths_file() -> str:
    """用户可编辑的路径配置文件——固定在插件仓 `data/paths.json`。

    固定锚点（不受 data_root 自身取值影响），保证「配置读取」不会
    与「配置结果」互相依赖。
    """
    return os.path.join(plugin_root(), "data", "paths.json")


def _user_paths() -> dict:
    try:
        with open(paths_file(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def default_data_root() -> str:
    """默认数据根 = 插件仓自身 data/。"""
    return os.path.join(plugin_root(), "data")


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


def state_dir(*parts: str, create: bool = True) -> str:
    """运行态子目录（日志/队列/草稿…），默认挂在数据根下。"""
    p = os.path.join(data_root(), *parts) if parts else data_root()
    if create:
        os.makedirs(p, exist_ok=True)
    return p


def legacy_candidates(name: str) -> list:
    """历史位置候选（只读兼容：三仓分离前的校验缓存等）。

    仅用于「读旧件」，顺序：数据根 → 插件仓根 → 归档区。
    """
    out = [os.path.join(data_root(), name),
           os.path.join(plugin_root(), name),
           os.path.join(os.path.dirname(plugin_root()), "AEIS", "_archive",
                        "ctp-aeis-data", name)]
    return [p for p in out if os.path.isfile(p)]


def find_existing(name: str) -> str | None:
    """在数据根/插件仓/归档区中找已存在的同名文件，找不到返回 None。"""
    hits = legacy_candidates(name)
    return hits[0] if hits else None


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
