# -*- coding: utf-8 -*-
"""mock_mcp.py · 模拟灵枢 MCP stdio 服务（供桥接测试）
- initialize → 正常响应
- notifications/initialized → 忽略
- tools/list → 返回 normal_tool + slow_tool（slow_tool 故意不响应）
- tools/call: normal_tool 立即响应；slow_tool 永不响应（模拟子进程挂死）"""
import sys, json, time

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        rid = msg.get('id')
        method = msg.get('method')
        if rid is None:
            continue  # 通知
        if method == 'initialize':
            out = {"jsonrpc": "2.0", "id": rid,
                   "result": {"protocolVersion": "2024-11-05",
                              "capabilities": {"tools": {}},
                              "serverInfo": {"name": "mock", "version": "0.0.1"}}}
        elif method == 'tools/list':
            out = {"jsonrpc": "2.0", "id": rid, "result": {"tools": [
                {"name": "normal_tool", "description": "正常工具",
                 "inputSchema": {"type": "object"}},
                {"name": "slow_tool", "description": "永不响应的工具",
                 "inputSchema": {"type": "object"}},
            ]}}
        elif method == 'tools/call':
            params = msg.get('params', {})
            name = params.get('name', '')
            if name == 'slow_tool':
                continue  # 故意不响应 → 触发桥接超时
            out = {"jsonrpc": "2.0", "id": rid,
                   "result": {"content": [{"type": "text", "text": '{"ok": true}'}],
                              "isError": False}}
        else:
            out = {"jsonrpc": "2.0", "id": rid,
                   "error": {"code": -32601, "message": f"unknown {method}"}}
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + '\n')
        sys.stdout.flush()

if __name__ == '__main__':
    main()
