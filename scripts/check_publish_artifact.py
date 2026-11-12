#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""# 功能名：npm 发布件发版门禁 check_publish_artifact

# 生效条件：本地模式需 npm 与 git 可用，且 --root 指向仓库根；
   registry 模式需网络可达 registry.npmjs.org。
# 子功能：R1 凭据/密钥面；R2 私有数据面；R3 隐私文本；R4 非追踪件面；
   R5 清单路径安全；R6 清单来源可信；R7 扫描面完整性（清单内文本件不得「未扫」而不报）；
   R8 声明面产物在位；R9a/R9b 运行时必需件与同名分叉；
   R10a/R10b 随包文档里**可执行形态**点名的脚本必须可达（不随包须登记）；
   --registry 增加 tarball sha1/sha512/fileCount 一致性核验。
# 执行：python scripts/check_publish_artifact.py [--root <仓库根>] [--registry <版本>] [--max-examples N] [--selftest]
# 验证方式：本地 npm pack --dry-run --json 生成发布清单，扫描工作区文本；
   registry 下载 tarball 并核对 sha1/sha512/fileCount。
# 不适用条件：无 npm/git 的纯补丁校验；非 npm 包仓库；需验签而非内容面时。

判据: R1 文件名/内容 token；R2 白箱 KB/实验区/缓存；R3 本机/沙箱路径；
R4 包内非追踪件仅允许 lib/；R5 清单条目不得越出 --root；R6 清单来源须为
npm 自身产出（N216：生命周期脚本 stdout 不得冒充发布清单）；R7 清单内文本件
须真被扫描过——读不到 / 超 TEXT_SIZE_LIMIT 即判负（N251：「未扫」不得等价于
「已扫且干净」）；R8 `exports`/`files` 声明的产物必须真在包里；R9a 被随包模块
按路径装载的件必须随包，**但装载方自己就不随包时整链不发布 ⇒ 只记 NOTE 不判负**
（装机侧根本到不了那段代码，判负等于要求「把源码树工具也发货」）；R9b 同一判据不得
分叉两个落点（未登记即判负）；
R10a 随包文档里可执行形态点名的脚本必须在某个基址下真实存在；R10b 该脚本若不随包
须登记（维护者工具），否则判负。
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
import tempfile
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
#: R4 的**允许面**（前缀白名单）：包内允许出现哪些「非追踪件」。
#:
#: 判据＝「该文件能否由**仓库内的脚本/源**确定性复现」。当前两类构建产物：
#:   · `lib/`                     —— `tsc` 编译产物（lib/index.js 等）
#:   · `web/` · `build-ui.mjs`    —— `scripts/build_ui.py` 从 `ui/minimal/payload/` 铺出的
#:                                  UI 产物（0.9.15 起接线入库，产物仍不入库——见 .gitignore）
#:   · `src/lib/`                 —— 同上脚本铺出的 `console_web.mjs` 源侧副本
#:     （`src/index.ts` 的 `import ... from './lib/console_web.mjs'` 需要它在盘上才能编译）
#:
#: 2026-10-27 补：此前只有 `lib/`，UI 产物一入 files 就有 6 件落进 bad（R4 红）。
#: 注意「允许=32」那类数字是**实测量**（len(untracked)-len(bad)），不是可调阈值；
#: 本元组才是唯一的政策常量。
ALLOW_NONTRACKED = ("lib/", "web/", "build-ui.mjs", "src/lib/")
BATCH_MAX = 400

#: R9b 的**登记豁免面**：源码树薄壳/薄垫片——设计上就是「包内是单点、源码树留薄壳」。
#:
#: 判据不是「有同名就红」，而是「**未登记的分叉**才红」。理由：
#: `scripts/review_cli.py` / `scripts/judgment_manifest.py` / `scripts/state_extract.py`
#: 三件都是**薄壳**（只 re-export 或只转发 main，实现在 `md_cg/`），源码树保留它们
#: 是为了既有路径不断。只要「薄壳不含第二份实现」，它不发货**不是缺陷**。
#:
#: 但 `state_extract.py` 本轮暴露了真问题：**薄壳本身被运行时按路径装载**
#: （`sync_zcode_session._load_state_extract()` 直接 open `scripts/state_extract.py`），
#: 于是「包内已有本体」也救不了装机侧——装载点找的是薄壳，薄壳不发货就断。
#: 故登记项必须写成「为什么它作为薄壳**不会被运行时装载**」；被装载的不能登记。
#:
#: 登记格式：{"文件名": {"why": "为何安全（一行）",
#:                     "requires_not_shipped": "该安全性所依赖的装载方（须不随包）"}}
#:
#: **带前提的登记**（2026-11-02 升级，本轮教训）：登记不是说「永远没问题」，
#: 而是「在某个可检验的前提下没问题」。一旦前提失效（装载方开始随包，
#: 于是装机侧会执行这次装载），登记自动失效 ⇒ 重新判负。
#: 这正是本轮栽过的坑：`sync_zcode_session` 一旦进包，`scripts/state_extract.py`
#: 就立刻从「源码树薄壳」变成「装机必需件」，漏发即断链。
R9B_REGISTERED_SHIMS = {
    "review_cli.py": {
        "why": "薄壳只转发 main；出货包唯一入口是 "
               "`python -m md_cg.review_cli`，无任何模块按路径装载 scripts/ 版",
        "requires_not_shipped": None,          # 无前提：本就不被装载
    },
    "judgment_manifest.py": {
        "why": "薄壳；`md_cg/interop.py` 优先加载源码树版、安装态自动降级到包内版"
               "（已有等价实现 + 降级分支），非断链",
        "requires_not_shipped": None,
    },
    "state_extract.py": {
        "why": "薄垫片（只 re-export md_cg.state_extract）；源码树里由 "
               "scripts/sync_zcode_session.py::_load_state_extract 按路径装载",
        # **前提**：装载方自己不随包 ⇒ 装机侧不执行该装载，故垫片不发货不致断链。
        # 一旦 sync_zcode_session.py 进 files 白名单，下面这条前提失效，登记自动作废。
        "requires_not_shipped": "scripts/sync_zcode_session.py",
    },
    # 2026-11-02：两个**随包运维探针**的薄垫片（与 state_extract 同款处置）。
    # 文档 §七/§十 随包发给使用者，命令原本写 `scripts/probe_c_ledger_integrity.py`，
    # 而 scripts/ 不随包 ⇒ 装机用户照抄即 Errno 2（实测）。本体移进 md_cg/ 后，
    # 源码树垫片只转发。装载方：无按路径装载（纯人工照抄命令行），故无前提。
    "probe_c_ledger_integrity.py": {
        "why": "薄垫片（只 re-export md_cg.probe_c_ledger_integrity）；本体随包，"
               "装机侧入口是 `python -m md_cg.probe_c_ledger_integrity`，"
               "无任何模块按路径装载 scripts/ 版",
        "requires_not_shipped": None,
    },
    "probe_d_retirement_discipline.py": {
        "why": "薄垫片（只 re-export md_cg.probe_d_retirement_discipline）；本体随包，"
               "装机侧入口是 `python -m md_cg.probe_d_retirement_discipline`，"
               "无任何模块按路径装载 scripts/ 版",
        "requires_not_shipped": None,
    },
}

#: N251（2026-10-05，high）：清单内**文本件**却未被扫描的成因——「未扫」不得等价于
#: 「已扫且干净」。修前 `read_local_text_if_needed` 的三处静默 `return None`（stat 失败 /
#: 超 TEXT_SIZE_LIMIT / open 失败）与 registry 侧的成员过滤（`is_text_path(...) and
#: size <= TEXT_SIZE_LIMIT`）都把两者压成同一可观测态：被跳过的子集零 NOTE、零计数，
#: 而 R1 照样打印「内容面=0」、VERDICT=PASS / exit 0。实测两形态：①真形态令牌放进
#: 4,194,443 B 的 `lib/big.txt`（在 npm 全形态清单内、size 字段在场）→ 静默出货，而
#: 同一令牌放进 53 B 的小文件即 R1 FAIL（判据随文件大小翻转，等于没有判据）；②`postpack`
#: 删掉 `lib/gone.txt` 后 npm 清单**仍列**该件而盘上已无 → 同样静默。
#: 处置方向：逐条按成因记账并交 R7 判负（不得靠「读不到就跳过」把扫描面缩小）。
UNSCANNED_UNREADABLE = "清单内文本件读不到（stat/open 失败）"
#: 越根兜底闸命中：清单条目本身是包内相对路径（过了 R5 的 `unsafe_rel_reason`），
#: 但符号链接/junction 归一后真实路径在 --root 之外——不读，同样属「未扫」。
UNSCANNED_ESCAPE = "清单内文本件真实路径越出 --root（符号链接/链接点）"


def unscanned_cause_oversize(size: int) -> str:
    """清单内文本件超 TEXT_SIZE_LIMIT 的成因串（措辞单点，local / registry 共用）。"""
    return "清单内文本件超 TEXT_SIZE_LIMIT（%d B > %d B）" % (size, TEXT_SIZE_LIMIT)


def unscanned_entry(rel: str, cause: str) -> str:
    """未扫条目记账行的**单点**（local / registry 同款，避免两套措辞漂移）。"""
    return "%s（%s）" % (rel, cause)


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
    # ★ 本笔修（R1-b① 左边界）：原为 `sk-[A-Za-z0-9_\-]{20,}`，**无左边界** ⇒ 任何以
    #   `sk-` 结尾的普通标识后面跟 ≥20 位字母数字即被判 FAIL —— 实测 `risk-` + 25 个 `a`
    #   即误报（发版门禁把无关代码判红；而门禁红是"操作者要去修"的信号，误报成本实打实）。
    #   **同仓 PII 族是正确写法**：`hive/exec.py` 的 PII-SK 用了双侧 lookaround
    #   `(?<![0-9A-Za-z])sk-[A-Za-z0-9_-]{16,}(?![0-9A-Za-z])`（详见 md_cg/test_issue419_pii_redaction.py
    #   的跨站点矩阵）⇒ 同一形态在两个站点口径分叉。本笔把 R1 的**左边界**对齐该写法。
    #   右边界与 `{16,}/{20,}` 的差异**本笔不动**（另立议题，避免夹带）。
    ("TOKEN_SK", re.compile(r"(?<![0-9A-Za-z])sk-[A-Za-z0-9_\-]{20,}")),
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


def read_local_text_detail(root: str, rel: str):
    """读清单内文本件 → (text, 未扫成因)。**「未扫」判据的唯一单点**（N251）。

    第二元素非空即表示「清单内本该扫却扫不成」，调用方须逐条记账并交 R7 判负——
    修前三种 `return None`（stat 失败 / 超 TEXT_SIZE_LIMIT / open 失败）与「已扫且干净」
    不可分，被跳过的子集零 NOTE 零计数（见 UNSCANNED_* 的取证注）。
    返回 `(None, None)` 的两处是**按设计不扫**，不是未扫：①非文本扩展名（TEXT_EXTS 之外）——
    二进制内容无 token 面可言；②越根条目（`unsafe_rel_reason` 命中）——R5 已记账判负，
    且本条判据不许读它。
    """
    ext = os.path.splitext(rel)[1].lower()
    if ext not in TEXT_EXTS:
        return None, None
    if unsafe_rel_reason(rel):
        return None, None                # 越根条目一律不读（N216；R5 已记账判负）
    fp = os.path.join(root, *rel.split("/"))
    if not _within_root(root, fp):
        return None, UNSCANNED_ESCAPE    # 兜底：清单判据之外的第二道越根闸
    try:
        st = os.stat(fp)
    except OSError:
        return None, UNSCANNED_UNREADABLE
    if st.st_size > TEXT_SIZE_LIMIT:
        return None, unscanned_cause_oversize(st.st_size)
    try:
        with open(fp, "rb") as f:
            data = f.read()
    except OSError:
        return None, UNSCANNED_UNREADABLE
    return data.decode("utf-8", "replace"), None


def read_local_text_if_needed(root: str, rel: str):
    """(兼容包装) → 文本内容或 None；语义与修前一致，成因面见 read_local_text_detail。"""
    return read_local_text_detail(root, rel)[0]


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
    """npm pack --json 的**基本清单形态**：数组（元素为含 files 列表的对象）、单对象，
    或 npm 12 起的**包名键控对象**（issue #70：{"<包名>": [ {files:[...]}, ... ]}）。"""
    if isinstance(val, list):
        return bool(val) and all(
            isinstance(it, dict) and isinstance(it.get("files"), list) for it in val)
    if isinstance(val, dict):
        if isinstance(val.get("files"), list):
            return True
        return _is_named_pack_object(val)
    return False


def _is_named_pack_object(val) -> bool:
    """npm 12（issue #70）的**包名键控对象**：整个对象无顶层 files 键，
    而每个 value 都是非空的「含 files 列表的对象」数组。"""
    if not isinstance(val, dict) or not val:
        return False
    if isinstance(val.get("files"), list):
        return False
    for v in val.values():
        items = [v] if isinstance(v, dict) else v      # npm 12.0.2 实测：value 是对象
        if not isinstance(items, list) or not items:
            return False
        for it in items:
            if not (isinstance(it, dict) and isinstance(it.get("files"), list)):
                return False
    return True


def _normalize_pack_manifest(val):
    """把包名键控对象摊平为条目数组（issue #70，2026-10-09 DSH 端）。

    修前：npm 12 的 npm pack --json 产出 {"<包名>": [ {...} ]}，形态闸不认 ⇒
    extract_pack_manifest 判无候选 ⇒ check_publish_artifact 恒以环境错误退出（exit=2）。
    归一后下游 _manifest_paths 无需改（它只认 list/单对象）。
    非该形态（含老版数组、老版单对象）原样返回。
    """
    if _is_named_pack_object(val):
        out = []
        for v in val.values():
            if isinstance(v, dict):
                out.append(v)          # npm 12.0.2 实测：value 是单个对象（2026-10-19）
            else:
                out.extend(v)          # 旧形态：value 是对象数组
        return out
    return val


def _is_full_pack_manifest_shape(val) -> bool:
    """npm pack --json 的**全形态**：每项 files 逐条含 path(str)/size(int)/mode(int)。

    npm 实产清单恒带 size/mode（2026-09-28 实测：本仓 1438 件逐条齐备），而
    「生命周期脚本冒充清单」的最小诱饵通常只写 `{path}`——全形态优先即用于在
    **多段候选**中挑出 npm 自身产出（N216）。
    """
    val = _normalize_pack_manifest(val)      # issue #70：先摊平包名键控对象
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
    return _normalize_pack_manifest(picked[2]), meta   # issue #70：包名键控对象在此摊平


# 生效条件：无入参，恒返回一个字符串——Windows 返回 "npm.cmd"（npm 在 Windows 上的可执行入口），其它平台返回 "npm"；不判存在性、不触盘。
def resolve_npm() -> str:
    """npm 可执行入口的**解析单点**（全仓唯一，供本门禁与 check_publish_smoke 共用）。

    为什么必须是单点：Windows 上 `npm` 实际由 `npm.cmd` 承载，直接写 "npm" 会
    落到无扩展名搜索；而 `cmd /c npm ...` 形态在本仓 Bash 里会打印 cmd 横幅且
    **假绿**（rc=0——2026-09-30 实测取证），故命令一律按 argv 列表直呼本函数
    返回的名字。第二个调用方（出货面冒烟腿）必须复用此处，不再写第二套方言
    ——两套方言必然随平台差异漂移。
    """
    return "npm.cmd" if os.name == "nt" else "npm"


def _npm_pack_json(root: str, extra_args=()):
    """执行一次 `npm pack --dry-run --json [extra]` → stdout / None（环境错误）。"""
    argv = [resolve_npm(), "pack", "--dry-run", "--json"] + list(extra_args)
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


#: R9 的扫描面：只认**动态装载调用**里出现的 `.py` 字面量。
#:
#: 为什么不用「文本里出现 scripts/xxx.py」这种粗判：实测两者差一个数量级——
#: 朴扫命中 48 个目标，其中 47 个只是文档/注释里提到（`docs/*.md`、模块 docstring、
#: CHANGELOG），**运行时从不打开**。若把它们都当必需件，闸门会产生数十条误报；
#: 而误报多了，闸门就会被忽略，等于没有闸门（本仓 N251 已有同款教训）。
#: 故判据收紧到「装载动作的第二参数」——这是「真的会去 open 它」的强信号。
_R9_LOAD = re.compile(
    r"spec_from_file_location\s*\(\s*"      # importlib 动态装载
    r"[^,)]*?,\s*"                          # 第一参数（模块名，忽略）
    r".{0,300}?"                            # 路径表达式（可跨行、可含 Path(...)/os.path.join）
    r"[\"']([A-Za-z0-9_]+\.py)[\"']",       # 第二参数里**字面出现**的 .py 文件名
    re.S,
)
_R9_SKIP_DIRS = {"node_modules", ".git", "__pycache__", "lib", "web", ".tmp"}


#: R9 的第二判据面：**同名文件分叉**（split-brain）。
#:
#: 为什么要这条（2026-11-02 实测教训，比装载关系更准）：
#: 本轮真实缺陷的形态是——`state_extract.py` 的**生产方本体**已在 `md_cg/`（随包），
#: 而 `scripts/` 下留的**薄垫片**不随包。这不是「装载关系断了」，而是
#: **同一判据存在于两个落点，一个发货一个不发**。只查装载关系的判据看不见它：
#: 因为装载方 `sync_zcode_session.py` 自己也不发货 ⇒ 整条 fall into「整链不发布」。
#:
#: 判据：同一文件名在仓内出现于多个**随包/不随包**混合位置 ⇒ 分叉风险。
#: 但**不能一律判负**——本仓实测有 33 组同名，其中大量是 `compiler/x.py` 与
#: `md_cg/whitebox_kb/wisdom/core/x.py` 这种**同名不同物**（不同包、不同职责），
#: 以及 `md_cg/test_*.py` 与 `tests/test_*.py` 这种**顶层测试与包内测试并行**。
#: 那两类都不是缺陷。故只判「**同名且互为薄壳/等价实现**」——判据取
#: 「其中一个文件 import 了另一个的同名模块」或「一个是薄垫片（re-export）」。
_R9_SHIM_HINT = re.compile(
    r"(薄垫片|thin\s+shim|薄壳|re-export|原样\s*re-export|包内等价实现)", re.I)


def _split_brain_split(root, pkg_set):
    """R9b：同名 .py 落在「一发货一不发」混合位置，且互为薄壳/等价实现。

    返回缺失清单（元素为说明串）。判定链：
      ① 同名 .py 在仓内 ≥2 处；
      ② 这些位置**混合**（有的随包、有的不随包）；
      ③ 至少一对满足「同一判据」信号：其中一方文件头有薄壳/等价实现措辞，
         或一方 import 了同名模块；
      ④ 测试件不参与（`md_cg/test_*.py` 与 `tests/test_*.py` 是并行套件，非分叉）。
    """
    shipped_files = list(pkg_set)

    def _shipped(rel):
        rel = rel.replace("\\", "/")
        return any(rel == s or rel.startswith(s.rstrip("/") + "/")
                   for s in shipped_files)

    by_name = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _R9_SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/")
            by_name.setdefault(fn, []).append(rel)

    out = []
    for fn, locs in sorted(by_name.items()):
        if len(locs) < 2:
            continue
        if fn.startswith("test_") or fn == "__init__.py" or fn == "__main__.py":
            continue                       # ④ 并行测试套件 / 包标记文件，非分叉
        flags = [_shipped(l) for l in locs]
        if not (any(flags) and not all(flags)):
            continue                       # ② 必须混合
        stem = fn[:-3]
        # ③ 同一判据信号
        signal = []
        for l in locs:
            try:
                with open(os.path.join(root, l), encoding="utf-8") as fh:
                    head = fh.read(2000)
            except (OSError, UnicodeDecodeError):
                continue
            if _R9_SHIM_HINT.search(head):
                signal.append(l)
            elif re.search(r"from\s+[\w.]*\b%s\s+import\b" % re.escape(stem), head):
                signal.append(l)
        if not signal:
            continue                       # 同名不同物：不判
        present = [l for l, f in zip(locs, flags) if f]
        absent = [l for l, f in zip(locs, flags) if not f]
        entry = "%s：随包 %s ｜ 不发货 %s（同一判据两落点，易分叉）" % (
            fn, "/".join(present[:2]), "/".join(absent[:2]))
        if fn in R9B_REGISTERED_SHIMS:
            reg = R9B_REGISTERED_SHIMS[fn]
            why = reg.get("why") or reg
            need = reg.get("requires_not_shipped") if isinstance(reg, dict) else None
            # **带前提的登记**：前提（装载方不随包）必须仍成立，否则登记失效。
            if need and _shipped(need):
                out.append(("unregistered", entry + " ｜ 登记已失效：其前提"
                            "「%s 不随包」不再成立（它进包了 ⇒ 装机侧会执行这次"
                            "装载，薄壳不发货即断链）" % need))
            else:
                extra = ("（前提：%s 不随包，现成立）" % need) if need else ""
                out.append(("registered", entry + " ｜ 已登记：" + why + extra))
        else:
            out.append(("unregistered", entry + " ｜ 未登记，需说明它"
                        "「为何不会被运行时装载」或把它移入随包面"))
    return out


def _runtime_loaded_not_shipped(root, pkg_set):
    """R9 扫描：被随包模块按路径装载、但自身不随包发货的必需件。

    返回 (缺失清单, 装载点数)。缺失清单元素形如
    ``"装载点:行 → 目标文件（仓内位置）"``，供 report.rule 直接判负。

    判据链（缺一不成立，故不误报）：
      ① 装载方本身**在包内**（否则它自己都不发货，谈不上「必需件」）；
      ①b 装载方**不是测试件**——测试件按设计就不随包发货，它们装载只存在于源码树
         （`hive/verify_runner.py`、`scripts/bootstrap_loop.py` 等）在安装态本就不存在，
         那是**测试面的已知边界**，不是发布缺陷。实测：不加这条会误报 4 条（全在
         `md_cg/test_*.py`），闸门一旦误报就会被忽略，等于没有闸门；
      ② 装载动作里**字面**出现 `<X>.py`；
      ③ 仓内**确实存在**同名文件（否则是拼错/可选依赖，不该由本闸判）；
      ④ 该文件的**所有**仓内位置都不在包内 ⇒ 装机侧必然装载失败。
    """
    shipped_files = [p for p in pkg_set]

    def _shipped(rel):
        rel = rel.replace("\\", "/")
        return any(rel == s or rel.startswith(s.rstrip("/") + "/")
                   for s in shipped_files)

    def _is_test(rel):
        base = rel.rsplit("/", 1)[-1]
        return (base.startswith("test_") or base.endswith("_test.py")
                or "/tests/" in rel or "/test/" in rel)

    # 仓内 .py 索引（按文件名）
    by_name = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _R9_SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            by_name.setdefault(fn, []).append(rel)

    misses, scanned, skipped = [], 0, []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _R9_SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            if _is_test(rel):
                continue                      # ①b 测试件：见 docstring 说明
            # ① 判据面＝「**装机侧会执行**的装载关系」。分两类，处置不同：
            #   · 装载方随包  ⇒ 装机侧一定执行这次装载，目标缺件即真断链 ⇒ 判 FAIL。
            #   · 装载方不随包 ⇒ 装机侧没有它，这次装载永不执行；但若其目标是
            #     「本该随包的生产件」，则说明**整条链路都没发布**——这是发布面的
            #     结构问题，不是「必需件缺失」，故记 NOTE 保持可见，不判 FAIL。
            #     （本仓实测：zcode 端 4 处 scripts/ 内部装载全属此类，
            #      根因是 scripts/ 只发 workspace_index.py ⇒ zcode 链路整体不在包里。）
            loader_shipped = _shipped(rel)
            try:
                with open(full, encoding="utf-8") as fh:
                    src = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            for m in _R9_LOAD.finditer(src):
                target = m.group(1)
                scanned += 1                  # ②
                locs = by_name.get(target) or []
                if not locs:
                    continue                  # ③
                if any(_shipped(l) for l in locs):
                    continue                  # ④ 至少一个位置在包内 ⇒ 可达
                line = src.count("\n", 0, m.start()) + 1
                entry = "%s:%d → %s（仓内 %s，均不在包内）" % (
                    rel, line, target, "/".join(locs[:3]))
                if loader_shipped:
                    misses.append(entry)      # 真断链
                else:
                    skipped.append(entry)     # 整链不发布（可见但不判负）
    return misses, scanned, skipped


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
    unscanned = []
    for rel in paths:
        text, cause = read_local_text_detail(root, rel)
        if cause:
            # N251：清单内却未扫——逐条记账，交 R7 判负；绝不再与「已扫且干净」同形。
            unscanned.append(unscanned_entry(rel, cause))
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

    # R8 声明面产物在位（2026-10-27 补，**实证驱动**）：`exports` / `files` 里声明了的产物，
    # 必须真在包里。R1~R7 全是「清单里不该有的东西」这类**负向**判据，缺一条正向判据：
    # 实测事故——`prepare` 钩子会 `rmSync('lib')` 再跑 `tsc`（不含 `build_ui`），而 `npm pack`
    # 会触发 `prepare`，于是 `lib/client.js` 与 `lib/lib/console_web.mjs` 在打包瞬间被删；
    # `files` 里 `lib`/`web` 仍在、R4 只查「非追踪件是否越界」⇒ **全绿**，但发出去的包里
    # `exports["./client"]` 指向不存在的文件（装上后 UI 侧栏直接失效）。本条把它挡住。
    _decl, _decl_note = [], []
    try:
        with open(os.path.join(root, "package.json"), encoding="utf-8") as _pf:
            _pkg = json.load(_pf)
        _cli = ((_pkg.get("exports") or {}).get("./client"))
        if isinstance(_cli, str) and _cli.strip():
            _decl.append(("exports[\"./client\"]", _cli.strip().lstrip("./")))
        _files_decl = _pkg.get("files") or []
        if "lib" in _files_decl:
            _decl.append(("files 含 lib", "lib/index.js"))
        if "web" in _files_decl:
            _decl.append(("files 含 web", "web/index.html"))
        if "ui" in _files_decl:
            _decl.append(("files 含 ui", "ui/minimal/install.ps1"))
    except (OSError, ValueError) as _exc:
        _decl_note.append("[R8] 跳过：package.json 不可读（%s）" % _exc)
    if _decl_note:
        report.note(_decl_note)
    _miss = [("%s → %s" % (k, p)) for k, p in _decl if p not in pkg_set]
    report.rule("R8 声明面产物在位；exports/files 声明的产物必须真在包里",
                not _miss, _miss,
                detail="；声明 %d 项" % len(_decl))

    # R9 运行时必需件在位（2026-11-02 补，**实测事故驱动**）：
    # R8 只查 `exports`/`files` **声明面**的产物；但有一类必需件从不被声明——
    # 运行时**按路径动态装载**的模块（`spec_from_file_location` / `exec_module` /
    # 按 `Path(__file__).parent` 拼路径打开的那类）。它们不在 `exports` 里，
    # `files` 白名单漏列时 R1~R8 **全绿**，而装机后装载不到。
    #
    # 实测事故（2026-11-02）：`scripts/state_extract.py` 是状态事件台账的生产方，
    # 由 `sync_zcode_session._load_state_extract()` 按路径装载；而 `files` 只发
    # `scripts/workspace_index.py` ⇒ 发货清单 1794 件里 `scripts/` 仅 1 件，
    # 该抽取器 MISSING。后果不是「少个文件」，是整条记账链在装机环境断掉，
    # 生产台账 `_state_events.jsonl` 长期 0 条（实测该文件不存在）。
    #
    # 判据（**正向**：「必须真在包里」）：仓内存在、且被随包模块按路径装载的模块，
    # 其自身必须随包发货。扫描面只取 `spec_from_file_location(...)` 的**第二参数**
    # 里出现的 `.py` 字面量——这是「运行时真的会去打开它」的强信号；
    # 文档/注释里提到 `scripts/xxx.py` 不算（实测两者的交集为 0，若混算会误报
    # 数十条纯文档引用）。
    _r9_miss, _r9_skipped, _r9_note = [], [], []
    _r9_scanned = 0
    _r9_split = []
    try:
        _r9_miss, _r9_scanned, _r9_skipped = _runtime_loaded_not_shipped(
            root, pkg_set)
        _r9_split = _split_brain_split(root, pkg_set)
    except Exception as _exc:  # noqa: BLE001 —— 闸门自身不得因扫描失败而静默放行
        _r9_note.append("[R9] 跳过：扫描异常（%s: %s）"
                        % (type(_exc).__name__, _exc))
        _r9_miss, _r9_scanned, _r9_skipped = [], 0, []
        _r9_split = []
    if _r9_note:
        report.note(_r9_note)
        # 扫描不了 = 判据失效，不能读成「没问题」——与 R7 同款纪律。
        report.rule("R9 运行时必需件在位", False, ["扫描异常，判据失效"],
                    detail="；详见 NOTE")
    else:
        if _r9_skipped:
            report.note(["[R9a] 整链不发布（装载方自己不随包，装机侧不执行；"
                         "仅登记不判负）：%s" % x for x in _r9_skipped])
        report.rule(
            "R9a 随包模块按路径动态装载的件必须随包发货",
            not _r9_miss, _r9_miss,
            detail="；装载点 %d 处，其中整链不发布 %d 处"
                   % (_r9_scanned, len(_r9_skipped)))
        # R9b 是本轮缺陷**真正的**判据面（见 _split_brain_split 头注）。
        # 三档：未登记分叉 ⇒ 判负；已登记薄壳 ⇒ NOTE 保持可见；无分叉 ⇒ 绿。
        _r9b_bad = [e for k, e in _r9_split if k == "unregistered"]
        _r9b_ok = [e for k, e in _r9_split if k == "registered"]
        if _r9b_ok:
            report.note(["[R9b] 已登记薄壳（源码树保留、不随包，非缺陷）：%s"
                         % x for x in _r9b_ok])
        report.rule(
            "R9b 同一判据不得分叉两落点（未登记即判负）",
            not _r9b_bad, _r9b_bad,
            detail="；分叉 %d 组（已登记 %d）"
                   % (len(_r9_split), len(_r9b_ok)))

    # R10 随包文档的可执行引用可达（2026-11-02 补，**实测事故驱动**，与 R9 互补但面不同）：
    # R9 管「代码按路径装载的件在不在包里」；R10 管「**文档让人照抄的命令**在装机侧跑不跑得
    # 起来」。实测两次同类事故（probe_c / probe_d 的命令写作 `python scripts/x.py`，而
    # `scripts/` 只有 workspace_index.py 随包）——R1~R9 全绿也照样发生，因为缺陷不在「件
    # 在不在包里」，而在「文档指向的件不在包里」。本仓 2026-11-02 实测口径：随包 md 1100 件，
    # 可执行形态点名 33 处，其中不随包 11 处（3 处是修前 R10a 真缺陷，其余为维护者工具）。
    _r10a, _r10b, _r10_scanned = [], [], 0
    _r10_note = []
    _expired = []
    try:
        _r10a, _r10b, _r10_scanned = _r10_doc_exec_refs(root, pkg_set)
        # 登记过期的**反向**判据：目标已进 files 白名单，登记就该删——
        # 静默留着的代价是「它被移出白名单时也没人发现」（与 R9b 带前提同款纪律）。
        # 只对**精确文件条目**判过期：目录前缀条目（`hive/`）本身不代表「进了白名单」，
        # 它的前提是「整棵子树都没进」，已由扫描面（命中即不再报 B）天然表达。
        _norm = {p.replace("\\", "/") for p in pkg_set}
        _expired = [k for k in R10_REGISTERED_UNSHIPPED
                    if not k.endswith("/") and k in _norm]
    except Exception as _exc:  # noqa: BLE001 —— 闸门自身不得因扫描失败而静默放行
        _r10_note.append("[R10] 跳过：扫描异常（%s: %s）"
                         % (type(_exc).__name__, _exc))
        _r10a, _r10b, _r10_scanned = [], [], 0
        _expired = []
    if _r10_note:
        report.note(_r10_note)
        report.rule("R10 随包文档的可执行引用可达", False, ["扫描异常，判据失效"],
                    detail="；详见 NOTE")
    else:
        report.rule(
            "R10a 随包文档点名的脚本必须能被解析到（任一基址下真实存在）",
            not _r10a, _r10a,
            detail="；可执行引用 %d 处" % _r10_scanned)
        report.rule(
            "R10b 文档点名的脚本若不随包须登记（维护者工具除外）",
            not _r10b, _r10b,
            detail="；已登记 %d 项" % len(R10_REGISTERED_UNSHIPPED))
        if _expired:
            report.note(["[R10b] 登记已过期（目标已进 files 白名单，请删该条登记）：%s"
                         % k for k in _expired])

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
    # N251：内容面只覆盖「读得进来」的那部分清单条目——读不到 / 超限的件必须显式判负，
    # 否则 R1「内容面=0」把「未扫」读成「干净」（发版门禁的最后一道，不许有静默子集）。
    report.rule(
        "R7 扫描面完整性",
        not unscanned,
        unscanned,
        detail="；清单文件数=%d 未扫文本件=%d" % (len(paths), len(unscanned)))
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
            unscanned = []
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
                if not is_text_path(rel):
                    continue             # 非文本件按设计不扫（TEXT_EXTS 之外）
                # N251：下面两条 continue 修前分别被写成「收集条件不满足」与「读不出即跳过」
                # ——同一个「未扫」态与「已扫且干净」不可分。此处按成因逐条记账交 R7。
                if (m.size or 0) > TEXT_SIZE_LIMIT:
                    unscanned.append(
                        unscanned_entry(rel, unscanned_cause_oversize(m.size or 0)))
                    continue
                f = tf.extractfile(m)
                if not f:
                    unscanned.append(unscanned_entry(rel, UNSCANNED_UNREADABLE))
                    continue
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
            # 非文本件，或未扫文本件——未扫成因已在收集期逐条记入 unscanned（见 R7）
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
    # N251（registry 同族）：内容面只覆盖读得进来的成员——超限 / 读不出的文本成员判负。
    report.rule(
        "R7 扫描面完整性",
        not unscanned,
        unscanned,
        detail="；包内文件数=%d 未扫文本件=%d" % (len(rel_files), len(unscanned)))
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

    # N251：「未扫」成因单点——清单内文本件读不到 / 超限须报成因（不得与「已扫且干净」同形）。
    # 阈值经 globals 临时收窄，以免自检写 3MB 文件；真实阈值另由
    # scripts/test_check_publish_artifact_coverage.py 的 C1/L1 腿按 TEXT_SIZE_LIMIT 取证。
    with tempfile.TemporaryDirectory() as _t:
        _ok = os.path.join(_t, "ok.txt")
        with open(_ok, "w", encoding="utf-8", newline="\n") as _fh:
            _fh.write("普通正文\n")
        _img = os.path.join(_t, "img.png")
        with open(_img, "wb") as _fh:
            _fh.write(b"\x89PNG\r\n\x1a\n")
        _tx, _cz = read_local_text_detail(_t, "ok.txt")
        check(_tx is not None and _cz is None, "N251 已扫文本件无未扫成因", (_tx, _cz))
        _tx, _cz = read_local_text_detail(_t, "gone.txt")
        check(_tx is None and _cz == UNSCANNED_UNREADABLE,
              "N251 清单内读不到 → 报未扫成因", _cz)
        _tx, _cz = read_local_text_detail(_t, "img.png")
        check(_tx is None and _cz is None, "N251 非文本扩展名 → 按设计不扫（无成因）", _cz)
        _tx, _cz = read_local_text_detail(_t, "../outside.md")
        check(_tx is None and _cz is None, "N251 越根条目 → R5 判负，不记未扫（不许读）", _cz)
        _saved = globals()["TEXT_SIZE_LIMIT"]
        globals()["TEXT_SIZE_LIMIT"] = 4
        try:
            _tx, _cz = read_local_text_detail(_t, "ok.txt")
        finally:
            globals()["TEXT_SIZE_LIMIT"] = _saved
        check(_tx is None and bool(_cz) and "TEXT_SIZE_LIMIT" in _cz,
              "N251 清单内超限 → 报未扫成因（成因与读不到可区分）", _cz)
        check(len(unscanned_entry("a/b.txt", _cz)) > len("a/b.txt"),
              "N251 未扫记账行单点含成因", unscanned_entry("a/b.txt", _cz))

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



#: R10 的**登记豁免面**：随包文档里以**可执行形态**点名、但目标不随包的脚本。
#:
#: 为什么需要 R10（2026-11-02 补，与 R9 同源但**面不同**）：
#: R9 查的是「**代码**按路径装载的件在不在包里」；R10 查的是「**文档**让人照抄的命令
#: 在装上之后跑不跑得起来」。两者不重叠——R9 全绿时，文档里仍可能写着
#: `python scripts/xxx.py`，而 `scripts/` 只有 `workspace_index.py` 随包 ⇒ 装机用户
#: 照抄即 `Errno 2` / `ModuleNotFoundError`。本仓实测过两次这种「文档让人照抄一个
#: 装好的包里不存在的文件」（probe_c / probe_d，见 docs/mdcg/世界模型功能端…§七）。
#:
#: 判据口径（只认**可执行形态**，不认叙述性提及）：
#:   · 形态 = 行内出现 `python` / `py` 调用 token，其后跟 `-m <模块>` 或 `<…>.py`；
#:     裸反引号里的 `` `scripts/x.py` ``（叙述「它在 scripts 下」）**不算**——
#:     否则几十条纯说明性提及会把闸门淹掉（R9 已有同款教训：误报多了等于没闸门）。
#:   · 基址解析：仓根 → 文档所在目录 → 其上目录 → 所在代码块之前最近的 `cd <dir>`。
#:     这四个基址覆盖了本仓全部现实写法；解析不出任何基址才是真缺陷。
#:
#: 两档判据：
#:   R10a **解析不出任何基址** ⇒ 判负。读者在任何基址下都找不到该文件，
#:        属「文档写了条跑不了的命令」，无豁免可谈（2026-11-02 修前实测 3 处）。
#:   R10b **目标在源码树存在、但不随包** ⇒ 默认判负；登记后可放行。
#:        放行条件：该脚本是**维护者工具**（读者手里有完整源码树才用得上），
#:        且文档已在上下文里说明其位置边界。
#:
#: 登记格式：{"<仓根相对路径 或 目录前缀/>": {"why": "为何它只在源码树里被点名而不构成装机缺陷"}}
#: 目录前缀（以 `/` 结尾）用于**整棵子树都是源码树**的情形——比逐文件登记更贴近事实
#: （`hive/` 就是整目录不随包，不是「碰巧少发十几个文件」）。
#: 与 R9b 同款**带前提**纪律：一旦某条登记的目标**进了 files 白名单**，登记即失效
#: （不再是「不随包」），本函数会把该条报成「登记已过期」提请删除，不静默留着。
R10_REGISTERED_UNSHIPPED = {
    # 2026-11-13 合并：README 的评测/冒烟段点名的三件维护者工具（源码树在、不随包）。
    "test/locomo_independent_eval.py": {
        "why": "LoCoMo 五臂评测脚本——要用它得有 LoCoMo 语料与本地引擎，装机用户没有；"
               "README 把它列在「评测与复现」段，读者是维护者。",
    },
    "test/locomo_jaccard_probe.py": {
        "why": "LoCoMo 的 Jaccard 口径拆解探针——同上，维护者工具。",
    },
    "compiler/cli/__main__.py": {
        "why": "中文编译器的包内入口（`python -m compiler.cli`）——`compiler/` 是"
               "独立实验件，不在 npm 包 files 白名单；README 平台全景表点名它作为"
               "「怎么跑」的示例，读者是拿到完整仓库的人。",
    },
    "scripts/body_e2e_smoke.py": {
        "why": "身体×脑端到端冒烟（门禁第 14 项同一件）——需要完整仓库与身体侧入口，"
               "不随包；README 用它作端到端示例。",
    },
    "hive/": {
        "why": "`hive/` 整目录不在 files 白名单（只单独发了 hive/id_charset_blocks.txt 与 "
               "hive/README.md）——它是源码树里的 Rust 并发调度面。hive/README.md 会随包，"
               "但文中命令全部面向「手里有完整仓库的部署者」；该 README 顶部已加位置边界块。",
    },
    "scripts/run_tests.py": {
        "why": "全仓测试驱动器——只在源码树有意义（装机侧没有 tests/ 与绝大多数 scripts/）。"
               "它出现在 hive/README.md 的验收命令里。",
    },
    "scripts/render_discipline.py": {
        "why": "纪律渲染器——维护者工具（改真源后重渲染各端产物）。装机用户不需要跑："
               "纪律注入是插件**已渲染好的产物**，不是安装期步骤。文档已按此标注。",
    },
    "scripts/verify_discipline.py": {
        "why": "纪律漂移校验器——维护者工具，与 render_discipline.py 配套；装机侧无"
               "真源可比对，跑它没有意义。文档已按此标注。",
    },
    "scripts/gate_output.py": {
        "why": "对外交付前的 echo/版本锚判据——维护者工具。它点名出现在**渲染产物**"
               "（CODEBUDDY.md / AGENTS.md 第 19 条纪律正文）里，属纪律本体的一部分，"
               "对装机用户是「知道有这条纪律」而非「现在就去跑」。",
    },
    "scripts/state_atlas.py": {
        "why": "多主体状态追踪图——源码树工具，依赖同样不随包的兄弟件"
               "（whale_state_tracker 等），整体迁移待裁。文档 §十 已显式标注"
               "「前三件在装机侧不存在」并给出随包替代面（md_cg.state_slots / stg）。",
    },
    # 2026-11-02：两个探针的**源码树薄垫片**。文档 §七 引它们时写的是
    # 「源码树里 python -X utf8 scripts/probe_X.py 也照旧可用（薄垫片…）；但装机侧
    # 只有 -m 形态」——即文档自己就说明了这处引用只在源码树成立。本体已随包。
    "scripts/probe_c_ledger_integrity.py": {
        "why": "薄垫片（只转发 md_cg.probe_c_ledger_integrity，本体随包）。文档 §七.1 "
               "引用它时已写明「源码树里可用、装机侧用 -m 形态」，与 R9b 同一份登记口径。",
    },
    "scripts/probe_d_retirement_discipline.py": {
        "why": "薄垫片（只转发 md_cg.probe_d_retirement_discipline，本体随包）。"
               "文档 §七.4 引用它时已写明「装机侧只有 -m 形态」，同上。",
    },
    "hive/hive_mcp/mcp_server.py": {
        "why": "蜂巢 MCP server——`hive/` 整目录不在 files 白名单。dsh/README.md 讲的是"
               "「怎么把它接进 DSH」，读者须先有源码树；文档已加位置边界块。",
    },
    # 2026-11-06：英文文档面（docs/en/）这两件。它们是**维护者工具**，不是装机件。
    "scripts/audit_translation.py": {
        "why": "英文文档翻译机械门禁——读 docs/en/TRANSLATION_MANIFEST.json，逐对校验"
               "结构保真（围栏代码块逐字节一致、标题层级序列一致、无未译汉字、相对链接"
               "可解析、生成文档不得手译）。它校验的**真源是 docs/ 与 TRANSLATION_MANIFEST"
               "本身**，装机侧既无源码树也无清单可对照，跑它没有意义。docs/en/TRANSLATION.md"
               "（翻译者手册）与 docs/en/glossary.md 点名的都是「改译文的人」的动作。",
    },
    "scripts/cogmap_sync.py": {
        "why": "认知图文档同步管线——从 md_cg/mcp_server.py 与 md_cg/whitebox.py **AST 提取**"
               "工具名/op 分支行/模块链，重生成《功能调用映射表》。真源是源码树，装机侧没有"
               "可提取的源；docs/en/mdcg/generated-docs.md 讲的是「这些文档怎么生成」，"
               "面向改文档的维护者，不是装机用户要执行的动作。",
    },
}

#: R10 的可执行形态正则。**只认调用**：`python [-flags] [-m mod | path/to/x.py]`。
#: 前导字符集合含反引号/引号/括号/管道——覆盖 `… 写作 \`python x.py\` 会挂` 这类行内写法；
#: 但要真的是「一次调用」，故 `python` 之前必须是分隔符或行首（防止 `mypython.py` 误命中）。
#:
#: flags 面**必须显式枚举**（2026-11-02 修）：最初写成 `(?:\s+-[A-Za-z0-9]+)*`，
#: 结果 `python -X utf8 scripts/x.py` 整条**扫不到**——`-X` 被当 flag 吃掉后，剩下的
#: `utf8` 不是 `.py`，正则在此失败并放弃该行。而本仓文档里带 `-X utf8` 的命令不少
#: （探针/守卫都这么写），漏扫等于给这一类留了白名单。现按 CPython 真实 CLI 分两组：
#:   · 取值型：`-X opt` / `-W arg` / `-Q arg`（**其后必须跟值**，故两段一起匹配）
#:   · 无值型：`-u -B -E -I -O -q -s -S -b -d -h -i -R -v -V` 与 `--long[=v]`
#: 这样既不会把 `-u script.py` 里的 `script.py` 误吃成 `-u` 的值（那是上一版另一种错法），
#: 也不会漏掉 `-X utf8`。新 flag 出现时最坏是「不扫」，不会「扫错」。
_R10_PY_VAL_FLAGS = r"-{1,2}[XWQ]\s+[^\s`\"'<>|;]+"
_R10_PY_BOOL_FLAGS = r"-{1,2}(?:[uBEIOqsSbdhiRvV]+|(?:-[A-Za-z0-9_-]+)(?:=[^\s]*)?)"
_R10_EXE = re.compile(
    r"(?:^|[\s`\"'($>|;])"
    r"(?:python[0-9.]*|py)"
    r"(?:\s+(?:" + _R10_PY_VAL_FLAGS + r"|" + _R10_PY_BOOL_FLAGS + r"))*"
    r"\s+(?:(?:-m)\s+([A-Za-z_][\w.]*)|((?:[A-Za-z]:)?[^\s`\"'<>|;]*?\.py))"
)
#: 代码块里的 `cd <dir>` / `pushd <dir>`——文档大量使用「先 cd 再跑相对路径」的写法，
#: 不认这个基址会把一批**能跑**的命令误判成 R10a。
_R10_CD = re.compile(r"^\s*(?:cd|pushd)\s+([^\s;&|`]+)\s*$")
#: R10 的**占位符面**（2026-11-06 补）。文档讲「怎么跑测试/怎么调某个工具」时，
#: 普遍会用示意路径举例，例如 `python md_cg/test_xxx.py`——原文恰恰是拿它说明
#: 「直接这样跑会 ImportError」，它**不是**一条让读者照抄的命令。若不排除，
#: 这类示意路径会被判成 R10a「文档写了条跑不了的命令」，属误报
#: （实测上游 docs/en/dev/coding-testing.md:26 因而红）。
#: 判据只认**真实文件名**：路径任一段命中下列形态即视为占位符——
#:   `xxx` / `Xxx`、`<...>`、`{...}`、`*`、`...`、`$VAR`、`%VAR%`、`NAME` 全大写变量段。
#: 注意这是**跳过整条引用**且不计数（不计入 scanned），故不会掩盖「扫了 0 处」。
_R10_PLACEHOLDER = re.compile(
    r"(?:^|/)[^/]*x{3,}[^/]*(?:/|$)"                # 段内含 3+ 个 x：xxx / test_xxx.py
    r"|(?:^|/)(?:<[^/]*>|\{[^/]*\}|\*+|\.{3,}|\$[\w]+|%[\w]+%)(?:\.\w+)?(?:/|$)",
    re.IGNORECASE,
)


def _r10_registered(rel):
    """该路径是否落在 R10 登记面内（精确条目 或 目录前缀条目）。"""
    rel = rel.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    for key in R10_REGISTERED_UNSHIPPED:
        k = key.replace("\\", "/")
        if k.endswith("/"):
            if rel.startswith(k):
                return key
        elif rel == k:
            return key
    return None


def _r10_base_candidates(doc_rel, raw, cd_dir):
    """文档内可执行引用的**基址候选**（按现实写法排序，先命中先用）。

    `cd <dir>` 的基址有两种现实读法，都要认（2026-11-02 实测出来的）：
      · 相对**仓根**——读者在仓根开终端，`cd skills/x` 这类写法属这种；
      · 相对**文档所在目录**——文档自己的示例块里 `cd sub`，指的是它旁边的 sub/。
    只认一种会漏判一半（本仓 skills/README.md 就踩过：`cd skills/designer-perspective`
    在仓根下不成立、在文档目录下也不成立——它本身就是条陈旧路径，属真缺陷）。
    """
    cands = [("repo-root", raw)]
    docdir = os.path.dirname(doc_rel).replace("\\", "/") or "."
    if docdir != ".":
        cands.append(("doc-dir", docdir + "/" + raw))
        parent = os.path.dirname(docdir).replace("\\", "/") or "."
        if parent != "." and parent != docdir:
            cands.append(("doc-parent", parent + "/" + raw))
    if cd_dir:
        cands.append(("cd-block", cd_dir + "/" + raw))
        if docdir != ".":
            cands.append(("cd-block-doc", docdir + "/" + cd_dir + "/" + raw))
    return cands


def _r10_doc_exec_refs(root, pkg_set):
    """R10 扫描：随包文档里**可执行形态**点名的脚本，解析得到却跑不到的那些。

    返回 ``(unresolved, unshipped, scanned)``：
      unresolved —— R10a 命中（任何基址下都不存在的目标），元素为说明串；
      unshipped  —— R10b 命中（源码树存在但不随包、且未登记），元素为说明串；
      scanned    —— 实际扫到的可执行引用处数（用于打印「扫了 N 处」，
                    防止「扫了 0 处」被读成「很干净」——与 R7 同款纪律）。
    """
    shipped = [p.replace("\\", "/") for p in pkg_set]

    def _is_shipped(rel):
        rel = rel.replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        return any(rel == s or rel.startswith(s.rstrip("/") + "/") for s in shipped)

    def _ondisk(rel):
        return os.path.isfile(os.path.join(root, *rel.split("/")))

    md_docs = [p.replace("\\", "/") for p in pkg_set
               if p.lower().endswith(".md") and _is_shipped(p)]
    unresolved, unshipped = [], []
    scanned = 0
    for doc in md_docs:
        fp = os.path.join(root, *doc.split("/"))
        try:
            with open(fp, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        cd_dir, cd_at = None, {}
        for i, line in enumerate(lines, 1):
            m = _R10_CD.match(line.strip("`").strip())
            if m:
                c = m.group(1).replace("\\", "/").rstrip("/")
                while c.startswith("./"):
                    c = c[2:]
                # `cd <dir>` 的落点同样有两种现实读法：相对仓根、相对文档所在目录。
                # 只按仓根判目录存在性会把文档自带的 `cd sub`（sub 就在文档旁边）整条否掉。
                docdir0 = os.path.dirname(doc).replace("\\", "/") or "."
                for cand in ([c] if docdir0 == "." else [c, docdir0 + "/" + c]):
                    if os.path.isdir(os.path.join(root, *cand.split("/"))):
                        cd_dir = cand
                        break
            cd_at[i] = cd_dir
        for ln, line in enumerate(lines, 1):
            for m in _R10_EXE.finditer(line):
                mod, path = m.group(1), m.group(2)
                # 2026-11-13 合并：`-m` 既可能是**模块**（a/b.py），也可能是
                # **包**（a/b/__main__.py 或 a/b/__init__.py）。上一版只认前一种，
                # 于是 `python -m compiler.cli`（包）被误报成「文件不存在」。
                # 这里按 Python 的三档解析顺序试，命中即用。
                _raw_mods = ([(mod.replace(".", "/") + ".py"),
                              (mod.replace(".", "/") + "/__main__.py"),
                              (mod.replace(".", "/") + "/__init__.py")]
                             if mod else [path])
                _cands = []
                for _r in _raw_mods:
                    _r = (_r or "").replace("\\", "/")
                    while _r.startswith("./"):
                        _r = _r[2:]
                    if _r:
                        _cands.append(_r)
                if not _cands:
                    continue
                # 占位符面（2026-11-06 修）：文档讲「怎么跑测试」时普遍写
                # `python md_cg/test_xxx.py` 这类**示意路径**，它不是让读者照抄的
                # 命令——原文恰恰是拿它举例说明「直接跑会 ImportError」。不排除
                # 会把它报成 R10a「文档写了条跑不了的命令」，属误报（实测上游
                # docs/en/dev/coding-testing.md:26 就是这么红起来的）。
                # 判据只认**真实文件名**：路径里任一段含 xxx/<...>/{...}/* 者跳过，
                # 且不计入 scanned（它不是一次可执行引用）。
                _eff = [c for c in _cands if not _R10_PLACEHOLDER.search(c)]
                if not _eff:
                    continue
                scanned += 1
                hit = None
                for raw in _eff:
                    for _base, cand in _r10_base_candidates(doc, raw, cd_at.get(ln)):
                        if _ondisk(cand):
                            hit = cand
                            break
                    if hit is not None:
                        break
                raw = _eff[0]
                if hit is None:
                    unresolved.append("%s:%d → %s（仓根/文档目录/上级目录/cd 块四种"
                                      "基址下均不存在）" % (doc, ln, raw))
                    continue
                if _is_shipped(hit):
                    continue
                if _r10_registered(hit):
                    continue
                unshipped.append("%s:%d → %s（源码树存在，不在 files 白名单）"
                                 % (doc, ln, hit))
    return unresolved, unshipped, scanned



if __name__ == "__main__":
    sys.exit(main())
