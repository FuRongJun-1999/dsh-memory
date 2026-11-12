# -*- coding: utf-8 -*-
"""issue #214 守卫：REJECT 出口与证伪存根必须**原样透传调用方声明的密级**。

# 功能名：写链 REJECT 出口 / 证伪存根的密级透传（private 正文不得以 internal 明文落 rejected/）
# 生效条件：改动 md_cg/writepipe.py::_gate_audit 的 REJECT 分支、md_cg/mdcg.py::verify 的 falsified 分支，或改动 md_cg/mdcos.py 的 add_rejected 之后必跑
# 子功能：①声明 private + 缺六要素被 REJECT → 存根 fm=private、盘上无明文、访客读不到 ②未声明 → 仍 internal（行为不变）③声明 public → 按 public 落盘 ④clearance=internal 的写入方声明 private → fail-closed，不得静默按 internal 存下 ⑤证伪存根取原节点密级 ⑥透传探针（spy 记录 add_rejected 实参）⑦前置对照：把透传丢掉（等价修复前形态）⇒ ①的判据必然转红
# 执行：python -X utf8 -m md_cg.test_issue214_reject_sensitivity
# 验证方式：末行「通过 N / 失败 M」；红基线：修复前 main 上 ①⑤ 为红
# 不适用条件：只测**密级透传**这一条链，不测凭据打码（#43/#93，另有 test_rejected_redact）；不碰在役库（全程 tempfile 沙箱）

## 缺陷现场（issue #214）
writepipe._gate_audit 的 REJECT 分支调 cg.add_rejected 时不传 sensitivity ⇒
MdCGSecure.add_rejected 取 DEFAULT_SENSITIVITY=internal，声明 private 的正文前
200 字以**明文**写成 rejected/rej_<sha1>.md，无令牌访客经 stg(op=timeline) /
cg(op=read, node_id) / mdcg_get 三处可读；回执却写着「本条未入库」。
同函数的 DEFER 出口（#186）与 ACCEPT 落盘面（B2）都已透传，本条是漏掉的第三处；
mdcg.verify(falsified) 的证伪存根同根（#144 曾列为未纳入的改进项）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import traceback

# 沙箱必须在**任何** md_cg 子模块 import 之前设好（crypto.MASTER_FILE 在模块
# 导入时求值）——与 md_cg/test_b2_sensitivity_landing.py 同款装置。
_SANDBOX = tempfile.mkdtemp(prefix="i214_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SANDBOX
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
_SIX = ["功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件"]
_POLICY = os.path.join(_SANDBOX, "policy.json")
with open(_POLICY, "w", encoding="utf-8") as _f:
    json.dump({"forbidden": [], "required": list(_SIX)}, _f)
os.environ["MDCG_POLICY_FILE"] = _POLICY
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import nodefile, writepipe                        # noqa: E402
from md_cg.mdcos import MdCGSecure                           # noqa: E402
from md_cg.security import Principal                         # noqa: E402

_KEK = os.urandom(32)
_MARK = "I214MARK 私人日记：今天确诊抑郁症，医生开了舍曲林，别让同事知道"
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


def _principal(clearance="secret", can_admin=True):
    return Principal(tenant="t1", actor="alice", role="designer",
                     clearance=clearance, can_write=True, can_admin=can_admin)


class _SpyCG(MdCGSecure):
    """透传探针：记录每次 add_rejected 收到的 sensitivity 实参。"""

    def add_rejected(self, hypothesis, reason, sensitivity=None, **kw):
        self.seen.append(sensitivity)
        return super().add_rejected(hypothesis, reason, sensitivity=sensitivity, **kw)


class _DropCG(MdCGSecure):
    """前置对照：**丢掉** sensitivity（等价修复前 HEAD 的行为）。"""

    def add_rejected(self, hypothesis, reason, sensitivity=None, **kw):
        return super().add_rejected(hypothesis, reason, **kw)


def _mk(cls, tag, clearance="secret"):
    root = os.path.join(_SANDBOX, "lib_" + tag)
    cg = cls(root, principal=_principal(clearance), master_key=_KEK)
    cg.seen = []
    return cg, root


def _raw(cg, nid):
    e = cg.index["nodes"][nid]
    with open(cg._node_disk_path(e), encoding="utf-8") as f:
        text = f.read()
    fm, content = nodefile.loads(text)
    return text, fm, content


def _scan(root, needle):
    hits = []
    for dp, _dn, fs in os.walk(root):
        for f in fs:
            fp = os.path.join(dp, f)
            try:
                with open(fp, encoding="utf-8", errors="ignore") as fh:
                    if needle in fh.read():
                        hits.append(os.path.relpath(fp, root))
            except OSError:
                continue
    return hits


def _rej_id(cg):
    for nid in cg.index["nodes"]:
        if str(nid).startswith("rej_"):
            return nid
    return None


def _write_and_audit(pipe, cg, sensitivity="__absent__"):
    a = {"content_kind": "text", "layer": "knowledge", "content": _MARK}
    if sensitivity != "__absent__":
        a["sensitivity"] = sensitivity
    return pipe.execute(cg, a)


def _run():
    pipe = writepipe.install_default_gates(writepipe.WritePipeline())

    print("\n[G1] 声明 private + 缺六要素被 REJECT → 存根必须按 private 落盘")
    cg1, root1 = _mk(_SpyCG, "g1")
    out1 = _write_and_audit(pipe, cg1, "private")
    rid1 = out1.get("id")
    _check("G1a REJECT 出口照旧（moved_to=rejected，committed=false）",
           out1.get("moved_to") == "rejected" and out1.get("committed") is False,
           repr(out1)[:150])
    _check("G1b 透传探针：add_rejected 收到的 sensitivity == 'private'",
           cg1.seen == ["private"], repr(cg1.seen))
    if rid1 and rid1 in cg1.index["nodes"]:
        raw1, fm1, content1 = _raw(cg1, rid1)
        _check("G1c 存根 frontmatter sensitivity == 声明值 private",
               fm1.get("sensitivity") == "private", repr(fm1.get("sensitivity")))
        _check("G1d 盘上无明文（整库扫描）", not _scan(root1, _MARK),
               repr(_scan(root1, _MARK)))
        _check("G1e 存根正文不是明文", "I214MARK" not in raw1, raw1[:60])
        guest = MdCGSecure(root1, principal=_principal("internal", can_admin=False),
                           master_key=_KEK)
        got = (guest.get(rid1) or {}).get("content") or ""
        _check("G1f clearance=internal 的读者读不到 private 存根正文",
               _MARK not in got, repr(got[:40]))
    else:
        _check("G1c 存根 frontmatter sensitivity == 声明值 private", False,
               "未落盘 id=%r" % rid1)

    print("\n[G2] 未声明密级 → 仍按 internal（行为不变，#87 已裁的缺省）")
    cg2, root2 = _mk(_SpyCG, "g2")
    out2 = _write_and_audit(pipe, cg2)
    rid2 = out2.get("id")
    # 2026-10-19（#557 R5）：未声明不再原样下传 None——出口会先向**被改写节点**
    # 求一次 `_write_sensitivity`。新节点没有旧密级 ⇒ 求得的仍是缺省档 internal，
    # 故 G2b/G2c 的**行为**断言不变；变的只是探针该看到的实参（None → 'internal'）。
    _check("G2a 透传探针：未声明时收到继承值 'internal'（新节点无旧档 ⇒ 缺省）",
           cg2.seen == ["internal"], repr(cg2.seen))
    if rid2 and rid2 in cg2.index["nodes"]:
        _raw2, fm2, _c2 = _raw(cg2, rid2)
        _check("G2b 未声明仍落 internal", fm2.get("sensitivity") == "internal",
               repr(fm2.get("sensitivity")))
        _check("G2c 未声明仍保留原文（可修正的负记忆，行为不变）",
               _MARK in _raw2, _raw2[:60])
    else:
        _check("G2b 未声明仍落 internal", False, "未落盘 id=%r" % rid2)

    print("\n[G2d] 未声明 + 改写**既有 private 节点** ⇒ 存根继承 private（#557 R5）")
    cg2d, _root2d = _mk(_SpyCG, "g2d")
    cg2d.add("X", _MARK, layer="knowledge", sensitivity="private")
    cg2d.seen = []
    out2d = pipe.execute(cg2d, {"content_kind": "text", "layer": "knowledge",
                                "content": _MARK, "node_id": "X"})
    _check("G2d add_rejected 收到继承值 'private'（不再回落 internal）",
           cg2d.seen == ["private"], repr(cg2d.seen))
    _rid2d = out2d.get("id")
    _check("G2d 负记忆存根落盘档 == private",
           bool(_rid2d) and (cg2d.index["nodes"].get(_rid2d) or {}).get("sensitivity")
           == "private",
           (_rid2d, (cg2d.index["nodes"].get(_rid2d) or {}).get("sensitivity")))

    print("\n[G3] 声明 public → 按 public 落盘（与 ACCEPT 出口同口径）")
    cg3, _root3 = _mk(_SpyCG, "g3")
    out3 = _write_and_audit(pipe, cg3, "public")
    rid3 = out3.get("id")
    if rid3 and rid3 in cg3.index["nodes"]:
        _raw3, fm3, _c3 = _raw(cg3, rid3)
        _check("G3 声明 public 按 public 落盘", fm3.get("sensitivity") == "public",
               repr(fm3.get("sensitivity")))
    else:
        _check("G3 声明 public 按 public 落盘", False, "未落盘 id=%r" % rid3)

    print("\n[G4] clearance=internal 的写入方声明 private → fail-closed，不得静默降级")
    cg4, root4 = _mk(MdCGSecure, "g4", clearance="internal")
    denied, out4 = False, {}
    try:
        out4 = _write_and_audit(pipe, cg4, "private")
    except Exception as exc:                                 # noqa: BLE001
        denied = "AccessDenied" in type(exc).__name__ or "AccessDenied" in str(exc)
    _check("G4a 不按 internal 静默存下（拒绝或非 rejected 出口）",
           denied or out4.get("moved_to") != "rejected",
           "denied=%s out=%s" % (denied, repr(out4)[:110]))
    _check("G4b 盘上 rejected 层无新文件", not _scan(root4, _MARK),
           repr(_scan(root4, _MARK)))

    print("\n[G5] 证伪存根取**原节点 frontmatter 的密级**")
    cg5, root5 = _mk(MdCGSecure, "g5")
    body = "".join("# %s：i214 用\n" % k for k in _SIX) + "\n" + _MARK
    # 前置走**库层直写**而非写闸：本组只测 verify 出口，不掺写闸的裁决口径
    # （六要素齐也可能落 DEFER，那是另一条链的事）。
    nid5 = cg5.add("i214_g5", body, layer="knowledge", sensitivity="private")
    if nid5 in cg5.index["nodes"]:
        _check("G5a 前置：private 节点已落盘", True)
        cg5.verify(nid5, "被实测证伪", "falsified")
        rid5 = _rej_id(cg5)
        _check("G5b 证伪产生了 rejected 存根", bool(rid5), repr(rid5))
        if rid5:
            raw5, fm5, _c5 = _raw(cg5, rid5)
            _check("G5c 证伪存根 sensitivity == 原节点的 private",
                   fm5.get("sensitivity") == "private", repr(fm5.get("sensitivity")))
            _check("G5d 证伪存根盘上无明文", not _scan(root5, _MARK),
                   repr(_scan(root5, _MARK)))
    else:
        _check("G5a 前置：private 节点已落盘", False, repr(nid5))

    print("\n[G6] 前置对照（等价修复前形态）：丢掉透传 ⇒ G1 的判据必然转红")
    cg6, root6 = _mk(_DropCG, "g6")
    out6 = _write_and_audit(pipe, cg6, "private")
    rid6 = out6.get("id")
    if rid6 and rid6 in cg6.index["nodes"]:
        raw6, fm6, _c6 = _raw(cg6, rid6)
        leaked = bool(_scan(root6, _MARK))
        print("    读数：fm=%r 明文落盘=%s" % (fm6.get("sensitivity"), leaked))
        _check("G6 丢掉透传 ⇒ 存根变 internal 且明文落盘（判据有判别力）",
               fm6.get("sensitivity") == "internal" and leaked,
               repr((fm6.get("sensitivity"), leaked)))
    else:
        _check("G6 丢掉透传 ⇒ 存根变 internal 且明文落盘（判据有判别力）", False,
               "未落盘 id=%r" % rid6)


def main():
    print("=== issue #214 守卫：REJECT 出口 / 证伪存根的密级透传 ===")
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