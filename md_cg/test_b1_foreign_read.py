# -*- coding: utf-8 -*-
"""B1 守卫：read_foreign 与 open_failed 分家（跨身份预期隔离 ≠ 真异常）。

背景（2026-10-10 设计者裁定 B1）：在役库 `open_failed` 3,011,214 条（99.66%）全是
**跨身份读**（决定性读数 `only_self_reader_failed = 0`、`cross_only = 1353`，已排除
密钥丢失）——而 `open_failed` 的 reason 把「设计内隔离」与「密文被篡改」并列成一个
文案 ⇒ 误报淹没真信号。第一版修法：`crypto.seal_node` 在密文块携带**非敏感**指纹
`enc_id_fp = identity_fingerprint(tenant, actor)`，`_open_content` 解密前先比指纹。

**同日 DSH 端独立复核纠正其一（安全面）**：`enc_id_fp` 是密文块内的**未认证明文段**
（`crypto._node_aad` 只绑 node_id/tenant/actor，不含它），第一版让它**短路**解密 ⇒
一个可被篡改的字段决定了「是否执行唯一的完整性校验」，派生两个可操纵后果：
  ① 假阴性：只改指纹段（密文本体完好）⇒ 真密文被**静默拒读**、审计零留痕；
  ② 假阳性：谎报指纹＝读方自己（或写 `fm.enc_id_fp`）⇒ 走到解密 ⇒ 失败记
     `open_failed`（本该是「预期隔离」）⇒ 误报口径又回来了。
**纠正后语义：MAC 校验（`open_node`）是唯一判据**——先无条件试解密，成功即返回明文
（指纹是什么都不影响）；只有失败时才用**密文自带**指纹给失败**分类**：不等 ⇒
`read_foreign`（默认不记/可采样），其余（含旧格式无该段）⇒ `open_failed`。判据不再
回落可写 frontmatter `fm.enc_id_fp`。

**同日 DSH 端独立复核纠正其二（可观测性）**：原 `_read_foreign_sampled` 在采样关时
**先 return 后自增** ⇒ 默认配置下 `cg._read_foreign_seen` 从不被创建、越权探测信号
完全丢失。**纠正后：计数恒完整（与采样开关无关），采样只决定是否落审计**；计数经
`crypto_status()['read_foreign_seen']` 恒可读。默认「不落审计」口径**不变**（隔离读
是常态）。

断言面：
  ① 新格式密文块携带 enc_id_fp（且不含身份明文）
  ② 跨身份 + 采样开（MDCG_READ_FOREIGN_SAMPLE=1）⇒ 记 read_foreign、**不**记 open_failed
  ③ 跨身份 + 采样关（默认）⇒ 既不记 read_foreign 也不记 open_failed（零噪声）
  ④ 同身份读 ⇒ 正常解出明文，无 read_foreign / open_failed
  ⑤ **反向断言**：篡改密文（指纹仍在）⇒ 仍记 open_failed（真异常不静默）
  ⑥ 存量旧格式（无 enc_id_fp）⇒ 走旧路径：跨身份读仍记 open_failed（无需迁移）
  ⑦ **核心标志**：篡改指纹段（密文本体完好）⇒ **仍解出明文**、零噪声（缺陷一反面）
  ⑧ 谎报指纹（fm 写读方自己）⇒ **不再**制造假阳性；仍按密文自带指纹归类
  ⑨ 缺陷二：默认配置下计数**仍增长**且经 crypto_status 可读

运行：python -m md_cg.test_b1_foreign_read
"""
from __future__ import annotations

import os
import shutil
import tempfile

from . import crypto
from . import nodefile
from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _ops(root):
    """审计 ops 计数（payload-free 记录）。"""
    out = {}
    for r in crypto.audit_records(root):
        out[r.get("op")] = out.get(r.get("op"), 0) + 1
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_b1_")
    saved = os.environ.get("MDCG_READ_FOREIGN_SAMPLE")
    try:
        kek = os.urandom(32)
        body = "# 功能名：测试\n# 执行：{}\n\n{}\n"
        secret = "银行卡尾号 8888，仅本人可见"
        owner = Principal(tenant="t1", actor="alice", clearance="private",
                          can_write=True, can_admin=True)
        cg = MdCGSecure(tmp, principal=owner, master_key=kek)
        cg.add("priv1", body.format(secret, secret), sensitivity="private")

        # ---------- ① 密文块携带 enc_id_fp（非敏感） ----------
        rel = cg.index["nodes"]["priv1"]["path"]
        with open(os.path.join(tmp, rel), encoding="utf-8") as f:
            raw = f.read()
        _, c_priv = nodefile.loads(raw)
        fp_alice = crypto.identity_fingerprint("t1", "alice")
        ok(crypto.is_encrypted(c_priv)
           and crypto.enc_id_fp(c_priv) == fp_alice,
           "①新格式密文块携带 enc_id_fp（%s）" % crypto.enc_id_fp(c_priv))
        ok("alice" not in c_priv and "t1" not in c_priv.split(":", 1)[0],
           "①b指纹非敏感：块内不含身份明文（16 位 hex）")

        # ---------- ④ 同身份读 ⇒ 正常 ----------
        o = _ops(tmp)
        got = cg.get("priv1")
        ok(got is not None and secret in got.get("content", ""),
           "④同身份读正常解出明文")
        o2 = _ops(tmp)
        ok(o2.get("open_failed", 0) == o.get("open_failed", 0)
           and o2.get("read_foreign", 0) == o.get("read_foreign", 0),
           "④b同身份读零 open_failed / 零 read_foreign")

        reader = MdCGSecure(tmp, master_key=kek, principal=Principal(
            tenant="t1", actor="bob", clearance="secret",
            can_write=True, can_admin=True))

        # ---------- ② 跨身份 + 采样开 ⇒ read_foreign（不记 open_failed） ----------
        os.environ["MDCG_READ_FOREIGN_SAMPLE"] = "1"
        before = _ops(tmp)
        ok(reader.get("priv1") is None, "②跨身份读拿不到内容（预期隔离）")
        after = _ops(tmp)
        ok(after.get("read_foreign", 0) == before.get("read_foreign", 0) + 1,
           "②b记 read_foreign（%d→%d）"
           % (before.get("read_foreign", 0), after.get("read_foreign", 0)))
        ok(after.get("open_failed", 0) == before.get("open_failed", 0),
           "②c**不**记 open_failed（设计内隔离不再算异常）")

        # ---------- ③ 跨身份 + 采样关（默认）⇒ 零噪声 ----------
        os.environ.pop("MDCG_READ_FOREIGN_SAMPLE", None)
        before = _ops(tmp)
        ok(reader.get("priv1") is None, "③跨身份读仍拿不到内容")
        after = _ops(tmp)
        ok(after.get("read_foreign", 0) == before.get("read_foreign", 0)
           and after.get("open_failed", 0) == before.get("open_failed", 0),
           "③b默认不记 read_foreign / 不记 open_failed（零噪声）")

        # ---------- ⑤ 反向断言：篡改密文 ⇒ 仍记 open_failed ----------
        with open(os.path.join(tmp, rel), encoding="utf-8") as f:
            fm, content = nodefile.loads(f.read())
        payload = content[len(crypto.ENC_PREFIX):-len(crypto.ENC_SUFFIX)]
        if ":" not in payload:
            ok(False, "⑤前置：新格式密文应含 enc_id_fp 段"
                      "（实得旧格式 → 篡改断言不可达）")
        else:
            fp, b64 = payload.split(":", 1)
            b64 = ("AAAA" + b64[4:]) if not b64.startswith("AAAA") else \
                ("BBBB" + b64[4:])
            tampered = crypto.ENC_PREFIX + fp + ":" + b64 + crypto.ENC_SUFFIX
            ok(crypto.enc_id_fp(tampered) == fp_alice,
               "⑤篡改只动密文、指纹保持（fp=%s）" % crypto.enc_id_fp(tampered))
            before = _ops(tmp)
            ok(cg._open_content("priv1", fm, tampered) is None,
               "⑤b篡改密文解不出（返回 None）")
            after = _ops(tmp)
            ok(after.get("open_failed", 0) == before.get("open_failed", 0) + 1,
               "⑤c**篡改密文 ⇒ 仍记 open_failed**（%d→%d，真异常不静默）"
               % (before.get("open_failed", 0), after.get("open_failed", 0)))

        # ---------- ⑥ 存量旧格式 ⇒ 走旧路径（跨身份仍记 open_failed） ----------
        blob = crypto.seal_node("legacy payload", cg.dek, "lg1", "t1", "alice")
        inner = blob[len(crypto.ENC_PREFIX):-len(crypto.ENC_SUFFIX)]
        legacy = (crypto.ENC_PREFIX + inner.split(":", 1)[1]
                  + crypto.ENC_SUFFIX) if ":" in inner else blob
        ok(crypto.enc_id_fp(legacy) is None,
           "⑥旧格式密文无 enc_id_fp（存量为 1355 个此类节点）")
        before = _ops(tmp)
        ok(reader._open_content("lg1", {"sensitivity": "private"}, legacy)
           is None, "⑥b旧格式跨身份读仍解不出")
        after = _ops(tmp)
        ok(after.get("open_failed", 0) == before.get("open_failed", 0) + 1
           and after.get("read_foreign", 0) == before.get("read_foreign", 0),
           "⑥c旧路径保留：跨身份读记 open_failed（不记 read_foreign）"
           "（%d→%d）" % (before.get("open_failed", 0),
                          after.get("open_failed", 0)))

        # ---------- ⑦ 篡改指纹段（密文本体完好）⇒ 仍解出明文（核心标志） ----------
        with open(os.path.join(tmp, rel), encoding="utf-8") as f:
            fm, content = nodefile.loads(f.read())
        payload = content[len(crypto.ENC_PREFIX):-len(crypto.ENC_SUFFIX)]
        fp_seg, b64 = payload.split(":", 1)
        fp_flip_name = "f" * len(fp_seg)
        if fp_flip_name == fp_seg:
            fp_flip_name = "e" * len(fp_seg)
        fp_flip = (crypto.ENC_PREFIX + fp_flip_name + ":" + b64
                   + crypto.ENC_SUFFIX)
        ok(crypto.enc_id_fp(fp_flip) == fp_flip_name
           and crypto.enc_id_fp(fp_flip) != crypto.enc_id_fp(content),
           "⑦前置：指纹段已翻转（%s→%s）、密文本体逐字未动"
           % (fp_seg, fp_flip_name))
        before = _ops(tmp)
        got = cg._open_content("priv1", fm, fp_flip)
        after = _ops(tmp)
        ok(got is not None and secret in got,
           "⑦**篡改指纹段 ⇒ 仍解出明文**（缺陷一反面：未认证字段不再决定"
           "是否执行完整性校验）")
        ok(after.get("read_foreign", 0) == before.get("read_foreign", 0)
           and after.get("open_failed", 0) == before.get("open_failed", 0),
           "⑦b篡改指纹段 ⇒ 不产生 read_foreign / open_failed 噪声"
           "（原实现：默认下静默拒读、零留痕）")

        # ---------- ⑧ 谎报指纹＝读方自己 ⇒ 不再制造假阳性 ----------
        os.environ["MDCG_READ_FOREIGN_SAMPLE"] = "1"
        before = _ops(tmp)
        lie = reader._open_content(
            "priv1", {"sensitivity": "private",
                      "enc_id_fp": crypto.identity_fingerprint("t1", "bob")},
            content)
        after = _ops(tmp)
        ok(lie is None, "⑧谎报指纹的跨身份读仍拿不到内容")
        ok(after.get("open_failed", 0) == before.get("open_failed", 0),
           "⑧b谎报指纹**不再**制造假阳性（不记 open_failed；原实现：走到解密"
           "失败 ⇒ 记 open_failed）")
        ok(after.get("read_foreign", 0) == before.get("read_foreign", 0) + 1,
           "⑧c分类仍取**密文自带**指纹 ⇒ 正确记 read_foreign（%d→%d）"
           % (before.get("read_foreign", 0), after.get("read_foreign", 0)))
        os.environ.pop("MDCG_READ_FOREIGN_SAMPLE", None)

        # ---------- ⑨ 缺陷二：默认（采样关）下计数仍增长且可读 ----------
        fresh = MdCGSecure(tmp, master_key=kek, principal=Principal(
            tenant="t1", actor="bob", clearance="secret",
            can_write=True, can_admin=True))
        ok(hasattr(fresh, "_read_foreign_seen")
           and fresh._read_foreign_seen == 0
           and fresh.crypto_status().get("read_foreign_seen") == 0,
           "⑨a新建实例上计数属性**稳定存在**且为 0（缺陷二：原实现连读 3 次"
           "后 hasattr 仍 False）")
        ok(getattr(reader, "_read_foreign_seen", None) is not None,
           "⑨默认配置下 _read_foreign_seen 存在（原实现从不创建）")
        seen0 = reader.crypto_status().get("read_foreign_seen")
        for _ in range(3):
            reader._open_content("priv1", {"sensitivity": "private"}, content)
        seen1 = reader.crypto_status().get("read_foreign_seen")
        ok(isinstance(seen0, int) and seen1 == seen0 + 3,
           "⑨b默认（采样关）连读 3 次 ⇒ 计数 +3 且经 crypto_status 可读"
           "（%s→%s）" % (seen0, seen1))
    finally:
        if saved is None:
            os.environ.pop("MDCG_READ_FOREIGN_SAMPLE", None)
        else:
            os.environ["MDCG_READ_FOREIGN_SAMPLE"] = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nb1_foreign_read: {PASS} pass / {FAIL} fail")
    if FAILS:
        for f in FAILS:
            print(f" - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()