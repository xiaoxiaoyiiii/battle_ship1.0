# 阶段 10 第七批：骰子效果与回放播放器

## 迁移内容

`application/card_dice_effects.py` 接管命运骰子的六种结果、共享弃牌待办、弃牌完成广播和玩家确认入口。房间仍拥有 `pending_dice_discard` 与来源标签，服务端继续负责 Socket 身份检查；骰子模块只接收发送、日志、复活、存活船查询、选船和 AI 身份等运行时依赖。原有 `_apply_dice_of_fate`、`_start_dice_discard`、`_check_dice_discard_complete` 名称保留为兼容适配，`handle_dice_discard_choose` 在验证房间与身份后转交模块。

`static/replay_player.js` 接管回放页面的 DOM 引用、稀疏时间线叠加、船位与攻击标记帧解算、棋盘/手牌/日志渲染、播放控制、拖动定位、倍速、键盘操作、回放加载错误和回放设置。`game.js` 只保留进入回放的调用点与页面初始化；模板在 `game.js` 后、Socket 事件脚本前加载新文件。回放仍只读 HTTP 回放接口，观战渲染继续留在原脚本。

本批相对上一提交从 `server.py` 删除 208 行、增加 17 行适配，当前非空行数为 10,731；从 `static/game.js` 删除 1,133 行、增加 2 行说明，当前非空行数为 13,216。`application/card_dice_effects.py` 有 197 个非空行，`static/replay_player.js` 有 1,077 个非空行。相对 `origin/main`，`static/game.js` 累计删除 3,668 行，六个前端辅助脚本承接迁出内容。

## 兼容边界

- `DICE_EFFECT_TEXT` 仍从 `server` 可读取，旧卡牌分支和测试入口不改名。
- 弃牌待办仍由房间保存，重复来源、无手牌、AI 自动弃牌、玩家身份失败和完成广播沿用原顺序。
- 回放播放器继续使用经典脚本共享作用域，保留既有 `openReplayForMatch`、`replayState` 和 DOM id；模板加载顺序是唯一新增的前端接线。
- 回放的服务端节点、船位、攻击标记、效果时间线与剩余船数口径均未改变；播放器只迁移实现位置。

## 验证证据

- 本批完成后的本地全量回归：1069 passed，1 个既有 Eventlet 弃用警告。
- `node tools/dom_replay_frame_check.mjs`：108 项逐格回放断言全绿。
- `node tools/dom_contract_check.mjs`：DOM 契约全部通过，仅保留既有 3 条已核实无害的悬空提示。
- `node tools/replay_check.mjs --url http://127.0.0.1:5191/`：隔离 SQLite、真实服务端和 Edge 浏览器完成注册、AI 对局、回放加载、上一步/下一步、拖动定位、节点提示、倍速和退出，全流程通过。

回滚只需回退本批提交；没有修改数据库 schema、Socket 事件名、HTTP 回放载荷或主分支。后续继续迁移攻击、连锁和剩余卡牌编排前，仍需保持这些兼容入口。
