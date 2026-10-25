# -*- coding: utf-8 -*-
"""全库文档相对链接巡检（防「文件移位后相对路径未同步」的断链复发）。

背景（2026-09-16 第 4 条根因取证）：外部评审实测全库 118 条 md 相对链接中 8 条
断链，根因两类——

  ① 投影管线基准错误：`cogmap_sync._mdlink` 以**仓根**为基准生成链接，落到
     `docs/mdcg/` 文档里被 GitHub/浏览器按**文档所在目录**解析 → 必断
     （已修：新增 `_rel_from_root` + `doc_dir` 形参）。
  ② 手写区无守卫：`cogmap_sync check` 只守 README 与功能调用映射表两文档的
     标记段及其链接，其余文档（如 `docs/mdcg/README详细版_v0.4.10.md`、
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
围栏代码块与行内代码（反引号跨度）内的文本先经 `_strip_code_spans` 置空——代码里
写出的链接形态是**示例**不是引用，按真链接判会假红（本仓实测自伤一次）。

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

# 白名单判据可用性（由 _allowlist() 写入，_allowlist_available() 读）：默认 True =
# 「还没取用，谈不上缺失」，避免 import 期就把它当成坏的。
_ALLOWLIST_OK = True


# 生效条件：用必需形参 args 追加到 ["git","-c","core.quotepath=false"] 后在模块常量 REPO 目录下执行（capture_output=True、text、encoding=utf-8、errors=replace、shell=False），返回 (r.stdout or "") 逐行 strip 后的非空行列表——r.stdout 为 None 或空串时返回 []，且不检查返回码。
def _git(args):
    # core.quotepath=false：否则非 ASCII 路径被八进制转义，tracked 集合无法匹配
    r = subprocess.run(["git", "-c", "core.quotepath=false"] + args, cwd=REPO,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", shell=False)
    return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


# 生效条件：成功导入 cogmap_sync 时返回 set(getattr(cogmap_sync,"FILE_LINK_ALLOWLIST",{}) or {})，即该属性为真值字典时得到其键集合、属性缺失或为假值（None/{}）时得到空集；导入触发 Exception 时打印警告、把模块级 `_ALLOWLIST_OK` 置 False 并返回空集（无必需形参）。
def _allowlist():
    """复用管线白名单（单一真源）。

    **空集有两种含义，必须能分开**：① `cogmap_sync` 载入成功、白名单本身为空
    （= 当前确实没有登记条目，判据完整）；② `cogmap_sync` 载不进来（= 判据缺失）。
    旧写法两种都返回 `set()`，于是②会被读成①：已登记的「本地才有」链接全部掉进
    BROKEN/UNTRACKED，产出一批假红，而提示只是一行 print、退出码照旧按红色算。
    `_allowlist_available()` 就是给调用方区分这两种情况的唯一入口。
    """
    global _ALLOWLIST_OK
    try:
        import cogmap_sync
        _ALLOWLIST_OK = True
        return set(getattr(cogmap_sync, "FILE_LINK_ALLOWLIST", {}) or {})
    except Exception as exc:  # pragma: no cover - 仅在非常规调用方式下触发
        _ALLOWLIST_OK = False
        print("警告：未能载入 cogmap_sync.FILE_LINK_ALLOWLIST（%s）；"
              "白名单不可用 ⇒ 本轮的 ALLOWED 恒为 0，已登记链接会落到 BROKEN/UNTRACKED"
              % exc)
        return set()


# 生效条件：返回上一次 _allowlist() 的载入结果——成功导入为 True，导入抛异常为 False；从未调用过时为 True（未取用即不受影响）。
def _allowlist_available() -> bool:
    """白名单判据是否可用（区分「登记为空」与「判据缺失」）。"""
    return _ALLOWLIST_OK


# 生效条件：必需形参 relcand 精确命中必需形参 tracked 集合时返回 True；否则仅当 tracked 中存在以 relcand.rstrip("/")+"/" 为前缀的元素时返回 True，tracked 为空集时 any(...) 为 False 而返回 False。
def _tracked_ok(relcand, tracked):
    """目标为目录时，只要其下有受管文件即视为已入库。"""
    if relcand in tracked:
        return True
    prefix = relcand.rstrip("/") + "/"
    return any(p.startswith(prefix) for p in tracked)


# 围栏开启行口径对齐 md_cg/docindex.py::_FENCE（`^\s*(```+|~~~+)`）；闭合按 CommonMark
# 从紧：同定界符、不短于开启者、且无信息串（围栏内的 ` ```js ` 只算代码内容）。
_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})")
_BACKTICK_RUN = re.compile(r"`+")


# 生效条件：对任意 line（含空串、无成对反引号者）用 _BACKTICK_RUN 取全部反引号串，按出现序以**同长度**成对（CommonMark 口径：长度不等者视为代码内容，继续找闭合），返回 [(start,end)] 半开区间列表；无成对者返回空列表。
def _code_span_ranges(line):
    """行内代码跨度 [start,end)：反引号串按同长度成对。"""
    runs = [(m.start(), m.end()) for m in _BACKTICK_RUN.finditer(line)]
    spans, opening = [], None
    for r in runs:
        if opening is None:
            opening = r
        elif (r[1] - r[0]) == (opening[1] - opening[0]):
            spans.append((opening[0], r[1]))
            opening = None
    return spans


# 生效条件：逐行扫描 text（\n 切分，末行无 \n 亦计）——不在围栏内时遇 _FENCE_OPEN 匹配行打开围栏（记录定界符与长度）、否则把该行 _code_span_ranges 命中的字符置空格；在围栏内时整行置空格、遇「同定界符且长度≥开启者且无信息串」的行闭合；返回与 text **等长且换行位置不变**的字符串（代码跨度外字符原样保留）。
def _strip_code_spans(text):
    """把围栏代码块与行内代码跨度内的字符换成空格（长度/换行不变）。

    单点：scan() 的链接匹配面前置本函数。为什么必须做——代码块/行内代码里写出的
    Markdown 链接形态（示例、伪码、模板占位）不是引用，按真链接判会假红（本仓实测
    自伤一次：报告正文写出该形态即令 gate 红）。判据本身（围栏外真链接判 broken）
    不动，只把「示例」排除出扫描面；等长替换保证 scan() 报出的行号仍是源文件行号。
    """
    out = list(text)
    i, fence = 0, None            # fence = (定界符, 长度)；None = 不在围栏内
    while i < len(text):
        j = text.find("\n", i)
        if j < 0:
            j = len(text)
        line = text[i:j]
        s = line.strip()
        blank = False
        if fence is not None:
            blank = True
            if s and s.count(fence[0]) == len(s) and len(s) >= fence[1]:
                fence = None                      # 闭合行本身也属围栏，一并置空
        else:
            m = _FENCE_OPEN.match(line)
            if m:
                fence = (m.group(1)[0], len(m.group(1)))
                blank = True
            else:
                for a, b in _code_span_ranges(line):
                    for k in range(i + a, i + b):
                        out[k] = " "
        if blank:
            for k in range(i, j):
                out[k] = " "
        i = j + 1
    return "".join(out)


# 生效条件：对 _git(["ls-files","*.md"]) 的每个 rel 且 os.path.isfile 为真者读文并经 _strip_code_spans 后按模块常量 LINK 逐条匹配——raw 以 SKIP_SCHEMES 开头则跳过；target（raw 去 "#" 首段）为空或含 NON_PATH_CHARS 者计入 non_path；否则按 target 是否以 "/" 前缀分别以 REPO 或文档所在目录 normpath 得 cand 与 relcand，relcand 或 target 命中 _allowlist() 计入 n_allowed，cand 不满足 os.path.exists 计入 broken，否则 _tracked_ok(relcand,tracked) 为假计入 untracked，其余计入 n_ok，最终返回含 files/broken/untracked/non_path/ok/allowed 的 dict。
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
        for m in LINK.finditer(_strip_code_spans(text)):
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
            "non_path": non_path, "ok": n_ok, "allowed": n_allowed,
            "allowlist_available": _allowlist_available()}


# 生效条件：无必需形参，取 scan() 结果后——白名单判据不可用且命令行带 --require-allowlist 时先打印判据缺失并返回 3；否则 res["broken"] 或 res["untracked"] 任一非空则打印断链结论并返回 1，皆空则打印全部可达并返回 0（非路径条目只计数打印，不影响返回值）。
def main():
    res = scan()
    if res["allowlist_available"] is False:
        print("[判据缺失] cogmap_sync.FILE_LINK_ALLOWLIST 载入失败：本轮 ALLOWED 恒为 0，"
              "BROKEN/UNTRACKED 里可能混着已登记条目。")
        if "--require-allowlist" in sys.argv[1:]:
            print("结论：前置条件不成立（白名单判据缺失），检查没做成——退出码 3。")
            return 3
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
