# -*- coding: utf-8 -*-
"""蜂巢执行器工具面单测（agent loop + lingshu_cg + web_search + read_file）。

不打真 API：LLM 侧以假 _post_chat 序列驱动 loop；搜索侧以假 urlopen 喂
预置响应测解析；lingshu 侧用临时认知图 root 走真实 md_cg 库层（最小闭环）。
运行：python hive/test_exec_tools.py   （退出码 0 = 全绿）
"""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
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
check("A1 注册表仅三个工具",
      set(ex.TOOL_SCHEMAS) == {"lingshu_cg", "web_search", "read_file"})
check("A2 schema 名与键一致",
      ex.TOOL_SCHEMAS["lingshu_cg"]["function"]["name"] == "lingshu_cg"
      and ex.TOOL_SCHEMAS["web_search"]["function"]["name"] == "web_search"
      and ex.TOOL_SCHEMAS["read_file"]["function"]["name"] == "read_file")
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
     "content_kind": "work_done", "verification_basis": "test",
     "layer": "contextual"},   # M3.2：worker 直写限 contextual（缺省被拒）
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

# M3.1 工具层写后回读（批次7）：committed=true 必须盘面真有节点文件
print("[B6] _write_readback（9·12 工具层防线）")
from types import SimpleNamespace as _NS
# B6: DEFER 入队形态（committed=false）→ 原样放行（无落盘声称，不拦）
out = ex._write_readback(tmp, cg_t, {"ok": True, "id": "mem_whatever",
                                     "committed": False})
check("B6 committed=false 原样放行（入队非落盘）",
      out.get("readback") is None and out.get("committed") is False, str(out)[:120])
# B7: committed=true 但盘面无文件 → 回读不一致 error（能红：旧实现冒充成功）
fake_cg = _NS(index={"nodes": {"mem_ghost": {
    "path": "nodes/knowledge/mem_ghost.md"}}})
out = ex._write_readback(tmp, fake_cg,
                         {"ok": True, "id": "mem_ghost", "committed": True})
check("B7 盘面无文件 → 回读不一致拒绝冒充成功",
      out.get("ok") is False and out.get("readback") == "missing"
      and "回读不一致" in out["error"], str(out)[:160])
# B8: committed=true 且文件真在盘 → 放行并附 readback=ok
cg_t.add("mem_readback_probe", "# 功能名：回读探针\n# 正文：真实落盘",
         layer="knowledge")
e = cg_t.index["nodes"]["mem_readback_probe"]
check("B8a 探针文件真在盘（前置）",
      os.path.isfile(os.path.join(tmp, e["path"])))
out = ex._write_readback(tmp, cg_t, {"ok": True, "id": "mem_readback_probe",
                                     "committed": True})
check("B8 盘面有文件 → 放行附 readback=ok",
      out.get("ok") is True and out.get("readback") == "ok", str(out)[:120])

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

# 预算拦截：工具轮累积超预算 → 默认交回续跑（v0.4 §5.3 换人续跑）
big_tool = json.loads(json.dumps(resp_route))
big_tool["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = \
    json.dumps({"op": "read", "query": "x"})
seq = [big_tool]
with mock.patch.object(ex, "_post_chat", side_effect=lambda b, t: seq.pop(0)):
    out = ex.run_with_tools({"model": "m1", "tools": ["lingshu_cg"],
                             "context_budget_tokens": 10},
                            [{"role": "user", "content": "q"}], "job_d")
check("D11 超预算默认交回（不 fail）：need_continue+completed=false",
      "_error" not in out and out.get("need_continue") is True
      and out.get("completed") is False and out["handoff"]["reason"]
      == "context_budget" and "交回续跑" in out["content"], str(out)[:300])
check("D11b 交回带完整交接字段（预算/轮次/进展卡/不自动续跑）",
      out["handoff"]["budget_tokens"] == 10
      and out["handoff"]["progress_file"] == ex.PROGRESS_FILE
      and out["handoff"]["auto_continue"] is False
      and out["handoff"]["est_tokens"] >= 10, str(out["handoff"]))

# context_strict=true → 保持旧 fail fast（历史行为，逐位兼容）
seq = [json.loads(json.dumps(big_tool))]
with mock.patch.object(ex, "_post_chat", side_effect=lambda b, t: seq.pop(0)):
    out = ex.run_with_tools({"model": "m1", "tools": ["lingshu_cg"],
                             "context_budget_tokens": 10,
                             "context_strict": True},
                            [{"role": "user", "content": "q"}], "job_d")
check("D11c context_strict=true 保持旧 fail fast",
      "_error" in out and "超预算" in out["_error"]
      and "need_continue" not in out, str(out)[:200])

# 大工具输出：全量落盘 + 回喂消息保尾（Pi⑦③）
tmp_job = tempfile.mkdtemp(prefix="hive_exec_job_")
seq = [json.loads(json.dumps(resp_route)), json.loads(json.dumps(resp_final))]
captured.clear()
with mock.patch.object(ex, "execute_tool",
                       side_effect=lambda *a, **k: (
                           {"ok": True, "blob": "B" * 9000}, "big")), \
        mock.patch.object(ex, "_post_chat", side_effect=_cap):
    out = ex.run_with_tools({"model": "m1", "tools": ["lingshu_cg"]},
                            [{"role": "user", "content": "q"}], "job_d",
                            job_dir=tmp_job)
tool_msg = [m for m in captured[-1]["messages"] if m["role"] == "tool"][0]
spill = out["tool_trace"][0].get("spill")
check("D12 大输出落盘 job 目录（trace 留名）",
      bool(spill) and os.path.isfile(os.path.join(tmp_job, spill))
      and len(open(os.path.join(tmp_job, spill), encoding="utf-8").read()) > 9000,
      str(spill))
check("D12b 回喂消息保尾 + 非静默省略提示",
      len(tool_msg["content"]) <= ex.TOOL_MSG_MAX_CHARS + 200
      and "中间省略" in tool_msg["content"]
      and tool_msg["content"].endswith('B"}\n'.strip())
      and tool_msg["content"].count("B") > 1000
      and "tool_0_0.json" in tool_msg["content"],
      str(len(tool_msg["content"])))

# v15-3：落盘面同样封顶（超长输出不得无上限写盘）
huge = "C" * (ex.TOOL_DUMP_MAX_CHARS + 5000)
_, huge_name = ex._shrink_tool_text(huge, tmp_job, "9_9")
huge_spill = open(os.path.join(tmp_job, huge_name), encoding="utf-8").read()
check("D12c 落盘受 TOOL_DUMP_MAX_CHARS 上限约束（截断并标注）",
      bool(huge_name) and len(huge_spill) <= ex.TOOL_DUMP_MAX_CHARS + 200
      and "落盘截断" in huge_spill,
      "%s -> %d" % (huge_name, len(huge_spill)))
check("D12c 进展卡逐轮留痕（tool/final 两类条目）",
      os.path.isfile(os.path.join(tmp_job, ex.PROGRESS_FILE)))
_pe = [json.loads(x) for x in open(os.path.join(tmp_job, ex.PROGRESS_FILE),
                                   encoding="utf-8") if x.strip()]
check("D12d 进展条目含步骤/证据/时间戳",
      [e["kind"] for e in _pe] == ["tool", "final"]
      and _pe[0]["tool"] == "lingshu_cg" and _pe[0]["round"] == 0
      and bool(_pe[0]["evidence"]) and isinstance(_pe[0]["ts"], float), str(_pe))

# 双空助手轮不入上下文（Pi⑦①）
seq = [{"choices": [{"message": {"content": "   "}}], "usage": {}, "model": "m1"}]
with mock.patch.object(ex, "_post_chat", side_effect=lambda b, t: seq.pop(0)):
    out = ex.run_with_tools({"model": "m1", "tools": ["lingshu_cg"]},
                            [{"role": "user", "content": "q"}], "job_d")
check("D13 双空助手轮不追加且诚实报错（Pi⑦①）",
      "_error" in out and "空助手轮" in out["_error"], str(out)[:200])

# API 错误后 messages 无空洞 assistant 轮（Pi⑦① 回归守卫）
captured.clear()
_seq2 = [json.loads(json.dumps(resp_route)),
         urllib.error.HTTPError("u", 503, "boom", {}, io.BytesIO(b"e"))]


def _cap2(body, t):
    captured.append(json.loads(json.dumps(body)))
    nxt = _seq2.pop(0)
    if isinstance(nxt, Exception):
        raise nxt
    return nxt


with mock.patch.object(ex, "_post_chat", side_effect=_cap2):
    out = ex.run_with_tools({"model": "m1", "tools": ["lingshu_cg"]},
                            [{"role": "user", "content": "q"}], "job_d")
_bad = [m for m in captured[-1]["messages"]
        if m["role"] == "assistant" and not m.get("tool_calls")
        and not (m.get("content") or "").strip()]
check("D14 失败轮不产生空洞 assistant 消息（Pi⑦①）",
      "_error" in out and not _bad, str(captured[-1]["messages"])[:200])

# ---------------------------------------------------------------- E 无工具路径等价
print("[E] 无 tools 时保持单发历史路径")
body = ex.build_body({"model": "m", "temperature": 0.3}, [{"role": "user",
                                                           "content": "hi"}])
check("E1 无 tools 不注入键", "tools" not in body and body["model"] == "m")
body2 = ex.build_body({"model": "m"}, [{"role": "user", "content": "hi"}],
                      tools=[ex.TOOL_SCHEMAS["web_search"]])
check("E2 tools 参数注入", body2.get("tools")
      and body2["tools"][0]["function"]["name"] == "web_search")

# ---------------------------------------------------------------- F 上下文护栏
print("[F] build_messages 上下文护栏（Pi⑦④ 图像/二进制 + ⑥ 提示词真源）")
ctx_ws = tempfile.mkdtemp(prefix="hive_exec_ctx_")
png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
       + (3000).to_bytes(4, "big") + (120).to_bytes(4, "big") + b"\x08\x06\x00")
jpeg = (b"\xff\xd8" + b"\xff\xe0" + (16).to_bytes(2, "big") + b"\x00" * 14
        + b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08"
        + (600).to_bytes(2, "big") + (800).to_bytes(2, "big") + b"\x00" * 12)
txt = "正文一\n" + "行" * 5
binf = b"PK\x03\x04" + b"\x00" * 64 + b"\x01\x02"
open(os.path.join(ctx_ws, "big.png"), "wb").write(png)
open(os.path.join(ctx_ws, "photo.jpg"), "wb").write(jpeg)
open(os.path.join(ctx_ws, "notes.txt"), "w", encoding="utf-8").write(txt)
open(os.path.join(ctx_ws, "archive.bin"), "wb").write(binf)

check("F1 尺寸探测（PNG IHDR / JPEG SOFn / 文本→未知）",
      ex.image_size(os.path.join(ctx_ws, "big.png")) == (3000, 120)
      and ex.image_size(os.path.join(ctx_ws, "photo.jpg")) == (800, 600)
      and ex.image_size(os.path.join(ctx_ws, "notes.txt")) == (None, None),
      str(ex.image_size(os.path.join(ctx_ws, "photo.jpg"))))
check("F1b 类型嗅探不把二进制当文本",
      ex.sniff_kind(png) == "image:png" and ex.sniff_kind(binf) == "binary"
      and ex.sniff_kind(txt.encode("utf-8")) == "text")

msgs, meta = ex.build_messages(
    {"workdir": ctx_ws, "user_prompt": "看这些文件",
     "context_files": ["big.png", "photo.jpg", "notes.txt", "archive.bin"]},
    tmp_job)
_user = [m for m in msgs if m["role"] == "user"][0]["content"]
check("F2 图像不读内容 + 尺寸/超限/未压缩如实登记",
      "kind=\"image\"" in _user and "width=\"3000\"" in _user
      and "oversize=\"true\"" in _user and "compressed=\"false\"" in _user
      and "先压缩" in _user and "3000x120" in _user, _user[:300])
check("F3 二进制不读内容（NUL 哨兵不进正文）",
      "kind=\"binary\"" in _user and "PK\x03\x04" not in _user)
check("F4 文本块行为不变（逐字全文）",
      f'<context path="notes.txt">\n{txt}\n</context>' in _user)
check("F5 图像计入预算折算（4800 字符/张 → est_tokens=1200）",
      meta["images"] == 2 and meta["binaries"] == 1
      and meta["image_tokens"] == 2 * ex.IMAGE_EST_TOKENS
      and ex.IMAGE_EST_TOKENS == 1200, str(meta))
check("F5b 未压缩图像同样计入（预算口径不因阈值豁免）",
      meta["image_tokens"] == 2400, str(meta["image_tokens"]))

# base_tokens（图像折算）参与预算判定 → 交回续跑
_seq3 = [json.loads(json.dumps(resp_route))]
with mock.patch.object(ex, "_post_chat", side_effect=lambda b, t: _seq3.pop(0)):
    out = ex.run_with_tools({"model": "m1", "tools": ["lingshu_cg"],
                             "context_budget_tokens": 1300},
                            [{"role": "user", "content": "q"}], "job_d",
                            base_tokens=ex.IMAGE_EST_TOKENS)
check("F6 图像折算计入预算（base_tokens 阻塞于首轮）",
      out.get("need_continue") is True
      and out["handoff"]["est_tokens"] >= ex.IMAGE_EST_TOKENS, str(out)[:200])

# system prompt 真源（Pi⑦⑥）：声明 from → 每次执行重建；缺文件 fail-closed
pfile = os.path.join(ctx_ws, "prompt.md")
open(pfile, "w", encoding="utf-8").write("纪律真源 v1")
_s, src = ex.resolve_system_prompt({"system_prompt_from": "prompt.md",
                                    "workdir": ctx_ws,
                                    "system_prompt": "旧提示词"}, tmp_job)
check("F7 system_prompt_from 重建覆盖旧字面量",
      _s == "纪律真源 v1" and src == "file:prompt.md", f"{_s!r}/{src}")
open(pfile, "w", encoding="utf-8").write("纪律真源 v2（已更新）")
_s2, _ = ex.resolve_system_prompt({"system_prompt_from": "prompt.md",
                                   "workdir": ctx_ws}, tmp_job)
check("F7b 同 spec 重跑取到最新真源（崩溃重投不复用旧提示词）",
      _s2 == "纪律真源 v2（已更新）", _s2)
try:
    ex.resolve_system_prompt({"system_prompt_from": "nope.md",
                              "workdir": ctx_ws}, tmp_job)
    _raised = False
except ex.SpecError:
    _raised = True
check("F8 真源缺失 fail-closed（不回落旧提示词）", _raised)
_lit, src_lit = ex.resolve_system_prompt({"system_prompt": "字面量"}, tmp_job)
check("F9 未声明 from 时行为逐位兼容（literal 标签）",
      _lit == "字面量" and src_lit == "literal")

# ---------------------------------------------------------------- G read_file
print("[G] read_file 只读工具（读放开 / 写严格）")

rw = tempfile.mkdtemp(prefix="hive_exec_read_")
os.makedirs(os.path.join(rw, "sub"))
open(os.path.join(rw, "lines.txt"), "w", encoding="utf-8").write(
    "".join(f"第{i}行\n" for i in range(1, 6)))
open(os.path.join(rw, "sub", "inner.txt"), "w", encoding="utf-8").write("内层内容")
open(os.path.join(rw, "big.png"), "wb").write(png)
open(os.path.join(rw, "archive.bin"), "wb").write(binf)

check("G1 schema 参数面只有只读键（无任何写参数）",
      set(ex.TOOL_SCHEMAS["read_file"]["function"]["parameters"]["properties"])
      == {"path", "offset", "limit", "max_chars"},
      str(ex.TOOL_SCHEMAS["read_file"]["function"]["parameters"]["properties"]))

_o = ex.tool_read_file({"path": "lines.txt"}, workdir=rw)
check("G2 相对路径以 workdir 为基准 + 全文行窗元数据",
      _o["ok"] and _o["kind"] == "text" and _o["lines_total"] == 5
      and _o["lines_returned"] == 5 and _o["content"].startswith("第1行")
      and _o["replacements"] == 0 and _o["encoding"] == "utf-8(replace)",
      str(_o)[:200])

_o = ex.tool_read_file({"path": "lines.txt", "offset": 2, "limit": 2}, workdir=rw)
check("G3 offset/limit 分页续读（第2-3行，窗口满即 truncated）",
      _o["ok"] and _o["offset"] == 2 and _o["lines_returned"] == 2
      and _o["content"] == "第2行\n第3行\n" and _o["lines_total"] == 5
      and _o["truncated"] is True, str(_o)[:200])

_o = ex.tool_read_file({"path": "lines.txt", "max_chars": 3}, workdir=rw)
check("G4 max_chars 截断（不把整文件灌进上下文）",
      _o["ok"] and _o["lines_returned"] == 1 and _o["truncated"] is True,
      str(_o)[:200])

# v14 缺陷 A 回归（2026-09-20）：字符上限是**硬约束**——单行本身超过上限时
# 必须截断该行，不得整行放行（旧实现 max_chars=100 会回吐 1,000,000 字符，
# READ_HARD_CHARS 自称「硬上限」名实不符，足以撑爆宿主上下文）。
# 独立目录：避免污染 G5 的 rw 目录条目计数。
rwbig = tempfile.mkdtemp(prefix="hive_exec_readbig_")
open(os.path.join(rwbig, "minified.js"), "w",
     encoding="utf-8").write("y" * 1000000)
_o = ex.tool_read_file({"path": "minified.js", "max_chars": 100}, workdir=rwbig)
check("G4b 单行超长文件：max_chars 硬约束（不整行放行）",
      _o["ok"] and len(_o["content"]) <= 100 and _o["truncated"] is True,
      f"content_len={len(_o.get('content') or '')}")
_o = ex.tool_read_file({"path": "minified.js", "limit": 1}, workdir=rwbig)
check("G4c 单行超长文件：默认上限下亦不越界",
      _o["ok"] and len(_o["content"]) <= ex.READ_MAX_CHARS,
      f"content_len={len(_o.get('content') or '')}")
_o = ex.tool_read_file({"path": "minified.js", "max_chars": 10 ** 9},
                       workdir=rwbig)
check("G4d max_chars 请求夹到 READ_HARD_CHARS 且真实生效",
      _o["ok"] and len(_o["content"]) <= ex.READ_HARD_CHARS,
      f"content_len={len(_o.get('content') or '')}")
_o = ex.tool_read_file({"path": "lines.txt", "max_chars": 100}, workdir=rw)
check("G4e 多行文件仍按整行收（行粒度软上限语义不变）",
      _o["ok"] and _o["content"] == "".join(f"第{i}行\n" for i in range(1, 6)),
      repr((_o.get("content") or "")[:40]))
del _o

_o = ex.tool_read_file({"path": "."}, workdir=rw)
_names = {e["name"]: e for e in _o.get("entries") or []}
check("G5 目录给清单（子目录优先、带类型与字节）",
      _o["ok"] and _o["kind"] == "dir" and _o["total"] == 4
      and _o["entries"][0]["name"] == "sub"
      and _names["sub"]["type"] == "dir" and _names["sub"]["bytes"] is None
      and _names["lines.txt"]["bytes"] > 0, str(_o)[:200])

_o = ex.tool_read_file({"path": "big.png"}, workdir=rw)
check("G6 图像只给元数据不给正文（尺寸另附）",
      _o["ok"] and _o["kind"] == "image:png" and _o["content"] is None
      and (_o["width"], _o["height"]) == (3000, 120), str(_o)[:200])

_o = ex.tool_read_file({"path": "archive.bin"}, workdir=rw)
check("G7 二进制只给类型+字节数（不猜内容）",
      _o["ok"] and _o["kind"] == "binary" and _o["content"] is None
      and _o["bytes"] > 0, str(_o)[:160])

open(os.path.join(rw, "gbk.txt"), "wb").write("中文内容".encode("gbk"))
_o = ex.tool_read_file({"path": "gbk.txt"}, workdir=rw)
check("G8 非 UTF-8 按替换处标记存疑（不静默当正文）",
      _o["ok"] and _o["replacements"] > 0 and "存疑" in (_o.get("note") or ""),
      str(_o)[:160])

_o = ex.tool_read_file({"path": "nope.txt"}, workdir=rw)
check("G9 路径不存在诚实报错（不猜内容）",
      _o["ok"] is False and "路径不存在" in _o["error"], str(_o)[:160])
_o = ex.tool_read_file({"path": " "}, workdir=rw)
check("G10 path 必填", _o["ok"] is False and "必填" in _o["error"])

# 白名单：非空即收窄（越界拒读）；未设置 = 读放开（缺省）
out_dir = tempfile.mkdtemp(prefix="hive_exec_outside_")
open(os.path.join(out_dir, "secret.txt"), "w", encoding="utf-8").write("外部文件")
os.environ["HIVE_READ_ROOTS"] = rw + os.pathsep + out_dir
_o = ex.tool_read_file({"path": os.path.join(out_dir, "secret.txt")})
check("G11 白名单内可读（多根按 os.pathsep 切分）", _o["ok"] is True,
      str(_o)[:160])
os.environ["HIVE_READ_ROOTS"] = out_dir
_o = ex.tool_read_file({"path": os.path.join(rw, "lines.txt")})
check("G12 越界拒读（越界即拒，不猜内容）",
      _o["ok"] is False and "白名单" in _o["error"]
      and _o.get("roots") == [os.path.realpath(out_dir)], str(_o)[:200])
os.environ.pop("HIVE_READ_ROOTS", None)
_o = ex.tool_read_file({"path": os.path.join(rw, "lines.txt")})
check("G13 未设置环境变量 = 读放开（缺省全路径开放）", _o["ok"] is True)

_o, _b = ex.execute_tool("read_file", json.dumps({"path": "lines.txt"}),
                         "job_r", workdir=rw)
check("G14 execute_tool 透传 workdir 并正常分发",
      _o["ok"] is True and _b == "ok items=0", f"{_o!r}/{_b!r}")
_o, _ = ex.execute_tool("nope", "{}", "job_r")
check("G15 未知工具错误列出 read_file", "read_file" in _o["error"])

# ------------------------------------------------ H model↔base 配对前置校验
# 能红说明：删掉 model_base_mismatch 或 main() 的插桩调用时，H1–H5 语义即失去守卫；
# 回归 2026-09-23 归因（jobs error 12 中 1 个 = glm 模型错配 deepseek base 烧到 API 才 400）。
print("[H] model↔base 配对前置校验（子代理配置标准 v0.5 §1）")
check("H1 deepseek base + glm 模型 → 错配",
      ex.model_base_mismatch("glm-5.3-flash", "https://api.deepseek.com")
      is not None and "deepseek base" in (ex.model_base_mismatch(
          "glm-5.3-flash", "https://api.deepseek.com") or ""))
check("H2 deepseek base + deepseek 模型 → 放行",
      ex.model_base_mismatch("deepseek-flash", "https://api.deepseek.com") is None)
check("H3 智谱 base + deepseek 模型 → 错配",
      ex.model_base_mismatch("deepseek-flash",
                             "https://open.bigmodel.cn/api/paas/v4") is not None)
check("H4 智谱 base + glm 模型 → 放行",
      ex.model_base_mismatch("glm-5.3-flash",
                             "https://open.bigmodel.cn/api/paas/v4") is None)
check("H5 未知网关放行（不误伤自定义 base）",
      ex.model_base_mismatch("whatever-model", "https://my-gw.example/v1") is None)
check("H6 空 model 放行（缺 model 由 rust 必填校验拦）",
      ex.model_base_mismatch("", "https://api.deepseek.com") is None)

# ------------------------------------------------ I M3.2 写通道双轨制（worker 拦截）
# 能红说明：删 tool_lingshu_cg 的 M3.2 拦截段（layer 限 contextual / on_conflict=record
# 覆写 / 来源行注入）时 I1–I4 即红；编排身份放行由 I5 守卫（误拦收口写同红）。
print("[I] M3.2 双轨制：worker 过程性直写约束（D3 裁决）")
_captured = {}


def _fake_dispatch(cg, args, **kw):
    _captured.update(args)
    return {"ok": True, "written": 1, "node_id": "n_test"}


from md_cg import mcp_server as _msrv
from unittest import mock as _mock

with _mock.patch.object(_msrv, "_cg_dispatch", _fake_dispatch):
    # I1 worker 写 knowledge → 拦（收口写归编排者）
    out = ex.tool_lingshu_cg(
        {"op": "write", "content": "x", "layer": "knowledge"}, "job_i1")
    check("I1 worker 写 knowledge 被拒（双轨制）",
          out["ok"] is False and "contextual" in out["error"], str(out)[:150])
    # I2 worker 写 contextual → 放行 + on_conflict 覆写 record + 来源行注入
    _captured.clear()
    out = ex.tool_lingshu_cg(
        {"op": "write", "content": "过程记录", "layer": "contextual"}, "job_i2")
    check("I2 worker contextual 放行", out["ok"] is True, str(out)[:120])
    check("I3 on_conflict 强制覆写 record",
          _captured.get("on_conflict") == "record", str(_captured.get("on_conflict")))
    check("I4 来源行自动注入（job + 父任务=none）",
          "来源 job=job_i2" in str(_captured.get("content"))
          and "父任务=none" in str(_captured.get("content")),
          str(_captured.get("content"))[-80:])
    # I5 编排身份（注册工厂）写 knowledge → 放行且不被覆写
    ex.set_principal_factory(
        lambda a, j: __import__("md_cg.security", fromlist=["Principal"])
        .Principal(actor="hive-orch", clearance="secret", can_write=True,
                   can_admin=False, role="orchestrator", auth_mode="hive-exec"))
    _captured.clear()
    out = ex.tool_lingshu_cg(
        {"op": "write", "content": "收口结论", "layer": "knowledge"},
        "job_i5")
    check("I5 编排者收口写 knowledge 放行且不被覆写",
          out["ok"] is True and _captured.get("layer") == "knowledge"
          and "on_conflict" not in _captured,
          f"{out!r}/{_captured.get('layer')}")
    ex.set_principal_factory(None)

# ------------------------------------------------ J M4 效力轴透传（schema + args）
# 能红说明：删 LINGSHU_TOOL_SCHEMA 的 valid_from/valid_until 声明时 J1/J2 红；
# tool_lingshu_cg 若改动 args 白名单过滤导致效力轴丢失时 J3 红。
print("[J] M4 效力轴：schema 声明 + args 原样透传（不做自动推导）")
_props = ex.LINGSHU_TOOL_SCHEMA["function"]["parameters"]["properties"]
check("J1 schema 声明 valid_from/valid_until",
      "valid_from" in _props and "valid_until" in _props)
check("J2 声明含「不填=现行为」默认规则（不自动推导）",
      "不填=现行为" in _props["valid_from"]["description"]
      and "不填" in _props["valid_until"]["description"])
_captured.clear()
with _mock.patch.object(_msrv, "_cg_dispatch", _fake_dispatch):
    out = ex.tool_lingshu_cg(
        {"op": "write", "content": "时效结论", "layer": "contextual",
         "valid_from": "2026-09-23", "valid_until": "2026-12-31"}, "job_j")
    check("J3 效力轴参数原样透传库层（exec 层不吞不猜）",
          out["ok"] is True
          and _captured.get("valid_from") == "2026-09-23"
          and _captured.get("valid_until") == "2026-12-31",
          str(_captured)[:150])

# ------------------------------------------------ K result.json 原子写（v2 N6）
# 能红说明：write_result 若退回 open("w") 裸写（无 tmp+fsync+os.replace），
# K2 并发压测必现撕裂/空窗（旧码线程形态实测 torn=22+empty=11）；rust serve
# 超时/kill 强杀落在写入窗口即留半截文件且先毁旧完整结果。
print("[K] write_result 原子性（tmp+fsync+replace，N6 红守卫 2026-09-25）")
_k_tmp = tempfile.mkdtemp(prefix="hive_exec_n6_")
try:
    ex.write_result(_k_tmp, {"ok": True, "content": "k1"})
    _k_raw = open(os.path.join(_k_tmp, "result.json"), encoding="utf-8").read()
    check("K1 写后 result.json 完整且无 .tmp 残留",
          json.loads(_k_raw).get("ok") is True
          and not os.path.exists(os.path.join(_k_tmp, "result.json.tmp")),
          _k_raw[:80])
    _k_stop = False
    _k_stat = {"torn": 0, "empty": 0, "ok": 0, "replace_starved": 0}

    def _k_reader():
        p_ = os.path.join(_k_tmp, "result.json")
        while not _k_stop:
            try:
                raw = open(p_, "rb").read()
                if not raw:
                    _k_stat["empty"] += 1
                else:
                    json.loads(raw.decode("utf-8", "replace"))
                    _k_stat["ok"] += 1
            except json.JSONDecodeError:
                _k_stat["torn"] += 1
            except OSError:
                pass

    # daemon=True（2026-09-25 全量第 1 轮超时归因）：reader 非 daemon 时，
    # 写循环若死于未捕获异常（见下 PermissionError），_k_stop 永不为 True，
    # 两个紧循环 reader 让进程永不退出——回归表现为「超时（>900s）」而非
    # FAIL，掩盖真实错误。daemon 化保证任何异常形态下进程都能退出。
    _k_rs = [threading.Thread(target=_k_reader, daemon=True) for _ in range(2)]
    for _t in _k_rs:
        _t.start()
    _k_writes = 0
    for _i in range(20):
        try:
            ex.write_result(_k_tmp, {"ok": True, "content": "x" * 1024 * 1024})
            _k_writes += 1
        except PermissionError:
            # Windows 读者瞬态句柄可把 replace 的 50 次重试整个耗尽（--jobs 4
            # 满载下实测连续多轮，每轮 12.75s 白等）：这是 write_result 的
            # fail-safe 设计内形态（exec.py 注释：旧完整态保留、tmp 残留
            # 可辨），**不是**撕裂/空窗——K2 守卫的是后者。记数不中断，
            # 由下方「写成功 ≥1」断言兜底：全部饿死时 K2 无效，必须红。
            _k_stat["replace_starved"] += 1
    _k_stop = True
    for _t in _k_rs:
        _t.join()
    check("K2 并发写读压测 0 撕裂（半截/空窗均不许出现）",
          _k_stat["torn"] == 0 and _k_stat["empty"] == 0 and _k_writes >= 1,
          str(_k_stat))
finally:
    shutil.rmtree(_k_tmp, ignore_errors=True)

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
