#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
knowledge_points · 知识点嵌套拆分器（v1.16 · 图架构增强 2/3）

设计者方向（2026-08-18）：知识点级嵌套——知识卡 ⊃ 知识点节点，
提高子图检索能力与精确度（问题直接命中知识点，而非整卡扫描）。

拆分：学科卡 content「N. 知识点名: 内容」→ 每知识点一个节点
  - 节点：layer=knowledge，tags=[knowledge_point, card:{卡id}, domain, edu]
    state_attributes={name, kind:"knowledge_point", parent_card, domain, edu_level}
  - 边：卡 -hierarchical-> 知识点（verified=1：知识点继承已验证卡）
  - 幂等：按 (parent_card, 知识点名) 查重

检索适配（配合 dex_respond 的 SQL 预过滤 + recursive_item_answer）：
  知识点节点带 knowledge_point 标签 → 卡扫描跳过（不拖慢）；知识点级精确命中
  由 find_points / recursive_item_answer 优先消费。

规模：75 卡 ≈ 2802 知识点（3 语言卡 + 元学科卡无「N.」格式，跳过）。
纯标准库 · 零外部依赖
"""

import json
import os
import re
import sqlite3
import sys
import time
from typing import Dict, List, Optional

DEFAULT_DB = r"C:\Users\FuRongJun\.dsh\profiles\web\data\lingshu.db"
HERE = os.path.dirname(os.path.abspath(__file__))

_KP_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)[:：]\s*(.*)$")


class KnowledgePointSplitter:
    """知识卡 content → 知识点节点 + 卡⊃知识点 hierarchical 边"""

    def __init__(self, db_path: str = DEFAULT_DB):
        """知识点库连接初始化（缺表自愈创建）。"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, timeout=15)
        self.conn.row_factory = sqlite3.Row

    # ---------------- 拆分 ----------------
    def parse_points(self, content: str) -> List[tuple]:
        """content → [(知识点名, 内容)]
        学科卡「N. 名: 内容」格式；语言卡「①名——内容；②…」格式（v1.16 补全）。"""
        points = []
        for ln in (content or "").split("\n"):
            m = _KP_RE.match(ln)
            if m:
                points.append((m.group(2).strip(), m.group(3).strip()))
        if points:
            return points
        return self.parse_lang_points(content or "")

    @staticmethod
    def parse_lang_points(content: str) -> List[tuple]:
        """语言卡「语言名 的规律性：①名——内容；②…；适用条件：…」格式"""
        points = []
        segs = re.split(r"([①②③④⑤⑥])", content)
        for i in range(1, len(segs), 2):
            seg = segs[i + 1] if i + 1 < len(segs) else ""
            seg = re.split(r"适用条件", seg)[0].strip().rstrip("。；;")
            if not seg:
                continue
            m = re.match(r"([^——：]{1,20})(?:——|：)(.*)", seg)
            if m:
                points.append((m.group(1).strip(), m.group(2).strip()))
            else:
                points.append((seg[:20], seg))
        m = re.search(r"适用条件[：:]([^。]*。?)", content)
        if m:
            points.append(("适用条件", m.group(1).strip()))
        return points

    def split_card(self, card_id: str, name: str, domain: str, edu: str,
                   content: str, card_imp: float, dry_run: bool = False) -> Dict:
        """拆一张卡 → 知识点节点 + hierarchical 边（幂等）"""
        c = self.conn.cursor()
        points = self.parse_points(content)
        # 已存在的知识点名（幂等）
        existing = set()
        for row in c.execute(
                "SELECT state_attributes FROM nodes WHERE tags LIKE ?",
                ("%card:" + card_id[:16] + "%",)).fetchall():
            try:
                nm = json.loads(row["state_attributes"] or "{}").get("name", "")
                if nm:
                    existing.add(nm)
            except Exception:
                pass
        added = 0
        skipped = 0
        now = time.time()
        for pname, pcontent in points:
            if pname in existing:
                skipped += 1
                continue
            if dry_run:
                added += 1
                continue
            pid = f"kp_{abs(hash(card_id + pname)) % 10**10}_{int(now * 1000)}"
            tags = ["knowledge_point", "subject_card",
                    f"card:{card_id[:16]}", f"domain:{domain}"]
            if edu:
                tags.append(f"edu:{edu}")
            sa = json.dumps({"name": pname, "kind": "knowledge_point",
                             "parent_card": card_id, "domain": domain,
                             "edu_level": edu}, ensure_ascii=False)
            cs = json.dumps({"observation_position": f"{name} 知识点（{pname}）",
                             "observation_tool": "学科知识卡拆分",
                             "time_window": [0.0, 9999999999.0],
                             "existence_constraint": "通用规律/知识（开源非盈利知识库）"},
                            ensure_ascii=False)
            c.execute(
                "INSERT INTO nodes (id, content, modality, spatial_coordinates, "
                "temporal_coordinate, condition_space, importance, confidence, layer, "
                "access_count, last_access, created_at, tags, semantic_coordinates, "
                "state_attributes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, pcontent, "text", "{}", now, cs,
                 round(card_imp * 0.9, 2), 0.6, "knowledge", 0, None, now,
                 json.dumps(tags, ensure_ascii=False), "{}", sa))
            # 卡 -hierarchical-> 知识点（verified：知识点继承已验证卡）
            eid = f"edge_kp_{abs(hash(card_id + pname)) % 10**10}_{int(now * 1000)}"
            c.execute(
                "INSERT INTO edges (id, source_id, target_id, relation_type, "
                "condition_space, confidence, weight, verified, created_at, "
                "last_verified, source_evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (eid, card_id, pid, "hierarchical", cs, 0.9, 0.9, 1, now,
                 now, "extracted"))
            added += 1
        if not dry_run:
            self.conn.commit()
        return {"card": name, "points": len(points), "added": added,
                "skipped": skipped}

    def split_all(self, dry_run: bool = False) -> Dict:
        """全库拆分（扫描 subject_card 卡）"""
        c = self.conn.cursor()
        report = {"cards": 0, "points_total": 0, "added": 0, "skipped": 0,
                  "no_format": []}
        cards = c.execute(
            "SELECT id, state_attributes, content, importance FROM nodes "
            "WHERE tags LIKE '%subject_card%' AND tags NOT LIKE '%knowledge_point%'").fetchall()
        for row in cards:
            sa = json.loads(row["state_attributes"] or "{}")
            name = sa.get("name", "")
            content = row["content"] or ""
            points = self.parse_points(content)
            if not points:
                report["no_format"].append(name or row["id"][:16])
                continue
            report["cards"] += 1
            report["points_total"] += len(points)
            r = self.split_card(row["id"], name, sa.get("domain", ""),
                                sa.get("edu_level", ""), content,
                                row["importance"] or 0.7, dry_run=dry_run)
            report["added"] += r["added"]
            report["skipped"] += r["skipped"]
        return report

    # ---------------- 知识点级精确检索 ----------------
    def find_points(self, query: str, limit: int = 8) -> List[Dict]:
        """问题 → 知识点精确命中（encode 规范词 LIKE 匹配 name/content）"""
        c = self.conn.cursor()
        fp = {}
        try:
            sys.path.insert(0, HERE)
            from semantic_translate import encode
            fp = encode(query)
        except Exception:
            pass
        scored = []
        for row in c.execute(
                "SELECT id, content, state_attributes, importance, tags "
                "FROM nodes WHERE tags LIKE '%knowledge_point%'").fetchall():
            sa = json.loads(row["state_attributes"] or "{}")
            name = sa.get("name", "")
            text = name + " " + (row["content"] or "")
            s = 0.0
            for term, w in fp.items():
                if term in text:
                    s += w
            # v1.16 术语兜底：学科/语言术语不在翻译表（encode 空），
            # 用问题窗口直接匹配知识点名（中文 2-4 字 + 英文词）
            if not fp or s == 0:
                _hit = False
                _chars = [ch for ch in query if "\u4e00" <= ch <= "\u9fff"]
                for i in range(len(_chars)):
                    for L in (4, 3, 2):
                        if i + L <= len(_chars):
                            w = "".join(_chars[i:i + L])
                            if w in name:
                                # 窗口越长越精确：4字 2.0 / 3字 1.5 / 2字 1.0
                                s += {4: 2.0, 3: 1.5, 2: 1.0}[L]
                                _hit = True
                                break
                    if _hit:
                        break
                if not _hit:
                    for _m in re.finditer(r"[A-Za-z]{2,}", query):
                        if _m.group(0).lower() in text.lower():
                            s += 1.5
                            break
            if s > 0:
                scored.append({"id": row["id"], "name": name,
                               "content": (row["content"] or "")[:200],
                               "score": round(s, 3),
                               "importance": row["importance"],
                               "card": sa.get("parent_card", "")[:16]})
        # 同分：短名优先（基础概念优先于长名细分，如「密度」>「密度矩阵与纠缠」）
        scored.sort(key=lambda x: (-x["score"], len(x["name"]), -x["importance"]))
        return scored[:limit]

    def close(self):
        """关闭数据库连接。"""
        self.conn.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sp = KnowledgePointSplitter()
    dry = "--dry-run" in sys.argv
    rep = sp.split_all(dry_run=dry)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    if not dry:
        hits = sp.find_points("水为什么烧开")
        print("\nfind_points('水为什么烧开'):")
        for h in hits[:5]:
            print("  %.2f %s: %s" % (h["score"], h["name"], h["content"][:40]))
    sp.close()
