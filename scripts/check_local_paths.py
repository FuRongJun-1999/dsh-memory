#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""本机路径门禁（B6）：**仓库追踪面不得含本机目录结构路径**。

为什么需要：仓库是公开面（GitHub + npm 白名单含 docs/ 等目录），历次报告把本机
绝对路径（盘符 + 父目录层）写进了正文——本机目录结构泄露属于隐私面问题（工作纪律
第 14 条「公开产物过隐私双清单」）。npm 发布面另有 check_publish_artifact.py 的
R3 规则（LOCAL_PATH_PROGRAM / LOCAL_PATH_USER / REMOTE_SANDBOX）把关；本脚本把
**判据面扩到全部 git 追踪件**（GitHub 公开面 = `git ls-files`），两处判据互补。

判据（deny 家族，只认**机器实有前缀**，不认通用/合成路径）：
  ① 本仓机器父级        `<盘符>\program\...`（本仓、AEIS 在役库、e2e_judge 数据根等）
  ② AI 目录族           `<盘符>\1_ai` ~ `<盘符>\4_ai`（外部设计稿/基准目录所在层）
  ③ 旧机 Program Files  `<盘符>\Program Files\2_ai\...`
  ④ DSH 本机 home       `<盘符>\dsh-home\...`（标准写法 %USERPROFILE%\.dsh）
  ⑤ E 盘沙箱            盘符为 E 时的 `\test\` 顶层（发版验证空沙箱）
  ⑥ 用户实名目录        `C:\Users\<实名>\...`（与 R3 同口径）
  ⑦ 用户目录子面        `C:\Users\<任意用户>\{AppData,.dsh,.mdcg}\...`（机器目录结构，用户名本身不判）
  ⑧ 安装面读数          `<盘符>\Program Files\Docker\...`（本机 which 读数，非默认路径通例）

**不在判据面**（有意放行，避免平凡红）：合成夹具（`X:/custom`、`G:/fake`、
`C:/Windows/win.ini`、`D:/proj`、`E:/new`、`D:/old`、`C:/Users/test/evil` 等）、
通用通例（`C:/Program Files/Git/work` = Git for Windows 标准改写行为、`C:\Windows\System32`
= 每台 Windows 都有）、占位写法（`d:/.../dsh-memory`、`<仓根>`）。

写法约束：本文件自身在扫描面内 ⇒ 规则字面量与样例一律**拼接构造**（同
check_publish_artifact.py 既有做法），`--selftest` 断言「不命中自身源码」。

退出码：0 通过 / 1 有命中 / 2 环境错误（fail-closed，绝不静默放行）。
"""
import os
import re
import subprocess
import sys

BS = chr(92)
SEP = "[" + BS + BS + "/" + "]{1,2}"
DRIVE = "[A-Za-z]:"


def _build_rules():
    return [
        ("本仓机器父级", DRIVE + SEP + "program(?![A-Za-z0-9_])"),
        ("AI 目录族", DRIVE + SEP + "(1_ai|2_ai|3_ai|4_ai)(?![A-Za-z0-9_])"),
        ("旧机 Program Files", DRIVE + SEP + "[Pp]rogram Files" + SEP + "2_ai"),
        ("DSH 本机 home", DRIVE + SEP + "dsh-home(?![A-Za-z0-9_])"),
        ("E 盘沙箱", "E:" + SEP + "test(?![A-Za-z0-9_])"),
        ("用户实名目录", "C:" + SEP + "Users" + SEP + "(Fu" + "RongJun|FU" + " RONG~1)"),
        ("用户目录子面",
         "C:" + SEP + "Users" + SEP + "[^" + BS + "/]+" + SEP
         + "(AppData|" + BS + ".dsh|" + BS + ".mdcg)"),
        ("安装面读数", DRIVE + SEP + "[Pp]rogram Files" + SEP + "Docker"),
    ]


RULES = [(label, re.compile(rx)) for label, rx in _build_rules()]

#: 合成夹具/通用通例（负样例；放进 selftest 断言「不命中」）
NEGATIVE_SAMPLES = [
    "X:/custom/hive.exe", "G:/fake/.git", "C:/Windows/win.ini", "D:/proj",
    "E:/new", "D:/old", "C:/Users/test/evil", "C:/Users/x/.cargo/bin/cargo.exe",
    "D:/gt-ws", "E:/private/node.log", "C:/Program Files/Git/work",
    "C:/Windows/System32", "D:/lingshu/mdcg", "D:/mem", "D:/somewhere/mdcg",
    "D:/.../public-root", "X:" + BS + "custom" + BS + "scope",
]

#: 样例一律变量式构造——盘符/分隔符不经字面量，防「守卫扫到自己」（同 R3 既有做法）
_DR = "D"
_CR = "C"
_SL = "/"
_DL = BS
POSITIVE_SAMPLES = [
    ("本仓机器父级", _DR + ":" + _DL + "program" + _DL + "x"),
    ("本仓机器父级", _DR + ":" + _SL + "program"),
    ("AI 目录族", _DR + ":" + _DL + "2_ai" + _DL + "d.md"),
    ("旧机 Program Files", _DR + ":" + _SL + "Program Files" + _SL + "2_ai/AEIS"),
    ("DSH 本机 home", _DR + ":" + _DL + "dsh-home" + _DL + "sessions"),
    ("E 盘沙箱", "E" + ":" + _SL + "test/smoke"),
    ("用户实名目录", _CR + ":" + _SL + "Users" + _SL + "Fu" + "RongJun"),
    ("用户目录子面", _CR + ":" + _DL + "Users" + _DL + "somebody" + _DL + "AppData" + _DL + "Temp"),
    ("用户目录子面", _CR + ":" + _SL + "Users" + _SL + "somebody" + _SL + ".mdcg/x.py"),
    ("安装面读数", _CR + ":" + _DL + "Program Files" + _DL + "Docker" + _DL + "x.exe"),
    ("AI 目录族", _DR + ":" + _DL + _DL + "2_ai" + _DL + _DL + "d.md"),
]


def hit_samples():
    bad = []
    for label, sample in POSITIVE_SAMPLES:
        hit = any(rx.search(sample) for lab, rx in RULES if lab == label)
        if not hit:
            bad.append("正样例未命中：%s <- %s" % (label, sample))
    for sample in NEGATIVE_SAMPLES:
        for lab, rx in RULES:
            if rx.search(sample):
                bad.append("负样例被误命中：%s <- %s" % (lab, sample))
    return bad


def own_source_clean(path):
    text = open(path, encoding="utf-8").read()
    return [lab for lab, rx in RULES if rx.search(text)]


def selftest():
    problems = hit_samples()
    src = os.path.abspath(__file__)
    own = own_source_clean(src)
    if own:
        problems.append("本文件自身命中规则：%s" % "、".join(own))
    if problems:
        for p in problems:
            print("  [FAIL] %s" % p)
        print("  SELFTEST=FAIL（%d 项）" % len(problems))
        return 1
    print("  自检：正样例 %d 项全命中 / 负样例 %d 项零命中 / 自身源码零命中"
          % (len(POSITIVE_SAMPLES), len(NEGATIVE_SAMPLES)))
    print("  SELFTEST=PASS")
    return 0


def tracked_files(root):
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            capture_output=True, cwd=root, shell=False, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [x.decode("utf-8", "replace") for x in proc.stdout.split(b"\x00") if x]


def scan(root):
    """→ 命中清单（list）；环境错误返回 None（fail-closed，调用方判 2）。"""
    files = tracked_files(root)
    if files is None:
        return None
    hits = []
    for f in files:
        p = os.path.join(root, f)
        try:
            b = open(p, "rb").read()
        except OSError:
            continue
        if b"\x00" in b[:8192]:
            continue
        t = b.decode("utf-8", "replace")
        for i, line in enumerate(t.splitlines(), 1):
            for lab, rx in RULES:
                m = rx.search(line)
                if m:
                    snip = m.group(0)
                    if len(snip) > 80:
                        snip = snip[:80] + "..."
                    hits.append("%s:%d [%s] %s" % (f, i, lab, snip))
    return hits


def main(argv):
    if "--selftest" in argv:
        return selftest()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print("=== 本机路径门禁（追踪面）===")
    print("  对象 root=%s；判据=机器实有前缀 %d 族（合成夹具/通用通例不在面）"
          % (root, len(RULES)))
    hits = scan(root)
    if hits is None:
        print("  [环境错误] 无法执行 git ls-files -z——fail-closed")
        return 2
    if hits:
        print("  [FAIL] 命中=%d" % len(hits))
        for h in hits[:20]:
            print("         - %s" % h)
        if len(hits) > 20:
            print("         ...（共 %d 条）" % len(hits))
        print("  VERDICT=FAIL：本机路径不得进入追踪面——改写为相对路径或中性占位"
              "（仓内 `<仓根>`、家目录 `~/`、临时 `%TEMP%`）")
        return 1
    print("  [PASS] 追踪面零本机路径")
    print("  VERDICT=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
