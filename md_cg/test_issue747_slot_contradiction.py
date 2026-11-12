# -*- coding: utf-8 -*-
"""issue #747：`scrub._contradiction` 按**槽位**比对（替代全文比对）。

## 病灶
旧实现用**全文**算 bigram 与极性：六要素模板头每节点都有（20+ 共享 bigram）⇒ `len(shared)>=3
且 ratio>=0.15 几乎必过；`不适用条件` 天然带否定词 ⇒ 任意两条 CCG 节点都可能被判矛盾并 weaken+demote。

## 修法（#747 讨论后的方案）
- 只取**主张正文**并按槽位切分（`_slot_claims`）；
- 同槽位或「主张 vs 对端拒绝域」两半契约（`不适用条件` **保留**，不整行丢弃）；
- **双值极性**：两侧该槽位都非零且严格异号；
- **绝对下限** `SLOT_MIN_SHARED=5`（剥模板后分母同步变小，仅看 ratio 会反向放宽）；
- 补否定词（不会/没有/无须/不必/无需）——「不会重试」vs「会自动重试三次」这类真矛盾此前两侧都是 0。

运行：python -X utf8 -m md_cg.test_issue747_slot_contradiction
"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from md_cg import scrub                      # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


class CG:
    """最小 cg 桩：只实现 _contradiction 用到的 get(node_id)。"""

    def __init__(self, body):
        self.body = body

    def get(self, _i):
        return {"content": self.body}


A = """# 功能名：billion-context 压缩代理配置
# 生效条件：调整 DSH 上下文压缩代理
# 子功能：配置文件热加载
# 执行：用 acp_status 查看
# 验证方式：代理自估 token 数高于上游
# 不适用条件：不要把代理估算值当作上游计费值"""

B = """# 功能名：部署链失败即停
# 生效条件：执行部署步骤
# 子功能：先 disconnect 再 reconnect
# 执行：部署写成 set -e 脚本
# 验证方式：可以核验 /ready
# 不适用条件：只读查询类命令串"""


def hit(cg_body, related=("b",)):
    return scrub._contradiction(CG(cg_body), "X", [{"node_id": x} for x in related])


def main():
    print("=" * 68)
    print("issue #747 · 槽位比对（scrub._contradiction）")
    print("=" * 68)
    # ① 模板噪声不再制造矛盾（issue 里的 A/B 原样）
    ok(scrub._contradiction(CG(B), A, [{"node_id": "b"}]) is None,
       "① 两条语义无关的 CCG 节点不再互判矛盾（A/B 原样）")
    # ② 同槽位真矛盾仍检出
    C = "# 执行：可以手改 nft 规则管理防火墙端口"
    D = "# 执行：不要手改 nft 规则管理防火墙端口"
    r = scrub._contradiction(CG(D), C, [{"node_id": "b"}])
    ok(r is not None and "槽位" in str(r.get("why")), "② 同槽位真矛盾仍检出", r)
    # ③ 双值极性：一侧中立 ⇒ 不算矛盾
    E = "# 执行：手改 nft 规则管理防火墙端口"
    r3 = scrub._contradiction(CG(D), E, [{"node_id": "b"}])
    ok(r3 is None, "③ 一侧中立（pol=0）不算矛盾", r3)
    # ④ 拒绝域 ↔ 主张（两半契约）仍可检出
    G = "# 生效条件：可以用于生产环境的批量导出任务"
    H = "# 不适用条件：不要用于生产环境的批量导出任务"
    r4 = scrub._contradiction(CG(H), G, [{"node_id": "b"}])
    ok(r4 is not None, "④ 主张 vs 对端拒绝域（不适用条件）仍检出", r4)
    # ⑤ h2/h3 历史写法同样按槽位识别
    I = "## 执行：可以手改 nft 规则管理防火墙端口"
    r5 = scrub._contradiction(CG(D), I, [{"node_id": "b"}])
    ok(r5 is not None, "⑤ h2 写法的槽位同样识别", r5)
    # ⑥ 纯模板重叠（正文不同）⇒ 不矛盾
    T1 = "# 功能名：甲\n# 生效条件：乙\n# 子功能：丙\n# 执行：丁\n# 验证方式：戊\n# 不适用条件：己"
    T2 = "# 功能名：子\n# 生效条件：丑\n# 子功能：寅\n# 执行：卯\n# 验证方式：辰\n# 不适用条件：巳"
    ok(scrub._contradiction(CG(T2), T1, [{"node_id": "b"}]) is None,
       "⑥ 纯模板重叠不算矛盾")
    # ⑧ 绝对下限：共享 3 个（ratio 0.6 已过）仍不判——SLOT_MIN_SHARED 钉住
    J = "# 执行：可以管理端口"
    K = "# 执行：不要管理端口"
    ok(scrub.SLOT_MIN_SHARED == 5, '⑧a SLOT_MIN_SHARED 常量 = 5', scrub.SLOT_MIN_SHARED)
    ok(scrub._contradiction(CG(K), J, [{'node_id': 'b'}]) is None,
       '⑧b 共享 3 个（低于绝对下限）不判矛盾')
    # ⑨ 功能名不做自比（signature 不是主张）
    F1 = "# 功能名：可以管理端口规则"
    F2 = "# 功能名：不要管理端口规则"
    ok(scrub._contradiction(CG(F2), F1, [{'node_id': 'b'}]) is None,
       '⑨ 功能名槽位退出矛盾比对')
    # ⑩ 自然语句不误认成槽位
    sl2 = scrub._slot_claims("执行成功后再验证")
    ok('执行' not in sl2 and '' in sl2, '⑩ 无分隔符的自然语句归入正文桶', list(sl2)[:3])

    # ⑦ _slot_claims：剥前缀、保留拒绝域、不含模板标记名
    sl = scrub._slot_claims(A)
    ok("acp_status" in " ".join(sl.get("执行", [])), "⑦a 执行槽位保留主张", sl.get("执行"))
    ok("不适用条件" in sl and "不要" in " ".join(sl["不适用条件"]),
       "⑦b 拒绝域被保留（#747 复核 ②）", sl.get("不适用条件"))
    print()
    print("issue #747：%d 项失败" % len(FAILS) if FAILS else "issue #747：全部通过")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
