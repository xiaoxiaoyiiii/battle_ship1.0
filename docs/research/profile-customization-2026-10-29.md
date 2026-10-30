# 个人名片编辑入口与视觉层级调研（2026-10-29）

本记录只整理成熟开源项目的一手仓库、官方文档和官方产品说明，服务于 Battle_ship 个人名片页的入口、编辑态、保存反馈、视觉层级与隐私边界设计。本轮不修改 Battle_ship 代码，不提交或推送。

## 1. Mastodon

### 一手来源

- [Mastodon 官方产品设计：A Redesign for Profiles](https://github.com/mastodon/blog/blob/master/content/posts/2026-03-26_a_redesign_for_profiles/index.md)
- [Mastodon 官方文档：Setting up your profile](https://docs.joinmastodon.org/user/profile/)
- [Mastodon 官方源码：`app/javascript/mastodon/features/account_edit/index.tsx`](https://github.com/mastodon/mastodon/blob/main/app/javascript/mastodon/features/account_edit/index.tsx)
- [Mastodon 官方源码：`app/javascript/mastodon/features/account_edit/components/image_edit.tsx`](https://github.com/mastodon/mastodon/blob/main/app/javascript/mastodon/features/account_edit/components/image_edit.tsx)
- [Mastodon 官方源码：`app/controllers/settings/profiles_controller.rb`](https://github.com/mastodon/mastodon/blob/main/app/controllers/settings/profiles_controller.rb)
- [Mastodon 官方源码：`app/javascript/mastodon/reducers/slices/profile_edit.ts`](https://github.com/mastodon/mastodon/blob/main/app/javascript/mastodon/reducers/slices/profile_edit.ts)

### 可核实交互模式

1. **入口直接放在自己的 profile**：官方设计说明明确指出，旧版编辑入口藏在 Account settings，多步返回；新版把 `Edit profile` 按钮放到自己的 profile，查看和编辑可以直接切换。`index.tsx` 的编辑列头有 `Done`，返回公开 profile。
2. **编辑页按区块组织**：编辑页按 header/avatar、Display name、Bio、Custom fields、Featured hashtags、Profile display settings、Advanced settings 分区。每区有说明文字和独立的 `Edit`/`Add` 按钮，不把全部字段压成一张很小的表。
3. **图片编辑有专门菜单**：`image_edit.tsx` 对头像和横幅分别提供 Add/Replace、Add/Edit alt text、Remove；上传和 alt 文本分别进入 modal。官方产品说明还明确支持裁剪与 alt text。
4. **保存状态明确**：`profile_edit.ts` 在 `patchProfile`、上传、删除、标签更新期间维护 `isPending`，控件会禁用；成功后把返回的 profile 写回状态并刷新 account，错误保持可重试。
5. **服务端成功/失败反馈明确**：传统 settings 表单成功后重定向回 profile 并带 `changes_saved_msg` notice；失败则重新渲染表单。API 更新返回完整 profile，校验失败返回 HTTP 422。

### 字段和隐私边界

- 官方文档把 Display name、Bio、Avatar、Header、Locked、Bot、Profile directory、四行 Profile metadata 分开解释；公开资料允许链接、提及、hashtag、custom emoji。
- `locked` 会让新关注先进入人工批准，并在 profile 显示锁图标；`bot` 只承担可见标识；是否进入 profile directory 由独立开关控制。
- 个人链接可以做 `rel="me"` 验证；新版编辑器把验证说明放在 custom fields 编辑区，而不是藏在另一个设置页。

## 2. Nextcloud Social（当前仓库已转移到 AlohaSocial/social）

### 一手来源

- [原 `nextcloud/social` 仓库地址（GitHub 会转到当前仓库）](https://github.com/nextcloud/social)
- [当前源码仓库 AlohaSocial/social](https://github.com/AlohaSocial/social)
- [当前仓库 README：Your profile / account settings](https://github.com/AlohaSocial/social/blob/master/README.md)
- [当前仓库架构文档：Frontend Architecture](https://github.com/AlohaSocial/social/blob/master/docs/Architecture.md)
- [当前源码：`src/components/ProfileInfo.vue`](https://github.com/AlohaSocial/social/blob/master/src/components/ProfileInfo.vue)

### 可核实交互模式

1. **自己的 profile header 有明确的 `Edit profile` 按钮**：`ProfileInfo.vue` 只有在 `isOwnProfile` 时渲染该按钮，点击 `openProfileModal`；访客只读。源码同时给 profile header 使用 128px avatar、`h1` display name 和 posts/following/followers 三个计数入口，层级比普通列表卡片更突出。
2. **编辑使用独立 modal，而不是把编辑控件常驻在展示卡片上**：modal 统一包含 Banner、Bio、metadata fields；banner 既可上传文件也可填 URL。README/架构文档说明，banner 按钮不再悬浮在访客可见的头像图上，避免阅读页被编辑 chrome 污染。
3. **字段反馈细**：Bio 有字符计数和超限状态；metadata 最多四行，行内可删除；pronouns 和 support link 作为已命名字段单独呈现；链接字段显示 verified / not verified、验证时间和可复制的 `rel="me"` 片段。
4. **保存反馈完整**：`saveProfile()` 先写 fields，再只在 bio 变化时 PATCH note；成功关闭 modal、显示 `Profile saved` 并刷新 account；失败显示 `Failed to save profile`，不会静默丢失编辑内容。banner 上传和 URL 设置也分别显示成功/失败 toast。
5. **读写边界清晰**：profile 页面用于阅读；自己的 profile 才能编辑。私有 note 折叠在单独区域，只对当前阅读者可见。账号设置把 follow requests、discoverable、indexable、bot、默认发帖可见性等开关放到另一页；发布名属于 Nextcloud 账号时不在 Social 中重复编辑，避免出现两个权威来源。

## 3. Lichess

### 一手来源

- [Lichess 官方仓库路由：`conf/routes`](https://github.com/lichess-org/lila/blob/master/conf/routes)
- [Lichess 官方源码：`app/controllers/Account.scala`](https://github.com/lichess-org/lila/blob/master/app/controllers/Account.scala)
- [Lichess 官方源码：`modules/pref/src/main/ui/AccountPages.scala`](https://github.com/lichess-org/lila/blob/master/modules/pref/src/main/ui/AccountPages.scala)
- [Lichess 官方源码：`modules/pref/src/main/ui/AccountUi.scala`](https://github.com/lichess-org/lila/blob/master/modules/pref/src/main/ui/AccountUi.scala)
- [Lichess 官方源码：`modules/user/src/main/UserForm.scala`](https://github.com/lichess-org/lila/blob/master/modules/user/src/main/UserForm.scala)
- [Lichess 官方源码：`ui/user/css/_profile.scss`](https://github.com/lichess-org/lila/blob/master/ui/user/css/_profile.scss)
- [Lichess 官方产品说明：New features: profile and preferences](https://lichess.org/forum/lichess-feedback/new-features-profile-and-preferences)

### 可核实交互模式

1. **入口有两层**：`AccountUi.scala` 的账号菜单把 `Edit profile` 放在第一项；官方说明还写明可以从右上角用户名或自己的 profile 进入。路由明确为 `GET /account/profile` 和 `POST /account/profile`。
2. **编辑页是完整页面**：`AccountPages.profile` 使用 `box box-pad`、清晰的 `h1`、`standardFlash` 和 `form3`；Bio/flair、country/location、real name、评级、links 分组排列，评级使用三列布局，并提供明确的 `Apply` 提交按钮。
3. **保存反馈标准化**：`Account.profileApply` 绑定表单后调用 `setProfile`，成功重定向到公开用户页并 `flashSuccess`；失败重新渲染同一编辑页，保留表单错误。
4. **内容默认轻量且公开边界明确**：编辑页直接提示所有资料“public and optional”；国家、位置、简介、真实姓名、多个评级和社交链接都可留空。公开头衔用户的 real name 在表单中只读，避免编辑无效字段。
5. **公开 profile 的视觉指标不会压成小字**：`_profile.scss` 把 profile-side 设为 `flex: 1 0 300px`；`insight strong` 使用 `font-size: 1.5em`，图标 `2.5em`。这是用可见尺寸表达核心指标的直接实现证据。

## 4. 对 Battle_ship 名片页的五条结论

1. **先解决入口可发现性**：在自己的名片 header 右侧放一个高对比度的 `编辑名片` 主按钮；用户菜单和名片页都保留入口。按钮只对本人出现，访客不显示。
2. **编辑态应有完整空间和明确层级**：采用独立编辑页或足够宽的 modal，按“头像/封面、显示名与简介、战绩与段位、称号/徽章、隐私与展示”分区；不要把所有字段继续塞进小卡片。头像建议接近 96–128px，名片主标题 28–32px，区块标题至少 18px，核心数值用 1.5em 以上并留出足够间距。
3. **展示优先，编辑控件不要污染阅读态**：展示页突出头像、显示名、段位/积分、胜率或成就等核心信息；图片替换、裁剪、删除、简介和字段编辑在独立 modal/编辑页完成，并提供返回名片的 `完成` 操作。
4. **保存必须可感知且可恢复**：保存中禁用按钮并显示 `保存中…`；成功后关闭编辑态、显示成功 toast 并刷新名片；失败显示错误、保留草稿，避免用户以为已保存但实际丢失。只提交有变化的字段，避免覆盖后端拥有权不同的资料。
5. **把公开资料、可见性和私密内容拆开**：名片展示字段明确标记“公开”；战绩统计、徽章、装扮收藏等可分别提供显示开关；私密备注、管理信息不可混在公开名片。若加入外链或身份验证，应像 Mastodon/Nextcloud 一样在字段旁显示验证状态和下一步动作。

## 5. Battle_ship 当前本地缺口（已读当前分支源码）

- [当前名片实现：`frontend/src/screens/profile/ProfileScreen.vue`](D:/Codex%20workspace/battle-ship-fork-cloud/frontend/src/screens/profile/ProfileScreen.vue)
- 当前本人操作区只有 `隐私与设置` 和 `返回排行榜`，没有 `编辑名片` 入口（`ProfileScreen.vue:508-515`）。这与 Mastodon、Nextcloud Social 都把编辑入口放在本人 profile header 的做法不一致。
- 名片主体尺寸已有一定基础：宽度上限 1120px、头像 88px、姓名 22px、主按钮最小高度 40px（`ProfileScreen.vue:590-600`、`662-678`、`722-729`、`1038-1047`）。但信息层级仍偏弱：区块标题只有 12px，装扮收藏标签 10px，状态/签名 13px/12px，统计数字 20px（`ProfileScreen.vue:847-855`、`879-895`、`906-917`）。这能解释“字体和模块太小、没有任何地方突出”的实测感受。
- `隐私与设置` 的视觉样式虽然是高对比背景（`ProfileScreen.vue:1049-1053`），语义却是设置，不会让用户想到“编辑名片”；应拆出一个更明确、更靠近名片 header 的 `编辑名片` 主动作。
- 当前名片展示内容混合了身份、段位、战绩、徽章、装扮收藏、历史战绩，但核心身份区仍只有 88px 头像与 22px 姓名；应参考 Nextcloud 的 128px avatar / `h1` 和 Lichess 的大指标比例，先提升身份与段位层级，再压缩次要记录。
## 6. 本轮边界

- 本轮只做仓库和官方文档调研，未修改 Battle_ship 代码、配置、测试或分支状态。
- 上述项目的功能会随版本变化；实现建议以各链接当前 `main`/`master` 源码为准，落地前仍需结合 Battle_ship 现有 API 和权限模型核对。
