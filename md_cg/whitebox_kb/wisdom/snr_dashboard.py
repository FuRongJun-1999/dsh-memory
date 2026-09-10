#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snr_dashboard · 信噪比仪表盘（v1.16 · C 维进化 8.0→9.0）
========================================================
递归反思协议 3.12 终裁产物。反思链：
  depth1：八机制（信息分层/白箱校验/重要性加权/翻译体系/诚实边界/主动遗忘/因果验证/自生长）
          覆盖八类噪声抑制 → 缺全局监控指标 → 可建仪表盘
  depth2：「self 路由 ≠ 注入信噪比」——须看「self 且答对」（route+质量结合，
          呼应 1000 条测试别名率 58% 分析：self 也可能答非所问）
  depth3：structural_blindspot 警示——递归到上限仍在细化指标口径 = 设计噪音本身。
          终裁：收敛为最小实现，聚合现成信号，零新增采集。

四类信噪比信号（全部现成数据，无新采集）：
  ① 压缩信噪比（知识层） compression_ratio = 纯知识体积 / 原始源体积
     已知里程碑：zhwiki 7.1GB → 纯知识 1.78MB ≈ 4000:1（极致信噪比压缩）
  ② 注入质量率（对话层） inject_quality = (route==self 且 score>=0.5) / (route==self)
     depth2 修正：不看 route 分布，看「self 且答对」——self 路由也可能答非所问，
     须结合质量闸门（1000 条测试逐条评分 score）
  ③ 图谱信噪比（知识层） graph_snr = verified 边 / (verified 边 + open 被拒路径)
     verified=物理基底/验证单元复核过的边；open 被拒路径=系统失败输入（噪声候选）
  ④ 记忆清理率（记忆层） memory_purge = archived 节点 / CONTEXT 节点总数
     主动遗忘（forget_advisor）清理的噪声记忆占比——可逆归档

输出：snr_report.json（指标 + 趋势 + 瓶颈建议）
运行：lifecycle 维护周期（MAINT_INTERVAL）自动执行；亦可独立命令行运行
消费：自我认知循环（self_cognition）——五维标尺 C 维的客观输入
纯标准库 · 零外部依赖（与 lifecycle/causal_discover 一致）
"""

import json
import os
import time
from typing import Dict, List, Optional


class SnrDashboard:
    """信噪比仪表盘：聚合四类信号 → JSON 报告（含趋势与瓶颈建议）"""

    # 知识压缩里程碑（measured 2026-08：zhwiki dump → 智慧之书纯知识库）
    DEFAULT_RAW_BYTES = 7.1e9        # 原始源：zhwiki 约 7.1GB
    DEFAULT_PURE_BYTES = 1.78e6      # 纯知识：约 1.78MB
    REPORT_NAME = "snr_report.json"

    def __init__(self, engine=None, dialogue_results: Optional[str] = None,
                 raw_bytes: float = DEFAULT_RAW_BYTES,
                 pure_bytes: float = DEFAULT_PURE_BYTES,
                 report_dir: Optional[str] = None):
        """信噪比面板初始化：原始字节与纯知识字节统计挂入。"""
        self.engine = engine
        if dialogue_results is None:
            # 自动探测：同目录（knowledge-base 工作区）下的 1000 条测试结果
            cand = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "dialogue_1000_results.json")
            dialogue_results = cand if os.path.exists(cand) else None
        self.dialogue_results = dialogue_results
        self.raw_bytes = raw_bytes
        self.pure_bytes = pure_bytes
        self.report_dir = report_dir or os.path.dirname(os.path.abspath(__file__))

    # ---------- ① 压缩信噪比 ----------
    def compression_snr(self) -> Dict:
        """压缩信噪比口径：raw_bytes/pure_bytes 比值报告。"""
        ratio = (self.raw_bytes / self.pure_bytes) if self.pure_bytes > 0 else 0.0
        return {"raw_bytes": self.raw_bytes, "pure_bytes": self.pure_bytes,
                "ratio": round(ratio, 1)}

    # ---------- ② 注入质量率（depth2 修正：self 且答对） ----------
    def inject_quality(self) -> Dict:
        path = self.dialogue_results
        if not path or not os.path.exists(path):
            return {"available": False, "note": "无对话测试结果（dialogue_1000_results.json）"}
        try:
            with open(path, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception as e:
            return {"available": False, "note": f"读取失败: {e}"}
        total = len(items)
        self_cnt = 0
        self_ok = 0      # self 且答对（score>=0.5：客观 keys 命中 或 主观正确）
        self_full = 0    # self 且完全答对（score>=1.0）
        route_cnt: Dict[str, int] = {}
        for it in items:
            r = it.get("route", "?")
            route_cnt[r] = route_cnt.get(r, 0) + 1
            if r == "self":
                self_cnt += 1
                s = it.get("score", 0.0)
                if s >= 0.5:
                    self_ok += 1
                if s >= 1.0:
                    self_full += 1
        return {"available": True, "total": total, "route_dist": route_cnt,
                "self_count": self_cnt,
                "self_ok_count": self_ok,
                "inject_quality": round(self_ok / self_cnt, 4) if self_cnt else None,
                "self_full_rate": round(self_full / self_cnt, 4) if self_cnt else None,
                "note": "注入质量率 = self 且答对(score>=0.5) / self 总数（route+质量结合）"}

    # ---------- ③ 图谱信噪比 ----------
    def graph_snr(self) -> Dict:
        if self.engine is None:
            return {"available": False, "note": "无 engine"}
        verified = 0
        rejected_open = 0
        try:
            stats = self.engine.store.get_stats()
            verified = stats.get("verified_edges", 0)
        except Exception:
            pass
        try:
            paths = self.engine.list_rejected_paths(status="open") or []
            rejected_open = len(paths)
        except Exception:
            pass
        denom = verified + rejected_open
        return {"available": True, "verified_edges": verified, "rejected_open": rejected_open,
                "graph_snr": round(verified / denom, 4) if denom else None}

    # ---------- ④ 记忆清理率 ----------
    def memory_purge(self) -> Dict:
        if self.engine is None:
            return {"available": False, "note": "无 engine"}
        try:
            conn = self.engine.store.conn
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM nodes WHERE layer='context'")
            context_total = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM nodes WHERE layer='context' AND tags LIKE '%archived%'")
            archived = c.fetchone()[0]
        except Exception as e:
            return {"available": False, "note": f"查询失败: {e}"}
        return {"available": True, "context_total": context_total, "archived": archived,
                "memory_purge": round(archived / context_total, 4) if context_total else None}

    # ---------- 趋势（对比上次报告） ----------
    def _trend(self, cur: Dict) -> Dict:
        """趋势对比：读上一份信噪报告作基线，无基线时返回首跑标注。"""
        prev_path = os.path.join(self.report_dir, self.REPORT_NAME)
        if not os.path.exists(prev_path):
            return {"note": "首次运行，无基线"}
        try:
            with open(prev_path, "r", encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            return {"note": "基线读取失败"}
        trend = {}
        for key in ("inject_quality", "graph_snr", "memory_purge", "compression_ratio"):
            pk = prev.get(key)
            ck = cur.get(key)
            if pk is not None and ck is not None:
                trend[key] = {"prev": pk, "current": ck, "delta": round(ck - pk, 4)}
        return trend

    # ---------- 瓶颈建议（规则式） ----------
    @staticmethod
    def _bottleneck(cur: Dict) -> List[str]:
        """瓶颈建议：按注入质量率、图谱信噪比等指标阈值生成改进建议清单。"""
        advice = []
        iq = cur.get("inject_quality")
        if iq is not None and iq < 0.7:
            advice.append(f"注入质量率 {iq:.1%} < 70%：自处理答非所问偏高，"
                          "建议用低分条目补卡/修正卡内容（含条件标注）")
        gs = cur.get("graph_snr")
        if gs is not None and gs < 0.9:
            advice.append(f"图谱信噪比 {gs:.1%} < 90%：存在 open 被拒路径，"
                          "建议走 causal_discover 验证闭环修复")
        mp = cur.get("memory_purge")
        if mp is not None and mp > 0.4:
            advice.append(f"记忆清理率 {mp:.1%} > 40%：噪声记忆占比过高，"
                          "建议 consolidate 归档节点或收紧 forget_advisor 阈值")
        if not advice:
            advice.append("各维度信噪比良好，维持现有八机制")
        return advice

    # ---------- 主入口 ----------
    def run(self, persist: bool = True) -> Dict:
        report = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "snr_dashboard v1.16（C 维进化·递归反思 3.12 终裁）",
            "compression_ratio": self.compression_snr()["ratio"],
            "inject_quality": None,
            "graph_snr": None,
            "memory_purge": None,
            "signals": {
                "compression": self.compression_snr(),
                "inject": self.inject_quality(),
                "graph": self.graph_snr(),
                "memory": self.memory_purge(),
            },
        }
        inj = report["signals"]["inject"]
        if inj.get("available"):
            report["inject_quality"] = inj.get("inject_quality")
        g = report["signals"]["graph"]
        if g.get("available"):
            report["graph_snr"] = g.get("graph_snr")
        m = report["signals"]["memory"]
        if m.get("available"):
            report["memory_purge"] = m.get("memory_purge")
        report["trend"] = self._trend(report)
        report["bottleneck"] = self._bottleneck(report)
        if persist:
            path = os.path.join(self.report_dir, self.REPORT_NAME)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
                report["report_path"] = path
            except Exception as e:
                report["report_path"] = f"写入失败: {e}"
        return report


if __name__ == "__main__":
    import sys
    dlg = sys.argv[1] if len(sys.argv) > 1 else None
    dash = SnrDashboard(dialogue_results=dlg)
    out = dash.run(persist=True)
    print(json.dumps(out, ensure_ascii=False, indent=2))
