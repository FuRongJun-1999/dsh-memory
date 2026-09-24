#!/usr/bin/env bash
# 批次 33：Linux node 面验证——npm ci(匿名卷) + build + ts test。
set -u
cd /work
node --version
npm ci --no-audit --no-fund >/dev/null 2>&1
echo "ci=$?"
npm run build >/dev/null 2>&1
echo "build=$?"
node --import tsx --test test/*.test.ts >/tmp/ts_test.log 2>&1
echo "test=$?"
tail -6 /tmp/ts_test.log
