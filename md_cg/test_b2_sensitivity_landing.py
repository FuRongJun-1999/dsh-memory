# -*- coding: utf-8 -*-
# 功能名：B2 密级「声明 → 落盘」透传与 fail-closed 闸守卫（cg(op=write) 端到端）
# 生效条件：writepipe._executor 的 cg.add 实参表带 sensitivity（:543）、
#           mcp_server.mdcg_remember 两分支带 sensitivity（:3199 / :3213）、
#           库层 md_cg.mdcg._check_sensitivity_landing（:1079）接线在
#           MdCG._write_node（:2609）时；
#           沙箱条件：MDCG_ROOT / MDCG_AUX_ROOT / MDCG_MASTER_KEY / MDCG_POLICY_FILE
#           全部指向 tempfile.mkdtemp 建的独立目录，绝不触在役库。
# 子功能：① cg(op=write, sensitivity='private') 落盘：frontmatter sensitivity 就是
#           private，且落盘正文不是明文（AEAD 密文、盘上文件不含明文）；
#         ② 声明加密级却落盘明文 → fail-closed 拒绝（判据直调 + 写面端到端两路）；
#         ③ 同族旁路：mdcg_remember 非 gated 分支的透传（第二处落盘面）。
# 执行：python -X utf8 -m md_cg.test_b2_sensitivity_landing
#       （cwd = 仓库根；不带参数、无网络、无外部依赖，全程沙箱）
# 验证方式：本文件自跑（自带断言计数与退出码 rc=0/1）；定点变异自证见文件尾
#           `--drop-fix`（抽掉 writepipe._executor 的 sensitivity 透传 → 本守卫必红）。
# 不适用条件：情感交互｜闲聊｜纯查询无改动；
#             无密封能力实例（基类 MdCG / MdCGOS）落 private 明文是**既有语义**
#             （fm 如实记 private、读面按密级隔离），不在本闸判据② 面内——已由
#             B2-B6 显式钉住，防把闸误扩到「无加密能力的库」。
"""B2 守卫：密级声明在落盘面是否被透传，以及「声明加密级却明文落盘」的 fail-closed。

缺陷（修复前）：
  writepipe 链尾执行器的 `cg.add` 实参表**缺 sensitivity**，而同文件
  `_gate_audit` 的 payload 带着它交给审核闸——两面口径分叉：审核闸按调用方
  声明的密级判、落盘闸按 DEFAULT_SENSITIVITY 回落 internal，于是声明 private
  的正文以**明文 + fm internal** 落盘（纯漏传，无任何失败信号）。

本守卫的判别力锚点（每条断言都可定点变异）：
  A 组 cg(op=write, sensitivity='private') 端到端：fm=private + 正文密文 + 盘上无明文。
  B 组 fail-closed：声明 private 而落盘 internal（闸①）/ 加密级却明文（闸②）
       一律 ValueError 且**未落盘**；合规面与「无密封能力实例」放行（防误扩）。
  C 组 mdcg_remember 非 gated 分支（第二处落盘面）同款透传。

沙箱（硬约束）：一切读写都在 tempfile.mkdtemp 内；跑完 rmtree。绝不碰在役库。
"""
import json
import os
import shutil
import sys
import tempfile

# 沙箱必须在**任何** md_cg 子模块 import 之前设好（`crypto.MASTER_FILE` 在模块
# 导入时求值）。
_SANDBOX = tempfile.mkdtemp(prefix="b2sens_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SANDBOX
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
_POLICY = os.path.join(_SANDBOX, "policy.json")
with open(_POLICY, "w", encoding="utf-8") as _f:      # audit 闸 ACCEPT 面
    json.dump({"forbidden": [], "required": ["B2MARK"]}, _f)
os.environ["MDCG_POLICY_FILE"] = _POLICY
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)

from . import crypto, mdcg, mcp_server, nodefile            # noqa: E402
from .mdcos import MdCGSecure                               # noqa: E402
from .security import Principal                             # noqa: E402

_KEK = os.urandom(32)
_MARK = "B2MARK 私有正文：银行卡尾号 8888，仅本人可见"
_OK = 0
_BAD = []


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _principal():
    return Principal(tenant="t1", actor="alice", role="designer",
                     clearance="secret", can_write=True, can_admin=True)


def _mk_secure(tag):
    root = os.path.join(_SANDBOX, "lib_" + tag)
    return MdCGSecure(root, principal=_principal(), master_key=_KEK), root


def _raw(cg, nid):
    """读节点盘上原文（不经解密），返回 (text, fm, content)。"""
    e = cg.index["nodes"][nid]
    with open(cg._node_disk_path(e), encoding="utf-8") as f:
        text = f.read()
    fm, content = nodefile.loads(text)
    return text, fm, content


def main():
    print("\n[B2-A] cg(op=write, sensitivity='private') 端到端落盘")
    cg_a, _root_a = _mk_secure("A")
    res = mcp_server._dispatch(cg_a, "cg",
                               {"op": "write", "content_kind": "text",
                                "content": _MARK, "sensitivity": "private"})
    nid_a = res.get("id") or ""
    _check("B2-A1 写面回执 committed（未被审核队列吞掉）",
           res.get("ok") is True and res.get("committed") is True,
           repr(res)[:140])
    if nid_a and nid_a in cg_a.index["nodes"]:
        raw_a, fm_a, content_a = _raw(cg_a, nid_a)
        _check("B2-A2 落盘 frontmatter sensitivity == 声明值 private",
               fm_a.get("sensitivity") == "private",
               "fm sensitivity=%r" % fm_a.get("sensitivity"))
        _check("B2-A3 落盘正文不是明文（AEAD 密文）",
               crypto.is_encrypted(content_a), str(content_a)[:40])
        _check("B2-A4 盘上文件不含明文标记",
               "B2MARK" not in raw_a and "8888" not in raw_a, raw_a[:60])
        readback = (cg_a.get(nid_a) or {}).get("content") or ""
        _check("B2-A5 有权限读面读回明文（加密存储不损可读性）",
               _MARK in readback, readback[:40])
    else:
        _check("B2-A2 落盘 frontmatter sensitivity == 声明值 private", False,
               "未落盘 id=%r" % nid_a)

    print("\n[B2-B] 声明加密级却落盘明文 → fail-closed 拒绝")
    dek = crypto.provision_dek(_SANDBOX, _KEK, "t1", "alice")
    sealed = crypto.seal_node("payload", dek, "n1", "t1", "alice")
    try:
        mdcg._check_sensitivity_landing("n1", "internal", "private", "明文")
        _check("B2-B1 闸①：声明 private 而落盘 internal → ValueError", False,
               "未抛")
    except ValueError as exc:
        msg = str(exc)
        _check("B2-B1 闸①：声明 private 而落盘 internal → ValueError",
               "声明值='private'" in msg and "sensitivity='internal'" in msg
               and "未写盘" in msg, msg[:110])
    try:
        mdcg._check_sensitivity_landing("n1", "private", "private", "明文", True)
        _check("B2-B2 闸②：加密级密级 + 有密封能力却明文 → ValueError", False,
               "未抛")
    except ValueError as exc:
        _check("B2-B2 闸②：加密级密级 + 有密封能力却明文 → ValueError",
               "明文落盘" in str(exc), str(exc)[:110])
    ok_pass = None
    try:
        mdcg._check_sensitivity_landing("n1", "private", "private", sealed, True)
        mdcg._check_sensitivity_landing("n1", "internal", None, "明文", True)
        ok_pass = True
    except Exception as exc:                                # noqa: BLE001
        ok_pass = repr(exc)
    _check("B2-B3 合规面放行（密文 private / 明文 internal）", ok_pass is True,
           repr(ok_pass)[:110])

    # 端到端：密封点被绕过的实例（覆写了密封钩子却不密封）经写面写入 → 拒绝
    class _LeakySecure(MdCGSecure):
        def _seal_content(self, node_id, content, sensitivity=None):
            return content                                  # 故意不密封

    leak = _LeakySecure(os.path.join(_SANDBOX, "lib_leak"),
                        principal=_principal(), master_key=_KEK)
    err_e = None
    try:
        mcp_server._dispatch(leak, "cg",
                             {"op": "write", "content_kind": "text",
                              "content": _MARK, "sensitivity": "private"})
    except ValueError as exc:
        err_e = str(exc)
    _check("B2-B4 写面端到端：密封点被绕过 + 声明 private → ValueError",
           err_e is not None and "明文落盘" in err_e, repr(err_e)[:130])
    leak_md = []
    for _d, _subs, _fs in os.walk(os.path.join(_SANDBOX, "lib_leak")):
        leak_md += [os.path.join(_d, f) for f in _fs if f.endswith(".md")]
    _check("B2-B5 闸命中时未落盘（盘上无任何节点文件）", not leak_md,
           "leak 库 .md=%s index=%s" % (leak_md[:3],
                                        list(leak.index["nodes"])[:4]))

    # 无密封能力的实例（基类 MdCG）：private 明文是既有语义，不得误伤
    base_root = os.path.join(_SANDBOX, "lib_base")
    base = mdcg.MdCG(base_root, autoflush=1)
    err_f = None
    try:
        base.add("b2_base_priv", _MARK, layer="knowledge",
                 sensitivity="private")
    except Exception as exc:                                # noqa: BLE001
        err_f = "%s: %s" % (type(exc).__name__, str(exc)[:90])
    if err_f is None:
        raw_f, fm_f, content_f = _raw(base, "b2_base_priv")
        _check("B2-B6 无密封能力实例（基类）：private 明文落盘放行（不误伤）",
               fm_f.get("sensitivity") == "private"
               and not crypto.is_encrypted(content_f),
               "fm=%r enc=%s" % (fm_f.get("sensitivity"),
                                 crypto.is_encrypted(content_f)))
    else:
        _check("B2-B6 无密封能力实例（基类）：private 明文落盘放行（不误伤）",
               False, err_f)
    base.close()

    print("\n[B2-C] 第二处落盘面：mdcg_remember 非 gated 分支透传")
    cg_c, _root_c = _mk_secure("C")
    res_c = mcp_server._dispatch(cg_c, "mdcg_remember",
                                 {"content": _MARK + " remember 分支",
                                  "content_kind": "text",
                                  "sensitivity": "private"})
    nid_c = res_c.get("id") or ""
    _check("B2-C1 remember 面回执 ok", res_c.get("ok") is True,
           repr(res_c)[:120])
    if nid_c and nid_c in cg_c.index["nodes"]:
        raw_c, fm_c, content_c = _raw(cg_c, nid_c)
        _check("B2-C2 remember 面落盘 fm sensitivity == private",
               fm_c.get("sensitivity") == "private",
               "fm sensitivity=%r" % fm_c.get("sensitivity"))
        _check("B2-C3 remember 面落盘正文为密文",
               crypto.is_encrypted(content_c), str(content_c)[:40])
    else:
        _check("B2-C2 remember 面落盘 fm sensitivity == private", False,
               "未落盘 id=%r" % nid_c)

    print("\n==== B2 密级落盘守卫：%d 通过%s ====" % (
        _OK, "，%d 失败：%s" % (len(_BAD), "; ".join(_BAD)) if _BAD else ""))
    return 1 if _BAD else 0


if __name__ == "__main__":
    try:
        _rc = main()
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(_rc)
