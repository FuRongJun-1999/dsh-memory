# -*- coding: utf-8 -*-
"""负记忆脱敏守卫（issue #43）：命中禁表被 REJECT 的写入，凭据原文不得随 rejected 落盘。

背景：writepipe._gate_audit 的 REJECT 分支把正文前 200 字交给 cg.add_rejected，
命中 forbidden（凭据形态）的内容虽被拦下、committed=false，原文却写进
`rejected/rej_*.md`，按返回的 id 可原样读回——拦截之后又把凭据存了一遍。

断言：
  R1 命中禁表 → moved_to=rejected；库目录下**任何文件**都不含哑值明文；
     rejected 节点正文带占位符「[已过滤:禁表#」；evidence 仍给出命中模式（可审计）
  R2 凭据跨 200 字截断边界 → 残片（哑值前 8 字符）同样不落盘（先脱敏后截断）
  R3 缺必需要素的 REJECT（可修正，无禁表命中）→ 负记忆保留原文（行为不变）
  R4 redact_forbidden 单元：多处命中全替换、非法正则跳过不抛错、无规则原样返回

红基线：在改动前的 main 上跑本文件，R1a/R1b/R2 为红（其余两态皆绿）。
实验纪律：全程临时目录 + 临时 policy（MDCG_POLICY_FILE 只指向临时文件）；
哑值 `tk_0123456789abcdef` 仅匹配禁表形态，**非真凭据**。
运行：python -X utf8 -m md_cg.test_rejected_redact（退出码 0 = 全绿）
"""

import json
import os
import shutil
import sys
import tempfile
import traceback

from . import audit, writepipe
from .mdcos import MdCGSecure
from .security import Principal

FAKE = "tk_0123456789abcdef"          # 哑值，非真凭据
TK = r"\btk_[0-9a-f]{8,}\b"           # 与 data/policy.json 批次71新增模式同形

_ok = 0
_bad = []


def _check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


def _files_containing(root, needle):
    hits = []
    for dp, _dn, fs in os.walk(root):
        for f in fs:
            fp = os.path.join(dp, f)
            try:
                with open(fp, encoding="utf-8", errors="ignore") as fh:
                    if needle in fh.read():
                        hits.append(os.path.relpath(fp, root))
            except OSError:
                continue
    return hits


def _mk_cg(tmp, name):
    p = Principal(tenant="default", actor="t_redact", role="designer",
                  can_write=True, can_admin=True)
    return MdCGSecure(os.path.join(tmp, name), principal=p)


def _rejected_text(cg, rid):
    fm, content = cg._read(cg.index["nodes"][rid])
    return content or ""


def main():
    tmp = tempfile.mkdtemp(prefix="rejected_redact_")
    old_policy = os.environ.pop("MDCG_POLICY_FILE", None)
    try:
        _run(tmp)
    except Exception:
        traceback.print_exc()
        _bad.append("未捕获异常")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if old_policy is not None:
            os.environ["MDCG_POLICY_FILE"] = old_policy
        else:
            os.environ.pop("MDCG_POLICY_FILE", None)
    print("\n负记忆脱敏守卫：%d 通过%s" % (
        _ok, ("，%d 失败：%s" % (len(_bad), "; ".join(_bad))) if _bad else ""))
    return 1 if _bad else 0


def _run(tmp):
    policy = os.path.join(tmp, "policy.json")
    with open(policy, "w", encoding="utf-8") as f:
        json.dump({"forbidden": [TK], "required": ["PASSED"]}, f)
    os.environ["MDCG_POLICY_FILE"] = policy
    pipe = writepipe.install_default_gates(writepipe.WritePipeline())

    # ---------- R1 命中禁表：凭据不落盘 ----------
    cg = _mk_cg(tmp, "root_r1")
    out = pipe.execute(cg, {"content_kind": "text", "layer": "knowledge",
                            "content": "PASSED 用令牌 %s 调发布接口" % FAKE})
    _check("R1 命中禁表 → rejected", out.get("moved_to") == "rejected"
           and out.get("committed") is False, repr(out))
    hits = _files_containing(cg.root, FAKE)
    _check("R1a 库目录无哑值明文", not hits, repr(hits))
    rid = out.get("id")
    body = _rejected_text(cg, rid) if rid in cg.index["nodes"] else ""
    _check("R1b rejected 正文带占位符", "[已过滤:禁表#1]" in body, repr(body))
    ev = (out.get("verdict") or {}).get("evidence") or ""
    _check("R1c evidence 仍给出命中模式", TK in ev and FAKE not in ev, repr(ev))

    # ---------- R2 跨 200 字截断边界 ----------
    cg2 = _mk_cg(tmp, "root_r2")
    # 哑值起点在第 190 字：截前 200 字剩「tk_0123456」（仅 7 位 hex，已不匹配
    # 禁表模式）——若先截断后脱敏，这段残片会漏过脱敏直接落盘。
    content = "PASSED " + "x" * 182 + " " + FAKE
    out = pipe.execute(cg2, {"content_kind": "text", "layer": "knowledge",
                             "content": content})
    frag = FAKE[:8]
    hits = _files_containing(cg2.root, frag)
    _check("R2 截断边界残片不落盘", out.get("moved_to") == "rejected" and not hits,
           repr((out.get("moved_to"), hits)))

    # ---------- R3 缺必需要素：原文保留（行为不变） ----------
    cg3 = _mk_cg(tmp, "root_r3")
    out = pipe.execute(cg3, {"content_kind": "text", "layer": "knowledge",
                             "content": "缺要素的正文，补齐后可重写"})
    rid = out.get("id")
    body = _rejected_text(cg3, rid) if rid in cg3.index["nodes"] else ""
    _check("R3 缺要素负记忆保留原文", out.get("moved_to") == "rejected"
           and "缺要素的正文，补齐后可重写" in body, repr((out.get("moved_to"), body)))

    # ---------- R4 redact_forbidden 单元 ----------
    rules = {"forbidden": ["(unclosed", TK, "", r"\bsk-[A-Za-z0-9]{20,}"]}
    s = "a %s b %s c sk-%s" % (FAKE, FAKE, "A" * 24)
    r = audit.redact_forbidden(s, rules)
    _check("R4a 多处命中全替换", FAKE not in r and "sk-AAAA" not in r
           and r.count("[已过滤:禁表#2]") == 2 and "[已过滤:禁表#3]" in r, repr(r))
    _check("R4b 无规则原样返回", audit.redact_forbidden(s, {}) == s)
    _check("R4c 非法正则跳过不抛错", "[已过滤:禁表#1]" not in r)


if __name__ == "__main__":
    sys.exit(main())
