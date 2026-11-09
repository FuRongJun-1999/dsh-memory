"""判据：跨 actor 封装的密文，设计者能否按指纹反查读回（2026-11-06）。

病象（实测）：consolidate 写回的 290 个 mn_gw 节点用自家 DEK 封装，frontmatter 的
key_actor 却记成 dsh-memory；于是设计者令牌（can_admin）也解不开，`get()` 返回
None，检索里静默少掉 41% 的语料，而审计只记一句 read_foreign。

判据（正负控同源同数据，只换读方身份）：
  A0 正控：节点由 actor A 封装（A 的信封在 _keys.json 里）→ 读方 B（can_admin）读回原文
  A1 正控：读回后审计里出现 read_cross_actor（不是静默放行）
  B0 负控：读方 B 读自己封装的节点 → 原文照旧，且**不**产生 read_cross_actor
  B1 负控：密文被改坏（截断 base64）→ 仍不可读，不因反查而 fail-open
  B2 负控：密文指纹指向**不存在的** actor → 不可读（反查未命中不得退化成明文）

跑法：PYTHONPATH=/home/ubuntu/mdcg python3 -X utf8 -m md_cg.test_read_cross_actor
"""

import json
import os
import shutil
import tempfile

from . import crypto
from .mdcos import MdCGSecure
from .security import Principal

FAILED = []
PASSED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  PASS %s %s" % (name, detail))
    else:
        FAILED.append(name)
        print("  FAIL %s %s" % (name, detail))


def _cg(root, actor, kek):
    p = Principal(actor=actor, role="designer", tenant="default",
                  clearance="private", can_write=True, can_admin=True)
    return MdCGSecure(root, principal=p, master_key=kek)


def _audit_ops(root, node_id):
    ops = []
    p = os.path.join(root, "_crypto.jsonl")
    if not os.path.isfile(p):
        return ops
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("node_id") == node_id:
                ops.append(rec.get("op"))
    return ops


def main():
    tmp = tempfile.mkdtemp(prefix="cross_actor_")
    root = os.path.join(tmp, "data")
    os.makedirs(root)
    kek = crypto.load_master_key(os.path.join(tmp, "master.key"), create=True)

    a = _cg(root, "actor-a", kek)
    b = _cg(root, "actor-b", kek)

    # A 封装一条 private 节点（private ⇒ 必然加密）
    nid = "cross_a_01"
    a.add(nid, "A 封装的正文：密文与 key_actor 必须一致才读得到。",
          layer="knowledge", sensitivity="private", importance=0.4)
    fm_a, c_a = a._read(a.index["nodes"][nid])
    check("A0a A 自己的密文指纹 = A 的身份指纹",
          crypto.enc_id_fp(c_a) == crypto.identity_fingerprint("default", "actor-a"),
          crypto.enc_id_fp(c_a))

    # B 读 A 的节点：反查命中后应能读回（B 必须重新构造：索引是构造期快照，
    # 早于 A 的写入就不会有这条 —— 这是测试自身的坑，不是被测行为）
    b = _cg(root, "actor-b", kek)
    d_b = b.get(nid, probe=True)
    ok_b = bool(d_b) and "A 封装的正文" in (d_b.get("content") or "")
    check("A0 B（can_admin）按指纹反查读回 A 的密文", ok_b,
          "" if not d_b else (d_b.get("content") or "")[:24])
    check("A1 读回留了 read_cross_actor 审计",
          "read_cross_actor" in _audit_ops(root, nid))

    # B 自己封装的节点：正常读，且不触发跨 actor 审计
    nid2 = "cross_b_01"
    b.add(nid2, "B 自己的正文。", layer="knowledge", sensitivity="private")
    d_b2 = b.get(nid2, probe=True)
    check("B0 读自己的节点正常", bool(d_b2) and "B 自己的正文" in (d_b2.get("content") or ""))
    check("B0b 自己读自己不产生 read_cross_actor",
          "read_cross_actor" not in _audit_ops(root, nid2))

    # 密文被改坏：不得 fail-open
    path = os.path.join(root, b.index["nodes"][nid2]["path"])
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    head, sep, tail = raw.partition("mdcg-enc:v1:")
    fp, _, b64 = tail.partition(":")
    broken = head + sep + fp + ":" + b64[: len(b64) // 2] + " -->"
    with open(path, "w", encoding="utf-8") as f:
        f.write(broken)
    b2 = _cg(root, "actor-b", kek)
    check("B1 密文改坏后不可读（不 fail-open）", b2.get(nid2, probe=True) is None)

    # 指纹指向不存在的 actor
    nid3 = "cross_a_02"
    a.add(nid3, "A 的第二条。", layer="knowledge", sensitivity="private")
    path3 = os.path.join(root, a.index["nodes"][nid3]["path"])
    with open(path3, encoding="utf-8") as f:
        raw3 = f.read()
    head3, sep3, tail3 = raw3.partition("mdcg-enc:v1:")
    _fp3, _, b64_3 = tail3.partition(":")
    with open(path3, "w", encoding="utf-8") as f:
        f.write(head3 + sep3 + "deadbeefdeadbeef" + ":" + b64_3)
    b3 = _cg(root, "actor-b", kek)
    check("B2 指纹指向不存在的 actor → 不可读", b3.get(nid3, probe=True) is None)

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n== %d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 2


if __name__ == "__main__":
    raise SystemExit(main())
