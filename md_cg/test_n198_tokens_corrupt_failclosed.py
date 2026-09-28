# -*- coding: utf-8 -*-
"""md_cg · 令牌库损坏 fail-closed 守卫（N198，凭据面无痕全员吊销）

缺陷（修复前）：`tokens._load`（tokens.py:288-299）对不可解析 / 顶层非对象 /
tokens 非映射的 `_tokens.json` **静默回落空表**——`except (OSError, ValueError):
pass` 后 `return {"schema": SCHEMA, "tokens": {}}`，无 stderr 告警、无损坏标记。
而 issue(:383-386)/derive(:480·:520)/revoke(:568·:573) 是「读 → 改 → 整份写回」：
`data = _load(path)` → `data["tokens"][tid] = rec` → `_save(data, path)` 整份覆盖。
于是**一次签发**就把「空表 + 新记录」写回，磁盘上全部既有令牌记录被永久抹除
且零告警，旧令牌此后一律验签失败（使用者仅看到 :400「令牌不存在（可能已吊销
或来自其他令牌文件）」）——等于一次无日志无告警的全员吊销。

同型 `crypto/_keys.json` 已在 N139 fail-closed（crypto.py:265-284 置
load_error、:288-295 `_save_keys` 写前对账拒写、:318-325 provision_dek 拒签），
本处是凭据面仅剩的「损坏 → 静默清空 → 覆盖」。

修复：`_load_raw` 单点产出「损坏描述」；`_load` 按 N139 口径回落空表 + stderr
告警 + `load_error` 标记；写点 `_save`（issue/derive/revoke 共用单点）据同一
判据 fail-closed 抛 TokenError 拒写，并复查「载入时损坏、写前被修复」窗口。

守卫（六组，全部临时令牌库 + 临时路径，**绝不触真实 ~/.mdcg/_tokens.json**）：
  ① 红转绿：签发 2 枚 → 截断为非法 JSON → verify 一律 TokenError 且 stderr
     开口（修前零告警）→ 再 issue：修前 ok=True 且盘上仅剩 1 条（既有记录被
     无痕抹除）；修后抛 TokenError、盘面保持损坏原文、stderr 告警；
  ② 顶层为数组 / `tokens` 非映射：同拒（修前：前者静默清空，后者 TypeError）；
  ③ 单点收口：直接 `_save` 损坏盘面拒写（issue/derive/revoke 三面同源）——
     该腿即「修前覆盖写回」的原地红形态；
  ④ 恢复原文件后可继续签发（不是永久拒签），旧令牌重新可用；
  ⑤ 缺文件（fresh install）零告警正常读写（不误伤新装）；
  ⑥ 合法库 issue/list/verify/derive/revoke 全程零告警（不误报）。

运行：python -m md_cg.test_n198_tokens_corrupt_failclosed
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile

from . import tokens
from .tokens import TokenError

PASS = FAIL = 0
FAILS = []

TRUNCATED = '{"tokens": {'          # 部分写/手工编辑典型形态
TOP_ARRAY = '[]'                    # 顶层数组（版本漂移）
BAD_TOKENS = '{"schema": 1, "tokens": []}'   # tokens 非映射


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _write(p, text):
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _count(p):
    """盘面令牌记录数（文件不可解析 → None）。"""
    import json
    try:
        with open(p, encoding="utf-8") as f:
            return len((json.load(f).get("tokens") or {}))
    except Exception:                                        # noqa: BLE001
        return None


def _raises(fn, *a, **kw):
    """执行 fn，返回异常实例或 None，并捕获 stderr 文本。"""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            fn(*a, **kw)
        return None, buf.getvalue()
    except Exception as e:                                   # noqa: BLE001
        return e, buf.getvalue()


def main():
    roots = []
    old_env = os.environ.get(tokens.TOKEN_FILE_ENV)
    try:
        tmp = tempfile.mkdtemp(prefix="n198_")
        roots.append(tmp)
        tf = os.path.join(tmp, "_tokens.json")
        # 环境同源：任何不显式传 path 的调用也只解析到临时库（绝不触真实库）
        os.environ[tokens.TOKEN_FILE_ENV] = tf
        check("环境已指向临时令牌库（默认路径解析同源）",
              tokens.token_file() == tf, tokens.token_file())
        check("临时路径 != 真实默认令牌文件（不触真实 ~/.mdcg/_tokens.json）",
              os.path.abspath(tf) != os.path.abspath(tokens.DEFAULT_TOKEN_FILE))

        # ---------- ① 红转绿：损坏库上 issue 必须拒写 ----------
        print("\n【①】签发 2 枚 → 截断为非法 JSON → verify/issue")
        a = tokens.issue("designer", actor="n198-a", ttl=3600.0, path=tf)
        b = tokens.issue("record", actor="n198-b", ttl=3600.0, path=tf)
        good = _read(tf)
        check("setup：2 枚令牌落盘且可校验",
              _count(tf) == 2
              and tokens.verify_token(b["token"], path=tf).actor == "n198-b",
              "count=%s" % _count(tf))
        _write(tf, TRUNCATED)
        ev, es = _raises(tokens.verify_token, b["token"], path=tf)
        check("① 绿：损坏后 verify 抛 TokenError（fail-closed 不变）",
              isinstance(ev, TokenError), repr(ev)[:100])
        check("① 绿：损坏时向 stderr 告警（修前零告警）",
              "损坏" in es and tf in es, repr(es)[:120])
        # 关键红转绿腿：一次签发不得把空表覆盖写回
        ei, si = _raises(tokens.issue, "record", actor="n198-c", path=tf)
        check("① 绿：损坏库上 issue 被 TokenError 拒绝（fail-closed）",
              isinstance(ei, TokenError), repr(ei)[:140])
        check("① 绿：盘面保持损坏原文（空表未被覆盖写回）",
              _read(tf) == TRUNCATED, repr(_read(tf))[:60])
        check("① 绿：issue 拒写时亦向 stderr 告警",
              "损坏" in si, repr(si)[:120])

        # ---------- ② 其它漂移形态 ----------
        print("\n【②】顶层数组 / tokens 非映射：同拒")
        for label, bad in (("顶层数组", TOP_ARRAY), ("tokens 非映射", BAD_TOKENS)):
            _write(tf, bad)
            e2, s2 = _raises(tokens.issue, "record", actor="n198-d", path=tf)
            check("② 绿[%s]：issue 抛 TokenError 拒写" % label,
                  isinstance(e2, TokenError), repr(e2)[:120])
            check("② 绿[%s]：盘面原文未变" % label, _read(tf) == bad)

        # ---------- ③ 单点收口：_save 是所有写路径的共用出口 ----------
        print("\n【③】_save 单点（issue/derive/revoke 共用）拒写")
        _write(tf, TRUNCATED)
        e3, _s3 = _raises(tokens._save,
                          {"schema": tokens.SCHEMA,
                           "tokens": {"tk_fake": {"role": "record"}}}, tf)
        check("③ 绿：_save 在损坏盘面上抛 TokenError",
              isinstance(e3, TokenError), repr(e3)[:140])
        check("③ 绿：盘面保持损坏原文（修前此腿即整份覆盖＝无痕抹除）",
              _read(tf) == TRUNCATED)
        # derive / revoke 两条写路径同样以拒写收场且盘面不变（两态同拒的
        # 回归钉：它们先在 verify/查表 上失败，但其「不写回」同样必须成立）
        _write(tf, TRUNCATED)          # 每条腿独立：盘面复位
        e4, _s4 = _raises(tokens.derive, a["token"], "record",
                          actor="n198-e", path=tf)
        check("③ 钉：derive 在损坏库上拒写且盘面不变",
              isinstance(e4, TokenError) and _read(tf) == TRUNCATED,
              repr(e4)[:120])
        _write(tf, TRUNCATED)
        e5, _s5 = _raises(tokens.revoke, b["token_id"], path=tf)
        check("③ 钉：revoke 在损坏库上拒写且盘面不变",
              isinstance(e5, TokenError) and _read(tf) == TRUNCATED,
              repr(e5)[:120])

        # ---------- ④ 恢复后可继续用（不是永久拒签） ----------
        print("\n【④】原文件修复回去：旧令牌可用、签发恢复")
        _write(tf, good)
        check("④ 绿：恢复后旧令牌 b 重新验签成功",
              tokens.verify_token(b["token"], path=tf).actor == "n198-b")
        d = tokens.issue("record", actor="n198-f", path=tf)
        check("④ 绿：恢复后签发恢复（3 条在盘）",
              _count(tf) == 3
              and tokens.verify_token(d["token"], path=tf).actor == "n198-f",
              "count=%s" % _count(tf))
        check("④ 绿：a/b 记录仍在（未被抹除）",
              all(r.get("actor") in ("n198-a", "n198-b")
                  for r in tokens.list_tokens(path=tf, include_revoked=True)[:2]))

        # ---------- ⑤ 缺文件（fresh install）零告警 ----------
        print("\n【⑤】全新路径（缺文件）不算损坏")
        tmp2 = tempfile.mkdtemp(prefix="n198_fresh_")
        roots.append(tmp2)
        tf2 = os.path.join(tmp2, "_tokens.json")
        ef, sf = _raises(tokens.issue, "record", actor="n198-fresh", path=tf2)
        check("⑤ 绿：缺文件时正常签发（不误伤新装）",
              ef is None and _count(tf2) == 1, repr(ef)[:80])
        check("⑤ 绿：缺文件路径零 stderr 告警", sf == "", repr(sf)[:80])

        # ---------- ⑥ 合法库全程零告警（不误报） ----------
        print("\n【⑥】合法库 issue/list/verify/derive/revoke 零告警")
        tmp3 = tempfile.mkdtemp(prefix="n198_ok_")
        roots.append(tmp3)
        tf3 = os.path.join(tmp3, "_tokens.json")
        step = {}
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            r1 = tokens.issue("designer", actor="n198-ok", ttl=600.0, path=tf3)
            tokens.issue("record", actor="n198-ok2", path=tf3)
            tokens.list_tokens(path=tf3)
            tokens.verify_token(r1["token"], path=tf3)
            r2 = tokens.derive(r1["token"], "record", actor="n198-ok3", path=tf3)
            step["revoked"] = tokens.revoke(r2["token_id"], path=tf3)
        check("⑥ 绿：合法库全流程零 stderr 告警（不误报）",
              buf.getvalue() == "", repr(buf.getvalue())[:120])
        check("⑥ 绿：合法库吊销仍正常（ok=True）",
              step["revoked"].get("ok") is True, str(step["revoked"])[:80])
    finally:
        if old_env is None:
            os.environ.pop(tokens.TOKEN_FILE_ENV, None)
        else:
            os.environ[tokens.TOKEN_FILE_ENV] = old_env
        for r_ in roots:
            shutil.rmtree(r_, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
