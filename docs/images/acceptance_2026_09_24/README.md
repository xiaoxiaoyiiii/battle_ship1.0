# 落地验收出图（2026-09-24）

> 对应 `docs/LANDING_STATUS_2026_09_24.md` §7.1 —— **"验证效果"那一轮**的实证。
> 这一批图不是"顺手截的"：逐张看过之后改掉了 **4 个属性断言没抓住的真缺陷**（见 §7.1 的表）。
> 归档在这里而不是 `.tmp/`（`.tmp` 被 gitignore，关掉会话就没了）——
> `docs/FLUENT_UI_2026_09_21.md` §8 的教训就是"归档截图不看，等于没测"，而当时对局屏一张存档都没有。

| 文件 | 看什么 | 对应期 |
| --- | --- | --- |
| `01-home-fluent.png` | 首页 · 默认 Fluent 预设（对照组） | — |
| `02-home-arena.png` | 首页 · 竞技场预设：主行动按钮变紫、排位变金 | Phase 1 |
| `03-ingame-hand.png` | 对局 · 手牌一排真卡（名牌+速阶宝石+说明+类型条） | Phase 2 |
| `04-ingame-chain.png` | 对局 · 「当前连锁」叠牌 | Phase 3 |
| `05-target-select.png` | 对局 · 目标选择态（虚线锚点 + 确认按钮文案） | Phase 4 |
| `06-mobile-hand.png` | 手机 · 一屏一块棋盘（`我的棋盘 / 对手棋盘` 段控件）+ 底部面板槽 | Phase 5.2 |
| `07-codex.png` | 图鉴 · 41 张真卡（可滚动，说明 9 行） | Phase 6 |
| `08-card-closeup-wide.png` | **卡面 native 近景 @2x** —— 说明框 3 整行 + 省略号（缺陷 1/2 修完的样子） | Phase 2 |
| `09-chain-stack.png` | 连锁叠牌近景：三张压在一起、角标标「对手/你」、**已让开聊天浮窗**（缺陷 4） | Phase 3 |
| `10-target-select-bar.png` | 确认条近景：「3×3 已选中：第 2–4 列，第 2–4 行」+「确认使用 冻结！」 | Phase 4 |
| `11-mobile-big-card.png` | 手机抽屉里的 **200×280** 大卡面（比例 0.7143，说明完整可读） | Phase 5.3 |

## 复跑

```bash
BATTLESHIP_DB_PATH=.tmp/x.db CORS_ORIGINS=http://127.0.0.1:5055 PORT=5055 ENABLE_TEST_EVENTS=1 python server.py
node tools/acceptance_shots.mjs --url http://127.0.0.1:5055/ --out .tmp/acceptance   # 01–08
node tools/chain_stack_check.mjs   --url http://127.0.0.1:5055/ --out .tmp/chain.png   # 09
node tools/target_selection_check.mjs --url http://127.0.0.1:5055/ --shots .tmp/target # 10
node tools/mobile_bigcard_check.mjs --url http://127.0.0.1:5055/ --out .tmp/bigcard.png # 11
```

## ⚠️ 两条出图口径的坑（都写进了工具注释）

1. **`acceptance_shots.mjs` 的对局态不可靠**：它是绕过 UI 直接发 socket 推进对局的，
   于是 `#ship-placement-screen` 一直 active（实测 `placeActive:true`，把内容顶到 y≈1416）、
   切视口后 `--board-size` 会残留上一档的值 —— **同一套脚本不同轮次拍到的状态会不一样**
   （有一轮恰好打完了，`04` 拍成了结算屏）。所以：**归档前先看文件大小**（空白图只有几百字节，
   实测 `08` 有一轮是 166 字节的纯色），并且**以各期自己的门禁工具出图**为准。
2. **手机手牌近景不在 `acceptance_shots.mjs` 出**（同上的合成状态问题）：
   紧凑档布局由 `ui_layout_check.mjs --only compact` 走真流程验（手牌 y=684 在 844 视口内），
   手机卡面由 `mobile_bigcard_check.mjs` 出图（干净口径）。
