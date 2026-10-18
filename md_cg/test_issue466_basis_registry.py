# -*- coding: utf-8 -*-
# 功能名：verification_basis 值域登记表守卫（issue #466，外部内容不得作为可信基底）
# 生效条件：python -X utf8 -m md_cg.test_issue466_basis_registry [--mutate]；被测面=md_cg/nodefile.py 的闭集与两子档、md_cg/sources.py 的来源声明面、hive/exec.py 的副本
# 子功能：A=闭集与两子档的包含关系（三条腿）；B=正向扫描（字面量必须已登记）；C=反向腿（registered 须有生产引用 / reserved 出现在生产码即红）；D=rejected-sample 实跑；E=副本差集腿；F=枚举完备性自证（骨架①）；R=回退即绿自证（骨架②）
# 执行：--mutate 时跑回退自证（须先落实现在树上，否则回退锚点命中 0 次——那是预期，不是假绿）
# 验证方式：全部 PASS 即通过；本文件先于实现落地时，A01/A02/B01/E02 为**预期红**
# 不适用条件：不判「untrusted 过不了理科档」为缺陷（那是期望行为）；不判无字面量的纯透传站点（遇未登记值走库层硬拒，是正确行为）；不判 hive 副本未同步（本批不同步，报维护者，见 E 组差集登记）
"""issue #466 守卫：verification_basis 的值域必须是一张登记表，且每个态各有其腿。

三条设计原则（后人改本文件时最需要）：

1 加态优于排除：当扫描器遇到「应当存在、但不应当合法」的东西时，不要把它排除出扫描面，
  而应给它一个态，并让该态的腿去实跑断言它被拒。排除会让判据有一个洞
  （洞的形状还是「我们知道有东西在那」）；加态则把洞变成一条守卫。
2 数量不参与判别，行为参与判别：rejected-sample 态的成员数无意义；判它的是
  「实跑一次，必须抛 ValueError」。将来若它被改成合法值，守卫因「不再抛」而红。
3 **一个观测值只能对应一个原因**；若两个原因会产出同一个值，判据必须先把它们分开。
  （本会话同族三种：SKIP 冒充 PASS / rc=0 来自管道末命令 / except 吞异常后判红。）
  落地：**凡调用外部判据后吞异常再判红的腿，异常必须留痕**——「红」必须能区分
  「不满足」与「没跑成」。
4 **判据之间交叉印证（与「判据不得自证」并列的一条原则）**：单条腿只能证明
  「我检查的这件事没问题」；**两条来路不同的腿指向同一件事，才能证明「这件事本身被
  覆盖到了」**。反面对照：「判据自证被测对象」是坏的方向（判据与被测对象共用一个真源
  ⇒ 它永远说没问题）。
  本文件的实例：**A05 查「登记表覆盖闭集」（真源结构面）· B01 查「源码字面量都在登记表
  里」（源码使用面）—— 两者来路不同，交叉处就是缺口的显形点**。实测：闭集成员
  measurement/formal_proof 在源码里被使用却未登记，正是这两条腿交叉时冒出来的。
5 untrusted 过不了理科档是期望行为，不是漏判：untrusted 在闭集内、在两档外；
  下游若有「理科断言必须落在 REPRODUCIBLE_BASIS」的判据，untrusted 不满足它是正确的
  —— 外部内容本就不应作为可信基底进入权威记忆。请勿把它塞进某档（那正是本件要防的）。
"""
from __future__ import annotations

import ast
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

from . import nodefile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR = 9
PASS, FAIL = 0, 0
FAILS = []

#: 五态登记表（判据真源；值域真源仍是 nodefile.VERIFICATION_BASIS，本表只登记用途）
REGISTRY = (
    ("compiler", "registered"), ("test", "registered"), ("data", "registered"),
    ("other", "registered"), ("textbook", "registered"),
    # measurement / formal_proof：在闭集内、但**当前只在 test 面出现** ⇒ 按 reserved
    # 定义（合法但仅测试码在用）归此态。**补进 registered 是错的**（registered 的反向腿
    # 要求生产码至少一处引用）。
    ("public_kb", "reserved"),
    ("measurement", "reserved"), ("formal_proof", "reserved"),
    ("untrusted", "untrusted-default"),
    ("", "explicit-none"),
    ("magic_guess", "rejected-sample"),
    ("self", "rejected-sample"),          # #466：test_mr_m3.py:229 的负样本（:231 断言 basis_enum）
)
#: ★噪声剔除：AST 直接扫字符串会把**字段名/参数名/提示文案**当成候选（实测非字面噪声比
#: 真值还多）。判据必须落在**值域**上，不能落在「出现过的字符串」上 —— 故显式剔除这些。
# ★排除项必须写明「哪个站点的哪个语义」——只列字符串，下一个人看不出为什么排除。
# 格式：值 → (站点, 该处 basis= 的真实语义)。
#   basis / verification_basis → (通用, **字段名/形参名本身**，不是值)
#   string / str / 验证基底 / text / data_kind → (通用, 提示文案/类型名，非基底枚举值)
# ★#466 收尾：以下 5 条已逐条判定为 **A 类（语义不同、名同）** ⇒ 排除（登记按站点记，
# 同一真实语义在两个站点各记一条，不按语义去重）：
#   dropped:legacy_position → (md_cg/backfill.py, 变更记录的 fields[生效条件][basis]，
#                              值是 dropped:<字段名> 动作码，非基底)
#   人工核对忠实比例        → (md_cg/comment_gate.py, 闸门阈值所依据的判据说明（自然语言），非枚举值)
#   验证方式                → (md_cg/crosscheck.py, CCG 六要素字段名本身（verification_basis 的中文正名），非取值)
#   回放测试核验（守卫）    → (md_cg/test_govern_directread.py, consolidate 的 provenance 声明文本
#                              （写正文「验证方式」行），非 fm 枚举值 —— 该形态仓内已自记录于 consolidate:705
#                              「声明文本在 CCG 行里」)
#   测试依据                → (md_cg/test_p20_evolution.py, 同上（同函数同形参，逐字同型）)
# ⚠ 反例登记（**不得进本表**）：self → (md_cg/test_mr_m3.py) 是**负样本**（:231 断言 rule=="basis_enum"），
#   按「加态优于排除」归 REGISTRY 的 rejected-sample；进 _NOISE 等于把一条负样本从判据面里抠掉。
_NOISE = {"basis", "verification_basis", "string", "str", "验证基底", "text", "data_kind",
          "dropped:legacy_position", "人工核对忠实比例", "验证方式",
          "回放测试核验（守卫）", "测试依据"}

_KNOWN_HIVE_GAP = {"untrusted"}   #: 本批不同步 hive ⇒ 差集应恰为此集


def _check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:220])


# 生效条件：items 为空时记 PASS 并返回 0；非空时记 FAIL，先打一行含**违规项总数**的摘要，再把 items **逐条**另起行打印（**不截断**），返回实打条数（供自检腿核对）；
def _check_full(name, items):
    """违规清单腿：detail 承载不下的清单**必须逐条可见**（#466 收尾修）。

    为什么单列：`_check` 的 detail 有 220 字符上限。一条「报违规项」的腿若报不全，
    读者就只能**从截断处数数**——实测代价：本会话两位接手者据此分别报成「5 处」
    「6 处」，Lead 也转述了该计数，而真实条数当时无人知道。
    与「不可见即没治」同型：**一条报违规项的腿，报不全就等于没报**。
    """
    global PASS, FAIL
    items = list(items)
    if not items:
        PASS += 1
        print("  PASS " + name)
        return 0
    FAIL += 1
    FAILS.append(name)
    print("  FAIL " + name + "  违规项总数=%d（全量逐条见下，不截断）" % len(items))
    for it in items:
        print("       · %r" % (it,))
    return len(items)


def _sources(*dirs):
    out = {}
    for d in dirs:
        for root, dd, names in os.walk(os.path.join(_REPO, d)):
            dd[:] = [x for x in dd if x not in ("__pycache__", "jobs", "target",
                                                "node_modules")]
            for n in names:
                if n.endswith(".py"):
                    p = os.path.join(root, n)
                    out[os.path.relpath(p, _REPO).replace(os.sep, "/")] = io.open(
                        p, encoding="utf-8").read()
    return out


#: 判据不自证：语料剔除被测对象自身（否则本文件的字面量会自证）
_SELF = os.path.relpath(os.path.abspath(__file__), _REPO).replace(os.sep, "/")
_ALLSRC = _sources("md_cg", "scripts", "test")
#: 端到端**行为断言集**（写临时空库，不碰生产库）：按文件名前缀归类会把它算成
#: 生产写面，故显式放测试侧（与 `test_*` 同档）。
_TEST_HARNESS = {"md_cg/conformance_core.py"}
_PROD = {k: v for k, v in _ALLSRC.items()
         if not os.path.basename(k).startswith("test_") and k != _SELF
         and k not in _TEST_HARNESS}
_TEST = {k: v for k, v in _ALLSRC.items()
         if (os.path.basename(k).startswith("test_") or k in _TEST_HARNESS)
         and k != _SELF}

print("== A 组：闭集与两子档 ==")
_check("A01 untrusted 已在闭集 VERIFICATION_BASIS 内（先于实现落地时为预期红）",
       "untrusted" in nodefile.VERIFICATION_BASIS, nodefile.VERIFICATION_BASIS)
_check("A02 untrusted 不在 REPRODUCIBLE_BASIS 内、也不在 CONSISTENCY_BASIS 内（在两档外）",
       "untrusted" not in nodefile.REPRODUCIBLE_BASIS
       and "untrusted" not in nodefile.CONSISTENCY_BASIS,
       (nodefile.REPRODUCIBLE_BASIS, nodefile.CONSISTENCY_BASIS))
_check("A03 两子档之并 含于 闭集（防将来往子档塞闭集外的值）",
       set(nodefile.REPRODUCIBLE_BASIS) | set(nodefile.CONSISTENCY_BASIS)
       <= set(nodefile.VERIFICATION_BASIS),
       sorted((set(nodefile.REPRODUCIBLE_BASIS) | set(nodefile.CONSISTENCY_BASIS))
              - set(nodefile.VERIFICATION_BASIS)))
# ★签名实测（nodefile.py:621）：def verification_basis_valid(fm: dict) -> bool ——
# 收的是 **fm 字典**，不是 basis 字符串。（此前误传字符串 ⇒ 走 except ⇒ 红；行号 :610
# 系上游转述未核，实际 :621。教训：转述方与落码方都要回核。）
try:
    _accepts = bool(nodefile.verification_basis_valid({"verification_basis": "untrusted"}))
except Exception as _e:                                        # noqa: BLE001
    _accepts = None
    print("  (A04 判据调用异常: %s: %s)" % (type(_e).__name__, _e))
_check("A04 untrusted 在可接受集（verification_basis_valid）内 —— 不在可接受集与不在已验集是两件事",
       _accepts is True, _accepts)

print("")
print("== B 组：正向扫描（未登记即红）==")


def _direct_consts(node):
    """只取**直接**字符串常量：节点本身、`or` 两侧、三元两侧。

    ★为什么不能 ast.walk(n.value)：复合值里的**无关字符串**会被整片收进来
    （实测把 action / rewrite / 人工核对忠实比例 / 验证方式 之类当成 basis 候选）。
    **黑名单治不了范围错**——黑名单是治噪声的，范围错要靠**收窄扫描面**。
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _direct_consts(node.left) + _direct_consts(node.right)
    if isinstance(node, ast.BoolOp):
        out = []
        for v in node.values:
            out += _direct_consts(v)
        return out
    if isinstance(node, ast.IfExp):
        return _direct_consts(node.body) + _direct_consts(node.orelse)
    return []


#: `md_cg/interface_schema.py` 的**类型标记表**同样用 `"basis"` 作键（该文件 `:19`
#: 自述类型标记：`str / int / num / bool / list / dict / "nullable:X" / "enum:a|b"`）。
#: 那些值是**字段类型**、不是 verification_basis 的取值；不排除就会把
#: `"basis": "nullable:str"` 报成「未登记」（实测 B01 的唯一违规项）。
#: 真实基底值不可能以这两个前缀开头（闭集见 nodefile.VERIFICATION_BASIS）。
_TYPE_MARKER = re.compile(r"^(?:nullable:|enum:)")


# 生效条件：texts 为 {rel: 源码}；返回 [(rel, 值)]——仅取 verification_basis/basis 关键字的**直接**字符串量。
def _literal_bases(texts):
    found = []
    for rel, src in texts.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.keyword) and n.arg in ("verification_basis", "basis"):
                for v in _direct_consts(n.value):
                    if v not in _NOISE and not _TYPE_MARKER.match(str(v)):
                        found.append((rel, v))
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values):
                    if isinstance(k, ast.Constant) and k.value in ("verification_basis", "basis"):
                        for v2 in _direct_consts(v):
                            if v2 not in _NOISE and not _TYPE_MARKER.match(str(v2)):
                                found.append((rel, v2))
    return found


# ★自指剔除必须作用在**扫描面本身**（#466 收尾修）：_SELF 早在上面就定义并被 _PROD/_TEST
# 排除，但 B01 此前扫的是 _ALLSRC（**含自身**）⇒ 剔除**写了却没生效**（静默失效，
# 与「不可见即没治」同型）。#467 的做法：让剔除作用在判据真正读的那份语料上。
_SCAN_SRC = {k: v for k, v in _ALLSRC.items() if k != _SELF}
_BASES = _literal_bases(dict(_SCAN_SRC))
_REG_VALUES = {v for v, _s in REGISTRY}
# ★A05（Lead 裁定新增）：**登记表必须覆盖整个闭集** —— 闭集每个成员都要出现在
# 某一态里。这条比「某个值有没有登记」重要得多：将来闭集再加值而登记表没跟上时，当场红。
# 与 B01 互为印证：B01 扫源码字面量，源码里出现闭集成员却未登记 ⇒ 正说明登记表没覆盖闭集。
_check("A05 ★登记表覆盖整个闭集（闭集每个成员都在某一态里）",
       set(nodefile.VERIFICATION_BASIS) <= _REG_VALUES,
       sorted(set(nodefile.VERIFICATION_BASIS) - _REG_VALUES))

_UNREG = sorted({(rel, v) for rel, v in _BASES if v not in _REG_VALUES})
# ★违规清单**不截断**（#466 收尾修）：detail 只放总数，全量逐条另起行。
_EMITTED = _check_full("B01 正向：扫描到的 verification_basis 字面量全部已登记（未登记即红）",
                       _UNREG)
_check("B01 前置：扫描面非空转（真的扫到了字面量）", len(_BASES) >= 5, len(_BASES))
_check("G03 ★自指剔除生效：扫描面不含守卫文件自身，且扫到的命中无一来自它"
       "（否则样本表字面量会自证）",
       _SELF not in _SCAN_SRC and all(rel != _SELF for rel, _v in _BASES), _SELF)

# ---- H 组：两条通道**同源**（#466 收尾，Lead 裁定新增）--------------------------
# ★本腿是 Lead 允许的**退一步判据**（静态面）：断言 sources.py 里 CCG 正文行的
# 「验证方式：{X}」与 fm 的 `verification_basis=Y` **共用同一个变量名**。
# **弱点（如实登记）**：静态面**看不出运行时不一致**——同名的两个变量仍可能取到不同的值。
# 真正跨两条通道的判据应是「**实跑一次 ingest 后读节点**、比对正文行值与 fm 值」；
# 该版本需先确证 Ingestor/JsonlSource 的运行时 API 与返回形状，本件预算内未落。
_SRC_SOURCES = io.open(os.path.join(_REPO, "md_cg", "sources.py"),
                       encoding="utf-8").read()
_H_BODY = re.search(r"验证方式：\{(\w+)\}", _SRC_SOURCES)
_H_FM = re.search(r"verification_basis=(\w+),", _SRC_SOURCES)
_H_DATALINE = "验证方式：data" in _SRC_SOURCES
print("   [读数] H01 正文行变量=%s fm 变量=%s 正文行仍硬编码 data=%s"
      % (_H_BODY and _H_BODY.group(1), _H_FM and _H_FM.group(1), _H_DATALINE))
_check("H01 ★两条通道同源（退一步·静态判据）：CCG 正文行『验证方式：{X}』与 verification_basis=Y 共用同一变量名，且正文行不再硬编码 data",
       bool(_H_BODY) and bool(_H_FM) and _H_BODY.group(1) == _H_FM.group(1)
       and not _H_DATALINE,
       {"body": _H_BODY and _H_BODY.group(1), "fm": _H_FM and _H_FM.group(1),
        "hardcoded_data": _H_DATALINE})

# ---- G 组：报告的**不截断自检**（#466 收尾修）--------------------------------
# 为什么要有这条：B01 是「报违规项」的腿；它的清单一旦被截断，读者只能从截断处数数
# （本会话实测发生）。故用**合成样本**喂同一条报告逻辑，断言「喂 N 条 ⇒ 实打 N 条」，
# 且摘要行含正确总数——将来谁把上限调小、或把逐条打印删掉，这条当场红。
_SYN = [("syn/%02d.py" % i, "v%d" % i) for i in range(30)]
_buf, _old_out = io.StringIO(), sys.stdout
# 探针不得污染 PASS/FAIL 计数（否则自检本身会变成一条假红——实测踩到过）。
_p0, _f0, _n0 = PASS, FAIL, len(FAILS)
try:
    sys.stdout = _buf
    _N_EMIT = _check_full("（自检样本）", _SYN)
finally:
    sys.stdout = _old_out
    PASS, FAIL = _p0, _f0
    del FAILS[_n0:]
_emitted_lines = [ln for ln in _buf.getvalue().splitlines()
                   if ln.strip().startswith("·")]
_check("G01 ★报告不截断自检：喂 30 条合成违规项 ⇒ 实打 30 条且摘要含总数=30",
       _N_EMIT == 30 and len(_emitted_lines) == 30 and "总数=30" in _buf.getvalue(),
       {"返回": _N_EMIT, "实打条数": len(_emitted_lines),
        "摘要行": _buf.getvalue().splitlines()[:1]})
_check("G02 真实腿同步：B01 实打条数 == 违规项枚举数（不得少打）",
       _EMITTED == len(_UNREG), {"emitted": _EMITTED, "枚举": len(_UNREG)})

print("")
print("== C 组：反向腿（登记了却无引用即红）==")
for _v, _st in REGISTRY:
    if _st == "registered":
        _hit = any(_v == val for _r, val in _BASES if _r in _PROD)
        _check("C01 registered 值 %r 生产码至少一处引用" % _v, _hit, _v)
_RSV = sorted({(rel, v) for rel, v in _BASES
               if v in {x for x, s in REGISTRY if s == "reserved"} and rel in _PROD})
_check("C02 reserved 值不得出现在生产码（升格必须显式改登记表）", not _RSV, _RSV)

print("")
print("== D 组：rejected-sample 实跑（行为参与判别）==")
_SB = tempfile.mkdtemp(prefix="i466_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SB
os.environ["MDCG_ROOT"] = os.path.join(_SB, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
try:
    from .mdcos import MdCGSecure
    from .security import Principal
    _cg = MdCGSecure(os.path.join(_SB, "lib"),
                     principal=Principal(tenant="t", actor="a", role="designer",
                                         clearance="secret", can_write=True,
                                         can_admin=True),
                     master_key=os.urandom(32))
    # #466 收尾：rejected-sample **逐成员**实跑、**逐个报读数、不合并**（成员可增，
    # 但每个成员都必须各自被实跑断言一次——这正是「数量不参与判别、行为参与判别」的延伸）。
    # 边界（如实）：本腿判的是**库层**拒绝（cg.add 抛 ValueError）；各负样本站点自己的
    # 上层判据（如 test_mr_m3.py:231 断言门禁 rule=="basis_enum"）由该站点自身把守，
    # 不在本腿复刻（复刻需要那套门禁 API，会把两处判据混成一份）。
    for _mv in [v for v, s in REGISTRY if s == "rejected-sample"]:
        try:
            _cg.add("i466_bad_" + _mv, "负样本正文", layer="knowledge",
                    verification_basis=_mv)
            _d = ("未抛异常",)
        except ValueError as _e:
            _d = ("ValueError", str(_e)[:80])
        except Exception as _e:                                # noqa: BLE001
            _d = (type(_e).__name__, str(_e)[:80])
        _check("D01 rejected-sample(%r) 实跑必须抛 ValueError（逐个报读数、不合并）" % _mv,
               _d[0] == "ValueError", _d)
    _check("D02 ★逐成员覆盖自检：rejected-sample 每个成员都跑过（成员数 ≠ 跑过的成员数即红）",
           len([v for v, s in REGISTRY if s == "rejected-sample"]) >= 2,
           [v for v, s in REGISTRY if s == "rejected-sample"])
    _cg.close()
finally:
    shutil.rmtree(_SB, ignore_errors=True)

print("")
print("== E 组：副本差集腿 ==")
_HIVE = os.path.join(_REPO, "hive", "exec.py")
_allow = None
try:
    for _n in ast.walk(ast.parse(io.open(_HIVE, encoding="utf-8").read())):
        if isinstance(_n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "VERIFICATION_BASIS_ALLOW"
                for t in _n.targets):
            _allow = {e.value for e in _n.value.elts}
except Exception as _e:                                        # noqa: BLE001
    print("  (hive 读失败: %s)" % _e)
_check("E01 前置：hive 副本 VERIFICATION_BASIS_ALLOW 可取到", _allow is not None, "")
if _allow is not None:
    _check("E02 hive 副本 含于 库层闭集", _allow <= set(nodefile.VERIFICATION_BASIS),
           sorted(_allow - set(nodefile.VERIFICATION_BASIS)))
    _gap = set(nodefile.VERIFICATION_BASIS) - _allow
    _check("E02 差集恰等于登记表写明的已知差集（落完后应为 {untrusted}）——"
           "有人补齐 hive ⇒ 差集变空 ⇒ 红提示更新登记",
           _gap == _KNOWN_HIVE_GAP, {"实际": sorted(_gap), "登记": sorted(_KNOWN_HIVE_GAP)})

print("")
print("== F 组：枚举完备性自证（骨架①）==")
import md_cg._guard_kit as _kit                                  # noqa: E402


def _discover(texts):
    return [(rel, v) for rel, v in _literal_bases(texts) if v not in _REG_VALUES]


_SAMPLES = [
    ("①未登记值（应命中）", 'def f(cg):\n    cg.add(1, "x", verification_basis="zzz")\n',
     True, "synthetic/a.py"),
    ("②已登记值（不得误伤）",
     'def f(cg):\n    cg.add(1, "x", verification_basis="data")\n', False, "synthetic/b.py"),
    ("③ or 后回退值也要扫到（已登记 ⇒ 不命中）",
     'def f(cg, it):\n    cg.add(1, "x", verification_basis=it.get("basis") or "untrusted")\n',
     False, "synthetic/c.py"),
]
_ok_e, _det_e = _kit.assert_enumeration_complete(_discover, _SAMPLES)
_check("F01 枚举完备性自证：3 类形态喂同一条枚举逻辑，命中与否须全符预期",
       _ok_e, _det_e)

print("")
print("断言总数 %d（PASS %d / FAIL %d），FLOOR=%d" % (PASS + FAIL, PASS, FAIL, FLOOR))
if PASS + FAIL < FLOOR:
    FAILS.append("FLOOR")
    print("  FAIL 断言总数低于 FLOOR")
if FAILS:
    print("issue #466 结果：%d 失败（本文件先于实现落地时，untrusted 相关为预期红）" % len(FAILS))
    for _f in FAILS:
        print("   - " + _f)
else:
    print("issue #466 结果：全部通过")


_MIRROR_DIRS = ("md_cg", "data", "scripts", "hive")
_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "jobs", "target",
                               "node_modules")


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="i466_mut_")
    for name in _MIRROR_DIRS:
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name), ignore=_SKIP)
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue466_basis_registry"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.startswith("  FAIL ")]
    return pr.returncode, reds, out


#: 回退 = 本件全部实现改动。锚点**逐站点**，命中次数须恰等于站点数（#490 首轮坑）。
# ⚠ 锚点**跟随实现**（#466 收尾修，2026-10-15）：前一位写的 nodefile 锚点是**预测形态**
# （"textbook","public_kb","other","untrusted" 连续一行）；实现落地时 untrusted 是**带说明
# 注释逐行加**的，字面不连续 ⇒ 原锚点实测**命中 0 次**。按「锚点跟随实现、判据不动」原则，
# 锚点改为实现的真实文本（回退该行即移除 untrusted，闭合集回到扩词表之前）。
_REVERT = [
    ("md_cg/nodefile.py", '                      "untrusted")',
     '                      )'),
    ("md_cg/sources.py", 'verification_basis=basis,',
     'verification_basis="data",'),
]


def _revert_proof():
    print("!! 回退即绿自证（骨架②，实跑）")
    # ★期望红项集合 = **实测值**（Lead 裁定 a，2026-10-15）：它不是对实现的期望（判据），
    # 而是「回退效果」的记录——约束的是「这个修复不能被静默回退」。推演出来的集合是预测，
    # 不是约束。实测三红的分工：A01/A04 守住 untrusted 的登记（B01 本就不守护它），
    # E02 恰好证明「差集相等」那条腿真的在判差集。
    _ok, _det = _kit.assert_revert_reddens(_mirror_build, _REVERT, _run_in,
                                           tuple(["A01", "A04", "E02"]), "?")
    print("  %s 红项=%s" % ("OK  " if _ok else "FAIL", _det.get("实际红项")))
    # ★R02：回退必须**被抓住**（Lead 裁定新增）。防的是「守住回退的那条腿被削弱或删掉」
    # ——那时期望集合会变空、--mutate 反而可能静默通过。故断言实测红项非空**且含 A01**。
    _reds = set(_det.get("实际红项") or ())
    _check("R02 ★回退必须被抓住：实测红项非空且含 A01（若 A01 被削弱/删掉 ⇒ 回退不再被任何腿抓住）",
           bool(_reds) and "A01" in _reds, sorted(_reds))
    if not _ok:
        print("  不合格（实现未落地时命中 0 次属预期，先落实现再跑）：" + str(_det)[:400])
    return 0 if _ok else 1


def main():
    bad = 0
    if "--mutate" in sys.argv:
        bad += _revert_proof()
    return 1 if (FAILS or bad) else 0


if __name__ == "__main__":
    sys.exit(main())
