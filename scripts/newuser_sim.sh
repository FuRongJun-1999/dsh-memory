#!/usr/bin/env bash
# 新用户模拟（发布 0.5.0 前门禁）：以「拿到仓库的全新用户」身份在 Linux 容器
# 内走 README 快速开始承诺的主链路。
#
# 用法（宿主）：
#   docker run --rm -v <repo>:/work -w /work node:22-bookworm \
#     bash scripts/newuser_sim.sh
#
# 场景：
#   U1 干净 clone（排除宿主工作区状态——新用户拿到的是 git 仓库）
#   U2 node 构建面：npm install --include=dev && npm run build
#   U3 npm pack：发布件可产出、清单含 md_cg/ 大脑
#   U4 大脑直连：python3 -c 导入 + 令牌签发（部署侧）
#   U5 MCP stdio 新用户全链（scripts/newuser_mcp_sim.py）：
#     initialize → 空库首写(#26) → 检索 → 冲突入队+裁决 → ccgc 令牌签章(#27)
set -u
set -o pipefail

pass=0; fail=0
record() {
  if [ "$2" -eq 0 ]; then pass=$((pass+1)); echo "[PASS] $1"
  else fail=$((fail+1)); echo "[FAIL] $1"; fi
}

echo "=== 环境 ==="
node --version; npm --version | head -1
( apt-get update -qq && apt-get install -y -qq python3 >/dev/null ) 2>&1 | tail -1
python3 --version

echo "=== U1 干净 clone（新用户视角）==="
rm -rf /tmp/fresh && git clone --quiet file:///work /tmp/fresh
record "git clone 干净副本" $?
cd /tmp/fresh || exit 1
git log --oneline -1

echo "=== U2 node 构建面（README：npm install && npm run build）==="
npm install --include=dev --no-audit --no-fund >/tmp/npm_install.log 2>&1
record "npm install" $?
npm run build >/tmp/npm_build.log 2>&1
record "npm run build (tsc)" $?
[ -f lib/index.js ] && echo "    lib/index.js 产出 OK"

echo "=== U3 npm pack 发布件 ==="
npm pack >/tmp/pack.log 2>&1
record "npm pack" $?
TGZ=$(ls *.tgz 2>/dev/null | head -1)
echo "    TGZ=$TGZ"
tar tzf "$TGZ" >/tmp/manifest.txt   # 先落盘再 grep——pipefail 下 grep -q 提前退出会让 tar 吃 SIGPIPE 误判失败
grep -q "package/md_cg/mcp_server.py" /tmp/manifest.txt
record "发布件含大脑入口 md_cg/mcp_server.py" $?
grep -q "package/md_cg/writepipe.py" /tmp/manifest.txt
record "发布件含写管线 writepipe.py" $?
grep -q "package/skills/" /tmp/manifest.txt
record "发布件含 skills 分发件" $?

echo "=== U4 大脑直连（README 装后验证形态）==="
PYTHONUTF8=1 python3 -c "from md_cg.mdcos import MdCGSecure; print('md_cg 导入 OK')"
record "md_cg 导入" $?
PYTHONUTF8=1 python3 -c "
from md_cg import tokens
import tempfile, os
tf = os.path.join(tempfile.mkdtemp(), 'tokens.json')
r = tokens.issue('designer', actor='newuser', path=tf)
assert r['ok'] and r['token'].startswith('mdcg1.'), r
print('令牌签发 OK（部署侧）')"
record "令牌签发（部署侧）" $?

echo "=== U5 MCP stdio 新用户全链 ==="
PYTHONUTF8=1 python3 scripts/newuser_mcp_sim.py
record "MCP stdio 新用户全链" $?

echo "=== 汇总: $pass pass / $fail fail ==="
[ "$fail" -eq 0 ]
