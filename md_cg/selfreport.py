# -*- coding: utf-8 -*-
"""常驻进程自报：把「我是谁 / 我从哪个 md_cg 包加载 / 我持哪一代 render 契约」
落成**外部可读的事实**。

# 生效条件：载体/位置：仓根 md_cg/selfreport.py（import 路径 md_cg.selfreport）；时间：常驻 md_cg MCP server 进程启动时由 mcp_server.main 调用 report()；方法：info() 采集进程事实（pid/ppid/cwd/argv/sys.path[0]），source_dir/source_file/render_version 由 codeindex 的实际加载位置与常量求出，report() 原子写 <tempdir>/md_cg_servers/<pid>.json；约束：**任何异常一律吞掉并返回 None/空**——自报是诊断设施，不得成为服务故障源；不记录环境变量值，只记录 MDCG_ROOT/MDCG_TOKEN 是否已设置。

## 为什么需要它（根因，非猜测）

判「一个常驻 md_cg 进程会不会用旧契约覆盖重建成果」，原先只能比「进程启动时间 vs
md_cg/*.py 最新 mtime」。该判据有**活体盲区**：npm 副本内的进程启动于 11:37~11:39，
而源码 mtime 为 09:24 —— `stale=False`，但它加载的是插件包 0.4.8 的
`codeindex.render`（旧契约：合成 `# 生效条件：载体/位置：`），会把全量重建成果刷回
`old_synth`（AGENTS.md §5 运维注记实证）。mtime 是**相对量**，每次须复算且天然滞后。

自报给的是**绝对事实**：进程**自己**报出它实际加载的 `md_cg` 包目录与契约代际。
外部脚本据此机械裁决，不再推断。旧包不含本模块，故**「无自报」本身即旧契约的证据**
（唯一例外见 `scripts/mdcg_stale_servers.py` 的 cwd 兜底分支）。

## 边界

- 自报目录取 `tempfile.gettempdir()`（同用户跨端一致），不依赖 MDCG_ROOT——
  库根未设时也要能判「进程持哪代契约」。
- 只报事实，不做裁决：`render_version` 由消费方与本仓 `codeindex.RENDER_VERSION`
  比对（同源，不写死版本号，避免两处漂移）。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

# 自报目录：同用户、跨端一致（DSH 与 CodeBuddy 的 python 子进程共用同一 tempdir）。
SELF_REPORT_DIR = os.path.join(tempfile.gettempdir(), "md_cg_servers")
# 自报格式代际：本模块自身结构变化时才 +1（与 codeindex.RENDER_VERSION 无关，
# 后者描述「节点正文由哪代 render 产出」，属索引契约，两者不可混用）。
SELF_REPORT_SCHEMA = 1


# 生效条件：无入参；返回 (source_dir, render_version, source_file)——均取自 codeindex 模块**实际加载位置**（而非本文件所在包），故包被 __path__ 重定向后报的是真源；import 失败时三项均 None，不抛。
def _source():
    try:
        from . import codeindex
        return (os.path.dirname(os.path.abspath(codeindex.__file__)),
                getattr(codeindex, "RENDER_VERSION", None),
                os.path.abspath(codeindex.__file__))
    except Exception:                     # noqa: BLE001 —— 自报失败降级为 None
        return None, None, None


# 生效条件：tag 为任意字符串（缺省空串）；返回本进程自报字典，键固定为 schema/pid/ppid/ts/iso/tag/cwd/argv/sys_path0/python/source_dir/source_file/render_version/mdcg_root_set/mdcg_token_set；任何取值失败均降级为 None 而不抛。
def info(tag: str = "") -> dict:
    """采集本进程事实（纯读取，不写盘）。"""
    sd, rv, sf = _source()
    try:
        cwd = os.getcwd()
    except Exception:                     # noqa: BLE001
        cwd = None
    try:
        ppid = os.getppid()
    except Exception:                     # noqa: BLE001
        ppid = None
    try:
        sp0 = sys.path[0] if sys.path else None
    except Exception:                     # noqa: BLE001
        sp0 = None
    now = time.time()
    return {
        "schema": SELF_REPORT_SCHEMA,
        "pid": os.getpid(),
        "ppid": ppid,
        "ts": now,
        "iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "tag": str(tag or ""),
        "cwd": cwd,
        "argv": list(sys.argv),
        "sys_path0": sp0,
        "python": "%d.%d.%d" % sys.version_info[:3],
        # 只报「是否设置」，不落值——避免令牌/库根出现在可被他人读取的临时文件里。
        "mdcg_root_set": bool(os.environ.get("MDCG_ROOT")),
        "mdcg_token_set": bool(os.environ.get("MDCG_TOKEN")),
        "source_dir": sd,
        "source_file": sf,
        "render_version": rv,
    }


# 生效条件：tag 为任意字符串；成功时把 info(tag) 原子写入 <tempdir>/md_cg_servers/<pid>.json（先写 .tmp 再经 fsutil.publish 改名，带 Windows 短重试），并追加 self_report_path 键后返回该字典；任何异常（目录不可建/不可写/序列化失败）一律吞掉并返回 None——自报故障绝不向上传播。
def report(tag: str = "mcp_server"):
    """写自报文件（fail-safe：失败返回 None，不抛）。"""
    try:
        data = info(tag)
        os.makedirs(SELF_REPORT_DIR, exist_ok=True)
        path = os.path.join(SELF_REPORT_DIR, "%d.json" % data["pid"])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        from .fsutil import publish
        publish(tmp, path)
        data["self_report_path"] = path
        return data
    except Exception:                     # noqa: BLE001
        return None


# 生效条件：无入参；返回 {pid(int): 自报字典}——读 SELF_REPORT_DIR 下全部 *.json，逐文件 json.loads 失败或 pid 键缺失/非整数者静默跳过（坏文件不使整体失败）；目录不存在时返回空字典。
def read_all() -> dict:
    """读全部自报（只读，无副作用）。"""
    out = {}
    try:
        names = os.listdir(SELF_REPORT_DIR)
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(SELF_REPORT_DIR, n), "r",
                      encoding="utf-8", errors="replace") as fh:
                d = json.load(fh)
            pid = int(d.get("pid"))
        except Exception:                 # noqa: BLE001
            continue
        out[pid] = d
    return out


# 生效条件：pids 为可迭代的 pid 集合（通常是「当前进程表中仍在的 md_cg 进程」）；删除自报目录中 pid 不在该集合内的 *.json 与遗留 *.tmp，返回删除条数；目录不存在或删除失败逐项吞掉，不抛。
def purge(pids) -> int:
    """清掉不属于「仍在的进程」的自报文件（防目录随重启次数膨胀）。"""
    keep = {int(p) for p in (pids or ())}
    n = 0
    try:
        names = os.listdir(SELF_REPORT_DIR)
    except OSError:
        return 0
    for name in names:
        try:
            if name.endswith(".tmp"):
                os.remove(os.path.join(SELF_REPORT_DIR, name))
                n += 1
                continue
            if not name.endswith(".json"):
                continue
            if int(name[:-5]) in keep:
                continue
            os.remove(os.path.join(SELF_REPORT_DIR, name))
            n += 1
        except Exception:                 # noqa: BLE001
            continue
    return n
