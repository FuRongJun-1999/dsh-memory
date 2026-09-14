# -*- coding: utf-8 -*-
"""命名治理批次 spec 生成器（零第三方依赖）。

从四问审计报告（naming_report.json）挑桶取行，每行产一个蜂巢 spec：
一个 job = 一个节点的命名裁决（deepseek-flash / 思考 high / 300k 预算 / 600s）。

用法（本机示例，路径不硬编码——env 或 CLI 传入）：
    set NAMING_REPORT=d:\\...\\naming_report.json
    set MDCG_ROOT=d:\\...\\mdcg
    python gen_specs.py --bucket cond_感知系统_d94e90d2 --limit 10
    python gen_specs.py --bucket cond_感知系统_d94e90d2 --limit 10 --submit   # 生成并提交

产出：<out>/<序号>_<title>.spec.json（submit 模式追加提交并打印 job_id）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT_FILE = os.path.join(HERE, "system_prompt.txt")

SPEC_COMMON = {
    "thinking": {"type": "enabled"},
    "reasoning_effort": "high",
    "context_budget_tokens": 300000,
    "timeout_s": 600,
    "max_tokens": 4096,
    "temperature": 0.3,
}


def build_spec(title: str, bucket: str, node_md: str) -> dict:
    with open(SYSTEM_PROMPT_FILE, encoding="utf-8") as f:
        system_prompt = f.read()
    user_prompt = (
        f"节点 id：{title}\n"
        f"条件空间（来源桶）：{bucket}\n\n"
        "请阅读 context 中的节点文件（frontmatter 元数据 + 正文），"
        "按系统提示的规范与契约输出严格单行 JSON。"
    )
    spec = dict(SPEC_COMMON)
    spec.update(
        {
            "model": "deepseek-flash",
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "context_files": [node_md],  # 绝对路径，exec.py 按 isabs 直读
        }
    )
    return spec


def main() -> int:
    ap = argparse.ArgumentParser(description="命名治理批次 spec 生成器")
    ap.add_argument("--bucket", required=True, help="隔离区桶名（naming_report 的 bucket_sample）")
    ap.add_argument("--limit", type=int, default=10, help="本批节点数上限")
    ap.add_argument("--offset", type=int, default=0, help="桶内起始偏移（续批用）")
    ap.add_argument("--batch-tag", default=None, help="批次标签（默认 batch<limit>）")
    ap.add_argument("--report", default=os.environ.get("NAMING_REPORT", ""), help="naming_report.json 路径")
    ap.add_argument("--mdcg", default=os.environ.get("MDCG_ROOT", ""), help="认知图真源根目录")
    ap.add_argument("--out", default=os.path.join(HERE, "specs"), help="spec 输出目录")
    ap.add_argument("--submit", action="store_true", help="生成后调 hive.exe submit 提交")
    ap.add_argument("--hive", default=None, help="hive.exe 路径（--submit 时必填或 PATH 可寻）")
    args = ap.parse_args()

    if not args.report or not args.mdcg:
        print("缺 --report / --mdcg（或 env NAMING_REPORT / MDCG_ROOT）", file=sys.stderr)
        return 2

    with open(args.report, encoding="utf-8") as f:
        rows = json.load(f)["rows"]
    iso = [r for r in rows if r.get("class") == "隔离区" and r.get("bucket_sample") == args.bucket]
    batch = iso[args.offset : args.offset + args.limit]
    if not batch:
        print(f"桶 {args.bucket} 在 offset={args.offset} 后无隔离区行", file=sys.stderr)
        return 2

    tag = args.batch_tag or f"batch{args.limit}_off{args.offset}"
    out_dir = os.path.join(args.out, tag)
    os.makedirs(out_dir, exist_ok=True)

    hive_exe = args.hive or os.path.join(HERE, "..", "..", "target", "release", "hive.exe")
    ok = fail = 0
    for i, row in enumerate(batch):
        title = row["title"]
        node_md = os.path.join(args.mdcg, "knowledge", args.bucket, f"{title}.md")
        if not os.path.isfile(node_md):
            print(f"  SKIP(无源文件) {title}", file=sys.stderr)
            fail += 1
            continue
        spec = build_spec(title, args.bucket, node_md)
        spec_path = os.path.join(out_dir, f"{i:04d}_{title}.spec.json")
        with open(spec_path, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=1)
        if args.submit:
            r = subprocess.run(
                [hive_exe, "submit", "--spec", spec_path],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            line = (r.stdout or r.stderr).strip().splitlines()
            print(f"  submit {title} -> {line[-1] if line else r.returncode}")
            if r.returncode == 0:
                ok += 1
            else:
                fail += 1
        else:
            ok += 1
    print(f"完成：生成 {ok}，跳过/失败 {fail}，输出目录 {out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
