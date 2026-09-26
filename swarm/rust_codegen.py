# -*- coding: utf-8 -*-
"""rust_codegen · Rust 原生后端（v0.4 · VM 路线）
荣 2026-09-06 裁定：AST → 智能论字节码 → Rust——Rust 侧是 .pbc 的独立解释器
（与 C3「零 Python 运行时依赖」定位一致），非 AST→Rust 源码直译。
  generate_rust_project(source, out_dir)  中文源码 → cargo 项目（program.pbc 嵌入）
  build_and_run(project_dir)              cargo build + run → 终态 JSON
产物：out_dir/{Cargo.toml, src/{lib,main,vm,pbc,hmac,serve,swarm}.rs, program.pbc}
runtime 模板：rust_runtime/（纯 std 零依赖，手写 JSON 序列化）。
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
from typing import Dict, Optional

from compiler.compiler import compile_source
from compiler.pbc import save_pbc, serialize

ALGO = "rust_codegen-0.1"
RUNTIME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rust_runtime")


# 生效条件：compile_source(source, strict=strict) 的 result["ok"] 为真时，在 abspath(out_dir) 下建 src/、写 program.pbc（内容与现存文件字节一致时不覆写——保 mtime 供 build_rust_exe 新鲜度判定，幂等重入不假重建）与 build_meta.json、把拷贝的 Cargo.toml 的 default 改写为 ["embed"]（模板默认关 embed——模板目录无 program.pbc，裸 cargo test 不失败；生成项目 program.pbc 在位，改写后编译期嵌入），返回 {"ok": True, "project_dir": out_dir, "pbc": ..., "instructions": len(code)}；result["ok"] 为假时返回 {"ok": False, "result": result, "algo": ALGO}；
def generate_rust_project(source: str, out_dir: str, strict: bool = False) -> Dict:
    """中文源码 → Rust cargo 项目。返回 {ok, project_dir, pbc, result}。"""
    code, result = compile_source(source, strict=strict)
    if not result["ok"]:
        return {"ok": False, "result": result, "algo": ALGO}
    out_dir = os.path.abspath(out_dir)
    src_dir = os.path.join(out_dir, "src")
    os.makedirs(src_dir, exist_ok=True)
    # ① 字节码 → program.pbc（tag6 支持 CALL 签名）
    # 内容一致时不覆写（保 pbc mtime）：build_rust_exe 以 pbc/exe mtime 判
    # 新鲜度（N-high 2026-09-26），幂等重入（同源重跑，cmd_run 每次都调本
    # 函数）若照写会无谓翻新 mtime → 触发假重建。
    pbc_path = os.path.join(out_dir, "program.pbc")
    pbc_bytes = serialize(code)
    if not (os.path.exists(pbc_path)
            and open(pbc_path, "rb").read() == pbc_bytes):
        save_pbc(code, pbc_path)
    # ② 拷贝 runtime 模板（Cargo.toml + src/*.rs）
    for name in ("Cargo.toml",):
        shutil.copy2(os.path.join(RUNTIME_DIR, name), os.path.join(out_dir, name))
    # ②' 生成项目形态：模板 default 关 embed（模板目录无 program.pbc），
    #    此处 program.pbc 已写入 out_dir，改写为默认开 → cargo build --release 自包含
    toml_path = os.path.join(out_dir, "Cargo.toml")
    with open(toml_path, "r", encoding="utf-8") as f:
        toml = f.read()
    if toml.count("default = []") != 1:
        raise RuntimeError("Cargo.toml 模板漂移：期望恰好一处 'default = []'")
    with open(toml_path, "w", encoding="utf-8") as f:
        f.write(toml.replace("default = []", 'default = ["embed"]', 1))
    for name in ("lib.rs", "main.rs", "vm.rs", "pbc.rs",
                 "hmac.rs", "serve.rs", "swarm.rs", "health.rs"):
        shutil.copy2(os.path.join(RUNTIME_DIR, "src", name),
                     os.path.join(src_dir, name))
    # ③ 编译元数据（可审计）
    meta = {"algo": ALGO, "instructions": len(code), "pbc_bytes":
            os.path.getsize(pbc_path), "source_bytes": len(source.encode("utf-8"))}
    with open(os.path.join(out_dir, "build_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return {"ok": True, "project_dir": out_dir, "pbc": pbc_path,
            "instructions": len(code), "result": result, "algo": ALGO}


# 生效条件：定位 project_dir 下 target/release/protocol_vm(.exe)；exe 存在且 program.pbc 不比其新（mtime 相等不触发——同刻无害避免假重建）时短路直接返回；exe 缺失或 program.pbc 较新（换源重跑形态——embed 字节码是编译期 include_bytes! 嵌 exe 的，generate_rust_project 只覆写 pbc，旧 exe 照跑旧程序，N-high 2026-09-26）时以 cwd=project_dir、timeout=180 跑 cargo build --release（cargo 经 dep-info 感知 include_bytes! 依赖变化自动重建），returncode!=0 抛 RuntimeError；构建后重探真实产物路径（Windows 产出 .exe 后缀——v5 N26① 无后缀路径返回值同面修复），重探失败（构建成功却无产物）抛 RuntimeError，返回该路径；
def build_rust_exe(project_dir: str) -> str:
    """定位/触发构建 → protocol_vm 可执行文件路径（含 pbc 新鲜度重建）。"""
    project_dir = os.path.abspath(project_dir)

    def _probe() -> Optional[str]:
        for name in ("protocol_vm.exe", "protocol_vm"):
            cand = os.path.join(project_dir, "target", "release", name)
            if os.path.exists(cand):
                return cand
        return None

    exe = _probe()
    pbc = os.path.join(project_dir, "program.pbc")
    # N-high（2026-09-26）：exe 存在但 program.pbc 较新 = 嵌入字节码陈旧
    # （同 project 换源重跑，generate 只覆写 pbc/build_meta.json）——不得
    # 短路放行旧 exe（旧码实测换源后照跑旧程序 trust=0.5 且全绿假成功），
    # 强制走 cargo（其 dep-info 覆盖 include_bytes! 依赖，感知 pbc 变化重建）。
    if exe is not None and os.path.exists(pbc) \
            and os.path.getmtime(pbc) > os.path.getmtime(exe):
        exe = None
    if exe is None:
        build = subprocess.run(["cargo", "build", "--release"], cwd=project_dir,
                               capture_output=True, text=True, timeout=180,
                               encoding="utf-8", errors="replace")
        if build.returncode != 0:
            raise RuntimeError("cargo build 失败: " + build.stderr[-2000:])
        # 构建后重探真实产物（旧码直接返回探测变量，Windows fresh build 时
        # 是无后缀不存在路径——v5 N26① 同面修复）
        exe = _probe()
        if exe is None:
            raise RuntimeError(
                "cargo build 成功但未找到产物 target/release/protocol_vm(.exe)")
    return exe


# 生效条件：以 timeout 跑 cargo build --release（cwd=project_dir），returncode!=0 返回 stage=build，否则定位 exe（.exe 不在则无后缀版）、trust 真值时加 --trust repr(trust)、symbols 真值时加 --symbols，运行 returncode!=0 返回 stage=run，末行 JSON 解析失败返回 stage=parse，成功返回 {"ok": True, "state": state}；
def build_and_run(project_dir: str, symbols: Optional[Dict] = None,
                  trust: float = 0.0, timeout: int = 120) -> Dict:
    """cargo build --release + run → 终态 JSON（与 Python run_pbc 同构）。"""
    project_dir = os.path.abspath(project_dir)
    build = subprocess.run(
        ["cargo", "build", "--release"], cwd=project_dir,
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace")
    if build.returncode != 0:
        return {"ok": False, "stage": "build",
                "stderr": build.stderr[-4000:]}
    exe = os.path.join(project_dir, "target", "release", "protocol_vm.exe")
    if not os.path.exists(exe):
        exe = os.path.join(project_dir, "target", "release", "protocol_vm")
    args = [exe]
    if trust:
        args += ["--trust", repr(trust)]
    if symbols:
        args += ["--symbols", json.dumps(symbols, ensure_ascii=False)]
    # Rust 侧输出 UTF-8（JSON 含中文符号名）；不显式指定编码时
    # Windows 默认 GBK 解码会在多字节边界崩溃 → stdout 变 None。
    run = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                         encoding="utf-8", errors="replace")
    if run.returncode != 0:
        return {"ok": False, "stage": "run", "stderr": run.stderr[-4000:]}
    try:
        state = json.loads(run.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"ok": False, "stage": "parse", "stdout": run.stdout[-2000:]}
    return {"ok": True, "state": state}


# 生效条件：generate_rust_project(source, out_dir, strict=strict) 的 ok 为假时原样返回 gen，否则 build_and_run(gen["project_dir"]) 的 ok 为假时返回 rr，两者皆真时返回 {**gen, "state": rr["state"]}；
def compile_source_to_rust(source: str, out_dir: str,
                           strict: bool = False) -> Dict:
    """一步到位：源码 → 生成 → build → 运行终态。"""
    gen = generate_rust_project(source, out_dir, strict=strict)
    if not gen["ok"]:
        return gen
    rr = build_and_run(gen["project_dir"])
    if not rr["ok"]:
        return rr
    return {**gen, "state": rr["state"]}


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "examples/trust.proto"
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join("out", "rust_demo")
    source = open(src, encoding="utf-8-sig").read()
    r = compile_source_to_rust(source, out)
    print(json.dumps(r.get("state") or r, ensure_ascii=False, indent=1))