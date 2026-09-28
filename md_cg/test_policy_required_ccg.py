# -*- coding: utf-8 -*-
"""写入闸门必需要素（CCG 六要素）守卫：policy.required 收窄到 text + 缺失清单可操作。

背景（规格：CCG 六要素强制与缺失报错）：
  · 规则库 `required` 原先对所有 content_kind 生效、缺失项只列前 3 个且显示**正则串**
    （`缺少必需要素：['(?m)^#\\s*执行', ...]`）——写入方拿不到完整、可读的补齐清单；
  · 写入面 REJECT 的 hint 只有一句「这是审核闸门的正常行为…重试同样结果」，
    把**可修正的缺要素**误导成重试无用（内容补全后重写即落盘，与政策违规不同）。

改动面（本守卫断言的对象）：
  · policy 新增 required / required_kinds / required_labels（data/policy.json）；
  · audit._rule_check 收 kind 参数：forbidden 对所有 kind 生效，required 只对
    required_kinds 收窄内的 kind 生效（键缺失/为空 = 全部 kind，向后兼容）；
    缺失项全列 + 中文展示名 + detail 结构化缺失清单；
  · writepipe._gate_audit 的 REJECT hint 分型：缺要素 → 列出缺失项与补齐指引；
    命中禁止规则 → 保留「重试同样结果」原文案。

断言（9 组）：
  G1 六要素齐全 → ACCEPT（且 evidence 说明必需规则确被检查，detail 为空）
  G2 缺 3 项 → REJECT；evidence 含 3 个中文名、无截断；detail.missing 恰 3 项且
     顺序与 required 一致，missing_patterns 与之一一对应
  G3 六项全缺 → REJECT；六个中文名全部出现，detail.missing 即六项
  G4 无 required_labels / 长度不匹配 / 非列表 → 回落正则串且**不抛错**
  G5 required_kinds=["text"]：kind=work_wip 不受 required 约束（forbidden 仍生效）；
     kind=text 仍受限
  G6 forbidden 优先于 required（同时命中时 evidence 为「命中禁止规则…」且无缺失清单）
  G7 required 为空、forbidden 非空 → 行为与改动前一致（不含禁止模式即 ACCEPT）
  G8 写入面返回：缺要素时 hint 列出缺失项 + 补齐指引且不含「重试同样结果」；
     命中禁止规则时 hint 保持原语义（写入链为真实 WritePipeline + audit 闸）
  G9 accept 旁路（红线）：临时库 propose 一条缺六要素正文后 review_decide(accept)
     仍能落盘——历史待审条目的 accept 不因本次改动收紧

红基线（不靠推理，用 git HEAD 版覆盖临时副本）：
    python -X utf8 md_cg/test_policy_required_ccg.py --head-baseline
该模式把 `git show HEAD:md_cg/audit.py` 与 `HEAD:md_cg/writepipe.py` 的字节装进临时假包
（其余依赖由转发层指向真仓模块），跑**同一套** check 并断言「红项集合 == 预期红项」。
G1/G5b/G6/G7/G9 项在两态皆绿（改动前这些行为本就成立，规格也要求它们不变）；
G8e（整链 default_pipeline 与最小装配同结果）只在绿态跑——假包无法整链装配。

实验纪律：全程**临时目录**（tempfile 建临时图 root 与临时 policy），`MDCG_POLICY_FILE`
只指向临时 policy，绝不写真实库、绝不改真实 `data/policy.json`；哑值一律非真凭据。
运行：退出码 0 = 全绿（红基线模式 0 = 红项集合符合预期）。
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGSecure          # noqa: E402
from md_cg.security import Principal        # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# CCG 六要素（顺序即 policy.required 的顺序，也是 detail.missing 的顺序）
SIX = ("功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件")
REQ_PATTERNS = tuple(r"(?m)^#\s*%s" % m for m in SIX)

# 哑值（**非真凭据**）：仅用于触发 forbidden，不构成任何密钥形态
FORBIDDEN = r"FORBIDDEN_TOKEN_[A-Z]{3}"
FORBIDDEN_HIT = "FORBIDDEN_TOKEN_XYZ"

# HEAD（required 对所有 kind 生效、缺项截断前 3、无 detail、hint 单文案）下应为红的项
EXPECTED_RED = ("G2b", "G2c", "G2d", "G3b", "G3c", "G4a", "G4b", "G4c",
                "G5a", "G8b", "G8c")

_HEAD_FILES = {"audit": "md_cg/audit.py", "writepipe": "md_cg/writepipe.py"}
_SHIMS = ("twophase", "trust", "linkref", "mcp_server")
_SHIM_TPL = ("import md_cg.%s as _m\n"
             "globals().update({k: v for k, v in vars(_m).items()\n"
             "                 if not k.startswith('__')})\n")

_seq = [0]


def _body(omit=()):
    """构造 CCG 正文：六要素各一行（omit 中的要素整行略去）+ 一行正文。"""
    lines = ["# %s：单元 要素守卫探针（%s）" % (m, m) for m in SIX if m not in omit]
    return "\n".join(lines) + "\n\n正文：必需要素守卫探针（临时库，非真实记忆）。"


def _policy(**kw):
    """与新 data/policy.json 同形的临时策略（只放守卫自用的哑 forbidden）。"""
    p = {"forbidden": [FORBIDDEN], "required": list(REQ_PATTERNS),
         "required_kinds": ["text"], "required_labels": list(SIX)}
    p.update(kw)
    return p


def _write_policy(tmp, obj, name):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return path


def _mk_cg(tmp, tag):
    _seq[0] += 1
    root = os.path.join(tmp, "root_%02d_%s" % (_seq[0], tag))
    p = Principal(tenant="default", actor="t_ccg_req", role="designer",
                  can_write=True, can_admin=True)
    return MdCGSecure(root, principal=p)


def _audit(audit_mod, text, rules, kind="text"):
    return audit_mod.audit(kind, {"content": text}, {"rules": rules})


def _write_face(wp_mod, cg, a):
    """真实写入链上只装 audit 闸（两态同源对拍用）。

    为什么不整链：HEAD 假包的链上其余闸（deps/linkref/consistency）依赖真仓模块的
    相对导入，装进假包会连带把工作区实现拉进基线态；audit 是该链**首个可短路闸**，
    其 REJECT 出口与本最小装配一等价（绿态另有 G8e 用整链 default_pipeline 复核）。
    """
    pipe = wp_mod.WritePipeline()
    pipe.register_before("audit", wp_mod._gate_audit)
    return pipe.execute(cg, dict(a))


def _try(fn):
    try:
        return fn(), None
    except Exception as exc:                      # noqa: BLE001
        return None, "%s: %s" % (type(exc).__name__, exc)


def _fake_pkg(tmp, blobs):
    """在临时目录搭假包 mdcg_head：HEAD 源 + 指向真仓模块的转发层。"""
    root = os.path.join(tmp, "head_pkg")
    pkg = os.path.join(root, "mdcg_head")
    os.makedirs(pkg, exist_ok=True)
    with open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8") as f:
        f.write("# 临时假包（守卫自用）：只装 HEAD 源与真仓模块的转发层\n")
    for name, data in blobs.items():
        with open(os.path.join(pkg, name + ".py"), "wb") as f:
            f.write(data)
    for name in _SHIMS:
        with open(os.path.join(pkg, name + ".py"), "w", encoding="utf-8") as f:
            f.write(_SHIM_TPL % name)
    sys.path.insert(0, root)
    importlib.invalidate_caches()
    return root


def _git_show(rel):
    r = subprocess.run(["git", "show", "HEAD:" + rel], cwd=_REPO,
                       capture_output=True)
    if r.returncode != 0:
        raise SystemExit("git show HEAD:%s 失败：%s"
                         % (rel, r.stderr.decode("utf-8", "replace")[:200]))
    return r.stdout


def run_checks(tmp, audit_mod, wp_mod, full_face=False):
    """对给定 audit/writepipe 模块跑全套 check → [(id, ok, detail)]，全临时目录。"""
    out = []

    def add(cid, ok, detail=""):
        out.append((cid, bool(ok), str(detail)[:200]))

    p1 = _write_policy(tmp, _policy(), "policy_full.json")
    three = ("执行", "验证方式", "不适用条件")
    miss3 = _body(three)
    miss_all = "正文：无任何要素标记（临时库探针）"

    # ---------------- G1 六要素齐全 → ACCEPT ----------------
    os.environ["MDCG_POLICY_FILE"] = p1
    r = _audit(audit_mod, _body(), _policy())
    add("G1a", r["state"] == "ACCEPT", r["state"])
    add("G1b", "6 条必需规则" in r["evidence"], r["evidence"])
    add("G1c", r["detail"] is None, repr(r["detail"]))

    # ---------------- G2 缺 3 项 ----------------
    r = _audit(audit_mod, miss3, _policy())
    want = "缺少必需要素：执行、验证方式、不适用条件（补齐后重写即可，本条未入库）"
    add("G2a", r["state"] == "REJECT", r["state"])
    add("G2b", r["evidence"] == want, r["evidence"])
    add("G2c", (r["detail"] or {}).get("missing") == list(three),
        (r["detail"] or {}).get("missing"))
    add("G2d", (r["detail"] or {}).get("missing_patterns") == list(REQ_PATTERNS[3:]),
        (r["detail"] or {}).get("missing_patterns"))

    # ---------------- G3 六项全缺 ----------------
    r = _audit(audit_mod, miss_all, _policy())
    add("G3a", r["state"] == "REJECT", r["state"])
    add("G3b", all(m in r["evidence"] for m in SIX), r["evidence"])
    add("G3c", (r["detail"] or {}).get("missing") == list(SIX),
        (r["detail"] or {}).get("missing"))

    # ---------------- G4 labels 缺失 / 长度不匹配 / 非列表 → 回落正则串 ----------------
    no_lab = {"forbidden": [FORBIDDEN], "required": list(REQ_PATTERNS),
              "required_kinds": ["text"]}
    got, err = _try(lambda: _audit(audit_mod, miss_all, dict(no_lab)))
    add("G4a", err is None and got is not None
        and got["state"] == "REJECT"
        and (got["detail"] or {}).get("missing") == list(REQ_PATTERNS),
        err or (got["detail"] or {}).get("missing"))
    got, err = _try(lambda: _audit(audit_mod, miss_all,
                                   dict(no_lab, required_labels=list(SIX[:3]))))
    add("G4b", err is None and got is not None
        and (got["detail"] or {}).get("missing") == list(REQ_PATTERNS),
        err or (got["detail"] or {}).get("missing"))
    got, err = _try(lambda: _audit(audit_mod, miss_all,
                                   dict(no_lab, required_labels="ABCDEF")))
    add("G4c", err is None and got is not None
        and (got["detail"] or {}).get("missing") == list(REQ_PATTERNS),
        err or (got["detail"] or {}).get("missing"))

    # ---------------- G5 required_kinds 收窄 ----------------
    r_wip = audit_mod.audit("work_wip", {"content": miss_all}, {"rules": _policy()})
    add("G5a", r_wip["state"] == "ACCEPT" and "不适用" in r_wip["evidence"],
        "%s / %s" % (r_wip["state"], r_wip["evidence"]))
    r_txt = _audit(audit_mod, miss_all, _policy())
    add("G5b", r_txt["state"] == "REJECT", r_txt["state"])
    r_wip_fb = audit_mod.audit("work_wip", {"content": "正文 " + FORBIDDEN_HIT},
                               {"rules": _policy()})
    add("G5c", r_wip_fb["state"] == "REJECT"
        and "命中禁止规则" in r_wip_fb["evidence"], r_wip_fb["evidence"])

    # ---------------- G6 forbidden 优先 ----------------
    r = _audit(audit_mod, "正文 " + FORBIDDEN_HIT + "，且无任何要素标记", _policy())
    add("G6a", r["state"] == "REJECT"
        and r["evidence"].startswith("命中禁止规则"), r["evidence"])
    add("G6b", r["detail"] is None, repr(r["detail"]))

    # ---------------- G7 required 为空（改动前行为） ----------------
    p7 = {"forbidden": [FORBIDDEN], "required": []}
    r = _audit(audit_mod, miss_all, dict(p7))
    add("G7a", r["state"] == "ACCEPT", r["state"])
    r = _audit(audit_mod, "正文 " + FORBIDDEN_HIT, dict(p7))
    add("G7b", r["state"] == "REJECT"
        and r["evidence"] == "命中禁止规则：" + FORBIDDEN, r["evidence"])
    add("G7c", r["detail"] is None, repr(r["detail"]))

    # ---------------- G8 写入面返回（真实写入链 + audit 闸） ----------------
    cg = _mk_cg(tmp, "g8")
    a_miss = {"content": miss3, "content_kind": "text", "layer": "knowledge"}
    got, err = _try(lambda: _write_face(wp_mod, cg, a_miss))
    got = got or {}
    add("G8a", err is None and got.get("ok") is False
        and got.get("committed") is False and got.get("moved_to") == "rejected",
        err or json.dumps(got, ensure_ascii=False, default=str)[:180])
    hint = str(got.get("hint") or "")
    add("G8b", "重试同样结果" not in hint, hint)
    add("G8c", all(m in hint for m in three) and "补齐后重写" in hint, hint)
    got2, err2 = _try(lambda: _write_face(
        wp_mod, cg, {"content": "正文 " + FORBIDDEN_HIT, "content_kind": "text",
                     "layer": "knowledge"}))
    got2 = got2 or {}
    add("G8d", err2 is None and got2.get("moved_to") == "rejected"
        and "重试同样结果" in str(got2.get("hint") or ""),
        err2 or str(got2.get("hint") or ""))
    if full_face:
        got3, err3 = _try(lambda: wp_mod.default_pipeline().execute(
            cg, dict(a_miss)))
        got3 = got3 or {}
        add("G8e", err3 is None and str(got3.get("hint") or "") == hint
            and got3.get("moved_to") == "rejected",
            err3 or str(got3.get("hint") or ""))

    # ---------------- G9 accept 旁路（红线） ----------------
    cg9 = _mk_cg(tmp, "g9")
    pr = cg9.propose("mem_ccg_accept", miss3, info=True, layer="knowledge")
    dec = cg9.review_decide(pr["pid"], "accept")
    add("G9a", bool(dec.get("ok")) and dec.get("node_id") == "mem_ccg_accept",
        json.dumps(dec, ensure_ascii=False, default=str)[:180])
    node = cg9.get("mem_ccg_accept") or {}
    add("G9b", "# 功能名" in str(node.get("content") or "")
        and "执行" not in str(node.get("content") or ""),
        json.dumps(node, ensure_ascii=False, default=str)[:180])
    return out


def main():
    ap = argparse.ArgumentParser(description="写入闸门必需要素（CCG 六要素）守卫")
    ap.add_argument("--head-baseline", action="store_true",
                    help="用 git HEAD 版 audit.py / writepipe.py 装配临时假包取红基线"
                         "（断言红项集合 == 预期红项）")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="ccg_required_")
    saved = os.environ.pop("MDCG_POLICY_FILE", None)
    try:
        if args.head_baseline:
            _fake_pkg(tmp, {n: _git_show(p) for n, p in _HEAD_FILES.items()})
            print("[红基线] 源 = git HEAD:md_cg/audit.py + HEAD:md_cg/writepipe.py"
                  "（写入临时假包，不覆盖工作区文件）")
            audit_mod = importlib.import_module("mdcg_head.audit")
            wp_mod = importlib.import_module("mdcg_head.writepipe")
            results = run_checks(tmp, audit_mod, wp_mod, full_face=False)
        else:
            print("[绿态] 源 = 工作区 md_cg/audit.py + md_cg/writepipe.py")
            import md_cg.audit as audit_mod
            import md_cg.writepipe as wp_mod
            results = run_checks(tmp, audit_mod, wp_mod, full_face=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if saved is not None:
            os.environ["MDCG_POLICY_FILE"] = saved
        else:
            os.environ.pop("MDCG_POLICY_FILE", None)

    reds = [cid for cid, ok, _ in results if not ok]
    for cid, ok, detail in results:
        print("  %s %s%s" % ("OK  " if ok else "FAIL", cid,
                             "" if ok else "  " + detail))
    print("\n结果：%d pass / %d fail（红项：%s）"
          % (len(results) - len(reds), len(reds), ", ".join(reds) or "无"))
    if args.head_baseline:
        if tuple(reds) == EXPECTED_RED:
            print("红基线符合预期：HEAD 侧缺要素清单不可读/被截断、required 未收窄、"
                  "hint 无补齐指引，共 %d 项分叉（%s）"
                  % (len(EXPECTED_RED), "、".join(EXPECTED_RED)))
            return 0
        print("红基线与预期不符——预期红项：" + "、".join(EXPECTED_RED))
        return 1
    if reds:
        print("FAILED：" + "、".join(reds))
        return 1
    print("ALL OK：text 类必需要素缺失即拒并给出可读补齐清单；work_wip 不受 required "
          "约束；accept 旁路未受影响")
    return 0


if __name__ == "__main__":
    sys.exit(main())
