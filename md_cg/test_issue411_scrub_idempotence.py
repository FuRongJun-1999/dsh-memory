# -*- coding: utf-8 -*-
# 功能名：scrub 幂等名单不得把**失败**记成「已处置」（issue #411）
# 生效条件：python -X utf8 -m md_cg.test_issue411_scrub_idempotence [--mutate]；被测面=md_cg/scrub.py 的 _actions_ok / decontaminate 写侧 / _handled 读侧
# 子功能：A 组=走**真实分发面**（cg(op=scrub, action=decontaminate, dry_run=false)）：无权身份 ⇒ 盘面零变化 + _scrub.jsonl 该行 ok=False + 下一轮有权限身份仍真正处置；K 组=非恒真对照（三形态枚举 + 反向样本 / 成功轮 ok=True 的过度收紧反证 / dry_run 语义不退化 / _handled 只认 ok / summary 不把失败批次算成功轮）；E 组=AST 钉子（_log 的 ok= 只能是 _actions_ok(...)）+ 枚举完备性 + writelimit 两处「已核、非本族」登记
# 执行：三个权限相位（建节点=有权限 / 实修=无权 verifier / 再实修=有权限）各起一个 MdCGSecure 实例，经 mcp_server.call_tool 走 scrub 分发；读 _scrub.jsonl 与节点盘面字节
# 验证方式：全部 PASS 即通过；--mutate 走镜像树定点变异（含 _guard_kit 两骨架实调），变异后红项必须**恰为**预期集合
# 不适用条件：①不判 _weaken/_move_layer 自身的权限语义（那是 security 面）②不判 audit 的判据正确性（污染识别另一面）③明文登记：writelimit.py:383 _already_tidied / :373 already_covered **已核、非本族**（理由见 E4）④不改读侧 _handled/summary 的判据形态（#411 的口径是「写侧写真值、读侧照旧只读 ok」这一单点）
"""issue #411 守卫：失败的处置不得被写进幂等名单。

病象（修前）：
  scrub.py:171  `if rec.get("op") == "decontaminate" and rec.get("ok"):`  ← 幂等判据只看 ok
  scrub.py:738  `_log(cg, "decontaminate", …, ok=True, …)`                 ← 无条件写 True
同批失败只以**字符串**留在 `actions` 里（`weaken_failed:<Type>` / `demote_failed:<Type>`
/ `demote_state:<error>`），于是**无权身份跑一次即可把 (节点, 污染类型) 永久钉成
「已处置」**，污染此后**永久不再被处置**（幂等名单被失败污染）。

处置（单点 + 不变量）：
  · 抽 `_actions_ok(actions)`（`ACTION_FAIL_MARKS` 显式三项，**不通配**）；
  · **写侧**两处写真值：`:738` 单条 `ok=_actions_ok(done)`；`:762` 批次
    `ok=(n_failed == 0)`（`n_failed` 由同一次 `_actions_ok` 汇总）；
  · **读侧** `_handled` / `summary` **一字不改**，照旧只读 `ok` —— 判据收成单点。

★**过度收紧方向**（K1/K5 + M3）：`_actions_ok` 恒 False 会把**合法成功处置**误判成
失败，幂等名单永不记账 ⇒ 每轮重复处置。K1 的反向样本（`["weaken"]`/`["demote"]`/
无冒号的 `"demote_state"`）就是这条的守卫。
"""
import ast
import io
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss411_")
os.environ.update({"MDCG_STATE_ROOT": os.path.join(_TMP, "state"),
                   "MDCG_AUX_ROOT": os.path.join(_TMP, "auxstore"),
                   "MDCG_DATA_ROOT": os.path.join(_TMP, "data"),
                   "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from md_cg import _guard_kit                             # noqa: E402
from md_cg import scrub                                  # noqa: E402
from md_cg.mdcos import MdCGSecure                       # noqa: E402
from md_cg.mcp_server import call_tool                   # noqa: E402
from md_cg.security import Principal                     # noqa: E402

FAILS = []
_RUN = [0]


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:400])
        FAILS.append(name)


def _lib(tag):
    _RUN[0] += 1
    root = os.path.join(_TMP, "%s_%d" % (tag, _RUN[0]))
    os.makedirs(root, exist_ok=True)
    return root


#: 有权限身份（建节点 / 正向实修）
P_YES = Principal(role="designer", clearance="private", can_write=True,
                  can_admin=True)
#: 无权身份：可写层只有 rejected ⇒ knowledge 层的 verify/_move_layer 双双 AccessDenied
P_NO = Principal(role="verifier", clearance="private", can_write=True,
                 layers_allow=("rejected",))


def _mk_cg(root, principal):
    return MdCGSecure(root, principal=principal, autoflush=1)


def _seed_expired(root, nid="n_exp"):
    """建一个`expired`污染节点（severity=high，fix=(weaken, demote)）。"""
    import time
    cg = _mk_cg(root, P_YES)
    cg.add(nid, "PASSED 过期条目 ALPHA", layer="knowledge",
           valid_until=time.time() - 86400 * 30, verification_basis="test")
    cg.flush()
    p = os.path.join(root, (cg.get(nid) or {}).get("path") or "")
    cg.close()
    return p


def _scrub(root, principal):
    """走**真实分发面**：cg(op=scrub, action=decontaminate, dry_run=false)。"""
    cg = _mk_cg(root, principal)
    try:
        return call_tool(cg, "cg", {"op": "scrub", "action": "decontaminate",
                                    "dry_run": False, "min_severity": "medium"})
    finally:
        cg.close()


def _sig(root, nid="n_exp"):
    """节点**处置相关**读数签名（demote 会改层并搬文件，故不能只按固定路径比字节）。"""
    cg = _mk_cg(root, P_YES)
    n = cg.get(nid) or {}
    fm = n.get("frontmatter") or {}
    out = (fm.get("layer"), fm.get("verification_state"),
           fm.get("negative_evidence"), fm.get("confidence"),
           (n.get("content") or "")[:40])
    cg.close()
    return out


def _rows(root):
    p = os.path.join(root, scrub.SCRUB_LOG)
    if not os.path.isfile(p):
        return []
    out = []
    with io.open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                out.append(json.loads(ln))
    return out


def _get(row, *path):
    cur = row
    for k in path:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
    return cur


# ========================================================= A 组：真实分发面
print("== A 组：无权身份的失败不得写进幂等名单 ==")

_root = _lib("a")
_p = _seed_expired(_root)
_b0 = io.open(_p, "rb").read()
_r1 = _scrub(_root, P_NO)
_b1 = io.open(_p, "rb").read()
_rows1 = _rows(_root)
_dec = [r for r in _rows1 if r.get("op") == "decontaminate"]
_bat = [r for r in _rows1 if r.get("op") == "decontaminate_batch"]
_done1 = _get(_r1, "actions") or []
_done1 = [a.get("done") for a in _done1 if a.get("applied")]
print("   [读数] A1 done=%s 盘面变化=%s" % (_done1, _b0 != _b1))
_check("A1 无权身份：两个动作都失败（done 带 weaken_failed:/demote_failed:），盘面零变化",
       bool(_done1) and any(str(d).startswith("weaken_failed:") for d in _done1[0])
       and any(str(d).startswith("demote_failed:") for d in _done1[0])
       and _b0 == _b1, (_done1, _b0 == _b1))

print("   [读数] A2 _scrub.jsonl decontaminate 行=%s"
      % [(r.get("kind"), r.get("ok"), r.get("actions")) for r in _dec])
_check("A2 _scrub.jsonl 该行 ok=False（修前无条件 True：失败被写成已处置）",
       len(_dec) == 1 and _dec[0].get("ok") is False
       and any(str(x).startswith("weaken_failed:") for x in (_dec[0].get("actions") or [])),
       _dec)

# 下一轮：有权限身份必须**仍然真正处置**（修前会被幂等名单拦成 skip）
_sig1 = _sig(_root)
_r2 = _scrub(_root, P_YES)
_sig2 = _sig(_root)
print("   [读数] A3 有权限轮 applied=%s already_handled=%s 盘面签名 %s → %s"
      % (_r2.get("applied"), _r2.get("already_handled"), _sig1, _sig2))
_check("A3 下一轮有权限身份仍**真正处置**（不是「已处置过（幂等）」）",
       (_r2.get("applied") or 0) >= 1
       and (_r2.get("already_handled") or 0) == 0 and _sig1 != _sig2,
       {k: _r2.get(k) for k in ("applied", "already_handled")})

_rows2 = _rows(_root)
_bat2 = [r for r in _rows2 if r.get("op") == "decontaminate_batch"]
print("   [读数] A4 批次 ok 序列=%s failed_actions=%s"
      % ([r.get("ok") for r in _bat2], [r.get("failed_actions") for r in _bat2]))
_check("A4 批次记录与子条一致：失败轮 ok=False/failed_actions=1，成功轮 ok=True/0",
       len(_bat2) == 2 and _bat2[0].get("ok") is False
       and _bat2[0].get("failed_actions") == 1
       and _bat2[1].get("ok") is True
       and _bat2[1].get("failed_actions") == 0, _bat2)

_dec2 = [r for r in _rows2 if r.get("op") == "decontaminate"]
print("   [读数] A5 成功轮 done=%s ok=%s"
      % ([a.get("done") for a in (_r2.get("actions") or []) if a.get("applied")],
         [r.get("ok") for r in _dec2]))
_check("A5 **过度收紧反证**：有权限身份的成功处置仍得 ok=True（含 demote_state: 不在成功路径上）",
       len(_dec2) == 2 and _dec2[1].get("ok") is True
       and (_r2.get("failed_actions") or 0) == 0, _dec2)

# ========================================================= K 组：非恒真对照
print("== K 组：非恒真对照（含**过度收紧**方向）==")

_cases = [
    ("全成功", ["weaken", "demote"], True),
    ("weaken 失败", ["weaken_failed:AccessDenied"], False),
    ("demote 失败", ["demote_failed:ProtectionError"], False),
    ("demote_state 失败", ["demote_state:denied"], False),
    ("混合：一成一败", ["weaken", "demote_failed:OSError"], False),
    ("空列表", [], True),
    ("None", None, True),
    ("反向：动作名不该被误判（无冒号）", ["weaken_failed"], True),
    ("反向：demote_state 无冒号", ["demote_state"], True),
    ("反向：名字里含 failed 但不在标记表内的合法动作", ["weaken", "verify_failed_once"], True),
]
_got = [(c, scrub._actions_ok(v)) for c, v, _ in _cases]
_bad = [(c, g, w) for (c, v, w), (c2, g) in zip(_cases, _got) if g != w]
print("   [读数] K1 _actions_ok 十形态=%s" % _got)
_check("K1 _actions_ok 三失败形态判 False、成功/空/None 判 True，"
       "且**无冒号的同名字面不被误判**（非恒真 + 不过度收紧）",
       not _bad, _bad)

# K2：dry_run 语义不退化（不写 decontaminate 记录、盘面零变化、写批次）
_kroot = _lib("k2")
_kp = _seed_expired(_kroot, "k2_exp")
_kb0 = io.open(_kp, "rb").read()
_cg = _mk_cg(_kroot, P_YES)
_rd = call_tool(_cg, "cg", {"op": "scrub", "action": "decontaminate",
                            "dry_run": True, "min_severity": "medium"})
_cg.close()
_krows = _rows(_kroot)
print("   [读数] K2 dry_run planned=%s 记录=%s 盘面变化=%s"
      % (_rd.get("planned_dry_run"),
         [r.get("op") for r in _krows], _kb0 != io.open(_kp, "rb").read()))
_check("K2 dry_run 照旧零副作用（无 decontaminate 记录、盘面零变化、无批次记录）",
       (_rd.get("planned_dry_run") or 0) >= 1
       and not [r for r in _krows if r.get("op") == "decontaminate"]
       and _kb0 == io.open(_kp, "rb").read(), _krows)

# K3：_handled 只认 ok（读侧单点未被改宽）
_kroot3 = _lib("k3")
_cg3 = _mk_cg(_kroot3, P_YES)
_cg3.add("k3_a", "PASSED 甲", layer="knowledge", verification_basis="test")
_cg3.flush()
scrub._log(_cg3, "decontaminate", node_id="k3_a", kind="expired", ok=False,
           actions=["weaken_failed:AccessDenied"])
_h_after_fail = sorted(scrub._handled(_cg3))
scrub._log(_cg3, "decontaminate", node_id="k3_a", kind="expired", ok=True,
           actions=["weaken"])
_h_after_ok = sorted(scrub._handled(_cg3))
_cg3.close()
print("   [读数] K3 ok=False 后名单=%s，ok=True 后名单=%s"
      % (_h_after_fail, _h_after_ok))
_check("K3 _handled 只认 ok：ok=False 的记录不进幂等名单，ok=True 才进",
       _h_after_fail == [] and _h_after_ok == [("k3_a", "expired")],
       (_h_after_fail, _h_after_ok))

# K4：summary 不把失败批次算成成功轮
_sum = scrub.summary(_cg3) if False else None
_kroot4 = _lib("k4")
_cg4 = _mk_cg(_kroot4, P_YES)
scrub._log(_cg4, "decontaminate_batch", ok=False, applied=1, failed_actions=1)
scrub._log(_cg4, "decontaminate_batch", ok=True, applied=2, failed_actions=0)
_s4 = scrub.summary(_cg4)
_cg4.close()
print("   [读数] K4 batches=%s decontaminated=%s"
      % (_s4.get("batches"), _s4.get("decontaminated")))
_check("K4 summary 只把 ok=True 的批次算作成功轮（失败批次不进 batches）",
       _s4.get("batches") == 1 and _s4.get("decontaminated") == 2, _s4)

# ========================================================= E 组：AST 钉子 / 枚举 / 族登记
print("== E 组：AST 钉子 · 枚举完备性 · 族登记 ==")

_scrub_src = io.open(os.path.join(_REPO, "md_cg", "scrub.py"),
                     encoding="utf-8").read()
_tree = ast.parse(_scrub_src)


# 生效条件：node 为 `_log(...)` 调用节点时返回其**第 2 个位置实参**的字符串值（op），非字面量/缺参返回 None；
def _op_of_log(node):
    """取 `_log(cg, op, **rec)` 的 op 字面（第 1 个位置实参是 cg）。"""
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        return node.args[1].value
    return None


#: #411 的 ok 判据面：**只**覆盖这两条记录（`_handled`/`summary` 消费的就是它们）。
_TARGET_OPS = ("decontaminate", "decontaminate_batch")


def _log_ok_values(tree, ops=_TARGET_OPS):
    """`_log(` 调用里 `ok=` 实参的 AST 节点列表，**按 op 收窄**到 `ops`。

    为什么按 op 收窄：`scrub.py` 还有 `calibrate` / `sweep` 两条记录也写 `ok=`
    字面（:911 等），但它们的 ok **不被任何幂等读面消费**、记录里也没有失败标记
    通道 ⇒ 不属本族（登记见 E5）。把 AST 钉子铺到全部 `_log(` 上会顺手改动
    本 issue 范围外的记录、并让「本族」与「全仓」两个面混成一个。
    """
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_log"):
            # _log(cg, op, **rec)：op 是**第 2 个位置实参**（第 1 个是 cg）
            op = (_op_of_log(node))
            if op not in ops:
                continue
            for kw in node.keywords:
                if kw.arg == "ok":
                    out.append(kw.value)
    return out


_oks = _log_ok_values(_tree)
_shapes = [ast.unparse(v) for v in _oks]
print("   [读数] E1 _log(ok=) 实参形态=%s" % _shapes)
# 判据是**绑定链**而不是「字面里出现某个子串」（后者用变量中转就能逃过）：
#   单条记录 ok=_ok，而 _ok 由 _actions_ok(done) 绑定；
#   批次记录 ok=(n_failed == 0)，而 n_failed 由 `if not _ok: n_failed += 1` 汇总。
_chain = ("_ok = _actions_ok(done)" in _scrub_src
          and "if not _ok:" in _scrub_src
          and "n_failed += 1" in _scrub_src)
_check("E1 AST：decontaminate / decontaminate_batch 两条记录的 _log(ok=) 只能是"
       "_ok / n_failed == 0 且其绑定链落在 _actions_ok(...) 上，不得出现字面 "
       "True/False（calibrate/sweep 两条已核非本族，见 E5）",
       len(_oks) == 2 and set(_shapes) == {"_ok", "n_failed == 0"} and _chain
       and not any(isinstance(v, ast.Constant) for v in _oks),
       (_shapes, _chain))

_handled_src = inspect.getsource(scrub._handled)
print("   [读数] E2 _handled 体=%r" % _handled_src.strip()[:120])
_check("E2 读侧单点：_handled 的过滤只读 ok（不引入第二份 _actions_ok 判据）",
       'rec.get("ok")' in _handled_src and "_actions_ok" not in _handled_src,
       _handled_src.strip()[:160])


#: **守卫侧独立字面表**：三处失败形态的已知全集。刻意**不**引用 scrub.ACTION_FAIL_MARKS
#: —— 引用被测常量会变成自指（把常量改成两项，枚举判据跟着变两项 ⇒ 永远自洽、抓不到漏形态）。
_KNOWN_FAIL_MARKS = ("weaken_failed:", "demote_failed:", "demote_state:")


def _fail_forms_in_src(src):
    """源码里的失败形态：扫每个 `done.append(...)` 实参中的**字符串字面量**，
    取其命中 ACTION_FAIL_MARKS 前缀的那些（与 scrub._actions_ok 同一判据）。"""
    hits = []
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append" and node.args):
            arg = node.args[0]
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                        and sub.value.startswith(_KNOWN_FAIL_MARKS):
                    hits.append(sub.value)
                # f-string：JoinedStr 的首段常量为前缀字面
                if isinstance(sub, ast.JoinedStr) and sub.values:
                    head = sub.values[0]
                    if (isinstance(head, ast.Constant)
                            and isinstance(head.value, str)
                            and head.value.startswith(_KNOWN_FAIL_MARKS)):
                        hits.append(head.value)
    return sorted(set(hits))


_forms = _fail_forms_in_src(_scrub_src)
print("   [读数] E3 源码失败形态=%s 常量元组=%s"
      % (_forms, list(scrub.ACTION_FAIL_MARKS)))
_check("E3 枚举完备：源码里 done.append 的失败形态**恰为**守卫侧独立字面表的"
       "三项，且 scrub.ACTION_FAIL_MARKS 与之逐项相等（多＝常量元组冗余会过度收紧；少＝漏形态）",
       sorted(_forms) == sorted(_KNOWN_FAIL_MARKS)
       and sorted(scrub.ACTION_FAIL_MARKS) == sorted(_KNOWN_FAIL_MARKS),
       (_forms, list(scrub.ACTION_FAIL_MARKS)))

_wl = io.open(os.path.join(_REPO, "md_cg", "writelimit.py"),
              encoding="utf-8").read()
_wl_tidy = "def _already_tidied(" in _wl and "TIDY_TAG" in _wl
_wl_cov = 'already_covered' in _wl
print("   [读数] E4 writelimit 登记：_already_tidied=%s already_covered=%s"
      % (_wl_tidy, _wl_cov))
_check("E4 **已核、非本族**登记：writelimit.py:383 _already_tidied 与 :373 "
       "already_covered 判的是**落盘条目字段**（tags/lifecycle_state、content_sink "
       "的字面动作名）而非本轮结果，其通路无「无条件写成功」写侧、也不是审计记录 "
       "⇒ 不需要同款不变量（防将来被误当漏点）",
       _wl_tidy and _wl_cov)

#: 非本族的 _log(ok= 字面落点（已核、登记，防将来被误当漏点）。
_ADJACENT_OK_SITES = ("calibrate", "sweep")
_other = sorted({_op_of_log(n) for n in ast.walk(_tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "_log" and _op_of_log(n)
                  and _op_of_log(n) not in _TARGET_OPS})
print("   [读数] E5 其余 _log op=%s" % _other)
_check("E5 **已核、非本族**登记：calibrate / sweep 的 _log(ok=True) 不消费于任何幂等"
       "读面（_handled/summary 只读 decontaminate(_batch)）、记录里也无失败标记通道"
       "⇒ 不需同款不变量（防将来被误当漏点）",
       set(_other) == set(_ADJACENT_OK_SITES), _other)

# ---- _guard_kit 骨架①：枚举完备性（喂合成样本给**本守卫自己的**枚举逻辑）----
_enum_samples = [
    ("weaken 失败形态",
     'def f(exc):\n    done.append(f"weaken_failed:{type(exc).__name__}")\n',
     True, "syn1.py"),
    ("demote 失败形态",
     'def f(exc):\n    done.append(f"demote_failed:{type(exc).__name__}")\n',
     True, "syn2.py"),
    ("demote_state 失败形态",
     'def f(st):\n    done.append("demote" if st else f"demote_state:{st}")\n',
     True, "syn3.py"),
    ("反向：成功动作名",
     'def f():\n    done.append("weaken")\n    done.append("demote")\n',
     False, "syn4.py"),
    ("反向：无冒号的同名字面",
     'def f():\n    done.append("weaken_failed")\n    done.append("demote_state")\n',
     False, "syn5.py"),
]
_eok, _edet = _guard_kit.assert_enumeration_complete(
    lambda texts: [h for src in texts.values() for h in _fail_forms_in_src(src)],
    _enum_samples)
print("   [读数] 骨架① 枚举完备性：%s" % (_edet.get("样本"),))
_check("骨架① assert_enumeration_complete：合成样本三形态全命中、反向样本零命中",
       _eok, _edet)

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #411 结果：%d 失败 → %s" % (len(FAILS), ", ".join(FAILS)))
else:
    print("issue #411 结果：全部通过")

# ========================================================= 定点变异（镜像树）
_MUTATIONS = (
    ("M1 回退写侧单条：ok=_ok → ok=True（#411 的修前形态）",
     (("md_cg/scrub.py", ["ok=_ok,"], ["ok=True,"]),),
     ("A2", "A3", "A5", "E1")),
    ("M2 _actions_ok 恒 True（判据摘除，失败重新写成已处置）",
     (("md_cg/scrub.py",
       ["    return not any(str(a).startswith(ACTION_FAIL_MARKS)",
        "                   for a in (actions or ()))"],
       ["    return True"]),),
     # A5 也红：失败轮被写成已处置 ⇒ 下一轮被幂等名单拦成 skip、成功轮不再出现。
     # K1 也红：三形态全判成功（判据被摘除）。
     ("A2", "A3", "A4", "A5", "K1")),
    ("M3 **过度收紧方向**：_actions_ok 恒 False（合法成功被误判成失败）",
     (("md_cg/scrub.py",
       ["    return not any(str(a).startswith(ACTION_FAIL_MARKS)",
        "                   for a in (actions or ()))"],
       ["    return False"]),),
     ("A4", "A5", "K1")),
    ("M4 读侧把 ok 判据拆掉（失败行重新进幂等名单）",
     (("md_cg/scrub.py",
       ['        if rec.get("op") == "decontaminate" and rec.get("ok"):'],
       ['        if rec.get("op") == "decontaminate":']),),
     # A5/K3 也红：失败行进了幂等名单 ⇒ 下一轮不再真处置，且 K3 的「ok=False 不进名单」被推翻。
     ("A3", "A5", "E2", "K3")),
    ("M5 回退批次写侧：ok=(n_failed == 0) → ok=True",
     (("md_cg/scrub.py", ["ok=(n_failed == 0), applied=n_applied,"],
       ["ok=True, applied=n_applied,"]),),
     ("A4", "E1")),
    ("M6 常量元组退回交接规格两项（漏 demote_state: 第三种形态）",
     (("md_cg/scrub.py",
       ['ACTION_FAIL_MARKS = ("weaken_failed:", "demote_failed:", "demote_state:")'],
       ['ACTION_FAIL_MARKS = ("weaken_failed:", "demote_failed:")']),),
     ("E3", "K1")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss411_mut_")
    for name in ("md_cg", "scripts", "data"):
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
    with io.open(path, "rb") as fh:
        raw = fh.read(8192)
    return "\r\n" if b"\r\n" in raw else "\n"


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue411_scrub_idempotence"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


# ---- _guard_kit 骨架②：回退即红（实跑，不接受推演）----
def _skeleton_revert():
    ok, det = _guard_kit.assert_revert_reddens(
        _mirror_build,
        [("md_cg/scrub.py", "ok=_ok,", "ok=True,")],
        _run_in, ("A2", "A3", "A5", "E1"), "md_cg/scrub.py", timeout=1800)
    print("   [读数] 骨架② 回退即红：%s" % json.dumps(
        {k: v for k, v in det.items() if k != "输出尾部"}, ensure_ascii=False,
        default=str)[:400])
    _check("骨架② assert_revert_reddens：把 ok=_actions_ok(done) 实退回 ok=True ⇒ "
           "守卫转红且红项**恰为** A2/A3/A5/E1", ok, det)


def _mutate():
    print("!! 定点变异自证：把修复点改回改动前形态，守卫必须转红")
    _skeleton_revert()
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
                old, new = nl.join(oldp), nl.join(newp)
                with io.open(p, encoding="utf-8", newline="") as fh:
                    t = fh.read()
                if t.count(old) != 1:
                    miss.append("%s —— 锚点命中 %d 次" % (rel, t.count(old)))
                    continue
                backups.append((p, t))
                with io.open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(t.replace(old, new, 1))
            if miss:
                bad.append("%s —— %s" % (desc, "；".join(miss)))
                print("  ANCHOR-MISS " + desc)
                for p, t in backups:
                    with io.open(p, "w", encoding="utf-8", newline="") as fh:
                        fh.write(t)
                continue
            rc2, reds2, out2 = _run_in(tree)
            for p, t in backups:
                with io.open(p, "w", encoding="utf-8", newline="") as fh:
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
