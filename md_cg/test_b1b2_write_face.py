# -*- coding: utf-8 -*-
"""B1/B2 写面守卫：自动节点 id 唯一性 + 密级落盘透传与 fail-closed。

对应缺陷：
  B1 自动节点 id 撞毫秒静默覆盖（原实现 `"mem_" + 毫秒` 两处各写一份；
     同毫秒自动写入铸出同一 id → `add` 的 upsert 语义静默顶替前者，
     返回 committed=true、正文全库 0 命中，无任何失败信号）；
  B2 密级静默降级（writepipe 落盘实参表缺 sensitivity，而审核闸 payload
     带着它 → 声明 private 的正文以明文 + fm internal 落盘）。

断言清单（每条对一个可定点变异的判据）：
  B1-a 形态：`mem_<毫秒>_<6位hex>`，同时过 `_NODE_ID_RE` 与 `linkref.ID_SHAPE_RE`
  B1-b 加熵：同毫秒 500 次铸造零重复
  B1-c 存在性闸：撞既有节点即换随机段重生成，既有节点正文未被顶替
  B1-d 有界 fail-closed：连续撞满 attempts 次 → RuntimeError
  B1-e 端到端：同毫秒两笔自动写入 → 两个 id、两笔正文各自可读回
  B1-f 显式 node_id 的「同 id 即改写」upsert 语义原样保留（要求④）
  B1-g 单点：三处调用面零裸毫秒铸造字面量且都委托 `mint_auto_id`；
       全仓 `mint_auto_id` 只有一份定义
  B1-h `linkref_backfill.do_propose` 的提案 id 走同一铸造点
  B2-a writepipe 链尾落盘面透传 sensitivity（private → fm private + 密文）
  B2-b `mdcg_remember` 非 gated 分支透传
  B2-c gated 分支（mcp_server 与 writepipe 两条）透传
  B2-d 密级一致性闸判据（声明≠落盘 / 加密级当明文）与放行面
  B2-e 端到端 fail-closed：闸命中时**未落盘**（盘上无该文件）

沙箱（硬约束 1）：一切读写都在 tempfile.mkdtemp 内——aux（密钥/身份）、
认知图根、主密钥全部指到沙箱，**绝不碰在役库**。
"""
import json
import os
import re
import shutil
import tempfile

# 沙箱必须在**任何** md_cg 子模块 import 之前设好：`crypto.MASTER_FILE` 在
# 模块导入时求值（`aux_root()`），晚设会让密钥面指回 ~/.mcg。
_SANDBOX = tempfile.mkdtemp(prefix="b1b2_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SANDBOX
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_POLICY_FILE", None)

from . import crypto, linkref, mdcg, mcp_server, nodefile, writepipe  # noqa: E402
from .mdcos import MdCGSecure                                 # noqa: E402
from .security import Principal                               # noqa: E402

_KEK = os.urandom(32)
_OK = 0
_BAD = []


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _mk_cg(tag, clearance="secret", role="designer"):
    root = os.path.join(_SANDBOX, "lib_" + tag)
    p = Principal(tenant="t1", actor="alice", role=role, clearance=clearance,
                  can_write=True, can_admin=True)
    return MdCGSecure(root, principal=p, master_key=_KEK)


def _policy(mark):
    path = os.path.join(_SANDBOX, "policy_%s.json" % mark)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"forbidden": [], "required": [mark]}, f)
    os.environ["MDCG_POLICY_FILE"] = path
    return path


def _raw(cg, nid):
    """读节点盘上原文（不经解密），返回 (text, fm, content)。"""
    e = cg.index["nodes"][nid]
    with open(cg._node_disk_path(e), encoding="utf-8") as f:
        text = f.read()
    fm, content = nodefile.loads(text)
    return text, fm, content


class _FakeTime:
    """固定毫秒的时间替身（只覆写 time()，其余属性委托真实模块）。"""

    def __init__(self, ts):
        self._ts = ts

    def time(self):
        return self._ts

    def __getattr__(self, k):
        import time as _t
        return getattr(_t, k)


def main():
    print("\n[B1] 自动 id 唯一性（唯一铸造点）")

    # ---- B1-a 形态 ----
    nids = [mdcg.mint_auto_id(None) for _ in range(5)]
    _check("B1-a1 形态 mem_<毫秒>_<6位hex>",
           all(re.match(r"^mem_\d+_[0-9a-f]{6}$", n) for n in nids), nids[:2])
    _check("B1-a2 过引擎 id 白名单 _NODE_ID_RE（含无 ..）",
           all(mdcg._NODE_ID_RE.match(n) and ".." not in n
               for n in nids), nids[:2])
    _check("B1-a3 过链引用形态 ID_SHAPE_RE（整串被当一个 id）",
           all(linkref.ID_SHAPE_RE.match(n) for n in nids), nids[:2])
    _check("B1-a4 长度 ≤128",
           all(len(n) <= 128 for n in nids), [len(n) for n in nids])

    # ---- B1-b 加熵：同毫秒零重复 ----
    # 6 位 hex = 16.7M 值域，500 次采样存在约 0.7% 的**生日碰撞**（理论允许），
    # 故断言留 1 次余量——「无加熵」的变异下 unique 恒为 1，仍必红。
    same_ms = {mdcg.mint_auto_id(None, now_ms=1790743939104)
               for _ in range(500)}
    _check("B1-b1 同毫秒 500 次铸造几乎零重复", len(same_ms) >= 499,
           "unique=%d" % len(same_ms))

    # ---- B1-c 存在性闸：撞车换随机段，既有节点不被顶替 ----
    cg = _mk_cg("b1c")
    ms = 1790743939104
    taken = "mem_%d_111111" % ms
    cg.add(taken, "既有节点正文（不得被顶替）", layer="knowledge")
    seq = iter(["111111", "222222", "333333", "444444", "555555"])
    _orig_hex = mdcg.secrets.token_hex
    try:
        mdcg.secrets.token_hex = lambda n=3: next(seq)
        got = mdcg.mint_auto_id(cg, now_ms=ms)
    finally:
        mdcg.secrets.token_hex = _orig_hex
    _check("B1-c1 撞既有 id → 换随机段重生成（返回第二个）",
           got == "mem_%d_222222" % ms, got)
    got_body = (cg.get(taken) or {}).get("content") or ""
    _check("B1-c2 既有节点正文未被顶替", "既有节点正文" in got_body, got_body[:40])

    # ---- B1-d 有界 fail-closed ----
    ms_d = 1790743939200
    cg.add("mem_%d_aaaaaa" % ms_d, "占位节点", layer="knowledge")
    _orig_hex = mdcg.secrets.token_hex
    try:
        mdcg.secrets.token_hex = lambda n=3: "aaaaaa"
        try:
            mdcg.mint_auto_id(cg, now_ms=ms_d)
            _check("B1-d1 连续撞满 → RuntimeError（fail-closed）", False,
                   "未抛异常")
        except RuntimeError as exc:
            _check("B1-d1 连续撞满 → RuntimeError（fail-closed）",
                   "fail-closed" in str(exc) and "绝不静默顶替" in str(exc),
                   str(exc)[:80])
        except Exception as exc:                          # noqa: BLE001
            _check("B1-d1 连续撞满 → RuntimeError（fail-closed）", False,
                   "抛了 %r" % exc)
    finally:
        mdcg.secrets.token_hex = _orig_hex

    # ---- B1-e 端到端：同毫秒两笔自动写入互不顶替 ----
    _policy("B1MARK")
    cg_e = _mk_cg("b1e")
    pipe = writepipe.install_default_gates(writepipe.WritePipeline())
    fixed = _FakeTime(1790743939.104)
    _orig_time = mdcg.time
    o1 = o2 = None
    err_e = None
    try:
        mdcg.time = fixed
        try:
            o1 = pipe.execute(cg_e, {"content_kind": "text",
                                     "content": "B1MARK 第一笔自动写入"})
            o2 = pipe.execute(cg_e, {"content_kind": "text",
                                     "content": "B1MARK 第二笔自动写入"})
        except Exception as exc:                          # noqa: BLE001
            err_e = "%s: %s" % (type(exc).__name__, str(exc)[:60])
    finally:
        mdcg.time = _orig_time
    o1, o2 = o1 or {}, o2 or {}
    _check("B1-e1 两笔自动写入 id 不同",
           o1.get("id") and o2.get("id") and o1["id"] != o2["id"],
           "%r vs %r %s" % (o1.get("id"), o2.get("id"), err_e or ""))
    b1 = (cg_e.get(o1.get("id")) or {}).get("content") or ""
    b2 = (cg_e.get(o2.get("id")) or {}).get("content") or ""
    _check("B1-e2 第一笔正文未被第二笔顶替（两笔都在）",
           "第一笔" in b1 and "第二笔" in b2, (b1[:20], b2[:20]))

    # ---- B1-f 显式 node_id 的「同 id 即改写」语义原样保留（要求④）----
    o1 = pipe.execute(cg_e, {"node_id": "explicit_upsert_x",
                             "content_kind": "text",
                             "content": "B1MARK 显式 id 第一次"})
    o2 = pipe.execute(cg_e, {"node_id": "explicit_upsert_x",
                             "content_kind": "text",
                             "content": "B1MARK 显式 id 第二次改写"})
    body = (cg_e.get("explicit_upsert_x") or {}).get("content") or ""
    _check("B1-f1 显式 id 两次返回同 id", o1.get("id") == o2.get("id")
           == "explicit_upsert_x", "%r %r" % (o1.get("id"), o2.get("id")))
    _check("B1-f2 显式 id 为改写（正文=第二次）",
           "第二次改写" in body and "第一次" not in body, body[:40])
    _check("B1-f3 显式 id 未被换成自动 id（索引键仍在）",
           "explicit_upsert_x" in cg_e.index["nodes"])

    # ---- B1-g 单点：零裸毫秒铸造字面量 + 一份定义 ----
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = {"md_cg/writepipe.py": os.path.join(repo, "md_cg", "writepipe.py"),
             "md_cg/mcp_server.py": os.path.join(repo, "md_cg", "mcp_server.py"),
             "scripts/linkref_backfill.py": os.path.join(
                 repo, "scripts", "linkref_backfill.py")}
    bare_ms = re.compile(r'"mem_" \+ str\(int\(|"mem_%d"')
    bad = []
    for name, path in files.items():
        src = open(path, encoding="utf-8").read()
        if bare_ms.search(src):
            bad.append(name)
        if "mint_auto_id" not in src:
            bad.append(name + "(未委托)")
    _check("B1-g1 三处调用面零裸毫秒铸造且都委托 mint_auto_id", not bad, bad)
    src_mdcg = open(os.path.join(repo, "md_cg", "mdcg.py"),
                    encoding="utf-8").read()
    hits = 0
    for name, path in files.items():
        hits += open(path, encoding="utf-8").read().count("def mint_auto_id(")
    hits += src_mdcg.count("def mint_auto_id(")
    _check("B1-g2 mint_auto_id 只有一份定义", hits == 1, "def 出现 %d 次" % hits)

    # ---- B1-h linkref_backfill 的提案 id 走同一铸造点 ----
    import importlib.util
    lp = os.path.join(repo, "scripts", "linkref_backfill.py")
    spec = importlib.util.spec_from_file_location("lrb_guard", lp)
    lrb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lrb)
    cg_h = _mk_cg("b1h")
    seen_h = {}
    orig_pp = cg_h.propose

    def _spy_propose(node_id, content, **kw):
        seen_h["node_id"] = node_id
        return "pid_guard_probe"

    try:
        cg_h.propose = _spy_propose
        lrb.do_propose(cg_h, [], {"nodes_with_gap": 0, "pairs": 0,
                                  "nodes_total": 0}, None)
    finally:
        cg_h.propose = orig_pp
    _check("B1-h1 提案 node_id 走唯一铸造点（带熵形态）",
           bool(re.match(r"^mem_\d+_[0-9a-f]{6}$", str(seen_h.get("node_id")))),
           repr(seen_h.get("node_id")))

    print("\n[B2] 密级落盘透传 + fail-closed 闸")

    # ---- B2-a writepipe 链尾落盘面透传 ----
    _policy("B2MARK")
    cg_a = _mk_cg("b2a")
    secret_text = "B2MARK 私有正文：银行卡尾号 8888，仅本人可见"
    out = pipe.execute(cg_a, {"content_kind": "text", "content": secret_text,
                              "sensitivity": "private"})
    nid_a = out.get("id") or ""
    _check("B2-a0 写入 committed", out.get("committed") is True, repr(out)[:120])
    if nid_a in cg_a.index["nodes"]:
        raw, fm, content = _raw(cg_a, nid_a)
        _check("B2-a1 落盘 fm sensitivity == 声明 private",
               fm.get("sensitivity") == "private", repr(fm.get("sensitivity")))
        _check("B2-a2 落盘正文为密文",
               crypto.is_encrypted(content), str(content)[:40])
        _check("B2-a3 落盘文件不含明文", secret_text not in raw)
    else:
        _check("B2-a1 落盘 fm sensitivity == 声明 private", False, "未落盘")

    # ---- B2-b mdcg_remember 非 gated 分支 ----
    cg_b = _mk_cg("b2b")
    res = mcp_server._dispatch(cg_b, "mdcg_remember",
                               {"content": "B2MARK remember 私有正文",
                                "sensitivity": "private",
                                "content_kind": "text"})
    nid_b = res.get("id") or ""
    _check("B2-b0 remember 返回 ok", res.get("ok") is True, repr(res)[:120])
    if nid_b in cg_b.index["nodes"]:
        raw, fm, content = _raw(cg_b, nid_b)
        _check("B2-b1 remember 落盘 fm sensitivity == private",
               fm.get("sensitivity") == "private", repr(fm.get("sensitivity")))
        _check("B2-b2 remember 落盘正文为密文",
               crypto.is_encrypted(content), str(content)[:40])
    else:
        _check("B2-b1 remember 落盘 fm sensitivity == private", False,
               "未落盘 id=%r" % nid_b)

    # ---- B2-c gated 分支透传（mcp_server 与 writepipe 两条）----
    seen = {}

    def _spy(node_id, content, layer="contextual", **kw):
        seen.update(kw)
        return {"verdict": "DROP", "node_id": node_id, "gate": {}}

    cg_c = _mk_cg("b2c")
    orig_rg = cg_c.remember_gated
    try:
        cg_c.remember_gated = _spy
        mcp_server._dispatch(cg_c, "mdcg_remember",
                             {"content": "B2MARK gated mcp 分支",
                              "gated": True, "sensitivity": "private",
                              "content_kind": "text"})
        _check("B2-c1 mdcg_remember gated 分支透传 sensitivity",
               seen.get("sensitivity") == "private",
               repr(seen.get("sensitivity")))
        seen.clear()
        pipe.execute(cg_c, {"content": "B2MARK gated writepipe 分支",
                            "gated": True, "sensitivity": "private",
                            "content_kind": "text", "layer": "contextual"})
        _check("B2-c2 writepipe gated 闸透传 sensitivity",
               seen.get("sensitivity") == "private",
               repr(seen.get("sensitivity")))
    finally:
        cg_c.remember_gated = orig_rg

    # ---- B2-d 闸判据（声明≠落盘 / 加密级当明文 / 放行面）----
    dek = crypto.provision_dek(_SANDBOX, _KEK, "t1", "alice")
    sealed = crypto.seal_node("payload", dek, "n1", "t1", "alice")
    try:
        mdcg._check_sensitivity_landing("n1", "internal", "private", "明文")
        _check("B2-d1 声明 private 而落 internal → ValueError", False, "未抛")
    except ValueError as exc:
        msg = str(exc)
        _check("B2-d1 声明 private 而落 internal → ValueError",
               "声明值='private'" in msg and "sensitivity='internal'" in msg
               and "未写盘" in msg, msg[:100])
    try:
        mdcg._check_sensitivity_landing("n1", "private", "private", "明文",
                                        True)
        _check("B2-d2 有密封能力 + 加密级密级却明文 → ValueError", False,
               "未抛")
    except ValueError as exc:
        _check("B2-d2 有密封能力 + 加密级密级却明文 → ValueError",
               "明文落盘" in str(exc), str(exc)[:100])
    try:
        mdcg._check_sensitivity_landing("n1", "secret", None, "明文", True)
        _check("B2-d3 有密封能力 + 未声明但 fm 落 secret + 明文 → ValueError",
               False, "未抛")
    except ValueError:
        _check("B2-d3 有密封能力 + 未声明但 fm 落 secret + 明文 → ValueError",
               True)
    try:
        mdcg._check_sensitivity_landing("n1", "private", "private", sealed,
                                        True)
        mdcg._check_sensitivity_landing("n1", "internal", None, "明文", True)
        _check("B2-d4 合规面放行（密文 private / 明文 internal）", True)
    except Exception as exc:                              # noqa: BLE001
        _check("B2-d4 合规面放行（密文 private / 明文 internal）", False,
               repr(exc))
    try:
        mdcg._check_sensitivity_landing("n1", "private", None, "明文", False)
        _check("B2-d5 无密封能力实例（has_sealer=False）→ 放行（既有语义）",
               True)
    except Exception as exc:                              # noqa: BLE001
        _check("B2-d5 无密封能力实例（has_sealer=False）→ 放行（既有语义）",
               False, repr(exc))

    # ---- B2-e 端到端 fail-closed 且**未落盘**（密封点被绕过的回归）----
    class _LeakySecure(MdCGSecure):
        """替身：覆写了密封钩子（＝有密封能力）却故意不密封。

        模拟「_write_node 的密封点被绕过/失效」的回归——闸必须抓住它。
        """

        def _seal_content(self, node_id, content, sensitivity=None):
            return content

    root_e = os.path.join(_SANDBOX, "lib_b2e")
    leak = _LeakySecure(root_e, principal=Principal(
        tenant="t1", actor="alice", role="designer", clearance="secret",
        can_write=True, can_admin=True), master_key=_KEK)
    try:
        leak.add("leaky_priv_probe", "明文却声明 private", sensitivity="private")
        _check("B2-e1 密封点被绕过的实例 → ValueError", False, "未抛")
    except ValueError as exc:
        _check("B2-e1 密封点被绕过的实例 → ValueError",
               "明文落盘" in str(exc) or "密级" in str(exc), str(exc)[:100])
    _check("B2-e2 闸命中时未落盘（盘上无该文件）",
           not os.path.isfile(os.path.join(root_e, "knowledge", "orphan",
                                           "leaky_priv_probe.md")))

    # ---- B2-f 无密封能力的实例落 private 明文 → 放行（既有语义，不得误扩）----
    # 钉住三条既有回归钉死的场景：docindex 私有目录文档 / identity_attribution
    # 的 legacy 无密钥私有条目 / hive_ingest 的 MdCGOS 事件流——它们用基类实例
    # 落 `private` 明文（fm 如实记 private、读面按密级隔离），不是「静默降级」。
    root_f = os.path.join(_SANDBOX, "lib_b2f")
    base = mdcg.MdCG(root_f, autoflush=1)
    err_f = None
    try:
        base.add("legacy_priv_probe", "无密封能力的库落 private 明文",
                 layer="knowledge", sensitivity="private")
    except Exception as exc:                              # noqa: BLE001
        err_f = "%s: %s" % (type(exc).__name__, str(exc)[:80])
    if err_f is None:
        raw_f, fm_f, content_f = _raw(base, "legacy_priv_probe")
        _check("B2-f1 无密封能力实例：private 明文落盘放行（不误伤）",
               fm_f.get("sensitivity") == "private"
               and not crypto.is_encrypted(content_f),
               repr(fm_f.get("sensitivity")))
    else:
        _check("B2-f1 无密封能力实例：private 明文落盘放行（不误伤）", False,
               err_f)

    print("\n==== B1/B2 写面守卫：%d 通过%s ====" % (
        _OK, "，%d 失败：%s" % (len(_BAD), "; ".join(_BAD)) if _BAD else ""))
    return 1 if _BAD else 0


if __name__ == "__main__":
    import sys
    try:
        rc = main()
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
        os.environ.pop("MDCG_POLICY_FILE", None)
    sys.exit(rc)
