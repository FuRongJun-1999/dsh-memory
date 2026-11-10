#!/usr/bin/env python3
# 生效条件：本文件由 run-server.sh 以 `python3 <部署根>/server/seal_default_private.py "$@"` 预载时生效；
#   直接 `python3 -m md_cg.mcp_server` 或 `python3 -m md_cg.test_*`（md_cg 自带测试跑法）都不会经过本文件。
# 子功能：把「本机 MCP 服务端的默认密级」钉成 private，使**不声明 sensitivity** 的写入
#   （DSH 记忆插件 `remember_event` 走的就是这条：clearance 给 private、sensitivity 不传）
#   自动落成密文；`md_cg` 自身的 232 个测试仍按上游常量 internal 运行，基线不动。
# 执行：import 目标模块 → 逐个把模块级 DEFAULT_SENSITIVITY 置 "private" → runpy 以 __main__ 跑 md_cg.mcp_server。
#   ⚠ 为什么不直接改 md_cg/security.py:47 的常量：那样会连带改掉所有 `clearance=DEFAULT_SENSITIVITY`
#   的测试基线（实测第四轮全套 171 PASS / 47 FAIL，比基线多 28 红），把「测试红不红」这把尺子弄钝。
#   部署级策略放在部署层，才既能生效又不污染上游语义。
# 验证方式：`D:\wook\tmp\p1-default-sens-test.mjs`（走真实 MCP stdio 通道，写一条不声明 sensitivity 的节点，
#   读盘断言 `sensitivity=private` 且正文 `mdcg-enc:v1`）；反证＝不经本文件跑同一脚本 → internal + 明文。
# 不适用条件：不适用于需要明文落盘的调试场景（如需临时关闭，把 run-server.sh 末行改回 -m md_cg.mcp_server 即可）。
"""部署级默认密封入口（只由 run-server.sh 预载）。"""
import importlib
import runpy

# mdos 的 `_seal_content` / `remember_event` / `_scan_nodes` 与 docindex、protect 各自持有一份
# 模块级绑定，必须逐个改；只改 security 模块的属性对已 `from .security import` 的模块无效。
_TARGETS = (
    "md_cg.security",
    "md_cg.mdcg",
    "md_cg.mdcos",
    "md_cg.docindex",
    "md_cg.protect",
    "md_cg.writepipe",
)


def pin_default_sensitivity(level: str = "private") -> list:
    """把各模块的模块级 DEFAULT_SENSITIVITY 钉成 level，返回真正被改到的模块名。"""
    pinned = []
    for name in _TARGETS:
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        if hasattr(mod, "DEFAULT_SENSITIVITY"):
            mod.DEFAULT_SENSITIVITY = level
            pinned.append(name)
    return pinned


if __name__ == "__main__":
    pin_default_sensitivity("private")
    runpy.run_module("md_cg.mcp_server", run_name="__main__")
