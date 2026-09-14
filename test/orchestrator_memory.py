#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主代理/子代理记忆架构 · 可运行参考实现

把《主代理子代理记忆架构设计.md》里验证过的机制封成一套可直接用的 API。
不依赖 MCP server，直接跑在灵枢的 MdCGOS 上；换成 MCP 只需把方法调用映射成工具调用。

性质：演示/参考脚本——selftest() 只 print 不 assert，退出码恒 0，跑绿不代表
功能验证；功能正确性以断言测试（如 parallel_test）为准。

用法：
    from orchestrator_memory import OrcMemory
    om = OrcMemory("/path/to/memory_root")

    # ① 开工：主代理锚定全局态
    ctx = om.anchor_global(task_desc="重构认证模块")

    # ② 派发：生成子代理的 prompt（含裁剪后的上下文 + 卡片规范）
    prompt = om.dispatch_prompt("subA", "迁移 login/logout", need=["token 策略"])

    # ③ 收工：子代理写入卡片 + 细节
    om.submit(sub="subA", feature="认证重构", subfeature="迁移 login/logout",
              conclusion="...", evidence="...", impact="...", pending="...",
              detail="完整过程与命令输出...")

    # ④ 收口：主代理只读卡片，不读细节
    cards = om.collect_cards()

    # ⑤ 合并进全局态
    om.merge_global(task_desc="...", updates=[...])
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time


def _ensure_repo(repo_path: str | None = None):
    """把灵枢仓库根加入 sys.path。"""
    root = repo_path or os.environ.get("LINGSHU_REPO")
    if not root:
        raise RuntimeError("请设置 LINGSHU_REPO 环境变量或传入 repo_path")
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


#: verification_basis 合法值（实测：写别的会直接抛异常）
VALID_BASIS = ("compiler", "test", "measurement", "formal_proof",
               "data", "textbook", "public_kb", "other")

CARD_TEMPLATE = """# 功能名：{feature}
# 子功能：{subfeature}
# 生效条件：{condition}

结论：{conclusion}

证据：{evidence}

影响面：{impact}

未决项：{pending}
"""

#: 卡片书写规范（每一条都是实测踩出来的，不是风格偏好）
CARD_RULE = """
⚠️ 本模板有三条**硬性**格式要求，违反会让冲突检测失效（均已实测）：

1. `# 功能名` / `# 子功能` / `# 生效条件` 三行**必须用 `#` 前缀**
   —— 它们是被 CCG 解析器识别的结构字段，缺一个就退化为「无从比对」。
   `# 生效条件` 还必须是**空格分隔的关键词串**（`缓存选型 决策`），
   不能写成句子（`缓存选型决策时`）——句子会稀释词面覆盖率到阈值以下。

2. `结论：/证据：/影响面：/未决项：` 四行**必须不带 `#`**
   —— 系统用「去掉 `#` 声明行后的正文」做结论比对。
   若结论也写成 `# 结论：X`，正文会被清空，
   两条矛盾的卡片会被判为"结论完全相同"（实测 conclusion_overlap=1.0 → 漏检）。

3. **必须有一段不带 `#` 的结论正文**
   —— 空正文同样导致漏检（同上）。
"""


class OrcMemory:
    """主代理/子代理分层记忆编排器。

    三层（实测隔离生效）：
      L0 全局态  session=main        importance>=0.9  layer=knowledge
      L1 卡片层  session=<sub>       importance=0.7   layer=knowledge
      L2 细节层  session=<sub>       importance=0.4   layer=contextual
    """

    def __init__(self, root: str, repo_path: str | None = None,
                 global_budget: int = 1200, card_budget: int = 600):
        _ensure_repo(repo_path)
        from md_cg.mdcos import MdCGOS  # noqa
        self.cg = MdCGOS(root)
        self.root = root
        self.global_budget = global_budget
        self.card_budget = card_budget
        self._global_id = None
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ================= L0 全局态 =================

    def anchor_global(self, task_desc: str, extra_ctx: str = "") -> dict:
        """开工锚定：读全局态；不存在则创建。返回主代理开局上下文。"""
        out = self.cg.recall(task_desc, budget_tokens=self.global_budget,
                             k=30, session="main")
        if out["pack"]:
            return {"recovered": True, "nodes": out["pack"],
                    "tokens_used": out["tokens_used"]}
        nid = "glob_" + str(int(time.time() * 1000))
        self.cg.add(
            nid,
            f"# 功能名：{task_desc}\n# 生效条件：本任务进行期间\n"
            f"结论：任务已启动，尚未有子任务产出。\n{extra_ctx}",
            layer="knowledge", verification_basis="other",
            importance=0.95, session="main")
        self._global_id = nid
        return {"recovered": False, "node_id": nid, "nodes": []}

    def merge_global(self, task_desc: str, summary: str,
                     derived_from: list[str] | None = None) -> str:
        """把子代理结论合并进全局态（主代理专属动作）。"""
        nid = "glob_" + str(int(time.time() * 1000))
        doc = (f"# 功能名：{task_desc}\n# 生效条件：本任务进行期间\n"
               f"结论：{summary}\n")
        kw = dict(layer="knowledge", verification_basis="other",
                  importance=0.95, session="main")
        if derived_from:
            kw["derived_from"] = derived_from
        self.cg.add(nid, doc, **kw)
        self._global_id = nid
        return nid

    # ================= 派发 =================

    def dispatch_prompt(self, sub: str, task: str,
                        need: list[str] | None = None) -> str:
        """生成子代理 prompt：裁剪上下文 + 卡片规范 + 写入指令。

        need: 该子任务真正需要的全局态关键词（主代理负责裁剪，这是关键）。
        """
        ctx = ""
        if need:
            picked = []
            for kw in need:
                o = self.cg.recall(kw, budget_tokens=300, k=3, session="main")
                picked.extend(o["pack"])
            if picked:
                ctx = "\n".join(f"- {self._brief(n)}" for n in picked[:6])
        return f"""你是一个子代理，标识为 `{sub}`。

## 你的任务
{task}

## 你需要知道的背景（由主代理裁剪，不要自己去查全局记忆）
{ctx or "（无需额外背景）"}

## 完成后你必须产出这张卡片，原样使用这个格式
{CARD_TEMPLATE.format(feature="<任务域>", subfeature=task[:20], condition="<结论生效条件>",
                      conclusion="<做了什么、结论>", evidence="<可验证锚点>",
                      impact="<影响面>", pending="<未决项，没有写无>")}

## 然后调用写入（两次，模板见 orchestrator_memory.py 的 submit()）
- 第一次写卡片：layer=knowledge, session={sub}, importance=0.7
- 第二次写细节：layer=contextual, session={sub}, importance=0.4

⚠️ 不要省略 `# 功能名` / `# 生效条件` 两行——省略会让系统无法检测你的结论
   与既有决策的冲突，你的产出会被静默放过（实测确认的盲区）。
"""

    # ================= 子代理写入 =================

    def submit(self, sub: str, feature: str, subfeature: str,
               conclusion: str, evidence: str = "", impact: str = "",
               pending: str = "无", condition: str | None = None,
               detail: str = "", derived_from: list[str] | None = None,
               basis: str = "other") -> dict:
        """子代理收工：写卡片（L1）+ 写细节（L2），并做冲突预检。

        返回 {"card_id", "detail_id", "conflict"}。
        conflict.verdict=DEFER 时应由主代理裁决。
        """
        if basis not in VALID_BASIS:
            raise ValueError(f"verification_basis 非法：{basis}（合法：{VALID_BASIS}）")
        # ⚠️ 生效条件必须是**空格分隔的关键词串**，不是自然句子。
        # 实测：`缓存选型 决策` → 词面覆盖率 1.0 → 触发 DEFER；
        #      `缓存选型决策时` → 覆盖率不足 → 静默 ACCEPT（漏检）。
        # 冲突检测靠词面覆盖率 >= SAME_COND_HIGH(0.75)，句子会被稀释。
        cond = condition or f"{feature} {subfeature}"
        card = CARD_TEMPLATE.format(
            feature=feature, subfeature=subfeature, condition=cond,
            conclusion=conclusion, evidence=evidence or "无",
            impact=impact or "无", pending=pending or "无")

        # L1 卡片：importance=0.7 触发自动保护（实测 >=0.7 打 protected）
        # 注意：ID 必须带序号，避免同一毫秒内 subA/subB 的卡/细节 ID 撞车
        # （实测：仅用毫秒时间戳时两份 .md 会互相覆盖）。
        seq = self._next_seq()
        card_id = f"{sub}_card_{int(time.time()*1000)}_{seq}"
        ckw = dict(layer="knowledge", verification_basis=basis,
                   importance=0.7, session=sub)
        if derived_from:
            ckw["derived_from"] = derived_from
        self.cg.add(card_id, card, **ckw)

        # L2 细节：默认不被主代理召回
        detail_id = None
        if detail:
            detail_id = f"{sub}_det_{int(time.time()*1000)}_{seq}"
            self.cg.add(detail_id, detail, layer="contextual",
                        verification_basis=basis, importance=0.4,
                        session=sub, derived_from=[card_id])

        # 冲突预检（不改库，只报告）
        cvd = self.cg.check_consistency(card, layer="knowledge",
                                        auto_flywheel=True)
        return {"card_id": card_id, "detail_id": detail_id,
                "conflict": cvd,
                "needs_adjudication": cvd.get("verdict") == "DEFER"}

    # ================= 主代理收口 =================

    def collect_cards(self, subs: list[str] | None = None,
                      query: str = "子任务 结论 影响面") -> list[dict]:
        """只读卡片层（不含细节）。subs=None 时读所有子代理。"""
        cards = []
        if subs:
            for s in subs:
                o = self.cg.recall(query, budget_tokens=self.card_budget,
                                   k=10, session=s)
                cards.extend(o["pack"])
        else:
            for nid in list(self.cg.index["nodes"]):
                fm, c = self.cg._read(self.cg.index["nodes"][nid])
                if fm.get("layer") == "knowledge" and fm.get("session") not in (None, "main"):
                    cards.append({"id": nid, "session": fm.get("session"),
                                  "content": c})
        return cards

    def pending_items(self, subs: list[str] | None = None) -> list[dict]:
        """扫出所有卡片的「未决项」——主代理的待办清单。"""
        out = []
        for card in self.collect_cards(subs=subs):
            for line in card["content"].splitlines():
                s = line.strip()
                if s.startswith("未决项：") or s.startswith("# 未决项："):
                    v = s.split("：", 1)[-1].strip()
                    if v and v != "无":
                        out.append({"from": card.get("session") or card["id"],
                                    "pending": v})
        return out

    def adjudicate(self, pid: str, decision: str, reason: str) -> dict:
        """主代理裁决冲突（decision: accept|reject|edit|merge）。"""
        return self.cg.review_decide(pid, decision, reason=reason)

    def pending_reviews(self) -> list:
        """待裁决队列。"""
        return self.cg.review_list()

    def drill_down(self, node_id: str) -> tuple:
        """需要追问细节时，按 id 精确取单条（这是唯一的细节读入口）。"""
        return self.cg._read(self.cg.index["nodes"][node_id])

    # ================= 多进程生命周期（并行实验实证补齐） =================

    def close(self) -> None:
        """写完必须调用：把未达 autoflush 阈值的脏索引 flush 进本进程独占分片。
        不调用 → 节点 .md 在盘上但索引无记录——「在盘上但不可见」
        （mdcg.close 注释自述的坑；多进程实验：worker 退出前不 close 则
        主代理 refresh 后也读不到，因为索引只认快照+分片回放，不重扫 .md）。"""
        self.cg.close()

    def refresh(self) -> None:
        """主代理收口前必须调用：重载索引（快照+全分片回放），
        感知其他进程的写入。index 是进程内快照（__init__ 加载一次），
        不 refresh 则 collect_cards/stats/recall 全部只见自己 init 时的旧世界
        （并行实验实测：8 进程写 24 卡，父进程不 refresh 时 collect 0/24）。"""
        self.cg.index = self.cg._load_index()

    # ================= 收口检查点（J-Space 证据链映射） =================

    def final_check(self, cards: list[dict] | None = None) -> dict:
        """收口全库一致性复查——并行盲区补全（证据链的「检查点」环节）。

        实证边界：check_consistency 只见调用方实例 init 时的索引快照，
        并行提交可绕过跨进程冲突检测（parallel_test B 组 0/4 DEFER）。
        跨进程冲突只能在主代理侧、refresh 之后统一检出——本方法即该检查点。

        只报告不落库、不投递飞轮：处置走 adjudicate/review 裁决通路
        （相同重试不产生新证据，静默放行才是事故）。
        """
        self.refresh()
        if cards is None:
            cards = self.collect_cards()
        detections = []
        for c in cards:
            rec = self.cg.check_consistency(
                c["content"], layer="knowledge",
                exclude=c["id"], auto_flywheel=False)
            if rec.get("verdict") in ("REJECT", "DEFER", "BLINDSPOT"):
                detections.append({
                    "card": c["id"], "session": c.get("session"),
                    "verdict": rec.get("verdict"),
                    "reason": rec.get("reason"),
                    "with": [x.get("with") for x in rec.get("conflicts", [])
                             if x.get("with")][:5]})
        return {"checked": len(cards), "detections": detections,
                "clean": not detections}

    def closeout(self, subs: list[str] | None = None) -> dict:
        """收口报告——证据链五环节的集成出口（源—地图—断言—检查点—报告）：
        源=L2 细节在盘、地图=index（refresh 后）、断言=卡片结论、
        检查点=final_check、报告=本返回值。
        fingerprint=卡 ID 清单的 SHA-256 前缀（地图挂指纹）：
        同一批收口复验时指纹必须一致，卡集变化则指纹变化——防报告陈旧。
        未决项随报告透出，可落 L5（cg.add_unresolved）驱动下一轮。"""
        cards = self.collect_cards(subs=subs)
        chk = self.final_check(cards=cards)
        pend = self.pending_items(subs=subs)
        fp = hashlib.sha256(
            json.dumps(sorted(c["id"] for c in cards),
                       ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        return {"cards": len(cards), "pending": pend,
                "final_check": chk, "fingerprint": fp,
                "stats": self.stats()}

    # ================= 工具 =================

    @staticmethod
    def _brief(node) -> str:
        if isinstance(node, dict):
            c = node.get("content", "")
        else:
            c = str(node)
        return c.replace("\n", " ")[:100]

    def stats(self) -> dict:
        """三层各自的节点数——用来监控细节层是否在膨胀。"""
        n = {"L0_global": 0, "L1_card": 0, "L2_detail": 0}
        for nid in self.cg.index["nodes"]:
            fm, _ = self.cg._read(self.cg.index["nodes"][nid])
            lay, sess = fm.get("layer"), fm.get("session")
            if sess == "main":
                n["L0_global"] += 1
            elif lay == "knowledge" and sess:
                n["L1_card"] += 1
            elif lay == "contextual" and sess:
                n["L2_detail"] += 1
        return n


# ============================================================
# 自检：跑一遍完整四阶段流程，验证设计可用
# ============================================================
def selftest():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="orc_selftest_")
    om = OrcMemory(tmp, global_budget=1200, card_budget=600)
    print("=" * 60)
    print("阶段1 主代理锚定全局态")
    r = om.anchor_global("重构认证模块：JWT→session")
    print("  新会话？", not r["recovered"], "  全局节点:", r.get("node_id"))

    print("\n阶段2 派发子任务（上下文由主代理裁剪）")
    p = om.dispatch_prompt("subA", "迁移 login/logout", need=["认证"])
    print("  prompt 长度:", len(p), "字符")

    print("\n阶段3 子代理产出卡片 + 细节")
    a = om.submit("subA", "认证重构", "迁移 login/logout",
                  conclusion="已迁移 login/logout，共改 3 个文件",
                  evidence="auth/login.py:20-60；pytest 12 passed",
                  impact="调用方 2 处需同步改", pending="refresh_token 未处理",
                  detail="完整过程：先读 auth/login.py……（此处省略 2000 字）"
                         "命令输出：pytest 12 passed in 0.4s",
                  derived_from=[r.get("node_id")])
    print("  卡片:", a["card_id"], " 细节:", a["detail_id"])
    print("  冲突判定:", a["conflict"].get("verdict"),
          "| 需裁决:", a["needs_adjudication"])

    b = om.submit("subB", "认证重构", "refresh_token 处理",
                  conclusion="发现 refresh_token 与 session 机制冲突",
                  evidence="token/refresh.py:88",
                  impact="阻塞 subA 的完成",
                  pending="需主代理裁决：保留 refresh_token 还是废弃",
                  detail="完整分析……")
    print("  卡片:", b["card_id"], " 冲突:", b["conflict"].get("verdict"))

    print("\n阶段4 主代理收口（只读卡片）")
    cards = om.collect_cards()
    print("  收到卡片数:", len(cards))
    for c in cards:
        print("   -", c.get("session"), "|", c["content"].split("结论：")[-1][:44])

    print("\n  未决项清单（主代理的待办）:")
    for it in om.pending_items():
        print(f"   · [{it['from']}] {it['pending']}")

    print("\n合并进全局态")
    gid = om.merge_global("重构认证模块：JWT→session",
                          "subA 完成迁移；subB 提出 refresh_token 冲突待裁决",
                          derived_from=[a["card_id"], b["card_id"]])
    print("  新全局节点:", gid)

    print("\n  证据链反查（这个全局结论从哪来）:")
    fm, _ = om.drill_down(gid)
    print("   derived_from:", fm.get("derived_from"))

    print("\n三层统计:", om.stats())
    print("\n  细节是否泄漏进全局召回？")
    g = om.cg.recall("完整 过程 命令 输出", budget_tokens=3000, k=50, session="main")
    print("   session=main 命中条数:", len(g["pack"]),
          "（应为 2：锚定全局节点 + 合并后全局节点，不含 L2 细节）")
    print("=" * 60)
    return om


if __name__ == "__main__":
    selftest()
