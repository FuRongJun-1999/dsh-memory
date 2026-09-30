# -*- coding: utf-8 -*-
"""md_cg · 索引代际签名 / 陈旧条目可见性 / 重载派生失效（N212 + N213 + N224）

三处缺陷同一根：**索引代际口径只在「他进程 compact 落快照」这一种变化上成立**。

① **N212 代际签名口径（`md_cg/mdcg.py:1023-1035 / 1053-1055 / 1180-1199`）**
   `_index_signature` 只 stat `_index.json` 的 (mtime_ns, size)，而 `flush()`
   **只 append `_index_log` 分片、从不重写快照**。于是「长期存活、autoflush=1
   只 flush 不 close」的写方（MCP serve 本身即此形态）**对本进程永久隐形**：
     · 写保护闸静默失效（N195 修复面回退）：`add` 覆写他进程刚写的 anchor 节点
       不抛 ProtectionError、不落 `_protected_history` 快照、不写
       `_protected_audit.jsonl`，旧正文不可恢复且无痕；
     · 存在性假阴性：`get` → None、`forget` → not_found、`override=True` 无效；
     · 文档承诺的逃逸口 `maintain action=reload` 返回 `reloaded=false`。
   次生（②）：`prev_entry` 取本进程索引 → 为 None ⇒ `mdcg.py:1794-1812` 的
   「写新文件再删旧文件」整段跳过 ⇒ 同一 id 落成**两份文件**（同层不同桶时），
   重开时索引在两版正文间漂移、一份永久孤儿。

③ **N213 陈旧条目判可见性（`md_cg/mdcos.py:4104-4118`）**
   `MdCGSecure.get` 用**本进程陈旧 entry** 的 sensitivity/session 判可见性，而正文
   解密自**当前盘上文件**（文件是真值、判据是旧快照）⇒ 同 actor 异 session 的
   private 节点在被判定「internal 且属本会话」后照常放行，正文以明文返回
   （AEAD 的 AAD 只绑 node_id/tenant/actor，session 是唯一隔离维度）。
   N196 的修复只在 `e is None` 分支探活，命中陈旧条目的路径全程零探活。

④ **N213 同根次生（`md_cg/protect.py:63-94`）**
   `_node_entry`/`_stage` **恒落** protected/immutable/self_state 三键（值可为
   None）⇒ `need_fallback` 的三个析取子句恒假、第四个（self_state 缺键且层受保护）
   在本仓所有构造点不可达 ⇒ `_fm` 100% 信任索引、**从不重读文件**。他进程在陈旧
   条目上刚盖的 immutable/protected（`add(immutable=True)` 一类）对
   guard_write / guard_forget / guard_move 全部不可见 → 受保护节点被静默覆写。
   与 `protect.mark`（只改文件 + 内存条目，**不进写日志**）同源。

⑤ **N224 重载后派生缓存不失效（`md_cg/mdcg.py:1068-1078`）**
   `_maybe_reload_index` 只清 hotcache/readcache/realpath，**不清** chain/subgraph/
   trust 三个派生缓存（本地写路径 `mdcg.py:1875-1877` 三个都失效）⇒ 重载后邻接表
   仍含「已不可见节点」的 id 与跳转条件（walk/explain/causal_path/
   expand_from_seeds 绕读隔离），新快照的节点/边在下次本地写前**永不进拓扑**。

守卫（六组，全部临时库 + 哑主密钥 + 临时令牌库，**绝不触真实 ~/.mdcg**）：
  ⓿ 隔离自证；① N212 核心（存活写方只 flush：探活/get/保护闸/逃逸口/无痕复刻）；
  ② N212 次生（同 id 双桶双文件 / 索引指向孤儿）；③ N213 跨会话明文泄漏 + 候选面；
  ④ N213 同根（immutable 与 protect.mark 的保护位对守卫不可见）；
  ⑤ N224（不可见化未传播 + 新节点不进 chain/trust/subgraph 缓存）；⑥ 源断言 + floor。

运行：python -X utf8 -m md_cg.test_n212_n213_n224_generation_gates
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
import time

# ── 隔离前置：必须在 import md_cg 子模块**之前**（tokens/theory 等在模块级把
# aux_root() 冻成常量）——否则会指到真实 ~/.mdcg 并在那里建密钥/令牌库。 ──
_TMP = tempfile.mkdtemp(prefix="n212_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "ef" * 32          # 哑主密钥（绝不触真实密钥面）
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES",
           "PYTHONIOENCODING", "PYTHONUTF8"):
    os.environ.pop(_k, None)

from . import chain, crypto, protect, subgraph, tokens, trust  # noqa: E402
from .datapath import aux_root                                        # noqa: E402
from .mdcos import MdCGSecure                                         # noqa: E402
from .security import Principal                                       # noqa: E402

atexit.register(lambda: _cleanup(_TMP))       # LIFO：晚于库层 _atexit_flush_all

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

PASS = FAIL = LIVE = 0
LIVE_FLOOR = 20
FAILS = []

R1 = os.path.join(_TMP, "cg1")      # N212 核心
R2 = os.path.join(_TMP, "cg2")      # N212 次生
R3 = os.path.join(_TMP, "cg3")      # N213 跨会话
R4 = os.path.join(_TMP, "cg4")      # N213 同根（protect 面）
R5 = os.path.join(_TMP, "cg5")      # N224 派生缓存
R6 = os.path.join(_TMP, "cg6")      # N213 第三序面（_dirty 遮蔽 + 正文水合）

ANCHOR_BODY = "# 身份锚点（甲）：灵枢的锚点声明。\n"
FORGED = "# 身份锚点（伪）：被覆写的伪造内容。\n"
DUP_B = "# 知识条目（乙）：本地磁盘观测路径。\n"
DUP_A = "# 知识条目（丙）：云端观测路径。\n"
INTERNAL_BODY = "# 情境记录（丁）：跨会话泄漏探针·初版（internal）。\n"
PRIVATE_BODY = "# 情境记录（戊）：跨会话泄漏探针·私密档（private）。\n"
IMM_BODY = "# 情境记录（己）：不可覆盖标记探针。\n"
MARK_BODY = "# 情境记录（庚）：显式保护标记探针。\n"
X_BODY = "# 知识条目（辛）：关系链可见性探针。\n"
PRIV_X = "# 知识条目（壬）：被私密化的关系链探针。\n"


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


def _princ(role, clearance="internal", can_admin=False, session=None,
           actor=None, layers=None):
    spec = tokens.role_spec(role)
    return Principal(tenant="default", actor=actor or ("n212-" + role),
                     clearance=clearance, can_write=bool(spec["can_write"]),
                     can_admin=can_admin, role=role, session=session,
                     layers_allow=(spec["layers_allow"] if layers is None
                                   else layers),
                     ops_allow=spec["ops_allow"], auth_mode="test")


_OPEN = []


def _secured(root, principal):
    cg = MdCGSecure(root, principal=principal)
    _OPEN.append(cg)
    return cg


def _designer(root, actor="n212"):
    return _secured(root, _princ("designer", clearance="secret",
                                 can_admin=True, actor=actor))


def _reflect(root, session, actor="n213"):
    """同 actor 异 session 的非管理身份（reflect：contextual 可写、无管理位）。"""
    return _secured(root, _princ("reflect", clearance="private",
                                 can_admin=False, session=session, actor=actor,
                                 layers=("contextual",)))


def _close_all():
    for cg in _OPEN:
        try:
            cg.close()
        except Exception:                      # noqa: BLE001 —— 清理面不得再抛
            pass


def _cleanup(path) -> bool:
    import gc
    for _ in range(6):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        gc.collect()
        time.sleep(0.25)
    return not os.path.exists(path)


def _raises(fn, *a, **kw):
    """执行并返回 (ok, 异常类名/空, 结果/异常文本)。"""
    try:
        return True, "", fn(*a, **kw)
    except Exception as exc:                   # noqa: BLE001 —— 守卫要的是拒绝形态
        return False, type(exc).__name__, str(exc)


def _files_named(root, nid):
    """root 下（含各层/桶目录）名字恰为 <nid>.md 的文件相对路径列表。"""
    out = []
    for dp, _d, files in os.walk(root):
        for fn in files:
            if fn == nid + ".md":
                out.append(os.path.relpath(os.path.join(dp, fn), root)
                           .replace("\\", "/"))
    out.sort()
    return out


def _disk_fm(root, nid, actor="n213"):
    """盘上真值：同 root 新建 designer 实例（自带全量重扫）读 fm 与原始正文。"""
    cg = _designer(root, actor=actor)
    e = (cg.index.get("nodes") or {}).get(nid) or {}
    fm, content = cg._read(e)
    return (fm or {}), (content or ""), e


def _audit_rows(root):
    p = os.path.join(root, protect.AUDIT_FILE)
    if not os.path.exists(p):
        return []
    out = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        return []
    return out


def _src_window(src, start, end):
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i)
    return src[i:] if j < 0 else src[i:j]


def _read_src(rel):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)
    with open(p, encoding="utf-8") as f:
        return f.read()


def main():
    global LIVE
    # ---------- ⓿ 隔离自证 ----------
    print("[0] 隔离自证")
    _tok = tokens.token_file()
    check("0a 默认令牌库与 aux 根都落在守卫临时目录（绝不触真实凭据）",
          os.path.abspath(_tok).lower().startswith(os.path.abspath(_TMP).lower())
          and os.path.abspath(aux_root()).lower().startswith(
              os.path.abspath(_TMP).lower()),
          "tok=%s aux=%s" % (_tok, aux_root()))
    for _r in (R1, R2, R3, R4, R5):
        if not os.path.abspath(_r).lower().startswith(
                os.path.abspath(_TMP).lower()):
            print("FATAL: 隔离失败，中止（绝不带病跑真实库）")
            return 2

    # ================= ① N212 核心：存活写方只 flush =================
    print("\n【①】N212 代际签名：常驻 A + 存活写方 B（只 flush 不 close）")
    a1 = _designer(R1)                       # 常驻 A（先建：签名基线在 B 写入前）
    a1.add("n212_seed", "# 知识条目（甲）：常驻进程初始记忆。\n",
           layer="knowledge")
    a1.flush()
    b1 = _designer(R1, actor="n212b")        # 存活写方 B：绝不 close
    b1.add("n212_anchor", ANCHOR_BODY, layer="anchor")
    b1.flush()                               # 只落分片日志，不写快照
    check("1 setup：盘上已有 B 写入的 anchor 节点（B 存活、快照未重写）",
          _files_named(R1, "n212_anchor") and not os.path.exists(
              os.path.join(R1, "_index.json")),
          "files=%r" % _files_named(R1, "n212_anchor"))
    check("1a A._maybe_reload_index() 为他进程分片日志变化返回 True",
          a1._maybe_reload_index() is True, "reloaded=False（签名只看快照）",
          live=True)
    check("1b A.get 可见他进程刚写入的 anchor 节点（存在性假阴性已消）",
          a1.get("n212_anchor") is not None, "get=None", live=True)
    _imm, _why = protect.is_immutable(a1, "n212_anchor")
    check("1c 保护面判据可见他进程 anchor 节点（is_immutable=True）",
          _imm is True, "is_immutable=%r/%r" % (_imm, _why), live=True)
    b1.add("n212_esc", "# 知识条目（乙）：逃逸口探针。\n", layer="knowledge")
    b1.flush()                               # 新的海外变化（逃逸口用）
    _esc = a1.maintain(action="reload")
    check("1d 逃逸口 maintain reload 对存活写方的写入返回 reloaded=True",
          isinstance(_esc, dict) and _esc.get("reloaded") is True,
          str(_esc)[:120], live=True)
    # 销毁腿：覆写他进程 anchor 节点必须被拒 + 零留痕
    b1.add("n212_ovr", ANCHOR_BODY, layer="anchor")
    b1.flush()
    ok, exc, _res = _raises(a1.add, "n212_ovr", FORGED, layer="anchor")
    check("1e A.add 覆写他进程 anchor 节点被 ProtectionError 拒绝",
          (not ok) and exc == "ProtectionError", "exc=%s" % exc, live=True)
    _fm, _c, _e = _disk_fm(R1, "n212_ovr", actor="n212")
    check("1f 拒绝后盘上正文保持 B 的原文（未被伪造内容覆写）",
          ANCHOR_BODY in _c and FORGED not in _c, repr(_c)[:90], live=True)
    check("1g 拒绝路径零留痕改动：无该 id 的快照目录、无 override_write 审计",
          not os.path.isdir(os.path.join(R1, protect.HISTORY_DIR, "n212_ovr"))
          and not [r for r in _audit_rows(R1)
                   if r.get("node_id") == "n212_ovr"], live=True)
    # ①b 修前形态复刻：禁用探活 = 修前病灶（闸静默失效、无痕覆写）
    _orig_probe = a1._maybe_reload_index
    a1._maybe_reload_index = lambda: False
    try:
        b1.add("n212_red", ANCHOR_BODY, layer="anchor")
        b1.flush()
        ok2, exc2, _r2 = _raises(a1.add, "n212_red", FORGED, layer="anchor")
    finally:
        a1._maybe_reload_index = _orig_probe
    check("1h 红形态复刻：禁用代际探活后写保护闸静默失效（不抛 ProtectionError）",
          ok2 is True, "exc=%s" % exc2, live=True)
    _fm2, _c2, _e2 = _disk_fm(R1, "n212_red", actor="n212")
    check("1i 红形态复刻：伪造正文已无痕覆写盘面且零快照零审计",
          FORGED in _c2
          and not os.path.isdir(os.path.join(R1, protect.HISTORY_DIR,
                                             "n212_red"))
          and not [r for r in _audit_rows(R1)
                   if r.get("node_id") == "n212_red"],
          repr(_c2)[:80], live=True)

    # ================= ② N212 次生：同 id 双桶双文件 =================
    print("\n【②】N212 次生：同 id 跨桶覆写必须只留一份文件（旧文件清理）")
    a2 = _designer(R2)
    a2.add("n212_seed2", "# 知识条目（丙）：次生探针种子。\n", layer="knowledge")
    a2.flush()
    b2 = _designer(R2, actor="n212b2")
    b2.add("n212_dup", DUP_B, layer="knowledge",
           condition_space={"observation_position": "本地磁盘"})
    b2.flush()
    a2.add("n212_dup", DUP_A, layer="knowledge",
           condition_space={"observation_position": "云端"})
    _dups = _files_named(R2, "n212_dup")
    check("2a 同 id 跨桶覆写后盘上恰一份文件（无孤儿副本）",
          len(_dups) == 1, "files=%r" % _dups, live=True)
    a2.flush()
    a2.close()
    _f2 = _designer(R2)
    _n2 = _f2.get("n212_dup") or {}
    check("2b 重开索引指向的文件内容 == 最后写入版本（无版本漂移/孤儿）",
          DUP_A in (_n2.get("content") or "")
          and len(_files_named(R2, "n212_dup")) == 1,
          "content=%r files=%r" % ((_n2.get("content") or "")[:40],
                                   _files_named(R2, "n212_dup")), live=True)

    # ================= ③ N213：跨会话私密泄漏 =================
    print("\n【③】N213 陈旧条目判可见性：同 actor 异 session 的 private 明文泄漏")
    a3 = _reflect(R3, "S1")
    a3.add("n213_priv", INTERNAL_BODY, layer="contextual")     # internal/S1
    a3.add("n213_ctrl", "# 情境记录（辛）：共享档阳性对照。\n",
           layer="contextual")
    a3.flush()          # serve 形态：autoflush=1，写后即落分片日志
    b3 = _reflect(R3, "S2")
    b3.add("n213_priv", PRIVATE_BODY, layer="contextual",
           sensitivity="private")                              # private/S2
    b3.flush()
    _fm3, _c3, _e3 = _disk_fm(R3, "n213_priv")
    check("3 setup：盘上真值已是 private/S2 且正文为密文",
          _fm3.get("sensitivity") == "private" and _fm3.get("session") == "S2"
          and crypto.is_encrypted(_c3),
          "sens=%r sess=%r enc=%r" % (_fm3.get("sensitivity"),
                                      _fm3.get("session"),
                                      crypto.is_encrypted(_c3)))
    _got = a3.get("n213_priv")
    check("3a 异 session 读 private：get 必须 None（不返回明文）",
          _got is None,
          "leaked=%r" % ((_got or {}).get("content") or "")[:60], live=True)
    a3._maybe_reload_index()
    _cands = a3._candidates(layer="contextual")
    _target = a3.index["nodes"].get("n213_priv")
    _ctrl = a3.index["nodes"].get("n213_ctrl")
    check("3b 候选面同闸：异 session 的 private 不进候选（条目身份比对）",
          _target is not None
          and not any(e is _target for e in _cands),
          "cand=%d" % len(_cands), live=True)
    check("3c 阳性对照：共享档（internal/S1）仍在候选中（闸未误伤）",
          _ctrl is not None and any(e is _ctrl for e in _cands),
          "cand=%d" % len(_cands), live=True)
    # ③d 第三序面（本批首手实测：本条同时钉住 _open_content 的解密出口闸）。
    # **N230（2026-10-01，P0-3）改判**：本组原 setup 断言「A 内存条目仍是本地未
    # 落盘版本（`_dirty` 重放遮蔽盘上真值）」，即把**旧盖新**当既定行为钉住。
    # N230 修复后该遮蔽不再发生——重载取回的是他进程写下的更新条目，本实例这条
    # 陈旧 `_dirty` 被逐字见证判为陈旧、**跳过重放**（新记录必须能盖住旧记录）。
    # 故 setup 断言改为「收敛到盘面真值（private/S2）」；下游两条（`get` 同闸拒绝、
    # 正文水合不泄明文）语义不变，且在新语义下更强：索引侧密级也已是 private。
    print("\n【③d】他进程更新条目必须盖过本实例陈旧 _dirty 条目（N230）")
    a6 = _reflect(R6, "S1")
    a6.add("n213_d", INTERNAL_BODY, layer="contextual")        # 故意不 flush
    b6 = _reflect(R6, "S2")
    b6.add("n213_d", PRIVATE_BODY, layer="contextual",
           sensitivity="private")
    b6.flush()
    a6._maybe_reload_index()
    _e6 = a6.index["nodes"].get("n213_d") or {}
    check("3d setup：A 重载后条目**收敛到盘面真值**（N230：旧不得盖新）",
          _e6.get("sensitivity") == "private" and _e6.get("session") == "S2"
          and a6._dirty_replay_superseded >= 1,
          "sens=%r sess=%r superseded=%r"
          % (_e6.get("sensitivity"), _e6.get("session"),
             getattr(a6, "_dirty_replay_superseded", None)))
    check("3d A.get 同闸拒绝",
          a6.get("n213_d") is None,
          repr((a6.get("n213_d") or {}).get("content") or "")[:50], live=True)
    _res6, _m6 = a6.search("跨会话泄漏探针")
    _leak6 = [n.get("id") for n, _s, _q in _res6
              if PRIVATE_BODY.strip() in str(n.get("content") or "")]
    check("3d search 正文水合同闸：私密正文不以明文进入检索结果",
          not _leak6, "leaked=%r" % (_leak6, ), live=True)

    # ================= ④ N213 同根次生：protect 面陈旧条目 =================
    print("\n【④】N213 同根：他进程新盖的 immutable/protected 对守卫不可见")
    a4 = _designer(R4)
    a4.add("n213_seed", "# 知识条目（丁）：陈旧条目探针种子。\n",
           layer="knowledge")
    a4.flush()
    b4 = _designer(R4, actor="n213b")
    b4.add("n213_imm", IMM_BODY, layer="contextual", immutable=True)
    b4.flush()
    _imm4, _why4 = protect.is_immutable(a4, "n213_imm")
    check("4a 他进程 immutable 标记可见（is_immutable=True）",
          _imm4 is True, "is_immutable=%r/%r" % (_imm4, _why4), live=True)
    ok4, exc4, _r4 = _raises(a4.add, "n213_imm", FORGED, layer="contextual")
    check("4b 覆写他进程 immutable 节点被 ProtectionError 拒绝",
          (not ok4) and exc4 == "ProtectionError", "exc=%s" % exc4, live=True)
    _fm4, _c4, _e4 = _disk_fm(R4, "n213_imm", actor="n213b")
    check("4c 拒绝后盘上正文未变", IMM_BODY in _c4 and FORGED not in _c4,
          repr(_c4)[:80], live=True)
    b4.add("n213_mark", MARK_BODY, layer="contextual")
    b4.flush()
    protect.mark(b4, "n213_mark", "N213 探针·显式保护标记")
    _pr4, _pw4 = protect.is_protected(a4, "n213_mark")
    check("4d protect.mark 的显式保护位对他进程可见（None ≠ 未标记）",
          _pr4 is True and "N213 探针" in _pw4,
          "is_protected=%r/%r" % (_pr4, _pw4), live=True)
    ok4b, exc4b, _r4b = _raises(protect.guard_forget, a4, "n213_mark")
    check("4e guard_forget 对 protect.mark 节点抛出 ProtectionError",
          (not ok4b) and exc4b == "ProtectionError", "exc=%s" % exc4b, live=True)

    # ================= ⑤ N224：重载后派生缓存必须失效 =================
    print("\n【⑤】N224 重载后 chain/subgraph/trust 三个派生缓存不失效")
    a5 = _reflect(R5, "S1", actor="n224")
    a5.add("n224c", "# 知识条目（子）：层级子节点。\n", layer="contextual")
    a5.add("n224x", X_BODY, layer="contextual", importance=0.3)
    a5.add("n224d", "# 知识条目（依）：依赖 x 的单元。\n", layer="contextual",
           depends_on=["n224x"])
    a5.add("n224y", "# 知识条目（父）：声明边与子层。\n", layer="contextual",
           edges=[{"target": "n224x", "relation_type": "depends_on"}],
           depends_on=["n224x"], subgraph={"nodes": ["n224c"]})
    a5.flush()
    _adj0 = chain.adjacency(a5)
    check("5 setup：初始邻接表含 y→x 边",
          any(t == "n224x" for t, _e in _adj0.get("n224y", [])),
          "adj=%r" % (sorted(_adj0), ))
    _deps0 = trust.dependents_index(a5)
    check("5 setup：初始依赖反查含 x←d",
          "n224d" in _deps0.get("n224x", []), str(_deps0)[:120])
    _par0 = subgraph.parents_index(a5)
    check("5 setup：初始父子反查含 c←y",
          "n224y" in _par0.get("n224c", []), str(_par0)[:120])
    b5 = _reflect(R5, "S2", actor="n224")
    b5.add("n224x", PRIV_X, layer="contextual", sensitivity="private")
    b5.flush()
    b5.add("n224z", "# 知识条目（新）：他进程新写入的依赖者。\n",
           layer="contextual", depends_on=["n224y"],
           edges=[{"target": "n224y", "relation_type": "depends_on"}])
    b5.flush()
    b5.add("n224g", "# 知识条目（新父）：他进程新写入的层级父。\n",
           layer="contextual", subgraph={"nodes": ["n224c"]})
    b5.flush()
    check("5a 探活：B 的新写入使 _maybe_reload_index 返回 True",
          a5._maybe_reload_index() is True, "reloaded=False", live=True)
    _adj1 = chain.adjacency(a5)
    check("5b 关系链读隔离：已不可见节点 x 的出边与指向 x 的边整体消失",
          "n224x" not in _adj1
          and not [t for t, _e in _adj1.get("n224y", []) if t == "n224x"],
          "y→x 仍在：%r" % (_adj1.get("n224y"), ), live=True)
    check("5c 新快照节点进拓扑：他进程新写入的 z 出现在邻接表",
          "n224z" in _adj1, "adj keys=%r" % sorted(_adj1), live=True)
    _deps1 = trust.dependents_index(a5)
    check("5d 依赖反查失效重算：新写入的 z 挂到 y 之下",
          "n224z" in _deps1.get("n224y", []), str(_deps1)[:160], live=True)
    _par1 = subgraph.parents_index(a5)
    check("5e 父子反查失效重算：新写入的 g 成为 c 的父",
          "n224g" in _par1.get("n224c", []), str(_par1)[:160], live=True)

    # ================= ⑥ 源断言 + floor =================
    print("\n【⑥】源断言（单点接线在位）")
    _s_mdcg = _read_src("mdcg.py")
    _sig = _src_window(_s_mdcg, "def _index_signature", "def _maybe_reload_index")
    check("6a _index_signature 计入口径覆盖分片日志（不只 stat 快照）",
          "index_log_dir" in _sig and "listdir" in _sig, _sig[-200:])
    _fl = _src_window(_s_mdcg, "def flush", "def close")
    check("6b flush 登记本进程分片（自身写入不计入代际签名）",
          "_own_shard" in _fl, "_own_shard missing")
    _ml = _src_window(_s_mdcg, "def _maybe_reload_index", "def _dir_fingerprint")
    check("6c 重载路径失效 chain/subgraph/trust 三派生缓存",
          "chain.invalidate_cache" in _ml and "subgraph.invalidate_cache" in _ml
          and "trust.invalidate_cache" in _ml, _ml[-200:])
    _s_mdcos = _read_src("mdcos.py")
    _get = _src_window(_s_mdcos, "def get(self, node_id", "def search_rrf")
    check("6d MdCGSecure.get 以盘上 frontmatter 复核可见性（陈旧条目不作准）",
          'fm.get("sensitivity")' in _get and "_readable" in _get, _get[-200:])
    _s_prot = _read_src("protect.py")
    _pfm = _src_window(_s_prot, "def _fm", "def is_protected")
    check("6e protect._fm 值为 None 时必须复核文件（受保护层，单点键集）",
          "_GATE_UNKNOWN_KEYS" in _pfm, _pfm[-220:])
    _pent = _src_window(_s_prot, "def _entry", "def _fm")
    check("6f protect._entry 判定前代际探活（写/删/搬迁三面同闸）",
          "_maybe_reload_index" in _pent, _pent[-160:])
    _mk = _src_window(_s_prot, "def mark", "def stats")
    check("6g protect.mark 改动进索引写日志（_dirty 标脏 + flush）",
          "_dirty[node_id] = e" in _mk, _mk[-200:])
    _oc = _src_window(_s_mdcos, "def _open_content", "# ---------- 索引")
    check("6h 解密出口 _open_content 前置读可见性闸（全文面单点，含 search 水合）",
          "read_denied" in _oc and "_readable" in _oc, _oc[-200:])
    print("  [INFO] live 断言数 = %d（floor=%d）" % (LIVE, LIVE_FLOOR))
    check("6i live 断言数不低于 floor（防空转绿）", LIVE >= LIVE_FLOOR,
          "live=%d" % LIVE)

    print("\n" + "=" * 64)
    print("PASS=%d  FAIL=%d  LIVE=%d" % (PASS, FAIL, LIVE))
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        _close_all()
        time.sleep(0.05)
    sys.exit(rc)
