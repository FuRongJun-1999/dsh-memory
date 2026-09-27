# -*- coding: utf-8 -*-
"""N184 守卫（第 23 轮，2026-09-28）：_keys.json 并发 provision 丢失更新——
陈旧快照整份写回无痕抹除他身份信封。

病灶（crypto.py:299-329 / :287-290，本轮 HEAD 分诊复核在位）：
provision_dek 先 _load_keys 读快照（:306）、经 AEAD 签发后按该快照经
_save_keys（:328）整份写回（fsutil.atomic_write 仅 tmp+rename 防撕裂，
无文件锁、无写前对账）。两写者交错——A 读 t0 快照 → B 签发落盘 →
A 按 t0 陈旧快照写回——B 的信封无痕抹除：旧密文永久不可解，全程无
告警无备份无审计。N139（load_error 拒重签）只堵「损坏回落→静默重签」
形态，并发写回形态无闸。触发面无需攻击者：hive/exec.py:845 每次工具
调用新建 MdCGSecure → _init_crypto → provision_dek（mdcos.py:3694-3696），
worker 首次 lingshu_cg 与设计者会话首条 private 写并发即中招。

红守卫（哑 KEK=os.urandom(32) + 系统临时目录，零真实状态；对齐桩只在
写点对齐调度、读与签发全走真实代码路径，等价 OS 调度竞态窗口）：
  R1 交错复现（确定性）：一次性 _load_keys 桩把 worker 的读定格在 t0
     （designer 落盘前从盘上真实读到的空快照，不伪造任何数据）——
     worker 后写不得抹除 designer 先签信封，designer 已密封节点必须
     仍可解（修复前：envelopes 只剩 worker，解封/解密全灭）；
  R2 真并发跨身份（save 点 Barrier 对齐 × N 轮）：双线程分别 provision
     两个身份，任一轮任一信封丢失即红（修复前每轮必红；修复后被写锁
     挡在临界区外，对齐窗自然超时属预期，捕获后照常落盘）；
  R2b 对齐桩自检：绕开写锁直呼写点，双写者必须同窗落盘——自证 R2 的
     红条件有效（修复前的红不是假红）；
  R3 真并发同身份幂等：双线程同 (tenant, actor) 并发 provision——修后
     临界区内互见，应得同一 DEK；修复前各签各的，一方 DEK 被抹；
  R4 写前对账机制断言：_save_keys 盘面已有而快照没有的信封必须保留
     （防线纵深，兜底任何陈旧快照写者）；盘面 load_error 时拒写且
     原字节不动（N139 同闸延申到写点）；
  R5 rotate 零误伤：rotate 换新密钥生效、同键以本次写回为准（不得被
     对账复活旧信封），他身份信封不受 rotate 影响。
运行：python -m md_cg.test_n184_keys_concurrent_provision
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import threading

from . import crypto
from .crypto import (LockedError, open_node, provision_dek, seal_node,
                     unwrap_dek)

PASS = FAIL = 0
FAILS = []

# 对齐窗超时必须短于 provision_dek 写锁超时（10s）：修复后另一写者被锁
# 挡在临界区外、对齐自然超时（BrokenBarrierError），捕获后照常落盘，无死锁。
ALIGN_TIMEOUT = 0.3
ROUNDS = 12


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:110])


def _unwrap(root, kek, tenant, actor):
    try:
        return unwrap_dek(root, kek, tenant, actor), None
    except crypto.CryptoError as e:
        return None, e


def _read(p):
    with open(p, "rb") as f:
        return f.read()


def _envelopes(root):
    return set((_load_keys_real(root).get("envelopes") or {}).keys())


_load_keys_real = crypto._load_keys


class _AlignedSave:
    """save 点对齐桩：两个写者都到写点再放行（读与签发全真实路径）。

    只对齐调度（等价 OS 竞态窗），不伪造任何数据。对齐未达成（修复后
    被写锁挡在临界区外）属预期形态，BrokenBarrierError 吞掉照常落盘。
    """

    def __init__(self, n=2):
        self.barrier = threading.Barrier(n, timeout=ALIGN_TIMEOUT)
        self.real = crypto._save_keys
        self.aligned = 0

    def __enter__(self):
        crypto._save_keys = self._save
        return self

    def _save(self, root, data):
        try:
            self.barrier.wait()
            self.aligned += 1
        except threading.BrokenBarrierError:
            self.barrier.abort()
        return self.real(root, data)

    def __exit__(self, *exc):
        crypto._save_keys = self.real
        return False


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tmp = tempfile.mkdtemp(prefix="mdcg_n184_")
    kek = os.urandom(32)           # 哑 KEK：仅本守卫用，绝不触真实主密钥
    try:
        # ---------- R1 交错复现（确定性红） ----------
        print("== R1 交错复现：worker 按 t0 陈旧快照写回不得抹除 designer 信封 ==")
        root1 = os.path.join(tmp, "r1")
        os.makedirs(root1)
        t0_snapshot = _load_keys_real(root1)     # t0：designer 落盘前的真实盘面
        dek_d = provision_dek(root1, kek, "tenantA", "designer")
        text = "设计者私有笔记：密钥与凭证管理要点"
        sealed = seal_node(text, dek_d, "node1", "tenantA", "designer")
        check("R1a designer 先签 + 密封成功",
              dek_d is not None and "tenantA|designer" in _envelopes(root1))
        # 一次性 _load_keys 桩：worker 的读定格在 t0（只此一读，其余真实）
        state = {"used": False}

        def frozen_once(root):
            if not state["used"] and root == root1:
                state["used"] = True
                return t0_snapshot
            return _load_keys_real(root)

        crypto._load_keys = frozen_once
        try:
            dek_w = provision_dek(root1, kek, "tenantA", "hive-worker")
        finally:
            crypto._load_keys = _load_keys_real
        check("R1b worker provision 完成（真实代码路径）", dek_w is not None)
        env_after = _envelopes(root1)
        check("R1c designer 信封幸存（整份写回不得抹除他身份信封）",
              "tenantA|designer" in env_after,
              f"envelopes={sorted(env_after)}")
        dek_d2, e_d = _unwrap(root1, kek, "tenantA", "designer")
        check("R1d designer DEK 仍可解封", dek_d2 == dek_d,
              f"exc={e_d if e_d else '解封值不符'}")
        # t3（证据场景）：designer 重进（真实再签路径）——信封被抹时此处会
        # 无告警静默重签一把新 DEK；t4：旧密文用重进所得 DEK 永久解不开。
        dek_d3 = provision_dek(root1, kek, "tenantA", "designer")
        check("R1e designer 重进取回同一 DEK（静默重签被阻断）",
              dek_d3 == dek_d, f"重签={'是' if dek_d3 != dek_d else '否'}")
        try:
            opened = open_node(sealed, dek_d3, "node1", "tenantA", "designer")
        except crypto.CryptoError:
            opened = None
        check("R1f designer 已密封节点仍可解（永久静默丢失被阻断）",
              opened == text,
              f"opened={'原文' if opened == text else 'None（AEAD 校验失败）'}")
        dek_w2, e_w = _unwrap(root1, kek, "tenantA", "hive-worker")
        check("R1g worker 自己的 DEK 也应可解封", dek_w2 == dek_w, f"exc={e_w}")

        # ---------- R2 真并发跨身份（save 点对齐 × N 轮） ----------
        print("== R2 真并发跨身份：双线程 provision 任一信封丢失即红 ==")
        lost = []
        aligned_rounds = 0
        for i in range(ROUNDS):
            root2 = os.path.join(tmp, f"r2_{i}")
            os.makedirs(root2)
            start = threading.Barrier(2, timeout=10)
            out = {}

            def _prov(actor):
                start.wait()
                out[actor] = provision_dek(root2, kek, f"t{i}", actor)

            with _AlignedSave() as al:
                ths = [threading.Thread(target=_prov, args=(a,),
                                        daemon=True)
                       for a in ("designer", "hive-worker")]
                for t in ths:
                    t.start()
                for t in ths:
                    t.join(30)
            aligned_rounds += 1 if al.aligned >= 1 else 0
            want = {f"t{i}|designer", f"t{i}|hive-worker"}
            got = _envelopes(root2)
            for a in ("designer", "hive-worker"):
                d, e = _unwrap(root2, kek, f"t{i}", a)
                if a not in {g.split("|", 1)[1] for g in got} or d != out.get(a):
                    lost.append((i, a, str(e)))
        check(f"R2 {ROUNDS} 轮并发零信封丢失（对齐达成 {aligned_rounds}/{ROUNDS} 轮）",
              not lost, f"丢失明细={lost[:3]}")

        # R2b 红条件有效性自证：绕开 provision_dek（即绕开写锁）直呼 _save_keys，
        # 对齐桩必须能让双写者同窗落盘——证明 R2 的对齐机制本身有效（修复前
        # R2 的红不是假红）；修复后 R2 主断言里 aligned=0 恰是写锁挡住交错
        # 的直接证据（第二轮被锁拦在临界区外，等不到对齐伙伴）。
        print("== R2b 对齐桩自检：无锁直呼写点时双写者确能同窗落盘 ==")
        root2b = os.path.join(tmp, "r2b")
        os.makedirs(root2b)
        start2b = threading.Barrier(2, timeout=10)
        with _AlignedSave() as al2b:

            def _save2b(tag):
                start2b.wait()
                crypto._save_keys(root2b, {"v": 1, "alg": crypto.ALG,
                                           "envelopes": {f"t2b|{tag}": {}}})

            ths = [threading.Thread(target=_save2b, args=(t,), daemon=True)
                   for t in ("a", "b")]
            for t in ths:
                t.start()
            for t in ths:
                t.join(30)
        check("R2b 对齐桩确能让双写者同窗落盘（红条件有效性自证）",
              al2b.aligned >= 1, f"aligned={al2b.aligned}")

        # ---------- R3 真并发同身份幂等 ----------
        print("== R3 真并发同身份：并发 provision 应互见幂等（同一 DEK） ==")
        root3 = os.path.join(tmp, "r3")
        os.makedirs(root3)
        start3 = threading.Barrier(2, timeout=10)
        out3 = {}

        def _prov3(tag):
            start3.wait()
            out3[tag] = provision_dek(root3, kek, "t3", "alice")

        with _AlignedSave() as al3:
            ths = [threading.Thread(target=_prov3, args=(t,), daemon=True)
                   for t in ("a", "b")]
            for t in ths:
                t.start()
            for t in ths:
                t.join(30)
        same = len(set(out3.values())) == 1 and None not in out3.values()
        d3, e3 = _unwrap(root3, kek, "t3", "alice")
        check("R3 并发同身份 provision 幂等（双方同一 DEK 且可解封）",
              same and d3 in set(out3.values()),
              f"deks={len(set(out3.values()))}种 exc={e3}")

        # ---------- R4 写前对账机制断言 ----------
        print("== R4 写前对账：盘面已有而快照没有的信封保留；load_error 拒写 ==")
        root4 = os.path.join(tmp, "r4")
        os.makedirs(root4)
        dek_x = provision_dek(root4, kek, "t4", "xholder")
        disk_env = _load_keys_real(root4)["envelopes"]
        fake_y = {"id_fp": "0" * 16, "clearance": "private",
                  "nonce": "AAAA", "ct": "BBBB", "created_at": 0.0}
        # 模拟陈旧快照写者：只带自己的 Y、不带盘面已有的 X
        crypto._save_keys(root4, {"v": 1, "alg": crypto.ALG,
                                  "envelopes": {"t4|ywriter": dict(fake_y)}})
        env4 = _envelopes(root4)
        check("R4a 盘面已有信封（X）在对账下幸存",
              "t4|xholder" in env4, f"envelopes={sorted(env4)}")
        check("R4b 写者自己的信封（Y）正常落盘", "t4|ywriter" in env4)
        root4b = os.path.join(tmp, "r4b")
        os.makedirs(root4b)
        with open(crypto.keys_path(root4b), "wb") as f:
            f.write(b'{"v": 1, "alg": "cha')          # 哑损坏样本
        corrupt4b = _read(crypto.keys_path(root4b))
        buf4 = io.StringIO()
        raised4b = None
        with contextlib.redirect_stderr(buf4):
            try:
                crypto._save_keys(root4b, {"v": 1, "alg": crypto.ALG,
                                           "envelopes": {}})
            except LockedError as e:
                raised4b = e
        check("R4c 盘面 load_error 时写点拒绝（LockedError）",
              raised4b is not None, str(raised4b)[:80])
        check("R4d 损坏盘面字节不被覆盖（N139 同闸延申到写点）",
              _read(crypto.keys_path(root4b)) == corrupt4b)

        # ---------- R5 rotate 零误伤 ----------
        print("== R5 rotate 零误伤：同键以本次写回为准，他身份信封不受影响 ==")
        root5 = os.path.join(tmp, "r5")
        os.makedirs(root5)
        dek_a = provision_dek(root5, kek, "t5", "alice")
        provision_dek(root5, kek, "t5", "bob")
        dek_a2 = crypto.rotate_dek(root5, kek, "t5", "alice")
        check("R5a rotate 换新密钥且生效",
              dek_a2 != dek_a and _unwrap(root5, kek, "t5", "alice")[0] == dek_a2)
        check("R5b rotate 不影响他身份信封",
              _unwrap(root5, kek, "t5", "bob")[0] is not None
              and "t5|bob" in _envelopes(root5))
    finally:
        crypto._load_keys = _load_keys_real
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print("FAILED: %d 项 → %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("ALL OK: %d 项（N184 密钥库并发 provision 丢失更新守卫全绿）" % PASS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
