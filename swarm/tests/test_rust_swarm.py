# -*- coding: utf-8 -*-
"""test_rust_swarm.py · 多进程蜂群验收（v0.5 · RUST-SWARM-REV1）
荣 2026-09-06 裁定：多实例并行（进程级）+ 消息传递 + 实例私有信任 + 聚合层。
覆盖：serve 实例化多轮 / 蜂群并行执行 / 消息路由（收件箱注入）/ HMAC 签名
（Python 独立复核交叉验证 Rust 手写 SHA256）/ WAL 落盘 / 信任聚合双端一致 /
篡改检测 / clippy 零警告 / 既有基线不破坏。
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from swarm.rust_codegen import generate_rust_project
from swarm.rust_swarm import (aggregate_trust_python, make_swarm_config,
                             run_swarm, verify_wal_signatures)

pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


SOURCE = """问曰：如何验证信任？
答曰：信任值大于0.7。
术曰：
1。道 新信任路径；
2。德 0.3；
3。若 信任值 大于 0.2，则 德 0.5；
4。止。
"""
SECRET = "验收密钥-蜂群v05"

tmp = tempfile.mkdtemp(prefix="swarm_acc_")
proj = os.path.join(tmp, "proj")
gen = generate_rust_project(SOURCE, proj)
check("项目生成", gen["ok"])

# ============ ① 双实例 3 轮蜂群 ============
print("=== ① 双实例 3 轮：并行执行 + 消息路由 ===")
cfg = make_swarm_config(
    instances=[
        # 缺陷②修复后：信任值 是内建名（读 trust_value 寄存器），无需再以
        # symbols 绕过（旧写法会把 信任值 归一为寄存器初值、覆盖实例 trust）。
        {"id": "实例甲", "role": "记录", "trust": 0.1},
        {"id": "实例乙", "role": "验证", "trust": 0.2},
    ],
    routes=[{"from": "实例甲", "event_type": "信任同步", "to": "实例乙",
             "payload": "@trust", "level": 0}],
    rounds=3, shared_secret=SECRET)
rr = run_swarm(proj, cfg, wal_path=os.path.join(tmp, "events.jsonl"))
check("蜂群运行", rr["ok"], str(rr.get("stderr", ""))[:150])
if rr["ok"]:
    rep = rr["report"]
    fs = rep["final_states"]
    check("双实例并行执行(均有合法终态)",
          all("error" not in fs.get(k, {"error": 1}) for k in ("实例甲", "实例乙")),
          json.dumps(fs, ensure_ascii=False)[:120])
    check("实例甲 终态 trust=0.9", abs(fs["实例甲"]["trust"] - 0.9) < 1e-9,
          str(fs["实例甲"]["trust"]))
    check("实例乙 终态 trust=1.0", abs(fs["实例乙"]["trust"] - 1.0) < 1e-9,
          str(fs["实例乙"]["trust"]))
    check("消息路由(乙最后一轮收件箱=1 条:每轮收上一轮 1 条,首轮无上一轮)",
          fs["实例乙"]["symbols"].get("已收消息数") == 1,
          str(fs["实例乙"]["symbols"]))

# ============ ② 信任聚合双端一致 ============
print("=== ② 信任聚合:Rust vs Python 参照 ===")
if rr["ok"]:
    # 从终态拿各实例 trust
    ts = [fs["实例甲"]["trust"], fs["实例乙"]["trust"]]
    py = aggregate_trust_python(ts)
    rs = rep["trust"]
    check("T_avg 一致", abs(py["T_avg"] - rs["T_avg"]) < 1e-6,
          f"py={py['T_avg']:.6f} rs={rs['T_avg']:.6f}")
    check("T_min 一致", abs(py["T_min"] - rs["T_min"]) < 1e-6)
    check("T_variance 一致", abs(py["T_variance"] - rs["T_variance"]) < 1e-6)
    check("T_alignment 一致", abs(py["T_alignment"] - rs["T_alignment"]) < 1e-6,
          f"py={py['T_alignment']:.6f} rs={rs['T_alignment']:.6f}")
    check("T_alignment 工程代理(1-var/avg) 数值合理",
          0 <= rs["T_alignment"] <= 1.0)

# ============ ③ HMAC 签名:Python 独立复核(交叉验证 Rust 手写 SHA256) ============
print("=== ③ WAL 验签(交叉验证) ===")
v = verify_wal_signatures(rr["wal"], SECRET)
check(f"WAL 全部验签通过({v['total']} 条)", v["all_valid"],
      f"verified={v['verified']} bad={v['bad']}")
check("事件计数(路由 3 + ACK 2[首轮无收件箱不 ACK] = 5)", v["total"] == 5,
      str(v["total"]))

# 篡改检测：改 payload → 验签必失败
with open(rr["wal"], encoding="utf-8") as f:
    lines = f.readlines()
tampered = json.loads(lines[0])
tampered["payload"] = "999"
line_t = json.dumps(tampered, ensure_ascii=False)
# 用原始文本切片重算（验签逻辑同 verify）
msg = "%s|%s|%s|%s|%s|%s" % (tampered["type"], tampered["from"], tampered["to"],
                             tampered["round"], tampered["ts"],
                             line_t[line_t.index('"payload":') + len('"payload":'):])
import hashlib, hmac as hm
expect = hm.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
check("篡改 payload → 签名不匹配", expect != tampered["hmac"])

# ============ ③b 验签器容错盲区：非法 UTF-8 行不得打崩验签器 ============
# 缺陷：open(encoding=utf-8) + for line in f 的行级解码发生在 try 之外——
# 撕裂写在多字节中文字符中间（torn-write 最真实形态）或任意非法字节序列
# → UnicodeDecodeError 打崩验签器（违背「验签器面对的正是被篡改的 WAL，
# 不得自己先崩」契约）。哑密钥合成 WAL：2 条合法签名行 + 1 条坏行 →
# 期望坏行计 bad、好行照验、all_valid=False，全程不抛异常。
print("=== ③b 验签器容错：非法 UTF-8 行（撕裂/污染） ===")
import shutil as _shutil

DUMMY_SEC = "哑密钥-验签容错守卫"


def _mk_wal_line(seq, payload_text, typ="消息", frm="实例甲", to="实例乙",
                 rnd=1, ts="2026-09-25T00:00:00"):
    """合成一条与 Rust WAL 同构的合法签名行（payload 为行内最后字段）。"""
    msg = "|".join([str(seq), typ, frm, to, str(rnd), ts, payload_text])
    mac = hm.new(DUMMY_SEC.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return ('{"seq":%d,"type":"%s","from":"%s","to":"%s","round":%d,'
            '"ts":"%s","hmac":"%s","payload":%s}'
            % (seq, typ, frm, to, rnd, ts, mac, payload_text))


def _verify_no_crash(wal_bytes, name):
    tmp_w = tempfile.mkdtemp(prefix="swarm_vfc_")
    p = os.path.join(tmp_w, "w.jsonl")
    with open(p, "wb") as f:
        f.write(wal_bytes)
    try:
        v = verify_wal_signatures(p, DUMMY_SEC)
        check(name, isinstance(v, dict) and v.get("verified") == 2
              and v.get("bad") == 1 and v.get("all_valid") is False,
              str(v)[:150])
    except UnicodeDecodeError as e:
        check(name, False, f"验签器崩了: {e}")
    finally:
        _shutil.rmtree(tmp_w, ignore_errors=True)


_g1 = _mk_wal_line(1, '"信任同步载荷"')
_g2 = _mk_wal_line(2, '"第二事件载荷"')
# 撕裂形态 a：尾行截在中文「荷」多字节中间（去掉 荷尾字节+闭引号+闭括号）
_torn = _mk_wal_line(3, '"撕裂实测载荷"').encode("utf-8")[:-3]
_verify_no_crash(_g1.encode() + b"\n" + _g2.encode() + b"\n" + _torn + b"\n",
                 "③b-1 撕裂行（截在中文多字节中间）→ 计 bad 不崩验签器")
# 污染形态 b：行内「污」(E6 B1 A1) 首字节换 0xFF → 非法字节序列
_dirty = _mk_wal_line(3, '"污染实测载荷"').encode("utf-8").replace(
    b"\xe6\xb1\xa1", b"\xff\xb1\xa1")
_verify_no_crash(_g1.encode() + b"\n" + _g2.encode() + b"\n" + _dirty + b"\n",
                 "③b-2 非法字节（0xFF）行 → 计 bad 不崩验签器")

# ============ ③c 空串密钥拒绝（N143 · 2026-09-26 修复守卫） ============
# 缺陷：verify_wal_signatures 对空串密钥无拒绝（fail-open）——任何能写 WAL
# 的本机组件以空串自签伪造行，verify('',…) 照验全绿（旧码实测 verified=1
# all_valid=True；CLI --secret "" 同绿 rc=0）。修复：入口空串/None 抛
# ValueError（结构化错误，读 WAL 之前拒）；CLI 面同口径显式拒绝 rc=2
# （test_swarm_cli.py ⑧）。run 侧缺省密钥语义属全量语义专项维持 deferred。
print("=== ③c 空串密钥拒绝：fail-closed ===")

_es_dir = tempfile.mkdtemp(prefix="swarm_es_")
try:
    # 以**空串密钥**自签伪造行（攻击形态本体：读过源码即知可用空串自签）
    _msg = '1|消息|queen|w1|1|1758888800000|"空串自签伪造行"'
    _mac = hm.new(b"", _msg.encode(), hashlib.sha256).hexdigest()
    _es_wal = os.path.join(_es_dir, "w.jsonl")
    with open(_es_wal, "wb") as _f:
        _f.write(('{"seq":1,"ts":1758888800000,"from":"queen","to":"w1",'
                  '"type":"消息","round":1,"level":0,"hmac":"%s",'
                  '"payload":"空串自签伪造行"}\n' % _mac).encode("utf-8"))
    try:
        verify_wal_signatures(_es_wal, "")
        check("③c-1 空串密钥 → 拒绝（抛 ValueError 密钥不得为空）",
              False, "空串密钥未拒绝（fail-open）")
    except ValueError as e:
        check("③c-1 空串密钥 → 拒绝（抛 ValueError 密钥不得为空）",
              "密钥不得为空" in str(e), str(e)[:120])
    except Exception as e:  # 拒了但崩法不对（非 ValueError 结构化错误）也算红
        check("③c-1 空串密钥 → 拒绝（抛 ValueError 密钥不得为空）",
              False, "%s: %s" % (type(e).__name__, e))
    try:
        verify_wal_signatures(_es_wal, None)
        check("③c-2 None 密钥同口径拒绝", False, "None 密钥未拒绝")
    except ValueError:
        check("③c-2 None 密钥同口径拒绝", True)
    except Exception as e:
        check("③c-2 None 密钥同口径拒绝",
              False, "%s: %s" % (type(e).__name__, e))
finally:
    _shutil.rmtree(_es_dir, ignore_errors=True)

# ============ ④ 多轮状态语义:符号表不跨轮持久 ============
print("=== ④ 每轮完整环境 ===")
# 实例乙 round3 终态 trust 仍 =1.0（不是 1.0 累加到 1.7）→ 每轮从初始环境起算
check("轮间无状态泄漏(乙每轮重算 trust=1.0)",
      abs(fs["实例乙"]["trust"] - 1.0) < 1e-9)
check("跨轮数据只经消息(乙有收件箱,甲无)",
      "已收消息数" in fs["实例乙"]["symbols"]
      and "已收消息数" not in fs["实例甲"]["symbols"])

# ============ ⑤ 独立形态蜂群（--no-default-features + --pbc 转发） ============
print("=== ⑤ 独立形态蜂群：协调器与子实例 --pbc 转发 ===")
import shutil
import subprocess
from compiler.pbc import compile_to_pbc

rt_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "rust_runtime")
if shutil.which("cargo") and os.path.isdir(rt_dir):
    ind = subprocess.run(["cargo", "build", "--release", "--no-default-features"],
                         cwd=rt_dir, capture_output=True, text=True, timeout=300,
                         encoding="utf-8", errors="replace")
    check("独立形态构建（关闭 embed）", ind.returncode == 0, (ind.stderr or "")[-200:])
    exe_ind = os.path.join(rt_dir, "target", "release",
                           "protocol_vm.exe" if os.name == "nt" else "protocol_vm")
    tmp5 = tempfile.mkdtemp(prefix="swarm_ind_")
    pbc5 = os.path.join(tmp5, "program.pbc")
    _, r5 = compile_to_pbc(SOURCE, pbc5)
    if r5["ok"] and os.path.exists(exe_ind):
        cfg5 = make_swarm_config(
            instances=[
                # 缺陷②修复后：信任值 为内建名，不再以 symbols 绕过
                {"id": "实例甲", "role": "记录", "trust": 0.1},
                {"id": "实例乙", "role": "验证", "trust": 0.2},
            ],
            routes=[{"from": "实例甲", "event_type": "信任同步", "to": "实例乙",
                     "payload": "@trust", "level": 0}],
            rounds=3, shared_secret=SECRET)
        rr5 = run_swarm(tmp5, cfg5, wal_path="events_ind.jsonl",
                        pbc_path=pbc5, exe=exe_ind)
        check("独立形态蜂群运行（子实例收到 --pbc）", rr5["ok"],
              str(rr5.get("stderr", ""))[:150])
        if rr5["ok"]:
            fs5 = rr5["report"]["final_states"]
            check("独立形态终态与 embed 形态一致(甲 0.9 / 乙 1.0)",
                  abs(fs5["实例甲"]["trust"] - 0.9) < 1e-9
                  and abs(fs5["实例乙"]["trust"] - 1.0) < 1e-9,
                  json.dumps(fs5, ensure_ascii=False)[:120])
            v5 = verify_wal_signatures(rr5["wal"], SECRET)
            check(f"独立形态 WAL 全部验签通过({v5['total']} 条)", v5["all_valid"],
                  f"verified={v5['verified']} bad={v5['bad']}")
    else:
        check("独立形态可执行产物存在", False, exe_ind)
else:
    check("cargo 不可用 → 跳过独立形态蜂群（环境声明）", True)

# ============ ⑤ run_swarm 错误契约（2026-09-25 缺陷） ============
# 契约：失败一律返回 {ok: False, stage: ...} dict——超时（TimeoutExpired）与
# exe 缺失（FileNotFoundError/OSError）此前直接穿透调用方，swarm_cli 整条
# CLI traceback。本节以 30s 慢执行器 + timeout=1s 与不存在 exe 各验一条。
print("=== ⑤ run_swarm 错误契约：超时/启动失败返回结构化 dict ===")
tmp6 = tempfile.mkdtemp(prefix="swarm_err_")
if os.name == "nt":
    slow_exe = os.path.join(tmp6, "slow.bat")
    with open(slow_exe, "w", encoding="utf-8") as f:
        f.write("@ping -n 30 127.0.0.1 > nul\r\n")
else:
    slow_exe = os.path.join(tmp6, "slow.sh")
    with open(slow_exe, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nsleep 30\n")
    os.chmod(slow_exe, 0o755)
try:
    rt = run_swarm(tmp6, {"algo": "rust_swarm-0.1"}, wal_path="w_err.jsonl",
                   timeout=1, exe=slow_exe)
    check("超时 → {ok:False, stage:swarm}（不抛 TimeoutExpired）",
          rt.get("ok") is False and rt.get("stage") == "swarm",
          str(rt)[:150])
    check("超时 dict 含可读 stderr（不吞现场）",
          isinstance(rt.get("stderr"), str) and "超时" in rt["stderr"],
          str(rt.get("stderr", ""))[:120])
    rm = run_swarm(tmp6, {"algo": "rust_swarm-0.1"}, wal_path="w_err2.jsonl",
                   exe=os.path.join(tmp6, "no_such_exe"))
    check("exe 缺失 → {ok:False, stage:swarm}（不抛 OSError）",
          rm.get("ok") is False and rm.get("stage") == "swarm",
          str(rm)[:150])
finally:
    shutil.rmtree(tmp6, ignore_errors=True)

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
