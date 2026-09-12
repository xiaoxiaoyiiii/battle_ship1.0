# 新功能 / 改进优化建议

> 制定日期：2026-09-13 ｜ 依据：**当前工作区实测**（`server.py` 5343 行 / `static/game.js` 5925 行 / `static/style.css` 2251 行，比 `CLAUDE.md` 记录的 5246 / 6032 / 2173 有未提交改动）。
> 本文所有结论均带实测证据（行号 + 原文）；凡未实测的推测会显式标注。
> 与 `docs/FIX_PLAN.md`（缺陷修复，已全部完成）互补：本文只谈**新增能力**与**结构优化**。

---

## 0. 结论速览

推荐 10 项，按「感知收益 ÷ 成本」排序：

| 优先级 | 项目 | 类型 | 预估成本 | 一句话价值 |
| --- | --- | --- | --- | --- |
| P0-1 | 房间邀请链接一键复制 | 新功能（半成品收尾） | 0.5 小时 | 前端自动入房**已写好**，只差一个按钮 |
| P0-2 | 战斗音效 SFX | 新功能 | 0.5 天 | 全项目**零音效**，感知提升最直接 |
| P0-3 | AI 会用魔法卡 + 三档难度 | 新功能 | 1–2 天 | AI 现在**一张卡都不出**，单点收益最高 |
| P0-4 | 卡牌图鉴页 | 新功能 | 0.5 天 | 41 张卡的新手门槛，零件已齐 |
| P1-5 | 回合思考计时器 | 新功能 | 1 天 | 只有连锁有超时，炮击阶段可无限长考 |
| P1-6 | 魔法卡使用统计 | 新功能 | 1 天 | 卡牌平衡目前**零数据支撑** |
| P1-7 | 卡牌数据单一来源 | 优化 | 0.5 天 | 消灭"改一张卡要同步 4 处"的漏改风险 |
| P1-8 | 测试护栏补强 | 优化 | 0.5 天 | 12 个高危调试事件里 **11 个无回归覆盖** |
| P2-9 | 对局复盘（只读回放） | 新功能 | 2–3 天 | 把日志升级成可播放时间轴 |
| P2-10 | 在线观战 | 新功能 | 3–5 天 | 成本最高，建议最后做 |

---

## 1. 三个关键判断（先看这节，能省下大量无效投入）

### 判断 A：AI 的**炮击逻辑没有优化空间**，别在这上面花时间

本体是 **6 艘单格船 × 6×6 棋盘**：

```python
# server.py:559（另有 782 / 915 / 2375 三处同样写法）
all_positions = [(x, y) for x in range(6) for y in range(6)]
# server.py:2378 —— AI 也是单格船
player.ships.append(PlayerShip(positions=[Position(x=px, y=py)], hits=[]))
```

经典战舰的「命中后搜索四邻格」启发式在这里**完全无效**——船**只有一格**。
在没有任何信息类卡牌时，每一发只要打「未打过的格子」，命中概率都是 `剩余船数 / 剩余空格数`，**与选择顺序无关**。

> 所以 `_ai_turn_loop`（`server.py:2392`）里的 `random.choice(candidates)`（2413 行）**不是偷懒，而是数学上接近最优**。
> 真正让 AI 显弱的是下面这条。

### 判断 B：AI 最大的短板是**一张魔法卡都不出**

- 后端**已经给 AI 发了手牌**：`server.py:383`
  ```python
  room.init_player_magic(ai_id, magic_cards)
  ```
- 但 AI 回合驱动全程只有四条指令（`_maybe_run_ai_turn` 2382 / `_ai_turn_loop` 2392）：
  `enter_battle_phase` → `handle_attack` ×N → `handle_enter_end_phase` → `end_turn`
  **零处调用 `handle_use_magic_card`（`server.py:2634`）**
- AI 也**不响应连锁**：`_can_respond_chain`（2835）只挂在真人的 `chain_response` 链路上
- 结果：AI 手上握着从 41 张卡池抽到的牌，**永远不用**，包括能直接改命的 `神机妙算` / `疗愈` / `伊甸园`；玩家出速阶 3 卡时也没有任何被"康"的压力

### 判断 C：卡牌平衡**目前没有任何数据支撑**

- `db.py` 无卡牌使用记录表（grep `card_usage|magic_stats` → 0 处）
- `room.magic_history` 只存在内存里，对局结束即丢
- 41 张卡孰强孰弱全靠体感，**没有胜率、没有使用率**，平衡性迭代只能拍脑袋

---

## 2. 新功能建议

### P0-1 房间邀请链接：功能**已经写好**，只差一个按钮

**证据**：`static/game.js:5573-5600` 已完整实现 `?room=XXXX` 自动入房（含连接未就绪时挂 `connect` 重试、成功回调后切到布船界面）：

```javascript
// game.js:5574
const urlParams = new URLSearchParams(window.location.search);
const autoRoom = urlParams.get('room');
if (autoRoom) { /* ensureSocket() + join_room + 重试 */ }
```

而全项目 **0 处**「邀请 / 复制 / clipboard」UI（grep `game.js` 与 `index.html` 均为 none）。

**建议**：在自定义房间界面（`#custom-room-screen`，`index.html:68`）房间号旁加一个「🔗 复制邀请链接」按钮：

```javascript
navigator.clipboard.writeText(location.origin + '/?room=' + roomId)
```

失败时（非 HTTPS / 老浏览器）回退到 `prompt()` 展示让玩家手工复制。

**成本 < 1 小时**，把"口头报房间号"变成"甩个链接"，是目前性价比最高的一项。

### P0-2 战斗音效（SFX）

**证据**：全项目只有 `static/music_player.js:19` 一处 `new Audio()`，且是 BGM；**没有任何音效**。

**建议** 8 个音：炮击命中 / 落空 / 击沉 / 抽卡 / 出牌 / 连锁触发 / 回合开始 / 胜负结算。
实现要点：
- 用小型 `Audio` 池（同一音效快速连播要能叠，不能互相打断——AI 回合可能 0.3 秒一发，见 `_ai_turn_loop` 的 `time.sleep(0.3)`）
- 音量复用现有 `bgm_volume`，另加独立 `sfx_muted` 开关（设置面板的音量/静音控件可直接照抄）
- ⚠️ **浏览器自动播放策略**：必须在首次用户手势后才创建/播放。现有 BGM 的开关（`game.js:576` 的 `bgm_muted`）正好提供了这个手势点

**成本 0.5 天**（音效素材需自备）。

### P0-3 AI 会用魔法卡 + 三档难度 ← **单点收益最高**

按判断 A，**不碰炮击**，把全部智能投在魔法卡上：

1. **AI 会用信息类卡**：`探测雷达` 等区域探测卡 → 从"随机开火"升级为"按情报开火"，这是**唯一**能真正提升 AI 命中率的机制
2. **AI 会响应连锁**：给它接上 `chain_response` 的等价调用，且只在"对手这张卡确实威胁到我"时康，避免无脑康
3. **AI 会自保**：血量低时优先出回血 / 护盾 / 复活类，而不是留到死
4. **难度分档**：`create_ai_room` 增加 `difficulty` 参数
   - **简单** = 现状（只炮击、不出卡）→ 保底可赢，适合第一次玩的人
   - **普通** = 只用速阶 1，不响连锁
   - **困难** = 全卡池 + 响应连锁 + 关键回合保留速阶 3

**实现落点**：`server.py` 新增纯函数 `_ai_choose_magic(room, ai_id) -> (card_index, targets) | None`（纯函数、好单测），在 `_ai_turn_loop` 的 `enter_battle_phase` 之后调用，结果直接喂给**现有**的 `handle_use_magic_card`（`server.py:2634`）——**不需要改任何魔法卡结算代码**。

**成本 1–2 天**（决策器 + 3 档参数 + 回归测试）。
**收益**：人机是三种模式里唯一不需要真人对手的入口（`README.md`），AI 出卡能**顺带教会玩家 41 张卡的用法**。

### P0-4 卡牌图鉴页

**证据**：零件基本都在——
- `game.js:1319` `helpMagicCards.innerHTML = uniqueCards.map(...)` 已渲染全部卡名列表
- `game.js:1145` `lookupCard(name)` 按卡名取卡
- `game.js:1165` `renderLogTextHtml` 已实现日志内卡名悬停预览 / 点击详情

**建议**：把它升级成正式全屏图鉴页：按**速阶**（1/2/3）、**类型**（普通/场地）、**关键词**搜索、**按使用率排序**（配合 P1-6）；每张卡显示卡面文字 + "当前阶段是否可打"（结合 `current_phase` 与 `can_play_magic_card`）。

**成本 0.5 天**，直接缓解 41 张卡的新手门槛。

### P1-5 回合思考计时器

**证据**：目前**只有连锁窗口有超时**——

```python
# server.py:2765
CHAIN_RESPONSE_SECONDS = 10
```

炮击 / 准备阶段可以无限长考，对手只能干等（真人匹配场景下体验问题突出）。

**建议**：战斗 + 准备阶段加可配置回合计时（默认 90 秒，房主可关）。超时行为二选一：
- **(a) 自动随机开火一发（推荐）**——不打断对局，长考的人只是失去思考优势
- (b) 直接交出回合——惩罚更重但对劣势方可能过于致命

**实现**：复用 `_schedule_chain_timeout`（`server.py:2926`）那套 `socketio.start_background_task` + `time.sleep` 范式。
⚠️ 两个坑：eventlet 下**不要用 `threading.Timer`**；`disconnect` handler 内**不能同步 emit**（会卡死 hub，代码里已有多处注释警告）。

**成本 ~1 天**。

### P1-6 魔法卡使用统计（平衡性数据 + 内容运营）

**建议**：`match_logs` 表已有对局日志（`db.py:111`），`room.magic_history` 已有出牌记录，二者拼接入库即可。新增 `card_stats` 表（`card_name / plays / wins_when_played / caster_id`），或直接从 `match_logs` 聚合。

**产出**：排行榜页新增三个榜单 → 「最常用卡 / 胜率最高卡 / 冷板凳卡」。
一眼看出哪张卡**没人用**（该加强）、哪张卡**胜率畸高**（该削）。这是 41 张卡走向平衡的唯一数据来源。

**成本 ~1 天**（写库 + 聚合查询 + 一个小面板）。

### P2-9 对局复盘（只读回放）

**证据**：全项目 0 处 `spectat|replay`；但 `db.py:111` 已有 `match_logs` 表，个人战绩弹窗已能看「局内日志」（见 `docs/STATS_AND_AI_RANKING_FIXES.md`）。

**建议**：把日志升级为**可逐步播放的复盘**（棋盘快照 + 时间轴拖动）。**先做只读版，不做实时观战**——无需处理权限与私有信息过滤，风险低一个量级。
注意：当前日志**只有文本**，需在关键节点额外存棋盘快照（6×6 体积可控，不必存整局全量）。

**成本 2–3 天**。

### P2-10 在线观战

成本最高的一项：需要把观战 sid 放进房间但**排除在 `room.players` 之外**，且**必须过滤私有信息**（船位、手牌、`magic_temp_data`）。
好消息是有先例可循：此前已修过「船数广播按收件人视角下发」，`_build_room_sync` 的按视角裁剪思路可以直接复用。
**建议放在最后做**，先看 P2-9 的复盘数据是否已经够用。

---

## 3. 改进优化建议

### P1-7 卡牌数据单一来源：删掉 `static/magic_cards.js`

**现状证据**（`CLAUDE.md` §12 明写）：改一张卡要同步 **4 处**——`magic_card.json`、`magic_cards.js`、`apply_magic_effect` 分支、测试。
而一致性测试**只比对 3 个字段**：

```python
# tests/test_all_magic_cards.py:1516-1530
"""前端 magic_cards.js 的卡名/速度/类型必须与后端 magic_card.json 一致"""
backend = read_json('./static/magic_card.json')      # 1521 硬编码相对路径
...
pattern = re.compile(r'name:\s*"([^"]+)",\s*speed:\s*(\d+),\s*type:\s*"([^"]+)"')
frontend = [(m.group(1), int(m.group(2)), m.group(3)) for m in pattern.finditer(js_text)]
assert frontend == backend_seq
```

→ **`description` 完全不在校验范围内**，两边卡面文字写歪了测试也不会红。

`docs/FIX_PLAN.md:163` 其实已经开好了方子（`magic_card.json` 为唯一源）但没有执行。

**做法**：
1. `index.html:521` 的 `<script src="/static/magic_cards.js">` 换成模板注入 `window.magicCards`（后端 `magic_cards` 变量已存在，见 `server.py:339`）
2. 删除 `static/magic_cards.js`
3. 一致性测试改为**全字段比对**（含 `description`），或直接删掉（数据只有一个源后，该测试自然失去意义）

**成本 0.5 天**，永久消灭"改 4 处"里最容易漏的那一处。

### P1-8 测试护栏补强（防止已修缺陷回归）

| # | 问题 | 实测证据 | 建议 |
| --- | --- | --- | --- |
| 1 | **12 个 `test_*` 高危事件，只有 1 个有回归覆盖** | `server.py` 516–893 共 12 个 `@socketio.on('test_*')`；测试里只搜到 `test_win_game`（`tests/test_fixes_regression.py:64`、`tests/test_review_fixes_2026_09_12.py:63`），其余 **11 个无任何测试** | 补一个**参数化测试**：把 12 个事件名循环一遍，断言生产模式（`ENABLE_TEST_EVENTS` 未设）下**全部拒绝**。1 个测试守住 12 个最危险的 handler |
| 2 | 全套测试唯一对 CWD 敏感的用例 | `tests/test_all_magic_cards.py:1521/1522` 硬编码 `'./static/...'` | 改 `pathlib.Path(__file__).parent.parent / 'static' / ...` |
| 3 | 一致性测试漏 `description` | 见 P1-7 | 与 P1-7 一并解决 |
| 4 | 列表乘法产生**共享引用** | `tests/test_disconnect_and_eden_shenji.py:37` `[PlayerShip(positions=[], hits=[])] * 4` | 改列表推导式。共享引用会让"改 A 却影响 B"产生**假绿** |
| 5 | 名不符实的空测试 | `test_magic_effects.py` 的 `test_bomb_returns_affected_positions` 从不该字段断言（`CLAUDE.md` §11） | 补真实断言 |

> ⚠️ `CLAUDE.md` §11 提到的 `tests/test_auth_spoof.py` **当前已不存在**（`tests/` 下只有 10 个文件），该条文档说明已过时——但这不影响结论：12 个事件的覆盖缺口是**实测确认**的。

**成本 0.5 天**。这不是新功能，但决定了后续所有改动的安全边际——**建议排在所有新功能之前**。

### 其它小优化（按需）

| 项 | 证据 / 说明 | 成本 |
| --- | --- | --- |
| `eventlet.monkey_patch()` 时序 | `CLAUDE.md` §2 记录的隐患：`import db` / `from api import app` 排在 patch 之前。当前未观察到故障，但 patch 应最先执行（注意循环导入） | 1 小时 |
| `chat_messages` / `match_logs` 无限增长 | `db.py` 中唯一的 DELETE 是 `db.py:174` 的 `DELETE FROM active_games`；**聊天与对局日志没有任何清理策略** | 加定期清理或分页查询，2 小时 |
| 手机误触保护 | 移动端自适应布局已落地（`docs/MOBILE_ADAPTIVE_LAYOUT.md`），但 6×6 格子在小屏依然小。建议"点两下确认"或长按放大镜 | 0.5 天 |
| `/healthz` + 基础指标 | 目前只有 `server.py:5333` 一行 `logging.basicConfig`，线上排障基本靠 systemd journal。建议暴露在线人数 / 活跃房间数 / 异常计数（`/api/online_count` 已有先例） | 0.5 天 |
| 无障碍 | 浅色主题下卡牌 / 日志文字对比度；键盘操作与 `aria-label`（`toggleGameLog` 已有 `aria-label` 先例可照抄） | 按需 |

---

## 4. 明确**不建议**做的事（避免踩坑）

1. **给 AI 写"智能炮击"** —— 见判断 A。单格船下随机已近最优，投入产出比极低；AI 的智能应全部投在魔法卡（P0-3）上。
2. **热恢复 `active_games` 表** —— 该表目前是死代码（`docs/PROJECT_DEFECT_ANALYSIS.md:81` 已指出）。进程重启后精确恢复对局成本很高，而 eventlet 单进程 + 30 秒掉线宽限（`server.py:2948 _start_disconnect_grace`）已覆盖绝大多数实际场景，收益不成比例。
3. **`game.js` / `server.py` 大重构（拆模块）** —— 方向正确，但**不要与功能开发并行**：5925 行 + 5343 行的无模块化单文件，在测试护栏补强（P1-8）之前拆分，风险远大于收益。**建议顺序：P1-8 → P1-7 → 再考虑拆**。
4. **多语言 i18n** —— 全项目 0 处 i18n 基建，且当前用户群为中文，暂不必做。

---

## 5. 建议的落地顺序

| 阶段 | 内容 | 说明 |
| --- | --- | --- |
| **第 1 步（低垂果实）** | P0-1 邀请链接 → P1-8 测试护栏 → P0-2 音效 | 半天内可全部完成，先拿到"立刻可见"的收益与安全边际 |
| **第 2 步（核心体验）** | P0-3 AI 出卡 + 难度 → P0-4 卡牌图鉴 → P1-5 回合计时 | 人机体验与新手门槛，是留存的关键 |
| **第 3 步（数据与内容）** | P1-6 卡牌统计 → P1-7 数据单一来源 → P2-9 复盘 | 有了数据再谈卡牌平衡，有了复盘再谈观战 |

> 每完成一项，建议同步更新 `CLAUDE.md` 的对应章节与 `docs/` 记录——本项目文档与代码脱节已发生过多次（`README.md` 测试数、`CHAIN_ENGINE_SPEC.md`、`test_auth_spoof.py` 均已证实过时）。
