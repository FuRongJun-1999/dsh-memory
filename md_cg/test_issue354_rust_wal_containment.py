# -*- coding: utf-8 -*-
r"""#354 P0-2 / P1-6 / P1-7 守卫（Rust 蜂群 WAL 面）：损坏不得当成空、
seq/round 连续性可察觉、并发恢复不丢行。

缺陷（本件修复，2026-10-14 · swarm/rust_runtime/src/swarm.rs）
----------------------------------------------------------------
【P0-2】replay_wal 用 read_to_string **整文件一次性解码**，并把**所有** Err
  （含「文件存在但含非法 UTF-8」的 InvalidData）一律当「无 WAL = 首跑」：
  had_wal_file=false 且 completed=None ⇒ open_wal_for_run 走 File::create
  **原位清空**且不归档 —— 已提交历史被无痕销毁，故障自愈退化成数据毁灭源。
  实测（修前，真二进制 protocol_vm swarm，两场景只差尾字节可否解码）：
    · 合法快照+事件前缀 + 尾 0xFF 0xFE  ⇒ 前缀消失、无 .corrupt-* 归档；
    · 同一前缀 + 尾为**合法 UTF-8** 的半行 ⇒ 前缀完好（正常 B1 截断）。
【P1-6】WAL 无 seq/round 单调连续性校验 ⇒ 整行删除/乱序对逐行验签不可检，
  丢行「不可察觉」（报告里也不存在任何可回读面）。
【P1-7】rewrite_wal_atomic 无进程排他锁且临时文件名**固定**（{wal}.tmp）⇒
  两个 coordinator 对同一 WAL 并发恢复时操作同一个 inode（O_TRUNC 互相截断 +
  交替写入），rename 换入的 WAL 是两份内容的交错混合（半行/丢行）且失败方静默。

本守卫三层
----------
  [A] 行为面（真二进制 protocol_vm swarm --config --wal，端到端）：
      W1 非法 UTF-8 尾 ⇒ 已提交前缀逐字节幸存（修前：整文件被清空）；
      W2 整段不可解码 ⇒ 必须归档留痕（.corrupt-* 逐字节），不是静默清空；
      W3 阴性对照：合法 UTF-8 坏尾 ⇒ 前缀照常幸存（防过度修复）；
      W4 seq 跳号 ⇒ 报告 wal_continuity.ok=false + 明细 + stderr 透出（修前静默）；
      W5 锁被他人持有 ⇒ fail-closed（WAL 逐字节不动）；释放后可恢复；
      W6 两个 coordinator 并发恢复 ⇒ 双方 rc=0、前缀幸存、无撕裂行。
  [B] 源断言（结构性，行为面不可用时仍决定 rc）。
  [C] 定点变异：P0-2 回退 / P1-6 回退 / P1-7 回退 → 判据必须转红
      （改源 → cargo build → 跑守卫转红 → 还原 → 重建）。

运行：
  python -X utf8 -m md_cg.test_issue354_rust_wal_containment
  python -X utf8 -m md_cg.test_issue354_rust_wal_containment --mutate
退出码：0 全绿 / 1 有失败。
环境：PROTOCOL_VM_EXE 可指向别处的 protocol_vm 可执行文件。
诚实边界：行为面需要 swarm/rust_runtime/target/release 下的可执行件（gitignored），
本守卫按仓内既有口径自建；cargo 与产物俱不可得时行为面显式 SKIP 并打印构建命令
（源断言面照判、照决定 rc）。W6 是**并发烟测**（时序相关）：它的判别力弱于 W5 的
确定性锁判据，两者并置——W5 决定「锁在不在」，W6 证「并发下不撕裂」。
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RT_DIR = os.path.join(_REPO, "swarm", "rust_runtime")
_SWARM_RS = os.path.join(_RT_DIR, "src", "swarm.rs")

PASS = 0
FAIL = 0
FAILS = []
SKIPS = []
_SANDBOXES = []
_SILENT = False
_VIOL = []

#: 哑密钥（每测试唯一合成；绝不硬编码真实密钥）
SECRET = "i354-哑密钥-" + os.urandom(6).hex()
SNAPSHOT_TYPE = "__snapshot__"


def check(name, cond, detail=""):
    global PASS, FAIL
    if _SILENT:
        if not cond:
            _VIOL.append(name)
        return bool(cond)
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))
    return bool(cond)


def skip(name, why):
    SKIPS.append(name)
    print("  [SKIP] %s  · %s" % (name, why))


def _exe_path():
    env = os.environ.get("PROTOCOL_VM_EXE")
    if env:
        return env
    base = os.path.join(_RT_DIR, "target", "release", "protocol_vm")
    return base + ".exe" if os.name == "nt" else base


EXE = _exe_path()
_BUILD_CMD = "cargo build --release   （在 %s 下执行）" % _RT_DIR


def _ensure_exe():
    if os.path.isfile(EXE):
        return True
    if not shutil.which("cargo") or not os.path.isdir(_RT_DIR):
        print("      （%s 不在场且 cargo 不可用）" % EXE)
        return False
    print("      自建：%s" % _BUILD_CMD)
    r = subprocess.run(["cargo", "build", "--release"], cwd=_RT_DIR,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    if r.returncode != 0:
        print("      构建失败：%s" % (r.stderr or "")[-400:])
        return False
    return os.path.isfile(EXE)


# ============================ WAL 合成（与在线写入同格式） ============================

def _sign(seq, typ, frm, to, rnd, ts, payload):
    """签名串 v0.7.1：seq|type|from|to|round|ts|payload（与 Rust sign_event 同式）。"""
    msg = "%d|%s|%s|%s|%d|%d|%s" % (seq, typ, frm, to, rnd, ts, payload)
    return _hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _line(seq, typ, frm, to, rnd, payload, ts=1758888800000):
    return ('{"seq":%d,"ts":%d,"from":"%s","to":"%s","type":"%s","round":%d,'
            '"level":0,"hmac":"%s","payload":%s}'
            % (seq, ts, frm, to, typ, rnd, _sign(seq, typ, frm, to, rnd, ts, payload),
               payload))


def _snap(seq, rnd, trusts='"i1":0.5'):
    return _line(seq, SNAPSHOT_TYPE, "协调器", "协调器", rnd,
                 '{"trusts":{%s},"states":{}}' % trusts)


def _ev(seq, rnd, payload='{"x":1}'):
    return _line(seq, "MSG", "i1", "i1", rnd, payload)


CONFIG = {"algo": "rust_swarm-0.1", "shared_secret": SECRET, "rounds": 2,
          "topology": "", "routes": [],
          "instances": [{"id": "i1", "role": "worker", "trust": 0.5, "symbols": {}}]}


def _mkspace(tag):
    t = tempfile.mkdtemp(prefix="i354wal_%s_" % tag)
    _SANDBOXES.append(t)
    return t


def _write_cfg(t, rounds=2):
    cfg = dict(CONFIG)
    cfg["rounds"] = rounds
    p = os.path.join(t, "swarm.json")
    io.open(p, "w", encoding="utf-8", newline="").write(json.dumps(cfg, ensure_ascii=False))
    return p


_PBC = [None]          # 惰性编译（None=未尝试；""=不可用）
#: pbc 必须落在**跨用例存活**的位置：若编进某个用例的沙箱，该用例收尾 rmtree 后
#: 缓存路径即成死路径 ⇒ 后续用例的实例子进程载不到字节码而自死（本守卫首版实测：
#: W1 正常、W2/W5/W6 全报「实例终态非法」，噪声掩盖真判据）。
_PBC_DIR = tempfile.mkdtemp(prefix="i354wal_pbc_")


def _pbc_path(t=None):
    if _PBC[0] is None:
        try:
            sys.path.insert(0, _REPO)
            from compiler.pbc import compile_to_pbc
            p = os.path.join(_PBC_DIR, "program.pbc")
            ok, _r = compile_to_pbc("术曰：\n1。道 新信任路径；\n2。止。\n", p)
            _PBC[0] = p if ok and os.path.exists(p) else ""
        except Exception as exc:                            # noqa: BLE001
            print("      （pbc 编译不可用，退化为「实例自死」形态：%s）" % exc)
            _PBC[0] = ""
    return _PBC[0]


def _argv(t, wal, rounds=2):
    cmd = [EXE, "swarm", "--config", _write_cfg(t, rounds), "--wal", wal]
    pbc = _pbc_path(t)
    if pbc:
        cmd += ["--pbc", pbc]
    return cmd


def _run(t, wal, rounds=2, timeout=120):
    """跑一次 coordinator；返回 (rc, report|None, stderr)。"""
    p = subprocess.run(_argv(t, wal, rounds), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, cwd=t)
    rep = None
    if p.stdout.strip():
        try:
            rep = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:                                   # noqa: BLE001
            rep = None
    return p.returncode, rep, (p.stderr or "")


def _run_parallel(t, wal, rounds=2, n=2, timeout=180):
    """并发拉起 n 个 coordinator（同一 WAL）；返回 [(rc, stderr)...]。"""
    procs = [subprocess.Popen(_argv(t, wal, rounds), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace", cwd=t)
             for _ in range(n)]
    out = []
    for p in procs:
        try:
            so, se = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            so, se = p.communicate()
        out.append((p.returncode, so or "", se or ""))
    return out


def _read(wal):
    return io.open(wal, "rb").read()


def _archives(d, prefix="events.jsonl.corrupt-"):
    return sorted(n for n in os.listdir(d) if n.startswith(prefix))


def _verify_lines(data):
    """逐行校验：能被本密钥验签的行数 / 撕裂（不可解析或缺 payload 标记）行数。"""
    good = torn = 0
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw.decode("utf-8"))
        except Exception:                                   # noqa: BLE001
            torn += 1
            continue
        try:
            rawp = raw.decode("utf-8")
            seg = rawp[rawp.index('"payload":') + len('"payload":'):]
            payload = seg[:-1] if seg.endswith("}") else seg
            msg = "%s|%s|%s|%s|%s|%s|%s" % (rec["seq"], rec["type"], rec["from"],
                                            rec["to"], rec["round"], rec["ts"], payload)
            exp = _hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
        except Exception:                                   # noqa: BLE001
            torn += 1
            continue
        if _hmac.compare_digest(exp, rec.get("hmac", "")):
            good += 1
        else:
            torn += 1
    return good, torn


# ============================ [A] 行为面 ============================

def w1_invalid_utf8_tail():
    print("== W1 P0-2：非法 UTF-8 尾不得清空已提交历史 ==")
    t = _mkspace("p02")
    wal = os.path.join(t, "events.jsonl")
    snap, ev = _snap(1, 1), _ev(2, 1)
    orig = (snap + "\n" + ev + "\n").encode("utf-8") + b"\xff\xfe"
    io.open(wal, "wb").write(orig)
    rc, rep, err = _run(t, wal, rounds=2)
    after = _read(wal)
    check("W1 coordinator 正常退出（rc=0）", rc == 0, (rc, err[-200:]))
    check("W1 已提交快照行逐字节幸存（修前：整文件被 File::create 清空）",
          snap.encode("utf-8") in after, _head(after))
    check("W1 未提交的非法尾被物理截断（B1 语义不变）",
          b"\xff\xfe" not in after)
    check("W1 有提交点时不得归档（另有 W2 专测零提交归档）",
          not _archives(t), _archives(t))
    check("W1 残留件核查：目录内无 .lock / .tmp（锁与临时件都该清干净）",
          not [n for n in os.listdir(t) if n.endswith(".lock") or ".tmp" in n],
          os.listdir(t))
    shutil.rmtree(t, ignore_errors=True)


def w2_undecodable_archived():
    print("== W2 P0-2：整段不可解码必须归档留痕（不得静默清空）==")
    t = _mkspace("p02b")
    wal = os.path.join(t, "events.jsonl")
    orig = b"\xff\xfe\xfd\n\x80\x81\n"
    io.open(wal, "wb").write(orig)
    rc, rep, err = _run(t, wal, rounds=1)
    arch = _archives(t)
    check("W2 coordinator 正常退出（零提交 → 从轮 1 重跑）", rc == 0, (rc, err[-200:]))
    check("W2 恰好一份 .corrupt-* 归档", len(arch) == 1, arch)
    if arch:
        check("W2 归档逐字节保留原 WAL（审计链可离线取证）",
              _read(os.path.join(t, arch[0])) == orig)
    check("W2 新 WAL 不含原坏字节（已另行归档，不是原位残留）",
          b"\xff\xfe\xfd" not in _read(wal))
    shutil.rmtree(t, ignore_errors=True)


def w3_valid_bad_tail_control():
    print("== W3 阴性对照：合法 UTF-8 坏尾照常截断（防过度修复）==")
    t = _mkspace("ctl")
    wal = os.path.join(t, "events.jsonl")
    snap, ev = _snap(1, 1), _ev(2, 1)
    io.open(wal, "wb").write(
        (snap + "\n" + ev + "\n" + '{"seq":3,"ts":1,"from":"BAD half').encode("utf-8"))
    rc, rep, err = _run(t, wal, rounds=2)
    after = _read(wal)
    check("W3 rc=0 且前缀幸存", rc == 0 and snap.encode("utf-8") in after,
          (rc, _head(after)))
    check("W3 合法坏尾被物理截断", b"BAD half" not in after)
    check("W3 不触发归档（有提交点）", not _archives(t), _archives(t))
    shutil.rmtree(t, ignore_errors=True)


def w4_seq_gap_detectable():
    print("== W4 P1-6：seq 跳号必须可察觉（报告 + stderr）==")
    t = _mkspace("p16")
    wal = os.path.join(t, "events.jsonl")
    # 1(快照r1),2,[缺 3/4],5,6(快照r2)：一处跳号；completed=2 → 目标 2 轮已完成，
    # 走早退聚合路径（不 spawn 实例、不改 WAL），只读连续性读数。
    io.open(wal, "wb").write(
        ("\n".join([_snap(1, 1), _ev(2, 1), _ev(5, 1), _snap(6, 2)]) + "\n").encode("utf-8"))
    rc, rep, err = _run(t, wal, rounds=2)
    wc = (rep or {}).get("wal_continuity")
    check("W4 报告必须带 wal_continuity 字段（可回读面）", isinstance(wc, dict),
          wc)
    check("W4 跳号被报出（ok=false 且 breaks>=1）",
          bool(wc) and wc.get("ok") is False and (wc.get("breaks") or 0) >= 1 and
          len(wc.get("detail") or []) >= 1, wc)
    if wc and wc.get("detail"):
        d = wc["detail"][0]
        check("W4 明细含 line/expected/actual/kind（可定位、可复核）",
              d.get("line") == 3 and d.get("expected") == 3 and d.get("actual") == 5
              and d.get("kind") == "跳号缺失", d)
    check("W4 stderr 亦透出（旧实现完全静默 = 不可察觉）",
          "连续性中断" in err and "P1-6" in err, err.strip()[-200:])
    shutil.rmtree(t, ignore_errors=True)


def w4b_continuous_wal_silent():
    print("== W4b 阴性对照：连续 WAL 不得误报、不得刷告警 ==")
    t = _mkspace("p16ok")
    wal = os.path.join(t, "events.jsonl")
    io.open(wal, "wb").write(
        ("\n".join([_snap(1, 1), _ev(2, 1), _snap(3, 2)]) + "\n").encode("utf-8"))
    rc, rep, err = _run(t, wal, rounds=2)
    wc = (rep or {}).get("wal_continuity")
    check("W4b ok=true 且 breaks=0", bool(wc) and wc.get("ok") is True
          and (wc.get("breaks") or 0) == 0, wc)
    check("W4b 不得刷连续性告警（零噪声）", "连续性中断" not in err, err.strip()[-160:])
    shutil.rmtree(t, ignore_errors=True)


def w5_held_lock_fails_closed():
    print("== W5 P1-7：锁被他人持有 ⇒ fail-closed（WAL 逐字节不动）==")
    t = _mkspace("p17")
    wal = os.path.join(t, "events.jsonl")
    orig = (_snap(1, 1) + "\n" + '{"seq":2,"ts":1,"from":"BAD half').encode("utf-8")
    io.open(wal, "wb").write(orig)
    lock = wal + ".lock"
    io.open(lock, "w", encoding="utf-8", newline="").write("99999 0\n")
    rc, rep, err = _run(t, wal, rounds=2)
    check("W5 持锁时不得改写：WAL 逐字节不动（修前：无锁照写）",
          _read(wal) == orig, _head(_read(wal)))
    check("W5 持锁时非零退出且原因点名排他锁（可诊断）",
          rc != 0 and "排他锁" in err, (rc, err.strip()[-200:]))
    os.remove(lock)
    rc2, rep2, err2 = _run(t, wal, rounds=2)
    after2 = _read(wal)
    check("W5 释放后可恢复（锁不是一次性）",
          rc2 == 0 and _snap(1, 1).encode("utf-8") in after2, (rc2, err2[-160:]))
    check("W5 正常路径不留锁件",
          not os.path.exists(lock), os.listdir(t))
    shutil.rmtree(t, ignore_errors=True)


def w6_concurrent_recovery():
    print("== W6 P1-7：两个 coordinator 并发恢复同一 WAL（烟测）==")
    t = _mkspace("p17c")
    wal = os.path.join(t, "events.jsonl")
    snap = _snap(1, 1)
    io.open(wal, "wb").write(
        (snap + "\n" + '{"seq":2,"ts":1,"from":"BAD half').encode("utf-8"))
    res = _run_parallel(t, wal, rounds=2, n=2)
    rcs = [r[0] for r in res]
    after = _read(wal)
    good, torn = _verify_lines(after)
    check("W6 双方 rc=0（旧实现固定 tmp 名 → rename 竞争，失败方 Err 退出）",
          all(x == 0 for x in rcs), (rcs, [r[2][-120:] for r in res]))
    check("W6 已提交前缀幸存", snap.encode("utf-8") in after, _head(after))
    check("W6 终态 WAL 无撕裂行（每行均可解析且验签）", torn == 0,
          {"good": good, "torn": torn, "tail": after[-160:]})
    shutil.rmtree(t, ignore_errors=True)


def _head(b):
    return bytes(b[:160])


# ============================ [B] 源断言 ============================

def _src():
    return io.open(_SWARM_RS, encoding="utf-8", errors="replace").read()


def b_source_face():
    print("== B 源断言（行为面不可用时仍决定 rc）==")
    src = _src()
    check("B1 P0-2：WAL 不再整文件解码（read_to_string(wal_path) 已消失）",
          "read_to_string(wal_path)" not in src)
    check("B1b P0-2：「文件不存在」与「文件损坏」分道",
          "ErrorKind::NotFound => return Ok(rp)" in src
          and "WAL 存在但不可读" in src)
    check("B1c P0-2：行级容错解码（坏字节只作废其所在行）",
          "std::str::from_utf8(chunk).ok()" in src)
    # 按**代码用法**断言（带尾逗号/表达式形态），不按裸词匹配：三种 kind 的字面量
    # 也出现在 SeqBreak 的文档注释里，裸词匹配会被注释喂饱（V2 首版即由此漏判）。
    check("B2 P1-6：seq/round 连续性判据在场（三种 kind 的代码用法）",
          'if ev.seq > exp { "跳号缺失" }' in src
          and '"round 倒退",' in src
          and '"快照轮号重复或倒退",' in src)
    # 注意：源码里该键名是 Rust 字面量内的转义形态（\"wal_continuity\"），故按
    # 「访问器 + 报告发射点」两个无歧义标记断言，不按裸引号形态匹配。
    check("B2b P1-6：读数进报告（wal_continuity 出口）",
          "pub fn ok(&self) -> bool" in src and "rep.wal_continuity.ok()" in src)
    check("B3 P1-7：排他锁在场且被恢复路径取用",
          "struct WalLock" in src and "WalLock::acquire(wal_path)?" in src
          and "LOCK_STALE_MS" in src)
    check("B3b P1-7：临时文件名含进程号（不再是固定 {wal}.tmp）",
          'format!("{wal_path}.tmp.{}", std::process::id())' in src
          and 'format!("{wal_path}.tmp")' not in src)
    check("B4 反陈化：三处缺陷都点名 issue #354 与条号",
          "#354 P0-2" in src and "#354 P1-6" in src and "#354 P1-7" in src)


# ============================ 主流程 ============================

_BEHAVIOR = (w1_invalid_utf8_tail, w2_undecodable_archived, w3_valid_bad_tail_control,
             w4_seq_gap_detectable, w4b_continuous_wal_silent,
             w5_held_lock_fails_closed, w6_concurrent_recovery)


def _run_groups(behavior_ok):
    global PASS, FAIL
    PASS = 0
    FAIL = 0
    del FAILS[:]
    del SKIPS[:]
    for g in _BEHAVIOR:
        if not behavior_ok:
            skip(g.__name__, "protocol_vm 可执行件不可得（构建命令：%s）" % _BUILD_CMD)
            continue
        try:
            g()
        except Exception as exc:                           # noqa: BLE001
            check("断言组 %s 抛异常：%s" % (g.__name__, exc), False)
            import traceback
            print(traceback.format_exc()[-700:])
    b_source_face()
    return len(FAILS)


def main():
    behavior_ok = _ensure_exe()
    if not behavior_ok:
        print("!! 行为面 SKIP：%s 不在场且无法自建 —— 构建命令：%s"
              % (EXE, _BUILD_CMD))
    n = _run_groups(behavior_ok)
    print()
    print("issue354 Rust WAL 守卫（P0-2 损坏不得当空 / P1-6 连续性可察觉 / P1-7 并发恢复）："
          "%d 通过，%d 失败，%d 跳过" % (PASS, n, len(SKIPS)))
    return 1 if n else 0


# ============================ [C] 定点变异自证 ============================

_MUTATIONS = (
    ("V1 P0-2 回退：整文件解码 + 所有 Err 当首跑",
     "    let bytes = match std::fs::read(wal_path) {\n"
     "        Ok(b) => b,\n"
     "        // 文件不存在 = 首跑（唯一可当「无 WAL」的分支）\n"
     "        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(rp),\n"
     "        // 存在但不可读（权限 / IO / 路径是目录）：损坏不得当成空 ⇒ 交调用方，\n"
     "        // 由它按「不销毁现场」的路径处置\n"
     "        Err(e) => {\n"
     "            return Err(format!(\n"
     "                \"WAL 存在但不可读（issue #354 P0-2：损坏不得当成空，拒绝继续）: {wal_path}: {e}\"\n"
     "            ))\n"
     "        }\n"
     "    };\n"
     "    rp.had_wal_file = true;\n",
     "    let bytes = match std::fs::read_to_string(wal_path) {\n"
     "        Ok(t) => t.into_bytes(),\n"
     "        Err(_) => return Ok(rp),\n"
     "    };\n"
     "    rp.had_wal_file = true;\n",
     "W1", "W2", "B1", "B1b"),
    ("V2 P1-6 回退：删掉 seq 连续性检测",
     "        if let Some(exp) = expected_seq {\n"
     "            if ev.seq != exp {\n"
     "                note_break(\n"
     "                    &mut rp.continuity,\n"
     "                    idx + 1,\n"
     "                    exp,\n"
     "                    ev.seq,\n"
     "                    if ev.seq > exp { \"跳号缺失\" } else { \"重复或乱序\" },\n"
     "                    &ev.event_type,\n"
     "                );\n"
     "            }\n"
     "        }\n",
     "        expected_seq = Some(ev.seq + 1);\n",
     "W4", "B2"),
    ("V3 P1-7 回退：删掉排他锁取用",
     "    let _lock = WalLock::acquire(wal_path)?;\n",
     "",
     "W5", "B3"),
)


def _rebuild():
    r = subprocess.run(["cargo", "build", "--release"], cwd=_RT_DIR,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    return r.returncode == 0, (r.stderr or "")[-400:]


def _mutate():
    bad = []
    if not os.path.isfile(_SWARM_RS):
        print("  SOURCE-MISSING：%s" % _SWARM_RS)
        return 1
    if not shutil.which("cargo"):
        print("  NO-CARGO：变异自证需要 cargo（改源后必须重建，否则跑的还是旧二进制）")
        return 1
    with io.open(_SWARM_RS, encoding="utf-8", newline="") as f:
        pristine = f.read()
    global _SILENT
    for name, anchor, repl, *want in _MUTATIONS:
        with io.open(_SWARM_RS, encoding="utf-8", newline="") as f:
            orig = f.read()
        NL = "\r\n" if "\r\n" in orig else "\n"
        a_ = anchor.replace("\n", NL)
        r_ = repl.replace("\n", NL)
        if a_ not in orig:
            print("  ANCHOR-MISS %s" % name)
            bad.append(name)
            continue
        try:
            with io.open(_SWARM_RS, "w", encoding="utf-8", newline="") as f:
                f.write(orig.replace(a_, r_, 1))
            ok_build, blog = _rebuild()
            if not ok_build:
                print("  BUILD-FAIL %s：%s" % (name, blog))
                bad.append(name + "(构建失败)")
                continue
            _SILENT = True
            del _VIOL[:]
            _run_groups(True)
            reds = list(_VIOL)
            hit = [w for w in want if any(x.startswith(w) for x in reds)]
            print("  %-4s %-44s 红项=%-3d 命中=%s"
                  % ("OK" if len(hit) == len(want) else "BAD", name, len(reds),
                     ",".join(hit) if hit else "无"))
            if len(hit) != len(want):
                print("       期望红：%s；实红：%s" % (list(want), reds[:8]))
                bad.append(name)
        finally:
            _SILENT = False
            with io.open(_SWARM_RS, "w", encoding="utf-8", newline="") as f:
                f.write(pristine)
            with io.open(_SWARM_RS, encoding="utf-8", newline="") as f:
                if f.read() != pristine:
                    print("  RESTORE-FAILED %s" % name)
                    bad.append(name + "(恢复失败)")
            _rebuild()
    if bad:
        print()
        print("定点变异自证：FAIL -- %s" % "、".join(bad))
        return 1
    print()
    print("定点变异自证：PASS（每处判据都被打红）")
    return 0


def _cleanup():
    for t in _SANDBOXES:
        shutil.rmtree(t, ignore_errors=True)
    shutil.rmtree(_PBC_DIR, ignore_errors=True)


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        rc = _mutate()
        _cleanup()
        sys.exit(rc)
    rc = main()
    _cleanup()
    sys.exit(rc)
