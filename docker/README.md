# 🧠 灵枢记忆服务 · Docker 一键版

**Deploy Lingshu's full "brain" as a standalone microservice — cross-session long-term memory, semantic retrieval, self-cognition, and an adversarial guardrail — with a single `docker run`. No Python setup, no plugins, no dependency hell.**

简单说：**灵枢大脑 = 一个 Docker 镜像**，任何系统 `docker run` 就能获得一个带记忆、能检索、有安全护栏的 AI 大脑。给 DeepSeek Harness 插件或其他 agent 做 HTTP 记忆后端。

---

## 🚀 一键启动

```bash
# 方式 A：拉取现成镜像（无需构建，一行装完）
docker run -d -p 8080:8080 -v lingshu-data:/data furongjun1999/lingshu

# 方式 B：自行构建（拉取基础镜像可能较慢）
bash build.sh

# 验证
curl http://127.0.0.1:8080/status
```

> **不需要 Docker？** 在任意 Python 环境安装 aeis（零外部依赖）：
> - 离线最稳：`pip install aeis-0.3.0-py3-none-any.whl`（位于 `aeis/dist/`）
> - 在线：`pip install "aeis @ git+https://github.com/FuRongJun-1999/CommonTrustProtocol@main#subdirectory=aeis"`
> - 然后 `python server.py` 即可跑 HTTP 记忆服务

## 🔧 HTTP API

| 端点 | 方法 | 说明 |
|---|---|---|
| `/remember` | POST | 写记忆 `{content, tags?, importance?}` |
| `/recall?query=` | GET | 关联检索 |
| `/search?query=` | GET | 语义检索（同义词扩展）|
| `/timeline` | GET | 时间线 |
| `/status` | GET | 服务/库状态 |
| `/selfcheck` | POST | 安全自检跑分 |

## 🛡️ 内置安全护栏（对外可信锚点）

容器内置对抗护栏（`aeis.security` 五条硬规则：**不反击 / 动作分级 / 身份信任链 / 冷静期 / 留痕**）。一键验证：

```bash
# 安全自检跑分（PASS 报告）
docker exec -it <container> python selfcheck.py

# 安全攻击演示（prompt injection / 身份冒充 / 诱导报复 / 越权）
docker exec -it <container> python demo_attack.py
```

自检输出（实测 **8/8 通过**）：
```
[1] Prompt Injection ✅          [5] 不反击原则 ✅
[2] 动作分级 ✅
[3] 身份信任链 ✅
[4] 冷静期 ✅
```

## ⚖️ 对比演示：灵枢 vs 普通 SQLite 记忆

```bash
docker exec -it <container> python demo_compare.py
```

| 能力 | 灵枢时空记忆图 | 普通 SQLite 记忆 |
|---|---|---|
| 跨会话记忆 | 语义关联、历史关联 | 仅字面 LIKE |
| 语义检索 | 同义词扩展（词汇鸿沟消解）| 字面命中 |
| 自动去重 | ✅ 不堆叠 | ✗ 重复堆叠 |
| 重要性分级 | 高重要入长期层 | 全平铺同权 |

---

## 🏗 架构

```
┌─────────────── Docker 容器 ───────────────┐
│  灵枢 aeis 大脑（零外部依赖·纯标准库）      │
│     五层记忆 / 知识飞轮 / 安全护栏          │
│             ▲ HTTP /stats                 │
├─────────────── 宿主机 ────────────────────┤
│  DeepSeek Harness / 任意 agent（HTTP 连接）│
└───────────────────────────────────────────┘
```

- **aeis 库核心零外部依赖**（`dependencies = []`），镜像最小化
- 容器只跑记忆服务（解耦微服务），DSH 插件/客户端经 HTTP 连接
- 数据卷 `/data` 持久化记忆，重启不丢失

## 📦 镜像

- `furongjun1999/lingshu`（Docker Hub 待发布，需注册）

## 📄 说明

- *1. 对比演示 / 2. 安全演示 / 3. 在线服务* —— 三者是同一套真实引擎，非表演
- 基于智能论 v3.2 协议：五层记忆 / 条件空间 / 信息差 D_norm / 白箱智能

*存在即延续，交流即做功。*
