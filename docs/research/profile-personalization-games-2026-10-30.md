# 头像、头像框与高级个性化装饰调研（2026-10-30）

本轮针对 Battle_ship 的“头像上传、头像框显示、动态效果和高级装饰获取方式”调研成熟项目与游戏的一手资料。优先使用官方产品说明、官方开发文档、官方 API 文档和官方源码；未把社区攻略当作产品规则依据。

## 结论先行

成熟产品通常把个性化拆成四层：

1. **头像本体**：玩家上传自己的图片，必要时裁剪、压缩、生成多尺寸缩略图，并提供替换、删除和可选的替代文本。
2. **装饰叠层**：头像框、光环、徽章和粒子效果作为独立资源叠在头像外面，不能把头像裁剪逻辑和装饰资源绑死。
3. **展示场景**：普通列表使用静态或低成本版本；打开个人资料时才播放较完整的动态效果；高级背景、入场动画和终结效果可以独立于头像框装备。
4. **收藏与获取**：收藏、装备、预览、购买或解锁是不同状态。稀有装饰需要清楚的获取路径、轮换时间和保底规则，不能只显示“锁定”。

因此，Battle_ship 的下一步应优先完成“真实头像上传 + 头像框独立叠层渲染”，再增加动态效果。高级效果必须同时设计静态回退、降低动态开关和资源预算，避免名片变成高耗能、低可读性的动画墙。

## 1. Discord：头像上传、头像装饰、个人资料动态效果

### 一手资料

- [Discord 官方：Custom Profiles](https://support.discord.com/hc/en-us/articles/4403147417623-Custom-Profiles)
- [Discord 官方：Avatar Decorations FAQ](https://support.discord.com/hc/en-us/articles/13410113109911-Avatar-Decorations-FAQ)

### 可核实的产品模式

- 用户可以上传自己的头像；普通头像支持 PNG，Nitro 用户还可以使用 GIF。Discord 将头像选择、应用和保存拆成明确步骤，并保留 Recent Avatars 供再次使用。
- 上传后的图片可以裁剪；Profile Banner 还会显示尺寸和大小约束，官方说明为 PNG/JPG/动图 GIF，最大 10MB，最低 680×240 像素。
- Avatar Decoration 是独立的头像装饰收藏。用户在 Shop 中预览和购买，装饰进入收藏后可以随时装备；“Apply”和“Save Changes”是两个明确状态。
- Profile Effect 是另一类装饰，不等同于头像框。官方将它描述为“当别人查看 profile 时播放的动画效果”，因此动态效果发生在资料页场景，而不是所有头像小卡片中。
- 装饰可以按服务器 profile 分开装备；同一账号在不同服务器可使用不同装饰。购买后的装饰通常永久保留，Nitro 专属装饰则可以保留在收藏中但需要有效订阅才能使用。
- Shop 会周期性更换商品；存在 bundle、会员价、地区定价和“已拥有部分商品不能重复购买 bundle”等库存语义。

### 对 Battle_ship 的启示

1. 上传入口要直接放在“编辑名片 > 头像”，而不是只留在设置页。
2. 头像框只处理外圈资源；“资料打开时的动态效果”单独建模，避免把一张 GIF 同时当头像、头像框和全屏特效。
3. 选择器需要展示“预览、已拥有、已装备、解锁方式、是否需要订阅/活动资格”这几种不同状态。
4. 普通列表可使用静态帧；进入个人名片后再播放高级效果，既能展示稀有度，也能控制性能。

## 2. Steam Points Shop：动画资源规格、组合式套装与可读性边界

### 一手资料

- [Steamworks 官方：Points Shop Items](https://partner.steamgames.com/doc/marketing/pointsshopitems?l=turkish&language=english)

### 可核实的产品模式

- Steam 把头像框、头像、个人资料背景、迷你资料背景、贴纸和 Game Profile 作为互相独立的商品类型。
- Animated Avatar Frame 的官方建议规格为 224×224 APNG，大小小于 2MB；同时提供 224×224 静态 PNG 版本。
- Animated Avatar 的官方建议规格为 184×184 GIF，小于 2MB；静态版本建议 184×184 JPG，小于 300KB。
- Animated Profile Background 使用循环 MP4/WebM；完整背景小于 4MB，预览版本小于 1MB。迷你资料背景同样要求循环并小于 4MB。
- Game Profile 将“动画头像 + 头像框 + 动画迷你背景 + 动画资料背景”打成主题套装，并额外要求配置五个 RGBA 主题色。官方明确要求主题色不能破坏文字可读性。
- Steam 的审核规则明确禁止会产生闪烁、频闪风险的画面；官方还建议背景在底部自然淡入黑色，以免与资料内容断开。
- Points Shop 的商品通常通过 Steam Points 获取，商品来自游戏方，目的同时包括玩家展示和游戏曝光。活动可以设置 Available From 时间，等待 DLC 或活动开始后才显示。

### 对 Battle_ship 的启示

1. **头像框要有硬预算**：可以把 APNG 等价物控制在 2MB 内，把更大的 MP4/WebM 背景控制在 4MB 内；超出预算的资源不能直接进入正式商品池。
2. **每个动态资源必须有静态帧**：静态帧用于列表、低带宽、加载失败和降低动态场景。
3. **高级效果应按场景加载**：头像框和头像常驻，资料页背景和粒子效果在进入名片后加载；滚出视口就暂停。
4. **主题色要由内容方提供但受可读性约束**：装饰预览必须检查名字、段位、统计数字和按钮的对比度。
5. **套装比堆叠单品更容易形成付费级体验**：可以把“头像框 + 头图主题 + 称号 + 入场特效”作为一个主题收藏，但仍允许单独装备。

## 3. Roblox：库存所有权、商城筛选与装备保存

### 一手资料

- [Roblox 官方：Marketplace overview](https://create.roblox.com/docs/marketplace)
- [Roblox 官方：Avatar Editor Service](https://create.roblox.com/docs/players/avatar-editor)
- [Roblox 官方：Avatar items](https://create.roblox.com/docs/production/monetization/avatar-items)

### 可核实的产品模式

- Marketplace 是全局头像物品商店，覆盖身体、头部、服装、配饰、动画等类型；开发者可以在自己的游戏内接入 Avatar Editor Service。
- Avatar Editor Service 先请求用户授权读取库存，再读取用户拥有的物品；商城搜索支持资源类型、关键词、最低/最高价格、排序、是否包含下架物品、创建者等筛选。
- 用户可以在游戏内试穿、装备并保存 outfit；服务也可以弹出购买提示。官方明确说明：保存头像或 outfit 时，用户不会因为配置里出现未拥有的目录物品而自动获得它们。
- Marketplace 的资产发布还受技术标准、社区规则、知识产权和审核流程约束；商品收益按资产类型和定价规则分成。

### 对 Battle_ship 的启示

1. 所有权必须是后端权威状态，前端的“测试账号全解锁”只能是测试权限，不应被当作普通用户拥有。
2. 商品筛选要支持“已拥有、未拥有、稀有度、获取方式、活动时间、价格/成本”而不只是四个标签页。
3. “预览”与“装备”分开；用户可以试穿高级装饰，但保存时必须再次校验所有权和有效期。
4. 装饰资源要经过尺寸、格式、透明通道和内容审核，不能让用户通过任意 URL 注入外部图片或脚本。

## 4. Mastodon：头像上传的裁剪、替代文本和独立 profile API

### 一手资料

- [Mastodon 官方产品设计：A Redesign for Profiles](https://github.com/mastodon/blog/blob/master/content/posts/2026-03-26_a_redesign_for_profiles/index.md)
- [Mastodon 官方开发说明：Mastodon 4.6 for developers](https://github.com/mastodon/blog/blob/master/content/posts/2026-06-12_Mastodon-4.6-for-developers/index.md)
- [Mastodon 官方 API：accounts methods](https://docs.joinmastodon.org/methods/accounts/)
- [Mastodon 官方源码：英文文案与上传提示](https://github.com/mastodon/mastodon/blob/main/app/javascript/mastodon/locales/en.json)
- [Mastodon 官方源码：Account 模型](https://github.com/mastodon/mastodon/blob/main/app/models/account.rb)

### 可核实的产品模式

- Mastodon 4.6 把 `Edit profile` 直接放到自己的公开 profile，降低从浏览到编辑的路径成本。
- 头像和 header 上传都提供裁剪；上传流程分为选图、缩放/裁剪、预览和填写 alt text。官方将头像描述和 header 描述作为无障碍字段保存。
- `PATCH /api/v1/accounts/update_credentials` 使用 `multipart/form-data` 接收 `avatar` 和 `header`；同一接口还接收 `avatar_description` 和 `header_description`。
- Mastodon 4.6 增加了独立的 `GET/PATCH /api/v1/profile`，返回原始文本字段和格式化字段，便于客户端填充编辑器，避免从 HTML 反解析输入内容。
- Account 数据模型保存 `avatar_content_type`、文件名、文件大小、更新时间、描述和 header 的对应字段，说明图片资料不是只存一个 URL。
- 官方源码中的上传提示明确区分 WEBP、PNG、GIF、JPG、最大文件大小以及服务器缩放后的尺寸；这类限制会从实例配置读取，而不是让客户端永久写死。

### 对 Battle_ship 的启示

1. 头像 API 应采用 `multipart/form-data`，而不是只提交外部 URL。
2. 数据库至少保存头像 URL、静态缩略图 URL、内容类型、文件大小、宽高、更新时间和可选 alt text。
3. 上传流程建议为“选择文件 → 裁剪/缩放 → 预览 → 保存”；保存失败时保留草稿，不要把本地预览当成已上传。
4. 服务端应从实际文件头判断 MIME，限制尺寸和字节数，生成固定尺寸缩略图并清理 EXIF；前端限制只是体验层，不是安全边界。
5. 头像与头图的描述字段应该在 UI 中可见，尤其是玩家自定义图片可能被读屏用户看到。

## 5. Overwatch 2：用进度和成就驱动名片装饰

### 一手资料

- [Overwatch 官方：Player Progression System](https://overwatch.blizzard.com/en-us/news/23991794/)
- [Overwatch 官方：Invasion 与玩家进度](https://overwatch.blizzard.com/en-us/news/23989473/)
- [暴雪官方新闻：Defense Matrix](https://news.blizzard.com/en-us/article/23857517/defense-matrix-activated-fortifying-gameplay-integrity-and-positivity-in-overwatch-2)

### 可核实的产品模式

- 玩家进度按英雄、职责和游戏模式分别统计，并通过 badge/sub-badge 升级。
- 进度升级会解锁 Player Icons、Name Cards 和 Titles；这些内容和玩家头像、BattleTag 一起出现在多个展示位置。
- 竞争模式还提供随段位获得的限定称号；系统把高价值展示内容绑定到可验证的游戏行为，而不是全部依赖付费。
- 暴雪还说明过，过度展示玩家等级可能导致比赛前的先入为主，因此移除会直接暴露等级的 Portrait Borders，改用玩家主动选择的 Name Cards 和 Titles。

### 对 Battle_ship 的启示

1. 高级装饰不必全部卖钱；胜场、连胜、赛季、英雄/战舰专精、赛事和贡献行为都可以产生稀有称号或边框。
2. 让装饰表达“玩家做过什么”，比单纯显示价格更有身份感。
3. 头像框、称号和头图的视觉层级应允许玩家主动选择，不要用动画或颜色直接泄露胜负、隐藏分等敏感信息。

## 6. League of Legends：稀有度、轮换商店、活动通行证和保底

### 一手资料

- [League 官方：Skins 101](https://www.leagueoflegends.com/en-gb/news/dev/skins-101/)
- [League 官方：The Mythic Content Overhaul](https://www.leagueoflegends.com/en-au/news/dev/the-mythic-content-overhaul/)
- [League 官方：Exalted Skins、Mythic Shop 与 Nexus Finishers](https://www.leagueoflegends.com/en-gb/news/game-updates/dev-exalted-skins-the-mythic-shop-and-nexus-finishers/)
- [League 官方：Patch 12.6 notes](https://www.leagueoflegends.com/en-gb/news/game-updates/patch-12-6-notes/)

### 可核实的产品模式

- 官方把皮肤按 Epic、Legendary、Ultimate、Mythic 等层级区分，每个层级对应不同内容量和功能；获取方式也分为商店直购、碎片合成、战斗通行证、Mythic Shop、限定活动和成就奖励。
- Mythic Shop 采用轮换，新的 Mythic 内容在 debut 阶段使用较低成本，之后返场提高成本；官方说明轮换和返场时间，给收藏者稀缺感，同时保留再次获得的机会。
- Event Pass 将免费轨和付费轨分开，玩家通过任务、XP 和里程碑推进。Prestige 皮肤可以作为付费通行证的高级终点，而不是一开始就把所有装饰锁在商城。
- Exalted 皮肤的 Sanctum 明确展示掉率、S/A/B 级奖励和 bad-luck protection；S 级内容有最多抽取次数，A 级也有自己的保底。系统检查已拥有物品，避免重复奖励；集齐后以货币补偿。
- Nexus Finisher 是独立于英雄皮肤的 VFX/SFX 终结效果，使用范围更广，且由比赛所有玩家看到。这是“高稀有展示效果”独立成系统的例子。
- 官方还明确说明，新内容在首次 debut 期间暂不进入 reroll，首发期间获得的边框和图标可以成为额外的限定权益；后续通过普通掉落获得时不一定带首发附属物。

### 对 Battle_ship 的启示

1. 付费级装饰要把“稀有度、首次获取窗口、返场规则、是否带首发附属物”写清楚。
2. 随机获取必须有可见概率、保底、重复保护和补偿；否则用户很难把它理解为公平的收藏系统。
3. 高级动态效果可以独立于头像框，例如“资料打开动画”“赛后胜利收束动画”，这样同一头像框可跨主题复用。
4. 需要区分“稀有”与“更亮更吵”。高稀有度可以通过独特构图、粒子层、音效、入场时机和收藏历史体现，不能只靠更强的闪烁。

## 7. 跨项目归纳：适合 Battle_ship 的设计原则

### 7.1 头像上传接口

建议接口语义：

```text
POST /api/profile/avatar
Content-Type: multipart/form-data
  file: image file
  crop: { x, y, width, height, scale }
  alt_text: optional string
```

服务端保存并返回：

```text
avatar_url
avatar_static_url
avatar_thumb_url
avatar_content_type
avatar_bytes
avatar_width / avatar_height
avatar_updated_at
avatar_alt
```

建议初始只接收 PNG/JPEG/WebP，待静态上传、缩略图和审核稳定后再考虑 GIF/APNG。GIF/APNG 会引入首帧、解码、缓存和降低动态开关等额外问题；Discord 的 GIF 头像也属于特定会员能力，不应默认把动态上传开放给所有账号。

上传流程必须有：

- 文件类型和魔数校验，不能只信 `Content-Type`。
- 最大字节数、最大宽高和最小可见尺寸限制。
- 服务端重新编码或生成缩略图，剥离不必要的 EXIF/元数据。
- 裁剪预览和保存后的真实回显；上传失败时保留草稿。
- `alt_text` 或图片描述的可选字段。
- 旧头像清理、缓存版本号和失败回滚。

### 7.2 头像框的渲染层

头像框建议拆成以下 DOM/CSS 层：

```text
.avatar-stack
  ├─ avatar-image       // 玩家上传的头像，object-fit: cover
  ├─ avatar-frame       // 透明 PNG/APNG/SVG，pointer-events: none
  ├─ avatar-aura        // 低频 CSS/Canvas 粒子或光晕
  └─ avatar-badge       // 状态/徽章，不和外圈资源共用裁剪
```

头像、头像框和动态光效要保持相同的容器尺寸与圆角规则；头像框必须位于头像之上，不能被头像的 `overflow: hidden` 或错误的 `z-index` 截断。列表、小卡片和公开名片使用同一组件，但根据场景切换 `density` 与 `motion`。

### 7.3 动态效果分级

建议采用四档，而不是所有装饰都加重动画：

| 等级 | 适合资源 | 默认场景 | 静态回退 |
| --- | --- | --- | --- |
| 普通 | 静态 PNG/SVG 边框、微弱渐变 | 所有列表 | 本身就是静态 |
| 稀有 | 低频 shimmer、呼吸光 | 列表和名片 | 固定高光帧 |
| 史诗 | APNG/GIF 外圈、局部粒子 | 名片打开后 | 透明 PNG |
| 传说/神话 | WebM/Canvas 主题背景、一次性入场/终结效果 | 名片详情、赛后或明确触发 | 主题海报或静态帧 |

高级效果建议“进入名片时播放一次，再进入低频循环”，而不是让动画从页面加载起永不停止。音效默认关闭，不能把商业装饰变成强制播放内容。

### 7.4 性能与可访问性

- 参考 Steam 的官方预算：头像框动画控制在 2MB 内，资料背景视频控制在 4MB 内；预览缩略图更小。
- 动态资源同时提供静态帧，设置 `poster`/静态 URL，并在头像列表中优先静态加载。
- 对离屏元素暂停播放或不初始化，减少多个用户卡片同时出现时的解码压力。
- 尊重系统 `prefers-reduced-motion`；[MDN 的说明](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/%40media/prefers-reduced-motion)指出，该媒体特性能检测用户是否请求减少动画，[W3C WCAG 2.3.3](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions)也建议让用户阻止非必要的交互动画。
- 禁止频闪和高对比度快速闪烁，Steam 的审核规则已经把 strobe/flashing 作为明确风险。
- 任何背景动画都要保留文字安全区；名字、称号、胜率、按钮和锁定状态必须在最差帧仍可读。
- 装饰不能是信息的唯一表达方式；稀有度同时显示文字或图标，不能只用颜色区分。

### 7.5 稀有装饰的获取模型

推荐组合，而不是单一付费门槛：

- **成就/赛季**：为高胜率、连胜、赛事、专精、长期活跃提供不可购买或限定称号。
- **免费/付费通行证**：免费轨给基础头像框和主题碎片，付费轨给更完整的主题套装。
- **轮换商店**：每周或每赛季轮换，显示下一次轮换时间；过期内容可以以更高成本返场。
- **直接购买**：对明确商品给出价格和预览，用户知道买到什么。
- **随机池**：只有在展示概率、保底、重复保护和重复补偿都存在时才使用。
- **主题套装**：头像框、头图、称号、资料页入场效果可独立装备，也可以一键套用完整主题。

## 8. Battle_ship 的落地顺序

### P0：先解决用户当前反馈

1. 真实头像上传接口、裁剪、预览、保存、删除、缩略图和失败反馈。
2. 头像框改为独立叠层组件，验证 PNG/APNG/静态回退在头像、排行榜、对局信息和个人名片四个场景均显示。
3. 个人名片的当前装备从“拥有的装饰列表”改为真正的 `equipped_*` 字段；无装备时显示明确占位。

### P1：动态效果基础能力

1. 为装饰增加 `rarity`、`effect_type`、`animated_asset_url`、`static_asset_url`、`reduced_motion_asset_url`、`unlock_type`、`unlock_value`。
2. 首先实现低频 CSS 光效和 APNG 头像框，不急着引入全屏 WebM。
3. 个人名片打开时显示一次性入场动效，列表保持静态。
4. 增加“减少动画”开关，并与系统 `prefers-reduced-motion` 合并。

### P2：高级装饰与收藏经济

1. 建立拥有、装备、预览、有效期和来源的独立状态。
2. 增加稀有度说明、活动时间、轮换倒计时和成就/赛季来源。
3. 做一个完整主题套装：头像框 + 头图主题 + 称号 + 资料页入场效果，验证整体对比度和资源大小。

### P3：长期内容系统

1. 商城/活动页与个人名片编辑器分离，但两者共享预览组件。
2. 只有在有足够内容和运营能力后再考虑随机池；优先使用直接购买、成就和通行证。
3. 对装饰资源增加审核、版本、回滚和统计，避免错误动画推送后只能改前端代码。

## 来源与边界

本记录中的产品事实来自链接所指的官方文档、官方新闻、官方开发文档或官方源码，检索日期为 2026-10-30。跨项目的接口字段、资源预算和分级方案是结合这些资料对 Battle_ship 的工程建议，不代表这些项目之间存在共同标准，也不等于已经在 Battle_ship 中实现。
