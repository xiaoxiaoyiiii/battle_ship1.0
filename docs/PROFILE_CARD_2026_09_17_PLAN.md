# 个人信息名片 / 界面设置改版 —— 第 1 批实现计划（票 + 依赖图）

> 依据：`docs/PROFILE_CARD_2026_09_17.md`（设计稿）。本文件只写**怎么做、谁负责哪个文件、怎么算做完**。
> 需求与取舍理由一律看设计稿，不要在这里重复。

## 0. 硬规矩（每个执行者都必须遵守）

1. **文件独占**：只改自己票里列出的文件。多张票并行时，越界改别人的文件必然冲突。
2. **不许提交**：不要 `git add/commit/push`，不要跑 `deploy.sh`。落地与部署由主会话统一做。
3. **契约优先**：§2 的接口字段名、§3 的 DOM id / class 名是**冻结契约**。发现契约有问题就报告，不要自行改名。
4. **跑测试**（Windows 本机临时目录 ACL 已损坏，必须重定向）：
   ```powershell
   $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP
   python -m pytest tests/ -q          # 当前基线 864 passed
   ```
5. **改 `game.js` 后必须 `node --check static/game.js`**；改 `style.css` 后必须跑
   `node tools/ui_layout_check.mjs --url http://127.0.0.1:5000/`（需要本地服务端，见 §5）。
6. **行号会漂移**，一律用 grep 定位（`CLAUDE.md` 第 1 节）。

## 1. 票与依赖图

```
T1 后端（表 + 解锁规则 + 接口 + 测试）      ─┐
T2 前端结构（index.html + style.css）       ─┼─► T4 无头工具（profile_card_check.mjs）─► T5 主会话集成/部署
T3 前端接线（game.js）                       ─┘
```

- T1 / T2 / T3 **可并行**：三者文件互不重叠，且契约在 §2 §3 已冻结。
- T3 依赖 T2 的 id，但 id 已冻结 → 允许并行，落地后由 T5 做机械化对账（§4）。
- T4 依赖 T1+T2+T3 全部落地（要真页面 + 真接口）。

| 票 | 负责文件（独占） | 完成判据 |
| --- | --- | --- |
| T1 | `db.py`、`api.py`、`server.py`（仅 `record_card_use` + 其调用点）、`profile_spec.py`(新)、`tests/test_profile_card.py`(新) | 新增用例全绿 + 全量 `pytest` 不回退（≥864 通过） |
| T2 | `templates/index.html`、`static/style.css` | §3 的 id 全部存在；`ui_layout_check.mjs` 仍全绿 |
| T3 | `static/game.js`、`tools/profile_leaderboard_check.mjs`（该表面的既有守卫工具，必要时同步更新断言） | `node --check` 通过；双态切换/保存/主题预设可用；`profile_leaderboard_check.mjs` 全绿 |
| T4 | `tools/profile_card_check.mjs`(新) | 工具自检全绿，且能 FAIL 在故意改坏时（见 §4） |
| T5 | 主会话：集成对账、文档回填、提交推送部署 | 全量回归 + 生产冒烟 |

## 2. 接口契约（冻结）

### 2.1 `profile_spec.py`（新模块，纯函数 + 常量，无 IO）

```python
TITLES   = [{"id","name","desc"}...]          # 7 项，见设计稿 §5.1
TAGS     = [{"id","name"}...]                 # 12 项，见设计稿 §5.2；id 用拼音短名
FRAMES   = [{"id","name","desc"}...]          # 5 项，见设计稿 §5.3
CARD_BGS = [{"id","name","desc"}...]          # 6 项，见设计稿 §5.4

def unlock_context(stats: dict) -> dict        # 归一化 wins/losses/longest_streak/created_at/card_uses_total
def unlocked_titles(stats) -> set[str]
def unlocked_frames(stats) -> set[str]
def unlocked_card_bgs(stats) -> set[str]
def catalog(stats) -> dict                     # 直接给接口用，见 2.4
def validate_payload(payload: dict, stats: dict) -> tuple[dict, list[str]]
    # 返回 (已归一化的可写入字段, 错误列表)。错误非空 = 拒绝整次保存。
```

`TAGS` 的 id 与 name 一律为：
`aggressive/激进`、`steady/稳健`、`fast/速攻`、`turtle/蹲坑`、`cardflow/卡牌流`、`chain/连锁控`、
`rookie/萌新`、`pro/大佬`、`nightowl/夜猫子`、`needmate/求带`、`serious/不苟言笑`、`chatty/爱聊`

### 2.2 数据表（`db.py init_db()` 内追加，`CREATE TABLE IF NOT EXISTS`）

```sql
user_profile(user_id TEXT PRIMARY KEY, title_id TEXT DEFAULT '', tags TEXT DEFAULT '[]',
             status_text TEXT DEFAULT '', frame_id TEXT DEFAULT 'none', card_bg_id TEXT DEFAULT 'deep',
             show_stats INTEGER DEFAULT 1, show_fav_cards INTEGER DEFAULT 1, show_history INTEGER DEFAULT 0,
             updated_at INTEGER)
user_card_usage(user_id TEXT, card_name TEXT, uses INTEGER NOT NULL DEFAULT 0, updated_at INTEGER,
                PRIMARY KEY (user_id, card_name))
```

新增 DAO（全部沿用现有「失败只记日志、返回安全默认值」风格）：

```python
get_user_profile_extra(uid) -> dict          # 不存在时返回默认值（不写库）
save_user_profile_extra(uid, fields) -> bool # UPSERT
record_user_card_use(uid, card_name, count=1) -> bool
get_user_card_usage(uid, limit=3) -> list[dict]   # [{"name","uses"}] 按 uses DESC
get_user_card_uses_total(uid) -> int
```

**`server.py:98 record_card_use`** 增加可选参数 `user_id=None`，同时写全局表与个人表；
调用点 `server.py:3370` 传入施法者的 `user_id`（注意：`room.players` 的 key 与 `Player.user_id`
是两套约定，**必须取 `Player.user_id`**，取不到（游客）就只写全局表）。

### 2.3 `GET /api/profile`（登录）—— 在现有 `profile` 对象上追加

```json
{ "profile": {
    ...现有字段(id/username/signature/avatar/wins/losses/current_streak/longest_streak/created_at) 保留...,
    "rank": 3,
    "title_id": "hunter", "tags": ["aggressive"], "status_text": "找队友",
    "frame_id": "gold", "card_bg_id": "cyber",
    "show_stats": 1, "show_fav_cards": 1, "show_history": 0,
    "fav_cards": [{"name":"失灵！","speed":3,"uses":41}],
    "catalog": { "titles":[{"id","name","desc","unlocked","requirement"}],
                 "tags":[{"id","name"}],
                 "frames":[...同 titles 形状...],
                 "card_bgs":[...] } } }
```

`fav_cards` 中 `speed` 取自全局 `magic_cards`（卡表按 name 查；查不到给 0，不要报错）。

### 2.4 `POST /api/profile/card`（登录，JSON body）

请求：`{"title_id","tags":["aggressive"],"status_text","frame_id","card_bg_id","show_stats","show_fav_cards","show_history"}`

⚠️ **8 个字段必须全部出现**（T1 实现时补充进契约）：缺任何一个 → 400 并点名。
理由：允许缺字段就等于"保持原值"，那会变成「保存了但没生效」这种最难查的静默失败。
`title_id` 允许空串（= 不展示称号）；`tags` 是**id 数组**而不是中文名。

- 成功：`200 {"success": true, "profile": {与 GET 的 profile 同形状}}`
- 失败：`400 {"success": false, "error": "未解锁的称号：不败神话"}`（**拒绝整次保存**，不做部分写入）
- 未登录：`401 {"success": false, "error": "未登录"}`

校验规则（设计稿 §4）：`title_id` 必须已解锁；`tags` 去重、≤3、必须全在池内；
`status_text` ≤30 字（超出截断、清掉控制字符）；`frame_id`/`card_bg_id` 必须已解锁；
`show_*` 归一化为 0/1。**未解锁项一律拒绝并说明原因，不静默降级。**

### 2.5 `GET /user_stats?username=X` —— 追加与隐私过滤

追加到 `stats`（继续走 `api.py:177` 那份字段白名单思路，**不许 `SELECT *` 整行下发**）：

```
title_id, title_name, tags, status_text, frame_id, card_bg_id, fav_cards,
show_history, show_stats, show_fav_cards
```

⚠️ **`show_stats` / `show_fav_cards` 必须一起下发**（2026-09-17 由 T1 提出后裁决补上）：
第一版契约只写了 `show_history`，结果前端在「看别人」这条路径上读到 `undefined` → 按默认值
当成「显示」→ **玩家关掉「显示战绩亮点 / 最爱用的卡」之后，别人照样看得到**，开关变成假控件，
正是本项目最忌讳的「看着能用其实没用」。

**统一规则（一套语义，自己与别人一致）**：`show_X == 0` 时该区块**对所有人隐藏**（自己也不显示），
`show_X == 1` 时对所有人可见。三个开关只管「名片上显示什么」，不区分视角 ——
两套语义（自己一套、别人一套）必然漂移。

隐私：`show_history == 0` 且**请求者不是本人**时，`history` 返回 `[]`；
本人（`session['user_id'] == stats['id']`）永远返回完整历史。

> `title / tags / status / frame / card_bg` 属于「这个人是谁」，不受任何开关控制，始终可见
> （设计稿 §7）；只有上面三个 `show_*` 控制的区块会隐藏。

## 3. DOM 契约（冻结）—— `templates/index.html`

### 3.0 铁律

**现有 id 一个都不许删**：`game.js` 里已有绑定，删了就静默失效。落地后 T5 会做机械化对账（§4）。
尤其保留：`#profile-form`、`#profile-avatar`、`#profile-username`、`#profile-signature`、
`#profile-save-msg`、`#avatar-input`、`#profile-modal-close`、`#settings-modal-close`、
`#primary-color-picker`、`#music-volume`、`#volume-display`、`#music-loop-mode`、`#music-toggle-play`、
`#music-next`、`#music-previous`、`#music-muted`、`#sfx-muted`、`#current-track`、
`#wp-section`、`#wp-now-playing`、`#wp-opacity`、`#wp-opacity-display`、`#wp-dim`、`#wp-dim-display`、
`#wp-blur`、`#wp-blur-display`、`#wp-fit`、`#wp-scan`、`#wp-toggle-play`、`#wp-clear`、`#wp-list`、
`#wp-path`、`#wp-path-import`、`#wp-url`、`#wp-url-import`、`#wp-status`、`#settings-save-btn`、
`#change-password-form`、`#old-password`、`#new-password`、`#change-password-msg`。

### 3.1 查看面 / 编辑面 —— ⚠️ 架构澄清（2026-09-17 实测代码后修正）

**现状（grep 实测）有两块面，不是一块**：

| 面 | 元素 | 打开入口 |
| --- | --- | --- |
| **查看面** | `#opponent-stats-modal` + `#opponent-stats-title` + `#opponent-stats-content`（index.html:610） | `showUserProfile(username)`：排行榜名字/头像、局内左上自己头像、局内右上对手头像、`#show-opponent-stats` 按钮 —— **四个入口共用** |
| **编辑面** | `#profile-modal`（index.html:420） | 页头 `#show-profile`（index.html:41）「个人信息」链接 |

👉 所以设计稿说的「查看态 / 编辑态两态」**就是这两个已有的面**，不要另外造：
**查看态 = 渲染进 `#opponent-stats-content` 的分层名片（自己与别人共用同一份渲染）；
编辑态 = `#profile-modal`（重排成左导航 + 分区表单）**。
把自己的查看态塞进 `#profile-modal` 会迫使四个入口改道、并丢掉下面的历史列表。

⚠️ **查看面必须保留这些（上一批作者明确要求过，旧工具 `profile_leaderboard_check.mjs` 的 P9/P10 在守）**：
- **对局历史列表**：`.match-history-btn` 行 + 「加载更多」+ 点击开 `#match-detail-modal`
- **隐私占位**：`show_history == 0` 且看的不是本人时，历史区显示「该玩家未公开对局历史」而不是留白
- 头像、用户名、个性签名、排行榜名次、胜率、胜场/负场 —— 信息一个都不能少（**标记结构可以换**）

```
#opponent-stats-modal.modal-overlay               ← 现有 id，保留
  .modal-content … + span.modal-close#opponent-stats-modal-close
  h2#opponent-stats-title                          ← 现有 id，保留
  #opponent-stats-content                          ← 现有 id，保留；内容由 buildProfileCard 渲染
    #profile-view.pf-card
      .pf-cover
      .pf-hero
        .pf-avatar-wrap > img#profile-view-avatar.pf-avatar + span#profile-view-level.lvl
        .pf-who > h3#profile-view-name + span#profile-view-title.title-chip
                  p#profile-view-status.state
                  .pf-tags#profile-view-tags              （内含 span.tag）
        .pf-actions > button#profile-edit-btn             （**仅自己**；看别人时不渲染）
      .pf-stats#profile-view-stats
        .stat[data-stat="streak"]  > b + span             （最高连胜）
        .stat[data-stat="rate"]    > b + span             （胜率）
        .stat[data-stat="matches"] > b + span             （总场次）
      .pf-block#profile-view-favcards                     （内含 .fav；空数据时整块 hidden）
      .pf-block#profile-view-history
        #profile-history-list                             （`.match-history-btn` 行，类名不改）
        #profile-history-more                             （加载更多）
        #profile-history-empty                            （空 / 未公开时的占位文案）
      .pf-meta#profile-view-meta
```

```
#profile-modal.modal-overlay                       ← 现有 id，保留（= 编辑态）
  .modal-content.profile-modal-card
    span.modal-close#profile-modal-close           ← 现有 id，保留
    #profile-edit.pf-editor
      .pf-editor-nav > .pf-editor-nav-item[data-pane="card|avatar|title|account"]
      .pf-editor-panes
        .pf-pane[data-pane="card"]
          input#profile-edit-status                   （maxlength=30）
          #profile-bg-row > button.pf-bg[data-bg="deep|graphite|cyber|lava|dusk|aurora"]
          .pf-toggles > label>input#profile-show-stats
                        label>input#profile-show-favcards
                        label>input#profile-show-history
        .pf-pane[data-pane="avatar"]
          img#profile-avatar.pf-avatar-edit           （现有 id，保留）
          .pf-drop > input#avatar-input               （现有 id，保留）
          #profile-frame-row > button.pf-frame[data-frame="none|silver|gold|aurora|crimson"]
        .pf-pane[data-pane="title"]
          #profile-title-list > button.pf-opt[data-title="<id>"]   （未解锁：disabled + title 写解锁条件）
          #profile-tag-list   > button.pf-opt[data-tag="<id>"]
          span#profile-tag-count                      （文案「已选 2 / 3」）
        .pf-pane[data-pane="account"]
          form#profile-form                            （现有 id，保留）
            span#profile-username                      （现有 id，保留）
            input#profile-signature                    （现有 id，保留）
          button#profile-goto-account                  （打开设置 → 账号与隐私；改密码表单在那里）
    .pf-edit-foot > button#profile-card-save + button#profile-edit-cancel + div#profile-save-msg
```

**不做分享按钮**：本批没有分享个人主页的功能，不做只能点着没反应的装饰按钮（第一版契约里的那个「分享」按钮已删除）。

### 3.2 界面设置弹窗

```
#settings-modal.modal-overlay
  .modal-content.settings-modal-card
    span.modal-close#settings-modal-close
    .settings-wrap
      nav.settings-nav > button.settings-nav-item[data-pane="look|sound|wp|acct"]
      .settings-panes
        section.settings-pane[data-pane="look"]
          #theme-preset-grid > button.theme-card[data-preset="deep|lava|cyber|dusk|aurora|classic"]
          input#primary-color-picker                    （现有 id，保留）
          #theme-preset-hint                            （自定义主色时提示「已改为自定义」）
        section.settings-pane[data-pane="sound"]        （现有音量/循环/按钮/静音控件全部搬进来，id 不变）
        section.settings-pane[data-pane="wp"]           （整个 `#wp-section` 连同 id 搬进来，内部结构不变）
        section.settings-pane[data-pane="acct"]
          form#change-password-form + #old-password + #new-password + #change-password-msg
          button#settings-goto-profile                  （切到个人信息编辑态）
    button#settings-save-btn                            （现有 id，保留）
```

**去重**：`show_history` 等三个展示开关**只放在个人信息编辑态**，设置页不再放一份
（同一个设置两份控件 = 两份实现，必然漂移）。改密码表单**只放在设置的账号与隐私**，
个人信息编辑态用 `#profile-goto-account` 指过去。

## 4. 验证

### 4.1 T5 的机械化对账（防"契约漂移"）

```powershell
# ① 计划里出现的每个 id，index.html 里都必须存在
# ② game.js 里新增代码引用的每个 #id，index.html 里都必须存在
node .tmp/design_preview/contract_check.mjs      （T5 编写；比对 §3 的 id 清单与两个文件）
```

### 4.2 新增 pytest（`tests/test_profile_card.py`，T1）

1. 未解锁称号 → `POST /api/profile/card` 返回 400 且**库里没被改**
2. 标签 4 个 → 只存 3 个；池外标签 → 400
3. `status_text` 31 字 → 截断到 30；含 `\x00` → 清掉且不报错
4. 未解锁 `frame_id` / `card_bg_id` → 400
5. `show_history=0` 时**他人** `/user_stats` → `history == []`；**本人** → 完整历史
6. `/user_stats` 不下发 `password_hash` / `token`
7. `unlocked_*` 边界：差 1 场不解锁
8. `user_card_usage` 累加 + Top3 排序 + `get_user_card_uses_total`
9. `CREATE TABLE IF NOT EXISTS` 在已有库上重复执行不报错（老库兼容）
10. 未登录访问 `/api/profile/card` → 401

### 4.3 新增无头工具（`tools/profile_card_check.mjs`，T4）

- 查看态默认可见（`#profile-view` 不含 `hidden`、`#profile-edit` 含 `hidden`）
- 点 `#profile-edit-btn` → 编辑态出现；点 `#profile-edit-cancel` → 回到查看态且**未保存的改动被丢弃**
- 关掉 `#profile-show-favcards` 保存后 `#profile-view-favcards` 消失；重开又回来
- 改 `#profile-edit-status` 保存后 `#profile-view-status` 文案同步变化
- 点 `#theme-preset-grid .theme-card[data-preset="lava"]` 后
  `getComputedStyle(document.documentElement).getPropertyValue('--primary')` 真的变了，
  且刷新后仍生效（localStorage）
- 设置页四个 `data-pane` 每次只有一个 `.settings-pane` 可见
- 未解锁的 `button.pf-opt[data-title]` / `.pf-frame` 是 `disabled`，且 `title` 里有解锁条件
- 窄屏 390×844 / 336×664 无横向溢出（`scrollWidth <= innerWidth + 1`）
- **反向自检**：故意把 `#profile-view-favcards` 加 `hidden` 再断言"应该 FAIL"，
  确认工具真的能红（否则就是假绿）

### 4.4 必须继续通过的既有回归

`python -m pytest tests/ -q`（≥864 通过）、
`tools/profile_leaderboard_check.mjs`、`tools/ui_layout_check.mjs`、`tools/stats_modal_check.mjs`、
`tools/chain_preview_check.mjs`、`tools/last_stand_board_check.mjs`、`tools/e2e_batch_2026_09_17.py`。

## 5. 本地怎么起服务端跑工具

```powershell
$env:PORT='5000'; $env:CORS_ORIGINS='http://127.0.0.1:5000'
$env:BATTLESHIP_DB_PATH="$PWD\.tmp\toolcheck.db"; $env:ENABLE_TEST_EVENTS='1'; $env:TURN_TIMEOUT_SECONDS='0'
python server.py      # 隔离库，别用生产库
```
无头工具一律 `--url http://127.0.0.1:5000/`。

## 6. 不做什么（本批）

设计稿 §11.1 那一份，原样执行：徽章墙、他人主页、点赞/留言、局内快捷语、累计击沉、
自由输入称号/标签 —— **全部不做**。用户主页在编辑态之外不出现「别人的」入口（本批只做自己看自己）。
