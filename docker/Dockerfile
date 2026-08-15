# 灵枢记忆服务 · Docker 镜像
# 最小化：python slim + 本地 aeis 源码（aeis 核心零外部依赖，未发布 PyPI）
# 架构：容器只跑 aeis 记忆 HTTP 服务（解耦微服务），DSH/客户端经 HTTP 连接
#
# 构建（用 build.sh，它会先复制 aeis 源码到本目录再构建）：
#   docker build -t furongjun1999/lingshu .
FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# aeis 源码（build.sh 已复制到 ./aeis_context/）+ 服务脚本
COPY aeis_context/ aeis/
COPY server.py selfcheck.py demo_compare.py demo_attack.py ./

# 数据卷：记忆持久化
VOLUME ["/data"]
ENV LINGSHU_DB=/data/lingshu.db

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/status || exit 1

CMD ["python", "/app/server.py"]
