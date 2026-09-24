# -*- coding: utf-8 -*-
"""datapath.py · 灵枢数据根解析（记忆写入路径可配置）

与 node 侧 `src/lib/datapath.ts` **同口径**——两侧读同一份
`<用户级状态根>/paths.json`（旧 `<插件仓>/data/paths.json` 兼容读）。

解析优先级（高 → 低）：
  1. 环境变量 `MDCG_DATA_ROOT`（数据根）／ `MDCG_ROOT`（认知图根）
  2. 用户可编辑的路径文件 `paths.json` 的 "data_root" / "root"
     （位置：`<用户级状态根>/paths.json`；旧 `<插件仓>/data/paths.json` 兼容读）
  3. 默认：`<用户级状态根>/data`（**插件包目录之外**，与进程 cwd 解耦）

为什么默认**不**锚定「插件仓自身 data/」（issue #18 相邻问题，数据丢失级）：
  DSH 插件按 hoisted 布局装在 `<profile>/node_modules/<pkg>`，`pnpm` 更新该包会
  **整个替换包目录**——运行时数据落在包内时，每次更新成功即连目录一起删掉
  （实机实证：`data/` 54 文件 → 0，46 条记忆节点靠人工备份回填）；`paths.json`
  同址，用户配置一并丢失。故默认数据根与配置文件一律落**用户级状态根**
  （见 state_root()），与包目录彻底解耦。

为什么默认不锚定 `data/mdcg` 相对路径：
  相对路径随进程 cwd 漂移——node 侧插件与 python 侧脚本 cwd 不同
  （历史事故：DSH 进程 cwd 在私有库目录时，记忆真源落到 `[私有库]/data/mdcg`，
  与插件仓内的 `data/` 分裂成两处）。

设计边界：
  - 本模块只决定「**新写入去哪**」。唯一的搬运是 `migrate_legacy_data()`：
    默认数据根生效且旧包内位置仍有内容时，一次性**复制**（不删除、不覆盖）
    到用户级位置——见该函数注释。
  - 纯标准库、无包内相对导入——可被 `sys.path` 以顶层模块方式加载，
    绕开 `md_cg/__init__.py` 的重依赖。

用法：
  from datapath import data_root, mdcg_root, state_dir   # scripts/ 内
  python md_cg/datapath.py                 # 打印当前解析结果
  python md_cg/datapath.py --set-root D:/x/data   # 写入 paths.json（用户可改）
  python md_cg/datapath.py --migrate-legacy       # 把旧包内数据复制到用户级根
"""
from __future__ import annotations

import json
import os
import shutil

ENV_DATA_ROOT = "MDCG_DATA_ROOT"
ENV_MDCG_ROOT = "MDCG_ROOT"
ENV_STATE_ROOT = "MDCG_STATE_ROOT"
#: 辅助存储根（密钥/令牌/信任/理论/心跳）——与「记忆真源」**有意分离**：
#: 身份与信任面不随认知图迁移（换库不该换身份），故默认仍是历史的 `~/.mdcg`。
ENV_AUX_ROOT = "MDCG_AUX_ROOT"
DEFAULT_AUX_DIRNAME = ".mdcg"


# 生效条件：无入参，恒返回本文件 __file__ 绝对路径上溯两级得到的插件仓根目录。
def plugin_root() -> str:
    """插件仓根目录（本文件位于 <root>/md_cg/datapath.py）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 生效条件：无入参；ENV_STATE_ROOT 环境变量为非空真值时返回其 abspath，为空串/未设时若 DSH_HOME 为非空真值则返回其 abspath 下 ".dsh-memory"，两者皆无则返回 ~/.dsh/.dsh-memory 的 abspath。
def state_root() -> str:
    """用户级状态根（**插件包目录之外**）：路径配置与默认数据根的落点。

    `DSH_HOME` **未必**由宿主注入（本仓 `dsh/dsh-web-start.bat` 自行 set），
    故家目录兜底；`~/.dsh` 是本插件既有约定（node 侧调试日志同址）。
    """
    env = os.environ.get(ENV_STATE_ROOT)
    if env:
        return os.path.abspath(env)
    dsh_home = os.environ.get("DSH_HOME")
    if dsh_home:
        return os.path.join(os.path.abspath(dsh_home), ".dsh-memory")
    return os.path.join(os.path.expanduser("~"), ".dsh", ".dsh-memory")


# 生效条件：无入参，恒返回 plugin_root() 下 "data" 的拼接路径（旧版落点，更新时被整目录替换，只作兼容读与迁移源）。
def legacy_data_root() -> str:
    """旧版落点（插件包内 `data/`）——更新时会被整个替换。"""
    return os.path.join(plugin_root(), "data")


# 生效条件：无入参，恒返回 legacy_data_root() 下 "paths.json" 的拼接路径。
def legacy_paths_file() -> str:
    """旧版路径配置文件位置（包内，兼容读）。"""
    return os.path.join(legacy_data_root(), "paths.json")


# 生效条件：两个路径参数经 normpath+normcase 规范化后相等时返回 True，否则 False（Windows 大小写不敏感）。
def _same_path(a: str, b: str) -> bool:
    return (os.path.normcase(os.path.normpath(a)) ==
            os.path.normcase(os.path.normpath(b)))


# 生效条件：无入参；<state_root()>/paths.json 存在（isfile）时返回之，不存在而 legacy_paths_file() 存在时返回旧件，两者皆不存在时返回新位置路径（首次写入时创建），不受 data_root() 取值影响。
def paths_file() -> str:
    """用户可编辑的路径配置文件——用户级优先，旧包内位置兼容读。

    新位置：`<用户级状态根>/paths.json`（随包更新不丢）。
    旧位置：`<插件仓>/data/paths.json`（旧版约定，仅当新位置不存在时读它，
    已存在新件则新件说了算——不做自动复制，避免旧件后续编辑静默失效）。
    """
    current = os.path.join(state_root(), "paths.json")
    if os.path.isfile(current):
        return current
    legacy = legacy_paths_file()
    return legacy if os.path.isfile(legacy) else current


# 生效条件：无入参；paths_file() 的所在目录与 state_root() 同路径时返回 "user"，否则返回 "legacy"（兼容读旧包内位置）。
def paths_file_source() -> str:
    """生效中的 paths.json 位置来源：`user` / `legacy`。"""
    return "user" if _same_path(os.path.dirname(paths_file()),
                                state_root()) else "legacy"


# 生效条件：无入参；paths_file() 的 JSON 顶层为 dict 时返回该 dict，JSON 解析或读取抛任何异常、或顶层非 dict 时返回 {}。
def _user_paths() -> dict:
    try:
        with open(paths_file(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# 生效条件：无入参，恒返回 state_root() 下 "data" 的拼接路径（插件包目录之外，更新不触碰）。
def default_data_root() -> str:
    """默认数据根 = 用户级状态根下 data/。"""
    return os.path.join(state_root(), "data")


# 生效条件：p 为目录且其下无任何条目时返回 True，p 不存在/是文件/OSError 时返回 False。
def _is_empty_dir(p: str) -> bool:
    try:
        return os.path.isdir(p) and not os.listdir(p)
    except OSError:
        return False


# 生效条件：无入参；data_root() 与 default_data_root() 不同路径时返回 {ran:False, reason:"数据根为显式配置（env/paths.json），不迁移", from, to, copied:0, failed:[]}；相同则继续——legacy_data_root() 非目录时返回 reason="旧位置不存在（多为更新时已随包目录被替换）"，其下无条目（除 paths.json 外）时返回 reason="旧位置无数据"，否则把其余顶层条目逐个复制到 default_data_root() 下（目标条目已存在且非空目录则跳过；只复制不删除、不覆盖；单个条目异常记入 failed 不抛），返回 ran=(copied>0)、copied、failed 与失败时的 reason（"目标不可写" 或 "新位置已有数据，未覆盖"）。
def migrate_legacy_data() -> dict:
    """一次性迁移：把旧版包内 `data/` 的数据面复制到用户级默认数据根。

    触发条件（三条同时满足，缺一不动）：
      ① 数据根未被显式配置（env `MDCG_DATA_ROOT` / paths.json 的 "data_root"
         都未设，即 data_root() 恰为默认值）——显式配置是用户的决定；
      ② 旧位置存在；③ 目标顶层条目不存在或为空目录（不覆盖、不合并）。

    `paths.json` 不复制（配置走 paths_file() 兼容读，复制会制造两说）。
    任何异常逐项吞掉并记入 `failed`——迁移是增益，不该成为启动失败源。

    边界（如实）：pnpm 更新是**先替换包目录再启动新代码**，旧数据在升级瞬间即
    已消失，本函数只能接手「旧位置那时仍在」的情形；已在升级中丢掉的数据无法
    由此恢复——发布说明须提示 0.4.8 及更早用户升级前备份包内 `data/`。
    """
    frm = legacy_data_root()
    to = default_data_root()
    out = {"ran": False, "reason": "", "from": frm, "to": to,
           "copied": 0, "failed": []}
    if not _same_path(data_root(), to):
        out["reason"] = "数据根为显式配置（env/paths.json），不迁移"
        return out
    if not os.path.isdir(frm):
        out["reason"] = "旧位置不存在（多为更新时已随包目录被替换）"
        return out
    try:
        names = [n for n in os.listdir(frm) if n != "paths.json"]
    except OSError:
        out["reason"] = "旧位置不可读"
        return out
    if not names:
        out["reason"] = "旧位置无数据"
        return out
    for name in names:
        src = os.path.join(frm, name)
        dst = os.path.join(to, name)
        # 新位置已有实质内容 → 跳过（宁可少搬，不可覆盖）
        if os.path.exists(dst) and not _is_empty_dir(dst):
            continue
        try:
            os.makedirs(to, exist_ok=True)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            out["copied"] += 1
        except Exception:                  # noqa: BLE001 —— 迁移不得成为启动失败源
            out["failed"].append(name)
    out["ran"] = out["copied"] > 0
    if not out["ran"]:
        out["reason"] = ("目标不可写" if out["failed"]
                         else "新位置已有数据，未覆盖")
    return out


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


# 生效条件：无入参；ENV_AUX_ROOT 为非空真值时返回其 expanduser+abspath，否则返回 ~/.mdcg 的拼接路径（历史默认，逐字不变）。
def aux_root() -> str:
    """辅助存储根（密钥/令牌/信任/理论/心跳）所在目录。

    历史默认 `~/.mdcg`，**逐字保留**（改默认会让存量密钥/令牌失联：私有内容
    会解不开、已签令牌会失效）。设 `MDCG_AUX_ROOT` 可把这些面整体搬到别处
    ——沙箱/多用户/与记忆真源同处的场景需要它。

    与 `mdcg_root()`（记忆真源）分离是**有意设计**：身份与信任不随认知图迁移。
    代价是两者可能分居两处，故 `mdcg.mcp_server` 启动时把两者一起打日志
    （不许静默分裂）；本函数即该分裂面的唯一解析入口。
    """
    env = (os.environ.get(ENV_AUX_ROOT) or "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.join(os.path.expanduser("~"), DEFAULT_AUX_DIRNAME)


# 生效条件：parts 非空时返回 aux_root() 与各 part 的 join，parts 为空时即 aux_root()；create 为真值时 makedirs(exist_ok=True)，create 为假值时只返回路径。
def aux_path(*parts: str, create: bool = False) -> str:
    """辅助存储根下的路径（可选建目录）。"""
    p = os.path.join(aux_root(), *parts) if parts else aux_root()
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


# 生效条件：给定 name 时按 data_root()/name、plugin_root()/name 顺序拼接候选，仅当 archive_root() 不为 None 才追加其下 _archive/ctp-aeis-data/name，最终只返回其中 os.path.isfile 为真的路径（其余被过滤掉），故全都不满足时返回空列表。
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


# 生效条件：无入参；恒返回含 plugin_root/state_root/data_root/mdcg_root/default_data_root/is_default/source/paths_file/paths_file_source/legacy_data_root/legacy_data_exists/data_root_exists/mdcg_root_exists 的字典，其中 source 按 ENV_DATA_ROOT 非空取 "env:MDCG_DATA_ROOT" → 否则 ENV_MDCG_ROOT 非空取 "env:MDCG_MDCG_ROOT" → 否则 _user_paths() 为非空 dict 取 "paths.json(用户级)" 或 "paths.json(兼容读旧包内位置)"（按 paths_file_source()）→ 否则取 "default(用户级状态根 data/)"。
def describe() -> dict:
    """当前解析结果的完整快照（供心跳/日志留痕）。"""
    dr = data_root()
    mr = mdcg_root()
    pf_src = paths_file_source()
    return {
        "plugin_root": plugin_root(),
        "state_root": state_root(),
        "data_root": dr,
        "mdcg_root": mr,
        "default_data_root": default_data_root(),
        "is_default": _same_path(dr, default_data_root()),
        "source": ("env:" + ENV_DATA_ROOT if os.environ.get(ENV_DATA_ROOT)
                   else ("env:" + ENV_MDCG_ROOT if os.environ.get(ENV_MDCG_ROOT)
                         else (("paths.json(用户级)" if pf_src == "user"
                                else "paths.json(兼容读旧包内位置)")
                               if _user_paths()
                               else "default(用户级状态根 data/)"))),
        "paths_file": paths_file(),
        "paths_file_source": pf_src,
        "legacy_data_root": legacy_data_root(),
        "legacy_data_exists": os.path.isdir(legacy_data_root()),
        "data_root_exists": os.path.isdir(dr),
        "mdcg_root_exists": os.path.isdir(mr),
    }


# 生效条件：path 为传入字符串（写入前反斜杠替换为 "/"），key 默认 "data_root"（传入时写入该键名）；先确保 <state_root()> 存在，读取 _user_paths()（可能来自旧包内位置的兼容读，异常时为 {}，故旧配置在首次改写时被带到新位置并从此由新件说了算）并补 "_comment"，再以该内容覆写 <state_root()>/paths.json 并返回该路径。
def set_user_root(path: str, key: str = "data_root") -> str:
    """把用户选择的路径写入**用户级** paths.json（不存在则创建）。返回文件路径。

    永远写新位置（不写旧包内那件）——旧位置会随包更新被删除，写进去等于
    用户设置迟早丢失；旧件的既有取值经 _user_paths() 带入新件，不丢配置。
    """
    pf = os.path.join(state_root(), "paths.json")
    os.makedirs(os.path.dirname(pf), exist_ok=True)
    d = _user_paths()
    d.setdefault("_comment",
                 "灵枢记忆写入路径（用户可改）。删掉本文件即回落到用户级默认数据根"
                 "（~/.dsh/.dsh-memory/data）。")
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
                    help="把数据根写入 <用户级状态根>/paths.json（用户可改）")
    ap.add_argument("--set-mdcg-root", metavar="PATH",
                    help="把认知图根写入 <用户级状态根>/paths.json")
    ap.add_argument("--migrate-legacy", action="store_true",
                    help="把旧版包内 data/ 的数据面复制到用户级默认数据根"
                         "（只复制不删除；默认数据根被显式配置时不动作）")
    a = ap.parse_args()
    if a.set_root:
        print("written:", set_user_root(a.set_root, "data_root"))
    if a.set_mdcg_root:
        print("written:", set_user_root(a.set_mdcg_root, "root"))
    if a.migrate_legacy:
        print("migrate:", json.dumps(migrate_legacy_data(),
                                     ensure_ascii=False))
    print(json.dumps(describe(), ensure_ascii=False, indent=2))