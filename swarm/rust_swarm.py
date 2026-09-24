# -*- coding: utf-8 -*-
"""rust_swarm · 多进程蜂群（RUST-SWARM-REV1 · v0.5）
荣 2026-09-06 裁定：多实例并行（进程级蜂群）+ 消息传递 + 实例私有信任/条件空间 + 聚合层。
对齐 aeis.swarm 语义（事件总线 WAL/ACK/HMAC、trust_aggregator T_avg/T_min/T_variance/
T_alignment、B6 防操纵）。职责：
  make_swarm_config           蜂群配置生成（实例身份/初始环境/路由表）→ swarm.json
  run_swarm                   调 protocol_vm swarm 子命令 → 报告解析
  verify_wal_signatures       WAL HMAC-SHA256 验签（Python hashlib/hmac 独立复核——
                              Rust 侧手写 SHA256 的交叉验证）
  aggregate_trust_python      信任聚合 Python 参照实现（对照 Rust 聚合一致性）
白箱 · 确定性。协调器与实例均为 Rust 进程（多进程隔离）。
"""
from __future__ import annotations
import hashlib
import hmac as _hmac
import json
import os
import subprocess
from typing import Dict, List, Optional

from .rust_codegen import build_rust_exe

ALGO = "rust_swarm-0.1"
DEFAULT_SECRET = "蜂群默认密钥"


# 生效条件：instances 每项必含 id（i["id"]），role/trust/symbols 分别缺省回落 "worker"/0.0/{}，rounds 经 max(1, int(rounds))，routes 为 None 或空时得到空列表、否则每项必含 from 与 to（r["from"]/r["to"]），condition_space 非 None 时写入 cfg["condition_space"]，返回 cfg；
def make_swarm_config(instances: List[Dict], routes: Optional[List[Dict]] = None,
                      rounds: int = 1, shared_secret: str = DEFAULT_SECRET,
                      topology: str = "",
                      condition_space: Optional[Dict] = None) -> Dict:
    """instances: [{"id","role","trust","symbols"}]；routes: [{"from","event_type","to","payload","level"}]
    payload 中 "@trust" 占位符在运行时替换为源实例终态信任值。
    topology: "" = 未指定（角色保持用户声明）；"mesh"/"hierarchical"/"centralized"
    指定后角色由拓扑推导（首实例为 queen/coordinator，其余 worker）——G4a。
    condition_space: G-R2 条件空间卡（§0.0.5 四要素，缺一不可）：
      {"space_id","observation_position","observation_tool","time_window","existence_constraint"}"""
    cfg = {"algo": ALGO, "shared_secret": shared_secret, "rounds": max(1, int(rounds)),
           "topology": topology,
           "instances": [{"id": i["id"], "role": i.get("role", "worker"),
                          "trust": float(i.get("trust", 0.0)),
                          "symbols": i.get("symbols", {})} for i in instances],
           "routes": [{"from": r["from"], "event_type": r.get("event_type", "消息"),
                       "to": r["to"], "payload": r.get("payload", "null"),
                       "level": int(r.get("level", 0))} for r in (routes or [])]}
    if condition_space is not None:
        cfg["condition_space"] = condition_space
    return cfg


# 生效条件：先把 config 写入 project_dir/swarm.json，exe 为假值时回落 build_rust_exe(project_dir)，以 [exe, "swarm", "--config", cfg_path, "--wal", wal_full] 运行且 pbc_path 真值时追加 --pbc，子进程超时（TimeoutExpired）或启动失败（OSError，exe 缺失）同样返回 stage=swarm 的失败 dict（不向调用方抛异常），returncode!=0 返回 stage=swarm，末行 JSON 解析失败返回 stage=parse，成功返回 {"ok": True, "report": report, "wal": wal_full}；
def run_swarm(project_dir: str, config: Dict, wal_path: str = "events.jsonl",
              timeout: int = 120, pbc_path: Optional[str] = None,
              exe: Optional[str] = None) -> Dict:
    """写 swarm.json → protocol_vm swarm → 报告解析（含 WAL 路径回传）。

    `exe` / `pbc_path` 供独立形态（`cargo build --release --no-default-features`，
    未嵌入字节码）使用：协调器须显式 `--pbc`，并由 Rust 侧转发给实例子进程。
    生成项目形态（默认 `embed`）两者均可省略。

    报告口径契约（消费方必读）：
    - `watermarks` 是「实例消费到的全局事件版本号 seq」（单调递增），不是消息条数；
      消息条数语义在 `gossip` 字段（也是计数口径）。
    - `trust` 聚合值（T_avg/T_min/T_variance/T_alignment）由 Rust 侧以 6 位小数
      精度呈现——跨实现比对用 1e-6 容差，勿做字符串/1e-9 级严格比较。
    - `events` 计数包含轮末快照行；事件口径（不含快照）= events − 快照行数。
    """
    cfg_path = os.path.join(project_dir, "swarm.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False)
    exe = exe or build_rust_exe(project_dir)
    wal_full = os.path.abspath(os.path.join(project_dir, wal_path))
    cmd = [exe, "swarm", "--config", cfg_path, "--wal", wal_full]
    if pbc_path:
        cmd += ["--pbc", pbc_path]
    # Rust 侧输出为 UTF-8（JSON 含中文符号名）——必须显式指定编码：
    # Windows 默认 GBK 解码会在多字节边界崩溃，导致 stdout 变为 None。
    # 超时/exe 缺失须按本函数错误契约返回 {ok: False, stage: ...} dict——
    # 此前 TimeoutExpired/FileNotFoundError 直接穿透调用方（swarm_cli 整条
    # CLI traceback 而非结构化错误，2026-09-25 缺陷）。
    try:
        r = subprocess.run(cmd,
                           capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", cwd=project_dir)
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "stage": "swarm",
                "stderr": f"swarm 子进程超时（>{timeout}s）被终止: {e}"}
    except OSError as e:
        return {"ok": False, "stage": "swarm",
                "stderr": f"swarm 子进程启动失败（exe 缺失/不可执行？）: {e}"}
    if r.returncode != 0:
        return {"ok": False, "stage": "swarm", "stderr": r.stderr[-3000:]}
    try:
        report = json.loads(r.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"ok": False, "stage": "parse", "stdout": r.stdout[-2000:]}
    return {"ok": True, "report": report, "wal": wal_full}


# 生效条件：逐行读 wal_path，strip 后为空则跳过，否则以 rec["type"]/["from"]/["to"]/["round"]/["ts"] 与 rec.get("seq", 0) 及原始 payload 文本重算 HMAC 与 rec["hmac"] 比对，type=="__snapshot__" 只计入 snapshots 而其余计入 total/verified/bad，单行 json.loads/index/取键失败（畸形或被篡改）计入 bad 并 continue（验签器面对的正是被篡改的 WAL，不得自己先崩），all_valid = bad==0 and snap_bad==0；
def verify_wal_signatures(wal_path: str, shared_secret: str) -> Dict:
    """WAL 逐条验签（Python hmac 独立实现——交叉验证 Rust 手写 SHA256）。
    签名串 v0.7.1：seq|type|from|to|round|ts|payload（与 Rust swarm.rs 约定
    一致）——seq 入签后才是不可变事件身份/顺序证明。旧 WAL（签名串无 seq）
    不兼容，须重跑再生产物。
    B1：轮末快照行（type=__snapshot__）同样验签（防篡改），但不计入事件 total。
    口径契约：total/verified/bad 均为「事件行」口径；快照行验签统计单列于
    返回值 snapshots={verified,bad}；all_valid = 事件行与快照行全部通过。"""
    ok = bad = 0
    snap_ok = snap_bad = 0
    with open(wal_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                # payload 在 WAL 里是内嵌 JSON——签名时用原始文本切片保真；
                # 行尾恰有一个 WAL 记录级闭括号需剥掉（payload 文本后面是行闭合 '}'）
                raw = line[line.index('"payload":') + len('"payload":'):]
                raw_payload = raw[:-1] if raw.endswith("}") else raw
                msg = "%s|%s|%s|%s|%s|%s|%s" % (
                    rec.get("seq", 0), rec["type"], rec["from"], rec["to"],
                    rec["round"], rec["ts"], raw_payload)
                expect = _hmac.new(shared_secret.encode(), msg.encode(),
                                   hashlib.sha256).hexdigest()
                valid = _hmac.compare_digest(expect, rec["hmac"])
            except (ValueError, KeyError, TypeError):
                # 畸形/被篡改行（非 JSON、缺 "payload":/必填键、hmac 非字符串）：
                # 验签器恰是面对篡改的——坏行计入 bad（all_valid=False）而非
                # 崩掉整轮验签（2026-09-25 缺陷 #2）
                bad += 1
                continue
            if rec.get("type") == "__snapshot__":
                # 快照行：验签（防篡改）但单列统计，不混入事件口径
                if valid:
                    snap_ok += 1
                else:
                    snap_bad += 1
            elif valid:
                ok += 1
            else:
                bad += 1
    return {"total": ok + bad, "verified": ok, "bad": bad,
            "snapshots": {"verified": snap_ok, "bad": snap_bad},
            "all_valid": bad == 0 and snap_bad == 0}


# 生效条件：trust_values 逐项 clamp 到 [0.0, 1.0] 后得到 ts，ts 为空列表时四项全返回 0.0，否则返回 avg=sum/n、min(ts)、var=sum((t-avg)^2)/n 与 avg>0 时的 align=1-var/avg（avg 为 0 时 align=0.0）；
def aggregate_trust_python(trust_values: List[float]) -> Dict:
    """信任聚合 Python 参照（对齐 aeis.swarm.trust_aggregator.snapshot 操作化定义：
    T_alignment = 1 - T_variance / T_avg；值域 0-1 夹取）。"""
    ts = [max(0.0, min(1.0, float(t))) for t in trust_values]
    if not ts:
        return {"T_avg": 0.0, "T_min": 0.0, "T_variance": 0.0, "T_alignment": 0.0}
    n = len(ts)
    avg = sum(ts) / n
    var = sum((t - avg) ** 2 for t in ts) / n
    align = 1.0 - var / avg if avg > 0 else 0.0
    return {"T_avg": avg, "T_min": min(ts), "T_variance": var, "T_alignment": align}


DEFAULT_HEALTH_WEIGHTS = {"success": 0.4, "uptime": 0.2, "threat": 0.2,
                          "integrity": 0.2}


# 生效条件：weights/verify_fail/total_events/gossip_coverage 为 None 或假值时分别回落 DEFAULT_HEALTH_WEIGHTS 与空 dict，对 round_outcomes 每实例按 total=max(1,len(outcomes))、非 None 计参与、True 计成功、False 计 error，total_events 缺省 0 时 ir=1.0*覆盖率（否则 (t-vf)/t*cov，cov 由 gc.get(iid,1.0) 夹取到 0-1），score 夹取到 [0,1]；
def aggregate_health_python(round_outcomes: Dict[str, list],
                            verify_fail: Optional[Dict[str, int]] = None,
                            total_events: Optional[Dict[str, int]] = None,
                            weights: Optional[Dict[str, float]] = None,
                            gossip_coverage: Optional[Dict[str, float]] = None) -> Dict:
    """实例健康四因子 Python 参照（B3 甲案 · 与 Rust health.rs score_instance 同公式）：
    score = W.success×成功轮占比 + W.uptime×参与轮占比 + W.threat×(1−error轮占比)
            + W.integrity×验签通过率×gossip覆盖率。
    round_outcomes: {实例id: [True|False|None, ...]} 按轮序（None=缺失轮）。
    gossip_coverage: {实例id: 实收/对账基准}（G3c；缺省=1.0 无 gossip 场景）。"""
    w = weights or DEFAULT_HEALTH_WEIGHTS
    vf = verify_fail or {}
    te = total_events or {}
    gc = gossip_coverage or {}
    out: Dict[str, Dict] = {}
    for iid, outcomes in round_outcomes.items():
        total = max(1, len(outcomes))
        part = [x for x in outcomes if x is not None]
        participated = len(part)
        success = sum(1 for x in part if x is True)
        errors = sum(1 for x in part if x is False)
        p = max(1, participated)
        sr = success / total
        ur = participated / total
        tr = errors / p
        t = te.get(iid, 0)
        cov = min(1.0, max(0.0, gc.get(iid, 1.0)))
        ir = (1.0 if t == 0 else (t - vf.get(iid, 0)) / t) * cov
        score = min(1.0, max(0.0, w["success"] * sr + w["uptime"] * ur
                             + w["threat"] * (1 - tr) + w["integrity"] * ir))
        out[iid] = {"score": score, "success_rate": sr, "uptime_rate": ur,
                    "threat_rate": tr, "integrity_rate": ir}
    return out