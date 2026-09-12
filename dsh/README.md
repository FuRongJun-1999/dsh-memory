# DSH 端 · 灵枢插件配置

本目录 = **DeepSeek Harness（DSH）harness 专属配置**。与 `codebuddy/`、`zcode/` 平级，
共享层（`md_cg/` 大脑、`data/`、`docs/`、`scripts/`）在仓库根。

## 目录内容

| 文件 | 作用 |
|---|---|
| `cordis.patch.yml` | 插件 **bundle 入口**（`package.json` 的 `dsh.bundle.patch` 指向本文件；裸 insert 声明） |
| `cordis.yml.example` | 插件配置示例（30+ 项：mdcg / memory / mutual / capability …） |
| `cordis-patch-profile-web.example.yml` | profile `web` 的 config override **备份模板**（换 profile / 重装 / 升级后须核对仍在） |
| `dsh-web-start.bat` | DSH web 宿主启动脚本（带 8GB heap 保护，防启动 OOM） |

## 安装

```bash
git clone https://github.com/FuRongJun-1999/dsh-memory.git
cd dsh-memory
npm install && npm run build          # tsc → lib/
dsh plugin --profile web add .        # 必须走 dsh plugin，勿用裸 npm install 装进 profile
```

再参照 `cordis.yml.example` 在 `<profile>/cordis.yml` 启用配置。

## 纪律注入（personaPrefix 受管块）

DSH 端的 16 条工作纪律**不走独立文件**，而是以 `compact` 变体写入
`~/.dsh/profiles/web/cordis.patch.yml` 的 `personaPrefix` 键，用受管标记块 `lingshu:discipline`
原地修订（保留注释）：

```
python scripts/render_discipline.py --target dsh --write
python scripts/verify_discipline.py --target dsh
```

> DSH 的 `personaPrefix` 是**每轮注入**的系统提示槽位，因此用 `compact` 变体；
> CodeBuddy / ZCode 是**会话起始注入**，用 `full` 变体。三角色同源于
> `docs/工作纪律_认知图条目_v1.1.json`，矩阵见 `docs/discipline/harnesses.yaml`。

## 与「三层拆分规划」的关系

本目录是**按 harness 维度**（DSH / CodeBuddy / ZCode）归置配置；
[`../docs/灵枢三层拆分规划_v0.1.md`](../docs/灵枢三层拆分规划_v0.1.md) 讨论的是**另一种正交维度**
（灵 / 脑 / 身 三仓职责分离，目标是主仓瘦身）。

二者在 `dsh-web-start.bat` 上存在**归属分歧**：三层规划拟将其移出主仓至「身体仓（宿主启动）」，
而本目录按 harness 维度将其收拢。该分歧**留待三层规划 Phase 裁决收敛**——本目录为其当前的
可追踪落点，不改变三层规划的结论。
