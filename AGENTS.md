# AGENTS.md — lingshu-src（灵枢地基分册）

> 这个块的读数与结构见 项目现状.md（scripts/项目现状.mjs 生成）。

灵枢真源码树、唯一地基：认知图的节点存储 / 语义时空图 / 一致性 / 元认知 / 出处链 / 加密。入口 `md_cg\mdcg.py`。

## 不许

- 本树是 clone 的上游只读存档：非编排任务明确授权不得改 md_cg 等源码；要改先用 `intake.mjs` note 记假设，再写进本次 run。
- **服务器上不许就地改 `md_cg`** —— 上线只有一条路：改本树 → `git commit` → `cd D:\wook && node scripts\deploy-mdcg.mjs`。判据：`ssh aliyun 'cd /home/ubuntu/mdcg && git status --porcelain'` 必须为空；非空说明有人就地改过，先把改动回流到本树提交，再部署。根 `AGENTS.md` 硬规则 12。
- `_md_cg_p*`、`_md_cg_membench` 是库数据分片，不是源码，不得当源码改。
- 仓内既有 `codex/AGENTS.md`、`zcode/AGENTS.md` 一律不动。
