# -*- coding: utf-8 -*-
"""issue #211 守卫：导出落点的第二道约束（link/export 与 op=export 不得写进密钥库/层目录/辅助根）。

# 功能名：导出落点护栏 security.check_export_target（与白名单无关的第二道约束）
# 生效条件：改动 md_cg/security.py::check_export_target、md_cg/mcp_server.py 的 link/export 分支或 _export_call 之后必跑
# 子功能：① 单元：空路径放行 / 辅助根拒 / 库根层目录拒 / 库根 _ 与 . 开头拒 / 目标已存在拒 / allow_overwrite 放行 / 根外放行 / 库根顶层普通文件放行 ② 集成 link/export：非管理员 out=_keys.json 与 out=节点 .md 均拒且原文件逐字节未动 ③ overwrite=true 需管理权 ④ op=export 管理员同样不得写 _keys.json / 层目录 / 辅助根 ⑤ 保持不变：不带 out 返回包、白名单外仍拒、库根顶层新文件可写、private 读回不受影响 ⑥ 前置对照：撤掉接线（等价修复前形态）⇒ _keys.json 被覆写，判据有判别力
# 执行：python -X utf8 -m md_cg.test_issue211_export_target
# 验证方式：末行「通过 N / 失败 M」；红基线：修复前 main 上 ②④ 为红
# 不适用条件：只测**落点判据**与其接线，不改 evidence.write_pack（CLI --out 行为不变）；不测 link/publish 与 link/import 的 swarm 参数（#211 已列为已知遗留）；不碰在役库（全程 tempfile 沙箱）

## 缺陷现场（issue #211）
MDCG_EXPORT_ROOT 未配置时 _whitelist_roots 回落**记忆库根本身**（#85 选 A），
而 check_path_root 只判「在根内」⇒ _keys.json、_index.json、各层节点 .md 全在
可写面里。持 sustain 令牌（can_admin=False）的调用方两次 MCP 调用即可把证据包
整份替换掉数据密钥信封库：属主读自己的 private 记忆一律 not_found、新 private
写入报 LockedError，库内无备份。

## 本守卫的判别口径（重要）
两个护栏抛的都是 PermissionError，**只看异常类型分不出是谁拦的**。故集成组一律
连**报文**一起断言：check_path_root 的报文含「白名单」，本判据的报文含
「只许根顶层」「不得以 _ 或 . 开头」「不得落在辅助存储根内」。若新判据没接线，
check_path_root 的报文就会出现（G6 前置对照即钉这一点）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback

# 沙箱必须在**任何** md_cg 子模块 import 之前设好（crypto.MASTER_FILE 在模块
# 导入时求值）——与 md_cg/test_b2_sensitivity_landing.py 同款装置。
# 子目录名**不得**用 aux / con / prn / nul / com1-9 / lpt1-9：Windows 保留
# 设备名，makedirs 会抛 NotADirectoryError(WinError 267)。
_SANDBOX = tempfile.mkdtemp(prefix="i211_sandbox_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_SANDBOX, "auxstore")
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "libroot")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_EXPORT_ROOT", None)     # 缺省配置：白名单回落库根
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
os.makedirs(os.environ["MDCG_ROOT"], exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import datapath, mcp_server, security        # noqa: E402
from md_cg.mdcos import MdCGSecure                       # noqa: E402
from md_cg.security import Principal                     # noqa: E402

_KEK = os.urandom(32)
#: 唯一库根。必须 == MDCG_ROOT：缺省白名单回落的是 _configured_library_root()，
#: 若库根另建子目录，check_path_root 会先以「超出白名单」拦下，本判据根本跑不到。
_ROOT = os.environ["MDCG_ROOT"]
_NEW_GUARD_MARKS = ("只许根顶层", "不得以 _ 或 . 开头", "不得落在辅助存储根内")
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


def _principal(role, can_admin):
    return Principal(tenant="t1", actor="a_" + role, role=role,
                     clearance="private", can_write=True, can_admin=can_admin)


def _mk(tag, role="designer", can_admin=True):
    return MdCGSecure(_ROOT, principal=_principal(role, can_admin), master_key=_KEK)


def _arm(cg):
    """满足 link/export 的前置：swarm 策略对 evidence 签名（#211 复现里同款）。"""
    mcp_server._dispatch(cg, "cg", {"op": "link", "action": "policy", "set": True,
                                    "subsystem": "swarm",
                                    "sign_on": ["handshake", "evidence"]})


def _raised(fn, *a, **kw):
    """→ (是否抛, 异常名, 文本)。"""
    try:
        fn(*a, **kw)
        return False, "", ""
    except Exception as exc:                                 # noqa: BLE001
        return True, type(exc).__name__, str(exc)


def _new_guard(txt):
    """报文是否出自 check_export_target（而非 check_path_root）。"""
    return any(m in txt for m in _NEW_GUARD_MARKS)


def _read(p):
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def _run():
    print("\n[1] 单元：check_export_target 判据")
    lib = os.path.join(_SANDBOX, "lib_unit")
    os.makedirs(os.path.join(lib, "knowledge"), exist_ok=True)
    aux = datapath.aux_root()
    _check("U1 空路径放行（未指定落点）",
           _raised(security.check_export_target, "", lib, "t")[0] is False
           and _raised(security.check_export_target, None, lib, "t")[0] is False)
    hit, kind, _t = _raised(security.check_export_target,
                            os.path.join(aux, "x.json"), lib, "t")
    _check("U2 辅助存储根内 → 拒", hit and kind == "PermissionError",
           repr((hit, kind)))
    hit, kind, _t = _raised(security.check_export_target,
                            os.path.join(lib, "knowledge", "a.md"), lib, "t")
    _check("U3 库根内的层目录 → 拒", hit and kind == "PermissionError",
           repr((hit, kind)))
    hit, kind, _t = _raised(security.check_export_target,
                            os.path.join(lib, "_keys.json"), lib, "t")
    _check("U4 库根顶层 _ 开头 → 拒", hit and kind == "PermissionError",
           repr((hit, kind)))
    hit, kind, _t = _raised(security.check_export_target,
                            os.path.join(lib, ".hidden"), lib, "t")
    _check("U5 库根顶层 . 开头 → 拒", hit and kind == "PermissionError",
           repr((hit, kind)))
    exists = os.path.join(lib, "already.json")
    with open(exists, "w", encoding="utf-8") as f:
        f.write("x")
    hit, kind, _t = _raised(security.check_export_target, exists, lib, "t")
    _check("U6 目标已存在且未允许覆盖 → 拒", hit and kind == "PermissionError",
           repr((hit, kind)))
    _check("U7 allow_overwrite=True 时已存在目标放行",
           _raised(security.check_export_target, exists, lib, "t",
                   allow_overwrite=True)[0] is False)
    _check("U8 根外落点放行（白名单外由 check_path_root 管）",
           _raised(security.check_export_target,
                   os.path.join(_SANDBOX, "elsewhere.json"), lib, "t")[0] is False)
    _check("U9 库根顶层普通文件放行",
           _raised(security.check_export_target,
                   os.path.join(lib, "export_1.jsonl"), lib, "t")[0] is False)
    # aux 根误配（末段是 Windows 保留设备名）时 datapath.aux_root() 抛
    # ValueError；落点无法校验 ⇒ 必须 fail-closed，且理由要能看懂。
    # Inject the resolver failure itself. "aux" is a valid directory on POSIX;
    # the same failure/PermissionError contract must be exercised on all hosts.
    _old_aux_resolver = datapath.aux_root
    def _broken_aux_resolver():
        raise ValueError("injected auxiliary-root resolution failure")
    datapath.aux_root = _broken_aux_resolver
    try:
        hit, kind, txt10 = _raised(security.check_export_target,
                                   os.path.join(lib, "export_2.jsonl"), lib, "t")
        _check("U10 aux 根无法解析 ⇒ fail-closed（PermissionError 而非裸 ValueError）",
               hit and kind == "PermissionError" and "辅助存储根无法解析" in txt10,
               repr((hit, kind, txt10[:90])))
    finally:
        datapath.aux_root = _old_aux_resolver

    print("\n[2] 集成 link/export：非管理员不得覆写密钥库与节点文件")
    cg = _mk("sustain", "sustain", can_admin=False)
    _arm(cg)
    cg.add("i211_node", "# 功能名：i211\n\n正文\n", layer="knowledge")
    node_path = cg._node_disk_path(cg.index["nodes"]["i211_node"])
    keys = os.path.join(_ROOT, "_keys.json")
    before_keys, before_node = _read(keys), _read(node_path)
    _check("G2 前置：库根下确有 _keys.json 与节点 .md",
           bool(before_keys) and bool(before_node),
           repr((len(before_keys), len(before_node))))

    hit, kind, txt = _raised(mcp_server._dispatch, cg, "cg",
                             {"op": "link", "action": "export", "out": keys})
    _check("G2a link/export out=<root>/_keys.json → 拒", hit and kind == "PermissionError",
           repr((hit, kind, txt[:90])))
    _check("G2a2 拒的理由来自**新判据**而非白名单（报文含 _ 开头口径）",
           _new_guard(txt), repr(txt[:110]))
    _check("G2b _keys.json 逐字节未动（数据密钥未丢）",
           _read(keys) == before_keys, "len=%d" % len(_read(keys)))

    hit, kind, txt = _raised(mcp_server._dispatch, cg, "cg",
                             {"op": "link", "action": "export", "out": node_path})
    _check("G2c link/export out=<节点 .md> → 拒", hit and kind == "PermissionError",
           repr((hit, kind, txt[:90])))
    _check("G2c2 拒的理由来自**新判据**（报文含「只许根顶层」）",
           _new_guard(txt), repr(txt[:110]))
    _check("G2d 节点文件逐字节未动（越权改写未发生）",
           _read(node_path) == before_node, repr(_read(node_path)[:40]))

    hit, kind, txt = _raised(mcp_server._dispatch, cg, "cg",
                             {"op": "link", "action": "export",
                              "out": os.path.join(_ROOT, "knowledge", "new.md")})
    _check("G2e link/export out=<层目录内新文件> → 拒", _new_guard(txt),
           repr((hit, kind, txt[:90])))

    hit, kind, txt = _raised(mcp_server._dispatch, cg, "cg",
                             {"op": "link", "action": "export",
                              "out": os.path.join(_ROOT, "_new.json")})
    _check("G2f link/export out=<root>/_new.json> → 拒", _new_guard(txt),
           repr((hit, kind, txt[:90])))

    print("\n[3] overwrite=true 需管理权")
    ok_target = os.path.join(_ROOT, "export_i211_ok.jsonl")
    hit, kind, txt = _raised(mcp_server._dispatch, cg, "cg",
                             {"op": "link", "action": "export", "out": ok_target,
                              "overwrite": True})
    _check("G3a 非管理员 overwrite=true → AccessDenied",
           hit and kind == "AccessDenied", repr((hit, kind, txt[:90])))
    _check("G3a2 被拦的是权限而不是落点（报 AccessDenied 而非 PermissionError）",
           kind == "AccessDenied", repr(kind))

    cg_a = _mk("designer", "designer", can_admin=True)
    _arm(cg_a)
    keys_a = os.path.join(_ROOT, "_keys.json")
    before_a = _read(keys_a)
    hit, kind, txt = _raised(mcp_server._dispatch, cg_a, "cg",
                             {"op": "link", "action": "export", "out": keys_a,
                              "overwrite": True})
    _check("G3c 管理员 overwrite=true 也不得写 _keys.json（自伤面同样收口）",
           _new_guard(txt), repr((hit, kind, txt[:90])))
    _check("G3d 管理员侧 _keys.json 亦未动", _read(keys_a) == before_a)

    print("\n[4] op=export（管理员）不得写进密钥库 / 层目录 / 辅助根")
    for label, target in (
            ("_keys.json", os.path.join(_ROOT, "_keys.json")),
            ("层目录内文件", os.path.join(_ROOT, "knowledge", "dump.jsonl"))):
        hit, kind, txt = _raised(mcp_server._dispatch, cg_a, "cg",
                                 {"op": "export", "action": "nodes",
                                  "out": target, "overwrite": True})
        _check("G4 op=export out=<%s> → 拒" % label, _new_guard(txt),
               repr((hit, kind, txt[:90])))
    # 白名单**覆盖辅助根**时（#211 第 9 条缺陷）：check_path_root 会放行，
    # 只有新判据能拦住。
    old_export_root = os.environ.get("MDCG_EXPORT_ROOT")
    os.environ["MDCG_EXPORT_ROOT"] = datapath.aux_root()
    try:
        hit, kind, txt = _raised(mdcg_export_root_case, cg_a)
        _check("G4b MDCG_EXPORT_ROOT 覆盖辅助根时仍不得往 aux 造文件",
               _new_guard(txt), repr((hit, kind, txt[:90])))
    finally:
        if old_export_root is None:
            os.environ.pop("MDCG_EXPORT_ROOT", None)
        else:
            os.environ["MDCG_EXPORT_ROOT"] = old_export_root

    print("\n[5] 保持不变")
    cg_b = _mk("keep", "designer", can_admin=True)
    _arm(cg_b)
    cg_b.add("i211_b", "# 功能名：i211b\n\n正文\n", layer="knowledge")
    hit, kind, txt = _raised(mcp_server._dispatch, cg_b, "cg",
                             {"op": "link", "action": "export"})
    _check("G5a 不带 out 的 link/export 仍返回包（不落盘）",
           not hit, repr((hit, kind, txt[:90])))
    hit, kind, _t = _raised(security.check_path_root,
                            os.path.join(_SANDBOX, "outside.json"),
                            "MDCG_EXPORT_ROOT", "t")
    _check("G5b 白名单外仍拒（#85 的根约束未被削弱）",
           hit and kind == "PermissionError", repr((hit, kind)))
    ok_path = os.path.join(_ROOT, "export_i211_top.jsonl")
    hit, kind, txt = _raised(mcp_server._dispatch, cg_b, "cg",
                             {"op": "link", "action": "export", "out": ok_path})
    print("    读数：link/export out=<root>/export_i211_top.jsonl → raised=%s kind=%s %s"
          % (hit, kind, txt[:70]))
    _check("G5c 库根顶层普通新文件不被落点判据拦（拒绝面只针对密钥/层/辅助根）",
           not _new_guard(txt), repr((hit, kind, txt[:90])))
    priv = cg_b.add("i211_p", "# 功能名：i211p\n\n私密\n", layer="knowledge",
                    sensitivity="private")
    _check("G5d private 写入与读回不受影响",
           "私密" in ((cg_b.get(priv) or {}).get("content") or ""))

    print("\n[6] 前置对照（等价修复前形态）：撤掉接线 ⇒ 密钥库被覆写")
    _orig = security.check_export_target
    security.check_export_target = lambda *a, **k: None      # 等价「未接线」
    try:
        cg_c = _mk("control", "sustain", can_admin=False)
        _arm(cg_c)
        before_c = _read(keys)
        hit, kind, txt = _raised(mcp_server._dispatch, cg_c, "cg",
                                 {"op": "link", "action": "export", "out": keys})
        after_c = _read(keys)
        print("    读数：raised=%s kind=%s 文件被改=%s"
              % (hit, kind, after_c != before_c))
        _check("G6 撤掉接线 ⇒ 无落点判据（修复前形态）",
               not hit, repr((hit, kind, txt[:90])))
        _check("G6b 撤掉接线后 _keys.json 确被改写（判据有判别力）",
               after_c != before_c, repr((len(before_c), len(after_c))))
        _check("G6c 覆写后的 _keys.json 不再是密钥信封库（永久数据丢失形态）",
               "mdcg.evidence.pack" in after_c, repr(after_c[:80]))
    finally:
        security.check_export_target = _orig


def mdcg_export_root_case(cg_a):
    """MDCG_EXPORT_ROOT=辅助根时，往辅助根导出（check_path_root 会放行）。"""
    return mcp_server._dispatch(cg_a, "cg",
                                {"op": "export", "action": "nodes",
                                 "out": os.path.join(datapath.aux_root(), "leak.jsonl"),
                                 "overwrite": True})


def main():
    print("=== issue #211 守卫：导出落点的第二道约束 ===")
    try:
        _run()
    except Exception:                                        # noqa: BLE001
        traceback.print_exc()
        _BAD.append("未捕获异常")
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    print("\n" + "=" * 68)
    print("通过 %d / 失败 %d" % (_OK, len(_BAD)))
    if _BAD:
        print("失败项：" + "、".join(_BAD))
    print("=" * 68)
    return 1 if _BAD else 0


if __name__ == "__main__":
    sys.exit(main())
