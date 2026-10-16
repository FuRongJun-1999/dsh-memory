# -*- coding: utf-8 -*-
# 功能名：issue #446 守卫——密文形状信任收口（is_encrypted 严格化 + 密封试解短路 + 读面止血）
# 生效条件：md_cg/crypto.py 的 `is_encrypted`（严格结构判据）/ `open_node`（失败只抛
#           CryptoError）、md_cg/mdcos.py 的 `_seal_content`（短路只认本库可 MAC 试解
#           载体）/ `_open_content`（兜底 except，绝不抛穿）在位时成立；
#           沙箱条件：所有库根一律 tempfile.mkdtemp + os.urandom(32) 合成主密钥，
#           绝不触在役库、在役密钥与真实 master.key 文件。
# 子功能：钉住 issue #446 的两个站点与四条期望：
#   A 判据单点：`is_encrypted` 只认「前缀内结构可解析」的载体块（伪造前缀一律明文）
#   B 密封短路：`_seal_content` 只对本库可解载体短路；伪造载体按明文重封（盘上必为
#     真密文、seal 审计留痕）；真密文重放不二封；locked + 伪造体 fail-closed 拒写
#   C 落盘闸②：`_check_sensitivity_landing` 对「加密级 + 伪造前缀串」fail-closed 抛
#     ValueError（修前同一形状判据被骗过 ⇒ fail-open 放行明文落盘）
#   D 读面止血：伪造前缀节点（新写 / 历史毒化盘）不得让 get/search/recall 抛穿
#     （修前 UnicodeEncodeError/binascii.Error 抛穿属主检索面＝跨权限 DoS）
#   E 反向腿：正常 private 写入仍加密可读回、跨身份仍不可读、public/internal 仍明文
# 执行：python -X utf8 -m md_cg.test_issue446_enc_shape_gate
# 验证方式：本文件自跑（自带断言计数与退出码 rc=0/1）。定点变异自证（抽回单点修复
#           ⇒ 本守卫必红；以下均本机实跑核验）：
#   变异① is_encrypted 改回 `content.lstrip().startswith(ENC_PREFIX)`
#          ⇒ 9 项红：A3–A7 / B7（locked+伪造体被形状短路放行落盘）/ B8 / C1 / D2；
#   变异② _seal_content 恢复「形状即短路」（去掉 MAC 试解，is_encrypted 保持严格）
#          ⇒ B3/B3b 红（结构合法伪装体原样落盘＝形状短路铁证；真重封必换载体、
#          且属主可解回原文）；
#   诚实边界（纵深分层实测）：`open_node` 的 ValueError→CryptoError 转换（③）与
#          `_open_content` 的兜底 except（④）单独抽回**无独立红项**——严格判据已把
#          坏形状挡在解码之前；但与①叠加（①+③+④ 同时抽回）时，add 的密封试解
#          直接抛 UnicodeEncodeError ⇒ 本守卫在 B 段即崩（rc=1，非干净红项），
#          正是 issue #446 站点 1 抛穿症状在写面的重演。D3/D3b 另钉 open_node 的
#          契约形状（非载体直通 / 伪装体只抛 CryptoError）。
# 不适用条件：情感交互｜闲聊｜纯查询无改动；`_is_encrypted_level`（按密级档的脱敏
#           判据，#345/#348/#315 族）与密钥信封/轮换面（test_p13/test_b1）不在本席面内。
import base64
import os
import shutil
import sys
import tempfile

from . import crypto, mdcg, nodefile
from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0
_FAILS = []


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        _FAILS.append(name)
        print("  [FAIL] %s · %s" % (name, detail))


P = crypto.ENC_PREFIX
S = crypto.ENC_SUFFIX
#: 伪造前缀族：正文形状调用方可控，其余部分随意
FAKE_CN = P + "这个根本不是密文，是攻击者可控的正文" + S          # 非 ascii 载体
FAKE_B64 = P + "not!valid@base64#$$$" + S                        # 非法字母表
FAKE_LOOK = P + "0123456789abcdef:" + base64.b64encode(
    b" forged-but-well-formed payload ").decode("ascii") + S      # 结构合法伪装体
PLAIN_MARK = "这个根本不是密文"


def _owner(root, kek, actor="owner", clearance="secret"):
    return MdCGSecure(root, master_key=kek, principal=Principal(
        tenant="t1", actor=actor, clearance=clearance,
        can_write=True, can_admin=True))


def _disk_body(root, cg, nid):
    p = os.path.join(root, cg.index["nodes"][nid]["path"])
    with open(p, encoding="utf-8") as f:
        raw = f.read()
    return raw, nodefile.loads(raw)[1]


def main():
    print("【A】is_encrypted 严格判据（单点）：只认前缀内结构可解析的载体块")
    dek = os.urandom(32)
    real = crypto.seal_node("真密文负载", dek, "n1", "t1", "alice")
    inner = real.strip()[len(P):-len(S)]
    legacy = P + inner.split(":", 1)[1] + S                 # 剥指纹段＝存量旧格式
    ok("A1 新格式真密文 → True", crypto.is_encrypted(real))
    ok("A2 旧格式真密文 → True（向后兼容，不迁移）",
       crypto.is_encrypted(legacy))
    ok("A3 伪造前缀+中文正文 → False（修前 True）",
       not crypto.is_encrypted(FAKE_CN), repr(FAKE_CN[:36]))
    ok("A4 伪造前缀+非法 base64 字母表 → False（修前 True）",
       not crypto.is_encrypted(FAKE_B64), repr(FAKE_B64[16:40]))
    ok("A5 指纹段非 16 位 hex → False",
       not crypto.is_encrypted(P + "xyz:" + base64.b64encode(b"x" * 28)
                               .decode() + S))
    ok("A6 前缀后尾随杂文 → False（修前 True）",
       not crypto.is_encrypted(real + " 尾随明文"))
    ok("A7 空载体 → False", not crypto.is_encrypted(P + S))
    ok("A8 结构合法伪装体 → True（形状边界：真伪由 B 组试解与读面 MAC 裁定）",
       crypto.is_encrypted(FAKE_LOOK))
    ok("A9 None / 空串 → False",
       crypto.is_encrypted(None) is False and crypto.is_encrypted("") is False)

    print("\n【B】_seal_content 短路只认「本库可 MAC 试解」的载体（伪造体重封）")
    root = tempfile.mkdtemp(prefix="i446_b_")
    try:
        kek = os.urandom(32)
        cg = _owner(root, kek)
        for tag, body, nid in (("B1", FAKE_CN, "own_fake_cn"),
                               ("B2", FAKE_B64, "own_fake_b64"),
                               ("B3", FAKE_LOOK, "own_fake_look")):
            cg.add(nid, body, sensitivity="private")
            raw, c = _disk_body(root, cg, nid)
            ok("%s 声明 private + 伪造前缀 → 盘面真密文（明文不落盘）" % tag,
               crypto.is_encrypted(c) and PLAIN_MARK not in raw
               and "forged-but-well-formed" not in raw
               # 伪装体自身过严格形状判据（A8）——「盘面==原文」恰是形状短路
               # 落盘的铁证；真重封必然换载体（AEAD 随机 nonce ⇒ 必不相同）。
               and c.strip() != body.strip(),
               "盘面==原文: %s" % (c.strip() == body.strip()))
        ok("B3b 伪装体重封后属主可解回原文（盘上确为本库真密文）",
           (_disk_body(root, cg, "own_fake_look")[1].strip()
            != FAKE_LOOK.strip())
           and (cg.get("own_fake_look") or {}).get("content",
                                                   "").strip()
           == FAKE_LOOK.strip())
        ok("B4 fm 密级如实为 private（声明↔落盘一致）",
           _disk_body(root, cg, "own_fake_cn")[1] is not None
           and cg.get("own_fake_cn")["frontmatter"]["sensitivity"] == "private")
        recs = crypto.audit_records(root)
        ok("B5 伪造体重封有 seal 审计留痕（修前零留痕）",
           any(r.get("op") == "seal" and r.get("node_id") == "own_fake_cn"
               for r in recs), "seal 行数=%d" % sum(
               1 for r in recs if r.get("op") == "seal"))
        # 真密文重放：把盘面密文原样作为正文写回同 id ⇒ 试解成功 ⇒ 逐字节不变
        _raw1, c1 = _disk_body(root, cg, "own_fake_cn")
        cg.add("own_fake_cn", c1, sensitivity="private")
        _raw2, c2 = _disk_body(root, cg, "own_fake_cn")
        ok("B6 真密文重放不二封（逐字节不变）", c1 == c2,
           "len %d vs %d" % (len(c1), len(c2)))
        cg2 = _owner(root, kek, actor="owner2")
        cg2.lock()
        raised = None
        try:
            cg2.add("locked_fake", FAKE_CN, sensitivity="private")
        except crypto.LockedError as e:
            raised = e
        ok("B7 locked + 伪造前缀 private → LockedError fail-closed 拒写",
           raised is not None
           and not os.path.exists(os.path.join(root, "knowledge/orphan",
                                               "locked_fake.md")),
           repr(raised)[:60])
        cg.add("low_fake_int", FAKE_CN, sensitivity="internal")
        _raw, c = _disk_body(root, cg, "low_fake_int")
        ok("B8 internal + 伪造前缀 → 照常写入、按明文语义落盘（非加密级不密封）",
           c.strip() == FAKE_CN.strip() and not crypto.is_encrypted(c))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n【C】落盘闸②：加密级 + 伪造前缀串 → fail-closed（修前 fail-open）")
    raised = None
    try:
        mdcg._check_sensitivity_landing("n1", "private", "private", FAKE_CN)
    except ValueError as e:
        raised = e
    ok("C1 闸②对伪造前缀串抛 ValueError（修前被同一形状判据骗过放行）",
       raised is not None and "明文落盘" in str(raised), repr(raised)[:70])
    dek2 = os.urandom(32)
    sealed = crypto.seal_node("payload", dek2, "n1", "t1", "alice")
    ok("C2 闸②对真密文放行",
       mdcg._check_sensitivity_landing("n1", "private", "private", sealed)
       is None)

    print("\n【D】读面止血：伪造前缀节点不得让 get/search/recall 抛穿（跨权限 DoS）")
    root = tempfile.mkdtemp(prefix="i446_d_")
    try:
        kek = os.urandom(32)
        # 低权同租户写者（clearance=private）灌两条毒节点；owner 另开私毒节点
        peer = MdCGSecure(root, master_key=kek, principal=Principal(
            tenant="t1", actor="peer", clearance="private", can_write=True))
        peer.add("peer_fake", FAKE_CN, sensitivity="private")
        peer.add("peer_fake_b64", FAKE_B64, sensitivity="private")
        own = _owner(root, kek)
        own.add("own_fake", FAKE_CN, sensitivity="private")
        # 历史毒化盘：手工把伪前缀明文写进 private 节点文件（修前遗留形态）
        p_poison = os.path.join(root, own.index["nodes"]["own_fake"]["path"])
        with open(p_poison, encoding="utf-8") as f:
            fm_p, _ = nodefile.loads(f.read())
        with open(p_poison, "w", encoding="utf-8") as f:
            f.write(nodefile.dumps(fm_p, FAKE_CN))

        reader = _owner(root, kek, actor="owner")   # 属主（另一进程语义）
        faces = {
            "mdcg_get(peer 伪前缀节点)": lambda: reader.get("peer_fake"),
            "mdcg_get(毒化盘节点)": lambda: reader.get("own_fake"),
            "mdcg_search": lambda: reader.search("测试"),
            "mdcg_recall": lambda: reader.recall("测试"),
        }
        for name, fn in faces.items():
            try:
                fn()
                ok("D1 %s 正常返回不抛穿" % name, True)
            except Exception as e:                  # noqa: BLE001
                ok("D1 %s 正常返回不抛穿" % name, False,
                   "%s: %s" % (type(e).__name__, str(e)[:80]))
        ok("D2 毒化盘 private 节点按明文语义可读（形状不再被信任）",
           (reader.get("own_fake") or {}).get("content", "").strip()
           == FAKE_CN.strip())
        ok("D3 open_node：非载体原样直通（不解码不抛）",
           crypto.open_node(FAKE_CN, dek2, "n1", "t1", "alice") == FAKE_CN)
        try:
            crypto.open_node(FAKE_LOOK, dek2, "n1", "t1", "alice")
            ok("D3b open_node：结构合法伪装体 → CryptoError（不漏 binascii/"
               "UnicodeEncodeError）", False, "未抛")
        except crypto.CryptoError:
            ok("D3b open_node：结构合法伪装体 → CryptoError（不漏 binascii/"
               "UnicodeEncodeError）", True)
        except ValueError as e:
            ok("D3b open_node：结构合法伪装体 → CryptoError（不漏 binascii/"
               "UnicodeEncodeError）", False, "漏抛 %s" % type(e).__name__)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n【E】反向腿：正常语义零误伤")
    root = tempfile.mkdtemp(prefix="i446_e_")
    try:
        kek = os.urandom(32)
        cg = _owner(root, kek)
        secret = "银行卡尾号 8888，仅本人可见"
        cg.add("priv_ok", "# 功能名：x\n" + secret, sensitivity="private")
        cg.add("pub_ok", "公开知识：Python 用 PEP8", sensitivity="public")
        _raw, c = _disk_body(root, cg, "priv_ok")
        ok("E1 正常 private 写入仍加密（盘面不含明文）",
           crypto.is_encrypted(c) and secret not in _raw)
        ok("E2 同身份读回明文（加密存储不损可读性）",
           secret in (cg.get("priv_ok") or {}).get("content", ""))
        other = _owner(root, kek, actor="bob", clearance="secret")
        ok("E3 跨身份仍不可读（身份一致性零回归）", other.get("priv_ok") is None)
        ok("E4 public 明文可读回",
           "PEP8" in (cg.get("pub_ok") or {}).get("content", ""))
        got = (cg.get("priv_ok") or {}).get("content", "")
        ok("E5 解密产物与密文判据一致（明文不再被误判为密文）",
           not crypto.is_encrypted(got))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n==== issue #446 守卫：%d 通过%s ====" % (
        PASS, "，%d 失败：%s" % (FAIL, "; ".join(_FAILS)) if _FAILS else ""))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
