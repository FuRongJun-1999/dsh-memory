#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""# 功能名：npm 发布件发版门禁 check_publish_artifact

# 生效条件：本地模式需 npm 与 git 可用，且 --root 指向仓库根；
   registry 模式需网络可达 registry.npmjs.org。
# 子功能：R1 凭据/密钥面；R2 私有数据面；R3 隐私文本；R4 非追踪件面；
   --registry 增加 tarball sha1/sha512/fileCount 一致性核验。
# 执行：python scripts/check_publish_artifact.py [--root <仓库根>] [--registry <版本>] [--max-examples N] [--selftest]
# 验证方式：本地 npm pack --dry-run --json 生成发布清单，扫描工作区文本；
   registry 下载 tarball 并核对 sha1/sha512/fileCount。
# 不适用条件：无 npm/git 的纯补丁校验；非 npm 包仓库；需验签而非内容面时。

判据: R1 文件名/内容 token；R2 白箱 KB/实验区/缓存；R3 本机/沙箱路径；
R4 包内非追踪件仅允许 lib/；R5 清单条目不得越出 --root；R6 清单来源须为
npm 自身产出（N216：生命周期脚本 stdout 不得冒充发布清单）。
用法: 本地模式 python scripts/check_publish_artifact.py --root <repo_root>；
registry 后置核验 python scripts/check_publish_artifact.py --registry <version>。
不适用条件: 非 npm 发布物；工作区缺少 npm 或 git；无法访问 registry.npmjs.org。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "lingshu-publish-verify/1.0", "Accept": "application/json"}
REG = "https://registry.npmjs.org/"

TEXT_EXTS = {
    ".ts", ".js", ".mjs", ".md", ".json", ".yml", ".yaml", ".py",
    ".txt", ".example", ".sh", ".bat", ".html", ".ps1", ".toml", ".cfg", ".ini",
}
TEXT_SIZE_LIMIT = 3 * 1024 * 1024
ALLOW_NONTRACKED = ("lib/",)
BATCH_MAX = 400

R1_FILE_RULES = [
    (r"(^|/)\.env$", "环境变量密文 .env"),
    (r"(^|/)\.env\.", "环境变量密文 .env.*"),
    (r"(^|/)\.npmrc$", "npm 凭据 .npmrc"),
    (r"(^|/)\.netrc$", "网络凭据 .netrc"),
    (r"(^|/)id_rsa", "SSH 私钥"),
    (r"\.pem$", "PEM 密钥/证书"),
    (r"\.key$", "私钥文件 .key"),
    (r"\.p12$", "PKCS#12 密钥库"),
    (r"(^|/)config\.local\.json$", "本地配置 config.local.json"),
    (r"(^|/)_keys(\.[^/]*)?\.json$", "密钥清单 _keys*.json"),
    (r"(^|/)_audit\.jsonl$", "审计日志 _audit.jsonl"),
    (r"_audit\.jsonl$", "审计日志 _audit.jsonl"),
    (r"(^|/)_access\.log$", "访问日志 _access.log"),
    (r"(^|/)_index\.json$", "索引 _index.json"),
    (r"_index\.json\.lock$", "索引锁 _index.json.lock"),
    (r"(^|/)_refindex\.json$", "引用索引 _refindex.json"),
    (r"(_index_log/)", "索引日志目录 _index_log"),
]
R1_FILE_REGEXES = [(re.compile(pat), reason) for pat, reason in R1_FILE_RULES]

R1_CONTENT_RULES = [
    ("TOKEN_SK", re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    ("TOKEN_GH", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("TOKEN_NPM", re.compile(r"npm_[A-Za-z0-9]{36}")),
    ("TOKEN_MDCG", re.compile(r"mdcg1\.[A-Za-z0-9._\-]{20,}")),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("APIKEY_LITERAL",
     re.compile(r"(?i)\b(api[_-]?key|access[_-]?key|secret|password)\b\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']")),
]



#: 占位符/假值标记（收窄口径，2026-09-20 实测取证）：文档与测试里刻意编写的示例令牌
#: （如 `mdcg1.designer.tk_xxxxxxxxxxxx.xxxxxxxx`、`tk_zzzzzz.bad-secret`）会被 TOKEN_* 正则
#: 命中，但它们是占位符而非真凭据——判 FAIL 会让门禁恒红（红着等于没门禁）。判据：命中
#: 片段（小写）含下列任一标记 → 记为 NOTE（显式列出，不计 FAIL）。真形态仍判 FAIL。
FAKE_TOKEN_MARKERS = ("xxxx", "zzzz", "bad-secret", "badsecret", "dummy", "placeholder",
                     "example", "redacted", "your-token", "fake")


def _looks_placeholder(snippet: str) -> bool:
    """命中片段是否像占位符/假值（而非真凭据）。"""
    low = snippet.lower()
    if any(mk in low for mk in FAKE_TOKEN_MARKERS):
        return True
    body = low.split(".")
    # 连续 6 位以上同一字符（tk_aaaaaa / xxxxxx）亦视为占位符
    return any(len(seg) >= 6 and len(set(seg)) == 1 for seg in body)
def _r3_sep_class() -> str:
    # 防守卫扫到自己：运行时拼接路径正则里的斜杠/反斜杠字符类。
    backslash = chr(92)
    return "[" + backslash + backslash + "/" + "]"


def _build_r3_rules():
    sep = _r3_sep_class()
    user = "Fu" + "RongJun"
    short = "FU" + "RONG~1"
    return [
        ("LOCAL_PATH_PROGRAM",
         re.compile("[A-Za-z]:" + sep + "Program" + " Files" + sep + "2_ai", re.IGNORECASE)),
        ("LOCAL_PATH_USER",
         re.compile("C:" + sep + "Users" + sep + "(" + user + "|" + short + ")", re.IGNORECASE)),
        ("REMOTE_SANDBOX",
         re.compile(chr(47) + "root" + chr(47) + "lingshu-test")),
    ]


R3_RULES = _build_r3_rules()


class CheckReport:
    def __init__(self, max_examples: int):
        self.max_examples = max_examples
        self.failed = False
        self.total_fails = 0

    def note(self, lines):
        """显式列出降级为 NOTE 的命中（占位符示例）——不静默丢弃。"""
        for item in lines[: self.max_examples]:
            print("  [NOTE] %s" % item)

    def rule(self, name: str, passed: bool, hits, detail: str = ""):
        if passed:
            print("  [PASS] %s%s" % (name, detail))
            return
        self.failed = True
        self.total_fails += 1
        print("  [FAIL] %s 命中=%d%s" % (name, len(hits), detail))
        for item in hits[: self.max_examples]:
            print("         - %s" % item)


def normalized_rel(path: str) -> str:
    p = path.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    if p.startswith("package/"):
        p = p[len("package/"):]
    return p.strip("/")


def unsafe_rel_reason(rel: str):
    """清单条目的**越根**判据：越出 --root 即返回原因，安全返回 None。

    N216（2026-09-28）：「发布清单」由 `run_npm_pack_dry_run` 的 stdout 解析而来，
    条目未经判据即被 `os.path.join(root, *rel.split("/"))` 拼接读取——诱饵清单列
    `../<根外可读文件>` 时，R1/R3 共用的 `read_local_text_if_needed` 会读出 --root
    之外的文件并把命中片段回显到 CI 日志（任意可读文件读取 + 内容外泄）。
    npm 自身产出的清单恒为包内相对路径；出现 `..` / 绝对路径 / 盘符即非 npm 清单。
    """
    p = (rel or "").replace("\\", "/").strip()
    if not p:
        return "空路径"
    if p.startswith("//"):
        return "UNC 路径"
    if p.startswith("/"):
        return "绝对路径"
    if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
        return "盘符路径"
    if any(seg == ".." for seg in p.split("/")):
        return "含 '..' 段（越出 --root）"
    return None


def _within_root(root: str, fp: str) -> bool:
    """真实路径包含判定（**越根读的最后一道闸**，与清单判据互为兜底）。

    用 realpath 解析后再比较（符号链接/junction/`..` 段都归一），根自身算包含。
    """
    try:
        r = os.path.realpath(root)
        t = os.path.realpath(fp)
    except OSError:
        return False
    return t == r or t.startswith(r + os.sep)


def is_text_path(rel: str) -> bool:
    return os.path.splitext(rel)[1].lower() in TEXT_EXTS


def _has_prefix(p: str, prefix: str) -> bool:
    prefix = prefix.rstrip("/")
    return p == prefix or p.startswith(prefix + "/")


def r2_reason(rel: str):
    p = normalized_rel(rel)
    if _has_prefix(p, "md_cg/whitebox_kb"):
        if p.endswith((".db", ".db-shm", ".db-wal", ".npz")):
            return "白箱 KB 运行时数据库/嵌入"
        if p == "md_cg/whitebox_kb/knowledge/_ccg_dump.json":
            return "白箱 KB 知识导出 _ccg_dump.json"
        if p == "md_cg/whitebox_kb/knowledge/_index.json":
            return "白箱 KB 索引 _index.json"
        if _has_prefix(p, "md_cg/whitebox_kb/data"):
            return "白箱 KB 本地数据 data/"
        if _has_prefix(p, "md_cg/whitebox_kb/wisdom/audit_log"):
            return "白箱 KB 审计日志 audit_log/"
        if p == "md_cg/whitebox_kb/wisdom/neural_index.json":
            return "白箱 KB 神经索引 neural_index.json"
    if _has_prefix(p, "docs/experiments"):
        return "实验工作区 docs/experiments/"
    if _has_prefix(p, "md_cg/knowledge/orphan"):
        return "本地记忆孤节点 orphan/"
    if "/__pycache__/" in ("/" + p + "/"):
        return "Python 缓存目录 __pycache__/"
    if p.endswith(".pyc") or p.endswith(".pyo"):
        return "Python 字节码"
    return None


def scan_r1_file_hits(paths):
    hits = []
    for rel in paths:
        for rx, reason in R1_FILE_REGEXES:
            if rx.search(rel):
                hits.append("%s（%s）" % (rel, reason))
                break
    return hits


def scan_r2_hits(paths):
    hits = []
    for rel in paths:
        reason = r2_reason(rel)
        if reason:
            hits.append("%s（%s）" % (rel, reason))
    return hits


def scan_text_hits(text: str, rules, rel: str):
    """→ (fail_hits, notes)。令牌类规则的命中若为占位符/假值标记则降级为 note，不静默丢弃。

    每规则遍历**全部**命中（finditer，N167 修）：TOKEN_* 规则任一命中为真
    形态即判 FAIL 并停止该规则扫描——修前只取 rx.search 首配、首配占位符即
    continue 跳过该规则余下文本，同文件「占位符令牌在前、真实凭据在后」时
    真令牌整条逃逸 R1 内容面（门禁静默漏报）。全部命中均为占位符才降级
    NOTE。规则判 FAIL 后不再收集其占位符命中（FAIL 已覆盖告警，note 仅是
    占位符展示面）；非 TOKEN_* 规则无降级语义，任一命中即 FAIL（与修前等价）。
    """
    hits = []
    notes = []
    for label, rx in rules:
        for m in rx.finditer(text):
            snippet = m.group(0).replace("\r", "\\r").replace("\n", "\\n")
            if len(snippet) > 80:
                snippet = snippet[:80] + "..."
            line = "文本命中 %s：%s 片段=%s" % (rel, label, snippet)
            if not (label.startswith("TOKEN_")
                    and _looks_placeholder(snippet)):
                hits.append(line)
                break                        # 该规则已坐实，不再扫描
            notes.append(line)               # 占位符命中：显式列出（NOTE）
    return hits, notes


def base_env():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    return env


def read_local_text_if_needed(root: str, rel: str):
    ext = os.path.splitext(rel)[1].lower()
    if ext not in TEXT_EXTS:
        return None
    if unsafe_rel_reason(rel):
        return None                      # 越根条目一律不读（N216；R5 已记账判负）
    fp = os.path.join(root, *rel.split("/"))
    if not _within_root(root, fp):
        return None                      # 兜底：清单判据之外的第二道越根闸
    try:
        st = os.stat(fp)
    except OSError:
        return None
    if st.st_size > TEXT_SIZE_LIMIT:
        return None
    try:
        with open(fp, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return data.decode("utf-8", "replace")


def parse_package_json(root: str):
    fp = os.path.join(root, "package.json")
    if not os.path.isfile(fp):
        print("  [环境错误] 未找到 package.json：%s" % fp)
        return None
    try:
        with open(fp, encoding="utf-8") as f:
            pj = json.load(f)
    except Exception as exc:  # noqa: BLE001
        print("  [环境错误] package.json 解析失败：%s: %s" % (type(exc).__name__, exc))
        return None
    # N217：合法 JSON 但顶层非对象（被写坏成 `[1,2,3]` / `"x"` / `null`）时，
    # 旧实现把任意 JSON 值原样返回，调用方 `pj.get(...)` 抛 AttributeError 逃出
    # main——退出码落到与本脚本自陈契约相反的一侧（读不通=2 实得 1）。
    if not isinstance(pj, dict):
        print("  [环境错误] package.json 顶层须为对象（实得 %s）——拒绝解析"
              % type(pj).__name__)
        return None
    return pj


def _is_pack_manifest_shape(val) -> bool:
    """npm pack --json 的**基本清单形态**：数组（元素为含 files 列表的对象）或单对象。"""
    if isinstance(val, list):
        return bool(val) and all(
            isinstance(it, dict) and isinstance(it.get("files"), list) for it in val)
    if isinstance(val, dict):
        return isinstance(val.get("files"), list)
    return False


def _is_full_pack_manifest_shape(val) -> bool:
    """npm pack --json 的**全形态**：每项 files 逐条含 path(str)/size(int)/mode(int)。

    npm 实产清单恒带 size/mode（2026-09-28 实测：本仓 1438 件逐条齐备），而
    「生命周期脚本冒充清单」的最小诱饵通常只写 `{path}`——全形态优先即用于在
    **多段候选**中挑出 npm 自身产出（N216）。
    """
    if not isinstance(val, list) or not val:
        return False
    for it in val:
        if not isinstance(it, dict):
            return False
        files = it.get("files")
        if not isinstance(files, list) or not files:
            return False
        for f in files:
            if not (isinstance(f, dict) and isinstance(f.get("path"), str)
                    and isinstance(f.get("size"), int)
                    and isinstance(f.get("mode"), int)):
                return False
    return True


def extract_pack_manifest(stdout: str):
    """从 npm pack 的混杂 stdout 中取**真清单** → (manifest, meta)；取不到 → (None, meta)。

    N216（2026-09-28，high）：npm 先跑生命周期脚本（prepack/prepare/postpack），其
    stdout 排在 npm 自身清单**之前**；旧实现（`extract_first_json_value`）取「首个
    可解析 JSON 值」，于是 `package.json` 的 `prepare` 只要打印一行
    `[{"files":[{"path":"a.js"}]}]` 即可把门禁的扫描面整体换成伪造清单——R1 凭据 /
    R2 私有数据 / R3 隐私文本 / R4 非追踪件四档只扫诱饵，真发布件里的凭据文件不再
    被检查，门禁照样 VERDICT=PASS / exit 0（发版链路整体失守，且改 package.json 的
    PR 即触发 CI：`.github/workflows/publish-artifact-check.yml:14/30`）。

    契约（三层，任一不成立即 fail-closed 交调用方判负）：
      · 候选枚举：对整个 stdout 逐段 `raw_decode` 全部可解析 JSON 值，不复用
        「首个」语义（旧实现只认首个，正是被冒充的入口）；
      · 形态优先：优先**全形态**候选（files 逐条含 path/size/mode），其次基本形态；
      · 位置取末：同为全形态候选时取**最后一段**——npm 自身清单恒在生命周期脚本
        stdout 之后（2026-09-28 实测：prepare 与 postpack 的输出均在其前）。

    meta 回报候选数与选中位置，由调用方显式记账/告警（不静默）。
    """
    decoder = json.JSONDecoder()
    found = []
    i, n = 0, len(stdout)
    while i < n:
        if stdout[i] in "[{":
            try:
                val, end = decoder.raw_decode(stdout, i)
            except ValueError:
                i += 1
                continue
            found.append((i, end, val))
            i = max(end, i + 1)
        else:
            i += 1
    manifest_candidates = [c for c in found if _is_pack_manifest_shape(c[2])]
    full = [c for c in manifest_candidates if _is_full_pack_manifest_shape(c[2])]
    picked = full[-1] if full else (manifest_candidates[-1]
                                    if manifest_candidates else None)
    meta = {"json_candidates": len(found),
            "manifest_candidates": len(manifest_candidates),
            "shape_rank": None, "picked_offset": None}
    if picked is None:
        return None, meta
    meta["shape_rank"] = "full" if full else "shape"
    meta["picked_offset"] = picked[0]
    return picked[2], meta


def _npm_pack_json(root: str, extra_args=()):
    """执行一次 `npm pack --dry-run --json [extra]` → stdout / None（环境错误）。"""
    npm = "npm.cmd" if os.name == "nt" else "npm"
    argv = [npm, "pack", "--dry-run", "--json"] + list(extra_args)
    print("  执行：%s" % " ".join(argv))
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=base_env(),
            cwd=root,
            shell=False,
            timeout=600,
        )
    except OSError as exc:
        print("  [环境错误] 无法执行 npm：%s" % exc)
        return None
    except subprocess.TimeoutExpired:
        print("  [环境错误] npm pack --dry-run 超时")
        return None
    if proc.returncode != 0:
        stderr = (proc.stderr or "")[:1500]
        print("  [环境错误] npm pack --dry-run 失败 rc=%s\n%s" % (proc.returncode, stderr))
        return None
    return proc.stdout or ""


def _manifest_paths(manifest):
    """清单 → (安全条目列表, 越根条目列表)。越根条目**不**进入扫描面。"""
    entries = manifest if isinstance(manifest, list) else [manifest]
    paths, unsafe = [], []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for item in (entry.get("files") or []):
            if isinstance(item, dict):
                raw = item.get("path")
            else:
                raw = item
            if not isinstance(raw, str) or not raw:
                continue
            reason = unsafe_rel_reason(raw)
            if reason:
                unsafe.append("清单条目越出 --root：%r（%s）" % (raw[:120], reason))
                continue
            paths.append(normalized_rel(raw))
    return sorted(set(paths)), unsafe


def run_npm_pack_dry_run(root: str):
    """→ {'paths','unsafe','trust','json_candidates','manifest_candidates'}；环境错误 → None。

    发布清单**只认 npm 自身产出**：表达式解析后还要过两道独立判据，任一不成立即
    记 trust 命中（门禁判负，不再「魔改清单照样绿」）：
      1. 形态：必须识别到 npm 自身的**全形态**清单（见 extract_pack_manifest）；
      2. 交叉核验：`--ignore-scripts` 的清单（无生命周期 stdout 污染，且脚本只能
         **增**件）必须是所选清单的子集——诱饵为骗过 R1/R4 必然**漏列**真发布件
         （例如 .env），漏列即被本判据坐实；脚本删件的异常形态同样落网。
    """
    stdout = _npm_pack_json(root)
    if stdout is None:
        return None
    manifest, meta = extract_pack_manifest(stdout)
    if manifest is None:
        print("  [环境错误] npm pack --dry-run JSON 解析失败：未找到发布清单形态的 JSON 值")
        print(stdout[:1500])
        return None

    paths, unsafe = _manifest_paths(manifest)
    trust = []
    if meta["manifest_candidates"] > 1:
        trust.append(
            "stdout 含 %d 段清单形态 JSON（json 候选共 %d 段）——生命周期脚本"
            "（prepare/prepack/postpack）向 stdout 打印了清单，疑似冒充发布清单；"
            "已取 npm 自身产出（%s 形态·偏移 %d）"
            % (meta["manifest_candidates"], meta["json_candidates"],
               meta["shape_rank"], meta["picked_offset"]))
    if meta["shape_rank"] != "full":
        trust.append(
            "未识别到 npm 自身产出的**全形态**清单（files 逐条含 path/size/mode）"
            "——候选 %d 段、基本形态 %d 段，无法证明清单来自 npm（fail-closed）"
            % (meta["json_candidates"], meta["manifest_candidates"]))

    # 交叉核验：--ignore-scripts 清单 ⊆ 所选清单（脚本只能增件；诱饵必然漏列）
    base_stdout = _npm_pack_json(root, ("--ignore-scripts",))
    if base_stdout is None:
        print("  [环境错误] 无法取得 --ignore-scripts 基线清单（清单可信性无法核验）")
        return None
    base_manifest, _base_meta = extract_pack_manifest(base_stdout)
    if base_manifest is None:
        print("  [环境错误] --ignore-scripts 基线清单解析失败（清单可信性无法核验）")
        return None
    base_paths, _base_unsafe = _manifest_paths(base_manifest)
    missing = sorted(set(base_paths) - set(paths))
    if missing:
        trust.append(
            "清单漏列 %d 件（--ignore-scripts 基线含而所选清单无，例：%s）——"
            "脚本只能增件，漏列即清单不可信（疑似 stdout 冒充发布清单）"
            % (len(missing), "、".join(missing[:5])))

    if not paths:
        print("  [环境错误] npm pack --dry-run 未返回任何文件")
        return None
    return {"paths": paths, "unsafe": unsafe, "trust": trust,
            "json_candidates": meta["json_candidates"],
            "manifest_candidates": meta["manifest_candidates"]}


def git_ls_files(root: str):
    env = base_env()
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=root,
            shell=False,
            timeout=120,
        )
    except OSError:
        return None
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    tracked = set()
    for token in (proc.stdout or "").split("\0"):
        if token:
            tracked.add(normalized_rel(token))
    return tracked


def allowed_nontracked(rel: str) -> bool:
    for prefix in ALLOW_NONTRACKED:
        if rel == prefix.rstrip("/") or rel.startswith(prefix):
            return True
    return False


def http_get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def local_mode(root: str, report: CheckReport) -> int:
    print("=== 本地模式 ===")
    pj = parse_package_json(root)
    if pj is None:
        return 2

    pkg_name = pj.get("name") or "未知包名"
    pkg_version = pj.get("version") or "未知版本"
    manifest = run_npm_pack_dry_run(root)
    if manifest is None:
        return 2
    paths = manifest["paths"]
    print("  发布清单：%s@%s，文件数=%d" % (pkg_name, pkg_version, len(paths)))

    r1_file_hits = scan_r1_file_hits(paths)
    r1_content_hits = []
    r3_hits = []
    notes = []
    for rel in paths:
        text = read_local_text_if_needed(root, rel)
        if text is None:
            continue
        _h, _n = scan_text_hits(text, R1_CONTENT_RULES, rel)
        r1_content_hits.extend(_h)
        notes.extend(_n)
        _h3, _n3 = scan_text_hits(text, R3_RULES, rel)
        r3_hits.extend(_h3)
        notes.extend(_n3)
    if notes:
        report.note(notes)

    r1_hits = r1_file_hits + r1_content_hits
    r1_detail = "；文件面=%d 内容面=%d" % (len(r1_file_hits), len(r1_content_hits))
    report.rule("R1 凭据/密钥面", not r1_hits, r1_hits, detail=r1_detail)

    r2_hits = scan_r2_hits(paths)
    report.rule("R2 私有数据面", not r2_hits, r2_hits)

    report.rule("R3 隐私文本", not r3_hits, r3_hits)

    tracked = git_ls_files(root)
    if tracked is None:
        print("  [环境错误] 无法执行 git ls-files -z，R4 不能核验")
        return 2
    pkg_set = set(paths)
    untracked = sorted(pkg_set - tracked)
    bad = [p for p in untracked if not allowed_nontracked(p)]
    allowed_count = len(untracked) - len(bad)
    r4_detail = "；非追踪=%d，允许=%d" % (len(untracked), allowed_count)
    report.rule("R4 非追踪件面", not bad, bad, detail=r4_detail)

    # N216：清单来源与路径两条独立判据——四档内容规则只扫「清单里的件」，
    # 清单本身被冒充/越根时四档全绿也不代表发布件干净（发版门禁的最后一道）。
    report.rule(
        "R5 清单路径安全",
        not manifest["unsafe"],
        manifest["unsafe"],
        detail="；条目越出 --root 即拒（`..` / 绝对 / 盘符 / UNC）")
    report.rule(
        "R6 清单来源可信",
        not manifest["trust"],
        manifest["trust"],
        detail="；json 候选=%d 清单候选=%d"
               % (manifest["json_candidates"], manifest["manifest_candidates"]))
    return 0


def registry_mode(root: str, version: str, report: CheckReport) -> int:
    print("=== registry 模式 ===")
    pj = parse_package_json(root)
    if pj is None:
        return 2
    pkg_name = pj.get("name")
    if not pkg_name:
        print("  [环境错误] package.json 缺少 name 字段")
        return 2

    q = urllib.parse.quote(pkg_name, safe="")
    base_url = REG + q
    version_url = base_url + "/" + urllib.parse.quote(version, safe="")

    try:
        pack = http_get_json(base_url)
    except Exception as exc:  # noqa: BLE001
        print("  [环境错误] 获取 packument 失败：%s: %s" % (type(exc).__name__, exc))
        return 2
    # N217：私有镜像/被劫持 registry 返回顶层非对象 packument（`[]` / `"x"` / `0`）
    # 时，旧实现直接 `.get` 抛 AttributeError 逃出 main——把「读不通」伪装成
    # 「语义判负」（契约 2 实得 1）。
    if not isinstance(pack, dict):
        print("  [环境错误] packument 顶层须为对象（实得 %s）——拒绝解析"
              % type(pack).__name__)
        return 2
    pub_time = (pack.get("time") or {}).get(version, "未记录")
    print("  package=%s version=%s 发布时间=%s" % (pkg_name, version, pub_time))

    try:
        vdoc = http_get_json(version_url)
    except Exception as exc:  # noqa: BLE001
        print("  [环境错误] 获取版本端点失败：%s: %s" % (type(exc).__name__, exc))
        return 2
    if not isinstance(vdoc, dict):
        print("  [环境错误] 版本端点顶层须为对象（实得 %s）——拒绝解析"
              % type(vdoc).__name__)
        return 2

    dist = vdoc.get("dist") or {}
    tarball_url = dist.get("tarball")
    if not tarball_url:
        print("  [环境错误] dist.tarball 缺失，无法下载")
        return 2
    print("  tarball=%s" % tarball_url)

    try:
        blob = http_get_bytes(tarball_url)
    except Exception as exc:  # noqa: BLE001
        print("  [环境错误] tarball 下载失败：%s: %s" % (type(exc).__name__, exc))
        return 2
    print("  字节数=%d" % len(blob))

    sha1 = hashlib.sha1(blob).hexdigest()
    sha512_b64 = base64.b64encode(hashlib.sha512(blob).digest()).decode("ascii")
    local_integrity = "sha512-" + sha512_b64
    remote_integrity = dist.get("integrity") or ""
    remote_sha1 = dist.get("shasum") or ""
    remote_file_count = dist.get("fileCount")

    consistency_hits = []
    if not remote_sha1:
        consistency_hits.append("registry 未提供 shasum")
    elif sha1 != remote_sha1:
        consistency_hits.append("sha1 不一致：本地=%s registry=%s" % (sha1, remote_sha1))
    if not remote_integrity:
        consistency_hits.append("registry 未提供 integrity")
    elif local_integrity != remote_integrity:
        left = local_integrity[:48] + "..."
        right = remote_integrity[:48] + "..."
        consistency_hits.append("sha512/integrity 不一致：本地=%s registry=%s" % (left, right))

    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            members = [m for m in tf.getmembers() if m.isfile()]
            rel_files = []
            unsafe_members = []
            texts = {}
            for m in members:
                reason = unsafe_rel_reason(m.name)
                if reason:
                    # 远端 tarball 带 `..` / 绝对路径条目（tar 路径穿越形态）：
                    # 不进扫描面、不读内容，只记账（N216 同族：清单条目不得越根）
                    unsafe_members.append("tarball 条目越根：%r（%s）"
                                          % (m.name[:120], reason))
                    continue
                rel = normalized_rel(m.name)
                rel_files.append(rel)
                if is_text_path(rel) and (m.size or 0) <= TEXT_SIZE_LIMIT:
                    f = tf.extractfile(m)
                    if f:
                        data = f.read()
                        texts[rel] = data.decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        print("  [环境错误] tarball 解包失败：%s: %s" % (type(exc).__name__, exc))
        return 2

    local_file_count = len(members)
    if remote_file_count is None:
        consistency_hits.append("registry 未提供 fileCount")
    elif local_file_count != remote_file_count:
        consistency_hits.append(
            "文件数不一致：本地=%d registry=%s" % (local_file_count, remote_file_count)
        )
    print("  文件数=%d（registry fileCount=%s）" % (local_file_count, remote_file_count))

    report.rule(
        "R0 发布件一致性",
        not consistency_hits,
        consistency_hits,
        detail="；sha1=%s sha512=%s" % (sha1, local_integrity[:48] + "..."),
    )

    r1_file_hits = scan_r1_file_hits(rel_files)
    r1_content_hits = []
    r3_hits = []
    notes = []
    for rel in rel_files:
        text = texts.get(rel)
        if text is None:
            continue
        _h, _n = scan_text_hits(text, R1_CONTENT_RULES, rel)
        r1_content_hits.extend(_h)
        notes.extend(_n)
        _h3, _n3 = scan_text_hits(text, R3_RULES, rel)
        r3_hits.extend(_h3)
        notes.extend(_n3)
    if notes:
        report.note(notes)

    r1_hits = r1_file_hits + r1_content_hits
    r1_detail = "；文件面=%d 内容面=%d" % (len(r1_file_hits), len(r1_content_hits))
    report.rule("R1 凭据/密钥面", not r1_hits, r1_hits, detail=r1_detail)

    r2_hits = scan_r2_hits(rel_files)
    report.rule("R2 私有数据面", not r2_hits, r2_hits)

    report.rule("R3 隐私文本", not r3_hits, r3_hits)

    print("  [SKIP] R4 非追踪件面：--registry 模式跳过（工作区未必对应该版本提交）")
    report.rule(
        "R5 清单路径安全",
        not unsafe_members,
        unsafe_members,
        detail="；tarball 条目越出包根即拒（`..` / 绝对 / 盘符 / UNC）")
    return 0


def default_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))


def selftest() -> bool:
    print("== 自检 ==")
    ok = True

    def check(cond: bool, label: str, detail=""):
        nonlocal ok
        print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label,
                               ("  " + str(detail)[:200]) if (detail and not cond) else ""))
        if not cond:
            ok = False

    def r1_file_match(p: str) -> bool:
        for rx, _ in R1_FILE_REGEXES:
            if rx.search(p):
                return True
        return False

    check(r1_file_match(".env"), "R1 文件名 .env")
    check(r1_file_match("foo/.env.local"), "R1 文件名 .env.local")
    check(not r1_file_match("env"), "R1 文件名 env 不命中")
    check(r1_file_match("config.local.json"), "R1 文件名 config.local.json")
    check(r1_file_match("md_cg/whitebox_kb/_index_log/x"), "R1 文件名 _index_log/")

    api_literal = "api_key = \"1234567890123456\""
    api_env_name = "api_key=ENV_NAME"
    api_rules = [rx for label, rx in R1_CONTENT_RULES if label == "APIKEY_LITERAL"]
    check(any(rx.search(api_literal) for rx in api_rules), "R1 内容 APIKEY 字面量命中")
    check(all(rx.search(api_env_name) is None for rx in api_rules), "R1 内容 APIKEY 环境变量名不命中")

    check(r2_reason("md_cg/whitebox_kb/wisdom/wisdom-book-cloud.db") is not None, "R2 白箱 DB")
    check(r2_reason("docs/experiments/a.json") is not None, "R2 实验区")
    check(r2_reason("md_cg/knowledge/orphan/x.md") is not None, "R2 孤节点")
    check(r2_reason("src/__pycache__/x.py") is not None, "R2 __pycache__")
    check(r2_reason("src/x.pyc") is not None, "R2 pyc")
    check(r2_reason("docs/experiments2/x.json") is None, "R2 前缀相似不命中")

    drive = "D:" + chr(92) + "Program" + " Files" + chr(92) + "2_ai" + chr(92) + "x.txt"
    user = "C:" + chr(92) + "Users" + chr(92) + "Fu" + "RongJun" + chr(92) + "x.txt"
    remote = chr(47) + "root" + chr(47) + "lingshu-test" + chr(47) + "x.txt"
    check(any(rx.search(drive) for _, rx in R3_RULES), "R3 命中程序目录路径")
    check(any(rx.search(user) for _, rx in R3_RULES), "R3 命中用户目录路径")
    check(any(rx.search(remote) for _, rx in R3_RULES), "R3 命中沙箱路径")

    fake = "mdcg1.designer.tk_" + "x" * 12 + ".xxxxxxxx"
    fake2 = "mdcg1.designer.tk_zzzzzz.bad-secret"
    real = "mdcg1.designer.tk_9f3aK2mQ8vLpR4sT1uWz7yB6nH0cX5dE.a1B2c3D4e5F6h7J8k9"
    check(_looks_placeholder(fake), "占位符令牌识别（tk_xxxx…）")
    check(_looks_placeholder(fake2), "占位符令牌识别（tk_zzzzzz.bad-secret）")
    check(not _looks_placeholder(real), "真形态令牌不误判为占位符")
    f_h, f_n = scan_text_hits(fake, R1_CONTENT_RULES, "x.md")
    check(not f_h and len(f_n) == 1, "占位符令牌降级为 NOTE（不计 FAIL）")
    r_h, _ = scan_text_hits(real, R1_CONTENT_RULES, "x.md")
    check(len(r_h) == 1, "真形态令牌仍判 FAIL")

    # N167：每规则遍历全部命中——同文件占位符令牌在前不得掩盖其后的真凭据
    mixed = fake + "\n中间正文\n真凭据 " + real + "\n"
    m_h, m_n = scan_text_hits(mixed, R1_CONTENT_RULES, "x.md")
    check(len(m_h) == 1, "N167 占位符在前+真凭据在后 → 真令牌仍判 FAIL")
    check(len(m_n) == 1, "N167 占位符命中仍显式 NOTE（不静默丢弃）")

    polluted = ("[prepare] 跳过构建：typescript 未安装（NODE_ENV=production）\n"
                "[\n  {\"id\": \"x@1.0.0\", \"files\": [{\"path\": \"a.js\", \"size\": 3, \"mode\": 420}]}\n]\n")
    parsed, meta = extract_pack_manifest(polluted)
    check(isinstance(parsed, list) and bool(parsed) and parsed[0]["files"][0]["path"] == "a.js",
          "健壮解析：prepare 文本污染 stdout 时仍能提取清单")
    check(meta["shape_rank"] == "full" and meta["manifest_candidates"] == 1,
          "健壮解析：纯文本污染不产生额外清单候选（不误报冒充）")
    clean = "[\n  {\"id\": \"b@1.0.0\", \"files\": [{\"path\": \"b.js\", \"size\": 1, \"mode\": 420}]}\n]"
    c_parsed, c_meta = extract_pack_manifest(clean)
    check(c_parsed is not None and c_parsed[0]["files"][0]["path"] == "b.js",
          "健壮解析：纯净 stdout")
    check(extract_pack_manifest("no json here")[0] is None, "健壮解析：无 JSON 时返回 None")
    obj_polluted = "[prepare] 跳过构建\n{\"files\": [{\"path\": \"c.js\"}]}\n"
    o_parsed, o_meta = extract_pack_manifest(obj_polluted)
    check(isinstance(o_parsed, dict) and bool(o_parsed.get("files")),
          "健壮解析：纯对象型 stdout 亦可提取（v15-8：候选起点含 {）")
    check(o_meta["shape_rank"] == "shape",
          "健壮解析：仅基本形态（无 path/size/mode）→ 记 shape 档（交 R6 判负）")

    # N216 负例（本轮新补，修前缺失故缺陷长期在位）：prepare 先打印 **清单形态** JSON
    # 诱饵（只列已追踪件以骗过 R4），npm 自身真清单在后——解析必须取真清单。
    decoy = '[{"files":[{"path":"a.js"}]}]'
    real_entry = ('{\n  "id": "p@1.0.0",\n  "name": "p",\n  "version": "1.0.0",\n'
                  '  "filename": "p-1.0.0.tgz",\n  "files": [\n'
                  '    {"path": ".env", "size": 37, "mode": 420},\n'
                  '    {"path": "a.js", "size": 5, "mode": 420}\n'
                  '  ],\n  "entryCount": 2\n}\n')
    real_stdout = decoy + "\n" + "[\n" + real_entry + "]\n"
    got, gmeta = extract_pack_manifest(real_stdout)
    got_paths, got_unsafe = _manifest_paths(got)
    check(got_paths == [".env", "a.js"],
          "N216 负例：prepare 清单诱饵在前 → 仍取 npm 真清单（含 .env）", got_paths)
    check(not got_unsafe, "N216 负例：真清单无越根条目")
    check(gmeta["manifest_candidates"] == 2 and gmeta["shape_rank"] == "full",
          "N216：诱饵被计为清单候选（R6 据此判负，不静默）", gmeta)

    # N216 越根判据：清单条目不得越出 --root
    check(unsafe_rel_reason("../x") is not None, "越根判据：'..' 段为不安全")
    check(unsafe_rel_reason("..\\x") is not None, "越根判据：反斜杠形态亦归一判不安全")
    check(unsafe_rel_reason("a/../../b.js") is not None, "越根判据：中段 '..' 为不安全")
    check(unsafe_rel_reason("/etc/passwd") is not None, "越根判据：绝对路径为不安全")
    check(unsafe_rel_reason("C:/Windows/x.txt") is not None, "越根判据：盘符路径为不安全")
    check(unsafe_rel_reason("src/a.js") is None, "越根判据：包内相对路径放行")
    esc_paths, esc_unsafe = _manifest_paths(
        [{"files": [{"path": "../outside.md", "size": 1, "mode": 420},
                    {"path": "a.js", "size": 1, "mode": 420}]}])
    check(esc_paths == ["a.js"] and len(esc_unsafe) == 1,
          "N216：越根条目不进扫描面且记账", (esc_paths, esc_unsafe))

    source_text = Path(__file__).read_text(encoding="utf-8")
    for label, rx in R3_RULES:
        check(rx.search(source_text) is None, "R3 不命中自身源码：%s" % label)

    return ok


def parse_args(argv):
    parser = argparse.ArgumentParser(description="npm 发布件发版门禁")
    parser.add_argument("--root", default=None, help="仓库根目录，默认由脚本位置推导")
    parser.add_argument("--registry", metavar="VERSION", default=None, help="切 registry 后置核验模式")
    parser.add_argument("--max-examples", type=int, default=5, help="每个 FAIL 规则最多打印的示例数")
    parser.add_argument("--selftest", action="store_true", help="执行内置断言自检")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.selftest:
        return 0 if selftest() else 1
    if args.max_examples < 0:
        print("[环境错误] --max-examples 不能为负")
        return 2

    root = os.path.abspath(args.root or default_root())
    if not os.path.isdir(root):
        print("[环境错误] 仓库根目录不存在：%s" % root)
        return 2

    print("=== 0) 对象 ===")
    print("  root=%s registry=%s max_examples=%d" % (root, args.registry or "本地", args.max_examples))

    report = CheckReport(args.max_examples)
    if args.registry:
        mode_code = registry_mode(root, args.registry, report)
    else:
        mode_code = local_mode(root, report)
    if mode_code != 0:
        return mode_code

    print("=== 结论 ===")
    print("  FAIL 规则数=%d" % report.total_fails)
    print("VERDICT=%s" % ("FAIL" if report.failed else "PASS"))
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
