#!/usr/bin/env bash
# 灵枢 Docker 构建脚本
# 把 aeis 库源码复制进 build context → docker build → 清理临时 aeis
# 用法: ./build.sh   (或 docker/build.sh)

set -euo pipefail
cd "$(dirname "$0")"

REPO_AEIS="../../../aeis/aeis"   # 主仓库 aeis 包（CommonTrustProtocol/aeis/aeis）
CTX_AEIS="./aeis_context"

echo "=== 复制 aeis 源码到 build context ==="
if [ -d "$REPO_AEIS" ]; then
    rm -rf "$CTX_AEIS"
    cp -r "$REPO_AEIS" "$CTX_AEIS"
    echo "  ✓ 已复制: $REPO_AEIS → $CTX_AEIS ($(ls "$CTX_AEIS" | wc -l) 项)"
else
    echo "  ✗ 找不到 aeis 源码: $REPO_AEIS"
    exit 1
fi

echo "=== docker build ==="
docker build -t furongjun1999/lingshu:latest .

echo "=== 清理临时 aeis ==="
rm -rf "$CTX_AEIS"

echo ""
echo "✅ 构建完成: furongjun1999/lingshu:latest"
echo "   运行: docker run -d -p 8080:8080 -v lingshu-data:/data furongjun1999/lingshu"
echo "   状态: curl http://127.0.0.1:8080/status"
