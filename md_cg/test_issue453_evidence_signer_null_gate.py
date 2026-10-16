# -*- coding: utf-8 -*-
"""跨实例证据包免签名通道与自报 created_at 守卫（issue #453，P1 Security）。

【守什么】
#453 报：`import_pack` 的缺签名判据看的是**包里的** `sig.signer != "null"`——
「我没签名」由对端自报即生效。默认策略（`require_peer_signature: false` 只表示
「不强制」，不等于「接受无签名」）下，任何节点把包写成
`{"sig": {"signer": "null", "signature": ""}}` 就能：

  站点 1  无密钥导入，落 `source:<对端自报来源>`（来源可伪造成任意节点）；
  站点 2  `created_at` 是对端自报的「版本号」且无上界——写成 9e15 后
          `_seen` 台账被毒化，此后该来源**一切**正常包 created <= 9e15
          ⇒ 永久 `replayed` 静默丢弃（回执仍是 `ok: true`），台账落盘持久。

复核**成立**（本守卫首跑即复现 issue 的 B / C1 / C2 读数，逐字一致）。

修法（报告 §四 三条，判据单点，全部落在 `import_pack`）：
  ① 站点 1：免签名通道由**本根策略显式选择**——`policy_for(subsystem)
     .get("signer") == "null"` 才放行空签名包；对端自报的 `sig.signer` 不再
     是通行证（默认策略 fail-closed）。
  ② 站点 2 之界：`created_at` 上下界 `[0, now + CREATED_FUTURE_SKEW(900s)]`，
     越界**整包拒收**留痕（与 #191-B「非有限值整包拒收」同口径；下界防负值
     把重放护栏反过来）。
  ③ 站点 2 之本：未签名包的自报 `created_at` **不得**写台账——版本号按 0
     （与「缺省按 0：只能新建、不能覆写」同语义），未签名内容永远覆写不了
     已签名内容；未签名导入另打 `TAG_UNSIGNED` 标记（来源未经密码学验证）。

判据：
  S1  默认策略下 `sig.signer="null"` 空签名包 → 拒收留痕、零落库、零台账。
  S2  显式 null 签名器策略（正门）→ 可导入，带 TAG_UNSIGNED；重导/改内容
      重导均 replayed（未签名=版本 0，防回滚）；`require_peer_signature=True`
      时空签名仍拒（正门不偷渡 required）。
  S3  created_at 上下界：9e15 / 负值 → 整包拒收（未签名与已签名两腿）；
      now+1 不误伤；**毒化序列**：now+600 未签名包放行后台账是 0.0（不是
      now+600），紧接的合法签名包 created=now+1 仍能导入（不被屏蔽）★★。
  S4  签名正道不回归（issue §六.1 本机密钥面不可用未测的腿）：合法签名包
      新建/更新可用；旧包重放仍拦（#191-B 原语义）；篡改仍拒；未签名包
      覆写不了已签名内容。
  S5  反陈化：判据与常量在源码里；旧的对端自报判据串不在。

运行：python -X utf8 -m md_cg.test_issue453_evidence_signer_null_gate
      python -X utf8 -m md_cg.test_issue453_evidence_signer_null_gate --mutate
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time

_TMP = tempfile.mkdtemp(prefix="i453g_")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "memroot")
# ★ 目录名不可用 "aux"——AUX 是 Windows 保留设备名（#245 实测踩到）。
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxstore")
os.environ["MDCG_SWARM_DIR"] = os.path.join(_TMP, "auxstore", "swarm")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ["MDCG_SIGNER_KEY_FILE"] = os.path.join(_TMP, "signer.key")
os.environ["MDCG_NODE_ID"] = "node-self"
os.environ.pop("MDCG_SIGNERS_FILE", None)          # 策略一律显式传参
os.makedirs(os.environ["MDCG_ROOT"], exist_ok=True)
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import evidence as E              # noqa: E402
from md_cg import signer as _signer          # noqa: E402
from md_cg.mdcos import MdCGOS               # noqa: E402

_OK = 0
_BAD = []
_N = [0]
_FROM = "peer-victim-node"
_XID = None                                   # 每次 _fresh 后由 build_pack 重算


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _fresh():
    """新建一对根 + 共享目录 + 各策略档，返回 (cg, SW, sf_default, sf_null, sf_hmac)。

    sf_*：sf_default 指向**不存在**的路径（回落默认策略 hmac-local /
    require_peer_signature=False——正是 issue 报告的默认面）；sf_null 显式
    选择 null 签名器（#453 修复的正门）；sf_hmac 是签名正道。
    """
    _N[0] += 1
    tag = "n%d" % _N[0]
    root = os.path.join(_TMP, tag + "_root")
    sw = os.path.join(_TMP, tag + "_swarm")
    os.makedirs(root, exist_ok=True)
    os.makedirs(sw, exist_ok=True)
    sf_default = os.path.join(_TMP, tag + "_absent_signers.json")   # 不写=默认
    sf_null = os.path.join(_TMP, tag + "_null.json")
    sf_hmac = os.path.join(_TMP, tag + "_hmac.json")
    _signer.set_policy(E.SUBSYSTEM, path=sf_null, signer="null",
                       sign_on=["handshake"])
    _signer.set_policy(E.SUBSYSTEM, path=sf_hmac, signer="hmac-local",
                       sign_on=["handshake", "evidence"])
    return MdCGOS(root), sw, sf_default, sf_null, sf_hmac


def _build_pack(created=None, text="观测-标记xyz", node="orig-1"):
    """构造攻击者完全可控的包（对端自报 sig.signer="null" 空签名）。"""
    global _XID
    p = {"kind": E.KIND, "schema": E.SCHEMA,
         "from_node": _FROM,
         "pack_id": "pack-4530000%03d" % _N[0],
         "created_at": time.time() if created is None else created,
         "subjects": ["s"],
         "items": [{"node_id": node, "subject": "s", "text": text,
                    "sensitivity": "internal", "ts": 1.0}],
         "sig": {"signer": "null", "signature": "", "signed": False}}
    _XID = E._xnode_id(_FROM, node)
    return p


def _sign_pack(p, sf):
    r = _signer.sign_for(E.SUBSYSTEM, E._pack_payload(p),
                         action=E.SIGN_ACTION, path=sf)
    p["sig"] = {"signer": r.get("signer"),
                "signature": r.get("signature") or "",
                "signed": bool(r.get("signed"))}
    return p


def _imp(cg, p, sw, sf):
    return E.import_pack(cg, p, swarm=sw, signers_file=sf, archive=False)


def _tags(cg, xid):
    return set(((cg.index.get("nodes") or {}).get(xid) or {}).get("tags") or [])


def _content(cg, xid):
    return ((cg.get(xid) or {}).get("content") or "").strip()


def _rejections(sw):
    p = os.path.join(E.inbox_dir(sw), "_rejected.jsonl")
    if not os.path.exists(p):
        return []
    out = []
    with io.open(p, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def s1():
    print("== S1 默认策略：sig.signer=\"null\" 免签名通道关死（站点 1）==")
    cg, SW, sf_def, sf_null, sf_hmac = _fresh()
    try:
        r = _imp(cg, _build_pack(), SW, sf_def)
        _check("S1a 拒收且理由点明缺签名",
               r.get("ok") is False and r.get("rejected") is True
               and "缺少签名" in (r.get("reason") or ""), r)
        _check("S1b 零落库（无 xnode 节点）",
               not [k for k in list(cg.index.get("nodes") or {})
                    if k.startswith("xnode_")],
               sorted(cg.index.get("nodes") or {}))
        recs = _rejections(SW)
        _check("S1c 拒收留痕落盘（_rejected.jsonl）",
               any("缺少签名" in (x.get("reason") or "") for x in recs),
               len(recs))
        _check("S1d 台账零写入", E._load_seen(cg) == {}, E._load_seen(cg))
    finally:
        cg.close()


def s2():
    print("== S2 显式 null 签名器策略：正门放行 + 未验签标记 + 防回滚 ==")
    cg, SW, sf_def, sf_null, sf_hmac = _fresh()
    try:
        p = _build_pack()
        r = _imp(cg, p, SW, sf_null)
        _check("S2a 显式 null 策略下可导入", r.get("ok") is True
               and r.get("imported") == 1, r)
        _check("S2b 带 TAG_UNSIGNED 标记（来源未经密码学验证）",
               E.TAG_UNSIGNED in _tags(cg, _XID)
               and "source:" + _FROM in _tags(cg, _XID),
               sorted(_tags(cg, _XID)))
        r2 = _imp(cg, p, SW, sf_null)
        _check("S2c 同包重导 replayed（未签名=版本 0，只能新建）",
               r2.get("ok") is True and r2.get("imported") == 0
               and r2.get("replayed") == 1, r2)
        before = _content(cg, _XID)
        r3 = _imp(cg, _build_pack(created=time.time() + 2,
                                  text="回滚-旧内容"), SW, sf_null)
        _check("S2d 改内容重导不覆写（防未签名回滚）",
               r3.get("imported") == 0 and _content(cg, _XID) == before,
               (r3, _content(cg, _XID)))
        sf_req = os.path.join(_TMP, "n%d_req.json" % _N[0])
        _signer.set_policy(E.SUBSYSTEM, path=sf_req, signer="null",
                           sign_on=["handshake"], require_peer_signature=True)
        r4 = _imp(cg, _build_pack(), SW, sf_req)
        _check("S2e require_peer_signature=True 时空签名仍拒（正门不偷渡）",
               r4.get("ok") is False and "对端签名" in (r4.get("reason") or ""),
               r4)
    finally:
        cg.close()


def s3():
    print("== S3 created_at 上下界 + 台账毒化不可达（站点 2）==")
    cg, SW, sf_def, sf_null, sf_hmac = _fresh()
    try:
        now = time.time()
        r = _imp(cg, _build_pack(created=9e15), SW, sf_null)
        _check("S3a 未签名 9e15 → 整包拒收（越界）",
               r.get("ok") is False and "越界" in (r.get("reason") or ""), r)
        _check("S3b 拒于台账前（_seen 无 9e15）",
               E._load_seen(cg) == {}, E._load_seen(cg))
        ps = _sign_pack(_build_pack(created=9e15), sf_hmac)
        r = _imp(cg, ps, SW, sf_hmac)
        _check("S3c 已签名 9e15 → 同样拒收（上界纵深到签名面）",
               r.get("ok") is False and "越界" in (r.get("reason") or ""), r)
        ps = _sign_pack(_build_pack(created=-1.0), sf_hmac)
        r = _imp(cg, ps, SW, sf_hmac)
        _check("S3d 负值 → 拒收（护栏不可反转）",
               r.get("ok") is False and "越界" in (r.get("reason") or ""), r)
        ps = _sign_pack(_build_pack(created=now + 1), sf_hmac)
        r = _imp(cg, ps, SW, sf_hmac)
        _check("S3e now+1 签名包不误伤", r.get("imported") == 1, r)
    finally:
        cg.close()

    cg, SW, sf_def, sf_null, sf_hmac = _fresh()
    try:
        now = time.time()
        # ★ 毒化序列（issue 守卫建议 ①+②）：偏移窗口内的未来时间戳能过界，
        # 但台账只准写 0；随后 created=now+1 的合法签名包必须仍能导入。
        r1 = _imp(cg, _build_pack(created=now + 600), SW, sf_null)
        _check("S3f 窗口内未来时间戳放行（不误伤近未来）",
               r1.get("ok") is True and r1.get("imported") == 1, r1)
        _check("S3g ★ 台账记 0.0 而非 now+600（自报版本不得入账）",
               E._load_seen(cg) == {_XID: 0.0}, E._load_seen(cg))
        ps = _sign_pack(_build_pack(created=now + 1), sf_hmac)
        r2 = _imp(cg, ps, SW, sf_hmac)
        _check("S3h ★ 紧随的合法签名包能导入（不被永久屏蔽）",
               r2.get("ok") is True and r2.get("imported") == 1
               and r2.get("replayed") == 0, r2)
    finally:
        cg.close()


def s4():
    print("== S4 签名正道不回归（issue §六.1 未测的腿）==")
    cg, SW, sf_def, sf_null, sf_hmac = _fresh()
    try:
        now = time.time()
        pa = _sign_pack(_build_pack(created=now - 10, text="旧观测"), sf_hmac)
        ra = _imp(cg, pa, SW, sf_hmac)
        _check("S4a 合法签名包可导入且无 TAG_UNSIGNED",
               ra.get("imported") == 1 and E.TAG_UNSIGNED not in _tags(cg, _XID),
               sorted(_tags(cg, _XID)))
        pb = _sign_pack(_build_pack(created=now, text="新观测"), sf_hmac)
        rb = _imp(cg, pb, SW, sf_hmac)
        _check("S4b 签名更新包可覆写（版本推进可用）",
               rb.get("imported") == 1 and _content(cg, _XID) == "新观测",
               (rb, _content(cg, _XID)))
        ra2 = _imp(cg, pa, SW, sf_hmac)
        _check("S4c 旧签名包重放仍拦（#191-B 原语义保持）",
               ra2.get("imported") == 0 and ra2.get("replayed") == 1
               and _content(cg, _XID) == "新观测", ra2)
        bad = _build_pack(created=now + 5, text="篡改观测")
        bad["sig"] = dict(pb["sig"])                # 旧签名配新载荷
        rbad = _imp(cg, bad, SW, sf_hmac)
        _check("S4d 篡改正文 → 验签仍拒",
               rbad.get("ok") is False, rbad)
        rc = _imp(cg, _build_pack(created=now + 600, text="未签名覆写"),
                  SW, sf_null)
        _check("S4e 未签名包覆写不了已签名内容（版本 0 < 台账）",
               rc.get("imported") == 0 and rc.get("replayed") == 1
               and _content(cg, _XID) == "新观测", rc)
    finally:
        cg.close()


def _src():
    return io.open(os.path.join(_REPO, "md_cg", "evidence.py"),
                   encoding="utf-8", errors="replace").read()


def s5():
    print("== S5 反陈化：判据与常量在源码里 ==")
    ev = _src()
    _check("S5a evidence 标注 issue #453", "issue #453" in ev)
    _check("S5b 常量在场（TAG_UNSIGNED / CREATED_FUTURE_SKEW）",
           "TAG_UNSIGNED" in ev and "CREATED_FUTURE_SKEW" in ev)
    _check("S5c 判据是本根策略（policy_for），非对端自报",
           "_signer.policy_for(subsystem, signers_file)" in ev
           and '(pack.get("sig") or {}).get("signer") != "null"' not in ev)
    _check("S5d 常量值不被顺手改掉",
           E.CREATED_FUTURE_SKEW == 900.0 and E.TAG_UNSIGNED == "sig:unsigned",
           (E.CREATED_FUTURE_SKEW, E.TAG_UNSIGNED))
    _check("S5e 「对端改不了」的旧断言已限定为签名前提",
           "只在有签名时成立" in ev)


_GROUPS = (s1, s2, s3, s4, s5)


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
    print("证据免签名通道守卫（#453）：%d 通过，%d 失败" % (_OK, n))
    return 1 if n else 0


# ---- 定点变异自证：每处收口回退即红 ----
_MUTATIONS = (
    ("V1 站点1回退：本地策略判据改回对端自报 sig.signer",
     "    if not signature and (_signer.policy_for(subsystem, signers_file)\n"
     "                          .get(\"signer\") != \"null\"):\n",
     "    if not signature and (pack.get(\"sig\") or {}).get(\"signer\") != \"null\":\n",
     "S1a"),
    ("V2 上界回退：created_at 越界不拒",
     "    if created < 0.0 or created > time.time() + CREATED_FUTURE_SKEW:\n",
     "    if False and (created < 0.0\n"
     "                  or created > time.time() + CREATED_FUTURE_SKEW):\n",
     "S3a"),
    ("V3 台账回退：未签名包用对端自报 created_at 入账",
     "    ver = created if signature else 0.0\n",
     "    ver = created\n",
     "S3g"),
    ("V4 标记回退：未签名导入不带 TAG_UNSIGNED",
     "            if not signature:\n"
     "                tags.append(TAG_UNSIGNED)\n",
     "",
     "S2b"),
)


def _reload():
    import importlib
    from md_cg import evidence as _e
    importlib.reload(_e)
    globals()["E"] = _e


def _mutate():
    bad = []
    target = os.path.join(_REPO, "md_cg", "evidence.py")
    with io.open(target, encoding="utf-8", newline="") as f:
        pristine = f.read()
    if "CREATED_FUTURE_SKEW" not in pristine:
        print("  SOURCE-ALREADY-MUTATED：evidence.py 缺 #453 修复")
        return 1
    for name, anchor, repl, want in _MUTATIONS:
        NL = "\r\n" if "\r\n" in pristine else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        try:
            if a_ not in pristine:
                print("  ANCHOR-MISS %s" % name)
                bad.append(name)
                continue
            with io.open(target, "w", encoding="utf-8", newline="") as f:
                f.write(pristine.replace(a_, r_, 1))
            _reload()
            _run_groups()
            hit = any(x.startswith(want) for x in _BAD)
            print("  %-4s %-46s 红项=%-3d 命中%s=%s"
                  % ("OK" if hit else "BAD", name, len(_BAD), want,
                     "是" if hit else "否"))
            if not hit:
                bad.append(name)
        finally:
            with io.open(target, "w", encoding="utf-8", newline="") as f:
                f.write(pristine)
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
