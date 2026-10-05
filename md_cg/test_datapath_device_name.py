# -*- coding: utf-8 -*-
"""test_datapath_device_name.py · Windows 保留设备名末段吞路径的守卫（issue #39 相邻缺陷）

现场（Windows 实测）：``ntpath.abspath`` 经 ``GetFullPathNameW`` 归一路径时，若
路径**末段是 Windows 保留设备名**（aux/con/nul/prn/com1-9/lpt1-9 等），整个路径
被吞成设备命名空间形态——env 设 ``MDCG_AUX_ROOT=<临时目录>\\aux`` 时
``datapath.aux_root()`` 返回 ``\\\\.\\aux``，原目录语义**静默丢失**：密钥/令牌/
信任面被指到不存在的设备路径，覆盖键静默失联（不报错、最难察觉的失败形态）。
``abspath`` 是纯字符串归一**不触盘**，故守卫只需把 env 指向含保留名末段的
**不存在路径**即可实弹复现——绝不能真的创建 aux 末段目录（Win32
CreateDirectory 同样被设备名劫持）。

修复（本守卫的红绿两态锚点）：``md_cg/datapath.py`` 新增模块级
``_abs_host_path(p, env_key)``——Windows（os.name=="nt"）上归一结果以
``\\\\.\\`` 前缀开头即抛 ValueError（消息含键名与「保留设备名」字样及改法）；
``state_root``/``data_root``/``mdcg_root``/``aux_root`` 四处 env 覆盖面（含
paths.json 直值面）改走该辅助。非 Windows 平台 ``\\\\.\\aux`` 是合法目录名
字面量，**不判定**（§4 在 POSIX 上反断言「不抛」，守住平台闸本身）。
承接面：``mcp_server.main()`` 启动早期对 root/aux 各探一次，ValueError →
stderr 告警 + return 2（对照 `_md_cg_` 前缀守卫先例「启动即拒绝，不带病运行」）。

issue #57 加固（判据与 OS 行为解耦）：较新 Windows 构建的 GetFullPathNameW 不再把
「<目录>\\aux」吞成 ``\\.\aux``，前缀判据随之失效（报告人红单：aux/con/com1/lpt1
漏判、nul 未漏，本机旧构建仍吞、复现不了该红）——``md_cg/datapath.py`` 新增
``_RESERVED_DEVICE_NAMES`` 与纯函数 ``_reserved_device_tail``（末段直判），
``_abs_host_path`` 条件改为「设备前缀判据 或 末段直判」两因并置。§7 谓词表直调
纯函数（平台无关闭集）；§8 把模块所用 ``os.path.abspath`` 临时换成恒等函数、模拟
报告人系统复现漏判现场——删掉「或末段直判」后 §8 在 Windows 上必转红（变异自证锚点）。

隔离纪律：四个覆盖键（MDCG_STATE_ROOT/MDCG_DATA_ROOT/MDCG_ROOT/MDCG_AUX_ROOT）
与 DSH_HOME 以 os.environ 副本注入、finally 逐键还原；探针路径全部是
tempfile.mkdtemp 下**不存在**的纯字符串（或正常临时子目录），不创建任何含
保留名的真实目录，不触真实令牌库与真实状态根。env 直设即命中各函数第一分支，
paths.json 回落面零参与。

自检 floor：断言总数低于 FLOOR 视为失败——防「探针面失效 → 假绿」。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from .datapath import (ENV_AUX_ROOT, ENV_DATA_ROOT, ENV_MDCG_ROOT,
                       ENV_STATE_ROOT, _reserved_device_tail, aux_root,
                       data_root, mdcg_root, state_root)

# 断言总数下限（防假绿）：含 [7] 谓词表 35 条 + [8] 现场模拟 2 条，
# 按新增断言数上调后仍留 ≥8 条余量。
FLOOR = 50
PASS, FAIL = 0, 0

#: 守卫注入/还原面（含 DSH_HOME——state_root 的第二档，一并与真实环境隔离）
_GUARD_KEYS = (ENV_STATE_ROOT, ENV_DATA_ROOT, ENV_MDCG_ROOT, ENV_AUX_ROOT,
               "DSH_HOME")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def _probe_reject(fn, key, tail, tmp):
    """设 env=<tmp>/<tail>（不存在的纯字符串路径）→ 返回 (抛出异常, 异常消息)。

    红态（修复前）fn() 不抛而返回 \\\\.\\<tail> 形态——由调用方断言兜住。
    """
    os.environ[key] = os.path.join(tmp, tail)
    try:
        fn()
    except ValueError as ve:
        return True, str(ve)
    return False, ""


def _func_window(src: str, func_name: str) -> str:
    """取 src 中 ``def <func_name>`` 起到下一个顶层 ``def ``/``class`` 的源窗口。"""
    start = src.find(f"def {func_name}(")
    if start < 0:
        return ""
    nxt = src.find("\ndef ", start + 1)
    nxt_cls = src.find("\nclass ", start + 1)
    ends = [e for e in (nxt, nxt_cls) if e > 0]
    return src[start:min(ends)] if ends else src[start:]


def main():
    saved = {k: os.environ.get(k) for k in _GUARD_KEYS}
    tmp = tempfile.mkdtemp(prefix="mdcg_devname_")
    try:
        for k in _GUARD_KEYS:
            os.environ.pop(k, None)

        # ---- 1. 实弹红转绿核心：MDCG_AUX_ROOT 末段 aux → aux_root() 必须拒绝 ----
        print("[1] 实弹核心：MDCG_AUX_ROOT=<临时目录>\\aux（不存在，纯字符串）")
        raised, msg = _probe_reject(aux_root, ENV_AUX_ROOT, "aux", tmp)
        if os.name == "nt":
            check("1a aux_root() 抛 ValueError（红态：静默返回 \\\\.\\aux 不抛）",
                  raised, f"msg={msg[:160]!r}")
            check("1b 消息含覆盖键名 MDCG_AUX_ROOT（定位误配来源）",
                  ENV_AUX_ROOT in msg, f"msg={msg[:160]!r}")
            check("1c 消息含「保留设备名」字样（说清劫持机理）",
                  "保留设备名" in msg, f"msg={msg[:160]!r}")
        else:
            # 与 [4] 同口径：平台门在 `_abs_host_path`（`os.name == "nt"`），POSIX 上
            # `\\.\aux` 是合法目录名字面量，不判定 → 必须不抛且原样返回。
            check("1a 非 Windows 不判定（\\\\.\\aux 是合法目录名字面量，原样返回不抛）",
                  not raised, f"msg={msg[:160]!r}")
            check("1b 非 Windows 不判定：不产生保留设备名拒因（消息为空）",
                  msg == "", f"msg={msg[:160]!r}")
            check("1c 非 Windows 不判定：aux_root() 原样返回该路径（未被吞成设备路径）",
                  aux_root() == os.path.abspath(os.path.join(tmp, "aux")),
                  f"aux_root()={aux_root()!r}")

        # ---- 2. 同族四面：state/data/mdcg 各 env 面同样拒绝 ----
        print("[2] 同族 env 面（MDCG_STATE_ROOT/MDCG_DATA_ROOT/MDCG_ROOT）")
        for key, fn, tail in ((ENV_STATE_ROOT, state_root, "con"),
                              (ENV_DATA_ROOT, data_root, "nul"),
                              (ENV_MDCG_ROOT, mdcg_root, "aux")):
            raised, msg = _probe_reject(fn, key, tail, tmp)
            if os.name == "nt":
                check(f"2·{key}: {fn.__name__}() 抛 ValueError 且消息含键名"
                      "（env 直设命中第一分支，paths.json 零参与）",
                      raised and key in msg,
                      f"raised={raised} msg={msg[:160]!r}")
            else:
                # 与 [4] 同口径：平台门在 `_abs_host_path`，POSIX 不判定保留设备名。
                check(f"2·{key}: 非 Windows 不判定（末段 {tail} 是合法目录名，"
                      f"{fn.__name__}() 原样返回不抛）",
                      not raised
                      and fn() == os.path.abspath(os.path.join(tmp, tail)),
                      f"raised={raised} msg={msg[:160]!r} got={fn()!r}")

        # ---- 3. 正常路径不误伤：无保留名末段 → abspath 原样返回 ----
        print("[3] 正常路径不误伤（临时子目录，末段无保留名）")
        normals = {}
        for name in ("state", "data", "cgroot", "auxroot"):
            p = os.path.join(tmp, name)
            os.makedirs(p, exist_ok=True)
            normals[name] = p
        os.environ[ENV_STATE_ROOT] = normals["state"]
        os.environ[ENV_DATA_ROOT] = normals["data"]
        os.environ[ENV_MDCG_ROOT] = normals["cgroot"]
        os.environ[ENV_AUX_ROOT] = normals["auxroot"]
        check("3a 四面正常值全部原样返回（不抛、不变形）",
              state_root() == os.path.abspath(normals["state"])
              and data_root() == os.path.abspath(normals["data"])
              and mdcg_root() == os.path.abspath(normals["cgroot"])
              and aux_root() == os.path.abspath(normals["auxroot"]),
              f"state={state_root()!r} data={data_root()!r} "
              f"mdcg={mdcg_root()!r} aux={aux_root()!r}")

        # ---- 4. 保留名清单抽查（aux_root 面）：Windows 全抛；POSIX 反断言不抛 ----
        print("[4] 保留名清单抽查（aux/con/nul/com1/lpt1）")
        for tail in ("aux", "con", "nul", "com1", "lpt1"):
            raised, msg = _probe_reject(aux_root, ENV_AUX_ROOT, tail, tmp)
            if os.name == "nt":
                check(f"4·{tail}: aux_root() 抛 ValueError（GetFullPathNameW "
                      "劫持被拦）", raised, f"msg={msg[:160]!r}")
            else:
                check(f"4·{tail}: 非 Windows 不判定（\\\\.\\{tail} 是合法目录名"
                      "字面量，原样返回不抛）",
                      not raised, f"msg={msg[:160]!r}")

        # ---- 5. 源断言：辅助函数在、四处 env 面改走它、未改面逐字保留 ----
        print("[5] 源断言（datapath.py 四处 env 面 + mcp_server 承接）")
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "datapath.py"), encoding="utf-8") as fh:
            src = fh.read()
        check("5a datapath.py 定义 _abs_host_path",
              "def _abs_host_path(" in src)
        for fname in ("state_root", "data_root", "mdcg_root", "aux_root"):
            check(f"5·{fname}: 函数体改走 _abs_host_path（env 覆盖面全覆盖）",
                  "_abs_host_path(" in _func_window(src, fname))
        check("5e plugin_root 基于 __file__ 的 abspath 未改（非攻击/误配面，逐字保留）",
              "os.path.abspath(__file__)" in _func_window(src, "plugin_root"))
        with open(os.path.join(here, "mcp_server.py"), encoding="utf-8") as fh:
            msrc = fh.read()
        mwin = msrc[msrc.find("def main"):msrc.find("def main") + 2000]
        check("5f mcp_server.main() 启动早期探 root/aux 且 ValueError → return 2",
              "_probe_root" in mwin and "_probe_aux" in mwin
              and "except ValueError" in mwin and "return 2" in mwin,
              "main() 首段缺承接受理")
        check("5g _abs_host_path 源窗口含 _reserved_device_tail( 调用"
              "（末段直判与设备前缀判据并置，issue #57）",
              "_reserved_device_tail(" in _func_window(src, "_abs_host_path"))

        # ---- 7. 末段直判谓词表（issue #57）：_reserved_device_tail 纯函数窗口 ----
        # 谓词表取自实测闭集：会被吞的形态必须全判真（含变形 aux.txt/aux.tar.gz/
        # "aux."/"aux "（尾空格）/aux..b 与绝对路径末段/带尾分隔符形态）；不吞的
        # 形态必须全判假——com0/lpt0/com10/lpt10 数字越界、auxx/auxiliary 非设备名、
        # ".aux" 名字以点开头不拆扩展名。纯函数不触盘、无平台分支，Windows/POSIX 同判。
        print("[7] 末段直判谓词表（_reserved_device_tail，纯字符串·平台无关）")
        for case in ("aux", "AUX", "Aux", "aux.txt", "aux.tar.gz", "aux.",
                     "aux ", "aux..b", "con", "prn", "nul", "com1", "com9",
                     "lpt1", "lpt9", "com\u00b9", "com\u00b2", "com\u00b3",
                     "lpt\u00b9", "lpt\u00b2", "lpt\u00b3", "conin$", "conout$",
                     "D:\\probe\\aux", "D:\\probe\\aux\\", "D:\\probe\\aux.txt"):
            check(f"7·真·{case!r}: 判为保留设备名末段（须拦）",
                  _reserved_device_tail(case), "判为 False（漏拦）")
        for case in ("com0", "lpt0", "com10", "lpt10", "auxx", ".aux",
                     "auxiliary", "", "D:\\probe\\com0"):
            check(f"7·假·{case!r}: 不判保留设备名末段（须放行）",
                  not _reserved_device_tail(case), "判为 True（过拦）")

        # ---- 8. issue #57 现场模拟：abspath 不改写绝对路径（新 Windows 构建）----
        # 报告人系统（较新 Windows 构建）的 GetFullPathNameW 不再把「<目录>\aux」
        # 吞成 \\.\aux——既有前缀判据（r.startswith("\\\\.\\")）随之失效（本机旧
        # 构建仍吞、复现不了该红，故以恒等替换模拟）。本段把 datapath 模块所用的
        # os.path.abspath 临时换成恒等函数（保存/还原，finally），模拟「abspath
        # 原样返回绝对路径」的报告人行为，再经 _probe_reject 探 aux_root。
        # 变异自证锚点：删掉 _abs_host_path 条件里的 `or _reserved_device_tail(r)`
        # 后，本段在 Windows 上必须转红（r 不以 \\.\ 开头 → 不抛 → 8a/8b 失败），
        # 而 [7] 谓词表保持全绿（证明末段判定是承重件而非装饰）。
        print("[8] issue #57 现场模拟：abspath 恒等（新构建不吞设备名）")
        _abspath_orig = os.path.abspath
        try:
            os.path.abspath = lambda p: p
            raised, msg = _probe_reject(aux_root, ENV_AUX_ROOT, "aux", tmp)
        finally:
            os.path.abspath = _abspath_orig
        if os.name == "nt":
            check("8a abspath 不改写时 aux_root() 仍抛 ValueError（末段直判承重）",
                  raised, f"msg={msg[:160]!r}")
            check("8b 该路径下消息仍含覆盖键名 MDCG_AUX_ROOT",
                  ENV_AUX_ROOT in msg, f"msg={msg[:160]!r}")
        else:
            check("8a 非 Windows 不判定：abspath 恒等后仍不抛（平台闸未越界）",
                  not raised, f"msg={msg[:160]!r}")
            check("8b 非 Windows 不判定：不产生拒因（消息为空）",
                  msg == "", f"msg={msg[:160]!r}")

        # ---- 6. 守卫自检 floor ----
        # [6] 后置于 [7][8] 之后：FLOOR 随新增断言数上调，须统计全部断言。
        print("[6] 守卫自检")
        check(f"6a 断言总数 ≥ {FLOOR}（防探针面失效假绿）",
              PASS + FAIL >= FLOOR, f"total={PASS + FAIL}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n=== datapath device-name tests: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    sys.exit(main())
