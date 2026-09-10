#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_wisdom · 智慧之书 → 灵枢主库迁移器（v1.16 · 统一信息差减少任务）

设计者方向（2026-08-18）：智慧之书库迁移进灵枢主库，灵枢成为完整工程实现
（灵魂=智能论3.2 协议层 + 神经系统功能类比），统一「信息差减少」任务。

知识真身分层（迁移数据源）：
  META 层：wisdom-book-cloud.db 30 元学科卡（存在论/条件论/智能论/学科映射等）
           87 边（31 causal + 56 similar，79 verified）
  SUBJECT 层：knowledge-base/*_knowledge.json 51 学科卡（E1-E4，23-81 知识点/卡）
           + programming_lang_cards.json 3 语言卡
  CAUSAL 层：causal_edge_candidates.json 学段递进因果边（R1 依赖型因果）
            + 元层 87 边中的 causal 边

迁移原则：
  - 幂等：按卡名（state_attributes.name）查重，已存在跳过
  - 可逆：迁移前备份目标库
  - 诚实：verified 标记如实保留（元层边已验证的保持 verified；
          学段递进边 R1 规则推导 → verified=0 confidence 0.75）
  - 报告：迁移统计输出 migrate_wisdom_report.json（可复现）
纯标准库 · 零外部依赖
"""

import json
import os
import shutil
import sqlite3
import sys
import time
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 默认路径（可参数覆盖）
DEFAULT_META_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wisdom-book-cloud.db")
DEFAULT_DST = r"C:\Users\FuRongJun\.dsh\profiles\web\data\lingshu.db"
DEFAULT_CAUSAL = os.path.join(HERE, "causal_edge_candidates.json")


class WisdomMigrator:
    """智慧之书 → 灵枢主库迁移器"""

    def __init__(self, meta_src: str = DEFAULT_META_SRC,
                 dst: str = DEFAULT_DST,
                 subject_dir: Optional[str] = None,
                 causal_src: str = DEFAULT_CAUSAL,
                 backup: bool = True):
        """迁移会话初始化：源库·目标库路径与游标准备。"""
        self.meta_src = meta_src
        self.dst = dst
        self.subject_dir = subject_dir or HERE
        self.causal_src = causal_src
        self.report: Dict = {"phases": {}}
        if backup and os.path.exists(dst):
            bak = dst + f".bak_migrate_{time.strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(dst, bak)
            self.report["backup"] = bak

    # ---------------- META 层：30 元卡 + 87 边 ----------------
    def migrate_meta(self) -> Dict:
        phase = {"nodes": 0, "edges": 0, "skipped_nodes": 0, "skipped_edges": 0}
        if not os.path.exists(self.meta_src):
            phase["error"] = f"源库不存在: {self.meta_src}"
            self.report["phases"]["meta"] = phase
            return phase
        src = sqlite3.connect(self.meta_src)
        dst = sqlite3.connect(self.dst)
        sc, dc = src.cursor(), dst.cursor()
        # 已存在的节点 id 集合（幂等）
        existing = {r[0] for r in dc.execute("SELECT id FROM nodes").fetchall()}
        # 搬节点
        rows = sc.execute("SELECT * FROM nodes").fetchall()
        cols = [r[1] for r in sc.execute("PRAGMA table_info(nodes)").fetchall()]
        for row in rows:
            nid = row[0]
            if nid in existing:
                phase["skipped_nodes"] += 1
                continue
            dc.execute(
                "INSERT INTO nodes (%s) VALUES (%s)" %
                (",".join(cols), ",".join("?" * len(cols))), row)
            phase["nodes"] += 1
        # 搬边（仅两端都存在于目标库的边）
        erows = sc.execute("SELECT * FROM edges").fetchall()
        ecols = [r[1] for r in sc.execute("PRAGMA table_info(edges)").fetchall()]
        eexisting = {r[0] for r in dc.execute("SELECT id FROM edges").fetchall()}
        for row in erows:
            eid, sid, tid = row[0], row[1], row[2]
            if eid in eexisting:
                phase["skipped_edges"] += 1
                continue
            if not dc.execute("SELECT id FROM nodes WHERE id=?", (sid,)).fetchone():
                phase["skipped_edges"] += 1
                continue
            if not dc.execute("SELECT id FROM nodes WHERE id=?", (tid,)).fetchone():
                phase["skipped_edges"] += 1
                continue
            dc.execute(
                "INSERT INTO edges (%s) VALUES (%s)" %
                (",".join(ecols), ",".join("?" * len(ecols))), row)
            phase["edges"] += 1
        dst.commit()
        # verified 统计
        phase["verified_edges"] = dc.execute(
            "SELECT COUNT(*) FROM edges WHERE verified=1").fetchone()[0]
        src.close()
        dst.close()
        self.report["phases"]["meta"] = phase
        return phase

    # ---------------- SUBJECT 层：51 学科卡 + 语言卡 ----------------
    def migrate_subject_cards(self) -> Dict:
        """学科卡批量迁移：逐识别卡解析→按名去重→写入目标 nodes 表，返回 nodes·skipped·files 迁移统计。"""
        phase = {"nodes": 0, "skipped": 0, "files": 0, "sources": []}
        dst = sqlite3.connect(self.dst)
        dc = dst.cursor()
        # 已存在的卡名（幂等，从 state_attributes.name 解析）
        existing_names = set()
        for (sa,) in dc.execute("SELECT state_attributes FROM nodes WHERE layer='knowledge'").fetchall():
            if not sa:
                continue
            try:
                existing_names.add(json.loads(sa).get("name", ""))
            except Exception:
                pass
        edu_level = {"E1": 1, "E2": 2, "E3": 3, "E4": 4, "E5": 5}
        files = sorted(f for f in os.listdir(self.subject_dir)
                       if f.endswith("_knowledge.json") or f == "programming_lang_cards.json")
        import re
        for fn in files:
            path = os.path.join(self.subject_dir, fn)
            try:
                d = json.load(open(path, encoding="utf-8"))
            except Exception as e:
                phase["sources"].append({"file": fn, "error": str(e)[:40]})
                continue
            phase["files"] += 1
            # dict（学科卡）或 list（语言卡）统一为卡列表
            cards = d if isinstance(d, list) else [d]
            for card in cards:
                content_map = card.get("content", {}) if isinstance(card, dict) else {}
                meta = card.get("meta", {}) if isinstance(card, dict) else {}
                name = meta.get("name") or card.get("name") or fn.replace("_knowledge.json", "")
                if not name or name in existing_names:
                    phase["skipped"] += 1
                    continue
                style = meta.get("style", "")
                m = re.search(r"(E\d)", style)
                edu = m.group(1) if m else card.get("edu_level")
                level = card.get("level") or {"E1": 1, "E2": 2, "E3": 3, "E4": 4, "E5": 5}.get(edu, 2)
                domain = (meta.get("domain") or card.get("domain")
                          or name.split(" ")[0])
                if content_map and isinstance(content_map, dict):
                    kps = list(content_map.items())
                    content_lines = [f"{name}（学科知识卡 · {len(kps)} 知识点）"]
                    content_lines += [f"{i+1}. {k}: {v}" for i, (k, v) in enumerate(kps)]
                else:
                    # 语言卡：response 驱动（trigger/action/counters）
                    resp = card.get("response", {})
                    content_lines = [f"{name}（语言卡 · {card.get('status', 'pending')}）"]
                    if isinstance(content_map, str) and content_map:
                        content_lines.append(content_map[:300])
                    content_lines.append("触发: " + str(resp.get("trigger", ""))[:200])
                    content_lines.append("动作: " + str(resp.get("action", ""))[:200])
                    content_lines.append("护栏: " + str(resp.get("counters", ""))[:200])
                nid = f"node_subject_{abs(hash(name)) % 10**10}_{int(time.time()*1000)}"
                tags = [f"domain:{domain}", f"level:L{level}",
                        f"status:verified", "subject_card",
                        f"edu:{edu}" if edu else "edu:unknown"]
                sa = json.dumps({"name": name, "domain": domain, "level": level,
                                 "edu_level": edu, "kind": "subject_card",
                                 "source": fn,
                                 "kp_count": len(content_map) if isinstance(content_map, dict) else 0},
                                ensure_ascii=False)
                cs = json.dumps({"observation_position": f"{name} 外部观测位",
                                 "observation_tool": "学科知识卡（知识综述）",
                                 "time_window": [0.0, 9999999999.0],
                                 "existence_constraint": "通用规律/知识（开源非盈利知识库）"},
                                ensure_ascii=False)
                now = time.time()
                dc.execute(
                    "INSERT INTO nodes (id, content, modality, spatial_coordinates, "
                    "temporal_coordinate, condition_space, importance, confidence, layer, "
                    "access_count, last_access, created_at, tags, semantic_coordinates, "
                    "state_attributes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (nid, "\n".join(content_lines), "text", "{}", now, cs, 0.8, 0.7,
                     "knowledge", 0, None, now, json.dumps(tags, ensure_ascii=False),
                     "{}", sa))
                phase["nodes"] += 1
                existing_names.add(name)
        dst.commit()
        dst.close()
        self.report["phases"]["subject"] = phase
        return phase

    # ---------------- CAUSAL 层：学段递进因果边 ----------------
    def migrate_causal_edges(self) -> Dict:
        phase = {"edges": 0, "skipped": 0}
        if not os.path.exists(self.causal_src):
            phase["error"] = f"因果边源不存在: {self.causal_src}"
            self.report["phases"]["causal"] = phase
            return phase
        cands = json.load(open(self.causal_src, encoding="utf-8"))
        dst = sqlite3.connect(self.dst)
        dc = dst.cursor()
        # name → id 映射（从 state_attributes；支持子串匹配——卡名长，candidate 名短）
        name2id = {}
        name_pool = []
        for (nid, sa) in dc.execute("SELECT id, state_attributes FROM nodes WHERE layer='knowledge'").fetchall():
            if not sa:
                continue
            try:
                nm = json.loads(sa).get("name", "")
            except Exception:
                nm = ""
            if nm:
                name2id[nm] = nid
                name_pool.append((nm, nid))
        def resolve(name: str) -> Optional[str]:
            if not name:
                return None
            if name in name2id:
                return name2id[name]
            # 子串匹配：candidate 短名 ⊂ 卡长名
            for nm, nid in name_pool:
                if name in nm or nm in name:
                    return nid
            return None
        # 元层卡的 name 在 state_attributes 里
        for cand in cands:
            a, b = cand.get("a", ""), cand.get("b", "")
            sid, tid = resolve(a), resolve(b)
            if not sid or not tid:
                phase["skipped"] += 1
                continue
            if dc.execute("SELECT id FROM edges WHERE source_id=? AND target_id=? "
                          "AND relation_type=?", (sid, tid, cand.get("kind", "causal"))).fetchone():
                phase["skipped"] += 1
                continue
            eid = f"edge_causal_{abs(hash(a+b)) % 10**10}_{int(time.time()*1000)}"
            cs = json.dumps({"observation_position": "教育体系学段递进/学科归属",
                             "observation_tool": f"{cand.get('rule', 'R1')} 规则",
                             "time_window": [0.0, 9999999999.0],
                             "existence_constraint": cand.get("note", "")},
                            ensure_ascii=False)
            now = time.time()
            dc.execute(
                "INSERT INTO edges (id, source_id, target_id, relation_type, condition_space, "
                "confidence, weight, verified, created_at, last_verified, source_evidence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (eid, sid, tid, cand.get("kind", "causal"), cs,
                 cand.get("confidence", 0.75), 0.75,
                 0, now, None, "inferred"))
            phase["edges"] += 1
        dst.commit()
        dst.close()
        self.report["phases"]["causal"] = phase
        return phase

    # ---------------- 元学科聚合卡：7 张元学科卡 ----------------
    def migrate_meta_discipline_cards(self,
                                      skeleton_src: Optional[str] = None) -> Dict:
        """历史学/地理学/政治学/语言学/计算机科学/工程学/模拟电子技术 聚合卡。
        数据源：knowledge_skeleton 子学科知识点并集（骨架锚点，内容待填充——
        诚实标注，不伪造具体知识内容）。"""
        phase = {"nodes": 0, "skipped": 0, "sources": []}
        skeleton = json.load(open(skeleton_src or os.path.join(HERE, "knowledge_skeleton.json"),
                                  encoding="utf-8"))
        meta_disciplines = {
            "计算机科学": ["程序设计", "数据结构", "算法设计与分析", "操作系统",
                        "计算机网络", "数据库系统", "编译原理", "软件工程",
                        "计算机组成原理", "人工智能"],
            "工程学": ["材料力学", "电路原理", "模拟电子技术", "数字电路",
                     "工程制图", "土木工程基础"],
            "语言学": ["古代汉语", "现代汉语", "文学理论"],
            "历史学": ["历史"],
            "地理学": ["地理"],
            "政治学": ["政治"],
            "模拟电子技术": ["模拟电子技术"],
        }
        dst = sqlite3.connect(self.dst)
        dc = dst.cursor()
        existing_names = set()
        for (sa,) in dc.execute("SELECT state_attributes FROM nodes WHERE layer='knowledge'").fetchall():
            if not sa:
                continue
            try:
                existing_names.add(json.loads(sa).get("name", ""))
            except Exception:
                pass
        for name, subs in meta_disciplines.items():
            if name in existing_names:
                phase["skipped"] += 1
                continue
            kps = {}
            for sub in subs:
                sub_data = skeleton.get(sub)
                if not sub_data:
                    continue
                if isinstance(sub_data, dict):
                    for stage, units in sub_data.items():
                        for unit in units:
                            for kp in unit.get("知识点", []):
                                kps.setdefault(kp, f"[{sub}·{stage}] 骨架锚点，内容待填充")
                elif isinstance(sub_data, list):
                    for unit in sub_data:
                        for kp in unit.get("知识点", []):
                            kps.setdefault(kp, f"[{sub}] 骨架锚点，内容待填充")
            if not kps:
                phase["sources"].append({"name": name, "error": "骨架无子学科知识点"})
                continue
            content_lines = [f"{name}（元学科聚合卡 · {len(kps)} 知识点，骨架锚点待填充）"]
            content_lines += [f"{i+1}. {k}: {v}" for i, (k, v) in enumerate(kps.items())]
            nid = f"node_meta_{abs(hash(name)) % 10**10}_{int(time.time()*1000)}"
            tags = [f"domain:{name}", "level:L4", "status:pending", "subject_card",
                    "meta_discipline"]
            sa = json.dumps({"name": name, "domain": name, "level": 4,
                             "kind": "meta_discipline", "source": "skeleton 聚合",
                             "kp_count": len(kps)}, ensure_ascii=False)
            cs = json.dumps({"observation_position": f"{name} 学科体系观测位",
                             "observation_tool": "课标骨架聚合",
                             "time_window": [0.0, 9999999999.0],
                             "existence_constraint": "学科归属/结构关系（骨架锚点，内容待填充）"},
                            ensure_ascii=False)
            now = time.time()
            dc.execute(
                "INSERT INTO nodes (id, content, modality, spatial_coordinates, "
                "temporal_coordinate, condition_space, importance, confidence, layer, "
                "access_count, last_access, created_at, tags, semantic_coordinates, "
                "state_attributes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (nid, "\n".join(content_lines), "text", "{}", now, cs, 0.7, 0.5,
                 "knowledge", 0, None, now, json.dumps(tags, ensure_ascii=False),
                 "{}", sa))
            phase["nodes"] += 1
            existing_names.add(name)
        dst.commit()
        dst.close()
        self.report["phases"]["meta_discipline"] = phase
        return phase

    # ---------------- 学段拆分卡：骨架×综合卡 → 学段卡 ----------------
    def migrate_stage_cards(self, skeleton_src: Optional[str] = None) -> Dict:
        """knowledge_skeleton.json 学科×学段 × 综合卡知识点 → 学段卡。
        补历史/地理/语文/英语/政治的学段拆分（33 条因果边跳过的原因）。
        卡名含学段（如 初中历史）→ causal_edge_candidates 子串匹配自动接通。"""
        phase = {"nodes": 0, "skipped": 0, "files": 0, "sources": []}
        skeleton = json.load(open(skeleton_src or os.path.join(HERE, "knowledge_skeleton.json"),
                                  encoding="utf-8"))
        # 学科 → (综合卡文件, 学段→卡名规则)
        card_files = {
            "语文": "chinese_knowledge.json",
            "英语": "english_knowledge.json",
            "历史": "history_knowledge.json",
            "地理": "geography_knowledge.json",
            "政治": "politics_knowledge.json",
        }
        name_rule = {
            "政治": lambda s: "小学道德与法治" if s == "小学" else (
                "初中道德与法治" if s == "初中" else "高中思想政治"),
        }
        dst = sqlite3.connect(self.dst)
        dc = dst.cursor()
        existing_names = set()
        for (sa,) in dc.execute("SELECT state_attributes FROM nodes WHERE layer='knowledge'").fetchall():
            if not sa:
                continue
            try:
                existing_names.add(json.loads(sa).get("name", ""))
            except Exception:
                pass
        import re
        for subject, fn in card_files.items():
            path = os.path.join(self.subject_dir, fn)
            if not os.path.exists(path):
                phase["sources"].append({"subject": subject, "error": "综合卡缺失"})
                continue
            try:
                content_map = json.load(open(path, encoding="utf-8")).get("content", {})
            except Exception as e:
                phase["sources"].append({"subject": subject, "error": str(e)[:40]})
                continue
            stages = skeleton.get(subject, {})
            for stage, units in stages.items():
                kp_names = []
                for unit in units:
                    kp_names.extend(unit.get("知识点", []))
                kps = {k: content_map[k] for k in kp_names if k in content_map}
                if not kps:
                    phase["sources"].append({"subject": subject, "stage": stage,
                                             "error": "综合卡无对应知识点"})
                    continue
                name = name_rule.get(subject, lambda s: s + subject)(stage)
                if name in existing_names:
                    phase["skipped"] += 1
                    continue
                domain = subject
                edu = {"小学": "E1", "初中": "E2", "高中": "E3"}.get(stage, "E2")
                level = {"E1": 1, "E2": 2, "E3": 3}.get(edu, 2)
                content_lines = [f"{name}（学段知识卡 · {len(kps)} 知识点，源自骨架 {subject}.{stage}）"]
                content_lines += [f"{i+1}. {k}: {v}" for i, (k, v) in enumerate(kps.items())]
                nid = f"node_stage_{abs(hash(name)) % 10**10}_{int(time.time()*1000)}"
                tags = [f"domain:{domain}", f"level:L{level}", f"status:verified",
                        "subject_card", f"edu:{edu}", "stage_card"]
                sa = json.dumps({"name": name, "domain": domain, "level": level,
                                 "edu_level": edu, "kind": "stage_card",
                                 "source": "skeleton+%s" % fn,
                                 "kp_count": len(kps)}, ensure_ascii=False)
                cs = json.dumps({"observation_position": f"{name} 外部观测位",
                                 "observation_tool": "课标骨架×综合卡",
                                 "time_window": [0.0, 9999999999.0],
                                 "existence_constraint": "通用规律/知识（开源非盈利知识库）"},
                                ensure_ascii=False)
                now = time.time()
                dc.execute(
                    "INSERT INTO nodes (id, content, modality, spatial_coordinates, "
                    "temporal_coordinate, condition_space, importance, confidence, layer, "
                    "access_count, last_access, created_at, tags, semantic_coordinates, "
                    "state_attributes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (nid, "\n".join(content_lines), "text", "{}", now, cs, 0.8, 0.7,
                     "knowledge", 0, None, now, json.dumps(tags, ensure_ascii=False),
                     "{}", sa))
                phase["nodes"] += 1
                existing_names.add(name)
        dst.commit()
        dst.close()
        self.report["phases"]["stage"] = phase
        return phase

    # ---------------- 总报告 ----------------
    def run(self, meta: bool = True, subject: bool = True,
            causal: bool = True, stage: bool = True,
            meta_discipline: bool = True, persist: bool = True) -> Dict:
        """执行完整迁移流水线：meta→学科卡→因果→阶段→纪律→持久化（各相由布尔开关独立启停）。"""
        if meta:
            self.migrate_meta()
        if subject:
            self.migrate_subject_cards()
        if stage:
            self.migrate_stage_cards()
        if meta_discipline:
            self.migrate_meta_discipline_cards()
        if causal:
            self.migrate_causal_edges()
        # 目标库终态统计
        dst = sqlite3.connect(self.dst)
        dc = dst.cursor()
        self.report["dst_final"] = {
            "nodes": dc.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "knowledge_nodes": dc.execute(
                "SELECT COUNT(*) FROM nodes WHERE layer='knowledge'").fetchone()[0],
            "edges": dc.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "causal_edges": dc.execute(
                "SELECT COUNT(*) FROM edges WHERE relation_type='causal'").fetchone()[0],
            "verified_edges": dc.execute(
                "SELECT COUNT(*) FROM edges WHERE verified=1").fetchone()[0],
        }
        dst.close()
        self.report["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.report["source"] = "migrate_wisdom v1.16（智慧之书→灵枢主库）"
        if persist:
            path = os.path.join(HERE, "migrate_wisdom_report.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.report, f, ensure_ascii=False, indent=2)
            self.report["report_path"] = path
        return self.report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    mig = WisdomMigrator()
    rep = mig.run()
    print(json.dumps(rep, ensure_ascii=False, indent=2))
