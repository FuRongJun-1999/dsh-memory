# -*- coding: utf-8 -*-
"""默认策略加载守卫（issue #43 问题 1 修复，2026-09-29）。

运行：python -X utf8 -m md_cg.test_issue43_default_policy
      python -X utf8 -m md_cg.test_issue43_default_policy --mutation-baseline

缺陷（第 4 条取证）：默认安装下写入闸门不生效——
  (a) `audit.load_rulebook` 只从 `MDCG_POLICY_FILE` 取路径，未设即返回**空规则库**
      且无任何默认回落；空规则让 `_rule_check` 恒判 `DEFER`；
  (b) npm 包不含 `data/policy.json`、`lingshu-init` 也不生成该 env，而 README 写
      「默认 data/policy.json」——三处不符；
  (c) 后果不是「少一条规则」而是**安全面翻转**：`writepipe._gate_audit` 的
      非 ACCEPT/REJECT 出口是 `cg.propose` ⇒ 正文（含凭据）**明文**落
      `hippocampus/inbox.jsonl`，且脱敏只在 REJECT 分支。

使用者 2026-09-29 裁定方向（①+③）：
  ① 包内随发默认策略（`package.json` 的 files 纳入 `data/policy.json`），
     `load_rulebook` 未设/为空时回落**包内默认路径**（按包根解析、不依赖 cwd）；
  ② 未设且包内默认也拿不到 → **fail-closed**，且必须发生在提案入队**之前**
     （不落节点、不 propose、inbox.jsonl 字节面零正文），错误结构化
     （错误码 + 可执行 hint）；
  ③ 显式 `MDCG_POLICY_FILE` 指向不可读/不可解析的文件同样 fail-closed。

本套断言分八组：
  G1 包内默认回落生效（未设 / 空串两条路；规则内容与包内文件逐条一致）
  G2 定位不依赖 cwd（chdir 到系统临时目录后包根/策略路径/解析结果三不变）
  G3 未设且不可用 → fail-closed 且**零正文**（合成凭据 + 标记实测 inbox 与全库字节面）
  G4 显式坏路径 fail-closed（不存在 / 不可解析 / 顶层非对象 / 目录不可读 + 端到端）
  G5 默认安装的真实行为（包内默认生效：命中禁表或缺六要素 → REJECT，绝不进审核队列）
  G6 来源可见面（`--show-config` / 启动 stderr 单行 / `cg(op=info).write_policy`）
  G7 单点与接线（防副本回归；含判据函数自身的合成负例判别力自证）
  G8 **键类型闸**（issue #43 补强；复核判 DEFER 的实据面）：策略是合法 JSON 对象
     而列表型键取值是**标量**（int / bool / str）时，三面同时失守的旧行为被钉死——
     ① `policy_report()` 抛 `TypeError`（int/bool）或把字符串长度当规则数（str）；
     ② `mcp_server.py` 启动调用不在 try 内 ⇒ server rc=1、诊断面 rc=1 且 stdout 空；
     ③ 写入侧 `_rule_check` 同抛被兜底吞成 DEFER ⇒ 正文（含凭据）逐字落
     `hippocampus/inbox.jsonl`。收口口径：**任何列表型键取值非列表 ⇒ 一律视同
     策略不可用**，走与①②③同一条 fail-closed（在提案入队之前拦下），
     `policy_report()` 恒不抛、`--show-config` 恒退出 0（`available=false`）、
     启动 stderr 的来源行不因策略畸形缺失、`op=info` 不被拖崩、字符串**不按
     字符拆成规则**。每形态 7 条（A 诊断面 / B 解析面 / C `--show-config`(同进程) /
     C2 真进程 `--show-config` / D 真进程启动 / E 写入 fail-closed 且字节面零
     正文 / F `op=info` 面）+
     3 条（G 计数非长度 / H 消费面纵深 / I 形状闸不误伤合法默认策略）。

**变异自证（--mutation-baseline）**：逐个**定点变异**生产实现（源码锚点替换后
exec，不碰磁盘文件），套件必须转红且**恰好命中声明条数**（多一条少一条都判
FAIL——多了说明断言串扰，少了说明该判据空转）。变异锚点写死在 `_MUTATIONS`，
实现改动致锚点漂移即报 **ANCHOR-MISS 并退出码 2**（fail-closed）。G8-D 走**真
子进程**（`python -m md_cg.mcp_server`），内存 patch 不跨进程 ⇒ 对 `audit` 模块
的变异另经 `sitecustomize.py` 注入子进程（N225 同款），注入标记缺失即报
**INJECT-MISS 并退出码 2**（否则「子进程那半」会静默不设防）。

**基线源纪律**：本套**不以 git HEAD 为基线源**（基线绑提交即失效，本仓已有两次
教训）——判别力由「源码锚点变异 + 逐条计数」现场自证，与提交状态无关。
实验一律用系统临时目录的合成库；合成凭据是拼接哑值，非真凭据。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import audit
from . import mcp_server
from . import writepipe
from .mdcos import MdCGSecure
from .security import Principal

_PASS = []
_FAIL = []
_RED = []          # [(组名, 断言名)] —— 变异核验只看它
_GROUP = ["?"]

# 合成凭据（拼接哑值，非真凭据；整串在源码里不成形态，发布闸不误报）与正文标记
SECRET = "sk-" + ("A1b2C3d4" * 3)
MARK = "I43CANARY"

# 包内默认策略的**规模基线**（防「禁表被削弱」的显式人工核对位，非从文件自身推导——
# 那样即自证空转）。计数随策略真源 `data/policy.json` 变更同步：
#   11 → 12（2026-10-09 issue #82.1 提交 0590b650「禁表扩边界」新增第 12 条
#   『是/为/等于/is』凭据形态；该笔只改了 data/policy.json + 新守卫，未同步本件）。
_EXPECTED_FORBIDDEN = 12
_EXPECTED_REQUIRED = 6       # 六要素（功能名/生效条件/子功能/执行/验证方式/不适用条件）


def _group(name):
    _GROUP[0] = name


def ok(cond, name):
    global _PASS
    if cond:
        _PASS.append(name)
        print("  PASS " + name)
    else:
        _FAIL.append(name)
        _RED.append((_GROUP[0], name))
        print("  FAIL " + name)


# ---------------------------------------------------------------- 实验装置

@contextlib.contextmanager
def _env(**kw):
    """临时设定/清除环境变量（None = 清除），退出时逐键恢复。"""
    old = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def _dfl_policy(path):
    """临时把包内默认策略路径指向 path（实验注入点；用后必还原）。"""
    old = audit.default_policy_path
    audit.default_policy_path = (lambda: path)
    try:
        yield
    finally:
        audit.default_policy_path = old


def _write_text(tmp, name, text):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def _cg(root):
    p = Principal(tenant="default", actor="i43-t", role="designer",
                  can_write=True, can_admin=True)
    return MdCGSecure(root, principal=p)


def _pipe():
    return writepipe.install_default_gates(writepipe.WritePipeline())


def _root_bytes(root):
    """root 下全部文件的字节面拼合（零正文的**全库**判据面）。"""
    chunks = []
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            try:
                with open(os.path.join(dp, fn), "rb") as f:
                    chunks.append(f.read())
            except OSError:
                pass
    return b"\n".join(chunks)


def _inbox_bytes(root):
    p = os.path.join(root, "hippocampus", "inbox.jsonl")
    if not os.path.exists(p):
        return b""
    with open(p, "rb") as f:
        return f.read()


# ---------------------------------------------------------------- G1 包内回落

def g1():
    _group("G1")
    with _env(MDCG_POLICY_FILE=None):
        rules, src, err = audit.resolve_rulebook()
        ok(src == "package_default" and err is None,
           "G1a 未设 env → 回落包内默认（source=%s）" % src)
        with open(audit.default_policy_path(), encoding="utf-8") as f:
            dflt = json.load(f)
        ok((rules or {}) == dflt,
           "G1b 规则与包内 data/policy.json 逐条一致（不掺默认值）")
        ok(len((rules or {}).get("forbidden") or []) == _EXPECTED_FORBIDDEN
           and len((rules or {}).get("required") or []) == _EXPECTED_REQUIRED,
           "G1c 包内默认含 %d 条 forbidden + %d 条 required（禁表与六要素未被削弱）"
           % (_EXPECTED_FORBIDDEN, _EXPECTED_REQUIRED))
        ok(audit.load_rulebook() == dflt,
           "G1d load_rulebook 未设 env 时同样回落包内默认")
        rep = audit.policy_report()
        ok(rep.get("source") == "package_default" and rep.get("available") is True
           and rep.get("forbidden") == _EXPECTED_FORBIDDEN
           and rep.get("required") == _EXPECTED_REQUIRED,
           "G1e policy_report 报出来源与计数（source=%s）" % rep.get("source"))
    with _env(MDCG_POLICY_FILE=""):
        rules2, src2, err2 = audit.resolve_rulebook()
        ok(src2 == "package_default" and err2 is None and bool(rules2),
           "G1f env 为空串同样回落包内默认（「未设/为空」两条路）")


# ---------------------------------------------------------------- G2 不依赖 cwd

def g2():
    _group("G2")
    before_root = audit.package_root()
    before_path = audit.default_policy_path()
    tmp = tempfile.mkdtemp(prefix="i43_cwd_")
    cwd = os.getcwd()
    try:
        os.chdir(tmp)
        ok(audit.package_root() == before_root
           and os.path.isfile(os.path.join(audit.package_root(), "md_cg", "audit.py")),
           "G2a package_root 不随 cwd 变（且指向含 md_cg/audit.py 的包根）")
        ok(audit.default_policy_path() == before_path
           and os.path.isfile(before_path),
           "G2b default_policy_path 不随 cwd 变且文件存在")
        rules, src, err = audit.resolve_rulebook()
        ok(src == "package_default" and err is None and bool(rules),
           "G2c cwd 在别处时仍解析到包内默认策略（source=%s）" % src)
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- G3 不可用 → fail-closed

def g3():
    _group("G3")
    tmp = tempfile.mkdtemp(prefix="i43_unavail_")
    miss = os.path.join(tmp, "no_such_policy.json")
    try:
        with _dfl_policy(miss), _env(MDCG_POLICY_FILE=None):
            root = os.path.join(tmp, "root")
            cg = _cg(root)
            out = _pipe().execute(cg, {
                "node_id": "i43_unavail", "content_kind": "text", "layer": "knowledge",
                "content": "%s 正文 %s\n" % (MARK, SECRET)})
            ok(out.get("moved_to") == "policy_unavailable"
               and out.get("committed") is False and out.get("ok") is False,
               "G3a 未设 env 且包内默认不可得 → fail-closed（moved_to=%s）"
               % out.get("moved_to"))
            err = out.get("error") or {}
            ok(isinstance(err, dict) and err.get("code") == "policy_unavailable"
               and bool(err.get("hint")),
               "G3b 错误结构化：code=policy_unavailable 且有可执行 hint")
            ib = _inbox_bytes(root)
            ok(SECRET.encode() not in ib and MARK.encode() not in ib,
               "G3c inbox.jsonl 字节面零正文（len=%d）" % len(ib))
            ok(not os.path.exists(os.path.join(root, "knowledge", "i43_unavail.md")),
               "G3d 未落节点（knowledge/ 无该 id 文件）")
            rb = _root_bytes(root)
            ok(SECRET.encode() not in rb and MARK.encode() not in rb,
               "G3e 全库字节面零正文（含负记忆/索引，len=%d）" % len(rb))
            ok(SECRET not in json.dumps(out, ensure_ascii=False),
               "G3f 响应体亦不含凭据明文")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- G4 显式坏路径

def g4():
    _group("G4")
    tmp = tempfile.mkdtemp(prefix="i43_envbad_")
    try:
        with _env(MDCG_POLICY_FILE=os.path.join(tmp, "no_such.json")):
            rules, src, err = audit.resolve_rulebook()
            ok(src == "env" and (err or {}).get("code") == "policy_not_found",
               "G4a 显式坏路径 → 不可用（source=env code=policy_not_found）")
            ok(rules is None,
               "G4b 显式坏路径**不回落到包内默认**（rules 为 None，非包内规则）")
            ok(audit.load_rulebook() == {},
               "G4c load_rulebook 对坏路径返回空规则（不抛异常）")
        for name, text, want in (
                ("bad_json.json", "{ oops", "policy_invalid_json"),
                ("not_object.json", "[1,2,3]", "policy_not_object"),
                ("empty_obj.json", "{}", None)):
            with _env(MDCG_POLICY_FILE=_write_text(tmp, name, text)):
                _r, _s, e2 = audit.resolve_rulebook()
                if want is None:
                    ok(e2 is None and _r == {},
                       "G4d 空 dict 是**可用**策略（内容为空，非可用性故障）")
                else:
                    ok((e2 or {}).get("code") == want,
                       "G4e 显式坏路径 %s → code=%s" % (name, want))
        with _env(MDCG_POLICY_FILE=tmp):          # 目录：exists 为真但不可读
            _r, _s, e3 = audit.resolve_rulebook()
            ok((e3 or {}).get("code") == "policy_unreadable",
               "G4f 显式路径指向目录（不可读）→ code=policy_unreadable")
        # 端到端：显式坏路径 → fail-closed，队列零正文
        with _env(MDCG_POLICY_FILE=os.path.join(tmp, "no_such.json")):
            root = os.path.join(tmp, "root")
            cg = _cg(root)
            out = _pipe().execute(cg, {
                "node_id": "i43_envbad", "content_kind": "text", "layer": "knowledge",
                "content": "%s 正文 %s\n" % (MARK, SECRET)})
            ok(out.get("moved_to") == "policy_unavailable"
               and out.get("committed") is False,
               "G4g 端到端：显式坏路径写入 fail-closed（moved_to=%s）"
               % out.get("moved_to"))
            rb = _root_bytes(root)
            ok(SECRET.encode() not in rb and MARK.encode() not in rb,
               "G4h 端到端：全库字节面零正文（len=%d）" % len(rb))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- G5 默认安装真实行为

def g5():
    _group("G5")
    tmp = tempfile.mkdtemp(prefix="i43_default_")
    try:
        with _env(MDCG_POLICY_FILE=None):
            root = os.path.join(tmp, "root_a")
            cg = _cg(root)
            out = _pipe().execute(cg, {
                "node_id": "i43_cred", "content_kind": "text", "layer": "knowledge",
                "content": "%s 正文 %s\n" % (MARK, SECRET)})
            ok(out.get("moved_to") == "rejected" and out.get("committed") is False
               and "命中禁止规则" in str((out.get("verdict") or {}).get("evidence")),
               "G5a 默认策略生效：命中禁表 → REJECT（moved_to=%s）"
               % out.get("moved_to"))
            ok(SECRET.encode() not in _inbox_bytes(root) and MARK.encode() not in _inbox_bytes(root),
               "G5b inbox 零正文（不进审核队列）")
            rb = _root_bytes(root)
            ok(SECRET.encode() not in rb, "G5c 负记忆已脱敏（凭据不出现）")
            ok("[已过滤:禁表#".encode() in rb, "G5d 负记忆含脱敏占位符（脱敏确实发生）")
            root_b = os.path.join(tmp, "root_b")
            cg_b = _cg(root_b)
            out_b = _pipe().execute(cg_b, {
                "node_id": "i43_six", "content_kind": "text", "layer": "knowledge",
                "content": "%s 只有标记没有六要素\n" % MARK})
            detail = (out_b.get("verdict") or {}).get("detail") or {}
            ok(out_b.get("moved_to") == "rejected" and out_b.get("committed") is False
               and len(detail.get("missing") or []) == 6,
               "G5e 缺六要素 → REJECT 且给全六条缺失清单（missing=%d）"
               % len(detail.get("missing") or []))
            ok(MARK.encode() not in _inbox_bytes(root_b),
               "G5f 缺要素场景 inbox 亦零正文")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- G6 来源可见面

def g6():
    _group("G6")
    argv = sys.argv
    with _env(MDCG_POLICY_FILE=None):
        buf = io.StringIO()
        try:
            sys.argv = [argv[0], "--show-config"]
            with contextlib.redirect_stdout(buf):
                rc = mcp_server.main()
        finally:
            sys.argv = argv
        out = buf.getvalue().strip()
        ok(rc == 0 and bool(out),
           "G6a --show-config 只读诊断面：退出码 0 且有输出（rc=%s）" % rc)
        try:
            doc = json.loads(out.splitlines()[-1]) if out else {}
        except (ValueError, IndexError):
            doc = {}
        ok(isinstance(doc.get("policy"), dict)
           and doc["policy"].get("source") == "package_default"
           and doc["policy"].get("available") is True,
           "G6b --show-config 报出来源=包内默认（source=%s）"
           % (doc.get("policy") or {}).get("source"))
        ok(doc.get("policy") == audit.policy_report(),
           "G6c --show-config 与 policy_report 同一判据（无第二套口径）")
        ok(doc.get("server") == mcp_server.SERVER_NAME
           and doc.get("version") == mcp_server.SERVER_VERSION,
           "G6d --show-config 含 server/version 自报")
    with _env(MDCG_POLICY_FILE=os.path.join(tempfile.gettempdir(), "i43_none.json")):
        buf2 = io.StringIO()
        try:
            sys.argv = [argv[0], "--show-config"]
            with contextlib.redirect_stdout(buf2):
                rc2 = mcp_server.main()
        finally:
            sys.argv = argv
        try:
            doc2 = json.loads(buf2.getvalue().strip().splitlines()[-1])
        except (ValueError, IndexError):
            doc2 = {}
        ok(rc2 == 0 and (doc2.get("policy") or {}).get("available") is False
           and bool(((doc2.get("policy") or {}).get("error") or {}).get("code")),
           "G6e 策略不可用时 --show-config 仍退出 0 且 available=false + code")
    with _env(MDCG_POLICY_FILE=None):
        rep = audit.policy_report()
        line = mcp_server._policy_stderr_note(rep)
        ok("写入策略：来源=package_default" in line and rep["path"] in line,
           "G6f 启动 stderr 单行报出「来源=包内默认 + 路径」")
    bad = dict(audit.policy_report(), available=False, source="unavailable",
               error={"code": "policy_unavailable", "reason": "哑值", "hint": "哑值"})
    line2 = mcp_server._policy_stderr_note(bad)
    ok("fail-closed" in line2 and "policy_unavailable" in line2,
       "G6g 不可用时启动 stderr 单行点明 fail-closed 与错误码")
    with _env(MDCG_POLICY_FILE=None):
        tmp = tempfile.mkdtemp(prefix="i43_info_")
        try:
            cg = _cg(os.path.join(tmp, "root"))
            info = mcp_server.call_tool(cg, "cg", {"op": "info"})
            wp = info.get("write_policy") or {}
            ok(wp.get("source") == "package_default" and wp.get("available") is True,
               "G6h cg(op=info).write_policy 报出来源（source=%s）" % wp.get("source"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- G7 单点与接线

def _def_count(src, name):
    import re
    return len(re.findall(r"^def %s\b" % name, src, re.M))


def _files_has_policy(files):
    return "data/policy.json" in (files or [])


def _func_body(src, name):
    i = src.index("def %s(" % name)
    j = src.find("\ndef ", i + 1)
    return src[i:(j if j > 0 else len(src))]


def _code_only(body):
    return "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))


def _no_env_in_load(src):
    """载入面不得自行读 env（来源判定单点在上游 resolve_rulebook）。"""
    return "os.environ" not in _code_only(_func_body(src, "load_rulebook"))


def g7():
    _group("G7")
    with open(audit.__file__, encoding="utf-8") as f:
        a_src = f.read()
    ok(_def_count(a_src, "resolve_rulebook") == 1
       and _def_count(a_src, "policy_report") == 1
       and _def_count(a_src, "load_rulebook") == 1,
       "G7a 来源解析/自描述/载入在 audit.py 各仅一处实现（单点）")
    ok(_def_count(a_src + "\n\ndef resolve_rulebook():\n    pass\n",
                  "resolve_rulebook") == 2,
       "G7b 单点判据有判别力（合成负例：加一份副本即计为 2）")
    ok(_no_env_in_load(a_src) is True,
       "G7c load_rulebook 不再自行读 env（来源判定单点在上游 resolve_rulebook）")
    ok(_no_env_in_load(_func_body(a_src, "load_rulebook")
                       + "\n    p = os.environ.get('MDCG_POLICY_FILE')\n") is False,
       "G7c' 判据有判别力（合成负例：载入面塞回 env 读取即 False）")
    with open(writepipe.__file__, encoding="utf-8") as f:
        w_src = f.read()
    body = w_src[w_src.index("def _gate_audit"):w_src.index("def _gate_audit") + 4000]
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))
    ok("resolve_rulebook" in code and "policy_unavailable" in code,
       "G7d 写入闸门在提案前有策略可用性前置（可执行行内）")
    with open(mcp_server.__file__, encoding="utf-8") as f:
        m_src = f.read()
    ok("_policy_stderr_note(_audit.policy_report())" in m_src,
       "G7e 启动 stderr 接线未断（main → 内容单点）")
    ok('if "--show-config" in sys.argv:' in m_src,
       "G7f --show-config 分派接线未断")
    with open(os.path.join(audit.package_root(), "package.json"), encoding="utf-8") as f:
        pkg = json.load(f)
    ok(_files_has_policy(pkg.get("files")) is True,
       "G7g package.json files 含 data/policy.json（默认策略随包发布）")
    ok(_files_has_policy(["lib", "md_cg"]) is False,
       "G7h 判据有判别力（合成负例：files 不含该项即 False）")


# ---------------------------------------------------------------- G8 键类型闸

# 三种标量形态（契约⑦）：**合法 JSON 对象**，但列表型键取标量。
# str 形态的取值刻意取一个「按字符拆开就一定会命中普通文本」的串：旧行为下
# `_rule_check` 会以单字符规则判定（count 与判定双失真），是本形态的病态点。
_STRV = "sk-" + ("Zz9" * 8)
_SCALARS = (
    ("int", {"forbidden": 1, "required": ["^# 功能名"]}),
    ("bool", {"forbidden": True, "required": ["^# 功能名"]}),
    ("str", {"forbidden": _STRV, "required": ["^# 功能名"]}),
)


def _policy_file(tmp, name, obj):
    p = os.path.join(tmp, name + ".json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return p


# 生效条件：无条件调用 audit.policy_report()，不抛到调用方——返回 (报告 dict 或 None, 异常类型名或 None)，供「恒不抛」类断言取证用。
def _pr_safe():
    try:
        return audit.policy_report(), None
    except Exception as exc:                          # noqa: BLE001
        return None, type(exc).__name__


# 生效条件：以 sys.argv=["--show-config"] 在本进程内跑 mcp_server.main()，捕获其 stdout 后还原 argv；返回 (退出码, 解析出的 doc 或 {})。
def _show_config_doc():
    argv = sys.argv
    buf = io.StringIO()
    try:
        sys.argv = [argv[0], "--show-config"]
        with contextlib.redirect_stdout(buf):
            rc = mcp_server.main()
    finally:
        sys.argv = argv
    try:
        doc = json.loads(buf.getvalue().strip().splitlines()[-1])
    except (ValueError, IndexError):
        doc = {}
    return rc, doc


# 真子进程启动面的隔离注入面（与 N225 守卫同款）：剔净全部 MDCG_* 注入，只留
# 指向临时目录的覆盖键——子进程绝不读真实 ~/.mdcg、真实令牌库与真实密钥面。
_SPAWN_DIRTY = (
    "MDCG_TOKEN", "MDCG_TOKEN_FILE", "MDCG_MASTER_KEY", "MDCG_CLEARANCE",
    "MDCG_TENANT", "MDCG_TENANT_REGISTRY",
    "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_LEGACY_ENV_AUTH",
    "MDCG_LEGACY_ENV_ADMIN", "MDCG_SESSION", "DSH_SESSION_ID",
    "MDCG_HARNESS", "MDCG_UNIT", "MDCG_ROOT", "MDCG_STATE_ROOT",
    "MDCG_DATA_ROOT", "MDCG_AUX_ROOT", "MDCG_SUSTAIN", "MDCG_SUSTAIN_NAME",
    "MDCG_MCP_SURFACE", "MDCG_TOOL_FACE", "MDCG_ACTOR",
    "MDCG_VERIFIER_MODULES", "MDCG_HIVE_JOBS", "MDCG_POLICY_FILE",
    "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO",
)


# 生效条件：tmp 为本次隔离根时，返回剔净 _SPAWN_DIRTY 后的 os.environ 副本再注入指向 tmp 的覆盖键（MDCG_ROOT / TENANT_REGISTRY / STATE_ROOT / DATA_ROOT / AUX_ROOT / TOKEN_FILE / MASTER_KEY / SUSTAIN=0 / LEGACY_ENV_AUTH=1 / ACTOR）——子进程零令牌、不落真实数据根。
def _spawn_env(tmp):
    env = {k: v for k, v in os.environ.items() if k not in _SPAWN_DIRTY}
    env["MDCG_ROOT"] = os.path.join(tmp, "cgroot")
    env["MDCG_TENANT_REGISTRY"] = os.path.join(tmp, "_tenants_absent.json")
    env["MDCG_STATE_ROOT"] = os.path.join(tmp, "state")
    env["MDCG_DATA_ROOT"] = os.path.join(tmp, "data")
    env["MDCG_AUX_ROOT"] = os.path.join(tmp, "auxroot")   # 不可取名 "aux"（保留设备名）
    env["MDCG_TOKEN_FILE"] = os.path.join(tmp, "tokens.json")
    env["MDCG_MASTER_KEY"] = "00" * 32
    env["MDCG_SUSTAIN"] = "0"          # 关常驻循环
    env["MDCG_LEGACY_ENV_AUTH"] = "1"  # 既有豁免面：零令牌
    env["MDCG_ACTOR"] = "i43-guard"
    return env


# 当前生效的跨进程变异（仅 --mutation-baseline 期间非 None）：内存 patch 不跨
# 进程，G8-D 走独立子进程 ⇒ 靠 sitecustomize 把同一处定点变异注入子进程。
_MUTATION = [None]

_SITE_SRC = '''# i43 守卫跨进程变异注入（临时件，随 tmp 目录一并回收）
import os
import sys
import inspect
_repo = os.environ.get("I43_REPO") or ""
if _repo and _repo not in sys.path:
    sys.path.insert(0, _repo)
try:
    import md_cg.audit as _A
    _fname = os.environ["I43_MUT_FUNC"]
    _old = os.environ["I43_MUT_OLD"]
    _new = os.environ["I43_MUT_NEW"]
    _src = inspect.getsource(_A.__dict__[_fname])
    exec(compile(_src.replace(_old, _new), "i43_mut.py", "exec"), vars(_A))
    sys.stderr.write("[i43-mut] injected audit.%s\\n" % _fname)
except Exception as _e:
    sys.stderr.write("[i43-mut] inject FAILED: %r\\n" % (_e,))
'''


class _InjectFailed(Exception):
    """跨进程变异注入未生效——子进程那半会静默不设防，故 fail-closed 停手。"""


# 包根（由 __file__ 反推，不经 audit.package_root()——该函数本身是变异靶子
# M2，走它会让「子进程 cwd / 注入源」随变异漂移）。
_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 生效条件：policy_path 为子进程要加载的策略文件、tmp 为隔离根、extra 为追加的 argv 尾巴（缺省空 = 常驻 server 模式、EOF 结束 stdin）时，spawn `python -X utf8 -m md_cg.mcp_server <extra>`（cwd=包根、env=_spawn_env(tmp)），返回 (退出码, stdout, stderr)；仅当 `_MUTATION[0]` 非 None 时另经 sitecustomize 把该变异注入子进程，注入标记缺失即抛 _InjectFailed。
def _talk(policy_path, tmp, extra=(), timeout=180):
    env = _spawn_env(tmp)
    env["MDCG_POLICY_FILE"] = policy_path
    mut = _MUTATION[0]
    if mut is not None:
        sc_dir = os.path.join(tmp, "_mutpath")
        os.makedirs(sc_dir, exist_ok=True)
        with open(os.path.join(sc_dir, "sitecustomize.py"), "w",
                  encoding="utf-8") as f:
            f.write(_SITE_SRC)
        env["PYTHONPATH"] = sc_dir + os.pathsep + env.get("PYTHONPATH", "")
        env["I43_REPO"] = _PKG_ROOT
        env["I43_MUT_FUNC"] = mut["func"]
        env["I43_MUT_OLD"] = mut["old"]
        env["I43_MUT_NEW"] = mut["new"]
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"] + list(extra),
        cwd=_PKG_ROOT, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate("", timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    out, err = out or "", err or ""
    if mut is not None and "[i43-mut] injected" not in err:
        raise _InjectFailed("%s：sitecustomize 注入未生效" % mut["name"])
    return proc.returncode, out, err


# 生效条件：无入参；对 int/bool/str 三种标量键形态各跑 A-F 七条（诊断面不抛且结构化 / 解析面判不可用 / --show-config 恒退出 0（同进程）/ 真进程启动 rc=0 且来源行未缺失 / 真进程 --show-config rc=0 且 available=false / 写入侧 fail-closed 且全库与 inbox 字节面零正文 / op=info 不被拖崩且 write_policy 报不可用），另跑 G 计数非长度、H 消费面纵深、I 形状闸不误伤合法默认策略共 3 条；断言数 24。
def g8():
    _group("G8")
    tmp = tempfile.mkdtemp(prefix="i43_ktype_")
    try:
        for tag, obj in _SCALARS:
            path = _policy_file(tmp, tag, obj)
            with _env(MDCG_POLICY_FILE=path):
                rep, exc = _pr_safe()
                perr = (rep or {}).get("error") or {}
                ok(exc is None and isinstance(rep, dict)
                   and rep.get("available") is False
                   and perr.get("code") == "policy_bad_shape"
                   and bool(perr.get("hint")),
                   "G8-%s A policy_report 恒不抛且报不可用+结构化（code=%s）"
                   % (tag, perr.get("code")))
                rules, src, rerr = audit.resolve_rulebook()
                ok(rules is None and src == "env"
                   and (rerr or {}).get("code") == "policy_bad_shape",
                   "G8-%s B resolve_rulebook 判不可用且不当规则用（rules=%r）"
                   % (tag, rules))
                rc, doc = _show_config_doc()
                pol = doc.get("policy") or {}
                ok(rc == 0 and pol.get("available") is False
                   and ((pol.get("error") or {}).get("code")
                        == "policy_bad_shape"),
                   "G8-%s C --show-config 恒退出 0 且 available=false+code（rc=%s）"
                   % (tag, rc))
                rcp, _out, errtxt = _talk(path, tmp)
                ok(rcp == 0 and "code=policy_bad_shape" in errtxt
                   and "fail-closed" in errtxt,
                   "G8-%s D server 启动 rc=0 且来源行报出 code+fail-closed（rc=%s）"
                   % (tag, rcp))
                # 真进程 `--show-config`：缺陷记录里的 rc=1 + stdout 空 就是这一面
                rcc, sout, _serr = _talk(path, tmp, extra=("--show-config",))
                try:
                    d2 = json.loads(sout.strip().splitlines()[-1])
                except (ValueError, IndexError):
                    d2 = {}
                p2 = d2.get("policy") or {}
                ok(rcc == 0 and p2.get("available") is False
                   and ((p2.get("error") or {}).get("code")
                        == "policy_bad_shape"),
                   "G8-%s C2 真进程 --show-config rc=0 且 available=false+code"
                   "（rc=%s stdout=%d 字节）" % (tag, rcc, len(sout)))
                root = os.path.join(tmp, "root_" + tag)
                cg = _cg(root)
                out = _pipe().execute(cg, {
                    "node_id": "i43_kt_" + tag, "content_kind": "text",
                    "layer": "knowledge",
                    "content": "%s 正文 %s\n" % (MARK, SECRET)})
                ib, rb = _inbox_bytes(root), _root_bytes(root)
                ok(out.get("moved_to") == "policy_unavailable"
                   and out.get("committed") is False
                   and SECRET.encode() not in ib and MARK.encode() not in ib
                   and SECRET.encode() not in rb and MARK.encode() not in rb
                   and not os.path.exists(os.path.join(
                       root, "knowledge", "i43_kt_%s.md" % tag))
                   and SECRET not in json.dumps(out, ensure_ascii=False),
                   "G8-%s E 写入 fail-closed 且 inbox/全库字节面零正文"
                   "（moved_to=%s inbox=%d）"
                   % (tag, out.get("moved_to"), len(ib)))
                # 第三处调用面（op=info）：畸形策略不得把 info 拖崩、也不得
                # 让 write_policy 缺项（诊断面三处调用兜底一并钉死）。
                info = mcp_server.call_tool(cg, "cg", {"op": "info"})
                wp = info.get("write_policy") or {}
                ok(wp.get("available") is False
                   and ((wp.get("error") or {}).get("code")
                        == "policy_bad_shape")
                   and bool(info.get("surface")),
                   "G8-%s F op=info 仍返回正常载荷且 write_policy 报不可用+code"
                   % tag)
        with _env(MDCG_POLICY_FILE=_policy_file(tmp, "str", dict(_SCALARS)["str"])):
            rep_f, _e = _pr_safe()
        ok(rep_f.get("forbidden") == 0 and rep_f.get("forbidden") != len(_STRV)
           and rep_f.get("available") is False,
           "G8-Str G 字符串键未被拆成单字符规则（计数=%s，非长度 %d）"
           % (rep_f.get("forbidden"), len(_STRV)))
        naive = len([r for r in ({"forbidden": _STRV}.get("forbidden") or []) if r])
        st, ev, _det = audit._rule_check("s", {"forbidden": _STRV,
                                               "required": []}, "text")
        ok(st != audit.REJECT and "命中禁止规则" not in str(ev)
           and naive == len(_STRV),
           "G8-Str H 消费面纵深：直喂标量 rules 不按字符建规则（旧写法同输入 ⇒ "
           "%d 条单字符规则）" % naive)
        with open(audit.default_policy_path(), encoding="utf-8") as f:
            dflt = json.load(f)
        ok(audit._policy_shape_error(dflt) is None
           and audit._policy_shape_error({"forbidden": 1}) is not None
           and audit._policy_shape_error({"required": True}) is not None
           and audit._policy_shape_error({"forbidden": _STRV}) is not None
           and audit._policy_shape_error({"required_labels": {"a": 1}}) is not None,
           "G8-I 形状闸不误伤合法默认策略（_comment/_note 是字符串）且标量/对象取值一律报错")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 运行器

_GROUPS = (g1, g2, g3, g4, g5, g6, g7, g8)


def _run_all_silent():
    """静默跑全部组，返回红项清单 [(组名, 断言名)]（供变异核验复用）。

    跨进程注入失效（_InjectFailed）**不吞**：子进程那半会静默不设防，必须让
    变异核验 fail-closed 停手（见 _mutation_baseline）。
    """
    _PASS.clear()
    _FAIL.clear()
    _RED.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        for g in _GROUPS:
            try:
                g()
            except _InjectFailed:
                raise
            except Exception as exc:                      # noqa: BLE001
                _RED.append((_GROUP[0], "组异常：%s: %s" % (type(exc).__name__, exc)))
    return list(_RED)


# 定点变异表：逐条变异生产实现的**源码锚点**，套件必须转红且**恰好**命中声明条数。
# （锚点 = 实现里的字面量；实现改了而本表未同步 → 报 ANCHOR-MISS，退出码 2。）
_MUTATIONS = (
    ("M1 删掉包内默认回落", "audit", "resolve_rulebook",
     "    dflt = default_policy_path()",
     '    dflt = os.path.join(package_root(), "data", "_mutated_missing.json")',
     13, "未设 env 只剩 fail-closed → G1 全 6 条 + G2c + G5a/d/e + G6b/f/h"
         "（G5b/c/f 反而不红：零正文在 fail-closed 下仍成立，正确）"),
    ("M2 定位改为依赖 cwd", "audit", "package_root",
     "    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))",
     "    return os.getcwd()",
     3, "包根随 cwd 漂移 → G2 全组"),
    ("M3 闸门取消策略前置", "writepipe", "_gate_audit",
     "    if perr is not None:",
     "    if False:",
     9, "不可用也继续走旧路（DEFER→propose）→ G3a/b/c/e 与 G4g/h + G8-E×3"
        "（键类型面：int/bool 抛 TypeError 被兜底 except 吞成 DEFER→review_queue，"
        "str 按字符 REJECT）（G3d/f 不红：propose 不落节点、响应体不带正文）"),
    ("M4 显式坏路径回落包内默认", "audit", "resolve_rulebook",
     '        if rules is None:\n            return None, "env", {"code": why[0], "path": explicit,\n                                 "reason": why[1], "hint": POLICY_HINT}',
     '        if rules is None:\n            _dr, _dw = _read_policy_file(default_policy_path())\n            if _dr is not None:\n                return _dr, "package_default", None\n            return None, "env", {"code": why[0], "path": explicit,\n                                 "reason": why[1], "hint": POLICY_HINT}',
     31, "坏路径被包内默认掩蔽 → G4a/b/c/e×2/f/g/h + G6e + G8-A/B/C/E/F×3 + G8-C2×3"
         "（真进程 --show-config） + G8-D×3"
         "（注入子进程后启动面同样变可用）+ G8-G（坏路径面变可用）"
         "（G4d 不红：空 dict 仍走显式分支成功；G8-H/I 不红：直调判据不经来源面）"),
    ("M5 策略读取返回空规则", "audit", "_read_policy_file",
     "    return rules, None",
     "    return {}, None",
     12, "策略文件在但规则被掏空 → G1b/c/d/e/f + G2c + G5 全 6 条"
         "（G1a 不红：来源仍是包内默认，掏空的是内容；G8 不红：形状闸在"
         "该行之前就返回，畸形面走不到这里）"),
    ("M6 启动 stderr 行置空", "mcp_server", "_policy_stderr_note",
     "    rep = rep or {}\n",
     '    rep = rep or {}\n    return ""\n',
     2, "来源不可见 → G6f/g"),
    ("M7 --show-config 不输出", "mcp_server", "_show_config",
     '    sys.stdout.write(json.dumps(doc, ensure_ascii=False) + "\\n")',
     "    pass",
     8, "诊断面哑掉 → G6a/b/c/d/e（a 断言有输出、b/d 解析空 doc、c 判据比对失败）"
        "+ G8-C×3（键类型面同样读不到 available/code）"),
    ("M8 info 不报策略", "mcp_server", "_cg_dispatch",
     '            h["write_policy"] = audit.policy_report()',
     "            pass",
     4, "工具面来源不可见 → G6h + G8-F×3（info 面的 write_policy 键被摘掉）"),
    # —— G8 键类型闸两处定点变异（复核 DEFER 的实据面）——
    ("M9 形状闸失效（键类型面回退）", "audit", "_policy_shape_error",
     "        if key in rules and not isinstance(rules[key], (list, tuple)):",
     "        if False:",
     23, "标量键重新被当可用策略 → G8-A/B/C/E/F×3 + G8-C2×3（诊断面报错码/可用性、解析面、"
         "写入面退回 DEFER→review_queue 或按字符 REJECT、info 面码不对）"
         "+ G8-D×3（经 sitecustomize 注入子进程：int/bool 走 policy_report 兜底 ⇒ "
         "来源行 code 变 policy_report_failed、str 直接报可用）+ G8-G + G8-I"
         "（G8-H 不红：直调消费面不经形状闸）"),
    ("M10 列表取值不做类型闸", "audit", "_policy_list",
     "    return list(v) if isinstance(v, (list, tuple)) else []",
     "    return list(v) if isinstance(v, (list, tuple, str)) else []",
     1, "字符串取值被按字符当规则 → G8-H（消费面纵深那条；其余条不红："
         "形状闸在读取单点已把畸形策略判为不可用，正常路径下消费面碰不到标量）"),
)


def _mutation_baseline() -> int:
    """逐条定点变异核验：套件必须转红且恰好命中声明条数；锚点漂移 → 退出码 2。

    锚点漂移报 ANCHOR-MISS（2）；子进程注入未生效报 INJECT-MISS（2）——两者都是
    fail-closed 停手：前者说明「判据打不红」，后者说明「子进程那半静默不设防」。
    """
    print("!! 变异自证模式：逐条定点变异，套件必须按声明条数转红\n")
    clean = _run_all_silent()
    print("  未变异基线：红项=%d" % len(clean))
    if clean:
        print("  FAIL 未变异即红：", clean)
        return 1
    mods = {"audit": audit, "writepipe": writepipe, "mcp_server": mcp_server}
    bad = []
    for name, modname, fname, old, new, expect, why in _MUTATIONS:
        mod = mods[modname]
        backup = getattr(mod, fname)
        src = inspect.getsource(backup)
        if old not in src:
            print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步本表）" % name)
            return 2
        exec(compile(src.replace(old, new), "<mut:%s>" % name, "exec"), vars(mod))
        # 内存 patch 不跨进程：audit 面变异另注入 sitecustomize，G8-D（真子进程
        # 启动）才有判别力；其余模块（mcp_server/writepipe）不在本守卫的子进程
        # 判据面上，故不注入（避免把「注入」本身变成噪声源）。
        _MUTATION[0] = ({"name": name, "func": fname, "old": old, "new": new}
                        if modname == "audit" else None)
        try:
            red = _run_all_silent()
        except _InjectFailed as exc:
            print("  INJECT-MISS %s —— %s（子进程那半未设防，fail-closed 停手）"
                  % (name, exc))
            return 2
        finally:
            _MUTATION[0] = None
            setattr(mod, fname, backup)
        hit = len(red) == expect
        print("  %s → 红 %d/%d  %s（%s）"
              % (name, len(red), expect, "OK" if hit else "** 与声明不符 **", why))
        if not hit:
            for g, n in red:
                print("       红: [%s] %s" % (g, n))
            bad.append(name)
    print("\n变异自证：%s" % ("PASS（每条变异都恰好命中声明条数）" if not bad
                             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    if "--mutation-baseline" in sys.argv:
        return _mutation_baseline()
    cwd = os.getcwd()
    tmp = tempfile.mkdtemp(prefix="i43_main_")
    try:
        # 统一在包根下运行：G1/G5 的「包内默认」与 cwd 无关的前提被显式固定，
        # G2 再 chdir 到别处证明「不依赖 cwd」（否则断言随调用方 cwd 飘）。
        os.chdir(audit.package_root())
        for g in _GROUPS:
            try:
                g()
            except Exception as exc:                      # noqa: BLE001
                ok(False, "%s 组异常：%s: %s" % (g.__name__, type(exc).__name__, exc))
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nissue #43 默认策略守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
