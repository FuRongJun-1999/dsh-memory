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
R4 包内非追踪件仅允许 lib/。
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
    """→ (fail_hits, notes)。令牌类规则的命中若为占位符/假值标记则降级为 note，不静默丢弃。"""
    hits = []
    notes = []
    for label, rx in rules:
        m = rx.search(text)
        if not m:
            continue
        snippet = m.group(0).replace("\r", "\\r").replace("\n", "\\n")
        if len(snippet) > 80:
            snippet = snippet[:80] + "..."
        line = "文本命中 %s：%s 片段=%s" % (rel, label, snippet)
        if label.startswith("TOKEN_") and _looks_placeholder(snippet):
            notes.append(line)
            continue
        hits.append(line)
    return hits, notes


def base_env():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    return env


def read_local_text_if_needed(root: str, rel: str):
    ext = os.path.splitext(rel)[1].lower()
    if ext not in TEXT_EXTS:
        return None
    fp = os.path.join(root, *rel.split("/"))
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
            return json.load(f)
    except Exception as exc:  # noqa: BLE001
        print("  [环境错误] package.json 解析失败：%s: %s" % (type(exc).__name__, exc))
        return None


def run_npm_pack_dry_run(root: str):
    npm = "npm.cmd" if os.name == "nt" else "npm"
    print("  执行：%s pack --dry-run --json" % npm)
    try:
        proc = subprocess.run(
            [npm, "pack", "--dry-run", "--json"],
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

    stdout = proc.stdout or ""
    try:
        start = stdout.find("[")
        last = stdout.rfind("]")
        if start < 0 or last < 0:
            raise ValueError("未找到 JSON 数组")
        data = json.loads(stdout[start:last + 1])
    except Exception as exc:  # noqa: BLE001
        print("  [环境错误] npm pack --dry-run JSON 解析失败：%s" % exc)
        print((proc.stdout or "")[:1500])
        return None

    data0 = data[0] if isinstance(data, list) and data else data
    raw_files = data0.get("files") or []
    paths = []
    for item in raw_files:
        if isinstance(item, dict):
            path = item.get("path")
        else:
            path = str(item)
        if path:
            paths.append(normalized_rel(path))
    paths = sorted(set(paths))
    if not paths:
        print("  [环境错误] npm pack --dry-run 未返回任何文件")
        return None
    return paths


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
    paths = run_npm_pack_dry_run(root)
    if paths is None:
        return 2
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
    pub_time = (pack.get("time") or {}).get(version, "未记录")
    print("  package=%s version=%s 发布时间=%s" % (pkg_name, version, pub_time))

    try:
        vdoc = http_get_json(version_url)
    except Exception as exc:  # noqa: BLE001
        print("  [环境错误] 获取版本端点失败：%s: %s" % (type(exc).__name__, exc))
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
            texts = {}
            for m in members:
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
    return 0


def default_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))


def selftest() -> bool:
    print("== 自检 ==")
    ok = True

    def check(cond: bool, label: str):
        nonlocal ok
        print("  [%s] %s" % ("PASS" if cond else "FAIL", label))
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
