# -*- coding: utf-8 -*-
"""环二试点·复现件：机械自检（禁词表 + 参数锚点）。
等效于主体侧 _coord/pilot_review.py，唯一差异=路径来源于环境变量。
环境：REPO=仓根；COORD=含 pilot_picks.json 的目录；LLM_JOB_RESULT=LLM 型蜂巢作业的 result.json 路径。
"""
import json
import os
import re

REPO = os.environ["REPO"]
COORD = os.environ["COORD"]
JOB = os.environ["LLM_JOB_RESULT"]
MDCG = os.path.join(REPO, "md_cg")
_d = json.load(open(JOB, encoding="utf-8"))
res = _d.get("result") if isinstance(_d.get("result"), dict) and "content" in _d["result"] else _d
content = res["content"]
print("JOB_KEYS " + str(list(_d.keys()))[:200])
picks = json.load(open(os.path.join(COORD, "pilot_picks.json"), encoding="utf-8"))
by_id = {p["id"]: p for p in picks}
lines = [ln.strip() for ln in content.split(chr(10)) if ln.strip()]
props = []
for ln in lines:
    m = re.match(r"^id=([A-Za-z0-9_]+)\s*\|\s*生效条件：(.*)$", ln)
    if not m:
        props.append({"id": None, "raw": ln, "ok": False, "why": "格式不符"})
        continue
    pid, cond = m.group(1), m.group(2).strip()
    pk = by_id.get(pid)
    if pk is None:
        props.append({"id": pid, "raw": ln, "ok": False, "why": "id 不在候选清单"})
        continue
    src = open(os.path.join(MDCG, pk["path"]), encoding="utf-8", errors="replace").read()
    seg = chr(10).join(src.split(chr(10))[max(0, pk["lineno"] - 1): pk["end"]])
    forbidden = [w for w in ["索引元条件", "源文件存在", "全时窗", "本地仓", "仓库存在"] if w in cond]
    toks = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", cond))
    overlap = sorted(t for t in toks if t in seg)
    blind = cond.startswith("BLINDSPOT")
    ok = (not forbidden) and (blind or len(overlap) >= 1)
    props.append({"id": pid, "path": pk["path"], "name": pk["name"],
                  "lineno": pk["lineno"], "condition": cond,
                  "overlap": overlap[:6], "forbidden": forbidden,
                  "blindspot": blind, "ok": ok,
                  "why": "禁止词" if forbidden else ("无参数锚点" if not ok and not blind else "")})
json.dump(props, open(os.path.join(COORD, "pilot_proposals.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
good = [p for p in props if p.get("ok")]
print("PROPOSALS " + str(len(props)) + " OK " + str(len(good))
      + " BLINDSPOT " + str(len([p for p in props if p.get("blindspot")]))
      + " REJECT " + str(len([p for p in props if not p.get("ok")])))
for p in props:
    print(("OK " if p.get("ok") else "NO ") + str(p.get("id")) + " " + str(p.get("name")))
