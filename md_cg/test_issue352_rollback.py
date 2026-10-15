# -*- coding: utf-8 -*-
# 功能名：变更单回滚不得抹掉执行之后的写入、不得越过保护位、必须留痕（issue #352-A）
# 生效条件：python -X utf8 -m md_cg.test_issue352_rollback [--mutate]；被测面=md_cg/rollback.py 的 rollback_mutation/_land + md_cg/rollback_cli.py + md_cg/mdcos.py 的执行时点后像补全
# 子功能：A 组=漂移闸（执行之后又被写 / B 第二张合并单 / D 删除后同 id 重建 / 执行后加 immutable）+ 回滚留痕 + 被覆盖版本留档 + --dry-run/--force；K 组=非恒真对照（合法回滚照常 / 命令串幂等重放 / 旧记录无 after_hash 仍放行 / 元数据改写不算漂移 / 前像本就受保护时不得拦死）；E 组=源码面单点
# 执行：confirm 档出 C/B/D 三类变更单并 accept，执行后按场景追加写入，再调统一回滚入口或执行记录里的回滚命令串（subprocess）
# 验证方式：全部 PASS 即通过；--mutate 走镜像树定点变异，变异后红项必须**恰为**预期集合
# 不适用条件：①只判「回滚是否越权/抹掉执行之后的写入」，不判前像本身是否拍对（既有 test_mutation_rollback P/Q/R/S 组覆盖）②不判加密库的密文字节可比性（既有模块 docstring 已声明口径）③不判 D 的 restore 语义本身④不改 protect.py 既有 guard_*/snapshot 行为（守卫钉死）
"""issue #352-A 守卫：回滚越权（抹掉执行之后的写入 / 越 immutable / 不留痕）。

病象（修前）：`rollback_mutation` 用**执行时点前像整体覆写**目标，不检查目标在
执行之后有没有再被写过——
  · C 改写单：执行之后别人写进去的正文全部消失；
  · B 合并单：当前正文以前像为前缀时，前缀之后的**所有**聚合行被剥掉，包括后续
    另一张合并单追加的行；剥不精确时退回整份前像正文；
  · D 删除单：删除之后同 id 新写入的内容被前像校准覆写；
  · 执行之后目标被标 immutable 时照样覆写，immutable 标记被一并清掉；
  · 被覆盖的版本不进 `_protected_history`、`_audit.jsonl` 里也没有回滚这一行。
回执是 `ok:true / bytes_equal_preimage:true`，执行回滚的人看不到任何提示。

处置（三条，缺一不可）：
  1. **漂移闸**：执行桥在执行落盘**之后**补一个盘面指纹 `after_hash`
     （`rollback.node_fingerprint`），回滚前与现盘面比对；不等即 fail-closed
     （`drifted_since_execute`）。旧记录无该键 ⇒ 退化为 decisions.jsonl 次序
     判据，**不是「无键即放行」**。**幂等重放豁免**：现盘面已等于前像时放行
     （此时覆写是空操作，抹不掉东西）。
  2. **保护闸 + 留档**：`_land` 落盘前过既有单点 `protect.is_immutable`，落盘前
     调 `protect.snapshot` 把将被覆盖的版本留进 `_protected_history`。
     判据刻意**只在「现受保护 而 前像不带同一保护位」时拒**——否则受保护节点的
     合法回滚会被一并拦死（K3/K7 是这条的对照）。
  3. **留痕**：回滚成功即向 `_audit.jsonl` 写一行 `op="rollback"`（改前这一支
     一行审计都不写）。

★**过度收紧方向**：本条的修复天然是「加拒绝」，故 K 组里 K3/K7 专门盯
「前像本就带保护位时**必须放行**」、K4 盯「旧记录不能一律拒」、K5 盯「元数据
改写不算漂移」；M7 是**过度收紧方向的定点变异**（把保护闸改成「现受保护即拒」），
它必须打红 K3/K7——证明这两条判据有判别力，不是恒真对照。
"""
import inspect
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss352a_")
_POLICY = os.path.join(_TMP, "policy.json")
with open(_POLICY, "w", encoding="utf-8") as _f:
    json.dump({"forbidden": ["FORBIDDEN_WORD"], "required": ["PASSED"]}, _f)
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot",
                   "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_POLICY_FILE": _POLICY,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from md_cg import autonomy_modes                          # noqa: E402

os.environ[autonomy_modes.AUTONOMY_ENV_KEYS["mode"]] = "confirm"

from md_cg import forgetting, protect, rollback as _rb    # noqa: E402
from md_cg import writepipe                               # noqa: E402
from md_cg.mdcos import MdCGOS                            # noqa: E402

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:400])
        FAILS.append(name)


_PLAIN = "PASSED 端口 %s"
_BODY = ("# 功能名：部署面端口约定\n"
         "# 生效条件：prod 集群；2026-09-30 起；部署清单核对\n"
         "# 子功能：登记各服务监听端口\n"
         "# 执行：核对 manifest 的 ports 段\n"
         "# 验证方式：test\n"
         "# 不适用条件：无\n"
         "\n网关监听端口 8080/HTTP；指标面监听端口 %s/HTTP\n")

_RUN = [0]


def _lib(tag):
    _RUN[0] += 1
    return MdCGOS(os.path.join(_TMP, "%s_%d" % (tag, _RUN[0])), autoflush=0)


def _pipe():
    return writepipe.install_default_pipes() if hasattr(writepipe, "install_default_pipes") \
        else writepipe.install_default_gates(writepipe.WritePipeline())


def _c_accept(cg, nid, new, old="8080"):
    """出一张 C 改写单并 accept；返回 ({"pid","mutation"}, 写链返回体)。"""
    cg.add(nid, _PLAIN % old, layer="knowledge", verification_basis="test")
    cg.flush()
    o = _pipe().execute(cg, {"content_kind": "text", "content": _PLAIN % new,
                             "layer": "knowledge", "node_id": nid})
    if o.get("moved_to") != "review_queue" or not o.get("pid"):
        return None, o
    d = cg.review_decide(o["pid"], "accept", reason="issue352 守卫")
    return {"pid": o["pid"], "mutation": d.get("mutation") or {},
            "accept": d}, o


def _audit_rows(cg):
    p = os.path.join(cg.root, "_audit.jsonl")
    if not os.path.isfile(p):
        return []
    out = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass
    return out


def _history_blobs(cg, nid):
    import glob
    d = os.path.join(cg.root, protect.HISTORY_DIR, nid)
    blobs = []
    for p in sorted(glob.glob(os.path.join(d, "*.md"))):
        with open(p, encoding="utf-8", errors="replace") as f:
            blobs.append(f.read())
    return blobs


def _run_command(cmd, extra=None):
    """执行记录里的**原命令串**（切分 → python 换本解释器 → subprocess）。"""
    argv = shlex.split(cmd, posix=False)
    argv = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] == '"' else a for a in argv]
    if not argv:
        return {"rc": -1, "json": None, "err": "empty command"}
    argv[0] = sys.executable
    if extra:
        argv = argv + list(extra)
    env = dict(os.environ)
    env["PYTHONPATH"] = _REPO
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_REPO, env=env, timeout=600)
    try:
        js = json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception:                                     # noqa: BLE001
        js = None
    return {"rc": p.returncode, "json": js, "err": (p.stderr or "")[-200:]}


# ========================================================= A 组：漂移 / 保护 / 留痕
print("== A 组：执行之后的写入不得被回滚抹掉 ==")

# --- A1：C 改写单 accept 之后目标又被直写 ---
_a1 = _lib("a1")
_a1i, _a1o = _c_accept(_a1, "a1", "8081")
_a1pre = _a1i["mutation"].get("after_hash") if _a1i else None
_a1.add("a1", _PLAIN % "9090", layer="knowledge", verification_basis="test")
_a1r = _rb.rollback_mutation(_a1, _a1i["mutation"], reason="A1", pid=_a1i["pid"])
_a1c = (_a1.get("a1") or {}).get("content") or ""
print("   [读数] A1 出单=%s after_hash=%s 回滚=%s 正文末=%r"
      % (bool(_a1i), bool(_a1pre), {k: _a1r.get(k) for k in ("ok", "error", "audited")},
         _a1c.strip()[-24:]))
_check("A1 C 改写单 accept 后第三方再写：回滚 fail-closed "
       "（drifted_since_execute）且后续写入仍在",
       _a1r.get("ok") is False
       and _a1r.get("error") == "drifted_since_execute"
       and "9090" in _a1c, _a1r)
_a1.close()

# --- A2：B 合并单 accept 之后另有一张合并单并入同一目标 ---
_a2 = _lib("a2")
_a2.add("m_t", _BODY % "8081", layer="knowledge", verification_basis="test")
_a2.flush()
_r1 = _a2.remember_gated("m_n1", _BODY % "9595", layer="knowledge")
_d1 = _a2.review_decide(_r1["pid"], "accept", reason="A2-1")
_m1 = _d1.get("mutation") or {}
_r2 = _a2.remember_gated("m_n2", _BODY % "7777", layer="knowledge")
_d2 = _a2.review_decide(_r2["pid"], "accept", reason="A2-2")
_m2 = _d2.get("mutation") or {}
_a2r = _rb.rollback_mutation(_a2, _m1, reason="A2", pid=_r1["pid"])
_a2c = (_a2.get("m_t") or {}).get("content") or ""
print("   [读数] A2 第2单 accept=%s 回滚=%s 含7777=%s 聚合行=%d"
      % (_d2.get("ok"), {k: _a2r.get(k) for k in ("ok", "error")},
         "7777" in _a2c, _a2c.count(forgetting.AGG_MARK)))
_check("A2 B 合并单回滚：第 2 张合并单的聚合行仍在（fail-closed，不整体剥掉）",
       _a2r.get("ok") is False
       and _a2r.get("error") == "drifted_since_execute"
       and "7777" in _a2c, _a2r)
_a2.close()

# --- A3：D 删除单 accept 之后同 id 被重新写入 ---
_a3 = _lib("a3")
_a3.add("d_1", _PLAIN % "初版", layer="knowledge", verification_basis="test")
_a3.flush()
_dg = _a3.forget_gated("d_1", reason="A3 删除")
_d3 = _a3.review_decide(_dg["pid"], "accept", reason="A3")
_md = _d3.get("mutation") or {}
_a3.add("d_1", _PLAIN % "重新登记版", layer="knowledge",
        verification_basis="test")
_a3r = _rb.rollback_mutation(_a3, _md, reason="A3", pid=_dg["pid"])
_a3c = (_a3.get("d_1") or {}).get("content") or ""
print("   [读数] A3 回滚=%s 正文=%r"
      % ({k: _a3r.get(k) for k in ("ok", "error")}, _a3c.strip()[-24:]))
_check("A3 D 删除单回滚：不覆写删除后同 id 的新写入（fail-closed）",
       _a3r.get("ok") is False
       and _a3r.get("error") == "drifted_since_execute"
       and "重新登记版" in _a3c, _a3r)
_a3.close()

# --- A4a：执行之后目标被标 immutable（执行记录带 after_hash）---
_a4 = _lib("a4")
_a4i, _ = _c_accept(_a4, "i_1", "8081")
_a4.add("i_1", _PLAIN % "9090", layer="knowledge", verification_basis="test",
        immutable=True, protection_reason="定稿锁定", override=True)
_a4r = _rb.rollback_mutation(_a4, _a4i["mutation"], reason="A4a", pid=_a4i["pid"])
_a4fm = (_a4.get("i_1") or {}).get("frontmatter") or {}
print("   [读数] A4a 回滚=%s immutable=%s"
      % ({k: _a4r.get(k) for k in ("ok", "error")}, _a4fm.get("immutable")))
_check("A4a 执行后被标 immutable 的目标：回滚被拒（拒绝或不清标记，二者必有其一）",
       _a4r.get("ok") is False and _a4fm.get("immutable") is True, _a4r)
_a4.close()

# --- A4b：**旧执行记录**（无 after_hash）+ 执行之后加 immutable 且正文不变 ---
# 这条只有 _land 的保护闸能拦（漂移闸拿不到后像、decisions 里也没有后续 accept）
_a5 = _lib("a5")
_a5i, _ = _c_accept(_a5, "i_2", "8081")
_cur = (_a5.get("i_2") or {}).get("content") or ""
_a5.add("i_2", _cur, layer="knowledge", verification_basis="test",
        immutable=True, protection_reason="定稿锁定", override=True)
_legacy = {k: v for k, v in _a5i["mutation"].items() if k != "after_hash"}
_a5r = _rb.rollback_mutation(_a5, _legacy, reason="A4b", pid=_a5i["pid"])
_a5fm = (_a5.get("i_2") or {}).get("frontmatter") or {}
print("   [读数] A4b 旧记录回滚=%s immutable=%s"
      % ({k: _a5r.get(k) for k in ("ok", "error", "protection")},
         _a5fm.get("immutable")))
_check("A4b 旧执行记录（无 after_hash）+ 执行后加 immutable：保护闸拦下且标记仍在",
       _a5r.get("ok") is False and _a5fm.get("immutable") is True
       and "9090" not in str(_a5r), _a5r)
_a5.close()

# --- A5：回滚在 _audit.jsonl 留痕 ---
_a6 = _lib("a6")
_a6i, _ = _c_accept(_a6, "au_1", "8081")
_a6r = _rb.rollback_mutation(_a6, _a6i["mutation"], reason="A5 留痕",
                             pid=_a6i["pid"], actor="guard")
_rows = [r for r in _audit_rows(_a6)
         if r.get("op") == "rollback" and r.get("id") == "au_1"]
print("   [读数] A5 回滚=%s 审计行=%s"
      % (_a6r.get("ok"), [(r.get("op"), r.get("pid"), r.get("method"))
                          for r in _rows]))
_check("A5 回滚在 _audit.jsonl 留痕（op=rollback 且带 pid）",
       _a6r.get("ok") is True and len(_rows) == 1
       and _rows[0].get("pid") == _a6i["pid"], (_a6r.get("audited"), _rows))
_a6.close()

# --- A6：被覆盖的版本进 _protected_history（回滚前留档）---
_a7 = _lib("a7")
_a7i, _ = _c_accept(_a7, "h_1", "8081")
_a7r = _rb.rollback_mutation(_a7, _a7i["mutation"], reason="A6 留档")
_blobs = _history_blobs(_a7, "h_1")
print("   [读数] A6 历史文件=%d 含被覆盖版本(8081)=%s"
      % (len(_blobs), any("8081" in b for b in _blobs)))
_check("A6 回滚前把**将被覆盖的版本**留档进 _protected_history（修前只留下前像）",
       _a7r.get("ok") is True and len(_blobs) >= 2
       and any("8081" in b for b in _blobs), len(_blobs))
_a7.close()

# --- A7：--dry-run 只预演不落盘 ---
_a8 = _lib("a8")
_a8i, _ = _c_accept(_a8, "dr_1", "8081")
_a8.add("dr_1", _PLAIN % "9090", layer="knowledge", verification_basis="test")
_a8d = _rb.rollback_mutation(_a8, _a8i["mutation"], reason="A7", pid=_a8i["pid"],
                             dry_run=True)
_a8c = (_a8.get("dr_1") or {}).get("content") or ""
_a8cli = _run_command(_a8i["mutation"].get("rollback") or "", ["--dry-run"])
print("   [读数] A7 dry-run=%s CLI rc=%s 正文仍含9090=%s"
      % ({k: _a8d.get(k) for k in ("ok", "error", "would_apply")},
         _a8cli["rc"], "9090" in _a8c))
_a8j = _a8cli["json"] or {}
# 注意：dry-run 遇到漂移时**照实回报「会拒绝」**（would_apply=False + 漂移原因），
# 不是「预演失败」——预演什么都没做，故 CLI 仍返回 rc=0。这正是它的用处：
# 执行回滚的人在动手前就能看见「这一单现在回滚会抹掉别的东西」。
_check("A7 dry-run 只回报差异与漂移判定、不落盘（进程内与 CLI 两路一致）",
       _a8d.get("dry_run") is True and _a8d.get("would_apply") is False
       and _a8d.get("error") == "drifted_since_execute"
       and "9090" in _a8c
       and _a8cli["rc"] == 0 and _a8j.get("dry_run") is True
       and _a8j.get("would_apply") is False
       and _a8j.get("error") == "drifted_since_execute"
       and "9090" in _a8c, (_a8d, _a8j, _a8cli["rc"]))
_a8.close()

# --- A8：--force 显式越过闸并落盘 ---
_a9 = _lib("a9")
_a9i, _ = _c_accept(_a9, "fo_1", "8081")
_a9.add("fo_1", _PLAIN % "9090", layer="knowledge", verification_basis="test")
_a9cli = _run_command(_a9i["mutation"].get("rollback") or "", ["--force"])
_a9._maybe_reload_index()
_a9c = (_a9.get("fo_1") or {}).get("content") or ""
print("   [读数] A8 --force rc=%s ok=%s 正文回前像=%s audited=%s"
      % (_a9cli["rc"], (_a9cli["json"] or {}).get("ok"), "8080" in _a9c,
         (_a9cli["json"] or {}).get("audited")))
_check("A8 --force 越过漂移闸并落盘（闸不是硬墙：显式承担后果的通道存在）",
       _a9cli["rc"] == 0 and (_a9cli["json"] or {}).get("ok") is True
       and "8080" in _a9c, _a9cli)
_a9.close()

# ========================================================= K 组：非恒真对照
print("== K 组：非恒真对照（含**过度收紧**方向）==")

# --- K1：合法回滚（执行之后没人动过）照常成功 ---
_k1 = _lib("k1")
_k1i, _ = _c_accept(_k1, "k1", "8081")
_k1r = _rb.rollback_mutation(_k1, _k1i["mutation"], reason="K1")
_k1c = (_k1.get("k1") or {}).get("content") or ""
print("   [读数] K1 回滚=%s 逐字节=%s 正文回前像=%s"
      % (_k1r.get("ok"), _k1r.get("bytes_equal_preimage"), "8080" in _k1c))
_check("K1 合法回滚（无第三方写入）照常 ok + 逐字节回前像（修复没把正常路径关掉）",
       _k1r.get("ok") is True and _k1r.get("bytes_equal_preimage") is True
       and "8080" in _k1c, _k1r)
_k1.close()

# --- K2：同一条回滚命令串二次演练（幂等重放）仍 rc=0 ---
_k2 = _lib("k2")
_k2i, _ = _c_accept(_k2, "k2", "8081")
_rb.rollback_mutation(_k2, _k2i["mutation"], reason="K2-1")
_k2cli = _run_command(_k2i["mutation"].get("rollback") or "")
print("   [读数] K2 二次演练 rc=%s ok=%s（幂等重放豁免）"
      % (_k2cli["rc"], (_k2cli["json"] or {}).get("ok")))
_check("K2 命令串二次演练（幂等重放）仍 rc=0 ok=True——现盘面已等于前像即放行",
       _k2cli["rc"] == 0 and (_k2cli["json"] or {}).get("ok") is True, _k2cli)
_k2.close()

# --- K3：（过度收紧方向）前像**本就** immutable 的节点，回滚必须放行 ---
def _hand_rollback(tag, layer, immutable):
    cg = _lib(tag)
    kw = {"layer": layer, "verification_basis": "test"}
    if immutable:
        kw.update(immutable=True, protection_reason="定稿锁定")
    cg.add(tag, _PLAIN % "8080", **kw)
    cg.flush()
    rel = protect.snapshot_preimage(cg, tag, action="C", pid="p_" + tag)
    cg.add(tag, _PLAIN % "8081", override=True, **kw)
    m = {"action": "C", "target": tag, "before": rel,
         "impact": _rb.collect_impact(cg, tag),
         "after_hash": _rb.node_fingerprint(cg.get(tag)), "rollback": ""}
    r = _rb.rollback_mutation(cg, m, reason="K3/K7", pid="p_" + tag)
    c = (cg.get(tag) or {}).get("content") or ""
    cg.close()
    return r, c


_k3r, _k3c = _hand_rollback("k3", "knowledge", True)
print("   [读数] K3 前像本就 immutable：回滚=%s 正文回前像=%s"
      % ({k: _k3r.get(k) for k in ("ok", "error")}, "8080" in _k3c))
_check("K3 前像本就带 immutable：回滚**必须放行**（保护闸只拦「执行之后才加的」）",
       _k3r.get("ok") is True and "8080" in _k3c, _k3r)

# --- K4：旧执行记录（无 after_hash）且无后续执行 → 仍放行（向后兼容）---
_k4 = _lib("k4")
_k4i, _ = _c_accept(_k4, "k4", "8081")
_k4legacy = {k: v for k, v in _k4i["mutation"].items() if k != "after_hash"}
_k4r = _rb.rollback_mutation(_k4, _k4legacy, reason="K4", pid=_k4i["pid"])
_k4c = (_k4.get("k4") or {}).get("content") or ""
print("   [读数] K4 旧记录回滚=%s 正文回前像=%s"
      % ({k: _k4r.get(k) for k in ("ok", "error")}, "8080" in _k4c))
_check("K4 旧执行记录（无 after_hash）+ 无后续执行：仍放行（不把老库存量单一律拒掉）",
       _k4r.get("ok") is True and "8080" in _k4c, _k4r)
_k4.close()

# --- K5：执行之后只改元数据（正文不变）不算漂移 ---
_k5 = _lib("k5")
_k5i, _ = _c_accept(_k5, "k5", "8081")
_k5c0 = (_k5.get("k5") or {}).get("content") or ""
_k5.add("k5", _k5c0, layer="knowledge", verification_basis="test",
        tags=["后加标签"])
_k5r = _rb.rollback_mutation(_k5, _k5i["mutation"], reason="K5", pid=_k5i["pid"])
_k5c = (_k5.get("k5") or {}).get("content") or ""
print("   [读数] K5 元数据改写后回滚=%s 正文回前像=%s"
      % ({k: _k5r.get(k) for k in ("ok", "error")}, "8080" in _k5c))
_check("K5 执行之后只加 tags（正文不变）不算漂移：回滚仍放行（指纹不取每次落盘都变的键）",
       _k5r.get("ok") is True and "8080" in _k5c, _k5r)
_k5.close()

# --- K6：dry-run 在**无漂移**场景也不落盘 ---
_k6 = _lib("k6")
_k6i, _ = _c_accept(_k6, "k6", "8081")
_k6d = _rb.rollback_mutation(_k6, _k6i["mutation"], reason="K6", dry_run=True)
_k6c = (_k6.get("k6") or {}).get("content") or ""
print("   [读数] K6 dry-run(无漂移)=%s 正文未动=%s"
      % ({k: _k6d.get(k) for k in ("ok", "dry_run", "would_apply")},
         "8081" in _k6c))
_check("K6 dry-run 在无漂移场景同样只预演：would_apply=True 且正文未动",
       _k6d.get("ok") is True and _k6d.get("would_apply") is True
       and "8081" in _k6c, _k6d)
_k6.close()

# --- K7：（过度收紧方向）前像就在保护层（self）的节点，回滚必须放行 ---
_k7r, _k7c = _hand_rollback("k7", "self", False)
print("   [读数] K7 前像本在 self 层：回滚=%s 正文回前像=%s"
      % ({k: _k7r.get(k) for k in ("ok", "error")}, "8080" in _k7c))
_check("K7 前像本就在保护层（self）：回滚**必须放行**（层保护不构成对合法回滚的硬墙）",
       _k7r.get("ok") is True and "8080" in _k7c, _k7r)

# ========================================================= E 组：源码面单点
print("== E 组：源码面单点 ==")
_src_rb = inspect.getsource(_rb.rollback_mutation)
_src_land = inspect.getsource(_rb._land)
_src_me = inspect.getsource(autonomy_modes.mutation_executed)
_cli = os.path.join(_REPO, "md_cg", "rollback_cli.py")
_cli_src = open(_cli, encoding="utf-8").read()
_check("E1 漂移闸在统一入口内（drifted_since_execute + after_hash 比对）",
       "drifted_since_execute" in _src_rb and 'mutation.get("after_hash")' in _src_rb
       and "preimage_fingerprint" in _src_rb)
_check("E2 _land 接既有保护单点与留档单点（protect.is_immutable / protect.snapshot）",
       "protect.is_immutable(" in _src_land and "protect.snapshot(" in _src_land)
_check("E3 mutation_executed 增加 after_hash 形参且仅在非 None 时补键",
       "after_hash=None" in _src_me and 'if after_hash is not None:' in _src_me
       and 'out["after_hash"] = after_hash' in _src_me)
_check("E4 CLI 暴露 --dry-run / --force 且转交统一入口",
       '"--dry-run"' in _cli_src and '"--force"' in _cli_src
       and "force=args.force" in _cli_src and "dry_run=args.dry_run" in _cli_src)
_mdcos_src = open(os.path.join(_REPO, "md_cg", "mdcos.py"),
                  encoding="utf-8").read()
_check("E5 执行桥用**同一个**指纹单点补后像（rollback.node_fingerprint）",
       "_rb.node_fingerprint(" in _mdcos_src
       and "after_hash=_after_hash" in _mdcos_src)

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #352-A 结果：%d 失败 → %s" % (len(FAILS), ", ".join(FAILS)))
else:
    print("issue #352-A 结果：全部通过")

# ------------------------------------------------------------- 定点变异（镜像树）
_MUTATIONS = (
    # (描述, ((文件, 旧锚点行组, 新锚点行组), ...), 预期红项集合)
    ("M1 摘掉漂移闸（回到「执行时点前像整体覆写」的修前形态）",
     (("md_cg/rollback.py",
       ["    if cur_fp != pre_fp and not force:     # 相等＝幂等重放，放行（见 docstring）"],
       ["    if False:"]),),
     # A4a 不在预期集里：执行之后加的 immutable 会**同时**被漂移闸与 _land 的
     # 保护闸命中，摘掉漂移闸后仍被第二道拦下（M2 单独证明第二道的判别力）。
     ("A1", "A2", "A3", "A7")),
    ("M2 摘掉 _land 的保护闸（executed 之后加的 immutable 被一并清掉）",
     (("md_cg/rollback.py",
       ["    if prot and not force:"],
       ["    if False:"]),),
     ("A4b",)),
    ("M3 摘掉回滚留痕（_audit.jsonl 不再有 op=rollback）",
     (("md_cg/rollback.py",
       ['    out["audited"] = _audit_rollback(cg, tgt, act, rel, out, actor=actor,',
        '                                     pid=pid, reason=reason)'],
       ['    out["audited"] = False']),),
     ("A5",)),
    ("M4 摘掉落盘前的被覆盖版本留档（protect.snapshot）",
     (("md_cg/rollback.py",
       ["        protect.snapshot(cg, node_id)"],
       ["        pass"]),),
     ("A6", "E2")),
    ("M5 摘掉 CLI 的 --force 接线（显式承担后果的通道消失）",
     (("md_cg/rollback_cli.py",
       ["                                    force=args.force, dry_run=args.dry_run)"],
       ["                                    force=False, dry_run=args.dry_run)"]),),
     ("A8", "E4")),
    ("M6 摘掉执行桥的后像补全（回滚只剩 decisions 次序判据，直写类漂移看不见）",
     (("md_cg/mdcos.py",
       ["            after_hash=_after_hash)"],
       ["            after_hash=None)"]),),
     # A7 也在集里：dry-run 场景的漂移同样靠 after_hash 才看得见（直写不经 accept，
     # decisions 次序判据拿不到证据）。
     ("A1", "A3", "A7", "E5")),
    ("M7 **过度收紧方向**：保护闸改成「现盘面受保护即拒」（不看前像是否本就带保护位）",
     (("md_cg/rollback.py",
       ["        if not _pre_prot:"],
       ["        if True:"]),),
     ("K3", "K7")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss352a_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _nl_of(path):
    with open(path, "rb") as fh:
        raw = fh.read(8192)
    return "\r\n" if b"\r\n" in raw else "\n"


def _anchor(parts, nl):
    return nl.join(parts)


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue352_rollback"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=3600)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把修复点改回改动前形态 / 摘掉接线，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-30:]))
        for ln in out.splitlines():
            if "[读数]" in ln:
                print("  修后读数（未变异镜像）：" + ln.strip())
        okc, bad = 0, []
        for desc, edits, exp in _MUTATIONS:
            backups, miss = [], []
            for rel, oldp, newp in edits:
                p = os.path.join(tree, rel)
                nl = _nl_of(p)
                old, new = _anchor(oldp, nl), _anchor(newp, nl)
                with open(p, encoding="utf-8", newline="") as fh:
                    t = fh.read()
                if t.count(old) != 1:
                    miss.append("%s —— 锚点命中 %d 次" % (rel, t.count(old)))
                    continue
                backups.append((p, t))
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(t.replace(old, new, 1))
            if miss:
                bad.append("%s —— %s" % (desc, "；".join(miss)))
                print("  ANCHOR-MISS " + desc)
                for p, t in backups:
                    with open(p, "w", encoding="utf-8", newline="") as fh:
                        fh.write(t)
                continue
            rc2, reds2, out2 = _run_in(tree)
            for p, t in backups:
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(t)
            hit = sorted({e for r in reds2 for e in exp if r.startswith(e + " ")})
            if rc2 != 0 and hit == sorted(exp) and len(reds2) == len(exp):
                okc += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:14]:
                    print("        FAIL " + r)
            for ln in out2.splitlines():
                if "[读数]" in ln and "基线" not in ln:
                    pass
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
        return 1 if FAILS else 0
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
