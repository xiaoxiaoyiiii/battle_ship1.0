# P1 个性化名片动效与交互特效深度调研（2026-10-30）

本轮针对 Battle_ship 的 P1 方向重新核对仍在运营的成熟产品和官方设计规范，重点看：动态头像框、个人主页背景/头图、进入主页时的动效、鼠标拖动轨迹、鼠标点击或手机触控反馈、装饰的获取与付费分层，以及性能和无障碍边界。本文件只记录调研和可执行结论，不改业务代码，也不包含测试文件。

## 结论先行

Battle_ship 现在需要把“头像框动效”和“名片进入时的资料页特效”拆成两类资源，再增加一个受控的交互反馈层：

1. **头像框**负责持续但克制的外圈动效，例如呼吸光、环绕粒子、短促的高光扫过。它可以在列表和对局中显示低成本版本，进入个人名片时再显示完整版本。
2. **头图主题/个人主页背景**负责空间感和主题氛围，适合使用缓慢渐变、视差、扫描线、雾尘或星屑。背景必须让姓名、称号、统计数字和按钮保持清晰。
3. **进入名片的资料页特效**只在打开名片或切换到名片路由时播放一次，时长控制在约 450–900ms，不能变成持续遮挡内容的全屏动画。
4. **鼠标拖动轨迹和点击/触控反馈**应作为名片场景的可选交互层。拖动使用短尾迹和速度衰减，点击使用局部波纹/环形爆发；同一套 Pointer Events 同时覆盖鼠标、触摸和笔，不能只实现 `mousemove`。
5. **高稀有度不等于更大、更亮、更快**。付费级或难获得装饰应通过更细致的主题组合、独特的入场效果和更高质量的循环动画体现，而不是靠无限叠加粒子。所有高级效果都要有静态帧、低动态和关闭动效的回退。

## 一手资料与核实结果

### Steam Points Shop / Steamworks

- [Steamworks 官方：Points Shop Items](https://partner.steamgames.com/doc/marketing/pointsshopitems?l=turkish&language=english)
- [Steam 官方 Points Shop](https://store.steampowered.com/points/shop/)
- [Steam 官方 2026 inKONBINI Points Shop 公告](https://store.steampowered.com/news/posts/?appids=221100%2C224580%2C107410%2C33900%2C33930%2C65735%2C65734%2C224860%2C65790%2C65780%2C244030%2C33970%2C5794%2C5728%2C80673%2C80670%2C80671%2C80676%2C80672%2C80674%2C65740%2C80439%2C80433%2C80430%2C80432&enddate=1784998850&feed=steam_community_announcements)

官方把头像框、头像、个人资料背景、迷你资料背景、动画贴纸和 Game Profile 分开建模。头像框建议使用循环 APNG，224×224 且小于 2MB，同时提供静态 PNG；动画头像建议小于 2MB；资料背景使用循环 MP4/WebM，完整资源小于 4MB，并且提供小于 1MB 的预览版本和静态 JPG。迷你资料背景只在悬停等更小场景出现，也要求循环且小于 4MB。

Steam 的 Game Profile 是一套组合式商品：动画头像、头像框、动画迷你背景、动画资料背景，再配五个 RGBA 主题色。官方要求主题色不能破坏文字可读性，并建议背景底部自然淡入黑色。官方规则还明确要求避免频闪和闪烁，所有商品都要有合适的空间裁切和静态预览。

这说明 Battle_ship 应把“框、头图、入场效果、交互效果”作为可组合的槽位，同时每个槽位都保存静态回退和预览图。高价套装可以提供一套协调颜色和动效，但仍允许用户单独装备其中某一件。

### Discord：Profile Effects、Avatar Decorations、Banner 和 Reduced Motion

- [Discord 官方：Profile Effects](https://support.discord.com/hc/en-us/articles/17828465914263-Profile-Effects)
- [Discord 官方：Custom Profiles](https://support.discord.com/hc/en-us/articles/4403147417623-Custom-Profiles)
- [Discord 官方：Reduced Motion Setting](https://support.discord.com/hc/en-us/articles/360040613412-Reduced-Motion-Setting)
- [Discord 官方：Accessibility Settings](https://support.discord.com/hc/en-us/articles/1500010454681-Accessibility-Settings-Tab)

Discord 将 Avatar Decoration 和 Profile Effect 明确区分：前者是头像周围的装饰，后者是在别人打开个人资料时播放的动态效果。Profile Effect 可以在 Shop 中预览、购买并加入收藏，应用时要经过 Apply 和 Save；购买的效果可以长期保留，Nitro 用户获得会员价，Nitro 专属物品在取消订阅后仍保留在收藏但不能使用。官方还支持按服务器 profile 使用不同效果。

Discord 的上传路径包含头像、GIF、Banner、裁剪、预览和保存；Banner 对 PNG/JPG/GIF、10MB 上限和最小尺寸有明确约束。它把“上传内容”和“装饰内容”分开，便于给用户清楚的选择和回退。

Discord 的 Reduced Motion 会限制或关闭页面背景、GIF 头像、菜单和资料效果的动画，并提供“始终播放、交互时播放、从不播放”等分级控制。对 Battle_ship 来说，资料页特效必须默认只触发一次；用户可以在设置中选择完整动效、交互时动效或静态模式。

### Overwatch 2：进度驱动的边框、卡片和显示时机

- [Overwatch 官方：Show Off Your Playstyle with the New Player Progression System](https://overwatch.blizzard.com/en-us/news/23991794/)
- [Blizzard 官方：Weekly Recall — Gaining Progress](https://news.blizzard.com/en-gb/article/24224138/weekly-recall-gaining-progress)
- [Blizzard 官方：Defense Matrix](https://news.blizzard.com/en-us/article/23857517/defense-matrix-activated-fortifying-gameplay-integrity-and-positivity-in-overwatch-2)

Overwatch 2 把玩家图标、Name Card、Title、徽章和英雄进度放到 Career Profile 及玩家卡片中；Progression 2.0 让英雄特定的边框和徽章随游玩进度获得，并且在队友选择阶段、击杀回放等关键展示点出现。官方说明高阶边框会为队友“闪烁/ shimmer”，但敌方不会在比赛刚开始就看到全部卡片和边框，存在展示时机和隐私边界。

这提供了两个适合 Battle_ship 的模式：

- 低成本展示：房间列表、对局 HUD 只展示静态边框或一次短高光；
- 高价值展示：打开个人名片后播放入场效果，显示称号、主题和进度徽章；隐私设置可以关闭他人查看或延迟展示。

Overwatch 还把前 20 级进度设计成较容易获得的起步奖励，把高阶内容放到持续进度和更高稀有度。Battle_ship 可以用“基础、精良、史诗、传说”四层做可读的获取路径，而不是所有项目都简单标记为锁定。

### League of Legends：实时预览、撤销、筛选与多面玩家卡

- [League 官方：Challenges coming to PBE](https://www.leagueoflegends.com/en-gb/news/game-updates/challenges-coming-to-pbe/)
- [Riot 官方：Ask Riot — Loading Screen Chat](https://nexus.leagueoflegends.com/en-pl/2019/03/ask-riot-loading-screen-chat/)

League 的 Identity 菜单把 Icons、Borders、Titles、Challenge Tokens 等内容统一到一个选择器中。官方设计说明：左侧实时预览名片；切换选项立即更新，不需要每次保存，并提供 Undo；图标选择器支持稀有度、提示、过滤和搜索。玩家卡在加载画面有多面信息，可以在不同场景展示不同侧面。

Battle_ship 的名片编辑器应该沿用这个“所见即所得”：改变框、头图主题、称号或入场效果时立即更新预览；保存只提交最终组合，取消则回到原装备。装饰目录需要显示稀有度、获取条件和筛选，不把所有内容挤成小卡片。

## 鼠标轨迹与点击/触控特效的落地边界

### 输入模型

- [MDN 官方：Multi-touch interaction / Pointer Events](https://developer.mozilla.org/en-US/docs/Web/API/Pointer_events/Multi-touch_interaction)
- [Android Developers 官方：Track touch and pointer movements](https://developer.android.com/develop/ui/views/touch-and-input/gestures/movement)
- [Apple HIG：Gestures](https://developer.apple.com/design/human-interface-guidelines/gestures)

Pointer Events 可以用同一套 `pointerdown`、`pointermove`、`pointerup`、`pointercancel` 处理鼠标、触摸和笔；MDN 示例还说明了多指状态缓存和 `touch-action` 的边界。Android 官方建议使用移动距离（touch slop）区分轻触和拖动，并利用历史位置与速度渲染触控轨迹。Apple 要求手势反馈紧跟手势、短促准确，并允许用户取消或退出动画。

### Battle_ship P1 建议效果

1. **名片作用域轨迹**：只在个人名片的 hero/装饰预览层启用，不覆盖整个应用。每 16–32ms 采样一次，距离不足 8px 不新增节点；最多保留约 18–24 个轨迹点，按速度和时间衰减。使用 `transform`、`opacity` 和合成层，不触发布局。
2. **点击/触控波纹**：`pointerdown` 在触点处生成 1 个环形波纹、2–4 个短粒子和一次颜色脉冲；`pointerup` 让波纹收束或淡出。触摸、鼠标、笔共用事件模型，避免为移动端另写一套 `touchstart`。
3. **拖动与点击的区分**：短距离轻触只播放波纹；超过 touch slop 后才启用尾迹。拖动结束时不保留长线，避免用户滚动名片时整页铺满粒子。
4. **进入名片动效**：只在路由进入或从列表打开名片时播放一次，建议为 450–900ms 的遮罩揭示、头像框点亮、头图渐入和标题轻微上移；返回或刷新不重复堆叠。
5. **高级装饰的差异化**：史诗以上增加独有的轨迹颜色、点击爆发形状、入场音画提示或低频环绕粒子；不要同时叠加多个全屏粒子系统。装饰数据中要定义 `static_fallback`、`motion_tier`、`trail_theme`、`click_burst` 和 `entry_effect`，缺失时回退到静态框。
6. **展示时机**：列表/HUD 使用静态帧；打开个人名片后加载完整头图和资料页效果；离开页面、标签页不可见或滚出视口时暂停循环视频/粒子。

## 性能、可读性与无障碍验收线

- [W3C 官方：Media Queries Level 5 — `prefers-reduced-motion`](https://www.w3.org/TR/mediaqueries-5/)
- [W3C WAI 官方：Technique C39](https://www.w3.org/WAI/WCAG22/Techniques/css/C39)
- [Apple HIG：Motion](https://developer.apple.com/design/human-interface-guidelines/motion)
- [Apple HIG：Feedback](https://developer.apple.com/design/human-interface-guidelines/feedback)

W3C 标准提供 `prefers-reduced-motion: reduce`，WAI 建议把交互触发的动画在该模式下禁用或替换。Apple 建议动画服务于反馈和层次，不要为了“看起来炫”而持续移动；频繁交互应短、准、可取消，并提供文字、颜色、音频或触觉之外的替代反馈。

P1 必须满足：

- `prefers-reduced-motion` 下关闭轨迹、粒子、视差、连续旋转和入场大位移动画，保留静态边框、清晰文字和状态提示；
- 提供应用内“完整动效 / 交互时播放 / 静态模式”开关，并尊重系统设置；
- 姓名、称号、统计数字、按钮与背景保持足够对比度，主题颜色不能压住内容；
- 普通名片初始渲染不等待大资源，头像框静态帧可立即显示；动态资源按需加载并可取消；
- 单个头像框动画目标不超过 2MB，单个完整头图视频目标不超过 4MB，并提供预览图和静态回退；
- 轨迹和点击特效只允许 `pointer-events: none` 的视觉层，不能拦截头像上传、按钮和键盘焦点；
- 进入效果必须能被 Escape、返回和路由切换打断，不得阻塞操作；
- 移动端按钮和触控区域不能因粒子层变小，拖动名片时不误触发装饰选择。

## P1 执行顺序与验收标准

### P1-A：装饰效果模型和资料页展示层

先把当前 `frame_id`、`card_bg_id` 的 CSS 动效抽象成数据驱动的效果配置，至少支持静态帧、低频光晕、扫描线、轨道粒子、点击爆发和入场效果。列表/HUD 只用静态或低动版本，个人名片才启用完整层。验收时要能切换至少三种明显不同的高级主题，并检查加载失败回退。

### P1-B：Pointer 交互层

在名片作用域接入统一 Pointer Events：轻触显示波纹，拖动超过 touch slop 后显示短尾迹，多指或 `pointercancel` 时正确清理。验收要覆盖鼠标、触摸模拟、键盘操作和滚动，不允许轨迹层遮挡控件。

### P1-C：进入名片和实时预览

进入名片播放一次入场效果；编辑器预览实时反映头像框、头图主题、称号、标签和交互效果；取消撤销，保存一次提交。验收要确认低动效、静态模式、`prefers-reduced-motion` 和刷新后状态一致。

### P1-D：获取与稀有度

为高阶装饰增加可读的稀有度、获取方式、预览和已拥有/已装备状态。测试账号可以继续使用全解锁开关，但普通账号必须由后端所有权决定可用性。高级套装可以组合头像框、头图、称号和入场效果，同时允许单件替换。

## 本轮不建议立即做的事情

- 不把用户鼠标轨迹持久化或上传服务器；它属于本地即时反馈。
- 不为每个头像框引入独立 WebGL 场景；P1 先用 CSS、SVG、少量 Canvas 或循环媒体完成可控效果。
- 不让高级效果自动播放声音、强制全屏闪烁或持续强对比旋转；这些既损害可读性，也会触发无障碍和性能风险。
- 不把“付费”直接等同于“永远更亮”。稀有度需要对应主题完整度、获取难度、收藏价值和展示场景，而不是单纯增加粒子数量。

## 调研判断

成熟产品的共同做法是“组合式槽位 + 资料页专属动效 + 预览/收藏/装备分离 + 明确的静态回退”。Battle_ship 最适合采用 Steam 的资产预算和套装思路、Discord 的 Profile Effect 触发时机与 Reduced Motion、Overwatch 2 的进度稀有度、League 的实时预览和撤销，再用 Pointer Events 统一实现鼠标和触控反馈。这样能让高级装饰更有吸引力，同时不会把普通对局和移动端变成高耗能的动画墙。
