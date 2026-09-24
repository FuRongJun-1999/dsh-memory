# -*- coding: utf-8 -*-
"""批次10：互验工具库单测——A1/A2/A3 双态 + verdict 脱敏硬门禁。

能红对照：A3 断言在「验证者指纹被本轮改动」（判据面漂移）时必红；
脱敏门禁对绝对路径/prompt 字段/API key 必拦。
运行：python -m md_cg.test_interop  （退出码 0 = 全绿）
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.interop import (InteropSanityError, assert_a1, assert_a2, assert_a3,
                           freeze, make_verdict, sanity_check_verdict)

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_interop_")
    try:
        print("[1] 冻结与 A3（承重墙）")
        frozen = freeze("iter_test_001", out_dir=os.path.join(tmp, "interop"))
        digest = frozen["digest"]
        check("1a 冻结凭证含 digest 与文件清单",
              bool(digest) and len(frozen["files"]) >= 3, str(digest)[:20])
        r3 = assert_a3(frozen, digest)
        check("1b A3 成立（指纹==冻结值）", r3["ok"] is True)
        r3_bad = assert_a3(frozen, digest[:-1] + ("0" if digest[-1] != "0" else "1"))
        check("1c A3 红（验证者指纹漂移=判据被本轮改动——必红）",
              r3_bad["ok"] is False)
        frozen2 = dict(frozen)
        frozen2["digest"] = "different"
        check("1d A3 红（冻结值与声明不符）",
              assert_a3(frozen2, digest)["ok"] is False)

        print("[2] A1/A2")
        check("2a A1 成立（verifier≠subject）",
              assert_a1("verifier", "main")["ok"] is True)
        check("2b A1 红（同实例=自验无效）",
              assert_a1("main", "main")["ok"] is False)
        check("2c A2 成立（指纹不同）",
              assert_a2("aaaa", "bbbb")["ok"] is True)
        check("2d A2 红（同指纹）", assert_a2("aaaa", "aaaa")["ok"] is False)

        print("[3] verdict 脱敏硬门禁（§7.3，入库即公开）")
        v = make_verdict("iter_test_001", "verifier", "fp_ver", "main", "fp_sub",
                         "verifier-worktree", "2026-09-23T00:00:00", "pass",
                         27, 0, [{"test": "recover_by_artifact", "ok": True}])
        check("3a 合规 verdict 通过门禁", isinstance(v, dict) and v["passed"] == 27)
        for name, bad in [
            ("3b 绝对路径拦截",
             {**v, "details": [{"log": r"D:\program\secret\path.txt"}]}),
            ("3c prompt 字段拦截",
             {**v, "prompt": "你是一个…"}),
            ("3d API key 拦截",
             {**v, "details": [{"env": "sk-dummy0abcdefghijklmnop"}]}),
            ("3e unix 家目录拦截",
             {**v, "suite_origin": "/Users/test/worktree"}),
        ]:
            try:
                sanity_check_verdict(bad)
                check(name, False, "违规内容未被拦截")
            except InteropSanityError:
                check(name, True)

        print("[4] 冻结文件落盘形态（入库可复核）")
        fp = os.path.join(tmp, "interop", "frozen.json")
        data = json.load(open(fp, encoding="utf-8"))
        check("4a 冻结文件只含结构化事实（iter_id/frozen_at/digest/files"
              "/missing_patterns）",
              set(data.keys()) == {"iter_id", "frozen_at", "digest", "files",
                                   "missing_patterns"},
              str(sorted(data.keys())))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n=== interop tests: {PASS} passed, {FAIL} failed ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
