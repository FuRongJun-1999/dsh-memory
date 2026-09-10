# -*- coding: utf-8 -*-
"""llm_channel.py · LLM 生成通道（通道 B）——白箱自举的初稿引擎

流程：《自举任务书_v0.1》T5——LLM 初稿 → 白箱校验器验证 → 测试回归 → 固化。
LLM 只做初稿（差异探索），质量裁决全部由白箱校验器（verifier）完成。

通道配置：
  - deepseek：api.deepseek.com（key 从 ZCode config.json 读取，已验证可用）
  - glm：open.bigmodel.cn（用户订阅 Coding Max 后填入 bigmodel_api_key）

用法：
  from llm_channel import generate_unit
  result = generate_unit("写一个快速排序单元（分治递归）")
  # → {"ok": bool, "code": str, "checks": [...], "task": ...}
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

CONFIG_PATH = os.path.expanduser("~/.zcode/v2/config.json")


def _load_key(provider_hint: str) -> tuple[str, str] | None:
    """从 ZCode config.json 读 (api_key, base_url)。"""
    try:
        d = json.load(open(CONFIG_PATH, encoding="utf-8"))
    except Exception:
        return None
    for name, p in d.get("provider", {}).items():
        opts = p.get("options", {})
        url = opts.get("baseURL", "")
        key = opts.get("apiKey", "")
        if provider_hint in name.lower() and key:
            return key, url.replace("/v1", "")
    return None


def _deepseek() -> tuple[str, str]:
    # 优先环境变量，回退 ZCode config
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k, "https://api.deepseek.com"
    r = _load_key("314007fa") or _load_key("deepseek")
    return (r[0], "https://api.deepseek.com") if r else (None, None)


def _glm() -> tuple[str, str]:
    k = os.environ.get("GLM_API_KEY") or os.environ.get("BIGMODEL_API_KEY")
    if k:
        return k, "https://open.bigmodel.cn/api/paas/v4"
    return None, None


SPEC_PROMPT = """你是白箱代码生成器。输出**纯 Python 函数**（def 开头），遵守白箱 KCCS 注释规范：
1. 只输出代码，不要解释、不要 markdown 围栏
2. 每个函数必须有中文 docstring，包含四要素标注：
   生效条件（何时适用）、子功能（做什么）、执行（怎么做）、不适用条件（何时不适用）
3. 纯函数：无 I/O、无副作用、不依赖全局状态
4. 只用标准库（list/dict/str/int/float/math/collections/typing）
5. 处理边界：空输入、单元素、重复元素

任务："""


def strip_code(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def generate_code(task_desc: str, provider: str = "auto",
                  model: str | None = None, max_tokens: int = 800) -> dict:
    """通道 B：LLM 生成代码初稿。返回 {"ok", "code", "provider", "error"}。"""
    providers = []
    if provider in ("auto", "deepseek"):
        providers.append(("deepseek", *_deepseek()))
    if provider in ("auto", "glm"):
        providers.append(("glm", *_glm()))
    for pname, key, base in providers:
        if not key:
            continue
        try:
            if pname == "glm":
                # glm-5.3-flash 为常开思考模型（不支持 disabled，仅 low/high/max）：
                # thinking=low 控制思考链长度；max_tokens 需覆盖 reasoning+答案
                payload = {
                    "model": model or "glm-5.3-flash",
                    "max_tokens": max(max_tokens, 2000),
                    "thinking": {"type": "low"},
                    "messages": [{"role": "user", "content": SPEC_PROMPT + task_desc}],
                }
            else:
                payload = {
                    "model": model or ("deepseek-chat" if pname == "deepseek"
                                       else "glm-4.6-flash"),
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": SPEC_PROMPT + task_desc}],
                }
            req = urllib.request.Request(
                base.rstrip("/") + "/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
            code = strip_code(body["choices"][0]["message"]["content"])
            if code:
                return {"ok": True, "code": code, "provider": pname}
        except Exception as e:
            continue
    return {"ok": False, "error": "全部通道不可用（deepseek/glm）", "code": ""}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    a = ap.parse_args()
    r = generate_code(a.task)
    print(json.dumps(r, ensure_ascii=False)[:300])
