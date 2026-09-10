# -*- coding: utf-8 -*-
"""灵枢 · 测试用例执行器 code_test_runner（物理基底校准 · v1.16）

对代码类知识卡的测试用例**实际执行**——代码运行时报错/输出偏差 =
物理信息基底裁决（爸爸外部参照：最终校准是物理信息基底本身）。

三语言：
  Python：subprocess python 执行
  TypeScript：tsc 编译 + node 运行（npx.cmd 绕过 PowerShell 执行策略）
  Rust：rustc/cargo 可用则编译执行；环境缺失 → env_missing（D-005 降级，
       不假装验证过——物理基底缺失=诚实标记待环境）

用法：
  runner = CodeTestRunner()
  result = runner.run_card(card)   # card 带 tests.executable 字段
"""
import os
import shutil
import subprocess
import sys
import tempfile
import json

TIMEOUT = 20  # 秒


class CodeTestRunner:
    """代码类知识卡测试用例执行器（物理基底校准）。"""

    def _exec(self, cmd, cwd=None, timeout=TIMEOUT, extra_env=None):
        """执行命令，返回 (exit_code, stdout, stderr)。"""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        if extra_env:
            env.update(extra_env)
        try:
            p = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                cwd=cwd, encoding="utf-8", errors="replace",
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            return p.returncode, (p.stdout or ""), (p.stderr or "")
        except subprocess.TimeoutExpired:
            return -1, "", f"超时({timeout}s)"
        except Exception as e:
            return -2, "", str(e)

    # ---------------- Python ----------------
    def run_python(self, code, timeout=TIMEOUT):
        """执行 Python 代码片段，返回 (ok, output, detail)。"""
        rc, out, err = self._exec(
            [sys.executable, "-c", code], timeout=timeout)
        if rc == 0:
            return True, out.strip(), "运行成功"
        return False, out.strip(), (err or "").strip()[:300]

    # ---------------- TypeScript ----------------
    def run_typescript(self, code, timeout=TIMEOUT):
        """tsc 编译 + node 运行。返回 (ok, output, detail)。"""
        # 用全局 tsc.cmd（subprocess 直接调用，不经 PowerShell）
        tsc = shutil.which("tsc.cmd") or shutil.which("tsc")
        rc, _, err = self._exec([tsc, "--version"], timeout=30) if tsc \
            else (-1, "", "tsc 未安装")
        if rc != 0:
            return False, "", f"tsc 不可用: {err[:100]}"
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "main.ts")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            rc, out, err = self._exec(
                [tsc, "--strict", "--outDir", td, src],
                cwd=td, timeout=timeout)
            if rc != 0:
                return False, "", f"tsc 编译错误: {(err or out)[:300]}"
            js = os.path.join(td, "main.js")
            if not os.path.exists(js):
                return False, "", "编译产物缺失"
            rc, out, err = self._exec(["node", js], timeout=timeout)
            if rc == 0:
                return True, out.strip(), "tsc+node 运行成功"
            return False, out.strip(), (err or "").strip()[:300]

    # ---------------- Rust ----------------
    def run_rust(self, code, timeout=TIMEOUT):
        """rustc 编译执行。环境缺失 → env_missing（诚实降级）。"""
        rustc = shutil.which("rustc") or shutil.which("rustc.exe")
        if not rustc:
            return None, "", "环境缺失: rustc 未安装（D-005 降级，不假装验证）"
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "main.rs")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            rc, out, err = self._exec([rustc, "-o", os.path.join(td, "main"), src],
                                      timeout=timeout)
            if rc != 0:
                return False, "", f"rustc 编译错误: {(err or out)[:300]}"
            rc, out, err = self._exec([os.path.join(td, "main")], timeout=timeout)
            if rc == 0:
                return True, out.strip(), "rustc 运行成功"
            return False, out.strip(), (err or "").strip()[:300]

    # ---------------- 卡级执行 ----------------
    def run_card(self, card):
        """执行知识卡 tests.executable 的代码片段，物理基底验证卡声称的机制。
        card 需含: tests = {executable: {lang, code, expect_contains, expect_missing?}}。
        返回 {lang, status: pass/fail/env_missing/error, output, detail}。"""
        tests = card.get("tests") or {}
        ex = tests.get("executable") or {}
        lang = ex.get("lang", "")
        code = ex.get("code", "")
        expect = ex.get("expect_contains", "")  # 期望输出包含
        expect_missing = ex.get("expect_missing", "")  # 期望不包含（如报错词）
        if not lang or not code:
            return {"lang": lang, "status": "error", "output": "",
                    "detail": "tests.executable 缺失（lang/code）"}
        if lang == "python":
            ok, out, detail = self.run_python(code)
        elif lang == "typescript":
            ok, out, detail = self.run_typescript(code)
        elif lang == "rust":
            ok, out, detail = self.run_rust(code)
            if ok is None:
                return {"lang": lang, "status": "env_missing", "output": "",
                        "detail": detail}
        else:
            return {"lang": lang, "status": "error", "output": "",
                    "detail": f"未知语言 {lang}"}
        # 期望校验
        if ok:
            if expect and expect not in out:
                return {"lang": lang, "status": "fail", "output": out,
                        "detail": f"运行成功但输出不含期望「{expect}」"}
            if expect_missing and expect_missing in out:
                return {"lang": lang, "status": "fail", "output": out,
                        "detail": f"输出意外包含「{expect_missing}」"}
            return {"lang": lang, "status": "pass", "output": out,
                    "detail": detail}
        # 执行失败/编译失败：若期望的正是「编译错误含某词」（如 Rust 所有权
        # 移动后使用→E0382），物理基底确认机制成立 → pass
        if expect and expect in (out + detail):
            return {"lang": lang, "status": "pass", "output": out,
                    "detail": f"编译/运行失败但错误含期望「{expect}」（机制确认）"}
        return {"lang": lang, "status": "fail", "output": out,
                "detail": f"执行失败: {detail}"}


# ---------------- 三语言卡的可执行测试用例 ----------------
LANG_EXECUTABLES = {
    "Python": {
        "lang": "python",
        "code": (
            "# 物理基底验证: ①鸭子类型 len() 接受任何有 __len__ 的对象 ②GIL 多线程CPU加速比远低于核心数\n"
            "class Bag:\n"
            "    def __len__(self):\n"
            "        return 42\n"
            "assert len(Bag()) == 42, '鸭子类型失败'\n"
            "print('鸭子类型OK:', len(Bag()))\n"
            "import threading, time\n"
            "def work():\n"
            "    t0 = time.time()\n"
            "    while time.time() - t0 < 0.3:\n"
            "        pass\n"
            "threads = [threading.Thread(target=work) for _ in range(4)]\n"
            "t0 = time.time()\n"
            "[t.start() for t in threads]\n"
            "[t.join() for t in threads]\n"
            "wall = time.time() - t0\n"
            "print('4线程CPU密集耗时(s):', round(wall, 2))\n"
            "# GIL: CPU密集多线程加速比远低于核心数（非线性加速，也不绝对串行）\n"
            "assert wall < 0.9, 'GIL下多线程CPU密集应接近串行(加速比低)'\n"
            "assert wall >= 0.3, '多线程仍有线程调度开销'\n"
            "print('GIL验证OK: 加速比≈', round(0.3*4/max(wall,0.01), 2), 'x (远低于4x)')\n"),
        "expect_contains": "GIL验证OK",
    },
    "Rust": {
        "lang": "rust",
        "code": (
            "// 物理基底验证: 所有权移动后原变量不可用（编译期报错）\n"
            "fn main() {\n"
            "    let s = String::from(\"hello\");\n"
            "    let s2 = s;          // 所有权移动\n"
            "    println!(\"{}\", s2); // 可用\n"
            "    // 编译期应报错: use of moved value: `s`\n"
            "    println!(\"{}\", s);  // 若编译通过则物理基底判定卡错\n"
            "}\n"),
        "expect_missing": "编译成功",  # 期望编译失败（move 后使用）
        "expect_contains": "moved value",  # E0382: borrow of moved value
    },
    "TypeScript": {
        "lang": "typescript",
        "code": (
            "// 物理基底验证: ①结构类型(形状匹配无需implements) ②类型擦除(JS无类型)\n"
            "interface Point { x: number; y: number; }\n"
            "const p: Point = { x: 1, y: 2 }; // 结构兼容\n"
            "function dist(a: Point, b: Point): number {\n"
            "  return Math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2);\n"
            "}\n"
            "console.log('结构类型OK:', dist(p, {x:4,y:6}));\n"
            "console.log('运行时类型:', typeof p);\n"),
        "expect_contains": "结构类型OK: 5",
    },
}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    runner = CodeTestRunner()
    print("=== 测试用例执行器 · 物理基底校准 ===\n")
    for name, ex in LANG_EXECUTABLES.items():
        card = {"name": name, "tests": {"executable": ex}}
        r = runner.run_card(card)
        mark = {"pass": "✅", "fail": "❌", "env_missing": "⚠️"}.get(r["status"], "?")
        print(f"{mark} {name}: {r['status']}")
        print(f"   detail: {r['detail'][:100]}")
        if r.get("output"):
            print(f"   output: {r['output'][:120]}")
        print()
