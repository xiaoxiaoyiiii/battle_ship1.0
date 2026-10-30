# UI 重设计落地（#41 / 票 #42–#52）与仓外门禁重定

- 日期：2026-10-20 ｜ 集成分支 feat/ui-redesign，冻结 HEAD `1e070d6`（28 个提交）
- 规格：Issue #41 / `docs/UI_REDESIGN_SPEC_2026_10_20.md`
- 本文是交付取证：做到什么、门禁数字、重定了哪些旧断言及原因、残余项。

## 1. 做到了什么（按票）

| 票 | 交付 |
| --- | --- |
| #42 | 设计令牌与三主题、应用壳层（四目的地+头像菜单+好友图标）、浮层/提示/三态基础设施 |
| #43 | 服务端只增契约：回合截止、对手状态、稳定错误码、大厅房间字段、排行榜名次；契约产物重生成 |
| #44 | 登录/注册浮层与身份入口，游客自动名（舰长+四位数字），`bs:auth-required` 事件 |
| #45 | 首页单主行动与大厅卡片/筛选/空态；图鉴改为可搜索卡库入口 |
| #46 | 布船 6 槽与底部确认、猜拳可读结果与等待/离开回执、匹配成功「立即进入布船」 |
| #47 | 对局屏单主棋盘、状态带与回合计时、可读手牌与卡牌详情、连锁环形计时、抽屉化日志/聊天、非法点击回执 |
| #48 | 结算三出口（再来一局/返回大厅/返回首页）、未知数据隐藏、可跳过的 600ms 揭示、本局回放、加对手好友；回放单主盘+视角切换+轰炸标记+回传来路；观战手机标签+游客登录 CTA |
| #49 | 排行领奖台与固定「我的名次」、档案最近使用排序、设置四分组、减少动效/高对比/字号三档作用于全站 |
| #51 | 布船/猜拳阶段实时下发对手就绪与在线状态 |
| #52 | 全站连接横幅、大厅公告行、卡面语义、连锁环形计时、退出判负文案、自定义结算出口、错误码表与超时注入 |
| #53 | 终验缺陷修复：对局通道拉手牌（RPS 切屏丢手牌）、重连恢复座位、确认按钮回执、手机投降可达、公告关闭 44px |
| #50 | 仓外门禁重定、基线重录、旧套件归档、本文与玩家公告 |

## 2. 门禁集合（唯一真源：仓外 D:/develop/battleship-verify）

- `tools/web/run_all.py`：30 个工具 —— 7 个 41-* 屏级门禁（foundation/auth/settings/settlement/flow/game/review-fixes）
  + 既有 23 个（layout/mobile/replay/spectate/lobby/cards/…）。
- run_all 现在：向子进程发布 `WEB_BASE_URL`（20 个只读环境变量的工具不再一律打 5420）、注册全部 41-*、
  并按白名单判定 SKIP —— **白名单外的 SKIP 直接判 FAIL**。
- 旧 `review-fixes`（重设计前的综合回归）已从 TOOLS 退休：其唯一独有覆盖（`__BOOT__` 启动 JSON）暂缺新套件承接，见 §7 残余 7；由 41-review-fixes + 41-game + 41-settlement 接替 UI 行为。
- 截图基线：`tools/web/baselines/manifest.json` 的 14 项 D33 指纹，已按冻结 HEAD 重录；
  旧 cases/22–28 的 22 张套件内基线随套件归档封存。
- pytest：`cases/4,6,7,9,14,17,18,19,41-contracts` 与 `cases/30-cleanup`（构建/文档/路由/契约）。

## 3. 门禁数字（终验 HEAD 62ce8be，串行、独立库、无并发服务端）

**最后一轮（feat/ui-50-gates-2，--only 四件套）**

- `cplus-path` **PASS**（101 checks / 0 failures；九段：真实坐标点击、登录注册刷新、匹配成功立即进入、静默点、断线重连恢复座位、三出口、手机单盘、零 JS 异常）。
- `cards` **PASS**；`mobile` **PASS**；`layout` **PASS**（含 lobby 公告关闭按钮已由 #53 修到 44px）。
- `41-final-fixes`（#53 自带门禁）已注册进 TOOLS；独立运行时用隔离端口 5452。

**上一轮全量（HEAD 1e070d6，29 个工具）作为对照**

- 24 PASS / 2 SKIP / 3 FAIL；其中 `41-review-fixes` 的失败是门禁夹具缺陷（custom 结算喂 `ranked:true`），修正后单工具 12/12 PASS。
- 其余 2 FAIL（`layout` 的 32px 公告关闭、`cplus-path` 的手牌/重连/回执/手机投降）均由 **#53** 修复；本轮四件套重跑已全绿。
- SKIP 仅在白名单：`rank-help`（无帮助屏）、`cplus-screens`（无 room/图鉴路由）；白名单外 SKIP 直接 FAIL。

**pytest（integration 工作区）**

- 4-backend-root 26 passed / 1 failed（GBK 解码 + None stderr 拼接的环境/夹具问题，与改版无关）
- 6-auth 26、7-rooms 16、9-battle 37、14-lobby 26、17-spectate 39、18-replay 21、19-http 25 → 全绿
- 41-contracts 12 passed（按 #52 重定：AckResponse 的 code 死字段已删，稳定错误码在 error 帧/错误码表）
- 合计 **228 passed / 1 failed（环境）**

## 4. 重定了哪些旧断言，为什么

| 旧断言 | 为什么重定 | 新断言 |
| --- | --- | --- |
| cplus-path「回放退出 → 首页」 | #48 起回放带 `from=`，应回来源 | 回放退出回结算（并有 lobby/profile 来源分支） |
| cplus-path「单浏览器 + el.click()」 | 规格要求真实坐标点击、登录、五静默点、双视口 | 七段式重写：真 Input.dispatchMouseEvent + 命中测试；断线与三出口 |
| 结算「再来一局 = 返回首页」 | 三出口不得共用 | 再来一局→新排队/新对局；返回大厅→/lobby；返回首页→/start |
| 档案「胜率 —」 | 规格禁止成排「—」 | 未知值显示「暂无」 |
| 大厅「点解散即消失」 | #45 起两段确认并解释后果 | 断言确认文案、可取消、确认后消失 |
| cases/33「契约相对 feature/rewrite 零 diff」 | 重设计合法新增契约 | `cases/41-contracts` 的「只增不减」+ 路由/事件集合不变 |
| 「两块棋盘同尺寸 ≥280px」 | 新设计单主棋盘 | 41-game：桌面主盘 ≥480px、己方小地图；手机单盘+标签 |
| 触控 ≥40px | 规格改为 44px（矮横屏 36px 放宽） | **未完成**：layout/mobile 仍是 40px 口径（见残余 1） |
| 截图指纹的 C+ 紫色调色板 | 新视觉语言 | 14 张基线按冻结 HEAD 重录（逐张归因见 §5） |
| toast 重复 testid 判不唯一 | 提示队列本就是栈 | `checkUniqueTestids` 忽略全局 toast/route-loading |
| cards「确认按钮 disabled」 | #53 改为 aria-disabled（禁用仍可给出回执） | 断言 `aria-disabled="true"` |
| cplus-path offline 段放在 settle/mobile 之后 | 段末停在结算屏，断线段拿不到对局 | offline 移到 game 之后、settle 之前；`request_hand_sync` 带 room_id/player_id |
| AI 房猜拳随机可能导致平局卡在 RPS | 门禁需确定性 | AI 房先 `test_set_ai_rps_choice` 钉住必输手势，再点我方手势 |

## 5. 基线重录归因（14 张，全部为真实改动）

| 基线 | 归属 | 理由 |
| --- | --- | --- |
| layout-start-desktop / changelog-home-desktop | #42/#43/#44/#45 | 首页单主行动、公告行、身份入口、壳层 |
| lobby-desktop | #45 | 房间卡片（房主/人数/模式/公开性）、筛选、空态 |
| cplus-placement-desktop / mobile-placement | #46 | 6 舰位槽、底部确认、随机/清空、对手状态 |
| cards-game-desktop / mobile-game | #47 | 单主棋盘、状态带、手牌详情、抽屉 |
| leaderboard-desktop / ranked-leaderboard-desktop | #49/#43 | 领奖台、固定我的名次、行可点 |
| profile-card-desktop | #49 | 最近使用排序、未知值「暂无」 |
| cplus-result-desktop | #48/#52 | 三出口、隐藏未知、可跳过揭示、自定义结算出口 |
| replay-desktop / spectate-desktop | #48 | 回放单主盘+视角标签、观战手机标签/游客 CTA |
| wallpaper-settings-desktop | #49 | 设置四分组 + 外观/可访问性 |

重录纪律：先跑不带 update 的工具读 mean/max/beyond 并对照 `cases/29-tools/.shots/`，按票归因后才单批
`--update-baselines`；容差未放宽（mean ≤1、>10/255 占比 ≤0.2%）；重录后不带 update 复跑必须精确命中。

## 6. 旧套件归档

`cases/21-shell、22-sample、23-placement、24-lobby、25-profile、26-home、27-game、28-replay、31-chat、33-gaps`
已移到 `cases/99-archived-41/`，每套保留原文件 + 一句归因（见该目录 README）。不逐条改写旧断言。

## 7. 残余项 / 未完成（需要 lead 决定）

1. **触控 44px 口径仍未升级**：layout/mobile 判据仍是 40px；本轮 0 fail 依赖 #53 把公告关闭按钮修到 44px，但判据本身未改成 44px（含矮横屏 36px 放宽档）——下一票需要重定。
2. **已由 #53 修复并在本轮验证**：RPS→对局拉取手牌、断线重连恢复座位（rejoin 后 `request_hand_sync` 成功）、确认按钮回执、手机投降可达。cplus-path 对应四段现全绿；留作回归点。
3. **静默点覆盖残差**：`选目标时点非法格` 在本 UI 无可复现路径（整行/整列 + 合法格），cplus-path 以 WARN 记录未覆盖；`点不可用的确认按钮` 现在有回执（#53），但门禁在该状态下走的是「确认按钮已可用」分支，仅 WARN。
4. **断线重连不恢复座位**：浏览器离线→恢复后横幅出现「已恢复」，但 socket 换了 sid，服务端回「你不在这个房间」，
   之后的投降/操作全部失效（规格故事 52/84 要求重连回原局）。cplus-path offline 段有断言。
5. **提示队列会短暂遮住底部控件**：2–6s 的 toast 落在「更多操作/确认投降」上方，真实点击会被挡；
   cplus-path 用「关掉提示再点」绕过，并在投降路径上留了 socket 兜底（WARN 可见）。
6. **AI 房门禁需要 pin 猜拳**：不 pin 时随机平局会让 RPS 阶段停住（本轮已修门禁，非产品问题）。
7. **回合计时在门禁环境不可见**：run_all 固定 `TURN_TIMEOUT_SECONDS=0`，此时服务端不下发 deadline；
   时钟/超时回执由 41-game 用服务端形状的 fixture 覆盖，cplus-path 对该段只 WARN。
8. **cases/21–33 归档后**：构建产物/SPA 托管断言暂无仓内新套件承接（见归档 README 第 4 节）。

## 8. 证据索引

- 全量日志：`D:/develop/battleship-verify/cases/29-tools/full-run-50-final.log`
- 基线重录日志：`cases/29-tools/baseline-update-50.log`；截图历史：`cases/29-tools/.shots/`
- pytest：`cases/4,6,7,9,14,17,18,19,41-contracts`（见报告）
- 旧套件归档：`cases/99-archived-41/README.md`