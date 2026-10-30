# 全局指针特效与个性化装饰深度调研（2026-10-30）

本轮针对 Battle_ship 的后续 P1 工作重新调研成熟游戏和社区产品，重点回答四个问题：

1. 鼠标拖动尾迹、点击波纹和手机触控反馈如何做成全局能力，尤其覆盖局内战斗。
2. 如何把尾迹、点击特效、头像框、头图/个人资料背景和称号拆成可组合、可付费或通行证解锁的装饰槽位。
3. 如何让名片背景真正影响个人主页和整体界面，同时保留战斗信息的可读性。
4. 高级称号和动态装饰如何显得稀有，但不靠持续频闪和堆叠粒子制造噪音。

本文件只记录调研与可执行结论，不改业务代码，不包含测试文件。

## 结论先行

Battle_ship 的“鼠标拖动尾迹”和“点击/触控特效”应该从当前名片局部实现提升为**应用级输入反馈层**：

- 由应用 Shell 或统一输入服务监听 pointerdown、pointermove、pointerup、pointercancel；
- 视觉层固定在最上层，覆盖大厅、名片、设置和局内战斗，但必须 pointer-events: none，不改变按钮命中、棋盘落子或拖动逻辑；
- 鼠标/笔可以显示短尾迹；手机触控以点击波纹和轻量粒子为主，滑动超过 touch slop 后才显示尾迹；
- 战斗内使用低亮度、短寿命、低节点数的版本；名片编辑和个人主页可以展示完整版本；
- 装饰的所有权和效果选择由服务端保存，尾迹坐标和粒子状态只在本地即时渲染，不上传服务器。

同时，名片需要拆成以下独立槽位：

- avatar：用户上传的静态或动态头像；
- avatar_frame：头像边缘的静态/循环框；
- profile_background：个人主页和资料页的大背景；
- profile_theme：资料卡颜色、面板透明度和强调色；
- profile_entry_effect：打开名片时播放一次的入场效果；
- cursor_trail_effect：全局鼠标/笔拖动尾迹；
- pointer_burst_effect：点击或触控反馈；
- title_style：称号文字、稀有度、边框、微动效；
- bundle_id：可选的主题套装，套装只是默认组合，仍允许单件替换。

## 一手资料核实

### osu!：最直接的全局光标尾迹和点击反馈范例

- [osu! 官方 Wiki：Interface skinning](https://osu.ppy.sh/wiki/en/Skinning/Interface)
- [osu! 官方 Wiki：Client options](https://osu.ppy.sh/wiki/en/Client/Options)

osu!把光标拆成多个可以换肤的资源层：

- cursor.png 默认会在点击时旋转和扩张；
- cursortrail.png 位于光标下方，支持拖动尾迹，也可以单独控制是否旋转；
- cursor-ripple.png 在鼠标左键/右键按下时显示点击反馈；
- 设置页有 Cursor ripples 开关，说明点击波纹是独立可关闭的用户偏好；
- 光标、尾迹和波纹由皮肤提供，说明“输入反馈的表现”和“业务操作本身”可以解耦。

对 Battle_ship 的直接启发：

1. 统一输入事件只负责生成“轨迹点”和“点击点”，颜色、形状、粒子数量、衰减方式由用户装备的效果配置决定。
2. 尾迹与点击爆发必须是两个独立槽位。用户可以装备“无尾迹但有点击波纹”，也可以只开尾迹。
3. 对局中可保留较克制的光标主体和点击反馈，名片或大厅允许更完整的循环与粒子。
4. 设置中需要有“显示指针特效”开关，并与应用动效模式联动。

### Steam：资料背景、头像框和主题色的组合式商品模型

- [Steamworks 官方：Points Shop Items](https://partner.steamgames.com/doc/marketing/pointsshopitems)

Steam 将装饰拆成头像框、动画头像、资料背景、迷你资料背景、动画贴纸和 Game Profile：

- 动画头像框建议为循环 APNG，224×224，文件小于 2MB，并提供静态 PNG；
- 动画资料背景使用循环 MP4/WebM，完整资源小于 4MB，同时提供小预览和静态 JPG；
- 迷你资料背景只在好友列表悬停等小场景出现；
- Game Profile 把动画头像、头像框、动画迷你背景和动画资料背景组合成一个主题套装，并额外配置 5 个 RGBA 主题色；
- 官方明确要求主题色不能破坏文字可读性，资料背景底部可以自然淡入黑色；
- 官方规则要求避免频闪和闪烁，且素材需要适配资料内容遮挡区域。

对 Battle_ship 的直接启发：

- 头像框、头图、整体资料背景和指针特效可以组合成“海域赛季”“深空旗舰”“极夜雷达”等主题套装，但数据库仍按单件槽位保存；
- 预览必须提供静态帧，动态资源按需加载，加载失败自动回退；
- 个人主页背景需要有内容安全区：姓名、称号、段位、统计数字和操作按钮所在区域不能被高对比粒子遮住；
- 资料页背景和全局应用背景要区分：资料页允许完整展示，战斗页面只应用低透明度主题层，棋盘与落子信息优先；
- 初期建议采用 CSS/SVG/少量 Canvas 粒子，未来再考虑视频背景；如果引入媒体资源，保留 2MB 头像框和 4MB 资料背景的预算线。

### Discord：装饰、资料特效、预览和付费分层

- [Discord 官方：Custom Profiles](https://support.discord.com/hc/en-us/articles/4403147417623-Custom-Profiles)
- [Discord 官方：Profile Effects](https://support.discord.com/hc/en-us/articles/17828465914263-Profile-Effects)

Discord 的资料编辑器把不同的个性化内容分开：

- 用户可以上传头像；动画 GIF 头像属于更高等级能力；
- Avatar Decoration 是头像周围的装饰，购买后加入收藏，可在 Profiles > Change Decoration 中应用；
- Profile Effect 是查看个人资料时播放的动画，购买后加入收藏，可预览、Apply、Save；
- Banner 支持上传、裁剪、预览和保存；
- Profile Theme 允许选择主色和强调色，并在保存前预览；
- Profile Effects 页面明确支持购买、收藏、应用和持久使用；Reduced Motion 设置可以阻止资料特效和其他用户特效播放；
- Discord 还支持按服务器使用不同的个人资料效果，说明“同一用户在不同展示场景拥有不同装饰配置”是成熟做法。

对 Battle_ship 的直接启发：

- “编辑名片”要成为所有装饰的统一入口，至少提供实时预览、拥有/未拥有、装备中、获取方式和保存/取消；
- 头像框和头图是持续装饰，入场特效是查看资料时触发一次，指针特效是用户自己的本地反馈，三者不要混成一个大动画；
- 付费或通行证豪华版可以解锁效果收藏权，但普通用户必须看到合理的默认效果和静态回退；
- 未来可按模式或活动使用不同主题，例如竞技场、好友对局、赛季大厅分别保存一个 profile_preset；
- 应用内要提供“完整动效 / 交互时播放 / 静态模式”，并尊重系统 prefers-reduced-motion。

### Overwatch 2：称号、边框和展示时机

- [Blizzard 官方：Defense Matrix](https://news.blizzard.com/en-us/article/23857517/defense-matrix-activated-fortifying-gameplay-integrity-and-positivity-in-overwatch-2)
- [Blizzard 官方：Show Off Your Playstyle with the New Player Progression System](https://news.blizzard.com/en-gb/article/23991794/show-off-your-playstyle-with-the-new-player-progression-system)
- [Blizzard 官方：Weekly Recall — Gaining Progress](https://news.blizzard.com/en-gb/article/24224138/weekly-recall-gaining-progress)
- [Blizzard 官方：Rebel Against the Ordinary in Overwatch 2 – Season 14](https://news.blizzard.com/en-us/article/24162755/rebel-against-the-ordinary-in-overwatch-2-season-14)

Overwatch 2 使用可自定义的 Name Card 和 Title 与玩家图标并列显示，同时把英雄/模式进度转成徽章、边框、Name Card 和 Title。较新的进度页面把奖励集中到易导航的奖励列表中，获得后的 Name Card 和 Title 可以单击装备。部分高阶内容随英雄进度或 Battle Pass Prestige 解锁。

对 Battle_ship 的直接启发：

- 称号应至少有三个展示层：个人主页完整展示、房间/大厅简化展示、战斗 HUD 极简展示；
- 战斗开始前不要把可能引发判断的竞技等级和全部高级信息堆在队伍列表里；可以先显示玩家选择的称号和低成本边框，详情在点击名片后查看；
- 高稀有称号可使用持续但克制的微动效，例如 6–10 秒一次的渐变高光扫过、非常慢的色相漂移、徽章边框的呼吸光；
- 称号文字本身必须稳定、清晰，动效只放在边框、下划线、徽章和高光层。不能用持续快速闪烁来表达稀有度；
- 进度驱动的称号比单纯购买更有身份感。建议设置“赛季、连胜、探索、收藏、竞技、活动”来源，并在拥有详情里显示获取条件。

### League of Legends：称号、Token、卡片多面展示和实时预览

- [League 官方：Challenges Walkthrough](https://www.leagueoflegends.com/en-us/news/game-updates/challenges-walkthrough/)

League 将称号、Challenge Token 和 Challenge Crystal 放入 Identity/玩家卡体系：

- 玩家可以从已经解锁的称号中自由选择；
- 最多可装备多个 Token，在大厅和加载屏展示；
- 悬停 Token 或 Challenge Card 可以查看对应挑战和等级；
- 加载屏玩家卡分成多面，分别承载比赛信息、英雄信息和玩家进度；
- 官方还提出 Banner Skins，用更突出的方式展示历史段位；
- Challenge Card 直接展示当前等级、条件和下一阶段主要奖励。

对 Battle_ship 的直接启发：

- 称号选择器要显示来源、稀有度、当前等级和下一阶段奖励，避免只有一个小文本标签；
- 可把一个“主称号”与两个“勋章/标签”组合，主称号负责身份表达，标签负责战绩或偏好；
- 个人主页可以用卡片、徽章、统计、历史记录四个区块，局内只保留主称号和一个边框；
- 编辑时实时预览，取消恢复原装备，保存一次提交最终组合；
- 称号的高级动效适合放在主称号边框和徽章，不要让三枚 Token 同时闪烁。

### Fortnite：可编辑 Banner 的简化场景

- [Epic 官方文档：Fortnite Banner](https://dev.epicgames.com/documentation/fortnite/banner?lang=en-US)

Epic 文档把玩家 Banner 定义为“图标 + 有色背景”，并说明它可以在 Locker 中配置，且会在匹配大厅展示。

对 Battle_ship 的直接启发：

- 低复杂度的默认背景可以由颜色和图标组合生成，用户即使没有高级媒体资产也能拥有可识别的身份；
- Banner/头图不能只在个人主页出现，至少要在匹配大厅、准备阶段和玩家卡预览显示一份轻量版本；
- 这类轻量版本可以作为免费基础层，高级版本再增加动态背景、边框和入场效果。

## 全局鼠标拖动尾迹与点击/触控效果的设计

### 输入层

使用 Pointer Events 统一处理鼠标、笔和触摸：

- pointerdown：记录起点、生成点击/触控反馈，缓存 pointerId；
- pointermove：按采样间隔和距离阈值生成轨迹点；
- pointerup：结束轨迹并开始衰减；
- pointercancel、pointerleave、路由切换和页面失焦：清理活动指针；
- 多指同时操作时每个 pointerId 独立缓存，但全局视觉层限制同时活跃的指针数。

MDN 的 [Multi-touch interaction](https://developer.mozilla.org/en-US/docs/Web/API/Pointer_events/Multi-touch_interaction) 明确说明 Pointer Events 同时覆盖鼠标、笔和触摸，并展示了 pointerdown、pointermove、pointerup、pointercancel 的缓存与清理模型。对 Battle_ship 来说，不应该为手机另写一套 touchstart，否则容易产生重复波纹或滚动冲突。

### 作用域与层级

全局视觉层应该挂在应用 Shell，而不是某一个名片组件：

- 大厅、编辑名片和个人主页：完整轨迹和完整点击爆发；
- 局内战斗：低亮度短尾迹、短半径点击波纹，不遮挡棋盘网格和舰船；
- 加载、弹窗、上传裁剪：默认只保留点击反馈，暂时关闭尾迹；
- 后台标签页、页面不可见或性能降级：暂停新增粒子；
- 视觉节点全部 pointer-events: none，事件继续落到真实按钮和棋盘；
- 如果存在拖拽棋盘或滚动容器，必须通过事件目标和模式判断避免把业务拖拽误识别成装饰拖迹。

建议建立一个 PointerFxBus：

~~~ts
type PointerFxEvent =
  | { kind: 'trail'; pointerId: number; pointerType: 'mouse' | 'pen' | 'touch'; x: number; y: number; speed: number }
  | { kind: 'burst'; pointerId: number; pointerType: 'mouse' | 'pen' | 'touch'; x: number; y: number; pressure?: number }
~~~

业务层只发布事件，渲染层根据当前装备的 trail_theme、burst_theme 和 motion_tier 选择效果。

### 鼠标拖动尾迹

- 仅在 buttons !== 0 且 pointerType 为 mouse/pen 时默认启用；
- 采样间隔建议 24–40ms，移动距离不足 6–10px 不生成新点；
- 采用环形缓冲区，最多保留 16–24 个点，按时间和速度衰减；
- 使用 transform、opacity 和合成层，避免每个点改变布局；
- 战斗内颜色透明度建议为名片预览的 35%–55%，寿命 220–420ms；
- 高级效果通过形状、色带、残影方向、粒子尾端和低频音画提示体现，不单纯增加点数；
- 用户松开按钮、切换窗口或取消拖拽时立即收束，不留下长线。

### 手机点击和触控

- 轻触只生成一次波纹或短促四粒子爆发；
- 只有移动距离超过 touch slop 才进入拖迹状态，避免滚动名片和棋盘时到处飘粒子；
- pointercancel 立刻清理，不把取消操作误判成完成点击；
- 触控目标尺寸和业务命中区不受视觉层影响；
- 高级点击特效可以使用不同的环形纹理、扇形扫描、星尘爆发或主题色，但默认每次只发一个主波纹，避免连点时铺满屏幕；
- 与 touch-action 的设置一起验证滚动和棋盘操作，不能为了特效阻止正常滚动。

### 可选效果目录

建议先提供 4 个互相差异明显的可选效果，每个效果都有静态回退：

| ID | 名称 | 尾迹 | 点击/触控 | 建议获取 |
| --- | --- | --- | --- | --- |
| pointer_default | 航迹微光 | 青蓝短线 | 小型圆环 | 默认 |
| pointer_sonar | 声呐扫描 | 细粒度扫描线 | 同心波纹 | 赛季通行证 |
| pointer_nebula | 星云残响 | 紫蓝粒子带 | 星尘爆发 | 豪华版/商店 |
| pointer_crown | 王冠指令 | 金色双轨残影 | 菱形徽记爆发 | 稀有成就/高阶套装 |

每项数据至少包含：

~~~ts
type PointerFxDefinition = {
  id: string;
  rarity: 'free' | 'pass' | 'premium' | 'event' | 'achievement';
  staticFallback: string;
  trailTheme: string;
  burstTheme: string;
  motionTier: 'subtle' | 'standard' | 'spectacle';
  maxParticles: number;
  lifetimeMs: number;
  reducedMotion: 'static' | 'tap-only';
};
~~~

所有权判断在服务端完成；客户端只收到可装备的 ID 和效果配置。测试账号的全解锁属于开发/预览能力，不应绕过正式接口的所有权判断。

## 头像框、头图背景和个人资料整体背景

### 头像框

头像框要和头像本体分层渲染：

1. 头像图片；
2. 静态边框底；
3. 动态光晕/轨道；
4. 稀有装饰物；
5. 头像右下角状态标记。

列表和战斗只渲染第 2 层或第 2+3 层的低成本版本。个人主页再加载完整的轨道、粒子和入场效果。动态资源必须有静态 PNG/SVG 回退。

### 头图与整体个人主页背景

当前“选择主题却没有实际变化”的问题，说明主题选择和渲染应用之间需要明确的数据流：

1. 编辑器选择 profile_background_id；
2. 本地预览立即将 data-profile-bg 或 CSS 变量设置到个人主页容器；
3. 保存后提交到服务端；
4. 个人主页和刷新后的应用 Shell 根据服务端值重新应用；
5. 资源不存在时回退 default，并保留用户的选择状态提示；
6. 主题必须区分“个人主页背景”和“全局应用背景”：前者可完整展示，后者只作为低透明度氛围层。

建议个人主页采用 Steam 式 5 色主题映射：

- surface：资料卡和内容面板；
- surfaceRaised：按钮、悬浮卡和统计区；
- accent：主按钮和选中态；
- accentSoft：边框、进度条和提示；
- textOnImage：头图上的高对比文字。

背景渲染需要固定内容安全区，动态层不能覆盖用户名、称号、统计和编辑按钮。主题切换要至少能在页面上看到背景图、渐变和面板色同时变化，而不是只替换一个小标签。

## 称号的动感表现

称号的动效应表达稀有度和状态，不能破坏文字阅读：

- 普通称号：静态文字 + 低对比边框；
- 精良称号：边框每 8–12 秒一次高光扫过；
- 史诗称号：渐变文字或下划线轻微呼吸，附带一次短粒子；
- 传说称号：进入名片时播放一次徽记展开，平时保持极慢的光晕循环；
- 战斗中只保留主称号文字和一个小徽记，避免多个玩家的动效叠加；
- prefers-reduced-motion 或应用静态模式下，保留颜色、图标、稀有度徽标和获取条件，去掉所有持续动画；
- 不能用高频全屏闪烁区分稀有度。Steam 官方明确禁止频闪和闪烁，Discord 也提供 Reduced Motion 关闭资料效果。

称号数据建议包含：

~~~ts
type TitleStyle = {
  id: string;
  rarity: 'free' | 'pass' | 'premium' | 'event' | 'achievement';
  label: string;
  icon?: string;
  gradient?: string;
  borderTheme?: string;
  motion: 'none' | 'shimmer' | 'breath' | 'entry-burst';
  sourceLabel: string;
  sourceDetail: string;
};
~~~

## 付费与通行证分层建议

参考 Steam 的 Points Shop、Discord Shop 和 Overwatch 进度系统，不要把“付费”直接映射成更亮的颜色：

- 免费：基础头像框、默认指针反馈、少量静态主题；
- 赛季通行证：一套主题色、赛季头图、称号和 pointer_sonar；
- 豪华版：更完整的动态头图、头像框、入场效果和 pointer_nebula；
- 商店单件：独立购买头像框、点击爆发、称号样式或个人资料背景；
- 成就/竞技：可验证的称号、徽记和边框，强调身份价值；
- 活动限定：在限定时间获得，永久保留，过期后仍可装备；
- 管理员/测试预览：只在开发环境打开全解锁，不混入正式用户的所有权结果。

所有商品都要提供：

- 预览；
- 稀有度；
- 获取方式；
- 已拥有/未拥有/已装备状态；
- 动效强度和 Reduced Motion 回退；
- 资源加载失败时的静态回退。

## 性能与无障碍验收线

- 全局特效只能有一个渲染层，不能每个组件各自监听 pointermove；
- 战斗中最多保留 16–24 个尾迹点和一个点击爆发，连续点击时覆盖旧爆发；
- 使用 transform、opacity、CSS variables 或单一 Canvas，避免频繁布局；
- 页面不可见、窗口失焦、低性能模式下暂停或降级；
- prefers-reduced-motion: reduce 下禁用尾迹、粒子、视差、连续旋转和称号 shimmer，保留点击的静态状态变化或一次极短波纹；
- 所有特效层 pointer-events: none，不得截获上传、编辑、棋盘、键盘焦点或滚动；
- 名称、称号、数字和按钮始终保持足够对比度；背景主题不得只依赖颜色表达状态；
- 支持键盘用户：点击特效不能成为唯一反馈，焦点环、文本提示和状态消息仍要存在；
- 手机触控不能因粒子层阻止滚动或误触；必须处理 pointercancel；
- 动态头像框目标不超过 2MB，资料背景视频目标不超过 4MB，并提供静态回退和小尺寸预览；
- 不在局内自动播放声音，不使用持续高频闪烁；
- 所有动态效果都应能在设置中关闭，关闭后当前页面立即停止新增粒子。

## 对本项目的执行顺序建议

1. **修复主题真正生效**：先确认 profile_background_id 的保存、读取、路由刷新和 CSS 应用链路，再扩展更多主题。
2. **抽离全局 PointerFxBus**：把当前名片局部的尾迹/点击逻辑迁移到应用 Shell，统一覆盖大厅、名片和战斗。
3. **补齐触控状态机**：引入 touch slop、pointercancel、失焦清理和多指上限；手机轻触只显示波纹。
4. **增加效果选择器**：编辑名片中新增“鼠标/触控特效”区块，实时预览并显示所有权、稀有度和获取方式。
5. **增强头像框和头图**：保持静态回退，增加轨道、光晕、扫描线和背景漂移，但在战斗中使用低成本档。
6. **重做称号展示**：支持主称号 + 勋章/标签，加入稀有度和低频 shimmer/entry-burst，个人主页完整展示、对局极简展示。
7. **最后做付费/通行证接入**：效果配置和所有权先数据驱动，后接商店或通行证，不要把解锁条件写死在组件里。

## 参考来源

- [Steamworks Points Shop Items](https://partner.steamgames.com/doc/marketing/pointsshopitems)
- [Discord Custom Profiles](https://support.discord.com/hc/en-us/articles/4403147417623-Custom-Profiles)
- [Discord Profile Effects](https://support.discord.com/hc/en-us/articles/17828465914263-Profile-Effects)
- [osu! Interface skinning](https://osu.ppy.sh/wiki/en/Skinning/Interface)
- [osu! Client options](https://osu.ppy.sh/wiki/en/Client/Options)
- [Blizzard Defense Matrix](https://news.blizzard.com/en-us/article/23857517/defense-matrix-activated-fortifying-gameplay-integrity-and-positivity-in-overwatch-2)
- [Blizzard Player Progression](https://news.blizzard.com/en-gb/article/23991794/show-off-your-playstyle-with-the-new-player-progression-system)
- [Blizzard Weekly Recall](https://news.blizzard.com/en-gb/article/24224138/weekly-recall-gaining-progress)
- [Blizzard Season 14](https://news.blizzard.com/en-us/article/24162755/rebel-against-the-ordinary-in-overwatch-2-season-14)
- [League Challenges Walkthrough](https://www.leagueoflegends.com/en-us/news/game-updates/challenges-walkthrough/)
- [Epic Fortnite Banner](https://dev.epicgames.com/documentation/fortnite/banner?lang=en-US)
- [MDN Multi-touch interaction](https://developer.mozilla.org/en-US/docs/Web/API/Pointer_events/Multi-touch_interaction)

## 调研判断

成熟产品的共性不是“动画越多越高级”，而是：

- 输入反馈与业务逻辑分离；
- 头像框、背景、称号、入场效果和指针效果按槽位组合；
- 个人资料里展示完整动态，对局中展示低成本版本；
- 预览、所有权、装备和保存状态清楚分开；
- 高稀有度通过主题完整度、获取难度、展示时机和独有形态体现；
- 所有动态都提供静态回退和 Reduced Motion。

Battle_ship 适合采用 osu! 的光标尾迹/波纹拆分、Steam 的资料资产和预算、Discord 的装饰/资料特效/购买/预览模型、Overwatch 2 的进度称号和展示时机、League 的多面玩家卡和实时编辑预览。这样可以把全局战斗内特效做成真正可装备的个性化内容，同时保持棋盘操作、可读性和移动端体验稳定。
