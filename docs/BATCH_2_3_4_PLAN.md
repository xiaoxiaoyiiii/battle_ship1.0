# 第 2 / 3 / 4 批实现计划（徽章成就 · 社交互动 · 局内快捷语）

> 承接 `docs/PROFILE_CARD_2026_09_17.md`（第 1 批设计稿，已上线 `4659401`）。
> 第 1 批的分批理由见该文档 §2.1；本文只写**怎么做、谁负责哪些文件、怎么算做完**。
> ⚠️ 动手前先读本文 §1 的硬规矩与每批的契约，别照第 1 批的初版契约改（那份已经修过一次）。

---

## 1. 硬规矩（与第 1 批相同，踩过的坑都在里面）

1. **文件独占**：多张票并行时只改自己票里列的文件，越界必冲突。
2. **不许提交**：不要 `git add/commit/push`，不要跑 `deploy.sh` —— 落地与部署由主会话统一做。
3. **契约优先**：接口字段名、DOM id / class 名是冻结的。发现问题就报告，不要自行改名。
4. **禁用项必须有服务端裁决**：第 1 批的教训 —— 只在前端灰掉等于没校验。
5. **开关/效果必须有「别人视角」的下发路径**：第 1 批的教训 —— 只发给自己就是假控件。
6. **跑测试**：
   ```powershell
   New-Item -ItemType Directory -Force .tmp\pytemp | Out-Null
   $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP
   python -m pytest tests/ -q -p no:cacheprovider     # 当前基线 936 passed
   ```
7. **改 `game.js` 后 `node --check static/game.js`**；改 `style.css` 后跑 `tools/ui_layout_check.mjs`；
   改前端后跑 `node tools/dom_contract_check.mjs`（不需要浏览器，随时可跑）。
8. **新增浏览器工具时先过「工具假红清单」**（`CLAUDE.md` §11 名片改版批那一节：
   残留进程 / navigate 竞态 / 持久 profile / 与真机共用状态）。

---

## 2. 第 2 批：徽章墙 / 成就系统 + 他人主页的互动入口

### 2.1 为什么需要「每局结算收口」

成就的判据大多来自**跨局累计**，而现在的统计是散的：
`users.wins/losses/longest_streak`（现成）+ `card_usage`/`user_card_usage`（现成），
但「累计击沉」「零伤获胜」「闪电战」这类**每局事实**哪都没存。

现在对局结束写库有 **6 处** `db.record_match(...)`（`server.py` 内），各自为政。
👉 **先做一次收口**：新增 `_finalize_match(room, winner_id, loser_id)`，内部依次做
「写战绩 → 累加每局统计 → 发成就通知」，6 处调用点统一改调它。
理由：不这么做的话，以后每加一项统计都要再改 6 个地方（与「通用教训二：两份实现必然漂移」同源）。

### 2.2 数据（只加新表，不动老表 —— `db.py` 没有 ALTER 迁移机制）

```sql
-- 每局事实的累计（一次写入发生在对局结束时）
user_counters(user_id TEXT PRIMARY KEY,
              sunk_total       INTEGER DEFAULT 0,   -- 累计击沉
              matches_played   INTEGER DEFAULT 0,   -- 累计场次（含人机？不含：沿用 count_stats 口径）
              flawless_wins    INTEGER DEFAULT 0,   -- 零伤获胜次数
              fastest_win_sec  INTEGER DEFAULT 0,   -- 最快获胜用时（秒），0 = 还没有
              updated_at       INTEGER)

-- 已解锁的成就（判据可重算，这张表存「首次解锁时间」用于展示与排序）
user_achievements(user_id TEXT, badge_id TEXT, unlocked_at INTEGER,
                  PRIMARY KEY (user_id, badge_id))
```

⚠️ **口径必须复用第 1 批的两个小工具**：`_alive_ships()`（活船）与 `_own_occupied_cells()`
（己方占位 = `ships` ∪ `sunk_enemy_ships` 同理）。「击沉数」一律数**活船变死船**的那一次，
不要扫 `player.ships` 数长度（第 1 批为此专门写过一节）。
⚠️ **人机对局不计统计**（沿用现有 `count_stats=_count_stats_for(room)` 的口径）：打电脑刷不出徽章。

### 2.2.1 DAO 契约（冻结 —— A 票实现，B/C 票按此调用，不要各写一份）

```python
db.get_user_counters(uid) -> dict          # {sunk_total, matches_played, flawless_wins, fastest_win_sec, updated_at}
                                           # 无记录返回全 0 默认值，**不写库**
db.bump_user_counters(uid, **deltas) -> bool
                                           # 累加式 UPDATE（UPSERT）；只在 _finalize_match 里调
                                           # fastest_win_sec 是「取最小非零」（0/None 表示还没有）
db.get_user_achievements(uid) -> dict      # {badge_id: unlocked_at}
db.grant_user_achievements(uid, badge_ids) -> list
                                           # 只插入**新**解锁的，返回本次新增的 id 列表（用于播报）
db.get_distinct_cards_used(uid) -> int     # user_card_usage 里该用户的**不同卡名**张数
```

全部沿用第 1 批的风格：失败只记日志、返回安全默认值，绝不因为统计失败影响对局结算。

### 2.2.2 成就模块契约（冻结 —— 放在新文件 `achievements.py`，纯函数 + 常量，无 IO）

```python
BADGES = [{"id","name","desc","requirement","group"}...]   # §2.3 那 12 枚
def achievement_context(stats: dict) -> dict   # 归一化（缺字段按 0，脏数据兜住）
    # stats 的键：wins, losses, longest_streak, created_at, matches_played,
    #             sunk_total, flawless_wins, fastest_win_sec,
    #             card_uses_total, distinct_cards, rank
def evaluate(stats) -> set[str]                # 已解锁的 badge id 集合（**唯一一份判据**）
def catalog(stats, unlocked: dict) -> list     # [{id,name,desc,requirement,group,unlocked,unlocked_at}]
```

⚠️ **判据只有 `evaluate()` 一处**：接口、结算、测试全调它 —— 不允许在别处再写一遍
`stats['sunk_total'] >= 50` 这种比较（第 1 批的「两份实现必然漂移」就是这么来的）。

### 2.3 成绩单与判据（第 2 批 12 枚，先做这些）

| id | 名称 | 判据 | 数据来源 |
| --- | --- | --- | --- |
| `first_win` | 首胜 | `wins ≥ 1` | users |
| `veteran10` | 十场老兵 | `matches_played ≥ 10` | counters |
| `streak5` | 五连胜 | `longest_streak ≥ 5` | users |
| `streak10` | 十连胜 | `longest_streak ≥ 10` | users |
| `sunk50` | 五十沉 | `sunk_total ≥ 50` | counters |
| `sunk200` | 两百沉 | `sunk_total ≥ 200` | counters |
| `flawless` | 零伤获胜 | `flawless_wins ≥ 1` | counters |
| `flawless5` | 完美指挥 | `flawless_wins ≥ 5` | counters |
| `speedrun` | 闪电战 | `fastest_win_sec > 0 且 ≤ 180` | counters |
| `cardmaster` | 卡牌大师 | 个人累计出牌 ≥ 100 | user_card_usage |
| `allrounder` | 全能选手 | 用过 ≥ 20 张不同卡 | user_card_usage |
| `rank1` | 榜首 | 曾拿过排行榜第 1（`get_user_rank == 1`） | users/rank |

判据函数放**新模块 `achievements.py`**（纯函数 + 常量，无 IO），与第 1 批的
`profile_spec.py` 分工一致：`profile_spec` 管「称号/标签/外观」，`achievements` 管「徽章」。
**解锁判定只有一份实现**，接口层与结算层都调它。

### 2.4 接口

| 接口 | 变化 |
| --- | --- |
| `GET /api/profile` | 追加 `achievements`（全部徽章 + 是否解锁 + 解锁时间）与 `badge_count` |
| `GET /user_stats` | 追加 `achievements`（**只下发已解锁的**，未解锁的只给总数，避免暴露别人的进度） |
| `GET /api/achievements` | 新增：徽章图鉴（自己视角：全部 + unlocked + 判据文案） |

### 2.5 前端

- **查看面**：`#profile-view-badges` 区块（第 1 批已经在契约里留了位置）——已解锁的徽章展示，
  灰掉的未解锁位（**只在自己看自己时**显示未解锁的，看别人只显示已解锁）。
- **编辑面**：不需要新分区；徽章不是可编辑项，只在名片上展示。
- 新增 `tools/achievements_check.mjs`：判据边界（差 1 场不解锁）、解锁写库、下人视角只看已解锁、
  徽章区块渲染、无数据时不占位。

---

## 3. 第 3 批：点赞 / 送花 / 留言板

### 3.1 数据

```sql
profile_likes(from_user_id TEXT, to_user_id TEXT, kind TEXT, created_at INTEGER,
              PRIMARY KEY (from_user_id, to_user_id, kind))   -- kind: like | flower
profile_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,
                 to_user_id TEXT, from_user_id TEXT, from_name TEXT,
                 content TEXT, created_at INTEGER, deleted INTEGER DEFAULT 0)
```

### 3.2 必须一次性想清楚的四件事（否则后面补 = 返工）

1. **频率限制**：复用现有 `api.py` 的 `_rate_limited(scope)`；留言再加**每人对同一人每天上限**。
2. **长度与内容**：单条 ≤ 100 字；清控制字符；**空内容拒绝**（不是静默丢弃）。
3. **删除权限**：留言**本人**可删、**页面主人**可删（软删 `deleted = 1`，保留审计）。
4. **可见性**：留言板是否公开受主页主人的隐私开关控制（新增 `show_guestbook`，默认**公开**）。

### 3.3 接口契约（冻结）

| 接口 | 请求 | 响应 |
| --- | --- | --- |
| `POST /api/profile/like` | `{"username": 目标, "kind": "like"\|"flower", "on": true\|false}` | `{"success":true,"counts":{"like":N,"flower":M},"mine":{"like":bool,"flower":bool}}` |
| `GET /api/profile/messages` | `?username=X&limit=20&before_id=N` | `{"messages":[{"id","from_name","content","created_at","can_delete"}],"has_more":bool,"total":N,"guestbook_private":bool}` |
| `POST /api/profile/message` | `{"username": 目标, "content": "…"}` | `{"success":true,"message":{…与上面同形状…}}` |
| `POST /api/profile/message/delete` | `{"id": N}` | `{"success":true}` |

**逐条校验（服务端裁决，不靠前端灰掉）**

- 全部要求登录（401）；**目标账号不存在 → 404**（不要静默成功）。
- **不能给自己点赞 / 送花 / 留言** → 400 + 明确原因。
- `kind` 必须在白名单内；`on` 归一化为 bool。
- 留言 `content`：去控制字符与首尾空白、**≤100 字**、空内容 400；
  频率：复用 `api.py` 的 `_rate_limited('profile_message')`，另加**每人对同一人每天 ≤ 20 条**。
- 删除权限：**留言本人**或**页面主人**，其余 403；软删（`deleted = 1`），保留审计。
- `can_delete` 由**服务端**算好下发（前端只负责按它显示按钮）。

### 3.4 隐私

`user_profile` 新增 `show_guestbook`（**默认 1 = 公开**）。看别人且其为 0 时：
`messages` 返回 `[]` 且 `guestbook_private = true`（前端显示「该玩家未开放留言板」，不是留白）。
点赞 / 送花的**计数始终可见**（那是"人气"不是"内容"）。

⚠️ **写入通道（2026-09-17 实施中补的裁决）**：`show_guestbook` **并入既有的
`POST /api/profile/card`** —— 保存载荷从 8 个字段变成 **9 个**（新增 `show_guestbook`，0/1）。
理由：第 1 批定的规矩是「8 个字段必须全发、缺一个 400」，因为"允许缺字段＝保持原值"会变成
「保存了但没生效」这种最难查的静默失败；留言板隐私与那三个展示开关是同一类东西，
就该走同一条通道，不要为它单开一个接口。落地面：`profile_spec.WRITABLE_FIELDS` /
`validate_payload` / `_PROFILE_DEFAULTS` 三处都要有它，`/api/profile` 与 `/user_stats`
都要下发；前端编辑面「名片」分区加第四个开关 **`#profile-show-guestbook`**
（与另三个开关同一份，别在设置页再放一份）。既有的「8 字段」测试要跟着改成 9 个。

⚠️ **`show_guestbook` 是给「第 1 批已建的表」加列**，而本项目没有迁移机制：
`CREATE TABLE IF NOT EXISTS` **不可能**加列，必须用「`PRAGMA table_info` 判存在 →
`ALTER TABLE ... ADD COLUMN`」的幂等助手（失败只记日志）。生产库已有该表，做错这一步就是线上 500。

### 3.5 DOM 契约（冻结）

```
#profile-view 内（查看面，两个视角共用）
  .pf-actions …
    button#profile-like  + span#profile-like-count
    button#profile-flower + span#profile-flower-count
  #profile-guestbook
    textarea#guestbook-input + button#guestbook-send + span#guestbook-count（字数 N/100）
    #guestbook-list > .guestbook-item[data-id] > .guestbook-text + .guestbook-meta + button.guestbook-del[data-id]
    #guestbook-empty      （无留言占位）
    #guestbook-more       （加载更多）
    #guestbook-private    （未开放留言板时的占位）
```

- **自己看自己**：点赞/送花按钮 `disabled` 且 `title` 写「不能给自己点赞」；留言输入区隐藏。
- 只有 `can_delete === true` 的留言才渲染删除按钮。

### 3.6 不做（避免范围膨胀）

- 不做回复/楼中楼、不做 @提醒、不做图片、不做举报后台（只留 `deleted` 字段与删除接口）。

---

## 4. 第 4 批：局内快捷语 / 表情

### 4.1 需求（作者原话，务必包含）

> 「对于第四批中的局内快捷语 记得加入一句**『快点儿吧，我等的花都谢了』**」

这句话必须出现在快捷语列表里。其余条目按对局情境分组（开局 / 催prompt / 被击沉 / 反杀 / 投降前 / 结束），
每条**只发给房间里的双方 + 记进对局日志**，**不发给房间外的任何人**（不走自由聊天，避免脏词与刷屏）。

> ⚠️ **「只发给对手」的准确含义（2026-09-17 实施时消歧）**：服务端**广播给房间双方**（§4.2/§4.3 的冻结规则），
> 发送方自己也收一份 —— 前端靠 payload 里的 `player_id` 判断这条是不是自己发的，
> 据以渲染成"我发的"并各写一行日志。**要守的是"不泄露给房间外/旁观者"**，不是"不回显给自己"。
> 原句「只发给对手」容易读成"发送方收不到"，与 §4.3 冲突，已按此收敛口径。

### 4.2 设计要点

- 数据：快捷语用**常量表**（前后端各一份会漂移 → 只放后端，前端从接口拿；
  或放 `static/quick_chat.js` 单一来源 + 后端只存 id 校验白名单。**二选一，别两处各写一份文案**）。
- 事件：`quick_chat_send`（客户端 → 服务端，带 `msg_id`）；服务端校验 id 白名单 + 频率限制
  （每回合最多 N 条），再广播 `quick_chat` 给双方并写进 `room.game_logs`。
- **不能打断回合流程**：发快捷语不消耗攻击次数、不改变阶段、不打开连锁窗口。
- 频率：每人每 10 秒最多 3 条；**连点同样内容要节流**（否则变成刷屏工具）。
- 前端：对局界面加一个不挡棋盘的小按钮 + 弹层列表（复用现有 `.modal-overlay` 会挡棋盘，
  用**非模态**的浮层，别加 `modal-overlay`）。
- 工具：`tools/quick_chat_check.mjs` —— 真双客户端：A 发「快点儿吧，我等的花都谢了」，
  B 必须收到且文案一致；超过频率被拒；不消耗攻击次数；不进连锁窗口。

### 4.3 快捷语表（冻结 —— 单一来源，前后端不许各写一份文案）

**来源（2026-09-17 第 4 批开工时的裁决，与上面那句"放 server.py"不同，以此为准）**：
新建 **`quick_chat.py`** —— 纯数据 + 纯函数、无 IO，与第 2 批的 `achievements.py` 同一套路（`api.py` 要能直接 import 它，
放进 `server.py` 会让 `api.py` 反向依赖 `server.py`）。`server.py`（socket 事件）与 `api.py`（`GET /api/quick_chat`）各自 import 它，
前端**从接口拿**，`game.js` 里不写死任何一句文案 —— 两处各写一份必然漂移（本项目已吃过多次）。

| id | group | 文案 |
| --- | --- | --- |
| `hi` | 开局 | 你好，开打吧！ |
| `lets_go` | 开局 | 来，先手我拿走了 |
| **`hurry_flowers`** | **催促** | **快点儿吧，我等的花都谢了** ← 作者指定，必须有 |
| `think_fast` | 催促 | 想好了没呀？ |
| `nice_shot` | 交手 | 打得漂亮！ |
| `oops` | 交手 | 哎呀，手滑了 |
| `lucky` | 交手 | 这运气也没谁了 |
| `almost` | 交手 | 就差一点 |
| `watch_this` | 交手 | 看我这手 |
| `ouch` | 被击沉 | 我的船！ |
| `surrender_soon` | 投降前 | 我快撑不住了… |
| `gg` | 结束 | GG，打得好 |
| `rematch` | 结束 | 再来一局？ |
| `thanks` | 结束 | 多谢指教 |

**服务端规则**：事件 `quick_chat`（客户端 → 服务端，带 `room_id` / `player_id` / `msg_id`）
→ 校验 `msg_id` 在白名单内 + 身份（`_identity_ok`）+ 频率
（**每 10 秒最多 3 条**、同一 id 10 秒内不重复）→ 广播 `quick_chat` 给房间双方
（`player_id` / `name` / `msg_id` / `text` / `ts`）并写进 `room.game_logs`。
**不消耗攻击次数、不改变阶段、不打开连锁窗口**（这三条要写在注释里，并各有测试）。

> ⚠️ **"同一 id 10 秒内不重复"的实测口径（2026-09-17 实施时定死，别照字面过度承诺）**：
> 冻结的 `check_rate(recent, now, last_id, msg_id)` 只拿得到**最近一条 id**，
> 因此能拦的是**连点同一句（A→A）**，拦不住**交替重复（A→B→A）**。
> 裁决：**不改冻结签名**，因为 §4.2 的原话就是「**连点**同样内容要节流，否则变成刷屏工具」——
> 要防的是双击/连点；而"10 秒内最多 3 条"这条**独立上限**已经把交替重复的刷屏能力封死了
> （每 10 秒最多 3 句，无论怎么换）。若将来要拦任意两次同 id，需要把 `quick_chat_recent`
> 从「时间戳列表」改成「(时间戳, id) 列表」并同步改 `check_rate` 签名 —— 那是契约变更，要单独拍板。

### 4.4 前端

- 入口按钮 `#quick-chat-btn`（对局界面、阶段卡片附近），列表容器 `#quick-chat-panel`
  里每条 `button.quick-chat-item[data-msg-id]`。
- ⚠️ **不能用 `.modal-overlay`**（那是全屏遮罩会挡住棋盘）；用**非模态浮层**，
  并且要满足 `ui_layout_check.mjs` 的既有不变量（棋盘零遮挡、窄屏不压其他控件）。
- 收到 `quick_chat` 时在对局日志里显示（复用现有日志渲染），并用 `#quick-chat-toast` 轻提示。

### 4.5 工具（`tools/quick_chat_check.mjs`）

真双客户端（两个页面 / 两个 socket）：A 发 **`hurry_flowers`**，B 必须收到且文案**逐字**
等于「快点儿吧，我等的花都谢了」；越界 `msg_id` 被拒；超过频率的第 4 条被拒；
发送前后**攻击次数不变、阶段不变、`room.chain` 为空**。

---

## 7. 第 2 批实施记录（2026-09-17 落地）

**改动**：`db.py`（两表 + 5 DAO）、`server.py`（结算收口 + 4 助手 + 2 口径助手）、`achievements.py`（12 枚）、
`api.py`（3 个接口）、`static/game.js` + `static/style.css`（徽章墙）、
`tests/test_achievements.py`（47）+ `tests/test_achievements_counters.py`（40）、`tools/achievements_check.mjs`。

**实测（冻结树上重跑）**：pytest **1023 passed**；协议 e2e ✓；
`achievements_check` 35 ｜ `profile_card_check` 57 ｜ `profile_leaderboard_check` 47 ｜
`ui_layout_check` 100 ｜ `stats_modal_check` 21 ｜ `chain_preview_check` 25 ｜ `hand_play_check` 15 ｜
`last_stand_board_check` 16（浏览器工具合计 **339 项，0 FAIL**）；`dom_contract_check` ✓（限第 1/2 批契约）。

**部署**：`7948342` → 服务器 `dc33031` → 生产 PID 101068，健康检查 HTTP 200。
生产只读冒烟：两张新表与列名正确；`/user_stats` 游客视角 `badge_count {total:12, unlocked:3}`、
**只发 3 枚已解锁、无未解锁 id 泄露、无凭据泄露**；三个接口未登录 401；
生产 UI 探针 ✅ 线上账号名片渲染 `first_win/streak5/rank1` 三枚、`.locked` 计数 0、标题「已解锁 3 / 12」。

**实施中发现的四个真问题**

1. **★ 我误用了「旧代码服务端」当证据**（A 票指出）：`:5000` 上那个 python 进程是 19:45 起的，
   而 `server.py` 20:07 才改完 —— 用它跑 e2e 就算全过也**不能作为本版代码的证据**。
   👉 规矩：**改完后端必须先重启本地服务端再跑工具**；判断"服务端是不是新的"用一条新路由探针
   （本次用 `GET /api/achievements`：新代码 401、旧代码 404）。
2. **正则守卫会被注释误伤**：`test_every_record_match_call_site_passes_count_stats` 扫 `server.py` 全文
   （注释也算），A 在注释里写了带括号的调用形式 → 误报「漏传 count_stats」。
   👉 注释里别写「函数名+括号」；全角省略号同样命中。
3. **打桩接缝决定实现该放哪**：我把组装下沉进 `Database` 类后，测试（按模块级包装打桩）被绕过
   → `self.get_user_counters` 读到真库的 0 → 假红。改成**模块级函数**后正常。
4. **守卫必须点真实入口**：C 票的工具里有一条「非查看面不输出 id」是绿的，但它调的是渲染函数的
   **默认值**；而真实调用方写死了 `ids: true` —— 首页老容器其实也在输出那 12 个 id
   （实测 `{"homeIds":12,"viewIds":12}`）。已修 `fetchProfile(..., {ids})` 并补 D1/D1b 守卫。

**两个已知问题（刻意未改，属产品决策）**

- **自牺牲计入对方击沉数**：恶魔契约 / 神之宣告 / 绝处逢生 把自己船登记进 `sunken_ships`，
  于是算进**对方**的 `sunk_total`。精确区分需新增登记字段。
- **开局前投降可刷徽章**（`flawless5` 等）：`handle_surrender` 不要求对局已开始，而**改动前**
  这条路径就已经 `users.wins++`（排行榜同样可刷）。要堵应源头一次性堵（房间从未开局就不记 match），
  那会改动既有胜负口径，需作者拍板。

> 📊 **2026-09-17 生产只读审计（查清"开局前投降"这条路的真实规模，不写任何数据）**：
> `match_history` 共 **142** 局，其中**日志 0 条的 29 局、≤2 条的 32 局**（真实对局最少也是 5+ 条，109 局属于这一类）。
> 这 32 局的"胜者"分布：**小小弈11 = 21 局**、无名字的游客 7 局、弱碱性 3 局、123 1 局；
> 而 `users.wins` 里小小弈11 是 **31 胜**（14 负）—— **扣掉这 21 局只剩 10 胜**。
> 选手组合 `(游客, 小小弈11)` 出现 **17 次**，即反复"带一个游客开局即投"。
> 也就是说这不只是边角漏洞：**当前排行榜/胜场类徽章（`first_win`/`streak5`/`rank1` 等继承 `users.wins`）的名次，
> 有相当一部分不是真实对局打出来的**。要不要在源头堵（房间从未开局就不写 match、不计 wins）、
> 以及已有的 29 条空对局要不要一并清理，等作者拍板 —— 我没有动生产数据。

---

## 9. 第 3 批实施记录（2026-09-17 落地）

**改动**：`db.py`（两表 + 3 索引 + 9 DAO + 加列迁移 `_add_column_if_missing` / `_migrate_schema`）、
`api.py`（4 接口 + 隐私过滤 + 5 个助手）、`profile_spec.py`（`show_guestbook` 并入 `WRITABLE_FIELDS`，8 → 9 字段）、
`static/game.js` + `static/style.css`（查看面互动条 + 留言板 + 编辑面第 4 个展示开关）、
`tests/test_social.py`（47，新建）、`tests/test_profile_card.py`（`_payload()` 8 → 9）、
`tools/social_check.mjs`（46，新建）、`tools/profile_leaderboard_check.mjs`（假红修复，见下）。

**实测（冻结树上重跑）**

| 层 | 结果 |
| --- | --- |
| pytest | **1070 passed**（1023 基线 + 47） |
| `tools/social_check.mjs`（本批新建） | **46 PASS / 0 FAIL** |
| `profile_card_check` 57 ｜ `achievements_check` 35 ｜ `profile_leaderboard_check` 47 ｜ `stats_modal_check` 21 ｜ `chain_preview_check` 25 ｜ `hand_play_check` 15 ｜ `last_stand_board_check` 16 | 全绿 |
| `ui_layout_check`（**必须单跑**，见第 1 批的浏览器争用） | **100 PASS / 0 FAIL** |
| 协议 e2e `tools/e2e_batch_2026_09_17.py` | ✓ 全部通过 |
| `dom_contract_check --plan BATCH_2_3_4_PLAN.md` | 第 3 批 **15 个 id 全部落地**（运行期渲染）；只剩第 4 批的 `quick-chat-btn/panel/toast` |
| 浏览器工具合计 | **362 项，0 FAIL**（第 2 批后是 339） |

**部署与生产验证**：本机 `1c6169a` → 服务器与 GitHub `26e9c10` → 生产 PID **101753**，服务 active，健康检查 HTTP 200
（`deploy.sh` 在服务器归档上又跑了一遍全套 pytest：1070 passed）。

- **加列迁移在生产真库上确实生效**（本批最容易线上 500 的一步）：`PRAGMA table_info(user_profile)` 里
  `show_guestbook INTEGER DEFAULT 1`、`NULL` 老行 **0** 条；`profile_likes` / `profile_messages` 两表 + **3 个索引**都在，`deleted` 软删列在。
- 生产 HTTP 只读冒烟 **20 项全绿**：新前端已上线（`game.js` 含 `guestbook-input`/`guestbook-send`/`profile-like`/
  `profile-flower`/`guestbook-private`/`profile-show-guestbook`/`guestbook-del` 七个标记）、4 个接口未登录一律 401、
  `/user_stats` 他人视角下发 `show_guestbook=1` + `counts`/`mine`（键名恰为 `{like,flower}`）且**不下发留言内容**、无凭据泄露。
- 生产 UI 探针（游客身份**只读**，生产数据零写入）**8 项全绿**：线上名片查看面渲染出互动条（计数是服务端真数字不是 undefined）
  与留言板区块、公开的留言板显示留言区而不是「未开放」占位、零 JS 异常。

**实施中发现的三个真问题**

1. **`before_id=0` 是个"看着成功"的无效游标**：服务端语义是「取 id < before_id」，第一页传 0 →
   `total=N` 但 `messages=[]`，**永远看不到留言、刷新照样空**。修法：第一页**不带**该参数，翻页才带上一页最后一条的 id。
   👉 `tools/social_check.mjs` 按此写（第一页只用 `limit`）；别在别处传 `before_id=0`。
2. **保存路径的静默丢弃**：`save_user_profile_extra` 的 INSERT/UPSERT **漏了 `show_guestbook` 列** ——
   开关点了、界面也变了、库里没变。只有「真注册 → 真点保存 → 回头读服务端」的端到端抓得到
   （`tools/social_check.mjs` 第 32～34 项就是这条守卫）。
3. **隐私过滤只有服务端拦得住**（★ 本批最重要的验证教训）：把服务端的隐私分支关掉做红基线，
   **DOM 断言（37/38）照样全绿** —— 因为前端看到 `show_guestbook=0` 就提前 return、压根不去拉留言。
   只有以**别人的身份直接读接口**才发现内容泄露。👉 两个视角必须**各有服务端真值断言**（第 41/43 项），前端断言不能替代它。
   顺带：只断言"主人看得到 1 条"是不够的（那个版本在红基线下也是绿的），必须**两侧都断言**。

**顺带的工具修复（假红，全部出在工具自己身上）**

- `profile_leaderboard_check` 的 L3：桩里写的头像 `/static/avatars/u1_avatar.png` **仓库里根本不存在** →
  `<img>` 必 404 → 页面自带的 `onerror` 兜底把 `src` 改写成默认头像 → 断言读到的已经是兜底值。
  绿了很久纯属"断言比 404 事件先到"，第 3 批把渲染耗时拖长后就翻红。修法：桩改用**能真加载**的 1×1 data URL
  （页面那个兜底是**对的**——线上头像文件真实存在——要改的是桩）。
- 新建 `tools/social_check.mjs` 时自己踩的四个坑：① 点赞是**乐观预演**，"界面变了"≠"请求回来了"，
  请求没 settle 就点第二下会被连点保护吞掉 → 必须等**请求真的 settle**；② `/logout` 是 302 跳首页，
  "等地址变成 /logout"必然超时；③ Node 的 fetch **不跨跳转带 cookie**，注册成功的 flash 读不到 →
  改看"注册完能不能以这个身份读到自己"；④ 拿**主人**的 cookie 读 `guestbook_private` 永远是 false
  （那正是契约要求的"本人视角完整"），别人视角的真值必须用**别人的会话**读。
- 挑 CDP 页面时**必须留 `type === 'page'` 的兜底**：初始页是 `about:blank`，只认 `https?|file` 会一个都挑不到，
  报出来的却是「无法连接无头浏览器调试端口」（其实浏览器好好的）。
- ⚠️ **别用 PowerShell 的 `Get-Content -Raw | Set-Content` 改 UTF-8 源码**：本机默认按 GBK 读写，会把中文注释写成
  **非法 UTF-8**，`node --check` 报 `Invalid or unexpected token`、`read` 工具直接读不了
  （本批把 `tools/social_check.mjs` 弄坏过一次，只能整文件重写）。这与第 12 节「不要用脚本做全局字符串替换」是同一条教训。

**一个待拍板的产品决策（本批新增）**：留言接口除了契约里的「每人对同一人每天 ≤ 20 条」，还**复用了登录那套按 IP 的限流**
（60 秒内 10 次，与登录/注册**共用一个桶**）→ 同一出口 IP 下的所有人共享这 10 次/分钟，
而"每天 20 条"因此**只能分两分钟以上才可能打满**（一秒内连发会先撞 IP 限流的 429）。
反刷屏是好事，但用户感知上会先撞到 429。要么保留（倾向保留：人不会一分钟留 10 条），要么调宽/改成按账号限流 —— 需作者拍板。

---

## 10. 第 4 批实施记录（局内快捷语）

**改动**：新建 `quick_chat.py`（14 条快捷语 = 单一来源 + `check_rate` 纯函数 + `by_id`/`catalog`/`is_valid`）、
`server.py`（`quick_chat` 事件 + 房间级频率状态并在 `GameRoom.__init__` 初始化）、
`api.py`（`GET /api/quick_chat`，公开只读、不要求登录）、
`static/game.js` + `static/style.css` + `templates/index.html`（非模态浮层 + 轻提示）、
`tests/test_quick_chat.py`、`tools/quick_chat_check.mjs`。

### 10.1 开工时对冻结契约的三处消歧（都写在这里，免得后人照旧稿踩回去）

1. **快捷语表放新文件 `quick_chat.py`**，不是 §4.3 原写的「`server.py` 里的常量」——
   `api.py` 要能用它（`GET /api/quick_chat`），而 `api.py` 反向 import `server.py` 是环。
   与第 2 批的 `achievements.py` 同一套路：**纯数据 + 纯函数、无 IO、谁都能 import**。
2. **§4.1「只发给对手」与 §4.3「广播给房间双方」自相矛盾**，已按 §4.3 收敛：
   服务端**广播给房间双方**，发送方自己也收一份（前端按 payload 的 `player_id` 认出"这条是我发的"，
   只写日志不弹提示）；**真正要守的是"不泄露给房间外"** —— 工具为此专门开了**第三个不在房间里的客户端**，
   断言它一条都收不到。
3. **§4.3 的表是 14 条**（开局 2 / 催促 2 / 交手 5 / 被击沉 1 / 投降前 1 / 结束 3），不是 15 条。
   §4.1 提到的「反杀」组在 §4.3 表里**并不存在**，不补（补了就会改冻结的 `GROUPS`）。

### 10.2 实施中发现的真缺陷（三个都值得单独记）

1. **★ 同一件事有两个渲染来源 → 对局日志重复两行**。服务端同时做了两件事：
   ① 广播 `quick_chat`（前端 `handleQuickChatReceived` 写日志）；② 走既有的 `add_game_log()`
   把一条 `game_log` push 给房间（前端 `renderServerLog` 也写日志）—— 于是每发一条快捷语，
   双方日志里**各出现两遍**（一遍徽标「快捷语」、一遍「信息」）。
   **修法：广播侧不再写日志**，日志统一由 `game_log` 通道渲染（那才是写进 `room.game_logs` /
   对局历史的同一份来源），并把 `renderServerLog` 的 type 映射补上 `quick_chat → 快捷语`。
   👉 **这是集成层的缺陷：两票各自都"按契约做对了"**，错在契约让同一件事有了两条通路。
   通用规矩：**服务端已经推了一条权威记录时，前端不许再本地补一条。**
2. **工具只断言 `indexOf(...) >= 0` 是抓不到重复的**：第一版写的是"日志里有这句"，
   重复两行照样绿。已改成**数次数**（`split(文案).length - 1` 必须恰为 1），另加「日志徽标是快捷语」一条。
   👉 **"存在"与"恰好一次"是两个判据，会重复的东西不能用前者。**
3. **可见性判据认错机制 = 假绿**：同一个批次里那两个元素的隐藏机制**还不一样** ——
   面板用 `hidden` **属性**（`.quick-chat-panel[hidden]{display:none}`），
   轻提示用 **`opacity:0 + visibility:hidden` + `.is-show` 切类**。
   工具第一版读的是 `.hidden` **类** → 提示从没弹出来也会 PASS。
   现在判据统一成"**四种看不见的写法都要算进去**"：`hidden` 属性 / `display:none` /
   `visibility:hidden` / `opacity:0`（外加尺寸非 0）。
   👉 通用：**判"看得见吗"不要认某一个 class 或属性，要认计算后的样式与盒子**。
4. **★ `el.click()` 完全绕过命中测试 —— "按钮被压住、点不动"这类缺陷它一辈子测不出来**。
   本批前端实测到一次：回合标题的 `h2` 是 `display:block`、横跨整张阶段卡片（866px），
   把绝对定位的新按钮**压住 64×30** → 中心点上的事件被 `h2` 接走，**按钮看着在、点不动**。
   前端是靠人肉审 CSS 发现的（为此把那个 `h2` 收窄成 `width:auto; flex:0 0 auto`），
   而工具当时用的是 `document.querySelector(...).click()` —— 它会直接调用元素的 click 处理器，
   **根本不做命中测试**，所以这缺陷在工具里必然是绿的。
   **改法**：工具新增 `realClick()`，先 `elementFromPoint(中心)` 做命中测试、再用 CDP
   `Input.dispatchMouseEvent` 派发真实鼠标事件；并新增两条断言：
   「按钮可点（尺寸非 0）」与「**中心点上没有别的元素压着**」（`10b/10c`，发消息那条同理 `16`）。
   真实点击与合成点击的结果**不一样本身就是诊断信息**（合成能开、真实开不了 = 遮挡/命中问题；
   两者都开不了 = 处理器问题），所以保留合成点击作为兜底并把它记进判据。
   👉 与第 1 批「守卫必须点真实入口」是同一条教训的延伸：**点真实入口还不够，还要真的"点到"它**。
5. **"非模态"不能靠类名判，要靠"还能不能点到下面的东西"判**。契约的原话是「不能用 `.modal-overlay`
   （全屏遮罩会挡住棋盘）」，但只断言 `!panel.closest('.modal-overlay')` 是可以被糊弄的 ——
   自己写一个 `position:fixed; inset:0` 的遮罩就照样全屏挡着、而断言是绿的。
   所以工具在面板**开着**的时候拿棋盘中心点做一次命中测试：那一点上不能是浮层或按钮
   （`13b`）。**判"没挡住"要比判"没用某个类名"更接近契约的真实意图。**
6. **★ 浮层被卡牌预览浮窗压住 → 有条目点不动（本批抓到的真缺陷）**。工具加了"真实鼠标事件 +
   命中测试"之后立刻抓到一条**别人的探针查不到**的问题：`#quick-chat-panel` 打开后，
   `hurry_flowers` 那一条的中心点上，`elementFromPoint` 返回的是
   `DIV.stat-item < DIV.card-stats < DIV.preview-content < #magic-card-preview`，
   而且那个元素 `pointer-events:auto` / `opacity:1`（**完全可见、可接收点击**）。
   根因是位置撞车：`.magic-preview-container` 是 `position:fixed; top:80px; right:20px; width:300px`，
   与新的 `top:52px; right:6px` 按钮 / 从 y=98 起的浮层**同处右上角**，而浮层虽然写了 `z-index:60`，
   却因为不在同一个层叠上下文里而**实际被压在下面**。
   👉 教训有两层：① **同一个角落已经有人了**（预览浮窗的注释里甚至写了"右下角是聊天窗，所以固定右上角"），
   新控件落地前要先看**这个位置现在归谁**；② 这类缺陷**只有命中测试能发现** ——
   "浮层可见""条目存在""接口通了"三条全绿，玩家还是点不动。
   **修法（实测已闭合）**：前端把浮层从右上角搬到**左下角**（面板框从 `{l:1240,t:98}` 变成 `{l:6,t:444}`），
   直接避开预览浮窗那个角落，而不是去和层叠上下文较劲。复验：同一工具同一页面上
   `★ 16` 的命中结果变成 `BUTTON.quick-chat-item < .quick-chat-group-list < .quick-chat-group < #quick-chat-panel`，
   **44/44 全绿**。
7. ⚠️ **无头浏览器后台标签页拿到 0×0 布局 —— 一次假红会有两张面孔**。本工具开 3 个标签页
   （A/B/C 三个客户端），只有前台那页有正常布局；后台页的 `document.body` 是 0×0，
   于是 `getBoundingClientRect` / `elementFromPoint` 全是垃圾值。我先后看到两种"假红"：
   「浮层尺寸为 0」和「被 `#magic-card-preview` 压住」——**根因是同一个**。
   修法：**凡是读几何 / 做命中 / 派发鼠标事件之前，先 `Page.bringToFront`**（工具已封装 `front()`）。
   这与既有的记录一致：`priority_live_check.mjs` 的"倒计时不动"也是后台标签页被节流。

### 10.3 实测（冻结后回填）

- pytest：`tests/test_quick_chat.py` **81 passed**；`tests/` 全套 **1151 passed**（第 3 批基线 1070 → +81，零回归）
- **主会话的独立服务端验证**（`.tmp/verify_quick_chat_socket.py`，不依赖 G 票自己的用例、不起端口不起浏览器）：
  用 flask_socketio 的 test_client 在进程内跑真实 create_room / join_room / `emit(room=...)`，**26 项全通过**。
  其中两条正是本批缺陷的回归闸门：
  · **对局日志恰好 +1 条**（重复两行的写法会变成 +2 → 立刻红）；
  · **发送前后 `state`/`phase`/攻击次数/`chain`/待处理全部一字不变**。
  另有：房间外旁观者一条收不到（广播边界）、白名单外 msg_id 被拒且**不写日志不广播**、
  同一句连点被拦、窗口内第 4 条被拦、房间外冒充房内玩家被拒、频率**按玩家各算各的**。
- 后端红基线（已验并逐字节还原）：删白名单校验 → 3 failed（含 `TypeError: 'NoneType' object is not subscriptable`）；
  `MAX_PER_WINDOW=999` → 7 failed；两次都用 SHA256 核对了"还原后与改前同一哈希"。
  另有透明说明：还原**之后**又补了一处健壮性（`data` 非 dict 时不 AttributeError），
  因此 `server.py` 当前哈希与还原点不同，补完已重跑上面两条命令。
- `tools/quick_chat_check.mjs`：**待填** ｜ 既有浏览器工具：**待填** ｜ `ui_layout_check`：**待填**
- `dom_contract_check --plan BATCH_2_3_4_PLAN.md`：✅ **全部通过**（第 4 批那 3 个 id 从"缺失"变成"落地"，
  `index.html` 的 id 数 208 → 211）
- 协议 e2e / 静态：`node --check static/game.js` ✅ ｜ `py_compile` ✅ ｜ `--collect-only` 1151 条 ✅
- 协议级 e2e（`tools/e2e_batch_2026_09_17.py`，V1~V4 全过）：在**我自己起的 5011 端口服务端**（新代码）上跑通，
  只把脚本里那一行 URL 换成 5011，其余逐字节相同（用 `Compare-Object` 核过差异只有这一行）。
  ⚠️ 之所以另起端口：`:5000` 上那个是并行 agent 21:25 起的，而 `server.py` 21:27 才改完 ——
  拿它当证据就是"旧代码服务端"，本项目为此立过规矩。
- 浏览器工具（冻结树上重跑，服务端为我自己起的 5011 = 当前代码）：
  `ui_layout_check` **100/0** ｜ `profile_card_check` **57/0** ｜ `profile_leaderboard_check` **47/0** ｜
  `stats_modal_check` **21/0** ｜ `chain_preview_check` **25/0** ｜ `hand_play_check` **15/0** ｜
  `last_stand_board_check` **16/0** ｜ `dom_contract_check --plan BATCH_2_3_4_PLAN.md` ✅ 全过。
  合计 **330 项，0 FAIL**（第 3 批后是 362，其中第 4 批自身 49×2 视口）。
- `tools/quick_chat_check.mjs`（**49 项**，真三客户端，**两种视口各跑一遍**）：**两个视口都 0 FAIL**。
  过程中它抓到并闭合了一条真缺陷（浮层条目被卡牌预览压住、点不动，见 10.2 第 6 条）——
  修复前后是同一个页面、同一个工具，只有浮层位置变了。
- **`--size` 双视口覆盖**（本工具新增的能力）：同一套断言在 **1600×1000** 与 **390×844** 各跑一遍，
  因为浮层在两种布局里走的是**不同的 CSS 分支**（实测按钮框：宽屏 `{l:6,t:842}`（左下角 bottom 锚定）、
  手机 `{l:6,t:50}`（左上角浮标））。只测宽屏等于只测了一半。
- **多点命中测试**：不只测中心点，还测内缩 25% 的四个角 ——
  因为本项目记录过"控件被**部分**盖住（重叠 64×11）"这种缺陷，**只测中心会全绿**。
  `10d`（按钮五点）、`16a`（条目五点），两个视口下都是 `covered: 0`。
- **多控件遮挡扫描 `13c`**：面板开着时逐一扫日志 / 手牌 / 阶段按钮 / 两块棋盘的中点。
  ⚠️ 窄屏**允许**压棋盘（棋盘铺满屏幕，压不住不可能，那是"下拉菜单"而不是"全屏遮罩"），
  但这个放宽**有交换条件**：`16b`（选完自动收）+ `16c`（点界面别处能关）+ `16d`（Esc 能关）三条必须同时绿 ——
  否则"不会被困在菜单里"这句就只是说辞。
- ⚠️ **工具公平性**：`16c` 第一版拿**视口最右下角**当"浮层外面"，在宽屏上假红了一次
  （那个点多半已经不在 app 容器里，语义与"玩家点界面别处"不同）；
  改成在 game-screen 里挑第一个**确实落在浮层之外**的点之后，两个视口都绿。
  **判"点外面"要先确认那个点真的是"界面别处"。**
- 部署与生产冒烟：本机 `310dab0` → 服务器与 GitHub **`99db6f6`**（tree 相等已核），生产 PID **102252**，
  服务 active，健康检查 HTTP 200。
  · **生产 HTTP 冒烟 17/17 全绿**（部署前同一脚本是 **14 FAIL** —— 红→绿的翻转是同一脚本同一断言给出的）：
    `/api/quick_chat` 200 且 14 条、**作者点名那句逐字一致**、前端三个 id + 样式已上线、
    且 `game.js` 里**没有**硬编码那句文案（单一来源在生产上也成立）。
  · ⚠️ `tools/quick_chat_check.mjs` **不适合直接指向生产**：它读服务端真值要用 `test_get_game_state`，
    而生产**正确地**只把调试事件发给白名单账号 —— 游客拿到 `error`，于是它一上来就红一片。
    **那是门禁在正常工作**，不是缺陷；本批的生产 UI 验证因此另写了一个只用"真游客能做的事"的探针
    （`.tmp/prod_probe_b4.mjs`，一次性、不进仓库）。
  · 那个探针跑到一半停下，原因是**产品事实**而非缺陷：**快捷语按钮只在进入战斗阶段后才有尺寸**
    （摆船阶段它所在的那块容器还没显示，实测 `width=0`）。所以「开局」组的两句
    （你好，开打吧！/ 来，先手我拿走了）在摆船阶段**发不出去** —— 这是本轮实测发现的
    **产品观察**，要不要让按钮在摆船阶段也可用，属作者决策（我没有擅自改）。
  · 生产上驱动 `rps_choice` 会让页面重载、CDP 会话作废（`Inspected target navigated or closed`），
    这个探针没继续往下拧 —— 但**本批的 UI 断言在本地已用同一套工具覆盖到 49 项 × 两种视口**，
    生产侧则以 HTTP 冒烟为准。

---

## 8. 三批的执行顺序与依赖

```
第 2 批：A 每局结算收口 + counters 表 ──► B achievements.py + 接口 ──► C 前端徽章区块 + 工具
        ✅ 已完成并上线（`dc33031`，记录见第 7 节）
第 3 批：D 点赞/送花/留言板后端 + 加列迁移 ──► E 前端互动条 + 留言板 ──► 工具与收口
        ✅ 已完成并上线（`26e9c10`，记录见第 9 节）
第 4 批：G 快捷语常量表 + 服务端事件 ──► H 前端浮层 + 工具
        🔄 实施中（记录见第 10 节）
```

**依赖**：第 3、4 批与第 2 批互不依赖，**但它们都要改 `db.py` / `api.py` / `game.js` / `style.css`
这几个同一批文件 —— 所以必须一批做完再做下一批**（同一文件并行 = 必然冲突）。
每批都要跑第 1 批与既有的全部回归工具。

## 6. 环境提醒

- 本机 `:5000` 上可能残留**上一轮的 python 服务端**（`job_kill` 只杀 pwsh 作业、**不杀 python 子进程**）。
  用之前先确认它是不是你要的那个（`.tmp/server.log` 里会写实际使用的库路径），
  否则会出现「我明明起了新服务端，页面却是旧代码」这种查半天的问题。
- 跑 pytest 前先 `New-Item -ItemType Directory -Force .tmp\pytemp`（`.tmp` 被清理过就会 97 个 error，与代码无关）。
