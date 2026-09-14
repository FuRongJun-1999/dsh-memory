# -*- coding: utf-8 -*-
"""灵枢蜂巢 · 默认 LLM 执行器（零第三方依赖，Python 标准库）。

契约（与 hive/src/exec.rs 头注释一致）：
    入参   argv[1] = job 目录
    读     spec.json（model / system_prompt / user_prompt / context_files / ...）
    写     result.json —— 成功与 API 错误都写，error 字段区分：
             {"ok": true, "content": "...", "usage": {...}, "model": "...",
              "finished_ts": ..., "duration_s": ...}
             {"ok": false, "error": "...", ...}
           log.txt —— 详细日志（stdout/stderr 保持安静，不污染 serve 控制台）
    退出码 0 成功 / 2 规格错 / 3 API 错误

API：OpenAI 兼容 chat/completions（GLM 同形）。
env：HIVE_API_KEY（必填，缺失即 fail）、
     HIVE_API_BASE（默认 https://open.bigmodel.cn/api/paas/v4）。

HTTPS 之所以在这里而不是 rust：TLS 无第三方库在纯 std rust 不可行（D-005）；
Python urllib 走系统证书，零依赖达成。执行器是可替换子进程——换 curl /
其它 SDK 宿主时，保持「读 spec.json、写 result.json」契约即可。

上下文拼接：context_files 逐个读入，以
    <context path="...">
    ...文件全文...
    </context>
块追加在 user_prompt 之前（AI 侧归一由调用方在 spec 里完成，执行器不加工）。
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request

DEFAULT_API_BASE = "https://open.bigmodel.cn/api/paas/v4"
EXIT_OK, EXIT_SPEC, EXIT_API = 0, 2, 3


def log(job_dir: str, msg: str) -> None:
    with open(os.path.join(job_dir, "log.txt"), "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


def write_result(job_dir: str, payload: dict) -> None:
    with open(os.path.join(job_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def read_spec(job_dir: str) -> dict:
    with open(os.path.join(job_dir, "spec.json"), encoding="utf-8") as f:
        return json.load(f)


def build_messages(spec: dict, job_dir: str) -> list:
    user_prompt = spec.get("user_prompt", "")
    ctx_blocks = []
    base = spec.get("workdir") or os.getcwd()
    for rel in spec.get("context_files") or []:
        path = rel if os.path.isabs(rel) else os.path.join(base, rel)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            log(job_dir, f"context 读取失败 {path}: {e}")
            ctx_blocks.append(f'<context path="{rel}" error="读取失败: {e}"></context>')
            continue
        ctx_blocks.append(f'<context path="{rel}">\n{text}\n</context>')
    prompt = ("\n\n".join(ctx_blocks) + "\n\n" + user_prompt) if ctx_blocks else user_prompt
    messages = []
    sys_prompt = (spec.get("system_prompt") or "").strip()
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages


def call_llm(spec: dict, messages: list) -> dict:
    """调 chat/completions；返回归一化 result（ok 字段由调用方补）。"""
    api_base = os.environ.get("HIVE_API_BASE", DEFAULT_API_BASE).rstrip("/")
    api_key = os.environ.get("HIVE_API_KEY", "")
    if not api_key:
        raise RuntimeError("HIVE_API_KEY 未设置（执行器环境缺密钥）")
    url = f"{api_base}/chat/completions"
    body = {"model": spec["model"], "messages": messages}
    if spec.get("max_tokens"):
        body["max_tokens"] = spec["max_tokens"]
    if spec.get("temperature") is not None:
        body["temperature"] = spec["temperature"]
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    timeout = min(float(spec.get("timeout_s") or 300), 600.0)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return {
        "content": content,
        "usage": data.get("usage") or {},
        "model": data.get("model") or spec["model"],
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: exec.py <job_dir>", file=sys.stderr)
        return EXIT_SPEC
    job_dir = sys.argv[1]
    t0 = time.time()
    try:
        spec = read_spec(job_dir)
    except Exception as e:  # noqa: BLE001 —— 顶层兜底必须写 result
        write_result(job_dir, {"ok": False, "error": f"spec 读取失败: {e}"})
        return EXIT_SPEC

    try:
        messages = build_messages(spec, job_dir)
        n_ctx = len(spec.get("context_files") or [])
        log(job_dir, f"开始调用 model={spec.get('model')} ctx={n_ctx}")
        out = call_llm(spec, messages)
        out.update(
            {
                "ok": True,
                "finished_ts": time.time(),
                "duration_s": round(time.time() - t0, 2),
            }
        )
        write_result(job_dir, out)
        tokens = out.get("usage", {}).get("total_tokens")
        log(job_dir, f"完成 tokens={tokens}")
        return EXIT_OK
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:2000]
        except Exception:  # noqa: BLE001
            detail = ""
        write_result(
            job_dir,
            {
                "ok": False,
                "error": f"HTTP {e.code}: {detail or e.reason}",
                "finished_ts": time.time(),
                "duration_s": round(time.time() - t0, 2),
            },
        )
        log(job_dir, f"API HTTP 错误 {e.code}")
        return EXIT_API
    except Exception as e:  # noqa: BLE001
        write_result(
            job_dir,
            {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "finished_ts": time.time(),
                "duration_s": round(time.time() - t0, 2),
            },
        )
        log(job_dir, "异常:\n" + traceback.format_exc())
        return EXIT_API


if __name__ == "__main__":
    sys.exit(main())
