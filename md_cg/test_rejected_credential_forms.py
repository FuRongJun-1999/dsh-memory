# -*- coding: utf-8 -*-
"""负记忆里**凭据形态**的覆盖守卫（PR#44 复核补，2026-09-28）。

运行：python -X utf8 -m md_cg.test_rejected_credential_forms

为什么另立一套（与 `test_rejected_redact.py` 的分工）：那一套守的是
「命中禁表 → 原文不落盘」的**主路径**；本套守的是 PR#44 复核时实测出来的
三个**未覆盖形态**——主路径绿了、凭据照样能落盘：

  F1 全形态令牌 `mdcg1.<role>.<id>.<secret>`：只有 id 段命中禁表，负记忆脱敏
     按命中片段替换 → 掩掉 id 却把 **role 与密钥段**原样写进 rejected。
     令牌的可用性靠 role+id+secret 三段凑齐（`tokens.parse_token`），而 id 早已
     可公开查得（仓库/npm 曾发出），故密钥段落盘等于凭据可被拼回。
  F2 脱敏必须是**跨度合并**而非逐条串行 `re.sub`：串行时窄规则先把 id 换成
     占位符，宽规则再也匹配不上那段文字，密钥段漏掩（实测反例即 F1 的成因）。
  F3 `tags`：正文命中禁表而 tags 夹带凭据时，tags 原先原样进负记忆。
  F4 防误伤：泛形写法 `mdcg1.<role>.<id>.<secret>`（文档用）不得被拒。
  F5 跨闸口径：写入闸门禁表与发布门禁 `check_publish_artifact.R1_CONTENT_RULES`
     对同一合成令牌必须同判——两闸分叉正是本缺陷的根因。
  F6 判别力自证：无凭据的正文经脱敏后与原文逐字相同。

实验纪律：临时目录 + 临时 policy（其 forbidden 拷贝**真源** data/policy.json，
故本套同时钉住真源不丢这两条令牌口径）；哑值 `tk_0123456789abcdef` 与
`SYNTHFRAG...` 均为合成串，**非真凭据**。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import tempfile
import traceback

from . import audit, writepipe
from .mdcos import MdCGSecure
from .security import Principal

ID = "tk_0123456789abcdef"                                   # 哑令牌 id（与禁表同形）
FRAG = "SYNTHFRAG_do_not_use_0123456789"                   # 合成密钥段，非真凭据
# 变量名刻意不叫 FRAG_*：发布门禁 APIKEY_LITERAL 规则会命中
# `secret = "<16+ 字符>"` 这种**形似密钥赋值**的行（本条即被它抓到过一次）。
FULL = "mdcg1.designer." + ID + "." + FRAG                 # 全形态令牌（合成）
GENERIC = "mdcg1.<role>.<id>.<secret>"                       # 泛形写法（文档用）

_ok = 0
_bad = []


def ok(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _policy() -> dict:
    with io.open(os.path.join(_repo_root(), "data", "policy.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _files_with(root, needle):
    hits = []
    for dp, _dn, fs in os.walk(root):
        for f in fs:
            fp = os.path.join(dp, f)
            try:
                with io.open(fp, encoding="utf-8", errors="ignore") as fh:
                    if needle in fh.read():
                        hits.append(os.path.relpath(fp, root))
            except OSError:
                continue
    return hits


def _mk_cg(tmp, name):
    p = Principal(tenant="default", actor="t_forms", role="designer",
                  can_write=True, can_admin=True)
    return MdCGSecure(os.path.join(tmp, name), principal=p)


def _masked_regions(text):
    """把占位符折叠成统一记号——用于比较「哪些字被掩」，与规则序号无关。"""
    return re.sub(r"\[已过滤:禁表#\d+\]", "<MASK>", text)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="cred_forms_")
    old_policy = os.environ.get("MDCG_POLICY_FILE")
    try:
        _run(tmp)
    except Exception:
        traceback.print_exc()
        _bad.append("未捕获异常")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if old_policy is None:
            os.environ.pop("MDCG_POLICY_FILE", None)
        else:
            os.environ["MDCG_POLICY_FILE"] = old_policy
    print("\n凭据形态覆盖守卫：%d 通过%s" % (
        _ok, ("，%d 失败：%s" % (len(_bad), "; ".join(_bad))) if _bad else ""))
    return 1 if _bad else 0


def _run(tmp):
    src = _policy()
    policy = os.path.join(tmp, "policy.json")
    # 只搬 forbidden：保持与真源同口径（required 用不着，本套不走缺要素路径）
    with io.open(policy, "w", encoding="utf-8") as f:
        json.dump({"forbidden": src["forbidden"], "required": ["PASSED"]}, f)
    os.environ["MDCG_POLICY_FILE"] = policy
    rules = {"forbidden": src["forbidden"]}
    pipe = writepipe.install_default_gates(writepipe.WritePipeline())

    print("== F5 跨闸口径：写入闸门与发布门禁对同一合成令牌同判 ==")
    import importlib.util
    _sp = os.path.join(_repo_root(), "scripts", "check_publish_artifact.py")
    spec = importlib.util.spec_from_file_location("_cpa_forms", _sp)
    cpa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cpa)
    pub = [rx for _n, rx, *_ in [tuple(x) + (None,) if len(x) == 2 else x
                                 for x in cpa.R1_CONTENT_RULES]
           if hasattr(rx, "search") and rx.search(FULL)]
    write_hit = [p for p in src["forbidden"] if re.search(p, FULL)]
    ok(bool(pub) and bool(write_hit),
       "F5 两闸同判命中（发布 %d 条 / 写入 %d 条）" % (len(pub), len(write_hit)), repr((pub, write_hit)))

    print("== F1 全形态令牌经写入闸门 → 凭据不落盘 ==")
    cg = _mk_cg(tmp, "root_f1")
    out = pipe.execute(cg, {"content_kind": "text", "layer": "knowledge",
                            "content": "PASSED 用 %s 调发布接口" % FULL})
    ok("F1 命中 → rejected", out.get("moved_to") == "rejected"
       and out.get("committed") is False, repr(out.get("verdict", {}).get("state")))
    ok("F1a 库内无密钥段明文", not _files_with(cg.root, FRAG),
       repr(_files_with(cg.root, FRAG)))
    ok("F1b 库内无 id 明文", not _files_with(cg.root, ID),
       repr(_files_with(cg.root, ID)))
    rid = out.get("id")
    body = ""
    if rid in cg.index["nodes"]:
        _fm, body = cg._read(cg.index["nodes"][rid])
    ok("F1c 负记忆整段被掩", "[已过滤:禁表#" in (body or "") and FRAG not in (body or ""),
       repr((body or "")[:120]))

    print("== F2 跨度合并：与规则顺序无关、密钥段零残留 ==")
    one = audit.redact_forbidden("PASSED 用 %s 调接口" % FULL, rules)
    ok("F2 密钥段与 id 均被掩", FRAG not in one and ID not in one, repr(one))
    flip = {"forbidden": list(reversed(src["forbidden"]))}
    two = audit.redact_forbidden("PASSED 用 %s 调接口" % FULL, flip)
    ok("F2a 规则顺序颠倒 → 掩码区域相同", _masked_regions(one) == _masked_regions(two),
       repr((_masked_regions(one), _masked_regions(two))))

    print("== F3 tags 夹带凭据 → 负记忆里的 tags 同样被掩 ==")
    cg3 = _mk_cg(tmp, "root_f3")
    out3 = pipe.execute(cg3, {"content_kind": "text", "layer": "knowledge",
                              "content": "PASSED 正文含 %s" % ID, "tags": [FULL, "正常标签"]})
    rid3 = out3.get("id")
    fm3 = {}
    if rid3 in cg3.index["nodes"]:
        fm3, _b3 = cg3._read(cg3.index["nodes"][rid3])
    ok("F3 负记忆 tags 无密钥段", FRAG not in json.dumps(fm3.get("tags"), ensure_ascii=False),
       repr(fm3.get("tags")))
    ok("F3a 库内任何文件无密钥段明文", not _files_with(cg3.root, FRAG),
       repr(_files_with(cg3.root, FRAG)))

    print("== F4 防误伤：泛形写法不被拒、正常正文不受影响 ==")
    cg4 = _mk_cg(tmp, "root_f4")
    out4 = pipe.execute(cg4, {"content_kind": "text", "layer": "knowledge",
                              "content": "PASSED 令牌形如 %s ，照此书写" % GENERIC})
    ok("F4 泛形写法过闸（不被拒）", out4.get("moved_to") != "rejected",
       repr(out4.get("moved_to")))
    text = "PASSED 一条与凭据无关的正文，含 mdcg1 一词与 tk_zzzz 哑值"
    ok("F6 无凭据正文脱敏后逐字不变", audit.redact_forbidden(text, rules) == text,
       repr(audit.redact_forbidden(text, rules)))


if __name__ == "__main__":
    sys.exit(main())
