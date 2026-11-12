# -*- coding: utf-8 -*-
r"""守卫 · issue #470（P1）swarm WAL 事件行 flush 是 no-op（durable 纪律背离）。

缺陷（本件修复 · swarm/rust_runtime/src/swarm.rs）
--------------------------------------------------
`open_wal_for_run` 返回 `std::fs::File`（无用户态缓冲），而 Rust 的
`std::fs::File::flush()` 是 **no-op**（`write_all` 只进 page cache）。旧实现
在事件行写完后调 `wal.flush()` 并注释「事件行先 durable」，实为空背书：
事件行与轮末快照行一起等 `wal.sync_all()`，崩溃落在「事件行 write 后、轮末
sync 前」窗口 ⇒ 整轮路由/ACK/水位蒸发，B1 断点恢复的可恢复边界比宣称窄。

修复：事件行（含修正信号行）写完后显式 `wal.sync_data()`（只同步数据），
之后才写轮末快照行；轮末 `sync_all()` 仍负责快照。并新增可观测读数
`wal_durable.event_syncs / last_sync_round` 随报告透出——「是否真的过了一个
durable 点」不再只能靠读注释。

【功能名】swarm WAL 事件行独立 durable 判据
【生效条件】`protocol_vm swarm --config --wal` 执行至少一轮（早退路径无事件行
  写入，读数应为 0）；源码面断言在任意状态可判。
【子功能】A 行为面（真二进制）：每轮事件行 sync_data 计数 == 执行轮数、早退
  不伪造计数；B 源断言：sync_data 在快照写之前、无 `wal.flush()` 代码用法、
  报告出口在场、反陈化点名 issue；C 定点变异：回退修复 ⇒ 判据转红。
【执行】python -X utf8 -m md_cg.test_issue470_wal_event_durable
        python -X utf8 -m md_cg.test_issue470_wal_event_durable --mutate
【验证方式】退出码 0 全绿；`--mutate` 下每个变异体都点名预期红项且非空。
【不适用条件】无 cargo 且无预构建 protocol_vm 时行为面 SKIP（源断言面照判并
  决定 rc）；不覆盖 fsync 的物理介质语义（OS/文件系统层），只判「调用点与
  顺序 + 可观测计数」。
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

SECRET = "i470-哑密钥-" + os.urandom(6).hex()
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
_BUILD_CMD = "cargo build --release --manifest-path swarm/rust_runtime/Cargo.toml"


def _ensure_exe():
    if os.path.isfile(EXE):
        return True
    if not shutil.which("cargo") or not os.path.isdir(_RT_DIR):
        print("      （%s 不在场且 cargo 不可用）" % EXE)
        return False
    print("      自建：%s" % _BUILD_CMD)
    r = subprocess.run(["cargo", "build", "--release",
                        "--manifest-path", os.path.join(_RT_DIR, "Cargo.toml")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    if r.returncode != 0:
        print("      构建失败：%s" % (r.stderr or "")[-400:])
        return False
    return os.path.isfile(EXE)


# ============================ WAL 合成 ============================

def _sign(seq, typ, frm, to, rnd, ts, payload):
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
          "topology": "",
          "routes": [{"from": "i1", "event_type": "消息", "to": "i1",
                      "payload": {"x": 1}}],
          "instances": [{"id": "i1", "role": "worker", "trust": 0.5, "symbols": {}}]}

_PBC = [None]
_PBC_DIR = tempfile.mkdtemp(prefix="i470_pbc_")


def _pbc_path():
    if _PBC[0] is None:
        try:
            sys.path.insert(0, _REPO)
            from compiler.pbc import compile_to_pbc
            p = os.path.join(_PBC_DIR, "program.pbc")
            ok, _r = compile_to_pbc("术曰：\n1。道 新信任路径；\n2。止。\n", p)
            _PBC[0] = p if ok and os.path.exists(p) else ""
        except Exception as exc:                            # noqa: BLE001
            print("      （pbc 编译不可用，实例走自死形态：%s）" % exc)
            _PBC[0] = ""
    return _PBC[0]


def _mkspace(tag):
    t = tempfile.mkdtemp(prefix="i470_%s_" % tag)
    _SANDBOXES.append(t)
    return t


def _run(t, wal, rounds=2, timeout=120):
    cfg = dict(CONFIG)
    cfg["rounds"] = rounds
    cp = os.path.join(t, "swarm.json")
    io.open(cp, "w", encoding="utf-8", newline="").write(
        json.dumps(cfg, ensure_ascii=False))
    cmd = [EXE, "swarm", "--config", cp, "--wal", wal]
    pbc = _pbc_path()
    if pbc:
        cmd += ["--pbc", pbc]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, cwd=t)
    rep = None
    if p.stdout.strip():
        try:
            rep = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:                                   # noqa: BLE001
            rep = None
    return p.returncode, rep, (p.stderr or "")


# ============================ [A] 行为面 ============================

def a1_event_syncs_per_round():
    print("== A1 每轮事件行独立 durable：event_syncs == 执行轮数 ==")
    t = _mkspace("r2")
    wal = os.path.join(t, "events.jsonl")
    rc, rep, err = _run(t, wal, rounds=2)
    wd = (rep or {}).get("wal_durable")
    check("A1a 报告必须带 wal_durable 读数（可观测出口）",
          isinstance(wd, dict), wd)
    check("A1b coordinator 正常退出", rc == 0, (rc, err[-200:]))
    check("A1c event_syncs == 2（每轮一次，修前无此读数）",
          bool(wd) and wd.get("event_syncs") == 2, wd)
    check("A1d last_sync_round == 2", bool(wd) and wd.get("last_sync_round") == 2, wd)
    # 事件行与快照行都必须在盘上（顺序判据在 B 面做源码级断言）
    data = io.open(wal, "rb").read()
    rows = []
    for raw in data.split(b"\n"):
        if raw.strip():
            try:
                rows.append(json.loads(raw.decode("utf-8")))
            except Exception:                               # noqa: BLE001
                rows.append({"type": "<坏行>"})
    evs = [r for r in rows if r.get("type") != SNAPSHOT_TYPE]
    snaps = [r for r in rows if r.get("type") == SNAPSHOT_TYPE]
    check("A1e WAL 同时含事件行与快照行（有事件可判 durable 顺序）",
          bool(evs) and len(snaps) == 2, {"events": len(evs), "snaps": len(snaps)})
    shutil.rmtree(t, ignore_errors=True)


def a2_early_exit_no_fake_count():
    print("== A2 早退路径（目标轮已全部持久化）不得伪造 durable 计数 ==")
    t = _mkspace("done")
    wal = os.path.join(t, "events.jsonl")
    io.open(wal, "wb").write(
        ("\n".join([_snap(1, 1), _ev(2, 1), _snap(3, 2)]) + "\n").encode("utf-8"))
    rc, rep, err = _run(t, wal, rounds=2)
    wd = (rep or {}).get("wal_durable")
    check("A2a 早退 rc=0", rc == 0, (rc, err[-200:]))
    check("A2b 早退 event_syncs == 0（本会话无事件行写入）",
          isinstance(wd, dict) and wd.get("event_syncs") == 0, wd)
    shutil.rmtree(t, ignore_errors=True)


# ============================ [B] 源断言 ============================

def _src():
    return io.open(_SWARM_RS, encoding="utf-8", errors="replace").read()


def b_source_face():
    print("== B 源断言（行为面不可用时仍决定 rc）==")
    src = _src()
    i_sync = src.find("wal.sync_data()")
    i_snap = src.find("wal.write_all(snap_line.as_bytes())")
    check("B1 事件行显式 sync_data 在场", i_sync >= 0)
    check("B1b sync_data 在轮末快照写入之前（快照永不先于产生它的写入落盘）",
          i_sync >= 0 and i_snap >= 0 and i_sync < i_snap,
          (i_sync, i_snap))
    # 代码位置的 wal.flush() 用法必须消失（注释里点名旧实现不算）
    code_flush = [ln for ln in src.splitlines()
                  if ln.strip().startswith("wal.flush(")]
    check("B2 事件行 durable 不再依赖 File::flush()（no-op）",
          not code_flush, code_flush[:2])
    check("B3 报告出口 wal_durable 在场",
          '\\"wal_durable\\":{{' in src and "rep.wal_durable.event_syncs" in src)
    check("B4 反陈化：修复点名 issue #470",
          "#470" in src)
    check("B5 轮末 sync_all 仍在（快照 durable 未回退）",
          "wal.sync_all()" in src)


# ============================ 主流程 ============================

_BEHAVIOR = (a1_event_syncs_per_round, a2_early_exit_no_fake_count)


def _run_groups(behavior_ok):
    global PASS, FAIL
    PASS = 0
    FAIL = 0
    del FAILS[:]
    del SKIPS[:]
    for g in _BEHAVIOR:
        if not behavior_ok:
            skip(g.__name__, "protocol_vm 不可得（构建命令：%s）" % _BUILD_CMD)
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
    # 锚点自检（fail-closed）：修法的关键判据不在源码里 ⇒ exit 2，不给假绿。
    src = _src()
    missing = [a for a in ("wal.sync_data()", '\\"wal_durable\\":{{',
                           "rep.wal_durable.event_syncs") if a not in src]
    if missing:
        print("锚点自检失败：关键判据字面量缺失 %s" % missing)
        return 2
    behavior_ok = _ensure_exe()
    if not behavior_ok:
        print("!! 行为面 SKIP：%s 不在场且无法自建 —— 构建命令：%s"
              % (EXE, _BUILD_CMD))
    n = _run_groups(behavior_ok)
    print()
    print("issue470 WAL 事件行 durable 守卫：%d 通过，%d 失败，%d 跳过"
          % (PASS, n, len(SKIPS)))
    return 1 if n else 0


# ============================ [C] 定点变异自证 ============================

_SYNC_BLOCK = (
    "        wal.sync_data().map_err(|e| format!(\"WAL 事件行 sync 失败: {e}\"))?;\n"
    "        wal_durable.event_syncs += 1;\n"
    "        wal_durable.last_sync_round = round;\n")
_REPORT_BLOCK = (
    "    // issue #470：事件行 durable 读数（每轮事件行 sync_data 后才写快照）。\n"
    "    out.push_str(&format!(\n"
    "        \",\\\"wal_durable\\\":{{\\\"event_syncs\\\":{},\\\"last_sync_round\\\":{}}}\",\n"
    "        rep.wal_durable.event_syncs, rep.wal_durable.last_sync_round\n"
    "    ));\n")
_SNAP_SYNC_ALL = "        wal.sync_all().map_err(|e| format!(\"WAL sync 失败: {e}\"))?;\n"

_MUTATIONS = (
    ("V1 回退：sync_data 改回 File::flush()（no-op）",
     _SYNC_BLOCK,
     "        wal.flush().map_err(|e| format!(\"WAL flush 失败: {e}\"))?;\n",
     "A1c", "B1", "B2"),
    ("V2 回退：删掉 wal_durable 报告出口",
     _REPORT_BLOCK,
     "",
     "A1a", "A1c", "B3"),
    ("V3 顺序回退：sync_data 挪到快照写入之后",
     _SYNC_BLOCK,
     "",
     "B1b"),
)


def _rebuild():
    r = subprocess.run(["cargo", "build", "--release",
                        "--manifest-path", os.path.join(_RT_DIR, "Cargo.toml")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    return r.returncode == 0, (r.stderr or "")[-400:]


def _mutate():
    bad = []
    if not os.path.isfile(_SWARM_RS):
        print("  SOURCE-MISSING：%s" % _SWARM_RS)
        return 1
    if not shutil.which("cargo"):
        print("  NO-CARGO：变异自证需要 cargo（改源后必须重建）")
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
        mutated = orig.replace(a_, r_, 1)
        if name.startswith("V3"):
            # 顺序回退：删掉原位同步块，把同一调用挪到轮末 sync_all 之前
            # （此时快照行已 write_all 落进 page cache ⇒ 快照可先于事件行落盘）
            sw = _SNAP_SYNC_ALL.replace("\n", NL)
            if sw not in mutated:
                print("  ANCHOR-MISS %s（轮末 sync_all 点）" % name)
                bad.append(name)
                continue
            mutated = mutated.replace(
                sw,
                "        wal.sync_data().map_err(|e| format!(\"WAL 事件行 sync 失败: {e}\"))?;\n"
                "        wal_durable.event_syncs += 1;\n"
                "        wal_durable.last_sync_round = round;\n".replace("\n", NL) + sw,
                1)
        try:
            with io.open(_SWARM_RS, "w", encoding="utf-8", newline="") as f:
                f.write(mutated)
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
            print("  %-4s %-46s 红项=%-3d 命中=%s"
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
