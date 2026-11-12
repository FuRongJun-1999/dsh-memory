# -*- coding: utf-8 -*-
# 功能名：无 verify 权限的同 id 改写不得把「已验证」带到新正文上（issue #352-B）
# 生效条件：python -X utf8 -m md_cg.test_issue352_vstateinherit；被测面=md_cg/mdcg.py 的 MdCG.add 缺省继承分支（fm[trust.STATE_FIELD] 落值那一步）
# 子功能：B1=无 verify 权限且正文变了 ⇒ 落 doubted（判据主项）；B2/B3/B4/B5=反向对照（正文未变 / 有 verify 权限 / ops 未声明的默认主体 / 无 principal 属性的裸库，四条都必须照旧继承）；B6/B7/B8=源码面与迁移面的在位钉子
# 执行：tempfile 沙箱内直调 MdCGSecure.add / MdCGOS.add / MdCG.add，再回读 frontmatter.verification_state 比对**写死的期望表** _EXPECT
# 验证方式：全部 PASS 即通过（退出码 0；有 FAIL 即退出码 1）。B1..B5 的期望值取自 issue #352 §B 的裁定与 trust.TRANSITIONS（verified→doubted 是既有合法迁移），不由被测实现的返回值回推
# 不适用条件：①不判 #320 的入参闸本身（_require_verify_for_vstate 只看入参，主守卫 md_cg/test_issue320_vstate_requires_verify.py）②不判 doubted 之后的下游失效传播③不判加密库密文字节④不判工具面 mdcg_remember 的取参路径（本件只收口引擎缺省继承这一条路）
"""issue #352-B 守卫：缺省继承验证态时的权限收口。

病象（修前）：MdCG.add 覆写既有节点时 fm 是**全量重建**，缺省把旧
verification_state 原样继承——不带 verification_state 的同 id 改写会把旧节点的
「✓ 已验证」挂到**新正文**上。#320 那条闸（mcp_server._require_verify_for_vstate）
只看**入参**，看不见这条继承路，于是 ops 里没有 verify 的 record 令牌与工具面
mdcg_remember 都能借它把新正文带成「已验证」。

处置（一条判据）：既有态为 verified、**正文真的变了**、且写方无 verify 权限
（Principal.allows_op("verify") 为假，与 #320 同一判据）时，缺省继承落 doubted；
其余照旧继承（既有语义零变化）。

★**过度收紧方向**：本条的修复天然是「加降级」，故 B2/B3/B4/B5 四条专门盯「不该
降的时候必须不降」——正文没变（只改元数据）、写方有 verify 权限、ops 未声明的
默认主体、无 principal 属性的裸库；四条任一转红即说明改过了头。

跑法：python -X utf8 -m md_cg.test_issue352_vstateinherit
"""
from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
import tempfile

# ---- 沙箱：必须在任何 md_cg 子模块 import 之前 -------------------------------
_SANDBOX = tempfile.mkdtemp(prefix="iss352b_guard_")
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "root")
os.environ["MDCG_STATE_ROOT"] = os.path.join(_SANDBOX, "state")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_SANDBOX, "auxstore")
os.environ["MDCG_POLICY_FILE"] = os.path.join(_SANDBOX, "policy.json")
os.environ["MDCG_SUSTAIN"] = "0"
for _k in ("MDCG_SESSION", "DSH_SESSION_ID", "MDCG_DATA_ROOT"):
    os.environ.pop(_k, None)
with open(os.environ["MDCG_POLICY_FILE"], "w", encoding="utf-8") as _f:
    json.dump({"forbidden": ["FORBIDDEN_WORD"], "required": ["PASSED"]}, _f)

from . import trust                                              # noqa: E402
from .mdcg import MdCG                                           # noqa: E402
from .mdcos import MdCGSecure                                    # noqa: E402
from .security import Principal                                  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RUN = [0]

#: **写死的期望表**（判据不自证）：值取自 issue #352 §B 的裁定——「无 verify 权限 +
#: 正文变了 ⇒ doubted」，以及「其余四种写方照旧继承」。这四个字符串不读被测实现的
#: 返回值，也不从实现源码里提取。
_EXPECT = {
    "B1": "doubted",     # 无 verify 权限 + 正文变了
    "B2": "verified",    # 无 verify 权限 + 正文没变（只改元数据）
    "B3": "verified",    # 有 verify 权限 + 正文变了
    "B4": "verified",    # 未传 principal ⇒ 缺省 Principal()，ops 未声明 + 正文变了
    "B5": "verified",    # 无 principal 属性的裸库 + 正文变了
}

_FAILS = []


def _check(name, got, detail=""):
    want = _EXPECT[name]
    if got == want:
        print("  PASS %s  期望=%s 实测=%s" % (name, want, got))
    else:
        print("  FAIL %s  期望=%s 实测=%s  %s" % (name, want, got, str(detail)[:300]))
        _FAILS.append(name)


_BODY_8080 = ("# 功能名：生产库端口\n"
              "# 生效条件：生产环境；2026-10-16 起；端口核对\n"
              "# 子功能：登记连接端点\n"
              "# 执行：核对 manifest 的 ports 段\n"
              "# 验证方式：telnet 8080\n"
              "# 不适用条件：测试环境\n"
              "\n生产库端口为 8080/HTTP\n")
_BODY_9090 = _BODY_8080.replace("8080", "9090")


def _root(tag):
    _RUN[0] += 1
    return os.path.join(_SANDBOX, "%s_r%d" % (tag, _RUN[0]))


def _vstate(cg, nid="n1"):
    return ((cg.get(nid) or {}).get("frontmatter") or {}).get(trust.STATE_FIELD)


def _seed(cg):
    """落一个 verified 节点。前置条件不符即抛，不让用例带病继续。"""
    cg.add("n1", _BODY_8080, layer="knowledge",
           verification_basis="test", verification_state="verified")
    got = _vstate(cg)
    if got != "verified":
        raise AssertionError("前置条件未满足：seed 后回读 verification_state=%r" % (got,))
    return got


def g_b():
    print("== B 组：缺省继承验证态的权限收口（#320 同一判据）==")

    # ① 无 verify 权限的写方 + 正文变了 ⇒ 落 doubted（判据主项）
    cg = MdCGSecure(_root("b1"), autoflush=0,
                    principal=Principal(actor="agent_mallory", role="record",
                                        ops_allow=("info", "write")))
    _seed(cg)
    assert cg.principal.allows_op("verify") is False, "前置条件：record 角色不应带 verify"
    cg.add("n1", _BODY_9090, layer="knowledge", verification_basis="test")
    _check("B1", _vstate(cg))
    cg.close()

    # ② 无 verify 权限但正文没变（只改元数据）⇒ 照旧继承
    cg = MdCGSecure(_root("b2"), autoflush=0,
                    principal=Principal(actor="agent_mallory", role="record",
                                        ops_allow=("info", "write")))
    _seed(cg)
    cg.add("n1", _BODY_8080, layer="knowledge", verification_basis="test",
           tags=["probe"])
    _check("B2", _vstate(cg))
    cg.close()

    # ③ 有 verify 权限的写方 + 正文变了 ⇒ 照旧继承
    cg = MdCGSecure(_root("b3"), autoflush=0,
                    principal=Principal(actor="agent_owner", role="owner",
                                        ops_allow=("*",)))
    _seed(cg)
    assert cg.principal.allows_op("verify") is True, "前置条件：ops_allow=('*',) 应放行 verify"
    cg.add("n1", _BODY_9090, layer="knowledge", verification_basis="test")
    _check("B3", _vstate(cg))
    cg.close()

    # ④ 未传 principal 的加密库（落到缺省 Principal()，ops 未声明）+ 正文变了 ⇒ 照旧继承
    cg = MdCGSecure(_root("b4"), autoflush=0)
    _seed(cg)
    assert cg.principal.allows_op("verify") is True, "前置条件：未声明 ops 应不限制"
    cg.add("n1", _BODY_9090, layer="knowledge", verification_basis="test")
    _check("B4", _vstate(cg))
    cg.close()

    # ⑤ 无 principal 属性的裸库（MdCG 基类）+ 正文变了 ⇒ 照旧继承
    cg = MdCG(_root("b5"), autoflush=0)
    if hasattr(cg, "principal"):
        print("  FAIL B5  前提不成立：MdCG 基类不应带 principal 属性")
        _FAILS.append("B5")
    else:
        _seed(cg)
        cg.add("n1", _BODY_9090, layer="knowledge", verification_basis="test")
        _check("B5", _vstate(cg))
    cg.close()


def g_src():
    print("== 源码面与迁移面的在位钉子（回退即红）==")
    src = inspect.getsource(MdCG.add)
    anchor = 'allows_op("verify")'
    if anchor in src:
        print("  PASS B6  MdCG.add 缺省继承分支仍按 Principal.allows_op(\"verify\") 收口")
    else:
        print("  FAIL B6  MdCG.add 缺省继承分支不再含判据锚点 %s" % anchor)
        _FAILS.append("B6")
    doc = inspect.getdoc(MdCG.add) or ""
    if "例外（issue #352 §B）" in doc:
        print("  PASS B7  MdCG.add docstring 仍声明该例外段")
    else:
        print("  FAIL B7  MdCG.add docstring 缺例外段「例外（issue #352 §B）」")
        _FAILS.append("B7")
    if ("verified", "doubted") in set(trust.TRANSITIONS):
        print("  PASS B8  verified→doubted 是 trust.TRANSITIONS 里的既有合法迁移")
    else:
        print("  FAIL B8  verified→doubted 不在 trust.TRANSITIONS 里")
        _FAILS.append("B8")


def main():
    try:
        g_b()
        g_src()
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    if _FAILS:
        print("-- 读数：红项 %d 条 = %s" % (len(_FAILS), ", ".join(_FAILS)))
        return 1
    print("-- 读数：B1..B8 全 PASS（8/8），红项 0 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
