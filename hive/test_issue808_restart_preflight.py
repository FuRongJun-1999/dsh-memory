# -*- coding: utf-8 -*-
"""守卫 · issue #808 `--restart` 必须先校验配置、后停服务。

病象：`HIVE_API_KEY` 改为空字符串后跑 `--restart`，旧 serve 被 `stop` 停掉，
随后 `start` 的前置校验拒绝拉起 ⇒ 一份已知无效的配置把原本正常的服务弄下线。

守卫取向：真实 `load_config` / 真实 CLI 分派 + **桩化的 stop/start**（不碰宿主进程），
断言三件事：① 无效配置时 `stop` 从未被调用；② 返回 stage=preflight 且 ok=False；
③ 有效配置时仍然照常 stop→start（不误伤正常重启）。
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hive import serve_start as ss  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:180])
        FAILS.append(name)


def _cfg(tmp, name, extra):
    cfg = Path(tmp) / (name + ".json")
    body = dict(extra)
    body.setdefault("HIVE_JOBS_DIR", str(Path(tmp) / name))
    cfg.write_text(json.dumps(body), encoding="utf-8")
    return str(cfg)


def run_case(name, extra, expect_ok):
    with tempfile.TemporaryDirectory(dir=".") as tmp:
        cfg = _cfg(tmp, name, extra)
        env = {"HIVE_API_KEY": "", "HIVE_LLM_DISABLED": ""}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(ss, "stop", return_value={"ok": True, "stopped": True, "pid": 41}) as stop_m, \
             patch.object(ss, "start", return_value={"ok": True, "pid": 99}) as start_m:
            res = ss.restart(cfg)
            return res, stop_m.called, start_m.called


def main():
    print("=" * 70)
    print("issue #808：restart 先校验后停")
    print("=" * 70)

    # ① 空密钥：不得停、不得起
    res, stopped, started = run_case("empty_key", {"HIVE_API_KEY": ""}, False)
    ok(res.get("ok") is False, "P1 空密钥 restart 拒绝（ok=False）", res)
    ok(stopped is False, "P2 空密钥时 **stop 未被调用**（旧服务不被弄下线）", stopped)
    ok(started is False, "P3 空密钥时不尝试 start", started)
    ok(res.get("stage") == "preflight", "P4 stage=preflight（可区分于 stop 失败）", res.get("stage"))
    ok("启动前置校验未通过" in str(res.get("error") or ""), "P5 错误文案与 start 同源", res.get("error"))

    # ② 密钥来源文件缺失（解析成功但不可用）
    missing = {"HIVE_API_KEY": {"file": "fixture-missing-key.txt"}}
    res2, stopped2, started2 = run_case("missing_source", missing, False)
    ok(res2.get("ok") is False and stopped2 is False,
       "P6 密钥来源文件缺失时同样不动在跑实例", (res2.get("ok"), stopped2))

    # ③ 有效配置：照常 stop → start（不误伤正常重启）
    res3, stopped3, started3 = run_case("valid", {"HIVE_API_KEY": "synthetic-value"}, True)
    ok(res3.get("ok") is True, "P7 有效配置 restart 成功", res3)
    ok(stopped3 is True and started3 is True, "P8 有效配置仍照常 stop→start（不误伤）",
       (stopped3, started3))
    ok((res3.get("restart") or {}).get("stopped") is True, "P9 restart 回执带 stopped 明细")

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())