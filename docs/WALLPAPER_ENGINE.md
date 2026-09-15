# 动态壁纸（Wallpaper Engine 接入）· 2026-09-15

> 目标：把玩家自己在 Wallpaper Engine 里买的壁纸，变成游戏界面的背景；顺手把界面整体
> 做了一轮视觉增强。
>
> 相关文件：`wallpaper.py`（服务端扫描/解析）、`api.py`（4 个路由）、`static/wallpaper.js`
> （前端引擎 + 设置面板）、`static/style.css` 第 24/25 节、`templates/index.html`、
> `tests/test_wallpaper.py`（50 条）、`tools/wallpaper_check.mjs`（32 项无头浏览器断言）。

![对局内效果（深色主题 + 壁纸）](./images/wallpaper_engine_ingame_dark.png)

---

## 1. 三条导入通道（能力与限制各不相同）

| 通道 | 可用范围 | 适用场景 |
|---|---|---|
| 扫描本机壁纸库 | **仅本机（localhost）** | Steam 里下载过的创意工坊壁纸，一键列出、点一张即可 |
| 粘贴本机路径 | **仅本机（localhost）** | 壁纸存在非 Steam 目录、或壁纸装在第二个 Steam 库里 |
| 粘贴图片/视频直链 | 任何环境 | 站点部署在远端时唯一可用的通道 |

服务端为了"扫描"会去读磁盘，为了"按路径导入"会去读**用户指定**的文件。这两件事都只应
发生在**玩家自己的机器**上，因此：

- 非回环地址访问 `/api/wallpapers` → 返回 `available: false` + 一句说明（HTTP 仍是 200，
  前端照常渲染，不必为"本来就该被拒绝"的场景写异常分支）
- 非回环地址访问 `/api/wallpaper/scan_path` → 403
- `scan_path` 额外要求请求头 `X-Battleship-Wallpaper: 1`。自定义头会让跨站请求触发 CORS
  预检，而本站**没有任何 CORS 放行头** —— 于是别的网页无法借用户的浏览器读他本机文件。
- 想在自己服务器上开放扫描（例如自建、只给自己用）：`BATTLESHIP_WALLPAPER_ALLOW_REMOTE=1`

**媒体文件本身不限制回环**，因为 id 是 `sha1(realpath)` 的前 14 位、不可枚举，而注册只可能
发生在回环请求里。这样局域网/手机访问同一台服务器时，之前导入的壁纸还能正常显示，
不会出现"电脑上能看、手机上没了"的割裂。

---

## 2. 创意工坊目录怎么解析

Steam 库定位顺序：注册表 `HKCU/HKLM\...\Valve\Steam`（`SteamPath`/`InstallPath`）→
`libraryfolders.vdf` 里的其余库 → 几个平台惯例路径兜底。目标目录固定是
`<steamapps>/workshop/content/431960/<壁纸id>/`。

每张壁纸读 `project.json`：

| 字段 | 用法 |
|---|---|
| `type` | `video` / `scene` / `web` / `image`；只用于给玩家解释"为什么不能播" |
| `title` | 列表标题；缺失时退化成目录名 |
| `file` | 壁纸本体。**校验真实内容 + 校验没有越出壁纸目录**，不合法就退回"目录里最大的媒体文件" |
| `preview` | 缩略图；缺失时按 `preview.jpg/png/gif/webp/bmp` 兜底 |

### 踩过的坑：preview 会被误当成壁纸本体

创意工坊每张壁纸都带一张 `preview.*`。而场景型 / 网页型壁纸的 `file` 指向 `scene.pkg` /
`index.html`（都不在媒体扩展名白名单里）—— 早期实现的"目录里最大的媒体文件"兜底于是
把 `preview.jpg` 挑了出来，把**不能播的壁纸报成能播**。玩家点上去只会看到一张静止的
缩略图冒充动态壁纸：不报错，但完全是错的。

现在 `_largest_media()` 会跳过 `preview.*` 与 `project.json` 里声明的 preview 文件。

### 各类壁纸的判定

| 类型 | 结果 |
|---|---|
| `video` + `.mp4` / `.webm` / `.m4v` / `.ogv` | ✅ 可播 |
| `video` + `.mkv` / `.mov` / `.avi` | ❌ 明确标注「浏览器播不了 .mkv」，牌面禁用 |
| `image`（png/jpg/gif/webp/bmp/apng） | ✅ 可播（gif/apng 动图也算"动态"） |
| `scene`（scene.pkg） | ❌ 说明「靠 Wallpaper Engine 实时渲染，网页里没法播放」 |
| `web`（index.html 一套网页） | ❌ 说明「出于安全考虑没有内嵌」 |

不能播的条目**不会进注册表**（否则等于开了一个"按 id 取任意文件"的接口），但**仍然显示
在列表里**：玩家需要看到"我买了这张、为什么现在不能用"，而不是它凭空消失。

识别只信文件头魔数，不信扩展名 —— 改后缀就能让服务端把任意文件当壁纸播出去，不是我们
想要的能力。

---

## 3. 一个实测发现的坑：同路径换文件，浏览器吃缓存

id 是**路径**的哈希，所以玩家把同一个壁纸文件**原地替换**之后，URL 一个字符都没变 ——
浏览器会拿 `max-age=3600` 里的旧副本。这个坑是在对比截图时发现的：换了图，页面纹丝不动。

修法：`media_url` / `preview_url` 挂上 `?v=<文件 mtime>`，文件一变地址就变。回归见
`tests/test_wallpaper.py::test_media_url_carries_mtime_as_cache_buster`。

> 排查方法记一笔：无头浏览器用的是**持久 profile**，localStorage 里存着上一轮的壁纸。
> 看到"改了代码页面却没变"，先确认拿到的是不是缓存/旧状态，再怀疑代码。

---

## 4. 前端行为上的几个刻意取舍

| 行为 | 原因 |
|---|---|
| 视频一律 `muted` | 带声音的壁纸会盖住战斗音效；且浏览器不允许未静音自动播放 |
| 页面切到后台 → 暂停 | 一张 4K 壁纸后台空转，风扇会先抗议 |
| `prefers-reduced-motion: reduce` → 默认静止 | 尊重系统设置，界面写明原因，仍可手动播 |
| 自动播放被拦 → 等首次交互补播 | 不报错了事，也不静默失败；设置面板写明状态 |
| `play()` 被拒分两类报错 | `NotSupportedError`/`MediaError` = 文件解不了；`NotAllowedError` = 只是被策略拦。<br>此前一律当成后者，于是文件坏掉时会引导玩家反复点击一个永远播不出来的东西 |
| 换回图片时 `removeAttribute('src')` + `load()` | 否则视频还在后台解码、白占内存 |
| 参数存 localStorage | 和主题/主色同一套路，服务端不存任何偏好 |
| 缩略图 `loading="lazy"` | 壁纸库可能有几十张 |

四个可调参数（不透明度 / 压暗遮罩 / 模糊 / 铺满方式）都是**即时生效**，没有"保存"按钮。

**浅色 / 深色的差异**：静态界面里浅色是"白玻璃"，壁纸透过来会偏灰白；深色是"深蓝玻璃"，
壁纸的饱和度保得住。所以设置面板里直接写了：壁纸太亮压不住界面时把遮罩加到 50%+，
深色模式下观感最好。

---

## 5. 界面视觉增强（style.css 第 25 节）

按钮流光（hover 时一道斜光扫过）、手牌全息反光、标题/品牌字渐变流动、棋盘霓虹描边与
玻璃边缘高光、屏幕入场动画、滚动条/选区/焦点环。

**两条硬规则**（都来自本项目已经踩过的坑）：

1. **不改任何元素的盒模型尺寸**。`tools/ui_layout_check.mjs` 会逐视口断言棋盘
   300×300 / 单格 42px / 浮窗互不重叠 / 一屏不滚动，动了尺寸整片红。
2. **动画里不许对「含 `position:fixed` 后代的元素」用 `transform`**。这类元素是
   `.screen(#game-screen)` / `.game-content` / `.game-main-container` / `.game-container`。
   给它们加 `transform`（或 `filter` / `backdrop-filter`）会让日志、聊天、卡牌预览、连锁提示
   这些浮窗**改以它为基准定位**，表现为"浮窗跑到页面中间"。
   —— 所以入场动画里用 `transform` 的屏幕是显式列出的那几个（内部没有 fixed 浮窗），
   而 `#game-screen` 只做淡入。

顺带：有壁纸时把 `.game-container` 那层 **14px 毛玻璃减到 5px**。14px 是给"纯渐变背景"调的，
套在壁纸上会把画面细节全抹平，只剩一团色块 —— 玩家会觉得自己选的壁纸白导入了。

滚动条**只写 `::-webkit-scrollbar`**，不写标准的 `scrollbar-width`：在 Chromium 里一旦设了
非 `auto` 的 `scrollbar-width`，`::-webkit-scrollbar` 会被整个忽略，第 7 节给日志浮窗做的
6px 细滚动条会一起失效。

---

## 6. 怎么验证

```bash
# 服务端：扫描解析 / 路径安全 / 回环门禁 / 媒体与缩略图路由（50 条）
./.venv/Scripts/python.exe -m pytest tests/test_wallpaper.py -q
./.venv/Scripts/python.exe -m pytest tests/ -q          # 790 passed

# 端到端（无头 Edge + CDP）：自己造假壁纸库、自己起服务端、自己跑浏览器
node tools/wallpaper_check.mjs                           # 32 项
node tools/wallpaper_check.mjs --url http://127.0.0.1:5000/   # 只验前端

# 布局不变量不能被视觉增强搞坏
node tools/ui_layout_check.mjs --url http://127.0.0.1:5000/
```

`wallpaper_check.mjs` 造四张假壁纸（图片 / 视频 / 场景型 / mkv），因此**不依赖本机是否装了
Wallpaper Engine**；它会用 `BATTLESHIP_WALLPAPER_DIR` 指向假库、`BATTLESHIP_DB_PATH` 指到
临时文件，跑完不留痕。

---

## 7. 已知限制

- **场景型壁纸（占创意工坊相当一部分）无法支持**。`scene.pkg` 是私有格式，需要 Wallpaper
  Engine 自己的渲染器。想用这类壁纸，只能在 Wallpaper Engine 里另存导出成视频。
- **网页型壁纸（`type=web`）没有内嵌**。它是一整套本地 HTML/JS，内嵌等于把任意本地脚本
  引进游戏页面，风险与收益不成比例。
- **不做大文件上传**。本机场景下服务端直接读盘，不需要走浏览器上传；这也让
  `MAX_CONTENT_LENGTH` 保持 2MB（头像用的下限），没有为壁纸撑大请求体的攻击面。
- 壁纸偏好在浏览器 localStorage 里，换浏览器/清缓存就没了（与主题、主色一致）。
