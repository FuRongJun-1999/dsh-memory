# -*- coding: utf-8 -*-
r"""守卫 · #96 验证单元不得跨厂商回落通用 key（2026-10-09 DSH 端实施）。

缺陷（GitHub #96）：role_config 的注释写明「验证单元不回落 DEEPSEEK_API_KEY，
防跨厂商凭证外泄」，但实际回落链里 MDCG_LLM_KEY（**通用**变量，实测由反思单元
承载 DeepSeek 的 key）对验证单元同样生效 ⇒ DeepSeek 的 key 被发往智谱网关，
且只打算交给 DeepSeek 的记忆正文一并外发。

判据（真跑 role_config，用 env 隔离）：
  G1 跨厂商（verify base != reflect base）：只设 MDCG_LLM_KEY ⇒ verify 的 key 为 None
  G2 同源（verify base == reflect base）：同条件下 verify 的 key 仍回落（保留原行为）
  G3 反思单元不受影响：仍回落到 DEEPSEEK_API_KEY
  G4 显式 key 优先：显式传入时不受本次改动影响
运行：python -X utf8 -m md_cg.test_issue96_key_fallback
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
_ENV_KEYS = ("MDCG_LLM_KEY", "MDCG_LLM_BASE", "MDCG_LLM_MODEL", "DEEPSEEK_API_KEY",
             "MDCG_VERIFY_KEY", "MDCG_VERIFY_BASE", "MDCG_VERIFY_MODEL",
             "ZHIPU_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY", "BIGMODEL_API_KEY")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


class _Env(object):
    """临时隔离相关环境变量（进出各一次）。"""

    def __init__(self, **kw):
        self.kw = kw
        self.saved = {}

    def __enter__(self):
        for k in _ENV_KEYS:
            self.saved[k] = os.environ.pop(k, None)
        for k, v in self.kw.items():
            os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v


def main():
    from md_cg import consolidate as C
    R, V = C.REFLECT_ROLE, C.VERIFY_ROLE

    with _Env(MDCG_LLM_KEY="sk-FAKE-deepseek-key"):
        _, vbase, vkey = C.role_config(V)
        _, rbase, rkey = C.role_config(R)
        check("G1 跨厂商 ⇒ 验证单元 key 为 None（修前＝拿到 DeepSeek 的 key）",
              vkey is None, "verify base=%s key=%r" % (vbase, vkey))
        check("G3 反思单元不受影响（仍回落 MDCG_LLM_KEY）",
              rkey == "sk-FAKE-deepseek-key", "reflect key=%r" % (rkey,))
        check("G1b 跨厂商前提成立（两单元 base 默认不同）",
              vbase != rbase, "verify=%s reflect=%s" % (vbase, rbase))

    with _Env(MDCG_LLM_KEY="sk-FAKE-deepseek-key",
              MDCG_VERIFY_BASE="https://api.deepseek.com"):
        _, vbase2, vkey2 = C.role_config(V)
        check("G2 同源（base 相同）⇒ 通用兜底仍生效（保留原行为）",
              vkey2 == "sk-FAKE-deepseek-key", "verify base=%s key=%r" % (vbase2, vkey2))

    with _Env(MDCG_LLM_KEY="sk-FAKE-deepseek-key"):
        _, _, k4 = C.role_config(V, key="explicit-verify-key")
        check("G4 显式 key 优先（不受本笔影响）", k4 == "explicit-verify-key", repr(k4))

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
