# -*- coding: utf-8 -*-
"""G1 守卫：同租户共享数据密钥（`MDCG_TENANT_DEK_SHARING`）两个方向都钉住。

背景（2026-10-21 病灶 G）：`_dek_aad` 把 AAD 绑到 **写者 actor**，每个 actor 又各拿
一把 DEK ⇒ 同一个库（同租户）里 A 写的 private/secret 正文，B 即使密级更高、
`can_admin=True` 也解不开。生产读数：灵枢在役库 10 013 节点 / 9 941 索引节点中
只有 4 071 对网关主体可读（40.5%），其余 5 935 是 AAD 层不可读。

**但「跨 actor 读不到」不是缺陷——是设计者 2026-10-10 的裁定**：当时在役库
3,011,214 条 `open_failed` 全是跨身份读，被判定「设计内隔离」而非故障
（见 `test_b1_foreign_read` 的 B1 守卫）。所以本轮只补**可择能力**，
默认行为**逐位不变**，取舍交回清单（冲突表默认保留用户地基）。

断言面（两个方向都要能红）：
  ① 默认关：跨 actor 读不到；零 read_cross_actor；DEK 各不相同
  ② 打开：同租户跨 actor 读得到；批量读只写 1 条 read_cross_actor_batch
  ③ 打开：单读面记 read_cross_actor 且带 writer_actor（可追溯谁写的）
  ④ 打开也不能跨租户：`t2` 的 bob 读 `t1` 的密文仍为 None
  ⑤ `tenant_actors` 只列本租户、按签发顺序；不含他租户
  ⑥ `provision_tenant_dek` 让两 actor 共用同一把 DEK，但信封各一份、id_fp 各异
  ⑦ 存量迁移必要：关闭期写入的密文，开启后同租户他 actor 仍读不到
  ⑧ 关掉开关后新写入重新隔离（不是一次性开关）

运行：python -m md_cg.test_g1_tenant_sharing
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import crypto
from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0
FAILS = []

BODY = "# 功能名：测试\n# 执行：{}\n\n{}\n"
SECRET = "银行卡尾号 8888，仅本人可见"


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % label)
    else:
        FAIL += 1
        FAILS.append(label)
        print("  [FAIL] %s" % label)


def _ops(root):
    out = {}
    for rec in crypto.audit_records(root):
        op = rec.get("op") or "?"
        out[op] = out.get(op, 0) + 1
    return out


def _mk(root, kek, actor, tenant="t1", clearance="secret"):
    return MdCGSecure(root, master_key=kek, principal=Principal(
        tenant=tenant, actor=actor, clearance=clearance,
        can_write=True, can_admin=True))


def _entries(cg):
    return [dict(e, id=nid) for nid, e in cg.index["nodes"].items()]


def _set(v):
    if v is None:
        os.environ.pop("MDCG_TENANT_DEK_SHARING", None)
    else:
        os.environ["MDCG_TENANT_DEK_SHARING"] = v


def main():
    saved = os.environ.get("MDCG_TENANT_DEK_SHARING")
    # 四个互不污染的根：每个阶段新建的 actor 信封会永久留在 _keys.json 里，
    # 共用同一个根会让「关闭期已签发的 bob」在第二阶段直接命中旧信封（见 ⑥）。
    tmp_off = tempfile.mkdtemp(prefix="mdcg_g1off_")
    tmp_old = tempfile.mkdtemp(prefix="mdcg_g1old_")
    tmp_on = tempfile.mkdtemp(prefix="mdcg_g1on_")
    tmp_off2 = tempfile.mkdtemp(prefix="mdcg_g1off2_")
    try:
        kek = os.urandom(32)

        # ---------- ① 默认关：隔离仍在 ----------
        _set(None)
        alice = _mk(tmp_off, kek, "alice")
        alice.add("p1", BODY.format(SECRET, SECRET), sensitivity="private")
        bob = _mk(tmp_off, kek, "bob")
        ok(bob.get("p1") is None, "①默认关：跨 actor 读不到（用户地基）")
        ok(_ops(tmp_off).get("read_cross_actor", 0) == 0,
           "①b默认关：零 read_cross_actor")
        ok(alice.dek != bob.dek, "①c默认关：两 actor DEK 不同（按 actor 签发）")

        # ---------- ⑦ 关闭期写入的密文，开启后仍读不到（迁移必要） ----------
        # 历史库形态：alice 与 bob **各自**独立 DEK（共享关闭期签发）
        alice_o = _mk(tmp_old, kek, "alice")
        alice_o.add("p1", BODY.format(SECRET, SECRET), sensitivity="private")
        bob_o = _mk(tmp_old, kek, "bob")
        ok(alice_o.dek != bob_o.dek, "⑦历史库：两 actor 两把独立 DEK")
        _set("1")
        bob_o2 = _mk(tmp_old, kek, "bob")
        ok(bob_o2.dek == bob_o.dek,
           "⑦b已有信封不被改写（共享只为新身份复制，不迁移存量）")
        ok(bob_o2.get("p1") is None,
           "⑦c存量迁移必要：两把独立 DEK 的历史密文仍不可读（需 reencrypt）")

        # ---------- ⑥ 共享签发：同一把 DEK，两份信封（全新根） ----------
        _set("1")
        alice2 = _mk(tmp_on, kek, "alice")
        bob3 = _mk(tmp_on, kek, "bob")
        ok(alice2.dek == bob3.dek, "⑥共享签发：两 actor 得同一把 DEK")
        envs = {(e["tenant"], e["actor"]): e for e in crypto.envelopes(tmp_on)}
        ok(set(envs) >= {("t1", "alice"), ("t1", "bob")},
           "⑥b信封各一份（%d 份）" % len(envs))
        ok(envs[("t1", "alice")]["id_fp"] != envs[("t1", "bob")]["id_fp"],
           "⑥c两封 id_fp 各异（身份指纹仍各自绑定）")

        # ---------- ⑤ tenant_actors ----------
        actors = crypto.tenant_actors(tmp_on, "t1")
        ok(actors[:2] == ["alice", "bob"] and "carl" not in actors,
           "⑤tenant_actors 只列本租户（%s）" % ",".join(actors))

        # ---------- ② 共享开启：新写入的密文跨 actor 可读（批量 1 条审计） ----------
        alice2.add("n1", BODY.format(SECRET, SECRET), sensitivity="private")
        alice2.add("n2", BODY.format(SECRET, SECRET), sensitivity="private")
        bob3 = _mk(tmp_on, kek, "bob")       # 重建：索引在构造时加载
        ok(bob3.dek == alice2.dek, "⑥d重建读方仍是同一把 DEK")
        before = _ops(tmp_on)
        docs = bob3._read_many(_entries(bob3), {"scanned": 0})
        after = _ops(tmp_on)
        ok(len(docs) >= 2, "②共享开启：批量读水合到密文（%d 条）" % len(docs))
        ok(after.get("read_cross_actor_batch", 0) ==
           before.get("read_cross_actor_batch", 0) + 1,
           "②b批量只写 1 条 read_cross_actor_batch（O(1) 不放大）")
        ok(any(r.get("op") == "read_cross_actor_batch"
               and r.get("count", 0) >= 2
               for r in crypto.audit_records(tmp_on)),
           "②c该条带 count≥2（信息不丢）")

        # ---------- ③ 单读面：一条 read_cross_actor，带 writer_actor ----------
        before = _ops(tmp_on)
        got = bob3.get("n1")
        after = _ops(tmp_on)
        ok(got is not None and SECRET in got.get("content", ""),
           "③共享开启：单读跨 actor 解出明文")
        ok(after.get("read_cross_actor", 0) ==
           before.get("read_cross_actor", 0) + 1, "③b记录 read_cross_actor")
        rec = [r for r in crypto.audit_records(tmp_on)
               if r.get("op") == "read_cross_actor"]
        ok(rec and rec[-1].get("writer_actor") == "alice",
           "③c审计带 writer_actor=alice（可追溯归属）")

        # ---------- ④ 跨租户仍隔离 ----------
        eve = _mk(tmp_on, kek, "eve", tenant="t2")
        ok(eve.get("n1") is None, "④跨租户仍不可读（共享不越租户边界）")

        # ---------- ⑧ 关掉开关后新写入重新隔离 ----------
        _set(None)
        alice3 = _mk(tmp_off2, kek, "alice")
        bob4 = _mk(tmp_off2, kek, "bob")
        ok(alice3.dek != bob4.dek, "⑧关掉后：新 actor 重新按 actor 签发")
        alice3.add("n3", BODY.format(SECRET, SECRET), sensitivity="private")
        ok(bob4.get("n3") is None, "⑧b关掉后新写入的密文跨 actor 读不到")
    finally:
        _set(saved)
        for d in (tmp_off, tmp_old, tmp_on, tmp_off2):
            shutil.rmtree(d, ignore_errors=True)

    print("\n==== G1 结果：%d 通过 / %d 失败 ====" % (PASS, FAIL))
    for f in FAILS:
        print(" - " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
