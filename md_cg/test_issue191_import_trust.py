# -*- coding: utf-8 -*-
"""issue #191 守卫：证据包导入的三处收口（层/重要度夹紧 · 旧包重放 · 同名本地节点）。

现象（9c5d946a；本项目在 HEAD 上复现读数与报告逐字一致）：
  A 每个条目的 layer 与 importance 原样交给 identity.observe(override=True)——
    对端可让条目落进 anchor/self 层、或把 importance 设到 0.7 以上，落盘即不可遗忘；
  B 导入不看包版本——旧包重放把新证据覆写回旧内容，属主删除后重放还能复活；
  C override=True 无条件——本根里恰好同名的本地节点也会被对端覆写。

本守卫钉四面 + 一面不回归：
  A 层白名单 + 重要度上限（anchor→knowledge、1.0→0.5，clamped 计数）；
  B created_at 版本台账（旧包 / 同版本重放一律跳过并计 replayed）；
  C 同名本地节点不覆写（本来源自己的 xnode 仍可被新版更新）；
  D created_at 非法整包拒收；缺省按 0（只能新建、不能覆写）。
  K 合法包照常导入/归档、contextual 不被误伤、#258 密级 fail-closed 不回归。

用法：
    python -X utf8 -m md_cg.test_issue191_import_trust
    python -X utf8 -m md_cg.test_issue191_import_trust --mutate=<名>
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SRC = os.path.join(_HERE, "evidence.py")

_FAILS = []


def _check(name, ok, detail=""):
    if not ok:
        _FAILS.append(name)
    print("  %s %s%s" % ("ok  " if ok else "FAIL", name,
                          "" if ok else "  · " + str(detail)[:170]))


def _ccg(title, body):
    return ("# 功能名：%s" + chr(10) + "# 生效条件：c" + chr(10) +
            "# 子功能：s" + chr(10) + "# 执行：%s" + chr(10) +
            "# 验证方式：test" + chr(10) + "# 不适用条件：n" + chr(10)) % (title, body)


class _Env:
    """一个隔离库 + 一个「受信对端」可签的导入会话。"""

    def __init__(self):
        self.d = tempfile.mkdtemp(prefix="i191_")
        self.env = {
            "MDCG_ROOT": self.d + "/brain",
            "MDCG_STATE_ROOT": self.d + "/state",
            "MDCG_AUX_ROOT": self.d + "/auxstore",
            "MDCG_DATA_ROOT": self.d + "/data",
            "MDCG_EXPORT_ROOT": self.d,
            "MDCG_TOKEN_FILE": self.d + "/auxstore/tokens.json",
            "MDCG_SIGNERS_FILE": self.d + "/auxstore/_signers.json",
            "MDCG_SIGNER_KEY_FILE": self.d + "/auxstore/_signer.key",
            "MDCG_SWARM_DIR": self.d + "/swarm",
            "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"}
        self._envpatch = patch.dict(os.environ, self.env)
        self._envpatch.start()
        self._err = contextlib.redirect_stderr(io.StringIO())
        self._err.__enter__()
        from md_cg import evidence as ev
        from md_cg import signer
        from md_cg import tokens
        from md_cg.mdcos import MdCGSecure
        from md_cg.mcp_server import call_tool
        self.ev, self.signer, self.call_tool = ev, signer, call_tool
        # 受信对端：本节点与对端共用 hmac-local 密钥（同 AUX 根）
        signer.set_policy(ev.SUBSYSTEM, signer="hmac-local",
                          sign_on=["handshake", "evidence"],
                          require_peer_signature=True, on_verify_fail="reject")
        tf = self.env["MDCG_TOKEN_FILE"]
        tok = tokens.issue("designer", actor="guard191", path=tf)["token"]
        self.cg = MdCGSecure(self.env["MDCG_ROOT"],
                             principal=tokens.verify_token(tok, path=tf),
                             autoflush=1)

    def pack(self, pid, items, created=None, tamper=None):
        p = {"schema": 1, "kind": self.ev.KIND, "from_node": "peer-a",
             "from_root": "", "theory": [],
             "created_at": time.time() if created is None else created,
             "subjects": [], "items": items, "pack_id": pid}
        if tamper:
            p.update(tamper)
        s = self.signer.sign_for(self.ev.SUBSYSTEM, self.ev._pack_payload(p),
                                 action=self.ev.SIGN_ACTION)
        p["sig"] = {"signer": s.get("signer"), "signature": s.get("signature"),
                    "signed": s.get("signed")}
        f = os.path.join(self.d, pid + ".json")
        io.open(f, "w", encoding="utf-8").write(json.dumps(p, ensure_ascii=False))
        return f

    def imp(self, f):
        return self.call_tool(self.cg, "cg",
                              {"op": "link", "action": "import", "path": f})

    def get(self, nid):
        return self.call_tool(self.cg, "mdcg_get", {"node_id": nid}) or {}

    def fm(self, nid):
        return self.get(nid).get("frontmatter") or {}

    def content(self, nid):
        return self.get(nid).get("content") or ""

    def close(self):
        try:
            self.cg.close()
        except Exception:
            pass
        self._err.__exit__(None, None, None)
        self._envpatch.stop()


def case_a():
    e = _Env()
    try:
        f = e.pack("pA", [
            {"node_id": "o1", "subject": "user:owner", "layer": "anchor",
             "importance": 1.0, "sensitivity": "internal", "text": "对端声明一"},
            {"node_id": "o2", "subject": "user:owner", "layer": "knowledge",
             "importance": 1.0, "sensitivity": "internal", "text": "对端声明二"}])
        r = e.imp(f)
        _check("A1 anchor 层被改落 knowledge（对端不得自选受保护层）",
               e.fm("xnode_peer-a_o1").get("layer") == "knowledge",
               e.fm("xnode_peer-a_o1").get("layer"))
        _check("A2 importance=1.0 被夹到 0.5（低于 AUTO_PROTECT 0.70）",
               e.fm("xnode_peer-a_o2").get("importance") == 0.5,
               e.fm("xnode_peer-a_o2").get("importance"))
        _check("A3 clamped 计数=3（o1 层+分、o2 分）", r.get("clamped") == 3,
               r.get("clamped"))
        _check("A4 imported=2 且 skipped=0",
               r.get("imported") == 2 and r.get("skipped") == 0, r)
        try:
            rf = e.call_tool(e.cg, "mdcg_forget",
                             {"node_id": "xnode_peer-a_o2", "reason": "清理对端声明"})
            err = ""
        except Exception as ex:   # 进程内直调不像 stdio 那样包成 {"error": ...}
            rf, err = {}, "%s: %s" % (type(ex).__name__, ex)
        _check("A5 属主遗忘不再 ProtectionError（分已低于 0.70）",
               not err and (rf or {}).get("ok") is True, err or rf)
    finally:
        e.close()


def case_b():
    e = _Env()
    try:
        t0 = time.time() - 100
        v1 = e.pack("v1", [{"node_id": "bob", "subject": "user:bob",
                            "sensitivity": "internal",
                            "text": "bob 可信，开通生产权限"}], created=t0)
        v2 = e.pack("v2", [{"node_id": "bob", "subject": "user:bob",
                            "sensitivity": "internal",
                            "text": "bob 账号已失陷，撤销生产权限"}], created=t0 + 10)
        e.imp(v2)
        _check("B1 新包写入生效", "失陷" in e.content("xnode_peer-a_bob"),
               e.content("xnode_peer-a_bob"))
        r = e.imp(v1)
        _check("B2 旧包被跳过并计 replayed=1", r.get("replayed") == 1, r.get("replayed"))
        _check("B3 旧包 imported=0", r.get("imported") == 0, r.get("imported"))
        _check("B4 新证据未被回滚（旧包重放不回滚）",
               "失陷" in e.content("xnode_peer-a_bob"),
               e.content("xnode_peer-a_bob"))
        r2 = e.imp(v2)
        _check("B5 同 created_at 重放也跳过（<= 即视为已见）",
               r2.get("replayed") == 1, r2.get("replayed"))
        seen_p = os.path.join(e.env["MDCG_ROOT"], e.ev.SEEN_FILE)
        _check("B6 版本台账落盘（含该 xnode 的记录）",
               os.path.exists(seen_p)
               and "xnode_peer-a_bob" in io.open(seen_p, encoding="utf-8").read(),
               seen_p)
    finally:
        e.close()


def case_c():
    e = _Env()
    try:
        e.cg.add("xnode_peer-a_local", _ccg("本地件", "本根自己写的"),
                 layer="knowledge")
        f = e.pack("pC", [{"node_id": "local", "subject": "user:owner",
                           "sensitivity": "internal", "text": "对端改写的正文"}])
        r = e.imp(f)
        _check("C1 同名本地节点被跳过（imported=0 / skipped=1）",
               r.get("imported") == 0 and r.get("skipped") == 1, r)
        _check("C2 本地正文未被覆写",
               "本根自己写的" in e.content("xnode_peer-a_local"),
               e.content("xnode_peer-a_local")[:80])
        _check("C2b 跳过理由点明同名本地节点",
               any("同名本地节点" in x for x in (r.get("skipped_reasons") or [])),
               r.get("skipped_reasons"))
        e.imp(e.pack("pC2", [{"node_id": "own", "subject": "user:owner",
                              "sensitivity": "internal", "text": "第一版"}]))
        e.imp(e.pack("pC3", [{"node_id": "own", "subject": "user:owner",
                              "sensitivity": "internal", "text": "第二版"}],
                     created=time.time() + 50))
        _check("C3 本来源自己的 xnode 仍可被新版更新（未误伤正常更新）",
               "第二版" in e.content("xnode_peer-a_own"),
               e.content("xnode_peer-a_own")[:80])
    finally:
        e.close()


def case_d():
    e = _Env()
    try:
        for bad in ("123", True, [1, 2], {"a": 1}, float("nan"), float("inf")):
            try:
                f = e.pack("pD", [{"node_id": "z", "subject": "user:z",
                                   "sensitivity": "internal", "text": "x"}],
                           tamper={"created_at": bad})
            except Exception as ex:
                print("  SKIP created_at=%r（签名阶段即拒：%s）" % (bad, ex))
                continue
            r = e.imp(f)
            _check("D created_at=%r ⇒ 整包拒收" % (bad,),
                   r.get("ok") is False and r.get("rejected") is True, r)
        # 缺省（无 created_at）按 0：可新建、不可覆写
        f = e.pack("pD0", [{"node_id": "q", "subject": "user:q",
                            "sensitivity": "internal", "text": "第一版"}])
        p = json.load(io.open(f, encoding="utf-8"))
        p.pop("created_at")
        s = e.signer.sign_for(e.ev.SUBSYSTEM, e.ev._pack_payload(p),
                              action=e.ev.SIGN_ACTION)
        p["sig"] = {"signer": s.get("signer"), "signature": s.get("signature"),
                    "signed": s.get("signed")}
        io.open(f, "w", encoding="utf-8").write(json.dumps(p, ensure_ascii=False))
        _check("D5 无 created_at 的包可新建（created 按 0）",
               e.imp(f).get("imported") == 1, e.imp(f))
    finally:
        e.close()


def case_k():
    e = _Env()
    try:
        r = e.imp(e.pack("k1", [{"node_id": "n1", "subject": "user:a",
                                "layer": "knowledge", "importance": 0.3,
                                "sensitivity": "internal", "text": "正文一"}]))
        _check("K1 合法包照常导入，clamped=0 / replayed=0",
               r.get("imported") == 1 and r.get("clamped") == 0
               and r.get("replayed") == 0, r)
        fm = e.fm("xnode_peer-a_n1")
        _check("K2 knowledge 层与 0.3 原样保留（白名单内不夹紧）",
               fm.get("layer") == "knowledge" and fm.get("importance") == 0.3, fm)
        e.imp(e.pack("k2", [{"node_id": "n2", "subject": "user:a",
                            "layer": "contextual", "sensitivity": "internal",
                            "text": "正文二"}]))
        _check("K3 contextual 在白名单内，不被误伤",
               e.fm("xnode_peer-a_n2").get("layer") == "contextual",
               e.fm("xnode_peer-a_n2").get("layer"))
        r3 = e.imp(e.pack("k3", [{"node_id": "n3", "subject": "user:a",
                                 "sensitivity": "internal", "text": "正文三"}]))
        fm3 = e.fm("xnode_peer-a_n3")
        _check("K4 缺 layer/importance 沿用缺省，且**不计**夹紧",
               fm3.get("layer") == "knowledge" and fm3.get("importance") == 0.5
               and r3.get("clamped") == 0, (fm3, r3.get("clamped")))
        r4 = e.imp(e.pack("k4", [{"node_id": "n4", "subject": "user:a",
                                 "text": "缺 sensitivity"}]))
        _check("K5 缺 sensitivity 仍 fail-closed（#258 不回归）",
               r4.get("imported") == 0 and r4.get("skipped") == 1, r4)
        _check("K6 归档照常落盘", bool(r.get("archived")), r.get("archived"))
        _check("K7 返回体保留 #258 的 skipped_reasons / archive_skipped 键",
               "skipped_reasons" in r and "archive_skipped" in r, sorted(r))
    finally:
        e.close()


def main():
    print("=" * 68)
    print("issue #191 守卫：证据包导入的三处收口")
    print("=" * 68)
    for title, fn in (("A 层白名单 + 重要度夹紧", case_a),
                      ("B 旧包重放不得回滚", case_b),
                      ("C 同名本地节点不得被覆写", case_c),
                      ("D created_at 非法整包拒收", case_d),
                      ("K 不回归面", case_k)):
        print("[%s]" % title)
        fn()
        print()
    print("==== #191 结果：%d 失败 ====" % len(_FAILS))
    if _FAILS:
        print("失败项：" + " ｜ ".join(_FAILS))
    return 1 if _FAILS else 0


# ---------------------------------------------------------------- 变异
# 每条变异都让**指定**用例转红；只断言「变红了」而不指定红项，会让
# 「恰好因为别的原因变红」蒙混过关。
_MUT = [
    ("V1 层不夹紧（回到对端自选层 = 本件病象 A）",
     ["            layer, c_layer = _import_layer(it.get(\"layer\"))"],
     ["            layer, c_layer = (it.get(\"layer\") or \"knowledge\"), 0"],
     ("A1", "A3")),
    ("V2 重要度不夹紧（回到原值落盘 = 本件病象 A）",
     ["            imp, c_imp = _import_importance(it.get(\"importance\"))"],
     ["            imp, c_imp = (0.5 if it.get(\"importance\") is None",
      "                           else it.get(\"importance\")), 0"],
     ("A2", "A3")),
    ("V3 去掉重放判据（回到旧包覆写 = 本件病象 B）",
     ["            if (isinstance(last, (int, float)) and not isinstance(last, bool)",
      "                    and created <= last):"],
     ["            if False:"],
     ("B2", "B3")),
    ("V4 去掉同名本地节点守卫（= 本件病象 C）",
     ["            if prev is not None and TAG_XNODE not in set(prev.get(\"tags\") or []):"],
     ["            if False:"],
     ("C1", "C2")),
    ("V5 created_at 非法不拒收（回落 0）",
     ["        return _note_reject(pack, f\"证据包 created_at 非法：{created!r}\", swarm=swarm)"],
     ["        created = 0.0"],
     ("D ",)),
]


def _mutate(name):
    hits = [m for m in _MUT if m[0].startswith(name) or m[0].split()[0] == name]
    if not hits:
        print("未知变异名：%s" % name)
        print("可用：" + " ｜ ".join(m[0].split()[0] for m in _MUT))
        return 2
    label, old_lines, new_lines, exp_red = hits[0]
    orig = io.open(_SRC, encoding="utf-8", newline="").read()
    # 锚点跨行时必须按**文件实际行尾**拼接：evidence.py 是 CRLF。
    nl = chr(13) + chr(10) if (chr(13) + chr(10)) in orig else chr(10)
    old, new = nl.join(old_lines), nl.join(new_lines)
    if orig.count(old) != 1:
        print("[%s] 锚点不唯一（%d 处）——源码已漂移，请先核对" % (label, orig.count(old)))
        return 2
    mutated = orig.replace(old, new)
    if mutated == orig:
        print("[%s] 变异未改变源码" % label)
        return 2
    # 同尺寸变异落在同一 mtime 秒内时 CPython 会复用旧 .pyc ⇒ 禁写并清缓存
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    cache = os.path.join(_HERE, "__pycache__")
    try:
        io.open(_SRC, "w", encoding="utf-8", newline="").write(mutated)
        if os.path.isdir(cache):
            for f in os.listdir(cache):
                if f.startswith("evidence."):
                    os.remove(os.path.join(cache, f))
        p = subprocess.run([sys.executable, "-X", "utf8", "-m",
                            "md_cg.test_issue191_import_trust"],
                           cwd=_REPO, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env,
                           shell=False, timeout=900)
    finally:
        io.open(_SRC, "w", encoding="utf-8", newline="").write(orig)
        back = io.open(_SRC, encoding="utf-8", newline="").read()
    out = (p.stdout or "") + (p.stderr or "")
    fails = []
    for ln in out.splitlines():
        if ln.strip().startswith("失败项："):
            fails = [x.strip() for x in ln.split("失败项：", 1)[1].split("｜")]
    red = p.returncode != 0 and any(x.startswith(exp_red) for x in fails)
    print("[%s] rc=%s 红项=%s" % (label, p.returncode, fails or "(无)"))
    print("  还原一致=%s ｜ 期望红项 %s ⇒ %s"
          % (back == orig, list(exp_red), "PASS" if red else "FAIL"))
    return 0 if red else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a.startswith("--mutate")]
    if args:
        val = args[0].split("=", 1)[1] if "=" in args[0] else ""
        sys.exit(_mutate(val))
    sys.exit(main())
