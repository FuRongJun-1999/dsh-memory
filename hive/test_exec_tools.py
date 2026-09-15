# -*- coding: utf-8 -*-
"""蜂巢执行器工具面单测（agent loop + lingshu_cg + web_search）。

不打真 API：LLM 侧以假 _post_chat 序列驱动 loop；搜索侧以假 urlopen 喂
预置响应测解析；lingshu 侧用临时认知图 root 走真实 md_cg 库层（最小闭环）。
运行：python hive/test_exec_tools.py   （退出码 0 = 全绿）
"""
import io
import json
import os
import sys
import tempfile
import urllib.error
from unittest import mock

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "hive_exec", os.path.join(_HERE, "exec.py"))
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# ---------------------------------------------------------------- A 工具注册
print("[A] 工具注册表与参数面")
check("A1 注册表仅两个工具", set(ex.TOOL_SCHEMAS) == {"lingshu_cg", "web_search"})
check("A2 schema 名与键一致",
      ex.TOOL_SCHEMAS["lingshu_cg"]["function"]["name"] == "lingshu_cg"
      and ex.TOOL_SCHEMAS["web_search"]["function"]["name"] == "web_search")
check("A3 lingshu op 枚举=白名单",
      ex.TOOL_SCHEMAS["lingshu_cg"]["function"]["parameters"]["properties"]
      ["op"]["enum"] == list(ex.LINGSHU_OPS_ALLOW))

out, brief = ex.execute_tool("nope", "{}", "job_x")
check("A4 未知工具诚实报错", not out["ok"] and "nope" in out["error"])
out, _ = ex.execute_tool("web_search", "{bad json", "job_x")
check("A5 非法 JSON 参数报错", not out["ok"] and "JSON" in out["error"])

# ---------------------------------------------------------------- B lingshu
print("[B] lingshu_cg（临时认知图 root，真实 md_cg 库层）")
tmp = tempfile.mkdtemp(prefix="hive_exec_tools_")
os.environ["MDCG_ROOT"] = tmp

out = ex.tool_lingshu_cg({"op": "info"}, "job_t")
check("B1 op 白名单外拒绝", not out["ok"] and "info" in out["error"])
out = ex.tool_lingshu_cg(
    {"op": "write", "content": "测试", "verification_basis": "自由文本"},
    "job_t")
check("B2 非法验证基底前置拦截", not out["ok"]
      and "verification_basis" in out["error"]
      and "test" in out["error"])  # 错误里含合法枚举

# 写路径：DEFER 入审核队列（无验收器恒 DEFER 是设计行为）
out = ex.tool_lingshu_cg(
    {"op": "write", "content": "# 功能名：工具面冒烟\n# 【内容】测试节点",
     "content_kind": "work_done", "verification_basis": "test"},
    "job_t")
check("B3 write 过闸 DEFER 入队（op 成功+committed=false）",
      out.get("ok") is True and out.get("committed") is False
      and out.get("moved_to") == "review_queue", str(out)[:200])

# route/read：测试自写一个已落盘节点（库层直写）再查
from md_cg.mdcos import MdCGSecure
from md_cg.security import Principal
p = Principal(actor="t", clearance="secret", can_write=True, can_admin=False,
              role="recorder", auth_mode="t")
cg_t = MdCGSecure(tmp, principal=p)
cg_t.add("mem_toolroute_probe", "# 功能名：蜂巢工具路由探针\n# 正文：用于 route/read 冒烟",
         layer="knowledge", tags=["cap:hive"])
out = ex.tool_lingshu_cg({"op": "route", "intent": "蜂巢工具路由探针", "k": 3},
                         "job_t")
ks = out.get("knowledge") or []
check("B4 route 命中已落盘节点",
      isinstance(ks, list) and any(x.get("id") == "mem_toolroute_probe"
                                   for x in ks), str(out)[:200])
out = ex.tool_lingshu_cg({"op": "read", "query": "路由探针", "k": 3}, "job_t")
res = out.get("results") or []
check("B5 read 返回 results 结构",
      isinstance(res, list) and len(res) >= 1
      and "node" in res[0], str(out)[:200])

# ---------------------------------------------------------------- C web_search
print("[C] web_search（假 urlopen，不触网）")


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


zhipu_body = json.dumps({"search_result": [
    {"title": "结果一", "link": "https://a.example/1",
     "content": "摘要" * 300, "media": "siteA"},
    {"title": "结果二", "link": "https://a.example/2", "content": "短摘要"},
]}).encode("utf-8")

with mock.patch.dict(os.environ, {"HIVE_API_KEY": "fake-key-test"}), \
        mock.patch.object(ex.urllib.request, "urlopen",
                          return_value=_FakeResp(zhipu_body)):
    out = ex.tool_web_search({"query": "测试", "count": 2})
check("C1 zhipu 后端解析", out.get("ok") and out["backend"] == "zhipu"
      and len(out["results"]) == 2 and out["results"][0]["url"]
      == "https://a.example/1" and len(out["results"][0]["snippet"]) == 300)
with mock.patch.dict(os.environ, {"HIVE_API_KEY": "fake-key-test"}), \
        mock.patch.object(ex.urllib.request, "urlopen",
                          return_value=_FakeResp(b'{"error":{}}')):
    out = ex.tool_web_search({"query": "测试"})
check("C2 zhipu 空结果不报错", out.get("ok") and out["results"] == [])

ddg_html = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fb.example%2Fx'
            '&amp;rut=1">标题<b>加粗</b></a>'
            '<a class="result__snippet" data-xxx="1">这是<b>摘要</b>内容</a>'
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fb.example%2Fy'
            '&amp;rut=2">第二条</a>'
            '<a class="result__snippet">第二条摘要</a>').encode("utf-8")
with mock.patch.object(ex.urllib.request, "urlopen",
                       return_value=_FakeResp(ddg_html)):
    os.environ["HIVE_WEB_SEARCH"] = "duckduckgo"
    out = ex.tool_web_search({"query": "测试"})
    os.environ.pop("HIVE_WEB_SEARCH", None)
check("C3 ddg 兜底解析（uddg 解码+标签剥离+摘要归属）",
      out.get("ok") and out["backend"] == "duckduckgo"
      and out["results"][0]["url"] == "https://b.example/x"
      and out["results"][0]["title"] == "标题加粗"
      and out["results"][0]["snippet"] == "这是摘要内容"
      and out["results"][1]["snippet"] == "第二条摘要", str(out)[:200])

out = ex.tool_web_search({"query": " "})
check("C4 空查询拒绝", not out["ok"])
os.environ["HIVE_WEB_SEARCH"] = "bogus"
out = ex.tool_web_search({"query": "x"})
os.environ.pop("HIVE_WEB_SEARCH", None)
check("C5 未知后端拒绝", not out["ok"] and "bogus" in out["error"])

# ---------------------------------------------------------------- D agent loop
print("[D] run_with_tools（假 _post_chat 序列）")

resp_route = {"choices": [{"finish_reason": "tool_calls", "message": {
    "content": "", "tool_calls": [
        {"id": "call_1", "type": "function",
         "function": {"name": "lingshu_cg",
                      "arguments": json.dumps(
                          {"op": "route", "intent": "蜂巢工具路由探针"},
                          ensure_ascii=False)}}]}}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    "model": "m1"}
resp_final = {"choices": [{"finish_reason": "stop", "message": {
    "content": "终答完成"}}],
    "usage": {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230},
    "model": "m1"}

seq = [resp_route, resp_final]
with mock.patch.object(ex, "_post_chat", side_effect=lambda body, t: seq.pop(0)):
    out = ex.run_with_tools({"model": "m1", "tools": ["lingshu_cg"]},
                            [{"role": "user", "content": "q"}], "job_d")
check("D1 两轮收敛：终答 content",
      "content" in out and out["content"] == "终答完成", str(out)[:300])
check("D2 trace 记录工具调用", out["tool_trace"][0]["tool"] == "lingshu_cg"
      and out["tool_trace"][0]["ok"] is True)
check("D3 usage 跨轮累加", out["usage"]["total_tokens"] == 350,
      str(out.get("usage")))
check("D4 tool_rounds 透出", out.get("tool_rounds") == 1)

# 直接检查 loop 内 messages 累积：重跑并捕获
captured = []
def _cap(body, t):
    captured.append(json.loads(json.dumps(body)))
    return seq.pop(0)
seq = [json.loads(json.dumps(resp_route)), json.loads(json.dumps(resp_final))]
with mock.patch.object(ex, "_post_chat", side_effect=_cap):
    ex.run_with_tools({"model": "m1", "tools": ["lingshu_cg"]},
                      [{"role": "user", "content": "q"}], "job_d")
roles = [m["role"] for m in captured[-1]["messages"]]
check("D6 第二次请求消息序列 user/assistant/tool",
      roles == ["user", "assistant", "tool"], str(roles))
check("D7 第二次请求仍带 tools（未到上限）",
      "tools" in captured[-1])

# 强制终答：模型无限要求工具
always_calls = json.loads(json.dumps(resp_route))
seq = [always_calls.copy() for _ in range(3)]
captured.clear()
with mock.patch.object(ex, "_post_chat", side_effect=_cap):
    out = ex.run_with_tools({"model": "m1", "tools": ["lingshu_cg"],
                             "max_tool_rounds": 1},
                            [{"role": "user", "content": "q"}], "job_d")
check("D8 超轮次强制终答 forced_final",
      out.get("forced_final") is True
      and any(t["tool"] == "_force_final" for t in out["tool_trace"]),
      str(out.get("tool_trace"))[:200])
check("D9 强制终答请求不带 tools", "tools" not in captured[-1],
      str(captured[-1].get("keys") or list(captured[-1].keys())))

# API 错误收敛
err = urllib.error.HTTPError("u", 500, "boom", {}, io.BytesIO(b"e"))
with mock.patch.object(ex, "_post_chat", side_effect=err):
    out = ex.run_with_tools({"model": "m1", "tools": ["lingshu_cg"]},
                            [{"role": "user", "content": "q"}], "job_d")
check("D10 HTTP 错误收敛为 _error+trace 保留",
      "_error" in out and "500" in out["_error"] and "tool_trace" in out)

# 预算拦截：工具轮累积超预算
big_tool = json.loads(json.dumps(resp_route))
big_tool["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = \
    json.dumps({"op": "read", "query": "x"})
seq = [big_tool]
with mock.patch.object(ex, "_post_chat", side_effect=lambda b, t: seq.pop(0)):
    out = ex.run_with_tools({"model": "m1", "tools": ["lingshu_cg"],
                             "context_budget_tokens": 10},
                            [{"role": "user", "content": "q"}], "job_d")
check("D11 工具轮超预算诚实终止", "_error" in out
      and "超预算" in out["_error"], str(out)[:200])

# ---------------------------------------------------------------- E 无工具路径等价
print("[E] 无 tools 时保持单发历史路径")
body = ex.build_body({"model": "m", "temperature": 0.3}, [{"role": "user",
                                                           "content": "hi"}])
check("E1 无 tools 不注入键", "tools" not in body and body["model"] == "m")
body2 = ex.build_body({"model": "m"}, [{"role": "user", "content": "hi"}],
                      tools=[ex.TOOL_SCHEMAS["web_search"]])
check("E2 tools 参数注入", body2.get("tools")
      and body2["tools"][0]["function"]["name"] == "web_search")

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
