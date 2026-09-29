#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_open_encoding.py · 文本模式 `open` 的显式 `encoding` 机械守卫（B 项 / 纪律第15条）

**守卫面**：`md_cg/`、`hive/`、`scripts/` 下**全部** `.py`（含 `test_`/`bench_` 面）里，
凡**文本模式**的文件读写一律须显式声明 `encoding=`——不依赖 locale（Windows 上
locale=cp936，读 UTF-8 中文内容即 UnicodeDecodeError，写则静默产出 GBK 字节）。

**为什么不是文本模式扫描**（前一轮的口径教训）：`224 处` / `103 处` 两个数字都不准——
文本窗口与「attr == 'open'」匹配会把 `os.open` / `io.open` / `tarfile.open` / `gzip.open`
一并算作裸 open。本守卫用 `ast` 只认**内建 open**（`ast.Name` 且 `id == 'open'`），
Attribute 形态一律不计——判据落在语法意义上，不落在外形上。

判据（逐条）：
  ① 只认内建 `open`（`ast.Name` 且 `id == 'open'`）；`os.open` / `io.open` / `tarfile.open`
     / `gzip.open` / `zipfile.ZipFile.open` 等 Attribute 形态**一律不计**。
  ② 第二参数（或 `mode=` 关键字）**字面量含 'b'** → 不计（二进制模式传 `encoding=` 非法）。
  ③ `mode` 非字面量 / 缺失 / `**kwargs` 透传 → **计入**且要求显式 `encoding`
     （保守：口径无法确认即不合格，宁严勿松）。
  ④ `read_text` / `write_text`（Attribute 形态）无 `encoding` → 计入。
     注：`write_text(p, text)` 形态的**模块内自建同名函数**（如
     `scripts/_mdcg_reindex_dshlogs.py:148`）不是本判据的对象——那是一个普通函数调用，
     其函数体内的 `open` 已由 ①②③ 覆盖，不重复计。

**ANCHOR（漂移即报，退出码 2，fail-closed）**——三类：
  · 判据锚：内嵌 `_ANCHOR_CORPUS` 的 22 个固定片段，每个都有**预期违例数**；任一
    预期不成立 ⇒ 判据（分类逻辑）已漂移，不得放行。
  · 扫描面锚：`_FLOORS` 下限（文件数 / 文本 open / 二进制 open / Attribute open /
    read_text-write_text）。计数塌到下界以下 ⇒ 目录改名或枚举失效，**不得当假绿**。
  · 对照点位锚：`_ATTR_CONTROL_FILES` 这 5 个**真实假阳性点位**所在文件必须仍存在且
    仍含有 Attribute `.open(` ——对照面消失即报 ANCHOR-MISS（沉默的豁免比红更危险）。
    其下再钉一层 `_ATTR_CONTROL_POINTS`：契约本轮点名的 **5 个假阳性点位**
    （文件 + 该点位上的 Attribute 被调者名，如 `scripts/check_publish_artifact.py`
    的 `tarfile.open`）逐个须仍在位——文件级锚只保证「文件里还有某个 Attribute
    `.open`」，点位级锚才保证「被误报的那类形态仍在对照面上」。

**白名单**：本项（B）收口口径为**空**。`WHITELIST` 若被填入内容，须是**显式文件清单**，
且守卫**双向**报出「白名单有而未命中」与「命中而不在白名单」，绝不做静默豁免。

退出码：0 = 全绿；1 = 存在违例（含白名单不吻合）；2 = ANCHOR-MISS（锚点漂移）。

用法：
  python scripts/verify_open_encoding.py            # 扫全仓（默认）
  python scripts/verify_open_encoding.py --self-test # 锚点 + 定点变异自证
"""
from __future__ import annotations

import argparse
import ast
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)

# ---------------------------------------------------------------- 入口自保证 UTF-8
# 约束（工作纪律第 15 条）：本调用必须在**任何文件/库 I/O 之前**——utf8_boot.ensure_utf8
# 在解释器未开 UTF-8 模式时以相同 argv 重启自身（-X utf8）。**本守卫自身也必须先保证**：
# 它的诊断行含 `✔`/`✘`，未开模式时这些字符以 cp936 编码直接 `UnicodeEncodeError` 崩掉，
# 而退出码 1 与「扫描到违例」同码 ⇒ 裁决现场的红灯信号被污染（本仓自检项 §6.3 / Q7 记录
# 的正是这一形态）。仓库根入 sys.path 的形态照 scripts/run_tests.py 的最小写法（助手在仓根）。
# 被 import（本模块非 __main__）时助手只置子进程继承面、绝不重启/退出——F6：静默重启
# 会吞掉调用方输入。
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from utf8_boot import ensure_utf8  # noqa: E402

ensure_utf8(__file__)

#: 扫描面：三项全扫（含 test_/bench_ 面——测试夹具同样会被非桥路径拉起）
SCAN_DIRS = ("md_cg", "hive", "scripts")

#: 白名单：**B 项收口口径 = 空**。将来确需豁免时填 {相对路径: 理由}，
#: 守卫会双向核对（有而未命中 / 命中而不在清单），不留静默豁免通道。
WHITELIST: dict[str, str] = {}

#: 扫描面下限（ANCHOR）。实测基线（2026-09-29 本机全仓 walk 的量级）：文件 ~490 /
#: 文本模式内建 open ~840（其中 mode 不可判定 ~400）/ 二进制模式内建 open 89 /
#: Attribute `.open(` 66 / `read_text`-`write_text` 6。下限取基线的 ~85%——
#: 只在「枚举面塌陷 / 判据坏了」时触发，不因正常的文件增删误报。
_FLOORS = {
    "files": 420,
    "text_open": 700,
    "bin_open": 76,
    "attr_open": 56,
    "attr_text_rw": 4,
}

#: Attribute `.open(` 假阳性对照点位（本轮实测的真实点位；文件须仍在且仍有 Attribute open）
_ATTR_CONTROL_FILES = (
    "scripts/check_publish_artifact.py",        # tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")
    "scripts/criteria_fingerprint.py",          # tarfile.open(...)
    "md_cg/fsutil.py",                          # os.open(...)
    "md_cg/lexicon/build_cedict_en_zh.py",      # gzip.open(...) / io.open(...)
    "md_cg/bench_en_atoms_public.py",           # io.open(...)
)

#: 契约本轮点名的 5 个 Attribute 假阳性**点位**（文件 → 该点位上的被调者点分名）。
#: 与 `_ATTR_CONTROL_FILES` 的分工：文件级只保证「该文件里仍有某个 Attribute `.open`」，
#: 点位级保证「**被误报的那一类形态**仍在对照面上」——例如把 `tarfile.open` 换成别的
#: Attribute 调用时，文件级锚不会红，点位级锚会红（沉默的对照面塌陷比红更危险）。
_ATTR_CONTROL_POINTS = (
    ("scripts/check_publish_artifact.py", "tarfile.open"),
    ("scripts/criteria_fingerprint.py", "tarfile.open"),
    ("md_cg/fsutil.py", "os.open"),
    ("md_cg/lexicon/build_cedict_en_zh.py", "io.open"),
    ("md_cg/lexicon/build_cedict_en_zh.py", "gzip.open"),
)

#: 判据锚：固定片段 → 预期违例数。任一对不上即判据漂移。
_ANCHOR_CORPUS = (
    ("builtin_bare_w",           'open(p, "w")\n', 1),
    ("builtin_bare_default",     'open(p)\n', 1),
    ("builtin_bare_mode_kw",     'open(p, mode="a")\n', 1),
    ("builtin_bare_binary_read", 'open(p, "rb")\n', 0),
    ("builtin_bare_binary_wpb",  'open(p, "w+b")\n', 0),
    ("builtin_bare_var_mode",    'm = "r"\nopen(p, m)\n', 1),
    ("builtin_bare_star_args",   'open(p, *rest)\n', 1),
    ("builtin_bare_star_kwargs", 'open(p, "w", **kw)\n', 1),
    ("builtin_ok_encoding",      'open(p, "w", encoding="utf-8")\n', 0),
    ("builtin_ok_default_enc",   'open(p, encoding="utf-8")\n', 0),
    ("builtin_ok_enc_star",      'open(p, "w", encoding="utf-8", **kw)\n', 0),
    ("builtin_ok_binary_enc_none", 'open(p, "rb")\n', 0),
    ("attr_os_open",             'os.open(p, os.O_RDONLY)\n', 0),
    ("attr_io_open",             'io.open(p, "w", encoding="utf-8")\n', 0),
    ("attr_io_open_bare",        'io.open(p, "w")\n', 0),
    ("attr_tarfile_open",        'tarfile.open(fileobj=io.BytesIO(b), mode="r:gz")\n', 0),
    ("attr_gzip_open",           'gzip.open(p, "rb")\n', 0),
    ("attr_zipfile_open",        'zipfile.ZipFile.open(p)\n', 0),
    ("attr_read_text_bare",      'Path(p).read_text()\n', 1),
    ("attr_read_text_ok",        'Path(p).read_text(encoding="utf-8")\n', 0),
    ("attr_write_text_bare",     'Path(p).write_text(s)\n', 1),
    ("attr_write_text_ok",       'Path(p).write_text(s, encoding="utf-8")\n', 0),
)

#: 定点变异目标（一目录一个，真实仓库文件）：拷到临时面注入变体，断言**恰好**命中预期项数
_MUTATION_TARGETS = (
    "md_cg/test_lock.py",
    "hive/test_stop_tree_kill.py",
    "scripts/workspace_index.py",
)

_MUTATION_PROBE_BARE = '    return open(p, "w")'
_MUTATION_PROBE_BIN = '    return open(p, "rb")'
_MUTATION_PROBE_ATTR = '    return io.open(p, "r", encoding="utf-8")'
_MUTATION_PROBE_OK = '    return open(p, "w", encoding="utf-8")'


class AnchorMiss(Exception):
    """锚点漂移（退出码 2）。"""


# 生效条件：base 为仓根绝对路径时，遍历 SCAN_DIRS 下全部 .py（跳过 __pycache__；目录缺失即抛 AnchorMiss），返回按正斜杠相对路径排序的 (rel, abspath) 列表。
def list_py(base: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for d in SCAN_DIRS:
        top = os.path.join(base, d)
        if not os.path.isdir(top):
            raise AnchorMiss("扫描面目录缺失：%s" % d)
        for cur, subs, files in os.walk(top):
            subs[:] = [x for x in subs if x != "__pycache__"]
            for f in files:
                if f.endswith(".py"):
                    ap = os.path.join(cur, f)
                    out.append((os.path.relpath(ap, base).replace("\\", "/"), ap))
    return sorted(set(out))


# 生效条件：node 为 ast.Call 时返回 "builtin-open"（内建 open）/"attr-open"（任意 X.open）/"attr-text-rw"（X.read_text|X.write_text）之一，其它返回 None；内建判定只认 ast.Name 且 id=='open'。
def _callee_kind(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name) and f.id == "open":
        return "builtin-open"
    if isinstance(f, ast.Attribute):
        if f.attr == "open":
            return "attr-open"
        if f.attr in ("read_text", "write_text"):
            return "attr-text-rw"
    return None


# 生效条件：node 为内建 open 调用；返回 (kind, mode)——kind ∈ {"literal","missing","unknown"}；"literal" 时 mode 为字面量字符串（位置参或 mode= 关键字皆可），位置参为 *args 展开时一律 "unknown"。
def _mode_of(node: ast.Call) -> tuple[str, str]:
    kws = {k.arg: k.value for k in node.keywords if k.arg is not None}
    if len(node.args) >= 2:
        m: ast.AST = node.args[1]
        if isinstance(m, ast.Starred):
            return "unknown", ""
    elif "mode" in kws:
        m = kws["mode"]
    else:
        return "missing", ""
    if isinstance(m, ast.Constant) and isinstance(m.value, str):
        return "literal", m.value
    return "unknown", ""


# 生效条件：src 为单个 .py 源码；解析后累计 counts（就地累加）并把违例追加到 bad（元素为 (rel, lineno, kind, 说明)）；语法错误追加一条 kind="syntax" 的违例而不放行。
def scan_src(rel: str, src: str, counts: dict, bad: list) -> None:
    try:
        tree = ast.parse(src, filename=rel)
    except SyntaxError as e:
        bad.append((rel, 0, "syntax",
                    "语法错误，无法 AST 判定（守卫拒绝在未解析文件上放行）：%s" % e))
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kind = _callee_kind(node)
        if kind is None:
            continue
        kws = {k.arg: k.value for k in node.keywords if k.arg is not None}
        has_star = any(k.arg is None for k in node.keywords)
        has_enc = "encoding" in kws

        if kind == "attr-open":
            # 判据 ①：Attribute 形态一律不计（可能是 os.open/tarfile.open/gzip.open/…，
            # encoding 传进去反而非法）。只计入对照面计数，永不判违例。
            counts["attr_open"] += 1
            continue

        if kind == "attr-text-rw":
            counts["attr_text_rw"] += 1
            if not has_enc:
                bad.append((rel, node.lineno, "attr-text-rw",
                            "%s(...) 未声明 encoding=" % node.func.attr))
            continue

        mkind, mode = _mode_of(node)
        if mkind == "literal" and "b" in mode:
            counts["bin_open"] += 1
            continue                                  # 判据 ②：二进制模式不计
        counts["text_open"] += 1
        if mkind != "literal":
            counts["mode_unknown_open"] += 1          # 判据 ③：口径不可判定，计入
        if not has_enc:
            detail = 'open(..., %r)' % mode if mkind == "literal" else (
                "open(...) mode 未写字面量" if mkind == "missing" else
                "open(...) mode 非字面量/不可判定")
            if has_star:
                detail += "（另有 **kwargs 透传，口径不可确认）"
            bad.append((rel, node.lineno, "builtin-open", detail + " 未声明 encoding="))


# 生效条件：base 为仓根；扫描 list_py(base) 全部文件，返回 (bad, counts, files)；文件读取失败（OSError）跳过且不计入 files。
def scan(base: str) -> tuple[list, dict, int]:
    counts = {"text_open": 0, "bin_open": 0, "mode_unknown_open": 0,
              "attr_open": 0, "attr_text_rw": 0}
    bad: list = []
    files = 0
    for rel, ap in list_py(base):
        try:
            with open(ap, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except OSError:
            continue
        files += 1
        scan_src(rel, src, counts, bad)
    counts["files"] = files
    return bad, counts, files


# 生效条件：src 为单个 .py 源码；返回该文件内全部 Attribute 形态 `.open` 被调者的点分名集合（如 {"tarfile.open","io.open"}）——对照点位锚用；语法错误返回空集。
def attr_open_callees(src: str) -> set:
    out: set = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "open"):
            out.add(ast.unparse(node.func))
    return out


# 生效条件：counts 为 _FLOORS 同名键的计数字典；任一计数低于下限即抛 AnchorMiss（附实测值）。
def check_floors(counts: dict) -> None:
    miss = ["%s=%d < 下限 %d" % (k, counts.get(k, 0), v)
            for k, v in _FLOORS.items() if counts.get(k, 0) < v]
    if miss:
        raise AnchorMiss("扫描面锚点塌陷（文件枚举/判据坏了）：" + "；".join(miss))


# 生效条件：无入参；跑 _ANCHOR_CORPUS 全部片段，返回每个片段的 (名字, 预期, 实测)；不做断言。
def corpus_results() -> list[tuple[str, int, int]]:
    out = []
    for name, src, want in _ANCHOR_CORPUS:
        counts = {"text_open": 0, "bin_open": 0, "mode_unknown_open": 0,
                  "attr_open": 0, "attr_text_rw": 0}
        bad: list = []
        scan_src("<corpus>/%s.py" % name, src, counts, bad)
        out.append((name, want, len(bad)))
    return out


# 生效条件：src 为单文件源码、injected 为一行探针语句；返回 (注入后的源码, 该语句的**精确行号**)——行号按拼接后的行列表算出，故与源文件内容漂移无关。
def _inject(src: str, injected: str) -> tuple[str, int]:
    lines = src.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    lines += ["", "# ---- open/encoding 守卫定点变异探针（自证用，非仓库源码）----",
              "def _open_encoding_guard_probe(p):", injected]
    return "\n".join(lines) + "\n", len(lines)


# 生效条件：tmp 为目标目录；把真实扫描面（SCAN_DIRS 下全部 .py）逐文件物化进 tmp，返回物化文件数——保持扫描面下限锚在变异面上同样成立。
def _materialize_surface(tmp: str) -> int:
    n = 0
    for rel, ap in list_py(ROOT):
        dst = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(ap, dst)
        n += 1
    return n


_MUTATION_PROBES = (
    ("裸文本 open 一处", _MUTATION_PROBE_BARE, 1),
    ("二进制 open 一处", _MUTATION_PROBE_BIN, 0),
    ("Attribute io.open 一处", _MUTATION_PROBE_ATTR, 0),
    ("带 encoding 的 open 一处", _MUTATION_PROBE_OK, 0),
)


# 生效条件：无入参；跑三类自证（判据锚 / 扫描面锚 / 定点变异 + 假阳性对照），返回 (失败清单, 报告行清单)；失败清单非空即 ANCHOR-MISS。
def self_test() -> tuple[list[str], list[str]]:
    miss: list[str] = []
    rep: list[str] = []

    # ---- 判据锚 ----
    for name, want, got in corpus_results():
        if want != got:
            miss.append("判据锚 %s：预期违例 %d，实测 %d" % (name, want, got))
    rep.append("判据锚：%d/%d 片段预期成立" % (len(_ANCHOR_CORPUS) - len(miss),
                                          len(_ANCHOR_CORPUS)))

    # ---- 扫描面锚 + 真实仓对照 ----
    bad, counts, files = scan(ROOT)
    try:
        check_floors(counts)
    except AnchorMiss as e:
        miss.append(str(e))
    rep.append("扫描面：%d 文件 / 文本 open %d（其中 mode 不可判定 %d）/ 二进制 open %d"
               " / Attribute .open %d / read_text-write_text %d"
               % (counts["files"], counts["text_open"], counts["mode_unknown_open"],
                  counts["bin_open"], counts["attr_open"], counts["attr_text_rw"]))
    rep.append("真实仓现有裸文本 open 违例：%d（期望 0，即基线为空）" % len(bad))

    # ---- Attribute 形态对照点位（5 处真实假阳性）----
    for rel in _ATTR_CONTROL_FILES:
        ap = os.path.join(ROOT, rel)
        if not os.path.isfile(ap):
            miss.append("对照点位文件消失：%s" % rel)
            continue
        c2 = {"text_open": 0, "bin_open": 0, "mode_unknown_open": 0,
              "attr_open": 0, "attr_text_rw": 0}
        b2: list = []
        with open(ap, encoding="utf-8", errors="replace") as fh:
            scan_src(rel, fh.read(), c2, b2)
        if c2["attr_open"] < 1:
            miss.append("对照点位 %s 已无 Attribute .open（对照面漂移）" % rel)
        for r, ln, kind, d in b2:
            if kind == "attr-open":
                miss.append("Attribute 形态被误判为违例：%s:%d %s" % (r, ln, d))
    rep.append("Attribute 对照点位：%d 个文件全部核对（Attribute .open 不计违例）"
               % len(_ATTR_CONTROL_FILES))

    # ---- 契约点名 5 个假阳性**点位**（文件 + 被调者名）必须仍在位 ----
    pts_ok = 0
    for rel, marker in _ATTR_CONTROL_POINTS:
        ap = os.path.join(ROOT, rel)
        if not os.path.isfile(ap):
            miss.append("契约点名对照点位文件消失：%s" % rel)
            continue
        with open(ap, encoding="utf-8", errors="replace") as fh:
            callees = attr_open_callees(fh.read())
        if marker in callees:
            pts_ok += 1
        else:
            miss.append("对照点位漂移：%s 已无 Attribute `%s`（实测该文件 Attribute .open 被调者 %s）"
                        % (rel, marker, sorted(callees) or "（无）"))
    rep.append("契约点名 Attribute 假阳性点位：%d/%d 逐个仍在位（点位级锚）"
               % (pts_ok, len(_ATTR_CONTROL_POINTS)))

    # ---- 定点变异自证 ----
    # 「裸文本必红」用**完整扫描面**（临时面物化，保留下限锚真实性）证明：全域命中数**恰好**等于
    # 预期项数且行号精确；其余变体（须绿）只需单文件判据即可证伪误报，用 scan_src 直判以免重复全扫。
    with tempfile.TemporaryDirectory(prefix="open_guard_mut_") as tmp:
        cloned = _materialize_surface(tmp)
        for target in _MUTATION_TARGETS:
            src_abs = os.path.join(ROOT, target)
            if not os.path.isfile(src_abs):
                raise AnchorMiss("定点变异目标不存在：%s" % target)
            with open(src_abs, encoding="utf-8", errors="replace") as fh:
                orig = fh.read()
            dst = os.path.join(tmp, target)
            for label, injected, want in _MUTATION_PROBES:
                new_src, expect_line = _inject(orig, injected)
                if want == 1 and target == _MUTATION_TARGETS[0]:
                    # 「全域恰好 1 项」在**完整扫描面**上证明一次（证明其余文件均为 0）——
                    # 同一判据函数不会只对某些文件成立，其余目标只需同判据单文件判定。
                    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(new_src)
                    b3 = scan(tmp)[0]
                    got = [x for x in b3 if x[0].replace("\\", "/") == target]
                    if len(got) != 1 or len(b3) != 1:
                        miss.append("定点变异 %s × %s：预期全域恰好 1 项，实测 %d 项"
                                    "（本文件 %d）%s" % (target, label, len(b3), len(got), got))
                        continue
                    _rel, ln, kind, _d = got[0]
                    if ln != expect_line:
                        miss.append("定点变异 %s × %s：命中行号 %d ≠ 注入行号 %d"
                                    % (target, label, ln, expect_line))
                    if kind != "builtin-open":
                        miss.append("定点变异 %s × %s：命中类别 %s ≠ builtin-open"
                                    % (target, label, kind))
                else:
                    c3 = {"text_open": 0, "bin_open": 0, "mode_unknown_open": 0,
                          "attr_open": 0, "attr_text_rw": 0}
                    b3 = []
                    scan_src(target, new_src, c3, b3)
                    if len(b3) != want:
                        miss.append("定点变异 %s × %s：预期 %d 项，实测 %d 项 %s"
                                    % (target, label, want, len(b3), b3))
                    elif want == 1 and b3[0][1] != expect_line:
                        miss.append("定点变异 %s × %s：命中行号 %d ≠ 注入行号 %d"
                                    % (target, label, b3[0][1], expect_line))
            shutil.copyfile(src_abs, dst)          # 还原，供下一目标使用
    rep.append("定点变异：临时面物化 %d 文件；%d 目标 × %d 变体"
               "（裸文本必红且全域恰好 1 项 / 二进制·Attribute·带 encoding 必绿）"
               % (cloned, len(_MUTATION_TARGETS), len(_MUTATION_PROBES)))
    return miss, rep


# 生效条件：无入参；跑全仓扫描并按白名单双向核对，返回退出码（0 全绿 / 1 有违例或白名单不吻合 / 2 ANCHOR-MISS）。
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="文本模式 open 的显式 encoding 守卫")
    ap.add_argument("--self-test", action="store_true",
                    help="锚点自证 + 定点变异自证（不扫全仓）")
    args = ap.parse_args(argv)

    if args.self_test:
        try:
            miss, rep = self_test()
        except AnchorMiss as e:
            print("ANCHOR-MISS：%s" % e)
            return 2
        for line in rep:
            print("· " + line)
        if miss:
            print("✖ ANCHOR-MISS %d 项（判据/扫描面/对照点位已漂移，不得视为通过）：" % len(miss))
            for m in miss:
                print("   ", m)
            return 2
        print("✔ 自证通过：判据锚成立、扫描面锚成立、定点变异恰好命中预期项数")
        return 0

    try:
        bad, counts, files = scan(ROOT)
        check_floors(counts)
    except AnchorMiss as e:
        print("ANCHOR-MISS：%s" % e)
        return 2

    print("扫描面：%d 文件 / 文本 open %d / 二进制 open %d / Attribute .open %d"
          % (files, counts["text_open"], counts["bin_open"], counts["attr_open"]))

    hit_files = {r for r, _ln, _k, _d in bad}
    stale = sorted(set(WHITELIST) - hit_files)
    fresh = sorted(hit_files - set(WHITELIST))
    if WHITELIST or stale or fresh:
        print("白名单双向核对：清单 %d 项 / 有而未命中 %d / 命中而不在清单 %d"
              % (len(WHITELIST), len(stale), len(fresh)))
        for s in stale:
            print("   白名单有而未命中（陈化豁免，须删除或修码）：", s)
        for f in fresh:
            print("   命中而不在白名单（不得静默豁免）：", f)

    if bad:
        print("✖ 文本模式未声明 encoding 的调用点 %d 处：" % len(bad))
        for rel, ln, kind, d in sorted(bad):
            print("    %s:%d  [%s] %s" % (rel, ln, kind, d))
        print('修法：补 encoding="utf-8"（二进制模式不要传 encoding）')
        return 1
    if stale or fresh:
        return 1
    print("✔ 全部文本模式调用点均显式声明 encoding=（不依赖 locale）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
