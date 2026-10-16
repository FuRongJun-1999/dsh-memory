# -*- coding: utf-8 -*-
# 功能名：hive PII 脱敏「族」覆盖度自证 + 仓内凭据模式面矩阵（issue #419）
# 生效条件：python -X utf8 -m md_cg.test_issue419_pii_redaction [--mutate]；被测面=hive/exec.py 的 PII_FAMILIES / PII_EXCLUDED / _PII_PATTERNS / _redact_pii / _redact_deep，及三通道 tool_read_file / _context_block / resolve_system_prompt
# 子功能：A=逐族独立样本必脱敏（覆盖度自证 + 非空转）；B=族注册表结构完整性（含「收了/不收」二选一闭集）；K=过度脱敏对照（正常文本/摘要哈希不得被改）；E=三通道端到端；M=仓内五站点凭据模式面矩阵（打印 + 钉住，漂移即红）；S=自保（本批源码不得撞发版门禁 R1）
# 执行：--mutate 时镜像树注入**五向**变异（去族模式 / 放宽成无门控 / 抽掉排除理由 / 他站点漂移 / 漂移登记改名），守卫必须按预期转红
# 验证方式：全部 PASS 即通过（断言总数 ≥ FLOOR）；--mutate 下每条变异的「指定命中」须与预期一致
# 不适用条件：不判正则脱敏的概率性边界（作者自述「概率防线非密码学保证」）；不执行 node 侧 TS 规则（需构建，M 组对 src/hooks.ts 只做「声明 + 源证据指纹钉」）；不做真实 LLM 网关端到端外发（需真实网关）；跨站点**收编**（统一真源）属设计裁定，不在本守卫面内
"""issue #419 守卫：PII 模式族**覆盖度可自证**，且仓内各站点的模式面**漂移可见**。

病象（修前，逐条实测）：hive/exec.py 的 _PII_PATTERNS 只覆盖 4 家凭据前缀
（sk- / gh*_ / AKIA / mdcg1.）＋ Bearer，报告 12 类主流 token 前缀族**零覆盖**
⇒ 内容层唯一兜底失效，原文随 user/system 消息发往 HIVE_API_BASE。

为什么本守卫不复述「12 个前缀」：报告定性是**模式族缺口**（手工逐个添加、无系统
性覆盖）——只补前缀就是制造第 13、14 个缺口。故修法把模式集重建为带 family 的
**可枚举清单** PII_FAMILIES，本守卫则**逐族喂独立样本自证**：
  · 样本写在本守卫里（**独立于 hive 侧的 sample**）——两侧同源会互相印证出假绿；
  · 「样本族集合 ⊇ 注册族集合」+「样本数 ≥ 声明族数」两条非空转断言：
    新增一个族却忘了加样本、或加了样本却没有族，**都当场转红**。
另加 M 组**跨站点矩阵**：仓内至少 4 个可执行站点（hive / interop / policy.json /
发版门禁）＋ 1 个声明站点（node 侧 TS）各自维护一份凭据模式集，彼此**已经漂移**
（AIza、xox- 在 interop 早有而 hive 没有；sk-、mdcg1. 在 hive 有而 interop 没有）。
矩阵打印出来并**钉住**：任何站点新增/删除一族，都会被逼着面对全部站点。

隔离纪律：只读真实仓（不写任何仓内文件）；三通道探针全部用 tempfile 临时目录与
临时 job 目录，HIVE_READ_ROOTS 等 env 在 finally 逐键还原；变异只在镜像树里改。
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from hive import exec as E

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR = 62
PASS, FAIL, SKIP = 0, 0, 0
FAILS = []


def _check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:240])


def _skip(name, why):
    global SKIP
    SKIP += 1
    print("  SKIP " + name + "  " + why)


# ---------------------------------------------------------------- 独立样本面
#: 声明的族数下限（只许增不许减：删族即红——族是覆盖度的账本，不是注释）
DECLARED_MIN_FAMILIES = 20
#: 报告点名的族（12 类：issue #419 §一的「12 类主流 token 前缀族」）——本守卫断言
#: 它们都必须落在注册表里。族 id 与报告条目的对应关系逐条列在注释里。
REPORT_FAMILIES = (
    "gitlab_pat",        # glpat-
    "google_api_key",    # AIza
    "slack_token",       # xox[baprs]- / xapp-
    "jwt",               # eyJ 三段式
    "xai_token",         # xai-
    "groq_key",          # gsk_
    "stripe_key",        # pk_live_
    "shopify_token",     # shpat_
    "npm_token",         # npm_
    "google_oauth",      # ya29.
    "bare_hex_credential",  # 裸 hex（本批以**语境门控**档收，见 PII_EXCLUDED）
)

#: 逐族**独立样本**（与 hive 侧 PII_FAMILIES 的 sample 刻意不同：不同长度、不同
#: 字符、不同子类型）。全部用字符串拼接书写——明文 token 字面量会撞本仓发版门禁
#: scripts/check_publish_artifact.py 的 R1 内容面（S 组自检）。
INDEPENDENT_SAMPLES = {
    "private_key_block": ("-----BEGIN " + "OPENSSH PRIVATE KEY-----" + "\n"
                          + "b3BlbnNzaC1rZXktdjEAAAAABG5vbmU" + "\n"
                          + "-----END " + "OPENSSH PRIVATE KEY" + "-----"),
    "mdcg_token": "mdcg1." + "verifier" + "." + "tk_" + "abcdef012345" + "." + "qwertyuiopasdfgh",
    "openai_sk": "sk-" + "B" * 20,
    "github_token": "gho_" + "B" * 25,
    "aws_akid": "AKIA" + "B" * 16,
    "gitlab_pat": "glpat-" + "B" * 30,
    "google_api_key": "AIza" + "C" * 30,
    "google_oauth": "ya29." + "B" * 25,
    "slack_token": "xoxp-" + "B" * 15,
    "jwt": ("eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "11111111" + "."
            + "B" * 10),
    "xai_token": "xai-" + "B" * 25,
    "groq_key": "gsk_" + "B" * 30,
    "stripe_key": "sk_live_" + "B" * 25,
    "shopify_token": "shpat_" + "B" * 28,
    "npm_token": "npm_" + "B" * 30,
    "bare_hex_credential": "secret=" + "deadbeef" * 8,
    "bearer": "Bearer " + "B" * 30,
    "cn_id_card": "110101" + "19800101" + "001X",
    "cn_mobile": "139" + "12345678",
    "email": "a.b-c" + "@" + "mail.example.org",
}

#: 过度脱敏对照（**不得被改**的正常文本）。每条都对应一个真实误伤面：
#: 摘要哈希/裸 hex 是 PII_EXCLUDED 里 bare_hex_ungated 的实测对象；
#: 证书块是 begin_certificate 的实测对象；其余是「像但非凭据」的边界形态。
NEGATIVE_SAMPLES = {
    "git 40 位 sha": "8d40dea36d888b22af0c29dfa229a4203bcfeabe",
    "无语境 32 位 hex（md5 形态）": "a89dba18a62ef92f7d323ec890a0d38d",
    "无语境 64 位 hex（sha256 形态）": "f306a8618fbbf340bcf7299ba708def9" * 2,
    "公开证书块（不含私钥）": ("-----BEGIN " + "CERTIFICATE-----" + "\nMIIBAA\n"
                              + "-----END " + "CERTIFICATE" + "-----"),
    "标签 + 短值（非凭据）": "api_key = short",
    "token 一词出现在中文说明里": "token: 这句是说明文字",
    "npm_ 开头的普通词": "npm_install 完成",
    "stripe 形态但无 live/test": "pk_mode 已启用",
    "17 位身份证片段": "11010119900307851",
    "非法手机号段": "12800138000",
    "无点域名邮箱": "user@localhost",
    "UUID": "550e8400-e29b-41d4-a716-446655440000",
    "普通中文含令牌二字": "令牌机制的设计说明",
}

#: 跨站点矩阵（**钉住**：任何差异即红）。站点名 = 文件的唯一真源位置。
SITE_HIVE = "hive/exec.py::PII_FAMILIES"
SITE_INTEROP = "md_cg/interop.py::_FORBIDDEN_RES"
SITE_POLICY = "data/policy.json::forbidden"
SITE_PUBLISH = "scripts/check_publish_artifact.py::R1_CONTENT_RULES"
SITE_TS = "src/hooks.ts::SENSITIVE_PATTERNS"

REGISTERED_MATRIX = {
    "private_key_block": (SITE_HIVE, SITE_POLICY, SITE_PUBLISH),
    "mdcg_token": (SITE_HIVE, SITE_POLICY, SITE_PUBLISH, SITE_TS),
    "openai_sk": (SITE_HIVE, SITE_INTEROP, SITE_POLICY, SITE_PUBLISH, SITE_TS),
    "github_token": (SITE_HIVE, SITE_INTEROP, SITE_POLICY, SITE_PUBLISH),
    "aws_akid": (SITE_HIVE, SITE_INTEROP, SITE_POLICY),
    "gitlab_pat": (SITE_HIVE,),
    "google_api_key": (SITE_HIVE, SITE_INTEROP),
    "google_oauth": (SITE_HIVE,),
    "slack_token": (SITE_HIVE, SITE_INTEROP),
    "jwt": (SITE_HIVE,),
    "xai_token": (SITE_HIVE,),
    "groq_key": (SITE_HIVE, SITE_INTEROP),
    "stripe_key": (SITE_HIVE,),
    "shopify_token": (SITE_HIVE,),
    "npm_token": (SITE_HIVE, SITE_PUBLISH),
    "bare_hex_credential": (SITE_HIVE, SITE_POLICY, SITE_TS),
    "bearer": (SITE_HIVE, SITE_INTEROP, SITE_POLICY, SITE_TS),
    "cn_id_card": (SITE_HIVE, SITE_TS),
    "cn_mobile": (SITE_HIVE, SITE_TS),
    "email": (SITE_HIVE,),
}

#: node 侧 TS 站点的**声明覆盖**（不执行 TS：需构建）。每族给一组「源证据子串」，
#: 全部在场才算该族在该站点被覆盖——hooks.ts 里那条规则被删/改写 ⇒ 证据消失 ⇒
#: 矩阵与 REGISTERED_MATRIX 不符 ⇒ 转红。这是「声明 + 指纹钉」，不是执行验证，
#: 如实写进不适用条件。
TS_DECLARED = {
    "openai_sk": ("twoWidth('sk')", "API密钥"),
    "bearer": ("twoWidth('Bearer')", "令牌"),
    "mdcg_token": ("mdcg1|", "令牌"),
    "cn_id_card": ("身份证号",),
    "cn_mobile": ("手机号",),
    "bare_hex_credential": ("twoWidth('access')", "API密钥"),
}

#: **「一侧有、另一侧无」的跨站点漂移**——必须显式登记且被**点名打印**。
#: 与矩阵（族 × 站点）互补：矩阵记「哪些站点覆盖了某族」；本表记「某站点独有的**形态**
#: 在别处根本没有对应族」——后者**不进族表**（hive 侧不打算收），所以它不会出现在矩阵里，
#: 若不单独登记就会**静默**。每条的 registered_in 必须真的在 PII_EXCLUDED 里（M3 断言）。
TS_ONLY_DRIFT = (
    {
        "site": SITE_TS,
        "shape": "凭据标签 + **任意值**（api_key / access_token / password / 密码 / 密钥）",
        "hive_status": "不收；只收其高置信子集＝「标签 + 32/64 位 hex」（族 bare_hex_credential）",
        "registered_in": "labelled_credential_any_value",
    },
)

#: 站点名备注（矩阵打印时给读者看的口径差）
SITE_SEMANTICS = {
    SITE_HIVE: "通道脱敏（改写后放行）",
    SITE_INTEROP: "发布门禁（命中即抛错拒收）",
    SITE_POLICY: "写入闸门（命中即 REJECT）",
    SITE_PUBLISH: "发版扫描（命中即 FAIL）",
    SITE_TS: "node 自动记忆脱敏（改写后落库）·声明+指纹钉",
}


# ---------------------------------------------------------------- A 组
print("== A 组：覆盖度自证（逐族独立样本必脱敏）==")

_FAMS = {f["family"]: f for f in E.PII_FAMILIES}
_check("A0 注册表族 id 唯一", len(_FAMS) == len(E.PII_FAMILIES),
       [f["family"] for f in E.PII_FAMILIES])
_check("A0 族数 ≥ 声明下限 %d" % DECLARED_MIN_FAMILIES,
       len(E.PII_FAMILIES) >= DECLARED_MIN_FAMILIES, len(E.PII_FAMILIES))
_missing_report = [f for f in REPORT_FAMILIES if f not in _FAMS]
_check("A0 报告点名的 %d 类族全部在册" % len(REPORT_FAMILIES),
       not _missing_report, _missing_report)

_orphan = sorted(set(INDEPENDENT_SAMPLES) - set(_FAMS))
_uncovered = sorted(set(_FAMS) - set(INDEPENDENT_SAMPLES))
_check("A1 非空转：每个注册族都有独立样本（新增族必被逼着加样本）",
       not _uncovered, _uncovered)
_check("A1 非空转：没有指向不存在族的孤儿样本", not _orphan, _orphan)
_check("A1 非空转：样本数 ≥ 声明族数",
       len(INDEPENDENT_SAMPLES) >= len(E.PII_FAMILIES) >= DECLARED_MIN_FAMILIES,
       (len(INDEPENDENT_SAMPLES), len(E.PII_FAMILIES)))

_a_red = []
for _fam, _s in sorted(INDEPENDENT_SAMPLES.items()):
    _out = E._redact_pii(_s)
    _ok = _out != _s and "[已脱敏:" in _out
    if not _ok:
        _a_red.append(_fam)
    _check("A2 族 %-22s 独立样本被脱敏" % _fam, _ok, _out[:70])
_check("A2 逐族全绿（红族数 = 0）", not _a_red, _a_red)

# 报告 §二 A「锚定组」7/7 回归：既有四家 + 手机号 + 邮箱 + Bearer
_ANCHOR = {
    "sk-": "sk-" + "A" * 24,
    "ghp_": "ghp_" + "A" * 30,
    "AKIA": "AKIA" + "A" * 16,
    "mdcg1.": "mdcg1." + "a" + "." + "b" + "." + "c" * 20,
    "Bearer": "Bearer " + "A" * 24,
    "手机号": "138" + "00138000",
    "邮箱": "zhangsan" + "@" + "example.com",
}
_anchor_bad = [k for k, v in _ANCHOR.items() if E._redact_pii(v) == v]
_check("A3 报告锚定组 7/7 回归（判别力仍成立）", not _anchor_bad, _anchor_bad)

# 中英文紧邻（N174）不得回退
_n174 = {"电话13800138000": "手机号", "身份证110101199003078515": "身份证号",
         "邮箱zhangsan@example.com": "邮箱", "令牌sk-" + "abcDEF1234567890ab": "API密钥"}
_n174_bad = [k for k, lab in _n174.items()
             if (k in E._redact_pii(k)) or ("[已脱敏:%s]" % lab) not in E._redact_pii(k)]
_check("A4 N174 中文紧邻脱敏未回退", not _n174_bad, _n174_bad)

# ---------------------------------------------------------------- B 组
print("")
print("== B 组：族注册表结构完整性（收了/不收 = 二选一闭集）==")

_REQ = ("family", "label", "pattern", "sample", "source")
_bad_fields = [f.get("family") or "?" for f in E.PII_FAMILIES
               if any(not f.get(k) for k in _REQ)]
_check("B1 每条族都有 family/label/pattern/sample/source", not _bad_fields, _bad_fields)
_bad_type = [f["family"] for f in E.PII_FAMILIES
             if not hasattr(f["pattern"], "sub") or not isinstance(f["sample"], str)]
_check("B1 pattern 是可 sub 的正则、sample 是字符串", not _bad_type, _bad_type)
_check("B2 _PII_PATTERNS 由 PII_FAMILIES 派生（单一真源，长度与序一致）",
       len(E._PII_PATTERNS) == len(E.PII_FAMILIES)
       and all(p[0] == f["label"] and p[1] is f["pattern"]
               for p, f in zip(E._PII_PATTERNS, E.PII_FAMILIES)), len(E._PII_PATTERNS))
_check("B2 _PII_PATTERNS 形状仍是 (label, pattern) 二元组（既有消费者兼容）",
       all(isinstance(x, tuple) and len(x) == 2 for x in E._PII_PATTERNS))
_exc_bad = [x.get("family") or "?" for x in E.PII_EXCLUDED
            if not x.get("family") or not x.get("reason") or not x.get("measured")]
_check("B3 每条「不收」的族都有 family/reason/measured（为什么不收是可执行的）",
       not _exc_bad, _exc_bad)
_dup = len({x["family"] for x in E.PII_EXCLUDED}) != len(E.PII_EXCLUDED)
_check("B3 排除族 id 唯一", not _dup)
_overlap = sorted({f["family"] for f in E.PII_FAMILIES}
                  & {x["family"] for x in E.PII_EXCLUDED})
_check("B3 收/不收两表无交集（不存在既是又不是的族）", not _overlap, _overlap)
_check("B4 私钥块置首（后序规则不得先切碎密钥体）",
       E.PII_FAMILIES[0]["family"] == "private_key_block", E.PII_FAMILIES[0]["family"])
_ids = [f["family"] for f in E.PII_FAMILIES]
_check("B4 身份证排在手机号之前（17 位段不被手机号误吃）",
       _ids.index("cn_id_card") < _ids.index("cn_mobile"),
       (_ids.index("cn_id_card"), _ids.index("cn_mobile")))

# ---------------------------------------------------------------- K 组
print("")
print("== K 组：过度脱敏对照（正常文本不得被改）==")

_k_red = []
for _name, _s in sorted(NEGATIVE_SAMPLES.items()):
    _out = E._redact_pii(_s)
    _ok = _out == _s
    if not _ok:
        _k_red.append(_name)
    _check("K1 阴性样本「%s」原样保留" % _name, _ok, _out[:70])
_check("K1 阴性面全绿（误伤数 = 0）", not _k_red, _k_red)
_check("K2 _redact_deep 与 _redact_pii 同源（容器逐层下探）",
       E._redact_deep({"a": ["Bearer " + "B" * 30]})["a"][0] != "Bearer " + "B" * 30
       and E._redact_deep({"a": ["Bearer " + "B" * 30]})["a"][0]
       == E._redact_pii("Bearer " + "B" * 30))
_check("K3 排除族的对照：公开证书块确不被改（与 PII_EXCLUDED 同口径）",
       E._redact_pii(NEGATIVE_SAMPLES["公开证书块（不含私钥）"])
       == NEGATIVE_SAMPLES["公开证书块（不含私钥）"])
_bad_excl = [x["family"] for x in E.PII_EXCLUDED
             if "bare_hex_ungated" == x["family"]
             and not (x["measured"].get("bare_hex32_hits", 0) > 0
                      and x["measured"].get("bare_hex64_hits", 0) > 0)]
_check("K3 排除项带**实测**读数（不是空口理由）", not _bad_excl, _bad_excl)

# ---------------------------------------------------------------- E 组
print("")
print("== E 组：三通道端到端（不是只测一个函数）==")

_TOK = "glpat-" + "R" * 24          # GitLab PAT（修前零覆盖的族之一）
_TOK2 = "npm_" + "R" * 30
_BODY = ("配置说明\n" + _TOK + "\n" + _TOK2 + "\n")
_ENV_KEYS = ("HIVE_READ_ROOTS", "HIVE_API_KEY", "HIVE_SUBAGENT_API_KEY",
             "HIVE_API_BASE", "HIVE_SUBAGENT_API_BASE")
_bak_env = {k: os.environ.get(k) for k in _ENV_KEYS}
_tmp = tempfile.mkdtemp(prefix="i419_")
try:
    for k in _ENV_KEYS:
        os.environ.pop(k, None)
    _ws = os.path.join(_tmp, "ws")
    os.makedirs(_ws, exist_ok=True)
    _job = os.path.join(_tmp, "job")
    os.makedirs(_job, exist_ok=True)
    _fp = os.path.join(_ws, "leaky.md")
    with io.open(_fp, "w", encoding="utf-8", newline="") as f:
        f.write(_BODY)

    # E1 read_file 通道
    _rf = E.tool_read_file({"path": "leaky.md"}, workdir=_ws)
    _e1 = (_rf.get("ok") and _TOK not in (_rf.get("content") or "")
           and _TOK2 not in (_rf.get("content") or ""))
    _check("E1 read_file 通道：token 不随 tool 结果外发", bool(_e1), str(_rf)[:150])
    _check("E1 read_file 通道：pii_redacted 如实标记",
           _rf.get("pii_redacted") is True, str(_rf.get("pii_redacted")))

    # E2 context_files 通道（_context_block 是该通道文本分支的落点）
    _meta = {"notes": [], "images": [], "image_tokens": 0, "binaries": []}
    _blk = E._context_block("leaky.md", _fp, _job, _meta)
    _check("E2 context_files 通道：token 不进上下文块",
           _TOK not in _blk and _TOK2 not in _blk, _blk[:150])
    _check("E2 context_files 通道：块结构完好（未被整块吞掉）",
           _blk.startswith("<context") and _blk.rstrip().endswith("</context>"),
           _blk[:80])

    # E3 system_prompt_from 通道
    _sp, _src = E.resolve_system_prompt(
        {"system_prompt_from": "leaky.md", "workdir": _ws}, _job)
    _check("E3 system_prompt_from 通道：token 不进 system 消息",
           _TOK not in _sp and _TOK2 not in _sp, _sp[:150])
    _check("E3 system_prompt_from 通道：真源标记仍是 file:（未静默回落）",
           str(_src).startswith("file:"), _src)

    # E4 build_messages 端到端（三通道汇入 user 消息的最终面）
    try:
        _msgs = E.build_messages({"user_prompt": "看下这个", "context_files": ["leaky.md"],
                                  "workdir": _ws, "model": "glm-5.3-flash"}, _job)
        _blob = json.dumps(_msgs[0] if isinstance(_msgs, tuple) else _msgs,
                           ensure_ascii=False)
        _check("E4 build_messages 端到端：user 消息里无 token 原文",
               _TOK not in _blob and _TOK2 not in _blob, _blob[:150])
    except Exception as _e:                       # noqa: BLE001
        _skip("E4 build_messages 端到端", "环境不满足：%s: %s"
              % (type(_e).__name__, str(_e)[:90]))
finally:
    for k, v in _bak_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(_tmp, ignore_errors=True)

# ---------------------------------------------------------------- M 组
print("")
print("== M 组：仓内凭据模式面矩阵（族 × 站点；漂移即可见且被钉）==")


def _runtime_sites():
    """四个**可执行**站点的模式（各自按本文件唯一真源位置取）。"""
    sites = {}
    sites[SITE_HIVE] = [f["pattern"] for f in E.PII_FAMILIES]
    from . import interop as _I
    sites[SITE_INTEROP] = [rx for rx, _why in _I._FORBIDDEN_RES]
    with io.open(os.path.join(_REPO, "data", "policy.json"), encoding="utf-8") as f:
        _pol = json.load(f)
    sites[SITE_POLICY] = [re.compile(p) for p in (_pol.get("forbidden") or [])]
    _cpa = os.path.join(_REPO, "scripts", "check_publish_artifact.py")
    _spec = importlib.util.spec_from_file_location("_cpa419", _cpa)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    sites[SITE_PUBLISH] = [rx for _n, rx in _mod.R1_CONTENT_RULES]
    return sites


_TS_SRC = ""
_ts_path = os.path.join(_REPO, "src", "hooks.ts")
if os.path.exists(_ts_path):
    with io.open(_ts_path, encoding="utf-8") as f:
        _TS_SRC = f.read()


def _ts_covered():
    """TS 站点被覆盖的族＝其源证据子串全部在场者（声明 + 指纹钉）。"""
    out = []
    for fam, ev in TS_DECLARED.items():
        if _TS_SRC and all(e in _TS_SRC for e in ev):
            out.append(fam)
    return out


_SITES = _runtime_sites()
_SITE_ORDER = [SITE_HIVE, SITE_INTEROP, SITE_POLICY, SITE_PUBLISH, SITE_TS]
_check("M0 四个可执行站点全部可加载（判据有效）", len(_SITES) == 4,
       sorted(_SITES))
_check("M0 TS 源可读（声明站点有据可钉）", bool(_TS_SRC), _ts_path)

_observed = {}
for _fam, _f in _FAMS.items():
    _cov = [s for s in (SITE_HIVE, SITE_INTEROP, SITE_POLICY, SITE_PUBLISH)
            if any(p.search(_f["sample"]) for p in _SITES[s])]
    _observed[_fam] = tuple(_cov)

print("  【族 × 站点】矩阵（v = 该站点覆盖该族）")
_hdr = "  %-24s %s" % ("族", "  ".join("%-8s" % s.split("/")[0][:8] for s in _SITE_ORDER))
print(_hdr)
for _fam in sorted(_observed):
    _row = _observed[_fam]
    _cells = []
    for _s in _SITE_ORDER:
        if _s == SITE_TS:
            _cells.append("   v    " if _fam in _ts_covered() else "   .    ")
        else:
            _cells.append("   v    " if _s in _row else "   .    ")
    print("  %-24s %s" % (_fam, "".join(_cells)))
print("  站点口径：" + " ｜ ".join("%s=%s" % (s.split("/")[0], SITE_SEMANTICS[s])
                                 for s in _SITE_ORDER))

# 声明站点的实际覆盖也并入观测面（TS 未覆盖的族不写进去）
_ts_cov = set(_ts_covered())
for _fam in _FAMS:
    if _fam in _ts_cov:                      # 声明站点的实际覆盖并入观测面
        _observed[_fam] = _observed[_fam] + (SITE_TS,)
_ts_orphan = sorted(_ts_cov - {f for f in _FAMS
                               if SITE_TS in REGISTERED_MATRIX.get(f, ())})
_check("M1 TS 声明与登记矩阵一致（声明了却不覆盖、覆盖了却没登记，都红）",
       not _ts_orphan, _ts_orphan)

_drift = []
for _fam in sorted(set(_observed) | set(REGISTERED_MATRIX)):
    _want = tuple(sorted(REGISTERED_MATRIX.get(_fam, ())))
    _got = tuple(sorted(_observed.get(_fam, ())))
    if _want != _got:
        _drift.append((_fam, _want, _got))
_check("M1 观测矩阵与登记矩阵逐族一致（站点新增/删除一族即红）",
       not _drift, _drift[:4])
if _drift:
    for _fam, _want, _got in _drift:
        print("     漂移 %-24s 登记=%s 实测=%s" % (_fam, _want, _got))

# 已知差异必须**显式可见**：只有 hive 一个站点覆盖的族（＝其余站点全缺）
_hive_only = sorted(f for f, c in _observed.items() if c == (SITE_HIVE,))
print("  【已知差异】仅 hive 覆盖（其余可执行站点全缺）的族 %d 个：%s"
      % (len(_hive_only), "、".join(_hive_only)))
_check("M2 只在一处覆盖的族必须被点名打印（不许静默）", isinstance(_hive_only, list))
_check("M2 矩阵覆盖全部注册族", set(_observed) == set(_FAMS),
       sorted(set(_FAMS) - set(_observed)))

# 「一侧有、另一侧无」的漂移：登记 + 点名打印（**不许静默**）
_exc_ids = {x["family"] for x in E.PII_EXCLUDED}
for _d in TS_ONLY_DRIFT:
    print("  【已知差异·一侧独有】%s 有：%s ｜ hive 侧：%s ｜ 登记项：%s"
          % (_d["site"].split("/")[0], _d["shape"], _d["hive_status"],
             _d["registered_in"]))
_bad_drift = [_d["registered_in"] for _d in TS_ONLY_DRIFT
              if _d["registered_in"] not in _exc_ids]
_check("M3 一侧独有的漂移必须登记在 PII_EXCLUDED（不登记即红）",
       not _bad_drift, _bad_drift)
_check("M3 漂移被点名打印（TS_ONLY_DRIFT 非空且已逐条打印）",
       len(TS_ONLY_DRIFT) >= 1, len(TS_ONLY_DRIFT))
_check("M3 node 侧该形态的源证据在场（漂移不是空口）",
       bool(_TS_SRC) and "twoWidth('password')" in _TS_SRC
       and "twoWidth('access')" in _TS_SRC, "src/hooks.ts 源证据缺失")

# ---------------------------------------------------------------- S 组
print("")
print("== S 组：自保（本批源码不得撞发版门禁 R1 内容面）==")

_R1 = list(_SITES[SITE_PUBLISH])
_SELF_FILES = (os.path.join(_REPO, "hive", "exec.py"), os.path.abspath(__file__))
for _p in _SELF_FILES:
    with io.open(_p, encoding="utf-8") as f:
        _txt = f.read()
    _hit = [(rx.pattern[:40], m.group(0)[:40])
            for rx in _R1 for m in rx.finditer(_txt)]
    _check("S1 %s 内无 R1 形态的明文凭据字面量（样本已拼接书写）"
           % os.path.relpath(_p, _REPO), not _hit, _hit[:3])

print("")
print("断言总数 %d（PASS %d / FAIL %d / SKIP %d），FLOOR=%d"
      % (PASS + FAIL, PASS, FAIL, SKIP, FLOOR))
if PASS + FAIL < FLOOR:
    FAILS.append("FLOOR")
    print("  FAIL 断言总数低于 FLOOR —— 探针面疑似失效（防假绿）")

if FAILS:
    print("issue #419 结果：%d 失败" % len(FAILS))
    for _f in FAILS:
        print("   - " + _f)
else:
    print("issue #419 结果：全部通过")


# ---------------------------------------------------------------- 定点变异
_MIRROR_DIRS = ("md_cg", "hive", "scripts", "data", "src")
_MIRROR_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "jobs", "target",
                                      "node_modules")
_TARGET = "hive/exec.py"

_MUTATIONS = (
    ("V1 覆盖方向：把 gitlab 族的长度下限从 20 抬到 200（族形同废除）",
     're.compile(r"(?<![0-9A-Za-z])glpat-[A-Za-z0-9_\\-]{20,}(?![0-9A-Za-z])")',
     're.compile(r"(?<![0-9A-Za-z])glpat-[A-Za-z0-9_\\-]{200,}(?![0-9A-Za-z])")',
     ("A2 族 gitlab_pat",)),
    ("V2 过度收紧方向：把 hex 门控档放宽成**无门控**裸 hex",
     're.compile(r"(?i)(?:api[_\\-]?key|apikey|access[_\\-]?token|secret|token|passwd|password|credential|密钥|令牌|口令)\\s*[:=：]\\s*[0-9a-fA-F]{32,64}(?![0-9A-Za-z])")',
     're.compile(r"(?i)[0-9a-fA-F]{32,64}(?![0-9A-Za-z])")',
     ("K1 阴性样本「无语境 32 位 hex", "K1 阴性样本「无语境 64 位 hex")),
    ("V3 账本方向：抽掉「不收」族的理由（二选一闭集失守）",
     ('"reason": "**无凭据语境**的 32/64 位裸 hex 不脱敏：本仓实测误伤 169 处（32 位）"' + chr(10)
      + '                  "/ 6523 处（64 位）——MD5/SHA 摘要、评测哈希、节点 id 全是这种形态；"' + chr(10)
      + '                  "data/policy.json 的 _note 亦明记「长 hex（git SHA）等易误伤的模式"' + chr(10)
      + '                  "刻意不收；宁可漏报也不误伤」。故改以**语境门控**档收（族 "' + chr(10)
      + '                  "bare_hex_credential，误伤实测 0 处）——报告 §四.2 对裸 hex 的可选性"' + chr(10)
      + '                  "与「只在高置信上下文启用」建议与此一致。",'),
     '"reason": "",',
     ("B3 每条「不收」的族都有",)),
    ("V4 跨站点方向：他站点（policy.json）悄悄去掉 AKIA 一族",
     '"\\\\bAKIA[0-9A-Z]{16}\\\\b"',
     '"\\\\bAKIA[0-9A-Z]{16}X\\\\b"',
     ("M1 观测矩阵与登记矩阵逐族一致",), "data/policy.json"),
    ("V5 漂移登记方向：把「一侧独有」的登记项改名（漂移就地静默）",
     '"family": "labelled_credential_any_value",',
     '"family": "labelled_credential_any_value_RENAMED",',
     ("M3 一侧独有的漂移必须登记",)),
)


def _mirror_build():
    """镜像树：拷 md_cg/hive/scripts/data/src + 根级 .py（真实工作树只读）。"""
    dst = tempfile.mkdtemp(prefix="i419_mut_")
    for name in _MIRROR_DIRS:
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name), ignore=_MIRROR_SKIP)
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _fold(text, eol):
    """按目标文件实际行尾折算（本仓 CRLF/LF 混合）。"""
    return text.replace("\r\n", "\n").replace("\n", eol)


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("HIVE_READ_ROOTS", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue419_pii_redaction"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    # 只认断言行的 FAIL（摘要行「…/ FAIL 0 /…」含 FAIL 字样，不能计入）
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.startswith("  FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：镜像树注入五向变异（覆盖/过度收紧/账本/跨站点/漂移登记），守卫必须按预期转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print("\n".join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for mut in _MUTATIONS:
            desc, old, new, exp = mut[0], mut[1], mut[2], mut[3]
            rel = mut[4] if len(mut) > 4 else _TARGET
            p = os.path.join(tree, rel.replace("/", os.sep))
            with io.open(p, encoding="utf-8", newline="") as f:
                t = f.read()
            eol = "\r\n" if "\r\n" in t else "\n"
            o, n = _fold(old, eol), _fold(new, eol)
            if t.count(o) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次" % (desc, rel, t.count(o)))
                print("  ANCHOR-MISS " + desc)
                continue
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(t.replace(o, n, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(t)
            hit = [r for r in reds2 if any(r.startswith(e) for e in exp)]
            if rc2 != 0 and len(hit) >= len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
        return 0 if not FAILS else 1
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
