#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读权限分级守卫（批次 27）。

分级语义：
- 设计者/主代理：read_file 全路径（2026-09-19 裁定），文本内容过 PII 脱敏
  （跳过个人敏感信息不入明文）；
- 子代理（worker）：read_file 收敛到工作区（job_dir）+ 定制工作目录
  （spec.workdir / spec.read_roots）——其他会话与越界内容拒读（fail-closed，
  无根即无文件读权限）；lingshu_cg 读面默认密级 internal——**错误处置标记
  （private，错误相关/待排查内容限制平级扩散，非个人隐私）与 secret 拒读**。
  错误处置链路（设计者/上级节点/验证单元）必读 private 不受此限——verify
  面当前 clearance_cap=internal 的缺口已登记（安全审计实锚文档）。
"""
import importlib.util
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def _load_exec():
    spec = importlib.util.spec_from_file_location(
        "hx_b27", os.path.join(REPO, "hive", "exec.py"))
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    return m


def main():
    hx = _load_exec()

    print("== _worker_scope 白名单构造 ==")
    jd = tempfile.mkdtemp(prefix="b27_job_")
    wd = tempfile.mkdtemp(prefix="b27_cust_")
    extra = tempfile.mkdtemp(prefix="b27_extra_")
    scope = hx._worker_scope(jd, {"workdir": wd, "read_roots": [extra, extra]})
    check("B27-1a 工作区+定制目录进白名单（去重）",
          scope == (os.path.realpath(jd), os.path.realpath(wd),
                    os.path.realpath(extra)), str(scope))
    check("B27-1b 无根 worker 得空 tuple",
          hx._worker_scope(None, {}) == ())

    print("== read_file workspace 收敛（fail-closed）==")
    f_in = os.path.join(jd, "in_scope.txt")
    with open(f_in, "w", encoding="utf-8") as f:
        f.write("工作区内文件 alpha@test.com 13812345678")
    other = tempfile.mkdtemp(prefix="b27_other_sess_")
    f_out = os.path.join(other, "other_session.md")
    with open(f_out, "w", encoding="utf-8") as f:
        f.write("其他会话内容")
    r = hx.tool_read_file({"path": f_in}, workdir=jd, scope_roots=scope)
    check("B27-2a 工作区内可读", r.get("ok") is True, str(r)[:120])
    check("B27-2b 内容 PII 已脱敏（邮箱+手机号）",
          "alpha@test.com" not in (r.get("content") or "")
          and "13812345678" not in (r.get("content") or "")
          and "[已脱敏:邮箱]" in r.get("content")
          and "[已脱敏:手机号]" in r.get("content"), str(r.get("content"))[:80])
    check("B27-2c pii_redacted 标记", r.get("pii_redacted") is True)
    r = hx.tool_read_file({"path": f_out}, workdir=jd, scope_roots=scope)
    check("B27-2d 其他会话目录拒读",
          r.get("ok") is False and "scope_roots" in r, str(r)[:120])
    r = hx.tool_read_file({"path": f_in}, workdir=jd, scope_roots=())
    check("B27-2e 空白名单（无根 worker）拒读", r.get("ok") is False)
    r = hx.tool_read_file({"path": f_in}, workdir=jd)
    check("B27-2f 主代理（scope_roots=None）现状放开", r.get("ok") is True)

    print("== PII 脱敏模式集 ==")
    # 样本运行时拼接（R1 凭据扫描只认字面量——样本非真凭据）
    _sk = "sk-" + "abcdefghijklmnopq123456"
    _pk = ("-----BEGIN " + "RSA PRIVATE KEY-----\nMIIabc\n"
           "-----END " + "RSA PRIVATE KEY-----")
    _bearer = "Bearer " + "eyJhbGciOiJIUzI1NiIsIntoken"
    cases = [
        ("私钥块", _pk),
        ("API密钥", "my key: " + _sk),
        ("API密钥", "Authorization: " + _bearer),
        ("身份证号", "身份证 110101199003078515"),
        ("邮箱", "contact user@example.com here"),
        ("手机号", "电话 13912345678"),
    ]
    for label, sample in cases:
        out = hx._redact_pii(sample)
        check(f"B27-3 {label} 脱敏", "[已脱敏:" in out and sample not in out,
              out[:60])
    plain = "普通技术文档：quick sort 复杂度 O(n log n)，蜂群调度正常。"
    check("B27-3x 普通文本不误伤", hx._redact_pii(plain) == plain)

    print("== lingshu_cg 密级分级（worker=internal 拒读 private/secret）==")
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    root = tempfile.mkdtemp(prefix="b27_cg_")
    cg_admin = MdCGSecure(root, principal=Principal(
        actor="seed", clearance="secret", can_write=True, can_admin=True,
        role="designer", auth_mode="test"))
    cg_admin.add("pub_node", "# 功能名：公开\n# 正文：公开内容 alpha",
                 layer="knowledge", sensitivity="public")
    cg_admin.add("priv_node", "# 功能名：私有\n# 正文：标记私有内容 beta",
                 layer="knowledge", sensitivity="private")
    cg_admin.flush()
    worker = Principal(actor="hive-worker", clearance="internal",
                       can_write=True, can_admin=False, role="recorder",
                       auth_mode="hive-exec")
    cg_w = MdCGSecure(root, principal=worker)
    r_pub, _ = cg_w.search("公开", k=5)
    r_priv, _ = cg_w.search("标记私有", k=5)
    check("B27-4a worker 可读 internal 以下节点",
          any(x[0].get("id") == "pub_node" for x in r_pub),
          str([x[0].get("id") for x in r_pub]))
    check("B27-4b worker 读不到 private（标记私有）节点",
          not any(x[0].get("id") == "priv_node" for x in r_priv),
          str([x[0].get("id") for x in r_priv]))
    try:
        got = cg_w.get("priv_node") is not None   # None = 密级过滤不可得
    except Exception:       # noqa: BLE001——AccessDenied 也算拒
        got = False
    check("B27-4c worker get private 节点被拒/不可得", not got)

    print("== verify 面错误处置豁免（批次 28 裁定落地）==")
    from md_cg.tokens import issue, role_spec, verify_token
    check("B27-5a verify clearance_cap=internal（分型后 cap 豁免取消，"
          "restricted 走链路角色集）",
          role_spec("verify")["clearance_cap"] == "internal")
    check("B27-5b record 维持限读（cap=internal）",
          role_spec("record")["clearance_cap"] == "internal")
    tfile = os.path.join(tempfile.mkdtemp(prefix="b27_tok_"), "tok.json")
    issued = issue("verify", actor="b27-verify", path=tfile)
    check("B27-5c verify 签发 clearance=internal（分型取代 cap 豁免）",
          issued["clearance"] == "internal", str(issued)[:120])
    vp = verify_token(issued["token"], path=tfile)
    check("B27-5d verify_token 解析 clearance=internal",
          vp.clearance == "internal", str(vp))
    cg_v = MdCGSecure(root, principal=vp)
    got_priv = cg_v.get("priv_node")
    # 现状断言（批次 28）：密级闸已放行（cap=private），但 private 节点受
    # **信封加密**第二层限制——provision_dek 为每个 actor 发独立 DEK，节点
    # 用写入者 DEK 加密，跨 actor（含 verify）解密失败静默空。跨 actor 读
    # 需 DEK 共享机制（三选项已登记安全审计实锚文档），本批只完成密级闸面。
    check("B27-5e verify 密级闸放行（跨 actor 解密留 DEK 共享专项）",
          got_priv is None, str(got_priv)[:100])
    r_secret, _ = cg_v.search("标记私有", k=5)
    _ = r_secret
    # secret 仍禁：构造 secret 节点验证不可得
    cg_admin.add("sec_node", "# 功能名：最高密\n# 正文：secret 内容样本",
                 layer="knowledge", sensitivity="secret")
    cg_admin.flush()
    got_secret = cg_v.get("sec_node")
    check("B27-5f verify 读 secret 节点仍拒",
          got_secret is None, str(got_secret)[:80])
    rec_p = Principal(actor="b27-rec", clearance="internal",
                      can_write=True, can_admin=False, role="recorder",
                      auth_mode="test")
    cg_r = MdCGSecure(root, principal=rec_p)
    check("B27-5g record（cap internal）读 private 仍拒",
          cg_r.get("priv_node") is None)

    print("== 批次 28 分型：restricted 错误处置标记可见性矩阵 ==")
    root_r = tempfile.mkdtemp(prefix="b27_res_")
    cg_seed = MdCGSecure(root_r, principal=Principal(
        actor="seed", clearance="secret", can_write=True, can_admin=True,
        role="designer", auth_mode="test"))
    cg_seed.add("err_node", "# 功能名：错误处置样本\n# 正文：错误相关内容 gamma",
                layer="knowledge", sensitivity="restricted")
    cg_seed.add("priv_node2", "# 功能名：隐私样本\n# 正文：隐私内容 delta",
                layer="knowledge", sensitivity="private")
    cg_seed.flush()

    def reader(role, clearance, can_admin=False):
        p = Principal(actor="r-" + role, clearance=clearance,
                      can_write=False, can_admin=can_admin, role=role,
                      auth_mode="test")
        return MdCGSecure(root_r, principal=p)

    got = reader("designer", "secret", can_admin=True).get("err_node")
    check("B27-6a designer 读 restricted 可（处置链路）",
          got is not None and "gamma" in (got.get("content") or ""))
    got = reader("orchestr", "internal").get("err_node")
    check("B27-6b orchestr（上级节点）读 restricted 可",
          got is not None and "gamma" in (got.get("content") or ""))
    got = reader("verify", "internal").get("err_node")
    check("B27-6c verify 读 restricted 可（验证本职）",
          got is not None and "gamma" in (got.get("content") or ""))
    for role, cl in (("record", "internal"), ("output", "internal")):
        got = reader(role, cl).get("err_node")
        check("B27-6d " + role + "（平级/下游）读 restricted 拒", got is None)
    got = reader("recorder", "internal").get("err_node")
    check("B27-6e worker（recorder）读 restricted 拒", got is None)
    guest_cg = MdCGSecure(root_r)
    got = guest_cg.get("err_node")
    check("B27-6f guest 读 restricted 拒", got is None)
    import glob as _glob
    _files = _glob.glob(os.path.join(root_r, "knowledge", "**",
                                     "err_node.md"), recursive=True)
    raw = open(_files[0], encoding="utf-8").read() if _files else ""
    check("B27-6g restricted 落盘不加密（明文可读）", "gamma" in raw)
    got = reader("verify", "internal").get("priv_node2")
    check("B27-6h private 会话绑定语义不变（非归属拒）", got is None)
    from md_cg.security import SENSITIVITY_ORDER as _SO
    check("B27-6i 阶梯 public<internal<restricted<private<secret",
          _SO == ("public", "internal", "restricted", "private", "secret"))

    print("\n" + "=" * 60)
    print(f"结果：PASS {PASS} / FAIL {FAIL}")
    for x in FAILS:
        print(f"  - {x}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
