# -*- coding: utf-8 -*-
r"""#147 守卫：pack_id 一律不得逃出收件箱（路径穿越 / 覆写 _keys.json）。

缺陷（本件修复，2026-10-11）
--------------------------
\`write_pack\` 把 \`pack_id\` **未清洗**即拼进归档路径（缺省分支）；
\`_validate\` 也不校验 pack_id ⇒ 带 \`../\` 的 pack_id 可穿越出收件箱。
实测（tempfile 沙箱）：\`pack_id = '../../../../../memroot/_keys'\` 经
\`import_pack(archive=True)\` **一次即覆写** \`_keys.json\` 与 \`_tokens.json\`
（返回 \`ok=True / archived=memroot\_keys.json\`）；\`pack_id\` 带空字节时
\`ValueError\` 还会**逸出** import_pack（原 except 只捕 OSError）。

三道闸（本守卫逐条钉）
---------------------
  ① \`_validate\` pack_id 白名单（ASCII 字母数字与 . _ -；拒 ..、前导点、超长）
  ② \`write_pack\` 汇点兜底：同源白名单 + realpath 包含性 → 一律 \`EvidenceError\`
  ③ \`import_pack\` 归档 except 扩到 \`EvidenceError\`（不逃逸）

**磁盘证据优先**：不止断言「抛异常/拒收」，还断言**没有文件落在收件箱之外**
且受害者档未被覆写——M2 变异正是靠这条磁盘腿转红。

运行：python -X utf8 -m md_cg.test_issue147_pack_id_escape
      python -X utf8 -m md_cg.test_issue147_pack_id_escape --mutate
退出码：0 全绿 / 1 有失败
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import time

from . import evidence as ev
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []
_SANDBOXES = []

#: 恶意 pack_id 矩阵：(名, 值)——覆盖 穿越/绝对/盘符/UNC/空字节/点形/超长/类型
MALICIOUS = (
    ("穿越(glued)", "../../../../../memroot/_keys"),
    ("穿越(slash)", "/../../../../memroot/_keys"),
    ("穿越(_tokens)", "/../../../../memroot/_tokens"),
    ("反斜杠穿越", "..\\..\\memroot\\_keys"),
    ("纯 ..", ".."),
    ("单点", "."),
    ("前导点", ".hidden"),
    ("绝对路径", "/tmp/evil"),
    ("盘符", "C:/evil"),
    ("UNC", "\\\\srv\\share\\evil"),
    ("空字节", "bad\x00id"),
    ("超长", "p" * (ev.PACK_ID_MAX + 1)),
    ("非字符串", 123),
    ("缺失", None),
)
#: 合法 pack_id（导出面真实形态，见 export_pack：pack-<12hex>）
LEGIT = (("导出形", "pack-a1b2c3d4e5f6"), ("含点横线", "pack-1.2_x-3"))

SENT = '{"victim": "ORIGINAL"}'


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))
    return bool(cond)


# 生效条件：无入参；建 tempfile 沙箱（auxroot/memroot 两目录 + 策略档 + env），
# 返回 (T, AUX, ROOT, cg)。注意目录名不能取 "aux"——Windows 保留设备名。
def _sandbox():
    t = tempfile.mkdtemp(prefix="i147_guard_")
    _SANDBOXES.append(t)
    aux, root = os.path.join(t, "auxroot"), os.path.join(t, "memroot")
    for d in (aux, root):
        os.makedirs(d, exist_ok=True)
    os.environ.update(MDCG_AUX_ROOT=aux, MDCG_ROOT=root, MDCG_NODE_ID="node-self",
                      MDCG_MASTER_KEY=os.urandom(32).hex())
    # **必须显式设 MDCG_SWARM_DIR**：`evidence.DEFAULT_SWARM_DIR` 在**模块导入时**
    # 由 aux_root() 冻结，而本守卫是模块顶层 `import evidence` ⇒ 只设 MDCG_AUX_ROOT
    # 不生效，归档会落到**真实** aux 目录（本守卫首版即踩此坑：实测污染了
    # `~/.mdcg/swarm/inbox` 并在家目录下留下穿越产物 `~/memroot`，
    # 已逐项核对清理——见 _team/iss147/report.md「探针污染」节）。
    # ⚠ 本机绝对路径不得写进追踪面（check_local_paths 硬门禁），故此处用中性占位。
    # `swarm_dir()` 在**调用时**读该环境变量，故这是唯一有效的沙箱开关。
    os.environ["MDCG_SWARM_DIR"] = os.path.join(aux, "swarm")
    pol = os.path.join(t, "policy.json")
    io.open(pol, "w", encoding="utf-8").write(
        json.dumps({"forbidden": [], "required": []}))
    os.environ["MDCG_POLICY_FILE"] = pol
    # #453（SEC·P1）同批随动：`import_pack` 现为 fail-closed（空签名一律拒）。
    # 本守卫的 G2「合法 pack_id 不误伤」需要一个**真签得出来**的合法包，故在沙箱里
    # 声明子系统策略（要求对端签名）并把密钥/策略文件都指进沙箱——不碰真实 aux。
    sigfile = os.path.join(t, "signers.json")
    io.open(sigfile, "w", encoding="utf-8").write(json.dumps({
        "schema": 1, "default_signer": "hmac-local",
        "subsystems": {ev.SUBSYSTEM: {
            "signer": "hmac-local", "sign_on": ["handshake", "evidence"],
            "require_peer_signature": True, "on_verify_fail": "reject"}}}))
    os.environ["MDCG_SIGNERS_FILE"] = sigfile
    os.environ["MDCG_SIGNER_KEY_FILE"] = os.path.join(t, "signer.key")
    # fail-closed：沙箱没生效就**拒跑**，绝不在真实 aux 目录上做攻击面验证。
    inbox = os.path.realpath(ev.inbox_dir())
    if not inbox.startswith(os.path.realpath(t) + os.sep):
        raise RuntimeError(
            "沙箱未生效：收件箱 %s 不在 tempfile 沙箱 %s 内——拒绝运行" % (inbox, t))
    return t, aux, root, MdCGOS(root)


def _pack(pid):
    # #453（SEC·P1，同批随动）：`import_pack` 现为 **fail-closed：空签名一律拒收**
    # （不看 `sig.signer`/`sig.signed` 等对端自报值）。本守卫的合法夹具原先用
    # `{"signer":"null","signature":"","signed":False}` 冒充「合法包」——那条通道
    # 正是 #453 要关掉的免签名通行证，故夹具必须带**真签名**，否则 G2 的
    # 「合法 pack_id 不误伤」会被签名闸（而非 pack_id 闸）打红。
    # 判据强度**不降**：G2 仍断言 `ok is True and archived`，并新增 `sig` 非空断言
    # （见 _run_all），把「夹具确实签过」也钉住。
    p = {"kind": ev.KIND, "schema": ev.SCHEMA, "from_node": "attacker",
         "pack_id": pid, "created_at": time.time(),
         "items": [{"subject": "s", "text": "t", "sensitivity": "internal"}]}
    s = ev._signer.sign_for(ev.SUBSYSTEM, ev._pack_payload(p),
                            action=ev.SIGN_ACTION)
    p["sig"] = {"signer": s.get("signer"),
                "signature": s.get("signature") or "",
                "signed": bool(s.get("signed"))}
    return p


def _reset(root):
    for p in (os.path.join(root, "_keys.json"), os.path.join(root, "_tokens.json")):
        io.open(p, "w", encoding="utf-8").write(SENT)


def _victim_touched(root):
    for p in (os.path.join(root, "_keys.json"), os.path.join(root, "_tokens.json")):
        if io.open(p, encoding="utf-8").read() != SENT:
            return True
    return False


def _outside_inbox(aux):
    """收件箱之外（整个 aux 树里）的落点——磁盘证据腿。"""
    inbox = os.path.realpath(ev.inbox_dir())
    out = []
    for dp, _dn, fns in os.walk(aux):
        for f in fns:
            p = os.path.realpath(os.path.join(dp, f))
            if p != inbox and not p.startswith(inbox + os.sep):
                out.append(os.path.relpath(p, aux).replace("\\", "/"))
    return sorted(out)


# 生效条件：入参为 (_sandbox() 的四元组)；逐条跑恶意/合法矩阵与显式 path 面，
# 返回违规描述列表（空列表=全合规）。**判据单点**——变异打在其依赖的模块属性上。
def _judge(sb) -> list:
    t, aux, root, cg = sb
    bad = []
    for name, pid in MALICIOUS:
        _reset(root)
        why = ev._validate(_pack(pid))
        if not why:
            bad.append("validate:[%s] 放行了非法 pack_id %r" % (name, pid))
        try:
            f = ev.write_pack(_pack(pid), swarm=None)["file"]
            bad.append("sink:[%s] 汇点未拒（写到 %s）" % (name, f))
        except ev.EvidenceError:
            pass
        except Exception as exc:                          # noqa: BLE001
            bad.append("sink:[%s] 汇点抛了非 EvidenceError：%s: %s"
                       % (name, type(exc).__name__, str(exc)[:60]))
        _reset(root)
        try:
            r = ev.import_pack(cg, _pack(pid), swarm=None)
            if r.get("ok") is not False or not r.get("rejected"):
                bad.append("accept:[%s] import 未拒收：ok=%s rejected=%s"
                           % (name, r.get("ok"), r.get("rejected")))
        except Exception as exc:                          # noqa: BLE001
            bad.append("escape:[%s] import 异常逃逸：%s: %s"
                       % (name, type(exc).__name__, str(exc)[:60]))
        if _victim_touched(root):
            bad.append("victim:[%s] 受害者 _keys/_tokens 被覆写" % name)
    stray = _outside_inbox(aux)
    if stray:
        bad.append("stray:收件箱外出现落点：%s" % stray[:5])
    for name, pid in LEGIT:
        _p = _pack(pid)
        # 夹具自证（#453 随动）：G2 若用空签名包，「不误伤」会由签名闸而非
        # pack_id 闸决定 ⇒ 判据失去指向。先钉「夹具确实签过」，再判 pack_id 面。
        if not (_p.get("sig") or {}).get("signature"):
            bad.append("legit:[%s] 夹具未签（#453 后空签名必被拒，G2 会失去指向）"
                       % name)
            continue
        why = ev._validate(_p)
        if why:
            bad.append("legit:[%s] 被误拒：%s" % (name, why))
            continue
        f = ev.write_pack(_p, swarm=None)["file"]
        if not os.path.realpath(f).startswith(os.path.realpath(ev.inbox_dir()) + os.sep):
            bad.append("legit:[%s] 未落在收件箱内：%s" % (name, f))
        r = ev.import_pack(cg, _p, swarm=None)
        if not (r.get("ok") is True and r.get("archived")):
            bad.append("legit:[%s] import 未归档：%s" % (name, r))
    # 显式 path 仍为调用方权限（CLI --out / MCP out 两处调用面）——不得被收窄
    chosen = os.path.join(t, "userchosen", "export.json")
    os.makedirs(os.path.dirname(chosen), exist_ok=True)
    ev.write_pack(_pack(LEGIT[0][1]), path=chosen, swarm=None)
    if not os.path.isfile(chosen):
        bad.append("path:显式 path 被误拦（调用方权限被收窄）")
    return bad


def _run_one(sb, pid):
    """单条**恶意** pack_id 的三道闸核对；返回 (是否合规, 详情)。"""
    t, aux, root, cg = sb
    _reset(root)
    why = ev._validate(_pack(pid))
    sink = ""
    try:
        ev.write_pack(_pack(pid), swarm=None)
        sink = "未拦"
    except ev.EvidenceError:
        sink = "EvidenceError"
    except Exception as exc:                              # noqa: BLE001
        sink = "%s(非EvidenceError)" % type(exc).__name__
    _reset(root)
    try:
        r = ev.import_pack(cg, _pack(pid), swarm=None)
        imp = "拒收" if (r.get("ok") is False and r.get("rejected")) else "**放行**"
    except Exception as exc:                              # noqa: BLE001
        imp = "**异常逃逸 %s**" % type(exc).__name__
    touched = _victim_touched(root)
    ok = bool(why) and sink == "EvidenceError" and imp == "拒收" and not touched
    return ok, "validate=%s sink=%s import=%s 覆写=%s" % (
        "拒" if why else "**放行**", sink, imp, touched)


def _run_all():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    sb = None
    try:
        sb = _sandbox()
        t, aux, root, cg = sb
        for name, pid in MALICIOUS:
            ok, det = _run_one(sb, pid)
            check("G1-%s 恶意 pack_id 被拒且不落盘" % name, ok, det)
        stray = _outside_inbox(aux)
        check("G1z 收件箱外零残留（磁盘证据）", not stray, stray[:4])
        for name, pid in LEGIT:
            _p = _pack(pid)
            signed = bool((_p.get("sig") or {}).get("signature"))
            why = ev._validate(_p)
            f = ev.write_pack(_p, swarm=None)["file"]
            inside = os.path.realpath(f).startswith(
                os.path.realpath(ev.inbox_dir()) + os.sep)
            r = ev.import_pack(cg, _p, swarm=None)
            check("G2-%s 合法 pack_id 不误伤" % name,
                  signed and (not why) and inside and r.get("ok") is True
                  and bool(r.get("archived")),
                  "夹具已签=%s validate=%r 落inbox内=%s import_ok=%s"
                  % (signed, why, inside, r.get("ok")))
        chosen = os.path.join(t, "userchosen", "export.json")
        os.makedirs(os.path.dirname(chosen), exist_ok=True)
        ev.write_pack(_pack(LEGIT[0][1]), path=chosen, swarm=None)
        check("G3 显式 path 仍为调用方权限（CLI --out / MCP out 未被收窄）",
              os.path.isfile(chosen), chosen)
    except Exception as exc:                              # noqa: BLE001
        check("判据面组异常", False, "%s: %s" % (type(exc).__name__, exc))
    finally:
        if sb:
            sb[3].close()


# 生效条件：无入参；在三个落点各注入一次定点变异并重跑同一判据函数，逐条打印
# 「变异前 → 变异后」；返回失败条数（每条变异必须让判据转红）。
def _run_mutations() -> int:
    print(chr(10) + "=== 定点变异自证（变异前 → 变异后）===")
    sb = _sandbox()
    bad = 0
    try:
        base = _judge(sb)
        print("  [基线] 变异前违规项 = %s（应为空）" % (base or "无"))
        keep_os = ev.os
        keep_pidfn = ev._pack_id_error

        class _PathNoNorm:
            """代理 os.path：realpath 退化为原样返回（模拟包含性判定失效）。"""

            def __init__(self, real):
                self._real = real

            def __getattr__(self, k):
                return getattr(self._real, k)

            @staticmethod
            def realpath(p, *a, **k):
                return p

        class _OsNoNorm:
            """代理 os：**连带 os.path**——源码用的是 os.path.realpath，
            只替 os.realpath 不会生效（本守卫首版即踩此坑，实测仍抛 EvidenceError）。"""

            def __init__(self, real, path_proxy):
                self._real = real
                self.path = path_proxy

            def __getattr__(self, k):
                return getattr(self._real, k)

        def _relax_all():
            ev._pack_id_error = lambda pid: ""
            ev.os = _OsNoNorm(keep_os, _PathNoNorm(keep_os.path))

        only_pidfn = lambda: setattr(ev, "_pack_id_error", lambda pid: "")
        #: (名, 注入, 期望**必现**的腿, 说明)——腿标见 _judge：validate/sink/accept/
        #: escape/victim/stray/legit/path。三条各证一道闸承重。
        cases = (
            ("M1 白名单恒放行（断言 ② 汇点兜底独立承重）",
             only_pidfn, "sink"),
            # 期望腿是 victim 而非 stray：穿越目标（memroot）在 aux 树**之外**，
            # _outside_inbox 只巡 aux ⇒ 只有 victim 腿能看见（首版设计漏此点）。
            ("M2 白名单恒放行 + realpath 兜底失效（断言受害者档被覆写）",
             _relax_all, "victim"),
            ("M3 白名单恒放行（与 M1 同注入点、观测腿不同：③ 覆盖面）",
             only_pidfn, "escape"),
        )
        for label, inject, want_leg in cases:
            try:
                inject()
                got = _judge(sb)
            finally:
                ev._pack_id_error = keep_pidfn        # 复原注入点
                ev.os = keep_os
            legs = sorted({v.split(":", 1)[0] for v in got})
            hit = want_leg in legs
            if not check(label, hit, "期望腿 %r 未出现，实得腿=%s" % (want_leg, legs)):
                bad += 1
            print("        变异前：违规项=[] ｜ 变异后：违规项=%d 项，腿=%s ｜ 期望腿 %r ⇒ %s"
                  % (len(got), legs, want_leg, "命中" if hit else "未命中"))
            if want_leg == "victim" or want_leg == "stray":
                print("        磁盘证据：%s" % [v for v in got if v.startswith(("stray", "victim"))][:2])
        print("  变异自证结论：%s" % ("全部按预期转红" if bad == 0
                                  else "存在 %d 条未按预期" % bad))
        return bad
    finally:
        sb[3].close()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="#147 pack_id 穿越守卫")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证")
    a = ap.parse_args()
    print("[1] 判据面")
    _run_all()
    rc = 1 if FAILS else 0
    if a.mutate:
        rc = 1 if (_run_mutations() or FAILS) else 0
    print(chr(10) + "SUMMARY: #147 pack_id 穿越守卫：%d 通过，%d 失败%s"
          % (PASS, FAIL, ("；失败项=" + "; ".join(FAILS)) if FAILS else ""))
    for d in _SANDBOXES:
        shutil.rmtree(d, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
