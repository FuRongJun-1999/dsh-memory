# -*- coding: utf-8 -*-
"""check_referenced_paths —— 「点名的件在不在」扫描判据

背景（2026-10-25，S3 定档批的 E134/C42/E87/E17 一族）：仓库里有一类反复出现的病灶——
**注释、判据、清单、架构表点名了某个文件，而那个文件不存在**。它不会被任何测试发现：
文件不存在不报错，调用点不存在不报错，只有人肉读的时候才「怎么找不到」。已知实例：

  · `scripts/arch-check.py:72` 的注释写「`gate-tree-hygiene.mjs` 负责把它变成显式红」，
    该文件在四处候选目录里都不存在（真正的 tmp 门叫 `gate-tmp-hygiene.mjs`）；
  · `md_cg/semantic/__init__.py` 的模块清单列了 `build_en_index.py`，该目录里没有它；
  · 备份入口在两仓都缺：`lingshu-src` 与 `assistant-gateway` 底下都没有那个 backup 脚本。

判据（一句话）：**代码/判据/清单正文里以仓库相对路径形态点名的文件必须存在**——
扫出来的引用逐条判存在性，任一不存在即退出码 2 并点名 `文件:行号 → 被点名路径`。

反假过纪律（A7 原状那类错的教训）：
  · 扫描面为 0（一条引用都没扫到）**不算通过**，退 2——「没看」与「没发现问题」不同形；
  · 只认带目录分隔符、扩展名在白名单内的形态（裸模块名 / URL / 通配 / 占位符一律不算引用），
    避免把散文里的示例与占位符算成缺件；
  · 允许多个 `--base`，候选路径在任一 base 下存在即算存在（多仓工作区）；
  · 默认还要求**首段是 base 下真实存在的顶层名字**（`scripts/`、`md_cg/` …）——把跨仓引用与
    散文示例挡在外面，扫出来的缺件才是「本仓点了名、本仓没有」；要关掉用 `--allow-any-prefix`；
  · 缺件可用 `--ignore` 前缀豁免（每行一条，`#` 起注释），豁免项单独计数并打印——
    豁免是记账，不是静默。

退出码：0＝扫到的引用全部存在；2＝有缺件，或扫描面为 0（判不了也退 2，不 PASS）；1＝参数错。

用法：
    python scripts/check_referenced_paths.py --base . --base ..
    python scripts/check_referenced_paths.py --base D:\\wook --ext .py .mjs --json
"""
import argparse
import json
import os
import re
import sys

# 只有这些扩展名算「点名了一个文件」；其余（.txt 里的散文、数据库产物名）不判。
DEFAULT_EXTS = (".py", ".mjs", ".js", ".cjs", ".json", ".yml", ".yaml", ".sh", ".ps1", ".bat")

# 扫描的源文件扩展名（被扫的载体）：代码 + 判据 + 清单。散文 .md 默认不扫（示例太多）。
DEFAULT_SOURCES = (".py", ".mjs", ".js", ".cjs", ".json", ".yml", ".yaml")

# 裸文件名（不带目录分隔符）也算「点名了件」的扩展名：这几个在散文里几乎不会出现。
# 裸 .py / .json 不在此列 —— 那是模块名与产物名，认了就是满屏假红。
DEFAULT_BARE_EXTS = (".mjs", ".cjs", ".sh", ".ps1", ".bat")

SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", ".venv-test", "venv",
             "dist", "build", "target", ".pytest_cache", ".mypy_cache", "site-packages"}

# 候选形态：至少一个标识符段（可带目录层级）+ 白名单扩展名。前后不允许紧贴标识符字符/斜杠。
# 目录层级用 `*` 而不是 `+`：`gate-tree-hygiene.mjs` 这种裸文件名也要能被 `looks_like_path`
# 拿到再判（裸名只在 DEFAULT_BARE_EXTS 里才算引用）。
_TOKEN_RE = re.compile(r"(?<![\w./\\\-$])([A-Za-z0-9_][\w.\-]*(?:/[A-Za-z0-9_][\w.\-]*)*)")
_BAD_CHARS = set("<>*{}[]$%?|:\"'`#!,;=+&^~")


# 生效条件：token 含分隔符且末段扩展名在 exts 内、且不含 URL 协议/通配/占位符字符时返回 True（算「点名了一个文件」），否则 False。
def looks_like_path(token, exts, bare_exts=()):
    """判定一个 token 是不是「点名了一个文件」（不算 URL / 通配 / 占位符 / 变量）。"""
    if "://" in token or token.startswith("//"):
        return False
    if "/" not in token:
        # 裸文件名：只有「散文里几乎不会出现」的扩展名才算引用（.mjs/.sh/.ps1 …）。
        # 裸 .py/.json 太容易是模块名与产物名，不认——否则满屏假红，门就没人看了。
        return os.path.splitext(token)[1].lower() in bare_exts
    if any(ch in _BAD_CHARS for ch in token):
        return False
    if token.startswith("../") or token.startswith("./"):
        return False
    segs = token.split("/")
    if any(seg in ("", ".", "..") for seg in segs):
        return False
    if token.endswith(".") or ".." in token:
        return False
    # 全大写段＝占位符/变量（ROOT / HOME / SRC …），不是真路径
    if any(seg.isupper() and len(seg) > 1 for seg in segs):
        return False
    ext = os.path.splitext(token)[1].lower()
    return ext in exts


# 生效条件：token 的首段在任一 base 下 isfile/isdir 为真时返回 True（首段是仓内真名字），否则 False。
def prefix_exists(token, bases):
    """首段是否是仓内真实存在的顶层名字——用来把「跨仓/散文示例」与「本仓缺件」分开。"""
    head = token.split("/")[0]
    for base in bases:
        if os.path.exists(os.path.join(base, head)):
            return True
    return False


# 生效条件：token 在任一 base 下 isfile 为真时返回命中的绝对路径，全部不存在返回 ""；带分隔符的 token 走路径拼接，裸文件名走名字索引（names 为 None 时返回 ""）。
def resolve(token, bases, names=None):
    """→ 命中的绝对路径；都没命中返回 ""。"""
    if "/" not in token:
        return (names or {}).get(token, "")
    for base in bases:
        fp = os.path.normpath(os.path.join(base, token.replace("/", os.sep)))
        if os.path.isfile(fp):
            return fp
    return ""


# 生效条件：对 bases 下 max_depth 层内的文件名建一张 {名字: 绝对路径} 索引（裸文件名判定用）；目录不存在时该根不贡献。
def build_name_index(bases, max_depth=2):
    """→ {文件名: 绝对路径}，只走 base 下 max_depth 层（裸文件名判定用）。

    不做全盘 walk：`D:\\wook` 有二十多万个文件，全盘扫一遍就把门变成负担。
    """
    idx = {}
    for base in bases:
        root_depth = base.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(base):
            if dirpath.count(os.sep) - root_depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                idx.setdefault(name, os.path.join(dirpath, name))
    return idx


# 生效条件：path 为文件且扩展名在 sources 内时返回逐行文本，否则返回 None（目录/非载体/读不开）。
def iter_source_files(root, sources):
    """→ (相对根的文件路径, 行号, 行文本) 的生成器；跳过 SKIP_DIRS。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if os.path.splitext(name)[1].lower() not in sources:
                continue
            fp = os.path.join(dirpath, name)
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        yield fp, lineno, line
            except OSError:
                continue


# 生效条件：argv 为 None 时由 argparse 读 sys.argv[1:]；解析出的 base 列表用于存在性判定，扫描这几个 base 下 sources 里的候选路径，按 ignore 前缀豁免，打印缺件清单与计数，返回 0（无缺件且扫描面非空）/2（有缺件或扫描面为 0）/1（参数错）。
def main(argv=None):
    ap = argparse.ArgumentParser(description="点名的件在不在：仓库内相对路径引用 → 存在性判据")
    ap.add_argument("--base", action="append", default=None,
                    help="存在性判定用的根（可重复；缺省为当前目录）")
    ap.add_argument("--scan", action="append", default=None,
                    help="扫描哪些根（可重复；缺省与 --base 相同）")
    ap.add_argument("--ext", nargs="+", default=list(DEFAULT_EXTS),
                    help="算作「点名文件」的扩展名（缺省 %s）" % " ".join(DEFAULT_EXTS))
    ap.add_argument("--sources", nargs="+", default=list(DEFAULT_SOURCES),
                    help="扫描哪类载体文件（缺省 %s）" % " ".join(DEFAULT_SOURCES))
    ap.add_argument("--ignore", default="",
                    help="豁免文件：每行一个路径前缀，# 起注释")
    ap.add_argument("--bare-ext", nargs="+", default=list(DEFAULT_BARE_EXTS),
                    help="裸文件名也算引用的扩展名（缺省 %s；裸 .py/.json 不算，太容易是模块名）"
                         % " ".join(DEFAULT_BARE_EXTS))
    ap.add_argument("--allow-any-prefix", action="store_true",
                    help="不要求首段是仓内真名字（默认要求：把跨仓/散文示例与本仓缺件分开）")
    ap.add_argument("--max-report", type=int, default=80)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    bases = [os.path.abspath(b) for b in (args.base or ["."])]
    scans = [os.path.abspath(s) for s in (args.scan or args.base or ["."])]
    for p in bases + scans:
        if not os.path.isdir(p):
            print("参数错：--base/--scan 不是目录：%s" % p, file=sys.stderr)
            return 1

    ignores = []
    if args.ignore:
        try:
            with open(args.ignore, "r", encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip()
                    if s and not s.startswith("#"):
                        ignores.append(s.replace("\\", "/"))
        except OSError as exc:
            print("参数错：--ignore 读不开：%s" % exc, file=sys.stderr)
            return 1

    exts = tuple(e.lower() if e.startswith(".") else "." + e.lower() for e in args.ext)
    sources = tuple(e.lower() if e.startswith(".") else "." + e.lower() for e in args.sources)
    bare_exts = tuple(e.lower() if e.startswith(".") else "." + e.lower()
                      for e in args.bare_ext)
    names = build_name_index(bases) if bare_exts else {}

    seen = {}          # token → 首见位置
    n_refs = 0
    for root in scans:
        for fp, lineno, line in iter_source_files(root, sources):
            for m in _TOKEN_RE.finditer(line):
                token = m.group(1)
                if not looks_like_path(token, exts, bare_exts):
                    continue
                if "/" in token and not args.allow_any_prefix and not prefix_exists(token, bases):
                    continue
                n_refs += 1
                if token in seen:
                    continue
                hit = resolve(token, bases, names)
                seen[token] = (fp, lineno, bool(hit))

    missing = [(tok, fp, ln) for tok, (fp, ln, ok) in sorted(seen.items()) if not ok]
    waived = [(tok, fp, ln) for tok, fp, ln in missing
              if any(tok.startswith(ig) for ig in ignores)]
    missing = [x for x in missing if x not in waived]

    rel = lambda p: os.path.relpath(p, os.getcwd()).replace("\\", "/")
    if args.json:
        print(json.dumps({"refs": n_refs, "unique": len(seen),
                          "missing": [{"path": t, "at": "%s:%d" % (rel(f), l)}
                                      for t, f, l in missing],
                          "waived": len(waived)}, ensure_ascii=False, indent=1))
        return 2 if (missing or not seen) else 0

    print("[ref-paths] 载体扫描 %d 个根 · 引用 %d 处 · 去重 %d 个路径 · 豁免 %d"
          % (len(scans), n_refs, len(seen), len(waived)))
    for tok, fp, ln in missing[:args.max_report]:
        print("  [MISSING] %s:%d → %s" % (rel(fp), ln, tok))
    if len(missing) > args.max_report:
        print("  … 另 %d 条未打印（--max-report 调大）" % (len(missing) - args.max_report))
    if not seen:
        print("[ref-paths→2] 扫描面为 0：一条引用都没扫到 —— 没看，不等于没有缺件",
              file=sys.stderr)
        return 2
    if missing:
        print("[ref-paths→2] %d 个被点名的路径不存在（点名＝承诺，缺件要修或进 --ignore）"
              % len(missing), file=sys.stderr)
        return 2
    print("[ref-paths→0] 全部存在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
