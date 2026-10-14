# -*- coding: utf-8 -*-
"""跨节点证据包密级通路守卫（issue #258）。

【守什么】
#258 报：证据包整条通路**不带密级**——`_collect` 条目无 sensitivity、
`identity.observe` 签名无该形参 ⇒ `import_pack` 落盘走缺省
`DEFAULT_SENSITIVITY="internal"`。而 `crypto.ENCRYPTED_LEVELS =
("private","secret")` ⇒ 发送方盘上密文、接收方盘上**明文**，且默认
`archive=True` 把整包明文 JSON 再落一份到收件箱。

复核**成立**（实测与报告 JSON 逐字一致）：
  A 侧 private / 盘上无明文 → 包内条目无 sensitivity → B 侧 internal /
  **盘上明文** + 收件箱明文，返回体只说 `imported: 1`（降级不可见）。

修法（报告建议的 5 条，逐条落地）：
  ① `evidence._node_sensitivity` = `subgraph.node_sensitivity`（与 #164 同源）；
  ② `_collect` 每条带 sensitivity；
  ③ `import_pack` 经 `security.SENSITIVITY_ORDER` 校验，缺字段/非字符串/
     未知档 ⇒ fail-closed 不写盘（计入 skipped 并留理由）；
  ④ `identity.observe` 新增 sensitivity=None 并透传 cg.add（既有调用方零变更）；
  ⑤ 包内含 private/secret ⇒ 不归档（归档是明文 JSON），返回 `archive_skipped`。

判据：
  S1  _collect 每条带 sensitivity，且与 subgraph.node_sensitivity **同源**。
  S2  端到端：private 观测 A→B 后密级仍是 private，且 B 盘上**无明文**。
  S3  归档闸：含加密档 ⇒ archived 为空且给出理由。
  S4  旧格式包（删 sensitivity）⇒ 一律拒收（fail-closed，有意的行为变更）。
  S5  非字符串 / 未知档 ⇒ 拒收，且**不回落**到缺省 internal。
  S6  导入方密级不足（clearance 低于条目密级）⇒ 跳过且不降级落盘。
  S7  不误伤：internal 包正常导入、正常归档。
  S8  identity.observe 不传 sensitivity ⇒ 行为逐位不变（既有调用方零变更）。
  S9  反陈化：三处收口的**理由**在源码里。
  S10 修复前原形：git log -S 定位引入提交取父版本；**未提交时回落 HEAD**
      （不假设 HEAD 处于某历史状态——项目方在 #277 踩过该坑）。

运行：python -X utf8 -m md_cg.test_issue258_pack_sensitivity
      python -X utf8 -m md_cg.test_issue258_pack_sensitivity --mutate
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="i258g_")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "lib")
# ★ 目录名不可用 "aux"——AUX 是 Windows 保留设备名（#245 实测踩到）。
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxstore")
os.environ["MDCG_MASTER_KEY"] = "ef" * 32
os.environ["MDCG_SIGNER_KEY_FILE"] = os.path.join(_TMP, "signer.key")
os.makedirs(os.environ["MDCG_ROOT"], exist_ok=True)
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import crypto                     # noqa: E402
from md_cg import evidence as E              # noqa: E402
from md_cg import identity as _id            # noqa: E402
from md_cg import security as _sec           # noqa: E402
from md_cg import signer as _signer          # noqa: E402
from md_cg import subgraph as _sg            # noqa: E402
from md_cg.mdcos import MdCGSecure           # noqa: E402
from md_cg.security import Principal         # noqa: E402

_KEK = os.urandom(32)
_OK = 0
_BAD = []
_MARK = "私密观测正文-令牌-abc"
_N = [0]


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _fresh(clearance="secret"):
    """新建一对根 + 一个共享目录，返回 (cgA, cgB, rootA, rootB, swarm)。"""
    _N[0] += 1
    tag = "n%d" % _N[0]
    A = os.path.join(_TMP, tag + "_A")
    B = os.path.join(_TMP, tag + "_B")
    SW = os.path.join(_TMP, tag + "_swarm")
    for p in (A, B, SW):
        os.makedirs(p, exist_ok=True)
    return (_mk(A, "a"), _mk(B, "b", clearance=clearance), A, B, SW)


def _mk(root, actor, clearance="secret"):
    return MdCGSecure(root, principal=Principal(tenant="t1", actor=actor,
                                                role="designer",
                                                clearance=clearance,
                                                can_write=True,
                                                can_admin=True),
                      master_key=_KEK)


def _seed_private(cg, nid="obs_priv", sens="private"):
    return cg.add(nid, _MARK, layer="knowledge",
                  tags=["subject:x", "kind:note", _id.TAG_OBS],
                  condition_space={"subject": "x"}, importance=0.6,
                  verification_basis="data", sensitivity=sens)


def _plaintext_files(root, mark=_MARK):
    """盘上含明文（未加密）的文件相对路径列表。"""
    out = []
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                t = io.open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if mark in t:
                out.append(os.path.relpath(p, root))
    return out


def _resign(pack):
    r = _signer.sign_for(E.SUBSYSTEM, E._pack_payload(pack),
                         action=E.SIGN_ACTION)
    pack["sig"] = {"signer": r.get("signer"),
                   "signature": r.get("signature") or "",
                   "signed": bool(r.get("signed"))}
    return pack


def _write(cg, swarm, **kw):
    return E.write_pack(E.export_pack(cg, swarm=swarm, **kw)["pack"],
                        swarm=swarm)["file"]


def _src(rel):
    return io.open(os.path.join(_REPO, rel), encoding="utf-8",
                   errors="replace").read()


_signer.set_policy("swarm", sign_on=["handshake", "evidence"])


def s1():
    print("== S1 _collect 每条带 sensitivity，且与 subgraph 同源 ==")
    cgA, _cgB, A, _B, SW = _fresh()
    _seed_private(cgA)
    items = E._collect(cgA)
    _check("S1a _collect 收到条目", len(items) == 1, len(items))
    if not items:
        return
    _check("S1b 条目带 sensitivity 字段", "sensitivity" in items[0],
           sorted(items[0].keys()))
    _check("S1c 读数为 private", items[0].get("sensitivity") == "private",
           items[0].get("sensitivity"))
    _check("S1d 与 subgraph.node_sensitivity 同源（读数一致）",
           items[0].get("sensitivity") == _sg.node_sensitivity(cgA, "obs_priv"))
    _check("S1e 常量引的是既有权威（不另立判据）",
           E._SENSITIVITY_ORDER is _sec.SENSITIVITY_ORDER
           and E._ENCRYPTED_LEVELS == set(crypto.ENCRYPTED_LEVELS))


def s2():
    print("== S2 端到端：private 不降级且接收方盘上无明文 ==")
    cgA, cgB, A, B, SW = _fresh()
    _seed_private(cgA)
    _check("S2a 发送方盘上无明文", _plaintext_files(A) == [], _plaintext_files(A))
    pf = _write(cgA, SW)
    res = E.import_pack(cgB, pf, swarm=SW)
    _check("S2b 导入成功", res.get("imported") == 1, res)
    bn = (res.get("node_ids") or [None])[0]
    _check("S2c 接收方索引密级 == private（未降级）",
           ((cgB.index.get("nodes") or {}).get(bn) or {}).get("sensitivity")
           == "private",
           ((cgB.index.get("nodes") or {}).get(bn) or {}).get("sensitivity"))
    _check("S2d 接收方 frontmatter 密级 == private",
           ((cgB.get(bn) or {}).get("frontmatter") or {}).get("sensitivity")
           == "private")
    _check("S2e ★ 接收方盘上**无明文**（此前会落成明文）",
           _plaintext_files(B) == [], _plaintext_files(B))
    _check("S2f 包内条目带 sensitivity",
           "sensitivity" in E._read_pack(pf)["items"][0])


def s3():
    print("== S3 归档闸：含加密档不归档 ==")
    cgA, cgB, A, B, SW = _fresh()
    _seed_private(cgA)
    pf = _write(cgA, SW)
    res = E.import_pack(cgB, pf, swarm=SW)
    _check("S3a 未归档（archived 为空）", res.get("archived") == "",
           res.get("archived"))
    _check("S3b 给出 archive_skipped 理由",
           "private" in (res.get("archive_skipped") or ""),
           res.get("archive_skipped"))
    _check("S3c 返回体含 archive_skipped 键（降级/跳过可见）",
           "archive_skipped" in res and "skipped_reasons" in res)


def s4():
    print("== S4 旧格式包（缺 sensitivity）fail-closed 拒收 ==")
    cgA, cgB, A, B, SW = _fresh()
    _seed_private(cgA)
    pack = E.export_pack(cgA, swarm=SW)["pack"]
    for it in pack["items"]:
        it.pop("sensitivity", None)            # 伪造旧格式包
    _resign(pack)
    pf = E.write_pack(pack, swarm=SW)["file"]
    res = E.import_pack(cgB, pf, swarm=SW)
    _check("S4a imported == 0（旧格式包一律不收）", res.get("imported") == 0,
           res.get("imported"))
    _check("S4b skipped == 条目数", res.get("skipped") == len(pack["items"]),
           res.get("skipped"))
    _check("S4c 理由点明缺字段",
           any("sensitivity" in r for r in (res.get("skipped_reasons") or [])),
           res.get("skipped_reasons"))
    _check("S4d 接收方盘上无明文（未回落写盘）",
           _plaintext_files(B) == [], _plaintext_files(B))


def s5():
    print("== S5 非字符串 / 未知档 ⇒ 拒收且不回落 ==")
    for bad in (123, ["private"], "机密", "PUBLICX", ""):
        cgA, cgB, A, B, SW = _fresh()
        _seed_private(cgA)
        pack = E.export_pack(cgA, swarm=SW)["pack"]
        for it in pack["items"]:
            it["sensitivity"] = bad
        _resign(pack)
        pf = E.write_pack(pack, swarm=SW)["file"]
        res = E.import_pack(cgB, pf, swarm=SW)
        _check("S5 非法档 %r ⇒ imported==0" % (bad,),
               res.get("imported") == 0, res.get("imported"))
        _check("S5 非法档 %r ⇒ 盘上无明文" % (bad,), _plaintext_files(B) == [])
    # 空串按未知档处理（不得当作「未声明」回落）
    _check("S5z 空串也拒（不视作未声明）",
           E._item_sensitivity({"sensitivity": ""})[1] != "")


def s6():
    print("== S6 导入方密级不足 ⇒ 跳过且不降级落盘 ==")
    cgA, cgB, A, B, SW = _fresh(clearance="internal")   # B 只有 internal
    _seed_private(cgA)
    pf = _write(cgA, SW)
    res = E.import_pack(cgB, pf, swarm=SW)
    _check("S6a imported == 0（越权写入被拒）", res.get("imported") == 0,
           res.get("imported"))
    _check("S6b skipped == 1", res.get("skipped") == 1, res.get("skipped"))
    _check("S6c 理由点明密级不足",
           any("密级不足" in r for r in (res.get("skipped_reasons") or [])),
           res.get("skipped_reasons"))
    _check("S6d ★ 接收方盘上无明文（未降级落盘）",
           _plaintext_files(B) == [], _plaintext_files(B))
    # ★ list(...) 快照：本仓 md_cg/test_h4_sustain_snapshot.py 的 G1a 判据扫描
    # **全 md_cg 域（含测试模块）**，凡从 cg.index 取回的 nodes 一律要求先取
    # 快照（并发写索引时裸迭代会 RuntimeError: dictionary changed size）。
    # 项目方本件首版漏了这一处，被该守卫当场打红——记此以免复犯。
    _check("S6e 接收方索引无该节点",
           not any("xnode" in k for k in
                   list(cgB.index.get("nodes") or {})))


def s7():
    print("== S7 不误伤：internal 包正常导入并归档 ==")
    cgA, cgB, A, B, SW = _fresh()
    cgA.add("obs_int", _MARK, layer="knowledge",
            tags=["subject:x", "kind:note", _id.TAG_OBS],
            condition_space={"subject": "x"}, importance=0.6,
            verification_basis="data", sensitivity="internal")
    pf = _write(cgA, SW)
    res = E.import_pack(cgB, pf, swarm=SW)
    _check("S7a internal 包正常导入", res.get("imported") == 1, res)
    _check("S7b internal 包正常归档", bool(res.get("archived")),
           res.get("archived"))
    _check("S7c 无 archive_skipped 理由", res.get("archive_skipped") == "",
           res.get("archive_skipped"))
    _check("S7d 接收方密级 == internal",
           ((cgB.index.get("nodes") or {})
            .get((res.get("node_ids") or [None])[0]) or {})
           .get("sensitivity") == "internal")


def s8():
    print("== S8 identity.observe 缺省 sensitivity 行为逐位不变 ==")
    cgA, _cgB, A, _B, SW = _fresh()
    r1 = _id.observe(cgA, "s_old", "旧调用方不传 sensitivity")
    n1 = r1["node_id"]
    fm1 = (cgA.get(n1) or {}).get("frontmatter") or {}
    _check("S8a 不传 sensitivity 仍可写入", r1.get("ok") is True, r1)
    _check("S8b 落盘走缺省（非 private/secret ⇒ 不加密）",
           str(fm1.get("sensitivity") or _sec.DEFAULT_SENSITIVITY)
           not in crypto.ENCRYPTED_LEVELS, fm1.get("sensitivity"))
    _check("S8c 盘上可见明文（缺省档行为不变）",
           _plaintext_files(A, "旧调用方不传 sensitivity") != [],
           _plaintext_files(A, "旧调用方不传 sensitivity"))
    r2 = _id.observe(cgA, "s_new", "新调用方传 sensitivity", sensitivity="private")
    n2 = r2["node_id"]
    _check("S8d 传 sensitivity 则落盘该密级",
           ((cgA.get(n2) or {}).get("frontmatter") or {}).get("sensitivity")
           == "private")


def s9():
    print("== S9 反陈化：三处收口的理由在源码里 ==")
    ev = _src(os.path.join("md_cg", "evidence.py"))
    idt = _src(os.path.join("md_cg", "identity.py"))
    _check("S9a evidence 标注 issue #258", "issue #258" in ev)
    _check("S9b 写明病象（ENCRYPTED_LEVELS / 明文）",
           "ENCRYPTED_LEVELS" in ev and "明文" in ev)
    _check("S9c 写明「与 #164 同源」", "#164" in ev and "同源" in ev)
    _check("S9d 写明旧格式包拒收是**有意的行为变更**",
           "有意的行为变更" in ev or "旧格式包" in ev)
    _check("S9e identity.observe 标注 issue #258 与「既有调用方零变更」",
           "issue #258" in idt and "零变更" in idt)


def _prepatch_src():
    import subprocess

    def _g(*a):
        return subprocess.run(list(a), cwd=_REPO, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=60)
    lg = _g("git", "log", "-S_item_sensitivity", "--format=%H", "--",
            "md_cg/evidence.py")
    if lg.returncode == 0:
        shas = [x.strip() for x in (lg.stdout or "").splitlines() if x.strip()]
        if shas:
            src = _g("git", "show", shas[-1] + "^:md_cg/evidence.py")
            if src.returncode == 0:
                return src.stdout, "引入提交 %s 的父版本" % shas[-1][:8]
    src = _g("git", "show", "HEAD:md_cg/evidence.py")
    if src.returncode != 0:
        return None, "git show HEAD rc=%s" % src.returncode
    return src.stdout, "HEAD（本改动尚未提交）"


def s10():
    print("== S10 修复前原形（提交前/后都稳定）==")
    t, how = _prepatch_src()
    if t is None:
        _check("S10 取修复前源失败：%s" % how, False)
        return
    print("       （修复前源取自 %s）" % how)
    _check("S10a 修复前无 _item_sensitivity", "_item_sensitivity" not in t)
    _check("S10b 修复前 _collect 条目无 sensitivity",
           '"sensitivity": _node_sensitivity' not in t)
    _check("S10c 修复前无归档闸", "archive_skipped" not in t)


_GROUPS = (s1, s2, s3, s4, s5, s6, s7, s8, s9, s10)


def _run_groups():
    global _OK
    _OK = 0
    _BAD.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                   # noqa: BLE001
            _check("断言组 %s 抛异常：%s" % (g.__name__, exc), False)
            import traceback
            print(traceback.format_exc()[-600:])
    return len(_BAD)


def main():
    n = _run_groups()
    print()
    print("证据包密级通路守卫：%d 通过，%d 失败" % (_OK, n))
    return 1 if n else 0


_MUTATIONS = (
    ("V1 _collect 条目不带 sensitivity（回到病象）",
     '            "sensitivity": _node_sensitivity(cg, nid),\n',
     "", "S1"),
    ("V2 缺字段回落到缺省 internal（去掉 fail-closed）",
     '    if raw is None:\n        return None, "条目缺 sensitivity 字段（旧格式包一律拒收）"\n',
     '    if raw is None:\n        raw = _sec.DEFAULT_SENSITIVITY\n', "S4"),
    ("V3 去掉归档闸（含加密档仍落明文 JSON）",
     "        if sealed:\n",
     "        if False:\n", "S3"),
    ("V4 observe 不透传 sensitivity",
     '    if sensitivity is not None:\n        extra["sensitivity"] = sensitivity\n',
     "", "S2"),
)


def _reload():
    import importlib
    from md_cg import evidence as _e
    from md_cg import identity as _i
    importlib.reload(_i)
    importlib.reload(_e)
    globals()["E"] = _e
    globals()["_id"] = _i
    globals()["_sg"] = __import__("md_cg.subgraph", fromlist=["x"])


def _mutate():
    bad = []
    targets = {
        "V1": os.path.join(_REPO, "md_cg", "evidence.py"),
        "V2": os.path.join(_REPO, "md_cg", "evidence.py"),
        "V3": os.path.join(_REPO, "md_cg", "evidence.py"),
        "V4": os.path.join(_REPO, "md_cg", "identity.py"),
    }
    pristine = {}
    for p in set(targets.values()):
        with io.open(p, encoding="utf-8", newline="") as f:
            pristine[p] = f.read()
    if "_item_sensitivity" not in pristine[targets["V1"]]:
        print("  SOURCE-ALREADY-MUTATED：evidence.py 缺 _item_sensitivity")
        return 1
    for name, anchor, repl, want in _MUTATIONS:
        p = targets[name.split()[0]]
        orig = pristine[p]
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        try:
            if a_ not in orig:
                print("  ANCHOR-MISS %s" % name)
                bad.append(name)
                continue
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            _reload()
            _run_groups()
            reds = list(_BAD)
            hit = any(x.startswith(want) for x in reds)
            print("  %-4s %-52s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(reds), want,
                     "是" if hit else "否"))
            if not hit:
                bad.append(name)
        finally:
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(pristine[p])
            with io.open(p, encoding="utf-8", newline="") as f:
                if f.read() != pristine[p]:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
            _reload()
    if bad:
        print()
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print()
    print("定点变异自证：PASS（每处判据都被打红）")
    return 0


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
