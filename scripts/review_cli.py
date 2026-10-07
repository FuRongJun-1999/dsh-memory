# -*- coding: utf-8 -*-
"""review_cli · 审核队列裁决命令行（设计者/管理权限专用）——**源码树薄壳**

本文件是**薄壳**：审核队列裁决的实现单点在包内 `md_cg/review_cli.py`
（出货包唯一入口 `python -m md_cg.review_cli`）。此处只做 `sys.path` 注入后
转发其 `main`，**不再自带实现**——双副本纪律第 6 条：多副本改动必须双向同步，
自带实现会让两副本继续发散。

为什么是薄壳而不是"逐字复制的孪生件"（2026-10-07，三处归因口径缺口之④）：
本文件与 `md_cg/review_cli.py` 此前是两份近同构实现，却已**方向相反**地发散——
`md_cg` 版补了 `autoflush=1`（提交 bac86b87 的 P1b 第二落点），scripts 版从未获得；
而 `--session` 帮助文本 scripts 版已改为三态口径、`md_cg` 版仍是陈旧的"随机会话"
措辞。薄壳化后两副本共用同一 `main`/`_cg`（含 `autoflush=1`），从构造上消除发散。

用法（与包内完全一致；root 须与待裁决部署一致：--root 或环境变量 MDCG_ROOT）：
  python scripts/review_cli.py list
  python scripts/review_cli.py accept <pid> --session <会话id> --reason "实跑测试证据"
  python scripts/review_cli.py reject <pid> --reason "内容有误"
  python scripts/review_cli.py edit   <pid> --content "修正后内容" --reason "..."
  python scripts/review_cli.py merge  <pid> --into <已有节点id> --reason "..."
  python scripts/review_cli.py noop   <pid> --reason "已评估，判定无需改动"
  python scripts/review_cli.py rounds <pid>        # 某提案裁决轮次历史
  python scripts/review_cli.py stats               # 裁决动作统计（含 noop）

语义 / 归因 / 边界说明见包内单点 `md_cg/review_cli.py` 的模块 docstring
（`python -m md_cg.review_cli --help`）——本壳不重复，避免第二真源。
"""
import os
import sys

# 源码树内运行时把仓根（本文件的上一级）注入 sys.path，使 `md_cg` 可导入
# （与包内入口同一代码路径：那里 _HERE 同为插件根）。出货包不含 scripts/，
# 故安装态不经此处。
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from md_cg.review_cli import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
