# -*- coding: utf-8 -*-
# 功能名：身份观察面的 role 类型闸（issue #418 **第二入口**）
# 生效条件：python -X utf8 -m md_cg.test_issue418_identity_role_type_gate [--mutate]；被测面=**mdcg_identity / cg(op=identity) 的 observe 分支**（mcp_server._identity_call）
# 子功能：A=工具面端到端（非法 role 硬拒且零落盘；合法/缺省可读回=回执即事实）；B=第二入口同一点覆盖（cg op=identity）+**源码面**「闸仍在」（防闸被删守卫还绿）；C=与 mdcg_remember 面的回执键集/错误码一致；R=判据单点置恒真后实跑转红
# 执行：--mutate 时把 nodefile.valid_role 临时置恒真（等价于移除该闸）再实跑 A/B，红项须含两条行为腿
# 验证方式：全部 PASS 即通过；--mutate 下回退后红项须含 A1 与 B1（实跑，不接受推演）
# 不适用条件：不判 mdcg_remember 面的 role 闸（已有 test_issue418_role_type_gate.py 覆盖，**不重复**）；不判 cg(op=write) 的 role（writepipe 通路，另案）；不判其它非法类型的具体文案（只判 role_not_str 这一码）
"""issue #418 **第二入口**守卫：身份观察面的非法 role 必须在写入前被拒。

病象（修前实测，HEAD dd8a9640）：`_identity_call` 的 observe 分支把 `role` 直传
`cg.identity_observe`，而 role 类型闸只装在 `mdcg_remember` 分支 ⇒
`mdcg_identity(action=observe, role=[1,2,3])` 回执 `{"ok": true, "node_id": …}`、
节点**已落盘**，下次装载被自家装载器判 frontmatter 损坏而**隔离**
（不进索引、get/search 读不到）——与 #418 主帖逐字同形，只是入口不同。

修法：在 `_identity_call` 的 observe 分支紧邻写入前加**同一单点判据**
`nodefile.valid_role`，回执取协议声明的 `gate_hard_reject` 形态
（WRITE_TRIO + gate/error/verdict/hint，verdict=None 盲区声明），与 remember 面逐键对齐。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="i418b_")
os.environ.update({"MDCG_ROOT": os.path.join(_TMP, "brain"),
                   "MDCG_STATE_ROOT": os.path.join(_TMP, "state"),
                   "MDCG_AUX_ROOT": os.path.join(_TMP, "auxstore"),
                   "MDCG_DATA_ROOT": os.path.join(_TMP, "datastore"),
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_MASTER_KEY": "ab" * 32,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0", "MDCG_AUTONOMY": "full"})
from md_cg import autonomy_modes as am, mcp_server, nodefile      # noqa: E402
os.environ[am.AUTONOMY_ENV_KEYS["mode"]] = "full"
from md_cg.mdcos import MdCGSecure                                # noqa: E402
from md_cg.security import Principal                              # noqa: E402

FAILS, _PASSED = [], [0]
_SB = os.path.join(_TMP, "lib")


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        _PASSED[0] += 1
    else:
        print("  FAIL " + name + ("  · " + str(detail) if detail else ""))
        FAILS.append(name)


def _cg():
    return MdCGSecure(_SB, principal=Principal(
        role="designer", actor="i418b", clearance="secret", can_write=True, can_admin=True,
        layers_allow=("knowledge",), ops_allow=("read", "write", "identity", "info")),
        autoflush=1)


def _files_with(mark):
    out = []
    for dp, _dn, fns in os.walk(_SB):
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                if mark in io.open(p, encoding="utf-8", errors="replace").read():
                    out.append(os.path.relpath(p, _SB).replace("\\", "/"))
            except OSError:
                pass
    return out


def leg_A():
    """端到端：非法 role 硬拒 + 零落盘；合法/缺省受理且可读回。"""
    print("\n[A 端到端 · mdcg_identity 工具面]")
    cg = _cg()
    r_bad = mcp_server._dispatch(cg, "mdcg_identity",
                                 {"action": "observe", "subject_id": "user:x",
                                  "content": "行证 R418B_BAD", "role": [1, 2, 3]})
    cg.flush()
    print("   非法 role 回执 =", json.dumps(r_bad, ensure_ascii=False, default=str)[:190])
    _check("A1 非法 role ⇒ ok=false 且 error==role_not_str",
           (r_bad or {}).get("ok") is not True and (r_bad or {}).get("error") == "role_not_str", r_bad)
    _check("A2 非法 role ⇒ 回执形态含 gate/verdict 两键（gate_hard_reject）",
           (r_bad or {}).get("gate") == "role_type" and "verdict" in (r_bad or {}), r_bad)
    landed_bad = _files_with("R418B_BAD")
    _check("A3 非法 role ⇒ **零落盘**（盘面无该正文）", not landed_bad, landed_bad)

    r_ok = mcp_server._dispatch(cg, "mdcg_identity",
                               {"action": "observe", "subject_id": "user:x",
                                "content": "行证 R418B_OK", "role": "user"})
    r_def = mcp_server._dispatch(cg, "mdcg_identity",
                                {"action": "observe", "subject_id": "user:x",
                                 "content": "行证 R418B_DEF"})
    cg.flush()
    nid_ok = (r_ok or {}).get("node_id")
    _check("A4 合法 role 受理且读得回（回执即事实）",
           bool(r_ok and r_ok.get("ok") and nid_ok and cg.get(nid_ok)), r_ok)
    nid_def = (r_def or {}).get("node_id")
    _check("A5 缺省 role（省略）受理且读得回",
           bool(r_def and r_def.get("ok") and nid_def and cg.get(nid_def)), r_def)
    cg.close()


def leg_B():
    """第二入口同一点覆盖 + 源码面「闸仍在」。"""
    print("\n[B 另一入口 cg(op=identity) + 源码面]")
    cg = _cg()
    r = mcp_server._dispatch(cg, "cg", {"op": "identity", "action": "observe",
                                        "subject_id": "user:y", "content": "行证 R418B_CG",
                                        "role": {"a": 1}})
    cg.flush()
    print("   cg(op=identity) 非法 role 回执 =",
          json.dumps(r, ensure_ascii=False, default=str)[:190])
    _check("B1 cg(op=identity) 入口同样硬拒（同一单点覆盖两入口）",
           (r or {}).get("ok") is not True and (r or {}).get("error") == "role_not_str", r)
    _check("B2 cg(op=identity) 入口同样零落盘", not _files_with("R418B_CG"), _files_with("R418B_CG"))
    cg.close()

    src = io.open(os.path.join(_REPO, "md_cg", "mcp_server.py"), encoding="utf-8").read()
    m = re.search(r"if act == \"observe\":(.*?)\n    if act == \"trait\":", src, re.S)
    body = m.group(1) if m else ""
    _check("B3 源码面：observe 分支内仍有 valid_role 判据（防「闸被删而守卫还绿」）",
           "valid_role" in body and "role_not_str" in body, body[:120])
    _check("B4 源码面：判据取的是单点 nodefile.valid_role（不另写第二份类型判据）",
           "nodefile" in body and "isinstance" not in body, body[:120])


def leg_C():
    """与 remember 面回执形态一致（同一判据 ⇒ 同一错误码与键集）。"""
    print("\n[C 与 mdcg_remember 面回执对齐]")
    cg = _cg()
    a = mcp_server._dispatch(cg, "mdcg_remember", {"node_id": "pn418b", "content":
                                                  "# 功能名：x\n# 生效条件：c\n# 子功能：s\n"
                                                  "# 执行：e\n# 验证方式：v\n# 不适用条件：n\n正文：x",
                                                  "layer": "knowledge", "role": [1, 2, 3]})
    b = mcp_server._dispatch(cg, "mdcg_identity", {"action": "observe", "subject_id": "user:z",
                                                  "content": "行证 R418B_ALIGN", "role": [1, 2, 3]})
    cg.close()
    keys_a = set((a or {}).keys()) & {"gate", "error", "got_type", "hint"}
    keys_b = set((b or {}).keys()) & {"gate", "error", "got_type", "hint"}
    print("   remember 键集 =", sorted(keys_a), "| identity 键集 =", sorted(keys_b))
    _check("C1 两面同错误码 role_not_str",
           (a or {}).get("error") == "role_not_str" == (b or {}).get("error"), (a, b))
    _check("C2 两面键集一致（gate/error/got_type/hint）", keys_a == keys_b, (keys_a, keys_b))


def leg_R():
    """--mutate：把判据单点置恒真（等价于移除该闸）后**实跑**，行为腿必须转红。"""
    print("\n[R 变异自证：判据置恒真]")
    orig = nodefile.valid_role
    try:
        nodefile.valid_role = lambda x: True
        before = len(FAILS)
        leg_A()
        leg_B()
        regressed = len(FAILS) - before
        print("  [R] 判据置恒真后新增红项 = %d" % regressed)
        _check("R1 判据被移除后实跑转红（A1/B1 在红项内）", regressed >= 2, "新增=%d" % regressed)
    finally:
        nodefile.valid_role = orig


def main():
    mutate = "--mutate" in sys.argv
    print("=" * 72)
    print("md 认知图 · issue #418 第二入口守卫 · 身份观察面的 role 类型闸")
    print("沙箱 =", _TMP, "| mutate =", mutate)
    print("=" * 72)
    leg_A()
    leg_B()
    leg_C()
    if mutate:
        leg_R()
    print("\n" + ("全部 PASS（%d 项）" % _PASSED[0] if not FAILS
                  else "FAIL %d 项：%s" % (len(FAILS), FAILS)))
    shutil.rmtree(_TMP, ignore_errors=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
