# -*- coding: utf-8 -*-
"""蜂巢执行器 v0.2 纯函数单测：est_tokens / build_body。

exec.py 是顶层脚本（含 main 与网络调用），这里用 importlib 按路径加载，
只测无副作用的纯函数——网络路径由端到端假执行器测试覆盖（cargo test）。
"""
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_EXEC_PATH = os.path.join(_HERE, "..", "hive", "exec.py")

_spec = importlib.util.spec_from_file_location("hive_exec", _EXEC_PATH)
hive_exec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hive_exec)


# 生效条件：无必需形参，被调用即执行；断言 hive_exec.est_tokens("abcd"*100)（400 个 ASCII 字符）返回 100（400/4）。
def test_est_tokens_ascii_pure():
    # 400 ASCII 字符 → 400/4 = 100
    assert hive_exec.est_tokens("abcd" * 100) == 100


# 生效条件：无必需形参，被调用即执行；断言 hive_exec.est_tokens("汉"*50)（50 个汉字）返回 50。
def test_est_tokens_cjk_pure():
    # 50 个汉字 → 50（保守偏高估；实际 DeepSeek 约 1.6 字/token）
    assert hive_exec.est_tokens("汉" * 50) == 50


def test_est_tokens_mixed_and_empty():
    assert hive_exec.est_tokens("") == 0
    # "汉字abc"：2 CJK + ceil(3/4)=1 → 3
    assert hive_exec.est_tokens("汉字abc") == 3
    # 7 个 ASCII → ceil(7/4)=2
    assert hive_exec.est_tokens("abcdefg") == 2


def test_build_body_minimal():
    msgs = [{"role": "user", "content": "x"}]
    body = hive_exec.build_body({"model": "m1"}, msgs)
    assert body == {"model": "m1", "messages": msgs}  # 无可选字段→不注入缺省键


def test_build_body_thinking_and_effort():
    msgs = [{"role": "user", "content": "x"}]
    spec = {
        "model": "deepseek-flash",
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }
    body = hive_exec.build_body(spec, msgs)
    assert body["thinking"] == {"type": "enabled"}  # 对象原样透传
    assert body["reasoning_effort"] == "high"
    assert body["messages"] is msgs


def test_build_body_full_optional():
    spec = {
        "model": "m",
        "thinking": {"type": "disabled"},
        "reasoning_effort": "low",
        "max_tokens": 2048,
        "temperature": 0.3,
    }
    body = hive_exec.build_body(spec, [])
    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0.3
    assert body["thinking"] == {"type": "disabled"}


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"  PASS {name}")
    print(f"{len(tests)}/{len(tests)} 全绿")