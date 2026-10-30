# 匹配成功与对战确认界面调研（2026-10-30）

本轮围绕 Battle_ship 的“匹配成功后五秒进入对局”场景调研成熟游戏的官方设计，重点关注：双方身份资料、称号、头像与头像框、段位和等级、倒计时节奏、AI/真人差异、动效冲击力与可读性。本文只记录调研和落地方向，不包含业务代码或测试文件。

## 结论先行

当前截图中的确认弹窗仍把双方显示成两个通用的“战舰图标 + 名字”面板。成熟产品普遍把这一步当成一场短促的对战揭示，而不是普通等待弹窗：

1. **双方卡片必须先展示身份，再展示装饰。** 头像、头像框、称号、段位徽记和等级应组成同一个身份卡，名字是主层级，称号是副标题，段位/等级是可扫描的信息标签。
2. **左右对称、颜色分阵营、中心 VS 是稳定的结构。** Riot 对 VALORANT faceoff 的官方说明明确提到：移除地图，让 Player Cards 占据空间；突出 Player Cards、Titles、Rank badges；两侧颜色增强、布局镜像，并增加 VS 文案来强化正面对抗感。
3. **动效应服务于信息揭示。** 先让双方卡片入场，再在短时间内揭示称号与段位，倒计时始终是主锚点。不要让长动画阻塞“立即进入布阵/棋盘”的动作。
4. **等级和段位要有展示策略。** Overwatch 2 曾因赛前暴露等级和竞技段位导致队友提前判断而移除这些信息，改用可自定义的 Name Cards 和 Titles；后来又采用“队友先看完整卡片、敌方在对局开始一段时间后再看”的分级可见性。Battle_ship 当前是 1v1 对战确认，可以展示用户要求的段位和等级，但应把它们做成可配置的次级信息，而不是压过名字和头像。
5. **AI 必须有明确身份，不伪装成人类。** AI 卡片可以使用统一的机器人图标、`AI 对手` 标签和较简洁的段位占位，不应套用玩家头像、动态称号或会误导玩家的稀有装饰。

## 1. VALORANT：最贴近“匹配成功后双方揭示”

一手资料：[Riot 官方：Preview the future of VALORANT’s interface](https://playvalorant.com/en-gb/news/game-updates/preview-the-future-of-valorant-s-interface/)

官方把 lobby、pre-match loading screen 和 faceoff screen 作为同一套体验重做。文章明确说明：

- 通过 motion design 改善游戏流程和表达，目标不是装饰越多越好，而是让客户端体验更有品质和连续性。
- 为了提高可读性，团队移除了没有实际作用的装饰，提升对比度、强化色值并简化形状语言。
- Faceoff 屏幕去掉地图，让两侧 banners 充分展示玩家身份；布局采用镜像对称，颜色更有冲击力，并使用 VS 文案强调双方对抗。
- 展示重点是 Player Cards、Titles 和 Rank badges，而不是把所有战绩一次塞进弹窗。

**适合 Battle_ship 的映射：**

- 保留当前左右对战结构，但把通用战舰大图改成 `AvatarStack + TitleBadge + RankBadge + Level` 的身份卡。
- 使用玩家自己装备的资料背景作为卡片底图或两侧光带，中央保留干净的 VS 区域；背景必须加渐变遮罩，避免文字被动画吃掉。
- 玩家和 AI 使用不同的卡片密度：玩家显示头像、头像框、称号、段位和等级；AI 显示机器人头像、`AI 对手`、难度/模式标签。
- 视觉冲击应该来自“卡片进入 + 阵营光带 + VS 脉冲 + 倒计时收束”，而不是持续闪烁。

## 2. League of Legends：称号、段位和玩家卡片的分层

一手资料：[Riot 官方：Challenges Walkthrough](https://www.leagueoflegends.com/en-us/news/game-updates/challenges-walkthrough/)

League 的官方设计把身份拆成多个可理解的层级：

- 大厅以 Summoner Icon 为身份中心，旁边配 Ranked Border、Challenge Crystal、Title 和最多三个 Challenge Tokens。
- Title 是玩家主动解锁和选择的称号，放在名字下面，形成稳定的阅读顺序。
- Loading Screen 的 Player Card 分为三面：游戏信息、英雄信息、玩家信息；玩家信息单独承载 Rank、Challenge Crystal 和 Challenge Tokens。
- Identity Menu 支持 Icons、Borders、Titles、Challenge Tokens，并提供实时预览和 Undo，避免用户频繁保存才能判断效果。
- Quick Switcher 让十名玩家的卡片切换到同一面，减少逐张点击带来的操作成本。

**适合 Battle_ship 的映射：**

```text
身份卡
├─ 头像 + 头像框                 // 第一视觉焦点
├─ 玩家名                        // 最大文字
├─ 称号                          // 名字下方，允许流光/呼吸但不能持续跳动
├─ 段位徽记 + 段位文本           // 小型稳定标签
└─ Lv. 等级                      // 与段位同一信息行，降低视觉权重
```

- 五秒确认页只显示一面“对战信息卡”，不要同时塞入战绩、成就和所有收藏；详细信息留给个人主页或进入局内后的查看入口。
- 称号动画采用一次入场高光或低频流光，不能让字形位置上下跳动；用户必须在第一眼读清文字。
- 编辑名片时使用和对战确认相同的预览组件，保证“我装备的效果”与“对手看到的效果”一致。

## 3. Overwatch 2：显示时机和避免赛前偏见

一手资料：

- [Blizzard 官方：Defense Matrix activated](https://news.blizzard.com/en-us/article/23857517/defense-matrix-activated-fortifying-gameplay-integrity-and-positivity-in-overwatch-2)
- [Blizzard 官方：Initializing systems! Updating Competitive play](https://news.blizzard.com/en-gb/article/23857518/initializing-systems-updating-competitive-play-in-overwatch-2)
- [Blizzard 官方：Weekly Recall: Gaining Progress](https://news.blizzard.com/en-us/article/24224138/weekly-recall-gaining-progress)
- [Blizzard 官方：Show Off Your Playstyle](https://news.blizzard.com/en-gb/article/23991794/show-off-your-playstyle-with-the-new-player-progression-system)

Blizzard 官方明确记录了两类经验：

- 赛前直接展示玩家等级和竞技段位可能引发队友先入为主，因此 Overwatch 2 曾移除表示玩家等级的 Portrait Borders，并在竞技匹配前不直接显示 skill tiers；玩家改为使用可自定义的 Name Cards 和 Titles。
- 在后续 Hero Select 场景中，队友可以较早看到完整 Player Card；敌方 Player Cards 和 Ascended borders 会延迟到对局开始后，避免对局尚未开始就暴露过多信息。边框还可以随英雄进度升级并在 Hero Select 中为队友闪耀。
- 进度奖励包括 badges、Player Icons、Name Cards 和 Titles，并在头像与 BattleTag 旁边的多个场景复用。

**适合 Battle_ship 的映射：**

- 当前产品明确要求匹配成功页显示段位和等级，可以实现；但应提供 `显示详细身份` 的偏好设置，未来支持“只显示称号/头像框，不显示等级”的社交保护模式。
- 匹配成功页的段位和等级使用静态徽记与数字，不使用会不断变化的数字跳动；稀有动态边框可以闪耀一次，随后进入稳定状态。
- AI 资料永远标记为 AI，不进入玩家装饰所有权体系，不生成假的段位历史。
- 如果未来加入多人房间，可沿用 Overwatch 的分阶段展示：队友先看到完整身份，敌方只看到头像、称号和阵营信息，进入对局后再开放详细卡片。

## 4. Steam：个人资料背景与主题色的可读性边界

一手资料：[Steamworks 官方：Points Shop Items](https://partner.steamgames.com/doc/marketing/pointsshopitems?language=english)

Steam 将头像、头像框、完整资料背景、迷你资料背景和 Game Profile 作为独立槽位，Game Profile 可以组合动画头像、头像框、背景和主题色。官方还要求主题色不能破坏文字可读性，并限制动画资源体积；这说明“背景进入对战确认页”时应以主题氛围层出现，不能直接把个人主页的高密度动画全量搬进倒计时弹窗。

**适合 Battle_ship 的映射：**

- 资料背景可以作为全局游戏背景，也可以在对战确认页作为两侧卡片的主题光场；中央倒计时区域使用独立不透明底板。
- 个人资料背景的高密度粒子在对战确认页应降采样，保留色彩和轮廓，避免双方背景叠加后抢过名字和倒计时。
- 每个背景主题提供 `matchReveal` 轻量版本，专门用于匹配成功页和局内 HUD；列表和移动端使用静态 fallback。

## 5. 推荐的五秒揭示节奏

下面是基于上述产品模式的 Battle_ship 建议时序。它是实现目标，不是外部产品的硬编码：

| 时间 | 视觉事件 | 信息目标 |
| --- | --- | --- |
| 0–120ms | 弹窗和阵营光带出现，背景快速压暗，中心 `MATCH FOUND` / `匹配成功` 定位 | 立即确认匹配已经成功 |
| 120–420ms | 左右玩家卡片从两侧进入，头像框/头像只做一次短促高光 | 先识别两位对手 |
| 260–620ms | 名字和称号从卡片内部淡入，称号流光只经过一次 | 读清身份文字 |
| 480–820ms | 段位徽记、段位文本、Lv. 标签补齐；AI 同步显示 `AI 对手` | 扫描实力信息，区分 AI/真人 |
| 820–1100ms | 中心 VS 脉冲一次，进度环开始倒计时 | 建立对战冲击点 |
| 1100ms–4.2s | 每秒倒计时更新，卡片保持稳定，背景只做低频漂移 | 给用户准备时间，不干扰阅读 |
| 4.2–4.8s | 阵营光带收束到棋盘方向，主按钮/自动进入动作变为高亮 | 传达即将进入对局 |
| 4.8–5.0s | 轻量过渡到对局，不再播放第二套长动画 | 保证进入动作及时 |

验收边界：卡片里的姓名、称号、段位和等级应在 1.1 秒内可读；主动画的主体扩展不超过 700ms；倒计时永远不被动效遮挡；`prefers-reduced-motion` 下保留静态入场和清晰数字倒计时。

## 6. 数据与工程建议

匹配确认页不要在动画过程中重新请求个人资料。匹配成功事件应携带一次性身份快照：

```ts
type MatchRevealPlayer = {
  side: 'self' | 'opponent'
  kind: 'human' | 'ai'
  displayName: string
  avatarUrl?: string
  avatarAlt?: string
  frameId?: string
  titleId?: string
  titleText?: string
  titleEffect?: 'static' | 'sheen' | 'breathe' | 'orbit'
  rankId?: string
  rankLabel?: string
  level?: number
  profileBackgroundId?: string
}
```

建议：

- `kind` 必须来自服务端，AI 不由前端根据名字猜测。
- `frameId`、`titleId`、`rankId` 对应服务端已经校验过所有权的装备快照，匹配过程中不随个人主页实时变化。
- 头像、头像框和背景资源加载失败时分别回退到默认头像、静态框和静态主题，不让一个资源失败拖住五秒倒计时。
- 对战确认页复用 `AvatarStack`、`TitleBadge` 和个人背景主题 token，避免个人主页和对局页出现两套不一致的视觉规则。
- 动效层使用 `pointer-events: none`，不抢占“立即进入布船/棋盘”的按钮焦点。

## 7. 最终落地方向

本项目下一轮应按以下优先级实现：

1. **修正确认页信息模型**：从通用战舰图标切换为真实玩家/AI 身份卡，接入头像、头像框、称号、段位徽记和等级。
2. **实现五秒揭示时序**：卡片入场、称号/段位补齐、中心 VS、短促倒计时和进入对局收束。
3. **接入个人资料整体背景**：在大厅、主页、匹配确认和排行榜共享背景主题 token；匹配确认页使用低密度 `matchReveal` 版本。
4. **补足可读性与降级**：加入背景遮罩、静态资源回退、AI 标签、低动效模式和移动端布局。
5. **保留未来扩展位**：称号动效、头像框光效、全局鼠标特效可以继续作为装备槽位，但在匹配确认页只允许一次性或低频播放，避免五秒内堆叠多个动画。

## 来源与边界

本文检索日期为 2026-10-30。产品行为和设计意图均来自上述官方资料；“五秒揭示时序”、`MatchRevealPlayer` 数据结构、AI 卡片差异化和 `matchReveal` 资源档位是结合 Battle_ship 当前界面提出的工程建议，不代表 VALORANT、League、Overwatch 或 Steam 的内部实现。
