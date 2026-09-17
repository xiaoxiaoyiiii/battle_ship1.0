# 个人信息名片与界面设置改版（第 1 批）设计稿

> 2026-09-17。作者原话：「希望调整一下个人信息和界面设置的所有 ui，原先的 ui 太过混乱也太难看了」
> 「加入一些别的可被用户个性化编辑然后显示在个人信息里的东西」。
> 本稿是**实施前的设计**，第 1 批落地后请把实测结果与踩到的坑回填到本文档末尾的「实施记录」。

---

## 1. 目标

| 目标 | 判据 |
| --- | --- |
| 个人信息弹窗不再「一打开就是一堆输入框」 | 打开即干净名片，表单收进「编辑」态 |
| 界面设置不再是一条长滚动列 | 左侧分类导航，单分类内可见全部内容 |
| 新增可自定义、且能被别人看到的内容 | 称号 / 标签 / 一句话状态 / 头像框 / 名片底色 / 展示开关 |
| 观感统一到现有深色视觉体系 | 只用现有 CSS 变量，不引入新的盒模型尺寸 |

## 2. 已确认的决策（作者逐项勾选，2026-09-17）

| 决策点 | 结论 |
| --- | --- |
| 排版方案 | **A 分层名片**（大封面 + 头像压边、三块大数字、徽章 58px） |
| 默认主题 | **深海（冷蓝）**；其余 4 套（熔岩 / 赛博 / 暮光 / 极光）+ 经典 仍可切换 |
| 承载形态 | 仍用弹窗，拆 **查看态 / 编辑态** 两态 |
| 设置页 | **左侧分类导航 + 右侧内容**（外观与主题 / 音效与音乐 / 动态壁纸 / 账号与隐私） |
| 称号规则 | **只能从预设池选，按战绩解锁**（不允许自由输入 → 无脏词与冒充风险，不需要审核流程） |
| 名片外观 | **一部分免费 + 一部分按解锁** |
| 隐私默认 | **对局历史默认不公开**；头像与战绩默认可见 |
| 分批 | 同意四批，本轮只做第 1 批 |

### 2.1 四批划分

| 批次 | 内容 | 为什么这么排 |
| --- | --- | --- |
| **第 1 批（本稿）** | 个人信息双态 + 设置左导航 + 主题预设 + 称号/标签/状态/边框/底色/展示开关/最爱用的卡/战绩亮点/加入时间 | 后端只加表与读接口，**不动对局结算链路** |
| 第 2 批 | 徽章墙 / 成就系统 + 他人的个人主页 | 需要「每局结算统计钩子」，是独立模块 |
| 第 3 批 | 他人主页互动：点赞 / 送花 / 留言板 | 独立社交层：新表、防刷、举报与审核、通知 |
| 第 4 批 | 对局内快捷语 / 表情 | 要动对局聊天链路，风险最高 |

## 3. 现状实测（设计依据，均以代码为准）

| 事实 | 位置 / 证据 | 对设计的影响 |
| --- | --- | --- |
| `db.py` **没有任何 ALTER / 迁移机制**，只有 `CREATE TABLE IF NOT EXISTS` | `db.py:60 init_db()` | 生产库加字段必须走**新表**，不能改 `users` 表结构 |
| `card_usage` 是**全局表**，主键就是 `card_name` | `db.py:124` | 「最爱用的卡」必须新建**按用户**的表 |
| 主题 / 主色 / 音量全部存 **localStorage** | `battleship_primary_color`、`bgm_volume`、`bgm_loop_mode`、`bgm_muted` | 主题预设沿用 localStorage，**不进后端** |
| 现有名片渲染是 `buildProfileHead`（`:1621`）+ `buildStatsTable`（`:1637`） | 入口 `showUserProfile`（`:1737`） | 取代它们，并**反查是否还有第二套渲染** |
| 排行榜、局内头像、`#show-opponent-stats` **三个入口共用** `showUserProfile` | `game.js` | 改坏即三处同坏 → 旧工具必须保持绿 |
| 数据库**没有「累计击沉」**，只有 `wins / losses / longest_streak / created_at` | `db.py:64 users` | 第 1 批的三块大数字只能用现成字段（见 §5） |
| `record_card_use` 只有一个调用点 | `server.py:98` 定义，`:3370` 调用 | 加 `user_id` 参数成本低 |
| 对局结束写库有 **6 处** `db.record_match(...)` | `server.py:2018 / 2153 / 4495 / 5887 / 7709 / 7749` | 每局统计钩子要挂 6 处 → 推迟到第 2 批 |
| `/user_stats` 已经做了字段白名单，不下发 `password_hash` / `token` | `api.py:177` | 新增字段继续走这份白名单，不透传整行 |

## 4. 数据模型

两张新表，`CREATE TABLE IF NOT EXISTS`，老库启动即自动补齐，**不需要迁移脚本、不需要停机**。

```sql
CREATE TABLE IF NOT EXISTS user_profile (
    user_id       TEXT PRIMARY KEY,
    title_id      TEXT    DEFAULT '',     -- 称号 id，空 = 不展示
    tags          TEXT    DEFAULT '[]',   -- JSON 数组，最多 3 个，元素来自预设池
    status_text   TEXT    DEFAULT '',     -- 一句话状态，≤30 字
    frame_id      TEXT    DEFAULT 'none', -- 头像框 id
    card_bg_id    TEXT    DEFAULT 'deep', -- 名片底色 id
    show_stats    INTEGER DEFAULT 1,
    show_fav_cards INTEGER DEFAULT 1,
    show_history  INTEGER DEFAULT 0,      -- 隐私：默认不公开对局历史
    updated_at    INTEGER
);

CREATE TABLE IF NOT EXISTS user_card_usage (
    user_id    TEXT,
    card_name  TEXT,
    uses       INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER,
    PRIMARY KEY (user_id, card_name)
);
```

**为什么只存 id、不存自由文本**：`frame_id` / `card_bg_id` / `tags` / `title_id` 全部是**白名单 id**，
展示时由前端映射到内置样式。这样用户既注入不了 CSS，也不可能伪造称号文字，且不需要任何审核流程。

字段校验一律在**服务端**（见 §6）：

| 字段 | 规则 | 违规处理 |
| --- | --- | --- |
| `title_id` | 必须在预设池内，且调用者**确实已解锁** | 拒绝并返回原因（不是静默截断） |
| `tags` | 数组、去重、≤3 个、元素必须在标签池内 | 超出的丢掉，非法元素拒绝 |
| `status_text` | ≤30 字，去掉首尾空白与控制字符 | 超出截断 |
| `frame_id` / `card_bg_id` | 白名单内，且已解锁（免费项不限） | 拒绝 |
| `show_*` | 0 / 1 | 归一化 |

## 5. 称号、外观与解锁规则

新建 `profile_spec.py`（纯函数 + 常量，无 IO），前后端共享同一份池子定义来源：

```python
unlocked_titles(stats) -> set[str]      # stats: wins/losses/longest_streak/created_at/card_uses_total
unlocked_frames(stats) -> set[str]
unlocked_card_bgs(stats) -> set[str]
```

### 5.1 称号池（7）

| id | 名称 | 解锁条件 |
| --- | --- | --- |
| `rookie` | 新兵 | 无门槛（默认展示） |
| `sailor` | 老水手 | 总场次（wins+losses）≥ 20 |
| `hunter` | 深海猎手 | 胜场 ≥ 30 |
| `streak10` | 十连胜 | 最高连胜 ≥ 10 |
| `immortal` | 不败神话 | 最高连胜 ≥ 15 |
| `veteran` | 元老 | 注册满 180 天 |
| `cardmaster` | 卡牌大师 | 个人累计出牌 ≥ 100（来自 `user_card_usage` 合计） |

### 5.2 标签池（12，首批）

`激进 / 稳健 / 速攻 / 蹲坑 / 卡牌流 / 连锁控 / 萌新 / 大佬 / 夜猫子 / 求带 / 不苟言笑 / 爱聊`

### 5.3 头像框（5）

`none` 无（免费） · `silver` 银环（免费） · `gold` 金环（最高连胜 ≥ 10） · `aurora` 极光（胜场 ≥ 30） · `crimson` 绯红（总场次 ≥ 50）

### 5.4 名片底色（6）

`deep` 深海（免费默认） · `graphite` 石墨（免费） · `cyber` 赛博（胜场 ≥ 10） · `lava` 熔岩（最高连胜 ≥ 5） · `dusk` 暮光（总场次 ≥ 30） · `aurora` 极光（胜场 ≥ 50）

### 5.5 战绩亮点：第 1 批只用现成字段

第 1 批三块大数字 = **最高连胜 / 胜率 / 总场次**，全部由 `users` 表现有字段算出，**零写入**。

> 「累计击沉」需要在对局结算时累加（6 处 `record_match` 都要挂钩子），而那正是第 2 批徽章墙
> （百沉 / 闪电战等）本来就要做的事 —— 放在第 2 批一次做完，避免同一段结算链路改两遍。
> 这是本稿与作者原始选项（最高连胜 / 总击沉 / 胜率）的**唯一偏差**，已确认接受。

### 5.6 最爱用的卡

取 `user_card_usage` 按 `uses DESC` 前 3 张，展示卡名 + 速阶 + 使用次数。
写入点在 `server.py:98 record_card_use` 增加可选 `user_id` 参数，`:3370`（玩家出牌）传入施法者；
沿用现有「统计失败只记日志、绝不影响对局」的 try/except 风格。

## 6. 接口契约

| 接口 | 变化 |
| --- | --- |
| `GET /api/profile` | 返回自己的完整个性字段 + **已解锁的称号 / 边框 / 底色列表**（前端据此把未解锁项灰掉并写出解锁条件） |
| `POST /api/profile/card` | 保存称号 / 标签 / 状态 / 边框 / 底色 / 三个展示开关；逐项按 §4 表格校验 |
| `GET /user_stats` | 追加公开字段：称号 / 标签 / 状态 / 边框 / 底色 / 最爱用的卡；并做隐私过滤（§7） |
| `POST /api/profile/avatar` | **不动**（已有扩展名白名单 + 文件头 magic bytes + 2MB 体积校验，比多数项目细） |
| `POST /api/profile/signature` | **不动**（个性签名保留，与「一句话状态」并存：签名偏静态自述，状态偏当下） |

## 7. 隐私规则

| 字段 | 默认 | 别人能看到吗 |
| --- | --- | --- |
| 头像、用户名、称号、标签、一句话状态、名片底色 / 头像框 | 可见 | 是（「这个人是谁」不受开关控制） |
| 战绩亮点（最高连胜 / 胜率 / 场次） | 可见（`show_stats = 1`） | 关掉后**对所有人隐藏** |
| 最爱用的卡 | 可见（`show_fav_cards = 1`） | 关掉后**对所有人隐藏** |
| 对局历史（`history`） | **不公开**（`show_history = 0`） | 否（返回空数组） |
| 自己的主页 | —— | **永远返回完整历史**（否则「我的对局记录」功能作废） |

⚠️ **三个 `show_*` 是同一套语义**（2026-09-17 实施时补正）：`0` = 该区块对**所有人**隐藏
（包括自己），`1` = 对所有人可见。第一版契约只在 `/user_stats` 里下发了 `show_history`，
另两个开关在「看别人」时被前端读到 `undefined` → 默认显示 → **开关形同虚设**
（典型的「看着能用其实没用」）。实施时已把三个字段一起下发，并明确**不区分视角** ——
两套语义（自己一套、别人一套）必然漂移。

实现要点：`/user_stats` 判断「请求者是不是本人」时用 `session['user_id'] == stats['id']`。
未登录访问他人主页 = 他人视角（受隐私约束）。
`show_history` 与另两个的唯一区别在**默认值**：它对别人默认关，而「自己看自己」永远完整。

## 8. 前端结构

### 8.1 `templates/index.html`

- `#profile-modal`：重写为**查看态容器 + 编辑态容器两套 DOM**，同一份数据，靠 `display` 切换
- `#settings-modal`：重写为 左导航（4 项）+ 右侧 pane 容器；窄屏由 CSS 变顶部横向标签
- 头像上传：原生 `<input type=file>` 保留在编辑态内，外面套一个统一样式的拖拽区（**不引入新库**）

### 8.2 `static/game.js`

| 动作 | 对象 |
| --- | --- |
| 删除 | `buildProfileHead`（:1621）、`buildStatsTable`（:1637） |
| 新增 | `buildProfileCard(data, mode)`、`setProfileMode('view'\|'edit')`、`renderProfileEditor(data)`、`renderSettingsPanes()`、`applyThemePreset(name)` |
| 不改 | `showUserProfile`（:1737）—— 三个入口共用，签名保持一致 |
| 反查 | 落地后用 **grep 渲染文案**（如 `当前连胜`、`胜场`）确认**没有第三套**个人信息渲染 |

> 「同一份东西只允许一处渲染」是本项目已经踩过的坑（`CLAUDE.md` §11 通用教训四）：
> 上一轮就是漏了一处旧的迷你表格，导致局内点头像和排行榜看到的不一样。
> 因此这次**先 grep 文案、再动手**，落地后再 grep 一次。

### 8.3 `static/style.css`

新增一节「个人名片 / 设置页」，**只使用现有变量**（`--panel` / `--panel-border` / `--primary` /
`--primary-rgb` / `--glass` / `--accent` / `--secondary` / `--text` / `--muted`），
遵守第 12 节两条硬规则：**不改盒模型尺寸**、**含 `position:fixed` 后代的元素不加 `transform`/`filter`**。

## 9. 主题预设

| 预设 | 主色走向 |
| --- | --- |
| 深海（默认） | 冷蓝 `#1f6fb8 → #38a3f0` |
| 熔岩 | 暖橙 `#c2410c → #f97316` |
| 赛博 | 紫青 `#7c3aed → #22d3ee` |
| 暮光 | 粉紫 `#be185d → #f472b6` |
| 极光 | 青绿 `#0f766e → #34d399` |
| 经典 | 现在的 `#1565c0 / #1976d2` 体系 |

- 实现：`localStorage['battleship_theme_preset']` + `html[data-theme-preset="…"]` 覆盖一组变量
- 与手动改主色共存：选预设 = 记预设名并清掉手动色；手动调主色 = 预设记为 `custom`，只覆盖主色
- 现有 `battleship_primary_color` 的读取逻辑必须保留（老用户已存的颜色不能丢）

## 10. 验证计划

### 10.1 pytest（新增 `tests/test_profile_card.py`）

1. 越权挂未解锁称号 → 被拒（服务端，不是前端灰掉）
2. 标签超过 3 个 → 只保留 3 个；池外标签 → 拒绝
3. 状态超过 30 字 → 截断；含控制字符 → 清掉
4. 未知 / 池外 `frame_id` / `card_bg_id` → 拒绝
5. `show_history = 0` 时**他人**请求 `/user_stats` → `history == []`；**本人**请求 → 完整历史
6. `/user_stats` 不下发 `password_hash` / `token`（回归守卫，防新增字段时透传整行）
7. `unlocked_titles` / `unlocked_frames` / `unlocked_card_bgs` 边界（差 1 场不解锁）
8. `user_card_usage` 记录 + 读回 + 同卡多次累加 + 写失败不影响返回值
9. `CREATE TABLE IF NOT EXISTS` 在已有库上重复执行不报错（老库兼容）

### 10.2 无头工具（新增 `tools/profile_card_check.mjs`）

- 两态切换：默认是查看态（含 `.profile-card-view`），点「编辑资料」后出现表单，取消回查看态
- 展示开关真的生效：关掉「显示最爱用的卡」后该区块消失，重开又回来
- 主题预设切换后 `getComputedStyle(document.documentElement).getPropertyValue('--primary')` 真的变了
- 设置页左导航 4 项：每次只有对应 pane 可见
- 窄屏 390 / 336 无横向溢出
- 未解锁的称号/边框在编辑态里是灰的且点不动，并写着解锁条件

### 10.3 必须继续通过的旧工具（回归防线）

| 工具 | 守的是什么 |
| --- | --- |
| `tools/profile_leaderboard_check.mjs` | 局内头像 / 排行榜 / `#show-opponent-stats` 三个入口**指向同一份**个人信息面板 |
| `tools/ui_layout_check.mjs` | 棋盘 300×300、单格 42px、浮窗零叠压、对局页一屏不滚动 |
| `tools/stats_modal_check.mjs` | 战绩弹窗与对局详情（本次共享样式） |
| `tools/e2e_batch_2026_09_17.py` | 协议级双客户端回归 |

## 11. 风险与取舍

| 风险 | 应对 |
| --- | --- |
| 三个入口共用一份渲染，改坏即三处同坏 | `profile_leaderboard_check.mjs` 必须保持绿；先 grep 文案找第二套 |
| 只在前端灰掉未解锁项 = 没校验 | 解锁判定**只在服务端**做最终裁决 |
| 隐私开关改变 `/user_stats` 返回形状 | 「本人视角永远完整」由测试钉死（§10.1 第 5 条） |
| 统计写入可能拖慢对局 | 个人卡牌统计沿用 try/except；第 1 批**不新增任何每局结算写入** |
| 新样式破坏既有布局基线 | 只动颜色/圆角/阴影/间距，不改盒模型；`ui_layout_check.mjs` 兜底 |

### 11.1 本批明确不做（YAGNI）

- 徽章墙 / 成就系统（第 2 批，需要每局统计钩子）
- 他人的个人主页（第 2 批，与本批共用同一张卡片，届时复用即可）
- 点赞 / 送花 / 留言板（第 3 批，独立社交层）
- 对局内快捷语 / 表情（第 4 批）
- 累计击沉 / 百沉等每局统计（并入第 2 批，见 §5.5）
- 自由输入的称号或标签（**不做**，避免审核成本与冒充）

## 12. 为后续批次提前对齐的点

1. **第 2 批需要一个统一的「每局结算」收口**：现在 6 处 `db.record_match(...)` 各自为政，
   建议引入 `_finalize_match(room, winner_id, loser_id)` 一次完成「写战绩 + 写统计 + 发通知」，
   否则每加一项统计就要再改 6 个地方（与「通用教训二：两份实现会漂移」同源）。
2. **第 3 批的留言板必须预留**：单条长度上限、频率限制（现有 `_rate_limited` 可复用）、
   删除权限（本人 + 页面主人）、以及最基本的敏感词处理 —— 设计时一次性想清楚，避免后面补。
3. **他人主页与本批共用卡片**：本批只做「自己看自己」，卡片渲染必须写成
   `buildProfileCard(data, {editable: false})` 也能直接用的形状，第 2 批不重写。

---

## 13. 实施记录（落地后回填）

## 13. 实施记录（2026-09-17 落地）

### 13.1 实际改动文件

| 文件 | 改了什么 |
| --- | --- |
| `profile_spec.py`（新） | 池子 + 解锁规则（唯一一份）+ `catalog()` + `validate_payload()`，纯函数无 IO |
| `db.py` | `user_profile` / `user_card_usage` 两张表 + 1 条索引 + 5 个 DAO 与模块级包装（UPSERT 持锁、列名白名单、失败只记日志）；**未动 `users` 表结构** |
| `api.py` | `GET /api/profile` 追加个性字段 + `catalog`；新增 `POST /api/profile/card`；`/user_stats` 追加公开字段 + 三个 `show_*` + 隐私过滤 |
| `server.py` | `record_card_use(card, count, user_id=None)`；调用点传 `Player.user_id`（**不是** `room.players` 的 key） |
| `static/game.js` | 删 `buildProfileHead` / `buildStatsTable`；新增 `profileCardModel` / `buildProfileCard` / `renderProfileEditor` / `collectProfileEditorPayload` / `saveProfileCard` / `setProfileMode` / `bindProfileCardUI` / 主题预设四件套 |
| `templates/index.html` | 编辑面（左导航 + 4 分区 + 底部保存行）+ 设置面（左导航 + 4 分区）；**所有旧 id 一个没删** |
| `static/style.css` | 新增一节：`.pf-card`（方案 A 分层名片）+ `.pf-editor` + 设置页 + `html[data-theme-preset]` 四套覆盖 |
| `tests/test_profile_card.py`（新） | 72 条 |
| `tools/profile_card_check.mjs`（新） | 51 项，**真注册登录 + 真保存落库**，只桩「别人主页」的数据 |
| `tools/dom_contract_check.mjs`（新） | DOM 契约对账：区分「运行期渲染」与「真悬空」 |
| `tools/profile_leaderboard_check.mjs` | 断言随新结构更新（功能一条没减） |
| `tools/last_stand_board_check.mjs` | 1d 改为断言「**新**画上命中/落空」（见 13.3） |

### 13.2 实测输出（全部在落地后重新跑过）

| 层 | 命令 | 结果 |
| --- | --- | --- |
| pytest | `python -m pytest tests/ -q` | **936 passed**（基线 864 + 72，零回归） |
| 协议 e2e | `python tools/e2e_batch_2026_09_17.py` | 全部通过 |
| 新工具 | `node tools/profile_card_check.mjs` | **51 PASS / 0 FAIL** |
| 个人信息守卫 | `node tools/profile_leaderboard_check.mjs` | 47 PASS 全通过（三个入口仍指向同一份面板） |
| 布局不变量 | `node tools/ui_layout_check.mjs` | 全部通过（含 6 个窄视口，CSS +613 行后未破） |
| 战绩弹窗 | `node tools/stats_modal_check.mjs` | 21 PASS |
| 连锁预览 | `node tools/chain_preview_check.mjs` | 25 PASS |
| 绝处逢生棋盘 | `node tools/last_stand_board_check.mjs` | 16 PASS（连跑 3 次稳定） |
| DOM 契约 | `node tools/dom_contract_check.mjs` | 全部通过 |

### 13.3 实施中发现的四个真问题（都不是「照着设计稿写」能避开的）

1. **★ 设计稿漏了两个开关的下发（假控件）**：§2.5 只要求 `/user_stats` 给出 `show_history`，
   于是「看别人」这条路径上 `show_stats` / `show_fav_cards` 读到 `undefined` → 前端按默认值
   当成「显示」→ **玩家关掉这两个开关后，别人照样看得到**。已裁决并补上：三个 `show_*`
   **同一套语义**（0 = 对所有人隐藏，含自己），并加了 3 条 pytest 钉死「不区分视角」。
   👉 教训：**开关必须有下发给「别人视角」的路径**，只发给自己等于没做。
2. **两块面，不是一个**：实测 `#profile-modal`（编辑）与 `#opponent-stats-modal`（查看，
   四个入口共用）是两个容器。第一版契约把两个态都塞进 `#profile-modal`，会逼四个入口改道、
   并丢掉上一批要求保留的**对局历史列表**。已在动手前修正契约（`docs/..._PLAN.md` §3.1）。
3. **`#profile-view-*` 的撞 id 隐患 —— ⚠️ 这一条在第 2 批期间被实测纠正过，原结论是错的**：
   原文写「只在查看面输出、首页老容器只出 class」，**与代码不符**：`fetchProfile()` 里
   `ids` 写死为 `true`，而它有两个调用点（查看面 `showUserProfile`、首页老战绩容器
   `showUserStats`）→ **两个容器都会输出那 12 个 id**。当时没炸只是因为所有读取方都是
   容器内 scoped 查询（`container.querySelector`）。
   **实测证据**（无头工具点的**真实入口**，不是读源码猜）：把首页那处改回出 id 时
   `{"homeIds":12,"viewIds":12}` = **同一文档 24 个同名 id**。
   **修法**：`fetchProfile(username, limit, opts)` 增加 `ids`，由调用方声明 ——
   查看面 `{ids:true}`、首页老容器 `{ids:false}`；并加了 `profile_card_check.mjs` 的 D1/D1b
   守卫（**点真实入口**验证；直接调渲染函数看默认值会漏掉这个 bug —— 这正是第一版工具漏掉它的原因）。
4. **主题预设的旧自定义色会压住预设**：`applyPrimaryColor` 写的是 documentElement 上的**内联
   `--primary*`**，优先级高于任何 CSS —— 只清 localStorage 的话「切回预设」等于没切。
   必须同时清内联变量。

### 13.4 上线与生产验证（2026-09-17）

提交 `b2c46c1` → `push.sh` 推 GitHub（本机与服务器 tree 哈希一致 `677cad7`）→ `deploy.sh`
（整包跑全量 936 passed → `git reset --hard` → 重启 → 健康检查 HTTP 200），
线上 PID 99934、`battleship` active。

**只读层（脚本 + curl，未写任何生产数据）**

| 检查 | 结果 |
| --- | --- |
| 生产库两张新表 | `user_profile` / `user_card_usage` 均存在，列名与契约一致 |
| `GET /user_stats?username=<真实账号>` | 13 个新字段**一个不缺**；`password_hash` / `token` 未下发 |
| 隐私（游客看他人） | `history` 为 **0 行**、`show_history = 0` ✔ 过滤生效 |
| `GET /api/profile`（未登录） | 401 |
| `POST /api/profile/card`（未登录） | 401 |
| 下发 HTML | 含 `#theme-preset-grid` / `#profile-edit` / `#profile-card-save` / `#settings-nav-item`×4 / `#wp-section` / `#profile-show-history` / `#opponent-stats-content` |
| 下发 CSS / JS | `data-theme-preset` 5 段；`game.js` 含 `buildProfileCard` |

**UI 层（无头 Edge 只读探针，不注册账号、不改数据）：13 项全过**
线上真实账号 小小弈11 的名片实测渲染：`Lv.10 · 最高连胜 9 · 胜率 69% · 总场次 45`（由 31 胜 14 负算出）、
`第 1 名`、加入时间，**历史区块显示「该玩家未公开对局历史」**（隐私端到端生效）；
设置页左导航、主题预设换色（`#1565c0 → #22d3ee`）、`localStorage` 持久化、
🎬/🎵 两个入口落在 `wp` / `sound` 分区 —— 全部通过。

⚠️ **生产探针踩到的一个时序坑**（本地工具永远看不到）：弹窗**可见 ≠ 内容就绪** ——
名片先渲染「加载中…」再异步取数，本地服务端快到看不出差别，线上必须等
`#profile-view` 真的出现再断言，否则读到的是加载态。探针已改成两段等待。

### 13.5 本批仍未做（下一批的入口）

- 徽章墙 / 成就系统、他人主页的「约战 / 加好友」（第 2 批）
- 点赞 / 送花 / 留言板（第 3 批）
- 对局内快捷语 / 表情（第 4 批）
- 需要登录才能验的**编辑态保存**目前只在本地隔离库验过（`profile_card_check.mjs` 真注册真落库）；
  生产上未注册测试账号，如需线上验证编辑链路，请用自己的账号点一遍或允许我建一次性小号。

### 13.6 工具侧的四个假红（都改在工具里，不留在人工记忆里）

| 假红 | 真因 | 修法 |
| --- | --- | --- |
| `profile_card_check` 首次跑「等待超时：页面加载」 | 上一次运行残留的无头 Edge 占着调试端口、锁着 profile，新浏览器**静默起不来**，工具连上的是旧实例 | 工具开头按 profile 路径**预清理**残留进程 |
| 同上，A1/A2 偶发失败 | `Page.navigate` 返回后 `readyState` 仍是**旧文档**的 complete，断言打在上一页 | `goto()` 改为等「地址真的变了」+「新文档加载完」 |
| `last_stand_board_check` 1d 偶发红 | 它先跑真机对局（§4），AI 随机打中的格子可能正好是 §1 的注入坐标；而既定行为**就是**让已打过的候选格显示真实结果 | 改为断言「**新**画上命中/落空」，并在失败时打印前后类名 |
| `profile_card_check` T2 主色断言第二次必红 | 无头浏览器用**持久 profile**，上一轮已把预设存进 localStorage | 先切回「深海」归零，再切「熔岩」再断言 |

**共同点**：全都是「**测试环境的状态**没被清干净」造成的假红 —— 与本项目此前记过的
「无头 profile 别放 C:/Windows/Temp」「持久 profile 带着上一轮状态」是同一类问题。
**新增工具时先把这四条当作检查清单过一遍。**
