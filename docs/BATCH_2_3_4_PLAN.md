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

### 3.3 接口

`POST /api/profile/like`（kind=like|flower，可取消）、`GET/POST /api/profile/messages`、
`POST /api/profile/message/delete`。全部要求登录；**自己不能给自己点赞/送花**。

### 3.4 前端

查看面底部互动条（第 1 批 mockup 里已有位置）：`#profile-actions-like` / `-flower` / 留言区
`#profile-guestbook`。留言板分页 + 删除按钮（按权限显示）。

### 3.5 不做（避免范围膨胀）

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

---

## 5. 三批的执行顺序与依赖

```
第 2 批：A 每局结算收口 + counters 表 ──► B achievements.py + 接口 ──► C 前端徽章区块 + 工具
第 3 批：D 点赞/送花 + E 留言板（可并行）──► F 前端互动条 + 工具
第 4 批：G 快捷语常量表 + 服务端事件 ──► H 前端浮层 + 工具
```

**依赖**：第 3 批不依赖第 2 批；第 4 批独立。**但每批都要跑第 1 批与既有的全部回归工具**。
