# -*- coding: utf-8 -*-
"""bootstrap_loop.py · 白箱自举后台循环 v3（长期任务执行体·双通道）

v3 迁移（2026-09-10，三仓分离后）：
  - 归属：协议仓 `CommonTrustProtocol/tools/` → **灵枢大脑 `dsh-memory/scripts/`**
    （作用对象 wisdom 齿轮已随大脑仓，循环应与其同仓）。
  - 路径：`WISDOM = ROOT/aeis/wisdom`（已随三仓分离删除）→
    `BRAIN/md_cg/whitebox_kb/wisdom`。
  - 数据根：不再硬编码 `ROOT/aeis/data/*`，统一走 `md_cg/datapath.py`
    解析（env `MDCG_ROOT` > `paths.json`（用户级，旧包内兼容读）> 用户级状态根
    `data/`，即 `~/.dsh/.dsh-memory/data`——不再落插件包内，包内数据会被
    pnpm 更新连目录删掉）。运行态落 `<数据根>/bootstrap/`。

通道 A：路由缺口扫描 → triggers 补丁 → 验证 → 固化（零 LLM·确定性）
通道 B：LLM 初稿（deepseek/glm）→ verifier 六层校验 → 测试 → 固化
四机制安全闭环：selfmod 快照/审计/裁决 在每次固化前强制执行。

selfmod 闭环落地（A5 使用者裁决 2026-10-05）：固化 = 通道 A 的 `persist_triggers`
（就地改 WISDOM 单元表源文件）与通道 B 的 verified 落盘；**两处写盘前都强制走
`selfmod_gate`**，任一环节不成立即**拒且不改盘**（fail-closed）：
  · 裁决 —— ①待固化对象已过既有验证（通道 A 的 verify_patch / 通道 B 的
    verifier+cases，由调用方原样传入，不许旁路）②目标在**授权自改写面**内
    （防补丁/路径解析把自改写到别处）③前像与当前盘面逐字节一致（读取到落盘
    之间被第三方改过 ⇒ 固化依据已失效 ⇒ 拒，不静默覆盖别人的改动）
  · 快照 —— 逐字节前像 → `<数据根>/bootstrap/selfmod/snapshots/<名>.<秒>-<微秒>.bak`
    （二进制原子落盘，复用 `fsutil.publish` 的 Windows 短重试）
  · 审计 —— append-only 台账 `<数据根>/bootstrap/selfmod/selfmod_audit.jsonl`
    （`FileLock(strict=True)` + `fsutil.append_jsonl`——fsutil 明文「裁决记录」这类
    不能丢的写用 strict 锁；形态与本仓既有台账同款）
裁决/快照/审计本身失败也算「不通过」（快照/审计没就位就不许固化——这正是闭环
与 `branches._audit`「审计失败不阻断主流程」的区别：那个是观测留痕，这个是准入闸）。

用法：
  python scripts/bootstrap_loop.py --once --channel-b     # 单轮含 LLM 通道
  python scripts/bootstrap_loop.py --once                # 单轮仅通道 A
  python scripts/bootstrap_loop.py --interval 600 --channel-b   # 长期跑
日志：<数据根>/bootstrap/bootstrap_log.jsonl
安全闭环台账/前像：<数据根>/bootstrap/selfmod/{selfmod_audit.jsonl,snapshots/}
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRAIN = os.path.dirname(HERE)                      # 灵枢大脑仓根
WISDOM = os.path.join(BRAIN, "md_cg", "whitebox_kb", "wisdom")

sys.path.insert(0, WISDOM)
sys.path.insert(0, HERE)
sys.path.append(os.path.join(BRAIN, "md_cg"))      # 供顶层 import datapath

# 数据根解析（记忆写入路径可配置·默认用户级状态根 data/；解析器缺失时的
# 兜底分支保留旧「仓内 data/」口径——那是本脚本自带的最后兜底，非解析默认）
try:
    import datapath as _dp
except Exception:                                   # 兜底：解析器缺失时不高挂
    class _dp:                                      # type: ignore
        @staticmethod
# 生效条件：调用即返回 os.path.join(BRAIN, "data")，结果只取决于模块级常量 BRAIN，不接收参数。
        def data_root() -> str:
            return os.path.join(BRAIN, "data")

        @staticmethod
# 生效条件：以 name 拼出 os.path.join(BRAIN, "data", name)，该路径 os.path.isfile 为真时返回该路径，否则返回 None。
        def find_existing(name: str):
            p = os.path.join(BRAIN, "data", name)
            return p if os.path.isfile(p) else None

STATE = os.path.join(_dp.data_root(), "bootstrap")
os.makedirs(STATE, exist_ok=True)
LOG = os.path.join(STATE, "bootstrap_log.jsonl")


# 生效条件：evt 为 dict 时（含空 dict）先写入 evt["ts"]，再以 ensure_ascii=False 序列化追加一行到 LOG。
def log_event(evt: dict) -> None:
    evt["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # P2-13: rotate LOG when > 10MB (batch 31)
    try:
        if os.path.getsize(LOG) > 10485760:
            os.replace(LOG, LOG + ".rotated")
    except OSError:
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(evt, ensure_ascii=False) + "\n")


# ==================== 通道 A：路由缺口扫描（零 LLM） ====================
# 生效条件：limit_units 为真值且已遍历单元计数 count > limit_units 时提前返回当前 gaps，limit_units 为 None 或 0 时不限流；遍历每个 DOMAIN_UNITS 域单元时 domain_route 抛异常记 error 项、返回 unit != uid 或 ok 假值记 got 项，全遍历后返回 gaps。
def scan_route_gaps(limit_units: int | None = None) -> list:
    from code_compose import domain_route, DOMAIN_UNITS

    gaps = []
    domains = list(DOMAIN_UNITS.keys())
    count = 0
    for dom in domains:
        for uid, unit in DOMAIN_UNITS[dom].items():
            count += 1
            if limit_units and count > limit_units:
                return gaps
            triggers = [t for t in (unit.get("triggers") or []) if len(t) >= 2]
            probe = "写一个{}单元（{}）".format(
                uid, triggers[0] if triggers else unit.get("task", ""))
            try:
                r = domain_route(probe)
            except Exception:
                gaps.append({"domain": dom, "unit": uid, "probe": probe, "error": "exc"})
                continue
            if r.get("unit") != uid or not r.get("ok"):
                # GAP_DEBUG=1：gap 判定现场落盘（r 全量+环境快照）——
                # 「循环进程 gap=1 vs 交互进程同代码 True」非确定性排查取证点
                if os.environ.get("GAP_DEBUG"):
                    try:
                        json.dump({
                            "probe": probe, "result": r,
                            "pid": os.getpid(),
                            "sys_executable": sys.executable,
                            "code_compose_file": getattr(__import__("code_compose"), "__file__", "?"),
                            "cases_shape": type(unit.get("cases", [None])[0][0]).__name__ if unit.get("cases") else "?",
                            "env": {k: v for k, v in os.environ.items()
                                    if k.startswith(("PYTHON", "AEIS", "SYSTEMROOT", "PATH="))},
                        }, open(os.path.join(STATE, "gap_debug.json"), "w",
                                encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
                    except Exception:
                        pass
                gaps.append({"domain": dom, "unit": uid, "probe": probe,
                             "got": r.get("unit") or r.get("reason", "?")})
    return gaps


# 生效条件：gap["unit"] 按 "-" 切分后存在长度 >= 2 的片段时返回 {domain, unit, add_triggers=前 3 个片段}，无此类片段时返回 None。
def build_trigger_patch(gap):
    uid = gap["unit"]
    parts = [p for p in uid.split("-") if len(p) >= 2]
    if not parts:
        return None
    return {"domain": gap["domain"], "unit": uid, "add_triggers": parts[:3]}


# 生效条件：DOMAIN_UNITS.get(patch["domain"], {}).get(patch["unit"]) 取到的单元为 None 时返回 False；取到单元时把 patch["add_triggers"] 中长度 >= 2 且不在现 triggers 集合的项追加（无新项不修改 triggers），两种情况均返回 True。
def apply_patch(patch):
    from code_compose import DOMAIN_UNITS
    unit = DOMAIN_UNITS.get(patch["domain"], {}).get(patch["unit"])
    if unit is None:
        return False
    cur = set(unit.get("triggers") or [])
    new = [t for t in patch["add_triggers"] if t not in cur and len(t) >= 2]
    if not new:
        return True
    unit["triggers"] = (unit.get("triggers") or []) + new
    return True


# 生效条件：patch["unit"] 作为 uid 拼出 "写一个{uid}单元" 探针调用 domain_route，返回 domain_route 结果的 unit == patch["unit"] 且 ok 为真值的布尔与。
def verify_patch(patch):
    from code_compose import domain_route
    uid = patch["unit"]
    probe = "写一个{}单元".format(uid)
    r = domain_route(probe)
    return r.get("unit") == uid and r.get("ok")


# 生效条件：patches 中某 patch 的 domain 命中 files 六键之一、对应 os.path.exists(path) 为真、且 path 内容正则搜到 `"uid": {` 行且其后 600 字符块内无 "triggers" 时才进入固化；固化前调 selfmod_gate（裁决→快照→审计）通过才插入 triggers 行并让 changed 自增，裁决不通过即跳过该文件（不改盘，留痕见 selfmod 台账）；返回 changed。
def persist_triggers(patches):
    import re
    files = {dom: os.path.join(WISDOM, fn) for dom, fn in UNIT_FILES.items()}
    changed = 0
    for p in patches:
        dom, uid, triggers = p["domain"], p["unit"], p["add_triggers"]
        path = files.get(dom)
        if not path or not os.path.exists(path):
            continue
        # 前像基准 = 盘面**原字节**（文本读会把 \r\n 归一成 \n——拿文本摘要当盘面
        # 摘要会在 CRLF 文件上把「前像一致」误判成不一致，通道 A 就白拒了）
        with open(path, "rb") as f:
            raw = f.read()
        with open(path, encoding="utf-8") as f:
            src = f.read()
        pat_uid = re.compile(r'(\n(\s*)"' + re.escape(uid) + r'": \{\n)')
        m = pat_uid.search(src)
        if not m:
            continue
        block = src[m.end(1):m.end(1) + 600]
        if '"triggers"' in block:
            continue
        ind = m.group(2)
        trig_json = json.dumps(triggers, ensure_ascii=False)
        # selfmod 闭环（固化前强制，docstring:16）：裁决（本函数契约 = 入参只含
        # verify_patch 通过者，V22 守卫钉死 ⇒ verified=True ∧ 目标在授权自改写面内
        # ∧ 前像与盘面一致）→ 快照（逐字节前像）→ 审计（台账留痕）。**拒即不写盘**。
        _g = selfmod_gate([path], action=SELFMOD_ACTION_REWRITE,
                          why="通道 A triggers 固化（域 %s / 单元 %s）" % (dom, uid),
                          expect_sha={path: _selfmod_sha(raw)},
                          where="persist_triggers")
        if not _g["ok"]:
            continue                      # 裁决不通过：本文件本轮不动（留痕见台账）
        src = src[:m.end(1)] + ind + '    "triggers": ' + trig_json + ',\n' + src[m.end(1):]
        _tmp = path + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as f:
            f.write(src)
        # P2-14: atomic replace - concurrent instances never see a
        # half-written source file (batch 31).
        os.replace(_tmp, path)
        changed += 1
    return changed


# ==================== 通道 B：LLM 初稿 → verifier → 固化 ====================

def _atomic_write_json(path: str, obj) -> None:
    """状态 JSON 原子落盘（N169）：tmp + os.replace，对齐 persist_triggers
    的 P2-14 原子款（:178-183）——写中被 taskkill /F（watchdog kill_procs）
    强杀时，读者只见旧文件或新文件，绝不见半截截断态。
    """
    _tmp = path + ".tmp"
    with open(_tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(_tmp, path)


def _load_json_state(path: str, default, what: str):
    """通道 B 状态 JSON 读取（N169 自愈）：损坏即留痕重建，不再每轮同崩。

    文件缺失 → 返回 default；解析/读取失败 → 损坏文件改名
    `*.corrupt-<时间戳>` 留存现场（进度数据可人工找回）+ log_event 告警
    （round=channel_b_state_corrupt，已注册 watchdog DEGRADED 清单），
    返回 default 空状态重建——通道继续运行，不再 JSONDecodeError 永久死亡。
    """
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        try:
            os.replace(path, path + ".corrupt-"
                       + time.strftime("%Y%m%d%H%M%S"))
        except OSError:
            pass
        try:
            log_event({"round": "channel_b_state_corrupt",
                       "file": os.path.basename(path), "what": what,
                       "error": str(e)[:120],
                       "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
        except Exception:
            pass
        return default


# ==================== selfmod 安全闭环（快照 / 审计 / 裁决） ====================
# docstring「四机制安全闭环：selfmod 快照/审计/裁决 在每次固化前强制执行」的实现。
# 固化面只有两处，都是**自改**：通道 A persist_triggers 写 WISDOM 单元表源文件、
# 通道 B run_channel_b 的 verified 落盘；两处写盘前调 selfmod_gate，拒即不写盘。
SELFMOD_DIRNAME = "selfmod"                 # <STATE>/selfmod/
SELFMOD_SNAPSHOT_DIRNAME = "snapshots"      # <STATE>/selfmod/snapshots/
SELFMOD_AUDIT_NAME = "selfmod_audit.jsonl"  # <STATE>/selfmod/selfmod_audit.jsonl
CHANNEL_B_VERIFIED = "channel_b_verified_units.json"   # 通道 B 固化落点（唯一字面量）
#: 自改动作类（留痕用，取三档自治动作类同字母口径：C=就地改既有单元 / A=新增单元）。
#: 本闭环只做「前置闸 + 留痕」——**不接档位矩阵**：矩阵的对象面是认知图记忆节点
#: （docs/plans/记忆自处理三档自治_设计_v0.2.md §一），把源文件自改折成矩阵动作类
#: 会让默认「变更确认」档直接停掉通道 A 的固化（生产行为变更，须另行裁决）。
SELFMOD_ACTION_REWRITE = "C"
SELFMOD_ACTION_ADD = "A"
#: 通道 A 的域 → WISDOM 下单元表文件名（persist_triggers 与自改写面判据**共用一份**，
#: 不复制第二处字面量）。
UNIT_FILES = {
    "graph": "graph_db_units.py",
    "compiler": "compiler_code_units.py",
    "pylang": "python_code_units.py",
    "os": "os_units.py",
    "browser": "browser_units.py",
    "net": "net_units.py",
}


# 生效条件：无入参，按模块级 STATE 返回 (selfmod 目录, 快照目录, 审计台账路径) 三元组，只拼路径不建目录。
def _selfmod_paths():
    """selfmod 闭环的三个落点（按 STATE 现算——守卫可整体重定向 STATE）。"""
    d = os.path.join(STATE, SELFMOD_DIRNAME)
    return d, os.path.join(d, SELFMOD_SNAPSHOT_DIRNAME), \
        os.path.join(d, SELFMOD_AUDIT_NAME)


# 生效条件：data 为 bytes 时原样摘要、为 str 时先按 utf-8 编码再摘要，返回 sha256 十六进制前 16 位。
def _selfmod_sha(data) -> str:
    """盘面摘要（前 16 位，与真源指纹同口径）。"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


# 生效条件：path 经 normcase/abspath 归一后落于授权自改写面（WISDOM 下 UNIT_FILES 各单元表 + STATE 下的通道 B 落盘）内时返回 True，否则 False。
def _selfmod_allowed(path) -> bool:
    """授权自改写面（唯一真源）：本循环只许改自己的单元表与自己的 verified 账。

    为什么要有这一层：固化对象来自「扫描缺口 → 补丁」与「模型可控队列」两条链，
    路径若被解析/补丁带到别处（如任意 .py），自改就成了「任意文件覆写」。判据面
    只认同两份声明集合，不新增策略。
    """
    p = os.path.normcase(os.path.abspath(path))
    face = {os.path.normcase(os.path.abspath(os.path.join(WISDOM, fn)))
            for fn in UNIT_FILES.values()}
    face.add(os.path.normcase(os.path.abspath(
        os.path.join(STATE, CHANNEL_B_VERIFIED))))
    return p in face


# 生效条件：把 data（bytes）经同目录唯一临时名 + fsutil.publish 短重试写进 path；写成功置 tmp 为 None，任一步失败时删除残留临时文件后抛出原异常。
def _selfmod_write_bytes(path: str, data: bytes) -> None:
    """逐字节原子落盘（前像专用）：`fsutil.atomic_write` 是**文本**口径
    （写 str、newline 归一），前像要逐字节保真，故走二进制变体，原子性仍复用
    `fsutil.publish`（Windows 目标被短暂持锁时短重试，本仓明文单点）。
    """
    import fsutil
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".tmp-",
                               dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        fsutil.publish(tmp, path)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# 生效条件：path 不是常规文件时返回 None（无旧字节可留：首建目标没有前像）；是常规文件时原样读字节并以 `<快照目录>/<basename>.<秒>-<微秒>.bak` 为该前像落点写入（命名同 protect.snapshot_preimage 的「秒级+微秒」口径，同秒多次固化不互相踩像）后返回该路径。
def _selfmod_snapshot(path: str):
    """逐字节前像 → 快照目录；返回快照文件路径（目标不存在时返回 None）。"""
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        data = f.read()
    _d, snap_dir, _a = _selfmod_paths()
    os.makedirs(snap_dir, exist_ok=True)
    ts = (time.strftime("%Y%m%d-%H%M%S", time.localtime())
          + "-%06d" % (time.time_ns() // 1000 % 1000000))
    snap = os.path.join(snap_dir, "%s.%s.bak" % (os.path.basename(path), ts))
    _selfmod_write_bytes(snap, data)
    return snap


# 生效条件：无入参；对 rec 追加进审计台账——FileLock(SELFMOD_AUDIT, strict=True) 下调 fsutil.append_jsonl，锁超时或写失败即抛（调用方按「审计未就位 ⇒ 不许固化」处置）。
def _selfmod_audit(rec: dict) -> None:
    """append-only 审计台账（裁决记录口径：strict 锁，不许静默丢）。"""
    import fsutil
    _d, _s, audit = _selfmod_paths()
    os.makedirs(os.path.dirname(audit), exist_ok=True)
    with fsutil.FileLock(audit, strict=True):
        fsutil.append_jsonl(audit, rec)


# 生效条件：给定 paths（可为空列表）与 action/why——verified 为假、任一 path 不在授权自改写面内、expect_sha 中该 path 给出的摘要与**拍像前或拍像后**的盘面不等、快照抛异常、审计抛异常时返回 ok=False（并在审计可写时尽力留一条 ok=False 记录、向主日志写一行 selfmod_rejected），调用方**不得写盘**；全部成立时返回 ok=True 并带 snapshots（逐 path 的前像引用与改前摘要）与 audit（本次台账记录）。
def selfmod_gate(paths, action, why, verified=True, expect_sha=None, where=""):
    """固化前强制：裁决 → 快照 → 审计。**裁决不通过即拒且不改盘**（fail-closed）。

    裁决判据（三者全部成立才 ok=True）：
      ① verified —— 待固化对象已过既有验证（通道 A `verify_patch` / 通道 B
         的 verifier+cases）。由调用方把**判定值原样传入**：固化的验证输入不许
         旁路，False 即拒。
      ② 授权自改写面 —— 每个目标都落在 `_selfmod_allowed` 的面内。
      ③ 前像一致 —— 调用方按「读取时的字节」给出 expect_sha 时，当前盘面摘要
         必须相等（TOCTOU：读取到落盘之间被第三方改过 ⇒ 本次固化依据已失效 ⇒
         拒，绝不静默覆盖别人的改动）。
    快照/审计失败同样判拒——「安全件未就位就不许固化」是本闭环与纯留痕式审计
    （`branches._audit`：审计失败不阻断主流程）的分界。
    """
    paths = [p for p in (paths or []) if p]
    expect_sha = dict(expect_sha or {})
    rec = {"op": "selfmod", "action": action, "where": where, "why": why,
           "pid": os.getpid(), "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
           "mode": "selfmod", "verified": bool(verified),
           "targets": [os.path.abspath(p) for p in paths]}

    def _deny(reason, snapshots=None):
        rec.update({"ok": False, "reason": reason,
                    "snapshots": snapshots or []})
        try:                                   # 拒也要留痕；台账不可写不掩盖「拒」
            _selfmod_audit(rec)
        except Exception:
            pass
        try:                                   # 主日志一行（watchdog 未知 round 不计不下沉）
            log_event({"round": "selfmod_rejected", "action": action,
                       "where": where, "why": why, "reason": reason,
                       "targets": rec["targets"]})
        except Exception:
            pass
        return {"ok": False, "why": reason, "action": action,
                "snapshots": snapshots or [], "audit": rec}

    if not verified:
        return _deny("待固化对象未过既有验证（裁决不通过）")
    for p in paths:
        if not _selfmod_allowed(p):
            return _deny("目标不在授权自改写面内：%s" % p)
    for p in paths:
        want = expect_sha.get(p)
        if want is None:
            continue
        try:
            with open(p, "rb") as f:
                cur = _selfmod_sha(f.read())
        except OSError as e:
            return _deny("前像核验读盘失败：%s（%s）" % (p, e))
        if cur != want:
            return _deny("前像失效（TOCTOU）：%s 现盘面 %s ≠ 固化依据 %s"
                         % (p, cur, want))

    snaps = []
    for p in paths:
        try:
            snap = _selfmod_snapshot(p)
        except Exception as e:                 # noqa: BLE001 —— 快照失败即拒
            return _deny("快照失败：%s（%s）" % (p, str(e)[:120]),
                         snapshots=[s["snapshot"] for s in snaps if s["snapshot"]])
        snaps.append({"path": os.path.abspath(p), "snapshot": snap,
                      "before_sha": expect_sha.get(p) or ""})
    # 拍像后**再核一次**盘面：把 TOCTOU 窗口收到「本次核对 → 调用方写盘」之间
    # （拍像期间被改的话，前面那次核对就是过期证据）。此拒留下的快照是**该时点
    # 的盘面**，属留痕不是错误——拒绝记录（ok=False）与它成对。
    for p in paths:
        want = expect_sha.get(p)
        if want is None:
            continue
        try:
            with open(p, "rb") as f:
                cur = _selfmod_sha(f.read())
        except OSError as e:
            return _deny("前像复核读盘失败：%s（%s）" % (p, e),
                         snapshots=[s["snapshot"] for s in snaps if s["snapshot"]])
        if cur != want:
            return _deny("前像失效（拍像后盘面已变动）：%s 现盘面 %s ≠ 固化依据 %s"
                         % (p, cur, want),
                         snapshots=[s["snapshot"] for s in snaps if s["snapshot"]])
    rec.update({"ok": True, "snapshots": [s["snapshot"] for s in snaps
                                          if s["snapshot"]],
                "files": snaps})
    try:
        _selfmod_audit(rec)
    except Exception as e:                     # noqa: BLE001 —— 审计未就位即拒
        return {"ok": False, "why": "审计台账不可写：%s" % str(e)[:120],
                "action": action, "snapshots": rec["snapshots"], "audit": rec}
    return {"ok": True, "why": "", "action": action, "snapshots": rec["snapshots"],
            "audit": rec}


# 危险名 denylist（配合 __builtins__ 收窄双层防御）：
#   执行/IO 面：eval exec compile open __import__ breakpoint input
#   反射面：globals locals vars getattr setattr delattr（内省逃逸链入口）
#   进程面：exit quit（干扰循环宿主）
# ---- P1-7（批次 26）：LLM 产出代码的 AST 沙箱 ------------------------------
_GEN_BANNED_NAMES = frozenset({
    "eval", "exec", "compile", "open", "__import__", "breakpoint", "input",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "exit", "quit", "memoryview", "super",
})
# 自举生成物的合法计算面（排序/查找/字符串处理足够）；len/range 等纯函数
_GEN_SAFE_BUILTINS = {name: getattr(__import__("builtins"), name)
                      for name in (
                          "abs", "all", "any", "bool", "bytes", "chr", "dict",
                          "divmod", "enumerate", "filter", "float", "frozenset",
                          "hash", "hex", "int", "isinstance", "len", "list",
                          "map", "max", "min", "oct", "ord", "pow", "range",
                          "repr", "reversed", "round", "set", "slice", "sorted",
                          "str", "sum", "tuple", "zip", "True", "False", "None",
                          "ArithmeticError", "IndexError", "KeyError",
                          "TypeError", "ValueError", "ZeroDivisionError")}


# 生效条件：code 为 LLM 返回或 channel_b_queue.json 产出的 Python 源码文本；ast.parse 失败抛原语法异常，ast.walk 命中 Import/ImportFrom 节点、Name.id 属 _GEN_BANNED_NAMES、Attribute.attr 以下划线双端包夹或属 ("system","popen") 任一即抛 ValueError（不执行）；全部通过则以 {"__builtins__": _GEN_SAFE_BUILTINS} 为命名空间 exec 编译产物并返回该 ns（其中含源码定义的函数）。
def _safe_exec_gen(code: str) -> dict:
    """LLM 产出代码的受限 exec：AST denylist + 内建收窄（P1-7，批次 26）。

    拒绝（ValueError，不执行）：
      · import 面——Import / ImportFrom 节点（禁 os/subprocess 前置）；
      · 危险内建名调用——_GEN_BANNED_NAMES（执行/IO/反射/进程面）；
      · 反射逃逸链——dunder 属性访问（__class__/__globals__/__subclasses__…）
        与 os.system/popen 类敏感属性；
      · Lambda/推导式中的同名调用同样被 walk 覆盖（AST 全遍历）。
    执行命名空间 `__builtins__` 收窄到纯计算内建——即使 denylist 漏项，
    ns 里也没有 open/import 可拿。
    """
    import ast
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError(f"沙箱拒绝 import（行 {getattr(node, 'lineno', '?')}）"
                             "——自举产出应为纯函数，无需依赖")
        if isinstance(node, ast.Name) and node.id in _GEN_BANNED_NAMES:
            raise ValueError(f"沙箱拒绝受限名 {node.id}"
                             f"（行 {getattr(node, 'lineno', '?')}）")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in ("system", "popen"):
                raise ValueError(f"沙箱拒绝受限属性 .{node.attr}"
                                 f"（行 {getattr(node, 'lineno', '?')}）"
                                 "——反射逃逸链入口")
    ns = {"__builtins__": _GEN_SAFE_BUILTINS}
    exec(compile(code, "<gen>", "exec"), ns)   # noqa: S102——沙箱内（见上）
    return ns



def run_channel_b(llm_generate=None, max_tasks=5):
    """通道 B v2：从队列文件读取初稿（由 GLM-5.3-Flash 在对话轮次中批量
    产出到 channel_b_queue.json）→ verifier 校验 → 固化到 verified_units。

    如果队列文件不存在或为空且 llm_generate 可用 → 调 LLM API 生成。
    """
    from verifier import Verifier


    queue_path = os.path.join(STATE, "channel_b_queue.json")
    out_path = os.path.join(STATE, CHANNEL_B_VERIFIED)
    # 批次 35：初始化必须是 dict——空串形态在产物文件不存在时首次固化即
    # TypeError（verified[key]=... 对 str 赋值）。此缺陷因 run_channel_b
    # 长期无测试覆盖而潜伏（V21 报告流程建议 2 的全链路冒烟首跑即暴露）。
    # N169：读取走 _load_json_state——状态文件损坏（写中被 taskkill /F
    # 强杀截断）不再每轮裸 json.load 同崩，留痕重建后通道继续运行。
    verified = _load_json_state(out_path, {}, "verified_units（已验证固化态）")
    stats = {"generated": 0, "passed": 0, "failed": 0, "source": "queue",
             "selfmod_rejected": 0}
    newly = []          # 本轮新固化条目（key, item）——裁决拒时要原样退回 pending

    queue = []
    qd = _load_json_state(queue_path, None, "channel_b_queue（LLM 初稿队列）")
    if qd:
        queue = [t for t in qd.get("pending", [])
                 if t.get("status") not in ("verified", "failed")]

    if not queue and llm_generate:
        stats["source"] = "llm_api"
        # LLM API 通道（需要 key）。2026-08-28 修复：无 cases 的生成条目
        # 无法物理验证却会写回 pending 永久占位（not cases: continue）——
        # 卡死队列且顶掉人工条目。必须有 cases 才入队。
        for task_desc in ["堆排序", "二分查找", "快速排序"]:
            r = llm_generate(f"实现 {task_desc}")
            if r.get("ok") and r.get("cases"):
                queue.append({"task": task_desc, "code": r["code"],
                              "cases": r["cases"]})

    v = Verifier()
    for item in queue[:max_tasks]:
        task = item.get("task", "")
        code = item.get("code", "")
        cases = item.get("cases", [])
        # cases 格式：[[inp, exp], ...]——每个 case 是 [input, expected] 对
        if not code or not cases:
            stats["failed"] += 1
            # 与下方 fname 缺失分支同型（批次 35 先例）：缺 cases/code 的
            # 坏条目不标 failed 则永久 pending，且占据 queue[:max_tasks]
            # 处理窗口——max_tasks 个坏条目即令合法条目永不被处理
            # （stats 恒 0 无报错的静默饥饿；queue 是模型可控输入）。
            item["status"] = "failed"
            continue
        stats["generated"] += 1

        # verifier 校验
        import re as _re
        fn_m = _re.search(r"def (\w+)\(", code)
        fname = fn_m.group(1) if fn_m else None
        if not fname:
            stats["failed"] += 1
            # 批次 35：前置拒绝路径也必须标 failed——否则条目永久占位
            # 反复重试（与 2026-08-28 卡队列缺陷同型；冒烟守卫暴露）
            item["status"] = "failed"
            continue

        # 物理验证：exec + cases
        # P1-7（批次 26，外部审查报告）：code 来自 LLM 返回 / channel_b_queue.json
        # （模型可控输入），直接 exec = 以循环进程身份执行任意 Python。改为
        # AST 白名单沙箱（报告建议 2）：自举循环的合法产出 = 纯算术/逻辑
        # 函数（排序/查找等算法题），不需要 import 与 IO——denylist 拒绝
        # import 面、危险内建与反射逃逸链，命中即 ValueError 不执行。
        try:
            ns = _safe_exec_gen(code)
        except Exception:
            stats["failed"] += 1
            item["status"] = "failed"     # 批次 35：防卡队列（同上）
            # 批次 35：沙箱拒绝（import 面/危险内建/反射逃逸）的产出单独
            # 留痕——恶意/坏产出是最该进拒绝日志的类别（与 cases 未过同款）
            _rej = os.path.join(STATE, "channel_b_drafts", "rejected_log.json")
            os.makedirs(os.path.dirname(_rej), exist_ok=True)
            _rej_list = _load_json_state(_rej, [],
                                         "rejected_log（沙箱拒绝留痕）")
            _rej_list.append({"task": task, "layer": "queue_sandbox",
                              "why": "AST 沙箱拒绝（import 面/危险内建/"
                                     "反射逃逸链）",
                              "ts": time.strftime("%Y-%m-%d %H:%M")})
            _atomic_write_json(_rej, _rej_list)
            continue
        if fname not in ns or not callable(ns[fname]):
            stats["failed"] += 1
            item["status"] = "failed"     # 批次 35：防卡队列（同上）
            continue
        fn = ns[fname]
        all_pass = True
        for case in cases:
            inp_raw, exp = case[0], case[1]
            import inspect as _insp
            try:
                _np = len(_insp.signature(fn).parameters) if callable(fn) else 1
                _declared = item.get("nargs")
                # 展开判定：签名 >1 参数自动展开；单参函数但生成侧标注
                # nargs>1（如 arr 类参数）也展开——字符串单参不被误展开
                if (_np > 1 or (_declared is not None and _declared > 1)) \
                        and isinstance(inp_raw, (list, tuple)):
                    got = fn(*inp_raw)
                elif isinstance(inp_raw, list) and _np == 1 and _declared == 1:
                    got = fn(*inp_raw)
                else:
                    got = fn(inp_raw)
                if got != exp:
                    all_pass = False
                    break
            except Exception:
                all_pass = False
                break
        if all_pass:
            key = "task:" + task
            verified[key] = {"task": task, "code": code, "ok": True,
                             "fingerprint": __import__("hashlib").sha256(
                                 code.encode()).hexdigest()[:16],
                             "ts": time.strftime("%Y-%m-%d %H:%M")}
            newly.append((key, item))
            stats["passed"] += 1
            item["status"] = "verified"
        else:
            stats["failed"] += 1
            item["status"] = "failed"
            _rej = os.path.join(STATE, "channel_b_drafts", "rejected_log.json")
            os.makedirs(os.path.dirname(_rej), exist_ok=True)
            # V22 修复：必须是 []（对照 :319 沙箱拒绝分支）——空串形态在
            # rejected_log.json 不存在时首次失败即 AttributeError 崩溃，
            # 队列回写不执行 → 条目永久 pending，每轮重试再崩（死循环）。
            # N169：读取走 _load_json_state（损坏留痕重建）、写入走原子款。
            _rej_list = _load_json_state(_rej, [],
                                         "rejected_log（验证失败留痕）")
            _rej_list.append({"task": task, "layer": "queue_verifier",
                              "why": "cases 物理验证未过",
                              "ts": time.strftime("%Y-%m-%d %H:%M")})
            _atomic_write_json(_rej, _rej_list)

    # selfmod 闭环（固化前强制，docstring:16）：verified 落盘属**固化**，落盘前
    # 走 裁决（已验证 ∧ 目标在授权自改写面内）→ 快照（逐字节前像）→ 审计（台账）。
    # 裁决不通过 ⇒ 不落盘，且把本轮条目退回 pending（不谎报已固化——退回后下轮
    # 重新验证再试，不丢代码），stats 记 selfmod_rejected。
    flush_verified = True
    if newly:
        _g = selfmod_gate([out_path], action=SELFMOD_ACTION_ADD,
                          why="通道 B verified 固化（%d 条）" % len(newly),
                          where="run_channel_b")
        flush_verified = bool(_g["ok"])
        if not flush_verified:
            for key, item in newly:
                verified.pop(key, None)
                item["status"] = "new"
            stats["passed"] -= len(newly)
            stats["selfmod_rejected"] = len(newly)

    if queue:
        qd = {"_comment": "自举产物队列（已完成项标记 verified）",
              "_instructions": "bootstrap_loop 自动消化",
              "pending": queue}
        _atomic_write_json(queue_path, qd)       # N169：原子落盘
    if flush_verified:
        _atomic_write_json(out_path, verified)   # N169：原子落盘
    return stats


# 生效条件：channel_b 为假值时只走通道 A——scan_route_gaps() 的 gaps 非空则取前 max_patches 个构建含 add_triggers 的补丁，apply_patch 为假或 verify_patch 为假计入 patches_failed、verify_patch 为真计入 patches_verified 并入 persisted，persisted 非空才 persist_triggers(persisted)（只固化验证通过者）；channel_b 为真值时额外 import llm_channel 并以 max_tasks=3 调 run_channel_b，其异常写入 result["channel_b"]["error"]；随后 log_event 并返回 result。
def run_once(channel_b=False, max_patches=20):
    result = {"gaps": 0, "patches_applied": 0, "patches_verified": 0,
              "patches_failed": 0, "persisted_files": 0}

    # ① 通道 A：路由缺口扫描与 triggers 补丁
    gaps = scan_route_gaps()
    result["gaps"] = len(gaps)
    if gaps:
        patches = []
        for g in gaps[:max_patches]:
            p = build_trigger_patch(g)
            if p and p["add_triggers"]:
                patches.append(p)
        persisted = []
        for p in patches:
            if not apply_patch(p):
                result["patches_failed"] += 1
                continue
            if verify_patch(p):
                result["patches_verified"] += 1
                persisted.append(p)
            else:
                result["patches_failed"] += 1
        if persisted:
            # V22 修复：只固化**验证通过者**（persisted）——此前误传全量
            # patches，verify_patch 失败的补丁也被写进 wisdom 源文件，
            # 绕过「补丁→验证→固化」闸（docstring 声明的流程）。
            result["persisted_files"] = persist_triggers(persisted)

    # ② 通道 B：LLM 初稿 → verifier → 固化
    if channel_b:
        try:
            from llm_channel import generate_code
            rb = run_channel_b(generate_code, max_tasks=3)
            result["channel_b"] = rb
        except Exception as e:
            result["channel_b"] = {"error": str(e)[:80]}

    # N169：通道 B 异常轮记 channel_b_error（watchdog DEGRADED 清单）——
    # 修前恒记 bootstrap_v2（HEALTHY 清单），通道 B 连续死亡时内容级判活
    # 恒 alive 假绿，watchdog 永不介入。
    round_name = "channel_b_error" if isinstance(result.get("channel_b"), dict) \
        and result["channel_b"].get("error") else "bootstrap_v2"
    log_event({"round": round_name, **result})
    return result


# 生效条件：_dp.find_existing("verify_cache.json") 返回 None 时只记 status=skipped 并返回；否则读取该 json 的固定键 "a866f668bd6f4a1c048e16f684df69bf" 条目，记录 a866_ok、checks 中是否含 "缓存命中"、非 "_" 前缀键数量；读取或处理抛异常记 error 后返回。
def gap_watch() -> None:
    """GAP_DEBUG 诊断：自报本进程视角的配对信任指纹状态——
    区分「本进程写的 False」vs「他进程写回」。

    v3：校验缓存位置不再硬编码 `ROOT/aeis/data/verify_cache.json`，
    改由 datapath 在数据根/插件仓/归档区中查找；找不到只记 skipped。
    """
    try:
        vc = _dp.find_existing("verify_cache.json")
        if not vc:
            log_event({"round": "gap_watch", "status": "skipped",
                       "why": "verify_cache.json 未在数据根/插件仓/归档区找到",
                       "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
            return
        with open(vc, encoding="utf-8") as f:
            _d = json.load(f)
        _ent = _d.get("a866f668bd6f4a1c048e16f684df69bf")
        log_event({"round": "gap_watch", "pid": os.getpid(),
                   "src": vc,
                   "a866_ok": (_ent or {}).get("ok"),
                   "a866_cached": "缓存命中" in json.dumps((_ent or {}).get("checks", []), ensure_ascii=False),
                   "cache_entries": len([k for k in _d if not k.startswith("_")]),
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    except Exception as _e:
        log_event({"round": "gap_watch", "error": str(_e)[:100],
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")})


def csre_freshness(last_kp_fp):
    """CSRE 索引新鲜度（T7 · 2026-08-28）：kp 卡指纹变化才重建，
    快照过期会让 L1 词向量对新知识卡零向量。返回新的指纹。

    v3：数据库位置改为 WISDOM（随大脑仓），并在 DB 缺失时明确 skipped。
    """
    try:
        import sqlite3 as _sq
        import hashlib as _hl
        db_path = os.path.join(WISDOM, "wisdom-book-cloud.db")
        if not os.path.isfile(db_path):
            log_event({"round": "csre_rebuild_error", "status": "skipped",
                       "why": "wisdom-book-cloud.db 缺失: %s" % db_path,
                       "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
            return last_kp_fp
        conn = _sq.connect(db_path)
        kp_cnt, kp_max = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(created_at), 0) FROM nodes "
            "WHERE tags LIKE '%knowledge_point%'").fetchone()
        conn.close()
        kp_fp = _hl.sha256(f"{kp_cnt}:{kp_max}".encode()).hexdigest()[:12]
        if kp_fp != last_kp_fp:
            if last_kp_fp is not None:
                from csre import Csre
                _c = Csre(db_path)
                _st = _c.build_index()
                _c.save_index()
                log_event({"round": "csre_rebuild",
                           "units": _st.get("units"),
                           "vocab": _st.get("vocab"),
                           "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
            return kp_fp
    except Exception as e:
        log_event({"round": "csre_rebuild_error", "error": str(e)[:200],
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    return last_kp_fp


# 生效条件：argparse 从命令行取 --interval（默认 600）、--channel-b、--once 后，--once 为真时只调一次 run_once(channel_b=args.channel_b)，并在环境变量 GAP_DEBUG 为非空真值时调 gap_watch() 后返回；未给 --once 时进入无限循环：每轮 run_once(channel_b=args.channel_b)（异常记 loop_error 后继续），GAP_DEBUG 为非空真值时才 gap_watch()，随后无条件执行 csre_freshness(last_kp_fp)，再按 --interval 睡眠。
def main():
    """长期循环：--interval 秒一轮 run_once，异常留痕不中断。

    （2026-08-28 修复：函数体曾截断为残行 `im`——重启进程 NameError
     短命退出且静默；本轮补全并加轮次异常留痕。）
    v3：补上文档承诺但从未实现的 `--once` 单轮模式（守护/人工验证用）。
    """
    import argparse
    import time as _time

    ap = argparse.ArgumentParser(description="白箱自举后台循环 v3")
    ap.add_argument("--interval", type=int, default=600)
    ap.add_argument("--channel-b", action="store_true")
    ap.add_argument("--once", action="store_true", help="只跑一轮后退出")
    args = ap.parse_args()

    log_event({"round": "loop_start", "interval": args.interval,
               "channel_b": args.channel_b, "once": args.once,
               "pid": os.getpid(), "here": HERE, "wisdom": WISDOM,
               "state": STATE, "data_root": _dp.data_root(),
               "ts": _time.strftime("%Y-%m-%d %H:%M:%S")})

    if args.once:
        run_once(channel_b=args.channel_b)
        if os.environ.get("GAP_DEBUG"):
            gap_watch()
        return

    last_kp_fp = None
    while True:
        try:
            run_once(channel_b=args.channel_b)
        except Exception as e:
            log_event({"round": "loop_error", "error": str(e)[:200],
                       "ts": _time.strftime("%Y-%m-%d %H:%M:%S")})
        if os.environ.get("GAP_DEBUG"):
            gap_watch()
        last_kp_fp = csre_freshness(last_kp_fp)
        _time.sleep(args.interval)


if __name__ == "__main__":
    main()