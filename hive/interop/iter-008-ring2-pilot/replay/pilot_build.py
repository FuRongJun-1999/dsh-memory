# -*- coding: utf-8 -*-
"""环二试点·复现件：抽符号 -> 取源码片段 -> 写提示词/picks/spec。
等效于主体侧 _coord/pilot_build.py，唯一差异=路径来源改为环境变量（避免本机绝对路径入库）。
环境：REPO=仓根（含 md_cg/）；COORD=输出目录；PILOT_SEED 默认 pilot-v2；PILOT_N 默认 60；PILOT_TAKE 默认 10。
"""
import json
import os
import sys

REPO = os.environ["REPO"]
COORD = os.environ["COORD"]
MDCG = os.path.join(REPO, "md_cg")
SEED = os.environ.get("PILOT_SEED", "pilot-v2")
N = int(os.environ.get("PILOT_N", "60"))
TAKE = int(os.environ.get("PILOT_TAKE", "10"))
os.makedirs(COORD, exist_ok=True)
sys.path.insert(0, REPO)
from md_cg import comment_gate  # noqa: E402

pl = comment_gate.plan_sources(MDCG, n=N, seed=SEED, skip_dirs=["whitebox_kb"])
print("SAMPLED " + str(pl["sampled"]) + " EXAMINED " + str(pl["examined"])
      + " CANDS " + str(pl["candidates"]) + " FAMILIES " + str(pl["families"]))


def usable(it):
    """剔除文件级符号与 bench 面噪声，保留真实功能符号。"""
    base = os.path.basename(it["code_ref"]["path"])[:-3]
    nm = str(it["name"])
    if nm == base or nm.startswith("__"):
        return False
    if base.startswith("bench"):
        return False
    return True


items = [it for it in pl["items"] if usable(it)][:TAKE]
print("USABLE " + str(len(items)))
picks = []
for it in items:
    ref = it["code_ref"]
    p = os.path.join(MDCG, ref["path"])
    lines = open(p, encoding="utf-8", errors="replace").read().split(chr(10))
    seg = lines[max(0, ref["lineno"] - 1): min(len(lines), ref["end"])]
    doc = ""
    for ln in seg[:6]:
        if ln.strip().startswith('"""') or ln.strip().startswith("'''"):
            doc = ln.strip()
            break
    picks.append({"id": it["id"], "path": ref["path"], "name": it["name"],
                  "kind": it["kind"], "lineno": ref["lineno"], "end": ref["end"],
                  "doc_head": doc[:120], "src": chr(10).join(seg)[:1200]})
    print("PICK " + ref["path"] + ":" + str(ref["lineno"]) + " " + str(it["name"]))

out = ["你是白箱代码评审助手。下面给出 N 个 Python 符号的源码片段。",
       "请为**每一个**符号写一行**功能级『生效条件』**——即「这段代码在何种输入/状态下正确」。",
       "硬要求：",
       "1. 只写功能前置条件，**禁止**写索引元条件（如『源文件存在于本地仓』『全时窗成立』）；",
       "2. 必须是可机械复核的判据（有输入/状态/取值范围），不要写『常用条件默认省略』这类空话；",
       "3. 每条一行，格式严格为：id=<id> | 生效条件：<一句话>；",
       "4. 若确实无法从片段判定，写 id=<id> | 生效条件：BLINDSPOT：缺证据（说明缺什么）；",
       "5. 不要输出任何其它文字、不要输出注释符号、不要用代码围栏。",
       "",
       "符号清单："]
for pk in picks:
    out.append("### id=" + pk["id"] + " | " + pk["kind"] + " | " + pk["path"]
               + ":" + str(pk["lineno"]) + "-" + str(pk["end"]) + " | name=" + pk["name"])
    if pk["doc_head"]:
        out.append("doc: " + pk["doc_head"])
    out.append("[src begin]")
    out.append(pk["src"])
    out.append("[src end]")
prompt = chr(10).join(out)
open(os.path.join(COORD, "pilot_prompt.txt"), "w", encoding="utf-8").write(prompt)
spec = {"model": "deepseek-flash", "user_prompt": prompt, "timeout_s": 900,
        "max_tokens": 200000, "cwd": REPO}
open(os.path.join(COORD, "pilot_spec.json"), "w", encoding="utf-8").write(
    json.dumps(spec, ensure_ascii=False, indent=1))
open(os.path.join(COORD, "pilot_picks.json"), "w", encoding="utf-8").write(
    json.dumps(picks, ensure_ascii=False, indent=1))
print("PROMPT_LEN " + str(len(prompt)))
