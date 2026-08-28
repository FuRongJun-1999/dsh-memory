# -*- coding: utf-8 -*-
"""
compiler_runner2.py · T9-2b 中文编译器域 token 对比 runner（v0.2 设计）
======================================================================
吸收用户五点修正：
1. 统计剔除 reasoning（max_tokens=10000 杜绝截断——截断是测试缺陷非能力差异）
2. 白箱价值=输入节约：A 组完整文档（长输入） vs B 组检索要点（低输入）
3. 被测能力=条件化路由：B 组先判复杂度→简单直答/复杂才进递归反思
4. 真实开发模拟：信息分轮投递 + 干扰片段混入（多轮测试/持续输入/信息干扰）
5. B 组知识来自白箱编译域检索（确定性记忆检索）
"""
import os, sys, io, json, time, urllib.request, winreg

def setup_stdout():
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

setup_stdout()

# ---------- API ----------
def get_key():
    for hive, name in [(winreg.HKEY_CURRENT_USER, "User"), (winreg.HKEY_LOCAL_MACHINE, "Machine")]:
        try:
            k = winreg.OpenKey(hive, r"Environment")
            val, _ = winreg.QueryValueEx(k, "DEEPSEEK_API_KEY")
            winreg.CloseKey(k)
            if val:
                return val
        except Exception:
            pass
    return None

KEY = get_key()
BASE = "https://api.deepseek.com"
MODEL = "deepseek-v4-flash"

def llm_chat(messages, max_tokens=10000, retries=3):
    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
    }).encode()
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{BASE}/chat/completions",
                data=body, headers={"Authorization": f"Bearer {KEY}",
                                    "Content-Type": "application/json"})
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode())
            dt = time.time() - t0
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return content, usage, dt
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"LLM 调用失败（{retries} 次）: {last_err}")

# ---------- 白箱：编译域单元检索（B 组知识来源·只给要点不给代码） ----------
def whitebox_units(unit_names):
    sys.path.insert(0, r"D:\Program Files\2_ai\CommonTrustProtocol\aeis\wisdom")
    try:
        import compiler_code_units as ccu
        parts = []
        for un in unit_names:
            u = ccu.COMPILER_UNITS.get(un)
            if u:
                parts.append(f"  - {un}：任务={u['task']}；语义要点={u['calibration']}")
        if parts:
            return "【白箱编译域检索命中】\n" + "\n".join(parts) + \
                   "\n以上为检索到的确定性知识要点（对照语义），据此实现，不照抄代码骨架。"
        return None
    except Exception as e:
        return f"【白箱检索】不可用: {e}"

# ---------- 条件化路由（B 组特有） ----------
ROUTING = """【条件化路由】
1. 先判断任务复杂度：
   - 简单确定性任务（有确定的直答路径、无需多步骤验证）→ 【直答模式】：直接实现，不进入递归反思
   - 复杂任务（多约束协调/需验证设计）→ 【递归反思模式】：元反思→全局视角→条件分析→验证
2. 知识获取：若本领域有确定性知识，优先从白箱检索结果获取，不要自己臆造
3. 输出：仅输出完整的中文协议程序（无多余文字）"""

# ---------- 最小语法骨架（两组相同·任务需求层面） ----------
SKELETON = """【最小语法骨架】
- 整个程序必须写为【一行】（多行会导致函数定义吞掉后续语句）
- 程序以「止。」结束；语句以「；」分隔
- 运算词：加 减 乘 除 等于 大于 小于
- 赋值运算符是 =（「等于」是比较运算，不是赋值；赋值写法：变量 = 表达式）
- 最终计算结果存入变量「结果」（验收读取）"""

# ---------- 测试任务（v0.2：信息流分轮 + 干扰 + 复杂度分级） ----------
# info_rounds: 每轮为片段列表；片段无标注（正确/干扰混合，LLM 需自行辨别）
# doc_ok: A 组完整文档的正确知识片段（文档化·长）；doc_noise: 干扰片段（两组同投）
TASKS = [
    {
        "id": "1", "name": "算术优先级", "complexity": "simple", "expected": 11.0,
        "task": "编写程序计算 3 加 4 乘 2，结果存入「结果」。",
        "whitebox_units": ["编译-赋值", "VM-算术执行"],
        "doc_ok": [
            "【领域文档】本语言中：乘法和除法优先于加法和减法，同级从左到右计算。",
            "【领域文档】本语言中：赋值语句格式为 变量 = 表达式；最终结果存入变量「结果」。",
        ],
        "doc_noise": [
            "【同事笔记】本语言中：变量名必须以字母 x 或 y 开头（否则编译警告）。",
            "【旧版手册】本语言中：每条语句以句号（。）结束，而非分号。",
        ],
    },
    {
        "id": "2", "name": "汉诺双递归", "complexity": "medium", "expected": 7.0,
        "task": "编写程序：定义 汉诺（n）：若 n 等于 1，则 返回 1，否则 返回 "
               "汉诺（n 减 1） 加 汉诺（n 减 1） 加 1。然后计算 汉诺（3） 的值，"
               "结果存入「结果」。（n=1 时 1 步；n 时两次子问题各 n-1 步再加 1 次"
               "移动，n=3 共 7 步）",
        "whitebox_units": ["编译-递归", "编译-若则"],
        "doc_ok": [
            "【领域文档】本语言中：条件语句格式为 若 条件，则 语句，否则 语句。",
            "【领域文档】本语言中：递归函数必须在函数体内包含终止条件（基例）保证能返回。",
        ],
        "doc_noise": [
            "【同事笔记】本语言中：条件语句不需要 否则 分支——写了 否则 会报语法错误。",
            "【旧版手册】本语言中：递归调用必须在函数名前加「递归」关键字声明。",
        ],
    },
    {
        "id": "3", "name": "递归阶乘", "complexity": "complex", "expected": 120.0,
        "task": "定义 阶乘 函数并计算 阶乘（5）存入「结果」。",
        "whitebox_units": ["编译-递归", "编译-若则"],
        "doc_ok": [
            "【领域文档】本语言中：条件语句格式为 若 条件，则 语句，否则 语句。",
            "【领域文档】本语言中：递归函数必须在函数体内包含终止条件（基例）保证能返回。",
        ],
        "doc_noise": [
            "【同事笔记】本语言中：条件语句不需要 否则 分支——写了 否则 会报语法错误。",
            "【旧版手册】本语言中：递归调用必须在函数名前加「递归」关键字声明。",
        ],
    },
]

# ---------- 验收 ----------
def verify_program(src, expected):
    sys.path.insert(0, r"D:\Program Files\2_ai\protocol-compiler")
    from core.compiler import compile_source
    from core.condition_vm import ConditionVM
    code, result = compile_source(src, strict=False)
    if not result["ok"]:
        return False, "编译错", "；".join(str(e) for e in result["errors"][:3])
    try:
        vm = ConditionVM()
        state = vm.run(code)
    except Exception as e:
        return False, "运行错", f"{e}"
    got = state["symbols"].get("结果")
    if got is None:
        return False, "结果错", f"变量「结果」未定义（符号表: {list(state['symbols'].keys())}）"
    if abs(got - expected) >= 0.01:
        return False, "结果错", f"「结果」={got} 期望={expected}"
    return True, "通过", f"「结果」={got} ✓"

def extract_program(content):
    if "```" in content:
        import re
        m = re.findall(r"```(?:\w+)?\s*\n(.*?)```", content, re.S)
        if m:
            return m[-1].strip()
    return content.strip()

# ---------- 单任务测试 ----------
def run_task(task, with_lingshu, max_rounds=5):
    history = {"prompt": 0, "completion": 0, "reasoning": 0, "visible": 0, "total": 0, "rounds": 0}
    rounds_log = []

    # 组装信息流（正确/干扰片段混排，分轮）
    def noise_block(round_idx):
        n = task["doc_noise"]
        half = len(n) // 2
        return "\n".join(n[:half] if round_idx == 0 else n[half:])

    if with_lingshu:
        wb = whitebox_units(task["whitebox_units"])
        system = ROUTING + ("\n\n" + wb if wb else "")
        # B 组初始：任务 + 骨架 + 第 1 轮干扰（正确知识来自白箱）
        info_r0 = noise_block(0)
        user0 = (f"任务：{task['task']}\n{SKELETON}\n"
                 f"{info_r0}\n请输出完整的中文协议程序。")
    else:
        system = "你是一个中文协议语言编译器工程师，严格按任务要求输出程序。"
        # A 组初始：任务 + 骨架 + 完整文档（正确+干扰，长输入）
        doc = "\n".join(task["doc_ok"] + task["doc_noise"])
        user0 = (f"任务：{task['task']}\n{SKELETON}\n{doc}\n"
                 f"请基于以上领域文档输出完整的中文协议程序（文档可能含过时/错误信息，请自行辨别）。")

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user0},
    ]

    for rnd in range(max_rounds):
        content, usage, dt = llm_chat(messages)
        prompt_t = usage.get("prompt_tokens", 0)
        comp_t = usage.get("completion_tokens", 0)
        reason_t = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
        visible_t = max(0, comp_t - reason_t)
        history["prompt"] += prompt_t
        history["completion"] += comp_t
        history["reasoning"] += reason_t
        history["visible"] += visible_t
        history["total"] += usage.get("total_tokens", 0)
        history["rounds"] += 1

        prog = extract_program(content)
        ok, cat, detail = verify_program(prog, task["expected"])
        rounds_log.append({
            "round": rnd + 1, "prompt": prompt_t, "comp": comp_t,
            "reasoning": reason_t, "visible": visible_t,
            "status": cat, "detail": detail, "program": prog,
        })
        if ok:
            return {"pass": True, "rounds": rnd + 1, **history,
                    "rounds_log": rounds_log, "program": prog}

        # 失败：追加下一轮信息（持续信息输入）+ 诊断
        feedback = f"验收未通过（{cat}）：{detail}\n期望「结果」== {task['expected']}。"
        if rnd + 1 < len(rounds_plan(task)):
            feedback += f"\n\n【新收到的项目信息】\n{noise_block(rnd + 1)}"
        feedback += "\n请修正程序，输出完整的中文协议程序。"
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": feedback})

    return {"pass": False, "rounds": max_rounds, **history,
            "rounds_log": rounds_log, "program": prog}

def rounds_plan(task):
    return task["doc_noise"]  # 干扰分两轮投递

# ---------- 主流程 ----------
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compiler_token_results_v2.json")
    results = {"裸LLM": [], "灵枢+白箱": []}

    for t in TASKS:
        print(f"\n===== 任务{t['id']} {t['name']}（{t['complexity']}·期望 {t['expected']}） =====")
        for label, flag in [("裸LLM", False), ("灵枢+白箱", True)]:
            if (mode == "bare" and flag) or (mode == "lingshu" and not flag):
                continue
            r = run_task(t, flag)
            results[label].append({**r, "task": t["id"], "name": t["name"],
                                   "complexity": t["complexity"], "expected": t["expected"]})
            print(f"  [{label}] pass={r['pass']} rounds={r['rounds']} "
                  f"prompt={r['prompt']} visible={r['visible']} reasoning={r['reasoning']} "
                  f"total={r['total']}")
            for rl in r["rounds_log"]:
                print(f"      R{rl['round']}: {rl['status']} {rl['detail'][:50]} "
                      f"prompt={rl['prompt']} visible={rl['visible']} reason={rl['reasoning']}")

    print("\n\n========== 汇总 ==========")
    for label in ["裸LLM", "灵枢+白箱"]:
        rs = results[label]
        if not rs:
            continue
        prompt = sum(r["prompt"] for r in rs)
        visible = sum(r["visible"] for r in rs)
        reasoning = sum(r["reasoning"] for r in rs)
        rounds = sum(r["rounds"] for r in rs)
        pass_n = sum(1 for r in rs if r["pass"])
        print(f"\n{label}: 输入token={prompt} 可见输出={visible} "
              f"(推理单独列={reasoning}) 总轮次={rounds} 通过={pass_n}/3")

    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"\n结果已保存: {out}")

if __name__ == "__main__":
    main()
