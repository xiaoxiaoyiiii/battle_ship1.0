# 全局鼠标尾迹与点击反馈专项调研（2026-10-30）

本轮只研究两项交互反馈：

1. 鼠标或笔只要移动就能持续留下尾迹，不依赖按住鼠标左键；
2. 鼠标点击与手机轻触要立即反馈，且不同效果具备明确的形态差异，避免“换颜色但仍是同一个圆环”。

本文不修改业务代码，不包含测试文件。结论用于 Battle_ship 的全局 `GlobalPointerEffects` 和名片编辑器效果选择器。

## 结论先行

当前“只有按住左键才有尾迹”是输入条件错误：尾迹采样不能绑定 `buttons !== 0` 或拖拽状态，鼠标和笔应在 `pointermove` 上直接生成轨迹点。点击爆发则单独由 `pointerdown` 触发，两者必须拆成两个独立事件流和两个独立装备槽位。

推荐采用以下时序：

- `pointermove`：鼠标/笔移动即采样；按距离和时间节流生成尾迹，按速度调整长度、亮度和粒子方向；不检查左键是否按下。
- `pointerdown`：在按下瞬间先生成一个 0–32ms 的核心反馈，随后在 120–220ms 内完成展开和衰减；不要等待 `click` 或 `pointerup` 才开始动画。
- `pointerup`：只负责结束按压态，不再启动第二次同形波纹。
- `pointercancel`、`pointerleave`、`blur`、页面隐藏和路由切换：清掉当前指针状态，防止尾迹从旧页面延续到新页面。
- 触摸设备：轻触只生成点击/触控效果；只有移动超过 touch slop 后才可进入低密度尾迹，避免滚动页面时满屏飘粒子。

这与成熟项目的共性一致：输入事件层负责位置和时序，效果层负责形状和稀有度，游戏内使用低成本版本，个人资料页可以使用完整版本。

## 一手资料与成熟实现

### osu!：最接近需求的全局光标拆分

[osu! 官方 Wiki：Interface skinning](https://osu.ppy.sh/wiki/en/Skinning/Interface) 将光标拆成可换肤的资源层：

- `cursor.png` 默认在点击时旋转和扩张，并可通过 `CursorExpand`、`CursorRotate` 分别关闭；
- `cursortrail.png` 是光标下方独立的尾迹资源，默认不旋转，也可以单独打开 `CursorTrailRotate`；
- `cursor-ripple.png` 是独立的点击反馈，在左键或右键触发；
- `cursormiddle.png` 位于主体上方，并且会影响尾迹长度。

这直接证明了三件事：移动尾迹不应依赖按键状态，点击反馈应独立于尾迹，且一个效果可以由主体、尾迹、中层和点击层组合而成。Battle_ship 不应继续使用一个统一圆环 CSS 去模拟所有 `burst` 选项，而应把尾迹和爆发拆为不同的渲染分支。

osu! 还在 [Client options](https://osu.ppy.sh/wiki/en/Client/Options) 中提供光效和性能选项，例如关闭着色器、柔化特效、背景视频和主菜单视差。可借鉴为“完整 / 标准 / 静态”三档，而不是强制所有用户看到高密度特效。

### Android Material：点击反馈必须从接触点立即开始

Android 官方 [Defining Custom Animations](https://developer.android.com/training/material/animations) 明确把 touch feedback 定义为“在接触点即时确认”，默认按钮反馈使用 `RippleDrawable`。官方 API [RippleDrawable](https://developer.android.com/reference/android/graphics/drawable/RippleDrawable) 支持：

- 使用 `setHotspot(x, y)` 把反馈锚定到真实接触点；
- 使用有边界或无边界的 ripple；
- 通过 mask 限制波纹范围；
- 由多个 child layers 组成一套反馈，而不是单个不可变圆圈。

对 Battle_ship 的改进要求：点击爆发在 `pointerdown` 立刻出现核心点，扩散半径和衰减从这个点开始计算；名片、按钮和战斗棋盘可以采用不同 mask/范围；不同商品效果至少要有不同的几何结构，而不只是换主题色。

### W3C Pointer Events 与 MDN：不要用拖拽条件代替移动条件

[W3C Pointer Events Level 3](https://www.w3.org/TR/pointerevents3/) 规定 `pointermove` 在指针坐标或其他属性变化时触发；规范同时说明浏览器可能为性能而合并 `pointermove`，并提供 `pointerrawupdate`、`getCoalescedEvents()` 和 `getPredictedEvents()` 处理高频绘制和感知延迟。

[MDN PointerEvent](https://developer.mozilla.org/en-US/docs/Web/API/PointerEvent) 明确区分：

- `pointermove`：指针坐标发生变化；
- `pointerup`：指针不再处于活动状态；
- `pointercancel`：浏览器判断后续指针事件不会继续时触发；
- 触摸场景下 `pointerdown` 可能产生隐式 pointer capture，结束时由 `pointerup` 或 `pointercancel` 释放。

[MDN pointercancel](https://developer.mozilla.org/en-US/docs/Web/API/Element/pointercancel_event) 还列出滚动、缩放、窗口切换、屏幕旋转、多指竞争等取消原因。

因此，输入状态机应采用如下判定：

```ts
type PointerState = {
  pointerId: number
  pointerType: 'mouse' | 'pen' | 'touch'
  lastX: number
  lastY: number
  lastTime: number
  movedDistance: number
  trailActive: boolean
}

// 鼠标/笔：只要坐标变了就可以采样
if (event.pointerType === 'mouse' || event.pointerType === 'pen') {
  emitTrail(event.clientX, event.clientY, event.timeStamp)
}

// 触摸：先判断 touch slop，再决定是否出现尾迹
if (event.pointerType === 'touch' && distanceFromDown > TOUCH_SLOP) {
  emitTouchTrail(event.clientX, event.clientY, event.timeStamp)
}
```

不要把 `event.buttons !== 0` 写进鼠标尾迹的公共条件。`buttons` 只能用于另一个独立需求：例如“拖拽中增强尾焰”。普通移动尾迹与左键拖动增强应分别配置。

### Unity / Unreal：成熟粒子系统通过距离、寿命、宽度和速度塑造差异

Unity 官方 [TrailModule](https://docs.unity3d.com/ja/current/ScriptReference/ParticleSystem.TrailModule.html) 提供 `lifetime`、`minVertexDistance`、`widthOverTrail`、`colorOverTrail`、`ratio` 和多条 ribbon 等参数。[Unity 的 `minVertexDistance` 说明](https://docs.unity3d.com/ja/2021.3/ScriptReference/ParticleSystem.TrailModule-minVertexDistance.html) 明确指出：距离越小，尾迹越平滑，但顶点、内存和更新成本越高。

Unreal 官方 [Niagara Ribbon Effect](https://dev.epicgames.com/documentation/unreal-engine/create-a-ribbon-effect-in-niagara?application_version=4.27) 使用 Ribbon Renderer、Spawn Rate、Lifetime、Ribbon Width、速度和加速度构成连续带状效果；官方说明 ribbon 适合连续轨迹，但也应在上下文中检查效果。[Niagara 示例包的最佳实践](https://dev.epicgames.com/community/learning/courses/qXe/unreal-engine-niagara-examples-pack/L7aY/unreal-engine-niagara-example-pack-best-practices?locale=ru-ru) 提醒 Ribbon Renderer 成本较高，需要做粒子、shader、overdraw 和平台档位控制。

对 Battle_ship 的直接映射：

- “星尘航迹”：短寿命小点 + 速度方向 + 颜色渐隐；
- “声呐扫描”：一条细线或半圆扫描弧，不使用同心圆爆发；
- “棱镜折射”：两条不同偏移的彩色短轨，宽度随速度变化；
- “王冠指令”：菱形/三角碎片沿速度方向排列，点击时形成徽记而不是圆环；
- 所有尾迹都使用距离阈值、寿命和最大节点数，速度只改变形态参数，不无限增加粒子数。

## 点击特效必须重新设计为不同“结构”

目前多个点击特效如果都使用“圆点 + `scale()` + `opacity`”，即使颜色不同，用户仍会感到换汤不换药。建议把效果定义成结构化配置：

```ts
type PointerBurstDefinition = {
  id: string
  trigger: 'pointerdown'
  core: 'dot' | 'diamond' | 'crosshair' | 'spark'
  expansion: 'ring' | 'radial-shards' | 'scan-arc' | 'ink-spread'
  secondary?: 'orbit' | 'star-dust' | 'none'
  immediateMs: number
  settleMs: number
  maxParticles: number
  reducedMotion: 'instant-mark' | 'tap-only'
}
```

建议首批四种结构：

| ID | 核心形态 | 展开形态 | 结束方式 | 适合的稀有度 |
| --- | --- | --- | --- | --- |
| `burst_ripple` | 亮点 | 单次圆环 | 160ms 内淡出 | 默认 |
| `burst_sonar` | 十字准星 | 半圆扫描弧 | 扫描线擦除 | 赛季通行证 |
| `burst_prism` | 菱形 | 四向折射碎片 | 碎片沿方向散开 | 豪华版 |
| `burst_nebula` | 星点簇 | 非均匀星尘爆发 + 小轨道 | 粒子先后错峰消散 | 稀有/活动 |

关键时序建议：

- 0–32ms：核心点和 1 个主形态立即出现；
- 32–120ms：完成主要扩展，避免等待；
- 120–220ms：只做余辉、碎片或轻微收束；
- 连续点击：最多保留 2 个正在展开的爆发，旧效果应缩短寿命或进入回收池；
- 不要让一次点击等待 `click`、动画延迟或异步资源加载后才可见；资源失败时立即使用 CSS/SVG 静态核心。

这些时间是 Battle_ship 的验收目标，不是 Android 或 Apple 的平台硬编码；它们依据“即时确认、简短精确、不阻塞后续操作”的官方设计原则设定。

## 全局覆盖与局内战斗的分级

全局层应挂在应用 Shell，仅创建一个 `GlobalPointerEffects` 实例：

- 大厅/个人主页：完整尾迹和完整点击爆发；
- 局内战斗：保留移动尾迹，但使用更短寿命、更低透明度、更小半径和更少节点；
- 弹窗/名片编辑：保留点击核心和尾迹，视觉层始终 `pointer-events: none`；
- 棋盘拖动或滚动：不能因为视觉层而阻止业务指针事件；
- 页面失焦和 `visibilitychange`：停止新增粒子并清空旧粒子；
- `prefers-reduced-motion: reduce` 或应用低动效模式：关闭连续尾迹和持续旋转，点击只保留一次静态高亮或极短标记。

Apple 的 [Motion 指南](https://developer.apple.com/design/human-interface-guidelines/motion)强调动效应有目的、简短精确、可选，并且不应让用户等待动画完成；[Game controls 指南](https://developer.apple.com/design/human-interface-guidelines/game-controls)建议通过明确的按压态、光晕以及声音/触感帮助玩家确认交互。Battle_ship 应保留键盘焦点、状态文本和棋盘命中反馈，特效不能成为唯一反馈。

## 代码验收清单

### 全局尾迹

- [ ] 在大厅、个人主页、名片、弹层和局内战斗移动鼠标，不按任何键也能出现尾迹。
- [ ] `pointermove` 逻辑不以 `buttons !== 0` 作为普通尾迹前置条件。
- [ ] 鼠标/笔尾迹与触摸尾迹独立配置；触摸先经过 touch slop。
- [ ] 快速移动不出现长直线断裂；可利用 `getCoalescedEvents()`，但不直接在 `pointerrawupdate` 中做重渲染。
- [ ] 尾迹点有最小距离、寿命、最大数量和回收策略。
- [ ] pointerup、pointercancel、pointerleave、blur、visibilitychange 都能清理状态。

### 点击/触控爆发

- [ ] 按下的第一帧或 32ms 内看到核心反馈。
- [ ] 120–220ms 内完成主体展开，不能出现明显等待。
- [ ] 至少四种效果拥有不同几何结构和运动路径，而不是只改颜色。
- [ ] 连点时不会无限堆积粒子；最大活跃爆发有上限。
- [ ] 资源加载失败仍有 CSS/SVG 核心反馈。
- [ ] 手机轻触显示一次反馈，滚动和多指取消不会误触发完成态。

### 性能和无障碍

- [ ] 视觉层只使用 `transform`、`opacity`、CSS variables 或单一 Canvas，避免频繁布局。
- [ ] 局内战斗使用低成本档，列表和 HUD 不同时生成完整粒子。
- [ ] `prefers-reduced-motion` 和应用动效开关会立即停止新增尾迹，并保留可理解的静态状态。
- [ ] 视觉层 `pointer-events: none`，不影响按钮、棋盘、滚动、键盘焦点和上传控件。

## 参考来源

- [osu! Interface skinning](https://osu.ppy.sh/wiki/en/Skinning/Interface)
- [osu! Client options](https://osu.ppy.sh/wiki/en/Client/Options)
- [W3C Pointer Events Level 3](https://www.w3.org/TR/pointerevents3/)
- [MDN PointerEvent](https://developer.mozilla.org/en-US/docs/Web/API/PointerEvent)
- [MDN pointercancel](https://developer.mozilla.org/en-US/docs/Web/API/Element/pointercancel_event)
- [Android Defining Custom Animations](https://developer.android.com/training/material/animations)
- [Android RippleDrawable](https://developer.android.com/reference/android/graphics/drawable/RippleDrawable)
- [Unity TrailModule](https://docs.unity3d.com/ja/current/ScriptReference/ParticleSystem.TrailModule.html)
- [Unity TrailModule.minVertexDistance](https://docs.unity3d.com/ja/2021.3/ScriptReference/ParticleSystem.TrailModule-minVertexDistance.html)
- [Unreal Niagara Ribbon Effect](https://dev.epicgames.com/documentation/en-us/unreal-engine/create-a-ribbon-effect-in-niagara?application_version=4.27)
- [Apple Motion](https://developer.apple.com/design/human-interface-guidelines/motion)
- [Apple Game controls](https://developer.apple.com/design/human-interface-guidelines/game-controls)

## 调研判断

本项目当前需要先修正输入语义，再扩展视觉数量：

1. 删除“按下左键才生成尾迹”的普通条件，使 `pointermove` 真正全局生效；
2. 将点击核心反馈提前到 `pointerdown`，缩短展开时间并限制同时存在的爆发数；
3. 用结构化效果目录区分圆环、扫描弧、折射碎片和星尘爆发；
4. 保留独立的拖动增强层，只有在 `buttons !== 0` 时额外增加速度、宽度或粒子，不影响普通移动尾迹；
5. 在局内战斗使用同一全局层的低成本配置，保证用户能确认指针位置但不遮挡棋盘。

这样既能满足“只要鼠标移动就留下尾迹”的实机要求，也能让点击特效从同一套圆环模板变成可被装备、分级和付费化的真正个性化内容。
