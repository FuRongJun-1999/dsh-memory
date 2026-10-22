# -*- coding: utf-8 -*-
"""改完代码后 5 秒内自检（本仓最常忘的三条，全部有 CI 守卫兜底）。

为什么有这个脚本（2026-10-21 复盘）：
新增一个 os.environ.get 却忘了登记配置层，CI 的 check_config_env_registry 会红，
但反馈要等一轮 CI（十几分钟）。三次同类红之后把这三条收成一条本地命令：

    python scripts/preflight.py

覆盖：
1) scripts.test_check_config_env_registry   —— 新增 env 必须登记（C1）
2) md_cg.test_config_registry               —— 登记的缺省值/生成件必须与源码逐位一致（G2/G3）
3) scripts.cogmap_sync check                —— 改 md_cg 后功能映射表必须同步

三条全绿才提交；任何一条红，脚本非零退出并打印红项。
"""
from __future__ import annotations

import subprocess
import sys

CHECKS = (
    ("scripts.test_check_config_env_registry", "配置层：新增 env 是否已登记"),
    ("md_cg.test_config_registry", "配置层：登记值与生成件是否新鲜"),
    ("scripts.cogmap_sync", "认知图：功能映射表是否同步", ("check",)),
)


def main() -> int:
    bad = []
    for item in CHECKS:
        mod, label = item[0], item[1]
        extra = list(item[2]) if len(item) > 2 else []
        r = subprocess.run([sys.executable, "-X", "utf8", "-m", mod, *extra],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        if r.returncode:
            bad.append(label)
            tail = [l for l in out if "FAIL" in l][:2] or out[-2:]
            print("[RED ] %s" % label)
            for l in tail:
                print("       " + l.strip()[:150])
        else:
            print("[ OK ] %s" % label)
    print("=" * 60)
    if bad:
        print("preflight：%d 条红（%s）——先修再提交" % (len(bad), "；".join(bad)))
        return 1
    print("preflight：全绿，可以提交")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
