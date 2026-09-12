# 游戏日志卡名可交互 · 设计稿

> 日期：2026-09-12
> 状态：已实现并上线
> 主题：让游戏日志里出现的魔法卡卡名可悬停预览、可点击查看详情

---

## 1. 需求

出牌日志里会写「第 N 回合 · 某人 使用了【某卡】」。希望：

- **鼠标移上去** → 显示卡名、速阶、类型、效果描述
- **点击** → 弹出小窗，同样内容

## 2. 确认过的决策

| 决策点 | 结论 |
| --- | --- |
| 作用范围 | **只做「出牌记录」这一类日志**；效果提示里顺带提到的卡名（如「恶魔契约生效」）不做 |
| 桌面交互 | 悬停出浮层；点击出居中详情小窗 |
| 手机交互 | 触摸屏没有悬停 → **点一下直接出详情小窗** |
| 小窗形态 | 新建独立浮层（**不复用**「待使用魔法卡」面板，那面板与手牌选中状态耦合） |
| 悬停浮层内容 | 完整信息（卡名 + 速阶 + 类型 + 效果描述） |

## 3. 现状（改造前）

- 日志 DOM：`.log-entry` 插入 `#game-logs`，由 `addGameLog(html)` 渲染
- `renderServerLog(entry)` 把 `entry.text` **整体 escapeHtml** 后显示，卡名是纯文本
- 服务端 `add_game_log(text, type, detail)` 的 payload **已经带了卡名**，但前端**丢弃了 detail**
- 卡牌数据在 `window.magicCards`（`{name, speed, type, description}`）

**服务端 payload 字段名不一致**（关键约束）：

| 日志写入点 | 字段 |
| --- | --- |
| `log_magic`（连锁结算，绝大多数出牌） | `{'caster':…, 'card': 卡名}` |
| 硫磺火焰专用分支 | `{'caster_id':…, 'card_name': 卡名, …}` |

日志里 `【】` **只用于卡名**（全项目仅上述 2 处，均确认是卡名）。

## 4. 方案选择

| 方案 | 做法 | 取舍 |
| --- | --- | --- |
| A（**采纳**） | 前端优先读 payload 的 `card`/`card_name`，取不到再扫 `【X】` 并用 `magicCards` 校验 | 结构化数据优先；字段名不一致也能兼容；**服务端零改动** |
| B | 只扫 `【】` + 卡表校验 | 最简，但完全依赖书写约定 |
| C | 服务端统一字段名为 `card`，前端只认一个 | 架构最干净，但要动服务端，收益有限 |

采纳 **A**：结构化优先 + 扫描兜底，且不动服务端（零回归风险）。

## 5. 数据流

```
服务端 add_game_log(text, 'magic', {card: '灵气复苏'})
   ↓ emit 'game_log' {ts, type, text, detail}
前端 renderServerLog(entry)
   ↓ renderLogTextHtml(entry)
   │   findLogCardName(entry)：
   │     ① detail.card / detail.card_name（须能在 magicCards 里查到）
   │     ② 兜底：正则 /【([^】]{1,24})】/ 且 magicCards 里存在该名
   ↓ 命中就把那段卡名包成
   │   <span class="log-card-ref" data-card="X">【X】</span>
   ↓ 其余文本照旧 escapeHtml
```

## 6. 组件划分

| 单元 | 职责 |
| --- | --- |
| `lookupCard(name)` | 从 `window.magicCards` 按名取卡，找不到返回 `null` |
| `findLogCardName(entry)` | 纯函数：解析日志涉及的卡名，无则将 `null` |
| `renderLogTextHtml(entry)` | 生成日志正文 HTML，卡名包成可交互 span，其余转义 |
| `renderServerLog(entry)` | 改：改用 `renderLogTextHtml` |
| `showCardTooltip(anchorEl, card)` / `hideCardTooltip()` | 桌面悬停浮层 |
| `showCardDetail(card)` / `closeCardDetail()` | 居中详情小窗 |
| `initGameLogCardRefs()` | **事件委托**绑定（幂等） |
| CSS | `.log-card-ref`、`.card-tooltip`、`.card-detail-overlay`、`.card-detail-box` |

### 关键决策：事件委托

在 `#game-logs` 上**只绑一次** click / mouseover / mouseout。

理由：日志条目持续新增、且超过 `GAME_LOG_MAX_ENTRIES` 会被裁剪。逐条绑监听会漏绑（新条目没监听）并造成泄漏（被删条目监听未解绑）。用 `host._cardRefsBound` 做幂等保护，因为 `setupSocketListeners` 会被多次调用。

## 7. 边界与错误处理

| 情况 | 处理 |
| --- | --- |
| 卡名不在 `magicCards` | 保持纯文本，不可交互（不报错、不误标） |
| 一行多个卡名 | 只标第一处（出牌记录正常只有一个） |
| 无 hover 的设备 | `matchMedia('(hover: hover)')` 为假 → **不绑** mouseover |
| `data-card` 被篡改成未知卡名 | 点击时 `lookupCard` 返回 `null` → 不开窗、不崩溃 |
| 小窗已开着再点另一个卡名 | 先关旧的再开新的（不会叠加） |
| 描述过长 | 小窗 `max-height: 86vh` + 内部滚动；遮罩可滚动 |
| 浮层定位出界 | 默认卡名下方居中；下方不够翻到上方；左右贴边钳制 |
| 滚动日志 | 收起浮层，避免其停在原处 |
| 悬停浮层挡鼠标 | `pointer-events: none`，防止 hover 抖动 |

## 8. 验证方式

服务端**零改动**，Python 测试保持 **185 全过**（无回归）。

前端本项目无测试框架，用 **Playwright 真实浏览器实测**：

- 渲染：payload `card` / payload `card_name` / 无 payload 靠扫描 —— 三种都能识别
- 反例：效果提示文本、不存在的卡名 —— **不**被误标
- 悬停：浮层内容为卡名 + 速阶 + 类型 + 描述
- 点击：小窗内容正确，且悬停浮层自动收起
- 关闭：点遮罩空白 / 点 ✕ / 按 ESC —— 三种都生效
- 健壮：重复打开不叠加；篡改 `data-card` 不崩溃；长描述不超视口
- 手机（390×844，`hasTouch`，移动 UA）：`hover` 不可用 → 不弹浮层；点击直接出小窗

## 9. 涉及文件

| 文件 | 改动 |
| --- | --- |
| `static/game.js` | 新增 7 个函数 + 改 `renderServerLog` |
| `static/style.css` | 新增 `.log-card-ref` / `.card-tooltip` / `.card-detail-*` 样式 |
| 服务端 | **无改动** |

## 10. 未做（明确排除）

- 效果提示里顺带提到的卡名（B 类）不做可交互
- 不做键盘可访问性（Tab 聚焦）增强 —— 日志是辅助信息，非关键路径
- 不引入前端测试框架
