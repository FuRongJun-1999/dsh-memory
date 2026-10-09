# 灵枢悬赏板 · 荣誉榜

> 本页由 `scripts/bounty_board.py --board-out docs/bounty/board.md` 从
> `docs/bounty/ledger.json`（append-only 事件流）**机械生成**——勿手改，手改会在下一次生成时被覆盖。
> 账本事件数：0

计分口径（设计稿 §五 建议值，待设计者裁定）：easy 1 / medium 3 / hard 6 / expert 10；虚假交付 −5；超时未交付 −1；主动释放与争议提起不扣分（争议败诉记录在案、不扣本金）。

## 当前榜面

（暂无入账事件——账本为空；第一条 `/settle` 落账后本表自动出现。）

## 账本

事件流真源：`docs/bounty/ledger.json`（append-only、id 幂等；写入命令见 `docs/bounty/README.md`「账本收口」）。

---

本页与账本由 `scripts/bounty_board.py` 生成；状态机与命令面见 `docs/bounty/README.md`。
