# -*- coding: utf-8 -*-
"""md_cg · 会话要点读出口可见性守卫（N202，restricted 档要点明文回给处置链路之外身份）

行号按修复后（本批 mdcos.py 因 +26 行 `_note_visible` 与闸位注释整体下移）。

缺陷（修复前）：`md_cg/mdcos.py:2548 _session_notes` 全函数体**零 `_readable`
调用**——它只按 tag 过滤（SESSION_TAG / `session:`）后 `self._read(e)` 回读正文
（:2573），`content is None` 才 continue（原 :2532-2533，注释自述「不可读
（无密钥 / 身份不符）→ 视为不存在」）。而 `_read`（mdcg.py:2445-2454）只在
**文件缺失/读失败**时返回 None：`restricted` 档按设计**不加密、盘上明文**
（同族断言见 md_cg/test_read_scope_b27.py:215「restricted 落盘不加密」），故该
continue 分支对「身份不可读」**永不生效**——可见性单点 `_readable`（:3973）被
get(:4087)/search_rrf(:4104)/list_goals(:4026)/_chain_visible(:4020)/_candidates
(:4070) 消费（单点健全），唯独这个读出口没接线（`session_recall` ① 段直接取它
的结果）。

后果：持 session op 的低密级身份（tokens.ROLE_SPECS 里 record/reflect/output/
sustain 的 ops_allow 含 "session" 而 `can_read_restricted=False`）调
`cg(op=session, action=recall)`（工具面 md_cg/mcp_server.py:2607-2614 →
mdcos.session_recall）即可拿到 restricted 档会话要点的**正文摘要明文**
（`_session_digest` 取 `# 执行：` 字段，:2498）；同一节点经 get/search
已正确拒绝（B27-6d/6e/6f），即「同一库两条出口口径不一致」。restricted =
错误处置标记（批次 28 分型：密级底线 internal ∧ 处置链路角色
designer/orchestr/verify 或 can_admin）。

修复（最小改动 · fail-closed，单点接线）：`_session_notes` 的 tag 过滤之后、
`_read` 之前断言可见性——判据取**同一个 `_readable`**（同一 `self.principal`），
故两侧口径**必然一致**；处置链路身份与同密级（internal/public）要点零影响。
取用方式为仓内既有的**可选钩子**口径（`_note_visible`，mdcos.py 模块级）：
`_readable` 定义在**子类** `MdCGSecure`，读数出口却在基类 `MdCGOS`——直调会让
纯 MdCGOS 实例（无身份/密级模型）抛 AttributeError 并被上层 except 吞成
degraded（修中实测：md_cg/test_p29_session_ingest_export 因此转红，见 ⑩ 组）。
同族第二出口（**本守卫实跑发现，N211**）：`session_recall` ④ 未解问题段同一
根因（只按 layer 过滤 → 直读正文 → 抽 `# 问题：`），restricted 档问题正文同样
明文外泄——同批接同一判据。

守卫（⓿+十一组，全部临时库 + 哑主密钥 + 临时令牌库，**绝不触真实 ~/.mdcg**）：
  ⓿ 隔离自证：aux 根与令牌库都落在守卫临时目录（否则中止，不带病跑）；
  ① 红转绿核心：record 身份 session_recall 的 notes 不含 restricted 正文摘要
     （修前 = 命中「RESTRICTED-ABC-def」即红），但仍含 internal 要点（反向腿：
     防「一刀切清空」式过度收紧）；
  ② 单点直调：`_session_notes(session=None/session=SESS)` 两形态同闸；
  ③ 工具面真身：`mcp_server._session_call(cg, {action:"recall"})`（op=session
     分发的实际出口）同闸；
  ④ 口径一致性：同身份下 `cg.get(restricted_id)` 为 None（既有行为）∧ notes
     亦不含该要点（修前两条出口矛盾）；
  ⑤ 攻击面可达性（第一手，替代材料二手结论）：record/reflect/output/sustain
     四角色 session ∈ ops_allow ∧ can_read_restricted=False；
  ⑥ 正控（防过度收紧）：designer/orchestr/verify（处置链路）仍看得到 restricted
     要点；
  ⑦ stdio 端到端（与缺陷材料同口径）：临时令牌库签发 record 令牌 →
     `python -X utf8 -m md_cg.mcp_server` 上 `cg(op=session,action=recall)`，
     响应 JSON 的 notes 不含 restricted 摘要（修前 = 明文泄漏）、含 internal 要点；
  ⑧ 同族第二出口（N211）：④ 未解问题段的 restricted 问题正文不外泄、
     internal 问题仍返回；
  ⑨ 判据确为闸门：置 `MdCGCSecure._readable` 恒真（= 修前形态）→ 两出口泄漏
     双双复现，还原后重新闭合（证明判据就是闸门，非「碰巧空」）；
  ⑩ 纯 MdCGOS（无 `_readable` 钩子）不得因本修复降级：notes 正常返回、
     degraded 段无 notes/unresolved（p29 形态回归）；
  ⑪ 源断言 + floor：两处出口都经 `_note_visible`、判据在 `_read` 之前、
     钩子取用走 getattr 且异常按不可见；实弹断言计数下限。

运行：python -X utf8 -m md_cg.test_n202_session_notes_visibility
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

# ── 隔离前置：必须在 import md_cg 子模块**之前**（tokens/theory/links/signer/
# evidence 在模块级把 aux_root() 冻结成常量，md_cg/datapath.py:254-268 逐字读
# env）——否则会指到真实 ~/.mdcg 并在那里建密钥/令牌库。 ──
_TMP = tempfile.mkdtemp(prefix="n202_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "cd" * 32          # 哑主密钥（纪律：绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")   # 临时令牌库
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")              # 防任何回落
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES",
           "PYTHONIOENCODING", "PYTHONUTF8"):
    os.environ.pop(_k, None)

from . import mcp_server, tokens                       # noqa: E402
from .datapath import aux_root                         # noqa: E402
from .mdcos import MdCGOS, MdCGSecure                  # noqa: E402
from .security import Principal, can_read_restricted   # noqa: E402

# 退场清洁（机制说明，非本次修复面）：库层 `mdcg._atexit_flush_all`（mdcg.py:104-111）
# 在进程退出时对**仍存活实例**补一次 close() → compact/rebuild 会把 `_index.json`
# 写回守卫刚删掉的临时根（实测残留 `<tmp>/n202_*/cgroot/_index.json{,.lock}` 61 字节）。
# atexit 为 LIFO：本处**在任何 MdCG 实例创建之前**注册（早于库层钩子注册时机）→
# 退出时**最后执行**，故最终状态清净。显式清理在 main 收尾也做一次（正常路径即时清）。
atexit.register(lambda: _cleanup(_TMP))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PASS = FAIL = 0
LIVE = 0
FAILS = []
LIVE_FLOOR = 4

SECRET = "限制级会话要点-RESTRICTED-ABC-def"     # restricted 要点（泄漏探针）
PLAIN = "常规会话要点-INTERNAL-XYZ-ghi"          # internal 要点（反向腿锚）
Q_SECRET = "限制级待解问题-RESTRICTED-QQQ-xyz"   # restricted 未解问题（第二出口探针）
Q_PLAIN = "常规待解问题-INTERNAL-QQQ-zzz"
SESS = "session-n202"
ATTACK_ROLES = ("record", "reflect", "output", "sustain")
CHAIN_ROLES = (("designer", "secret", True), ("orchestr", "internal", False),
               ("verify", "internal", False))


def check(name, cond, detail="", live=False):
    global PASS, FAIL, LIVE
    if live:
        LIVE += 1
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s · %s" % (name, detail))


def _princ(role, clearance="internal", can_admin=False, session=None):
    spec = tokens.role_spec(role)
    return Principal(tenant="default", actor="n202-" + role, clearance=clearance,
                     can_write=bool(spec["can_write"]), can_admin=can_admin,
                     role=role, layers_allow=spec["layers_allow"],
                     ops_allow=spec["ops_allow"], auth_mode="test",
                     session=session)


def _notes_of(pack):
    return [n.get("summary") or "" for n in (pack.get("notes") or [])]


def _has(texts, needle):
    return any(needle in (t or "") for t in texts)


def _src_window(src, start, end):
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i)
    return src[i:] if j < 0 else src[i:j]


def _cleanup(path) -> bool:
    """删守卫临时根（Windows 句柄释放有延迟：重试 + gc），失败如实上报。"""
    import gc
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        gc.collect()
        time.sleep(0.25)
    return not os.path.exists(path)


_OPEN = []          # 本守卫创建的图实例：临时根清理前显式 close（释放索引锁句柄）


def _secured(root, principal):
    cg = MdCGSecure(root, principal=principal)
    _OPEN.append(cg)
    return cg


def _close_all():
    for cg in _OPEN:
        try:
            cg.close()
        except Exception:              # noqa: BLE001 —— 清理面不得再抛
            pass


def main():
    global LIVE
    # ---------- ⓿ 隔离自证（fail-closed：未隔离即中止，不带病跑） ----------
    print("[0] 隔离自证")
    aux = aux_root()
    aux_ok = os.path.abspath(aux).lower().startswith(
        os.path.abspath(_TMP).lower())
    tokfile = tokens.token_file()
    tok_ok = os.path.abspath(tokfile).lower().startswith(
        os.path.abspath(_TMP).lower())
    check("0a aux 根（密钥/信任/理论面）落在守卫临时目录", aux_ok, "aux=%s" % aux)
    check("0b 令牌库落在守卫临时目录（绝不触真实凭据）", tok_ok,
          "tokfile=%s" % tokfile)
    if not (aux_ok and tok_ok):
        print("FATAL: 隔离失败，中止（绝不带病跑真实 ~/.mdcg）")
        return 2

    root = os.path.join(_TMP, "cgroot")
    seed = _secured(root, _princ("designer", clearance="secret",
                                can_admin=True))
    r_secret = seed.session_note(SECRET, session=SESS, sensitivity="restricted",
                                 basis="test")
    r_plain = seed.session_note(PLAIN, session=SESS, sensitivity="internal",
                                basis="test")
    # ④ 段（未解问题）的 restricted 探针：同族第二出口（N211）
    seed.add("unres_n209_secret",
             "# 功能名：待解问题样本\n# 生效条件：不限\n# 子功能：待解\n"
             "# 执行：探针\n# 验证方式：test\n# 不适用条件：无\n"
             "# 问题：" + Q_SECRET + "\n",
             layer="unresolved", sensitivity="restricted")
    seed.add("unres_n209_plain",
             "# 功能名：待解问题样本二\n# 生效条件：不限\n# 子功能：待解\n"
             "# 执行：探针\n# 验证方式：test\n# 不适用条件：无\n"
             "# 问题：" + Q_PLAIN + "\n",
             layer="unresolved", sensitivity="internal")
    seed.flush()
    sid_secret, sid_plain = r_secret["id"], r_plain["id"]

    # ---------- ① 红转绿核心：record 的 session_recall ----------
    print("[1] record 身份经 session_recall 取会话要点（session=None 与指定 session 两形态）")
    rec = _secured(root, _princ("record"))
    # 先确认库层该身份对 restricted 节点的既有正确行为（对照面，不得回归）
    check("1a 对照面：record 直接 get(restricted 要点) 必为 None（既有 _readable 行为）",
          rec.get(sid_secret) is None)
    pack_none = rec.session_recall(session=None, limit=5)
    sums_none = _notes_of(pack_none)
    check("1b session=None：notes 不含 restricted 正文摘要（修前 = 明文命中）",
          not _has(sums_none, "RESTRICTED"),
          "notes=%s" % [s[:60] for s in sums_none], live=True)
    check("1c session=None：notes 仍含 internal 要点（反向腿：非一刀切清空）",
          _has(sums_none, "INTERNAL"),
          "notes=%s" % [s[:60] for s in sums_none], live=True)
    pack_sess = rec.session_recall(session=SESS, limit=5)
    sums_sess = _notes_of(pack_sess)
    check("1d session=<归属会话>：restricted 摘要同样不为该身份返回",
          not _has(sums_sess, "RESTRICTED"),
          "notes=%s" % [s[:60] for s in sums_sess], live=True)
    check("1e 未降级：degraded 段无 notes（不是异常被吞成空）",
          "notes" not in (pack_none.get("degraded") or []),
          "degraded=%s" % (pack_none.get("degraded"),))

    # ---------- ② 单点直调（_session_notes） ----------
    print("[2] _session_notes 直调同闸（读数单点接线）")
    d_none = rec._session_notes(session=None, limit=5)
    check("2a 直调 session=None：不含 restricted 摘要且含 internal 要点",
          not _has([n.get("summary") for n in d_none], "RESTRICTED")
          and _has([n.get("summary") for n in d_none], "INTERNAL"),
          "notes=%s" % [n.get("summary", "")[:50] for n in d_none], live=True)

    # ---------- ③ 工具面真身（op=session → _session_call） ----------
    print("[3] 工具面出口 _session_call(action=recall)")
    out = mcp_server._session_call(rec, {"action": "recall", "session": None,
                                         "limit": 5})
    osums = _notes_of(out)
    check("3a op=session 出口不含 restricted 摘要（修前 = 工具面明文泄漏）",
          not _has(osums, "RESTRICTED"),
          "notes=%s" % [s[:60] for s in osums], live=True)
    check("3b op=session 出口仍含 internal 要点", _has(osums, "INTERNAL"),
          "notes=%s" % [s[:60] for s in osums], live=True)

    # ---------- ④ 两条出口口径一致（get vs session_recall） ----------
    print("[4] 口径一致性（可见性单点 vs 会话读数出口）")
    check("4a get(restricted)=None ∧ session_recall 亦不含 → 两出口一致（修前矛盾）",
          rec.get(sid_secret) is None and not _has(sums_none, "RESTRICTED"),
          "get=%r notes=%s" % (rec.get(sid_secret), [s[:40] for s in sums_none]),
          live=True)

    # ---------- ⑤ 攻击面可达性（第一手） ----------
    print("[5] 攻击身份可达性：session ∈ ops_allow ∧ can_read_restricted=False")
    for role in ATTACK_ROLES:
        spec = tokens.role_spec(role)
        p = _princ(role)
        check("5·%s session 在 ops_allow 且 restricted 链路角色缺位"
              % role,
              "session" in (spec["ops_allow"] or [])
              and can_read_restricted(p) is False,
              "ops_allow_has_session=%s can_read_restricted=%s"
              % ("session" in (spec["ops_allow"] or []), can_read_restricted(p)))
        entry = (seed.index.get("nodes") or {}).get(sid_secret) or {}
        check("5·%s 该身份处 _readable(restricted 要点) 确为 False"
              "（修前 session_recall 未消费此判据）" % role,
              bool(entry) and _secured(root, p)._readable(
                  dict(entry)) is False,
              "entry_sens=%s" % entry.get("sensitivity"))

    # ---------- ⑥ 正控：处置链路身份仍可见（防过度收紧） ----------
    print("[6] 正控：designer/orchestr/verify 仍读得到 restricted 要点")
    for role, cl, adm in CHAIN_ROLES:
        cgc = _secured(root, _princ(role, clearance=cl, can_admin=adm))
        csums = _notes_of(cgc.session_recall(session=None, limit=5))
        check("6·%s 处置链路仍见 restricted 摘要（未误伤必读面）" % role,
              _has(csums, "RESTRICTED"),
              "notes=%s" % [s[:50] for s in csums], live=True)

    # ---------- ⑦ stdio 端到端 ----------
    print("[7] stdio 端到端：临时 record 令牌 → cg(op=session,action=recall)")
    issued = tokens.issue("record", actor="n202-rec")
    env = {k: v for k, v in os.environ.items() if not k.startswith("MDCG_")}
    env.update({
        "MDCG_ROOT": root,
        "MDCG_AUX_ROOT": os.environ["MDCG_AUX_ROOT"],
        "MDCG_MASTER_KEY": os.environ["MDCG_MASTER_KEY"],
        "MDCG_TOKEN_FILE": os.environ["MDCG_TOKEN_FILE"],
        "MDCG_TOKEN": issued["token"],
        "MDCG_TENANT_REGISTRY": os.path.join(_TMP, "_tenants_absent.json"),
        "MDCG_STATE_ROOT": os.path.join(_TMP, "state"),
        "MDCG_DATA_ROOT": os.path.join(_TMP, "data"),
        "MDCG_SUSTAIN": "0",
    })
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
             json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                         "params": {"name": "cg", "arguments": {
                             "op": "session", "action": "recall",
                             "session": None, "limit": 5}}}),
             json.dumps({"jsonrpc": "2.0", "id": 3, "method": "shutdown"})]
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        out_s, err_s = proc.communicate("\n".join(lines) + "\n", timeout=180)
    except subprocess.TimeoutExpired:
        proc.kill()
        out_s, err_s = proc.communicate()
    # 自报戳残留清理（诊断设施，非本次修复面）：只删本子进程自己的那份
    try:
        os.remove(os.path.join(tempfile.gettempdir(), "md_cg_servers",
                               "%d.json" % proc.pid))
    except OSError:
        pass
    resp = None
    for ln in (out_s or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if isinstance(o, dict) and o.get("id") == 2:
            resp = o
    payload = {}
    if isinstance(resp, dict):
        try:
            payload = json.loads(
                (resp.get("result") or {}).get("content", [{}])[0].get(
                    "text", "{}"))
        except (ValueError, AttributeError, IndexError):
            payload = {}
    esums = _notes_of(payload)
    check("7a 端到端：record 令牌的 op=session 响应不含 restricted 摘要"
          "（修前 = 整段明文泄漏）",
          proc.returncode == 0 and isinstance(payload, dict)
          and not _has(esums, "RESTRICTED"),
          "rc=%s notes=%s err_tail=%r" % (proc.returncode,
                                          [s[:60] for s in esums], (err_s or "")[-200:]),
          live=True)
    check("7b 端到端：同响应仍含 internal 要点（出口本身仍工作）",
          _has(esums, "INTERNAL"),
          "notes=%s" % [s[:60] for s in esums], live=True)

    # ---------- ⑧ 同族第二出口：④ 未解问题段（N211，本守卫实跑发现） ----------
    print("[8] session_recall ④ 未解问题段（同族第二出口，N211）")
    unres = [u.get("question") or "" for u in (pack_none.get("unresolved") or [])]
    check("8a ④ 段不含 restricted 未解问题正文（修前 = 明文命中）",
          not _has(unres, "RESTRICTED-QQQ"),
          "unresolved=%s" % [u[:60] for u in unres], live=True)
    check("8b ④ 段仍含 internal 未解问题（反向腿：非一刀切清空）",
          _has(unres, "INTERNAL-QQQ"),
          "unresolved=%s" % [u[:60] for u in unres], live=True)

    # ---------- ⑨ 修前病灶复刻：置 _readable 恒真 → 两出口泄漏复现 ----------
    print("[9] 判据确为闸门（置 _readable 恒真 = 修前形态，泄漏必须复现）")
    _orig_readable = MdCGSecure._readable
    MdCGSecure._readable = lambda self, e, session=None: True
    try:
        m_notes = _notes_of(rec.session_recall(session=None, limit=5))
        m_unres = [u.get("question") or ""
                   for u in (rec.session_recall(session=None, limit=5).get(
                       "unresolved") or [])]
    finally:
        MdCGSecure._readable = _orig_readable
    check("9a 置恒真后 notes 泄漏复现（证明 ① 段判据就是 _readable）",
          _has(m_notes, "RESTRICTED"), "notes=%s" % [s[:50] for s in m_notes])
    check("9b 置恒真后 unresolved 泄漏复现（证明 ④ 段判据同源）",
          _has(m_unres, "RESTRICTED-QQQ"),
          "unresolved=%s" % [u[:50] for u in m_unres])
    check("9c 还原后两出口重新闭合（闸可逆、无残留状态）",
          not _has(_notes_of(rec.session_recall(session=None, limit=5)),
                   "RESTRICTED")
          and not _has([u.get("question") or "" for u in
                        (rec.session_recall(session=None, limit=5).get(
                            "unresolved") or [])], "RESTRICTED-QQQ"))

    # ---------- ⑩ 纯 MdCGOS（无 _readable 钩子）不得因本修复降级 ----------
    print("[10] 纯 MdCGOS 实例（无 _readable：无身份/密级模型）读数出口不降级")
    gos = MdCGOS(root, actor="n202-gos")
    _OPEN.append(gos)
    gos.principal = _princ("designer", clearance="secret", can_admin=True)
    gp = gos.session_recall(session=None, limit=5)
    g_notes = _notes_of(gp)
    check("10a 纯 MdCGOS：notes 正常返回（不得因调用不存在的 _readable 而整段降级）",
          _has(g_notes, "INTERNAL"), "notes=%s degraded=%s"
          % ([s[:40] for s in g_notes], gp.get("degraded")), live=True)
    check("10b 纯 MdCGOS：degraded 段无 notes/unresolved（无异常被吞）",
          not ({"notes", "unresolved"} & set(gp.get("degraded") or [])),
          "degraded=%s" % (gp.get("degraded"),), live=True)

    # ---------- ⑪ 源断言 + floor ----------
    print("[11] 源断言与自检")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "mdcos.py"), encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    body = _src_window(src, "def _session_notes", "def session_recall")
    check("11a _session_notes 函数体内接可见性判据（修前 = 零调用）",
          "_note_visible(self, e)" in body, "window_len=%d" % len(body))
    check("11b 判据取用在 _read 之前（fail-closed 序）",
          0 <= body.find("_note_visible(self, e)") < body.find("self._read(e)"),
          "guard_at=%d read_at=%d" % (body.find("_note_visible(self, e)"),
                                      body.find("self._read(e)")))
    helper = _src_window(src, "def _note_visible", "def _session_notes")
    check("11c 判据取用走可选钩子 getattr(cg, \"_readable\") 且异常按不可见"
          "（不误伤纯 MdCGOS，不 fail-open 判据异常）",
          "_readable" in helper and "getattr" in helper,
          "helper_len=%d" % len(helper))
    check("11d ④ 未解问题段同接该判据（同族第二出口已收口）",
          "_note_visible(self, e)" in _src_window(
              src, "# ④ 未解问题", "# ⑤ 自我状态卡"),
          "window_len=%d" % len(_src_window(src, "# ④ 未解问题",
                                            "# ⑤ 自我状态卡")))
    check("11e 实弹断言数 ≥ %d（防 spawn/扫描面失效假绿）" % LIVE_FLOOR,
          LIVE >= LIVE_FLOOR, "LIVE=%d" % LIVE)

    print("\n=== N202 session notes visibility: %d passed, %d failed (live=%d) ==="
          % (PASS, FAIL, LIVE))
    if FAILS:
        print("失败项：%s" % "；".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    _code = 0
    try:
        _code = main()
    finally:
        # 清洁纪律：先关实例（释放索引锁句柄），再清临时根；清不掉如实开口。
        _close_all()
        _dbg_ok = _cleanup(_TMP)
        if not _dbg_ok:
            print("WARN: 临时根残留未清（%s）——请人工清理" % _TMP)
    sys.exit(_code)
