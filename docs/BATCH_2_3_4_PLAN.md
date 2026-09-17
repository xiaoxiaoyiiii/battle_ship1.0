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
每条**只发给对手 + 记进对局日志**，不走自由聊天（避免脏词与刷屏）。

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

**来源**：`server.py` 里的常量 `QUICK_CHAT = [{"id","group","text"}...]`，前端**从接口拿**
（`GET /api/quick_chat`），前端不写死任何文案 —— 两处各写一份必然漂移（本项目已吃过多次）。

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

---

## 8. 三批的执行顺序与依赖

```
第 2 批：A 每局结算收口 + counters 表 ──► B achievements.py + 接口 ──► C 前端徽章区块 + 工具
第 3 批：D 点赞/送花 + E 留言板（可并行）──► F 前端互动条 + 工具
第 4 批：G 快捷语常量表 + 服务端事件 ──► H 前端浮层 + 工具
```

**依赖**：第 3、4 批与第 2 批互不依赖，**但它们都要改 `db.py` / `api.py` / `game.js` / `style.css`
这几个同一批文件 —— 所以必须一批做完再做下一批**（同一文件并行 = 必然冲突）。
每批都要跑第 1 批与既有的全部回归工具。

## 6. 环境提醒

- 本机 `:5000` 上可能残留**上一轮的 python 服务端**（`job_kill` 只杀 pwsh 作业、**不杀 python 子进程**）。
  用之前先确认它是不是你要的那个（`.tmp/server.log` 里会写实际使用的库路径），
  否则会出现「我明明起了新服务端，页面却是旧代码」这种查半天的问题。
- 跑 pytest 前先 `New-Item -ItemType Directory -Force .tmp\pytemp`（`.tmp` 被清理过就会 97 个 error，与代码无关）。
