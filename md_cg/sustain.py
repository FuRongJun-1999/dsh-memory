# -*- coding: utf-8 -*-
"""md_cg · 持续性自维持（记忆 OS #4）：常驻 / 心跳 / 自愈 / 会话续接

路线图「常驻服务：会话 / 心跳 / 自愈」的落地。回答三个问题：

① 别人怎么知道我还活着？—— **心跳戳**
   `<net_dir>/heartbeat.<name>.stamp`（原子写，含 ts / pid / uptime / task_running）。
   分级判定对齐 Mutual Sustain Loop v1.1：正常 / 警告 / 失联，阈值按心跳间隔的
   2.5× / 3.5×；**任务执行中阈值放宽**（working factor），避免长任务被误判死亡。
   戳写在仓库外（默认 ~/.mdcg/sustain），不污染知识库，也不随仓库泄露。

② 进程被杀会不会留下坏状态？—— **自愈（diagnose → heal）**
   诊断只读、不改动；修复动作幂等且逐条留审计：
     · 索引漂移 / 孤儿索引 → 重建索引（索引是派生物，可安全重建）
     · 索引增量分片积压 → 合并进快照
     · 陈旧临时文件     → 清理（被杀死的写者留下的唯一命名 tmp）
     · 日志半截行       → 补换行（否则下一条记录会粘在断行上）
     · 私有节点不可解   → **只报告不修**（缺密钥是权限事实，不是故障）
   原则：修复只碰派生物（索引 / 临时文件 / 日志边界），**永不删节点**。

③ 重启后从哪继续？—— **会话水位（SessionLedger）**
   `<root>/_sessions.json` 记录每个会话的 (last_t, last_seq, events)，
   与 `sources.Ingestor` 的 `_sources.json`（源视角水位）互补；重启后
   `resume_point(session)` 直接给出续接点，不重复摄取、不丢事件。

零第三方依赖。
"""
from __future__ import annotations

import json
import os
import threading
import time

from . import crypto
from .fsutil import append_jsonl, atomic_write, ends_mid_line
from .mdcg import LAYERS

STAMP_VERSION = 1
SUSTAIN_LOG = "_sustain.jsonl"
LEDGER_FILE = "_sessions.json"

DEFAULT_BEAT_INTERVAL = 600.0     # 心跳间隔 10min（对齐 mutual-sustain-loop）
DEFAULT_HEAL_INTERVAL = 300.0     # 自愈巡检 5min
DEFAULT_SCRUB_INTERVAL = 3600.0   # 记忆自净（抽查/去污染/校准）1h
DEFAULT_WARN_FACTOR = 2.5         # 2.5× 心跳间隔 → 警告
DEFAULT_DEAD_FACTOR = 3.5         # 3.5× → 失联
DEFAULT_WORKING_FACTOR = 2.0      # 任务执行中阈值 ×2
STALE_TEMP_AGE = 3600.0           # 临时文件超过 1h 视为陈旧
_POLL = 0.2                       # 循环轮询步长（常驻进程 CPU 可忽略）


# --------------------------------------------------------------------------
# 心跳
# --------------------------------------------------------------------------

def net_dir(d: str = None) -> str:
    """心跳戳目录：显式 → MDCG_SUSTAIN_DIR → ~/.mdcg/sustain（仓库外）。"""
    return (d or os.environ.get("MDCG_SUSTAIN_DIR")
            or os.path.join(os.path.expanduser("~"), ".mdcg", "sustain"))


def stamp_path(name: str, d: str = None) -> str:
    return os.path.join(net_dir(d), f"heartbeat.{name}.stamp")


def write_stamp(name: str, d: str = None, **extra) -> dict:
    """写一次心跳（原子替换）。extra 会并入戳内容（None 值丢弃）。"""
    rec = {"v": STAMP_VERSION, "name": name, "ts": time.time(),
           "pid": os.getpid(),
           "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "task_running": bool(extra.pop("task_running", False))}
    for k, v in extra.items():
        if v is not None:
            rec[k] = v
    atomic_write(stamp_path(name, d),
                 json.dumps(rec, ensure_ascii=False, indent=1))
    return rec


def read_stamp(name: str, d: str = None):
    """读心跳戳并附 age（秒）；不存在 / 损坏 → None。"""
    p = stamp_path(name, d)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
    except (ValueError, OSError):
        return None
    if not isinstance(rec, dict):
        return None
    rec["age"] = max(0.0, time.time() - float(rec.get("ts") or 0))
    return rec


def clear_stamp(name: str, d: str = None):
    try:
        os.remove(stamp_path(name, d))
    except OSError:
        pass


def judge(age, *, interval: float = DEFAULT_BEAT_INTERVAL,
          task_running: bool = False, warn: float = DEFAULT_WARN_FACTOR,
          dead: float = DEFAULT_DEAD_FACTOR,
          working: float = DEFAULT_WORKING_FACTOR) -> str:
    """按心跳年龄分级：ok / warning / dead / absent。

    task_running=True 时阈值整体放宽 working 倍——长任务期间不写心跳是正常的，
    若不放宽会把「正在干活」误判成「已死」。
    """
    if age is None:
        return "absent"
    factor = working if task_running else 1.0
    if age <= interval * warn * factor:
        return "ok"
    if age <= interval * dead * factor:
        return "warning"
    return "dead"


def peers(d: str = None):
    """列出本机所有心跳戳（含状态）。"""
    base = net_dir(d)
    if not os.path.isdir(base):
        return []
    out = []
    for fn in sorted(os.listdir(base)):
        if not (fn.startswith("heartbeat.") and fn.endswith(".stamp")):
            continue
        rec = read_stamp(fn[len("heartbeat."):-len(".stamp")], base)
        if rec:
            rec["state"] = judge(rec["age"],
                                 task_running=bool(rec.get("task_running")))
            out.append(rec)
    return out


# --------------------------------------------------------------------------
# 诊断（只读）
# --------------------------------------------------------------------------

def _count_node_files(root: str) -> int:
    """轻量统计磁盘节点数（只数文件名，不解析正文）。"""
    n = 0
    for layer in LAYERS:
        for _dp, _dirs, files in os.walk(os.path.join(root, layer)):
            n += sum(1 for f in files if f.endswith(".md"))
    return n


def _list_stale_temps(root: str, older_than: float):
    now, out = time.time(), []
    bases = [root] + [os.path.join(root, l) for l in LAYERS]
    for base in bases:
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            if ".tmp-" not in name or not name.startswith("."):
                continue
            p = os.path.join(base, name)
            try:
                if now - os.path.getmtime(p) > older_than:
                    out.append(p)
            except OSError:
                pass
    return out


def _half_line_logs(root: str):
    """顶层行式日志里末尾不是换行的（写者被杀留下的半截记录）。"""
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        if not (name.endswith(".jsonl") or name.endswith(".log")):
            continue
        p = os.path.join(root, name)
        if os.path.isfile(p) and ends_mid_line(p):
            out.append(p)
    return out


def _index_log_shards(root: str):
    d = os.path.join(root, "_index_log")
    if not os.path.isdir(d):
        return []
    return [f for f in os.listdir(d) if f.endswith(".log")]


def _locked_nodes(cg) -> int:
    """加密引擎在「未解锁」状态下被隔离的私有节点数（缺密钥 = 权限事实）。"""
    if not hasattr(cg, "crypto_status"):
        return 0
    try:
        st = cg.crypto_status() or {}
    except Exception:
        return 0
    if st.get("unlocked"):
        return 0
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    return sum(1 for e in nodes.values()
               if (e.get("sensitivity") or "") in crypto.ENCRYPTED_LEVELS)


def diagnose(cg, *, name: str = "md_cg", stale_temp_age: float = STALE_TEMP_AGE,
             check_heartbeat: bool = True) -> dict:
    """只读体检：返回 issues（带 fix 名）与 stats，不改动任何文件。"""
    root = cg.root
    issues = []
    nodes = (getattr(cg, "index", {}) or {}).get("nodes") or {}
    disk = _count_node_files(root)

    if len(nodes) != disk:
        issues.append({"code": "index_drift", "severity": "warning",
                       "detail": f"索引 {len(nodes)} ≠ 磁盘 {disk}",
                       "fix": "rebuild_index"})
    orphans = [nid for nid, e in nodes.items()
               if e.get("path")
               and not os.path.exists(os.path.join(root, e["path"]))]
    if orphans:
        issues.append({"code": "index_orphan", "severity": "warning",
                       "detail": f"{len(orphans)} 条索引指向不存在的文件",
                       "sample": orphans[:5], "fix": "rebuild_index"})

    shards = _index_log_shards(root)
    if shards:
        issues.append({"code": "index_log_backlog", "severity": "info",
                       "detail": f"{len(shards)} 个索引增量分片未合并",
                       "fix": "flush_index"})

    temps = _list_stale_temps(root, stale_temp_age)
    if temps:
        issues.append({"code": "stale_temps", "severity": "info",
                       "detail": f"{len(temps)} 个陈旧临时文件",
                       "sample": [os.path.basename(p) for p in temps[:5]],
                       "fix": "sweep_temps"})

    half = _half_line_logs(root)
    if half:
        issues.append({"code": "half_line_logs", "severity": "warning",
                       "detail": f"{len(half)} 个日志末尾半截行",
                       "sample": [os.path.basename(p) for p in half[:5]],
                       "fix": "seal_half_lines"})

    locked = _locked_nodes(cg)
    if locked:
        issues.append({"code": "locked_nodes", "severity": "info",
                       "detail": f"{locked} 个私有节点密文不可解（缺密钥）",
                       "fix": None})   # 权限事实，不自愈

    # ref 漂移 / 悬空（R3）：索引是派生物，源变了就报 stale，源没了就报 dangling。
    # 只读、不抛；修复动作是重跑 index_code / index_doc（rebuild_refs）。
    from . import refindex
    refs = refindex.check_refs(cg, ledger=refindex.Ledger(root))
    if refs["stale"]:
        issues.append({"code": "ref_stale", "severity": "warning",
                       "detail": f"{len(refs['stale'])} 个 ref 漂移（源文件已改动）",
                       "sample": [r.get("path") for r in refs["stale"][:5]],
                       "fix": "rebuild_refs"})
    if refs["dangling"]:
        issues.append({"code": "ref_dangling", "severity": "warning",
                       "detail": f"{len(refs['dangling'])} 个 ref 悬空（源文件已删除）",
                       "sample": [r.get("path") for r in refs["dangling"][:5]],
                       "fix": "rebuild_refs"})
    if refs.get("truncated"):
        issues.append({"code": "ref_check_truncated", "severity": "info",
                       "detail": f"ref 巡检只覆盖前 {refs['max_nodes']} 个节点，结果不完整",
                       "fix": None})   # 覆盖缺口，显式说出来而非静默

    if check_heartbeat:
        st = read_stamp(name)
        state = (judge(st["age"], task_running=bool(st.get("task_running")))
                 if st else "absent")
        if state != "ok":
            issues.append({"code": "heartbeat_" + state, "severity": "info",
                           "detail": f"本机心跳状态：{state}", "fix": "beat"})

    return {"ok": not any(i["severity"] == "warning" for i in issues),
            "root": root, "issues": issues, "t": time.time(),
            "stats": {"nodes_indexed": len(nodes), "nodes_on_disk": disk,
                      "index_log_shards": len(shards), "stale_temps": len(temps),
                      "half_line_logs": len(half), "locked_nodes": locked,
                      "ref_checked": refs["checked"],
                      "ref_stale": len(refs["stale"]),
                      "ref_dangling": len(refs["dangling"])}}


# --------------------------------------------------------------------------
# 自愈
# --------------------------------------------------------------------------

def _seal_half_line(path: str):
    with open(path, "ab") as f:
        f.write(b"\n")


def _audit(root: str, op: str, action: str, detail: str = ""):
    append_jsonl(os.path.join(root, SUSTAIN_LOG),
                 {"t": time.time(), "op": op, "action": action,
                  "detail": str(detail)[:200], "pid": os.getpid()})


def heal(cg, *, name: str = "md_cg", dry_run: bool = False,
         stale_temp_age: float = STALE_TEMP_AGE) -> dict:
    """按诊断结果修复派生物。dry_run=True 时只列动作、不落盘。"""
    before = diagnose(cg, name=name, stale_temp_age=stale_temp_age)
    codes = {i["code"] for i in before["issues"]}
    root = cg.root
    actions = []

    def act(code: str, detail: str, fn):
        if dry_run:
            actions.append({"code": code, "detail": detail, "applied": False})
            return
        try:
            fn()
            actions.append({"code": code, "detail": detail,
                            "applied": True, "ok": True})
        except Exception as e:                       # 自愈失败不能拖垮进程
            actions.append({"code": code, "detail": detail, "applied": True,
                            "ok": False, "error": f"{type(e).__name__}: {e}"})
        _audit(root, "heal", code, detail)

    if "index_drift" in codes or "index_orphan" in codes:
        act("rebuild_index", "重建索引（漂移 / 孤儿）", cg.rebuild_index)
    if "ref_stale" in codes or "ref_dangling" in codes:
        from . import refindex as _ri
        _led = _ri.Ledger(root)
        act("rebuild_refs", "按 ref 重建源索引（修复漂移；悬空需人工处置）",
            lambda: _ri.rebuild(cg, ledger=_led))
    if "index_log_backlog" in codes:
        act("flush_index", "合并索引增量分片", cg.flush)
    if "stale_temps" in codes:
        paths = _list_stale_temps(root, stale_temp_age)

        def _sweep():
            for p in paths:
                try:
                    os.remove(p)
                except OSError:
                    pass
        act("sweep_temps", f"清理 {len(paths)} 个陈旧临时文件", _sweep)
    if "half_line_logs" in codes:
        paths = _half_line_logs(root)
        act("seal_half_lines", f"修补 {len(paths)} 个半截日志行",
            lambda: [_seal_half_line(p) for p in paths])

    after = (before if dry_run
             else diagnose(cg, name=name, stale_temp_age=stale_temp_age))
    return {"ok": after["ok"], "dry_run": dry_run, "actions": actions,
            "before": before["stats"], "after": after["stats"],
            "t": time.time()}


# --------------------------------------------------------------------------
# 会话水位（重启续接）
# --------------------------------------------------------------------------

class SessionLedger:
    """会话水位账本：<root>/_sessions.json。

    与 sources.Ingestor 的水位互补：Ingestor 记「某个源读到哪」，
    这里记「某个会话发生过什么」——重启后按会话给出续接点。
    """

    def __init__(self, root: str):
        self.root = root
        self.path = os.path.join(root, LEDGER_FILE)

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict) and isinstance(d.get("sessions"), dict):
                    return d
            except (ValueError, OSError):
                pass
        return {"schema": 1, "sessions": {}}

    def _save(self, d):
        atomic_write(self.path, json.dumps(d, ensure_ascii=False, indent=1))

    def note(self, session: str, *, t=None, seq=None, n: int = 1,
             actor: str = None) -> dict:
        """记一笔会话活动（事件计数 + 最后 (t, seq) 水位）。"""
        d = self._load()
        s = d["sessions"].setdefault(
            session, {"events": 0, "first_t": None, "last_t": None})
        s["events"] = int(s.get("events") or 0) + int(n)
        if t is not None:
            s["last_t"] = float(t)
            if s.get("first_t") is None:
                s["first_t"] = float(t)
        if seq is not None:
            s["last_seq"] = seq
        if actor:
            s["actor"] = actor
        s["updated_at"] = time.time()
        self._save(d)
        return dict(s, session=session)

    def resume_point(self, session: str) -> dict:
        """重启续接点：(t, seq) 之后的事件才是新的。"""
        s = self._load()["sessions"].get(session)
        if not s:
            return {"session": session, "resume": None, "events": 0}
        return {"session": session, "events": s.get("events", 0),
                "resume": {"t": s.get("last_t"), "seq": s.get("last_seq")},
                "last_t": s.get("last_t"), "actor": s.get("actor")}

    def sessions(self) -> dict:
        return dict(self._load()["sessions"])

    def summary(self) -> dict:
        d = self._load()["sessions"]
        return {"sessions": len(d),
                "events": sum(int(v.get("events") or 0) for v in d.values()),
                "latest": max((v.get("last_t") or 0) for v in d.values())
                if d else None}


def watermarks(cg) -> dict:
    """源视角水位快照（读 sources.Ingestor 的 _sources.json）。"""
    p = os.path.join(cg.root, "_sources.json")
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (ValueError, OSError):
        return {}
    return dict((d or {}).get("sources") or {})


# --------------------------------------------------------------------------
# 常驻循环
# --------------------------------------------------------------------------

class SustainLoop:
    """常驻自维持循环：后台线程周期心跳 + 周期巡检 + 必要时自愈。

    daemon 线程，进程退出即消失；`stop()` 会清掉自己的心跳戳，
    让对端立刻看到「正常下线」而不是「失联」。
    """

    def __init__(self, cg, name: str = "md_cg", *,
                 beat_interval: float = DEFAULT_BEAT_INTERVAL,
                 heal_interval: float = DEFAULT_HEAL_INTERVAL,
                 auto_heal: bool = True, d: str = None,
                 ledger: SessionLedger = None,
                 scrub_interval: float = DEFAULT_SCRUB_INTERVAL,
                 auto_scrub: bool = False):
        self.cg = cg
        self.name = name
        self.beat_interval = float(beat_interval)
        self.heal_interval = float(heal_interval)
        self.auto_heal = bool(auto_heal)
        self.d = net_dir(d)
        self.ledger = ledger or SessionLedger(cg.root)
        self.scrub_interval = float(scrub_interval)
        self.auto_scrub = bool(auto_scrub)
        self.task_running = False
        self.beats = 0
        self.last_beat = None
        self.last_diagnose = None
        self.heals = []
        self.last_scrub = None
        self.scrubs = []
        self._started_at = None
        self._th = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ---- 心跳 ----

    def beat(self, task_running: bool = None) -> dict:
        if task_running is not None:
            self.task_running = bool(task_running)
        rec = write_stamp(
            self.name, self.d, task_running=self.task_running, root=self.cg.root,
            uptime=round(time.time() - self._started_at, 3)
            if self._started_at else 0.0)
        self.beats += 1
        self.last_beat = rec["ts"]
        return rec

    # ---- 生命周期 ----

    def start(self):
        if self._th is not None and self._th.is_alive():
            return self
        self._started_at = time.time()
        self._stop.clear()
        self.beat()
        self._th = threading.Thread(target=self._run, name="mdcg-sustain",
                                    daemon=True)
        self._th.start()
        return self

    def stop(self, timeout: float = 3.0):
        self._stop.set()
        if self._th is not None:
            self._th.join(timeout)
            self._th = None
        clear_stamp(self.name, self.d)
        return self

    def _run(self):
        next_beat = time.time() + self.beat_interval
        next_heal = time.time() + self.heal_interval
        next_scrub = time.time() + self.scrub_interval
        while not self._stop.is_set():
            now = time.time()
            if now >= next_beat:
                try:
                    self.beat()
                except Exception:
                    pass                       # 心跳失败不中断常驻
                next_beat = now + self.beat_interval
            if now >= next_heal:
                try:
                    self._tick_heal()
                except Exception:
                    pass                       # 巡检失败不中断常驻
                next_heal = now + self.heal_interval
            if now >= next_scrub:
                try:
                    self._tick_scrub()
                except Exception:
                    pass                       # 自净失败不中断常驻
                next_scrub = now + self.scrub_interval
            self._stop.wait(_POLL)

    def _tick_scrub(self):
        """记忆自净：抽查 → 联想 → 去污染 → 校准偏差。

        `auto_scrub=False`（默认）时只做只读巡检并记账，不动任何节点；
        开启后才执行去污染（仍只做可逆动作、永不删节点）。
        """
        from . import scrub
        rep = scrub.sweep(self.cg, dry_run=not self.auto_scrub)
        rec = {"t": rep["t"], "ok": rep["ok"],
               "n_issues": rep["audit"]["n_issues"],
               "n_high_medium": rep["n_high_medium"],
               "applied": rep["decontaminate"]["applied"],
               "dry_run": rep["dry_run"]}
        self.last_scrub = rec
        with self._lock:
            self.scrubs.append(rec)
            self.scrubs = self.scrubs[-20:]

    def _tick_heal(self):
        rep = diagnose(self.cg, name=self.name)
        self.last_diagnose = {"t": time.time(), "ok": rep["ok"],
                              "issues": [i["code"] for i in rep["issues"]]}
        if not (self.auto_heal and not rep["ok"]):
            return
        res = heal(self.cg, name=self.name)
        if res["actions"]:
            with self._lock:
                self.heals.append({"t": res["t"],
                                   "actions": [a["code"] for a in res["actions"]]})
                self.heals = self.heals[-20:]

    # ---- 状态 ----

    def status(self) -> dict:
        st = read_stamp(self.name, self.d)
        state = (judge(st["age"], interval=self.beat_interval,
                       task_running=bool(st.get("task_running")))
                 if st else "stopped")
        return {"name": self.name, "running": bool(self._th
                                                   and self._th.is_alive()),
                "pid": os.getpid(),
                "uptime": round(time.time() - self._started_at, 3)
                if self._started_at else 0.0,
                "beats": self.beats, "last_beat": self.last_beat,
                "beat_interval": self.beat_interval,
                "heal_interval": self.heal_interval,
                "auto_heal": self.auto_heal, "state": state,
                "task_running": self.task_running,
                "last_diagnose": self.last_diagnose,
                "heals": self.heals[-5:],
                "scrub_interval": self.scrub_interval,
                "auto_scrub": self.auto_scrub,
                "last_scrub": self.last_scrub,
                "peers": peers(self.d),
                "sessions": self.ledger.summary()}


_LOOPS = {}
_LOOPS_LOCK = threading.Lock()


def ensure_loop(cg, name: str = "md_cg", **kw) -> SustainLoop:
    """按 (root, name) 复用同一个常驻循环（避免重复线程 / 重复戳）。"""
    key = (os.path.abspath(cg.root), name)
    with _LOOPS_LOCK:
        lp = _LOOPS.get(key)
        if lp is None:
            lp = SustainLoop(cg, name=name, **kw)
            _LOOPS[key] = lp
        return lp


def get_loop(cg, name: str = "md_cg"):
    return _LOOPS.get((os.path.abspath(cg.root), name))


def stop_all():
    """测试 / 进程退出用：停掉本进程创建的所有常驻循环。"""
    with _LOOPS_LOCK:
        loops = list(_LOOPS.values())
        _LOOPS.clear()
    for lp in loops:
        try:
            lp.stop()
        except Exception:
            pass


def summary(cg, name: str = "md_cg") -> dict:
    """并入 health_os 的轻量摘要（只读戳与计数，不做巡检）。"""
    st = read_stamp(name)
    lp = get_loop(cg, name)
    return {
        "heartbeat": ({"age": round(st["age"], 1),
                       "state": judge(st["age"],
                                      task_running=bool(st.get("task_running"))),
                       "pid": st.get("pid"),
                       "task_running": bool(st.get("task_running"))}
                      if st else {"state": "absent"}),
        "loop": ({"running": bool(lp._th and lp._th.is_alive()),
                  "beats": lp.beats, "state": lp.status()["state"]}
                 if lp else {"running": False}),
        "sessions": SessionLedger(cg.root).summary(),
        "scrub": scrub_summary(cg),
    }


def scrub_summary(cg) -> dict:
    """记忆自净摘要（惰性导入，避免模块加载顺序耦合）。"""
    try:
        from . import scrub
        return scrub.summary(cg)
    except Exception:                     # noqa: BLE001
        return {}
