# 区域选择魔法卡：双方连锁预览（设计规格）

> ⚠️ **状态：扫描完成，代码实现尚未开始。**
> 本文的覆盖表与接缝分析来自 2026-09-27 的真实 grep 交叉验证（每格带 `文件:行号`，行号以当次 grep 为准）。
> 「实施清单」是待执行项，不是已完成项 —— 执行状态以交付报告为准。

---

## 1. 目标

连锁结算期间，双方都能看到**每个已确认的连锁节点将要作用在哪些格子、在哪一方的棋盘上、是哪张卡**，
且该预览**只含公开信息**（不泄漏隐藏船位/命中/私密参数），并且**多张卡的区域可同时存在、可分辨来源**。

## 2. 现状接缝（已确认，勿另写第二份）

| 事实 | 位置 | 含义 |
| --- | --- | --- |
| 连锁载荷的**唯一**净化函数 | `spectate.py:253 _pub_magic_chain(data, room=None)` | 所有对外连锁数据都过这里 |
| 该函数**整份剥掉** targets | `spectate.py:483`（`'magic_chain_updated': _pub_magic_chain`，注释「★ 剥掉客户端提交的 targets」） | 现状是"丢弃"，本任务把它换成"白名单净化" |
| 实时流与快照**共用同一函数** | `server.py:10453 _spectate_chain_payload(room)` → `spectate.sanitize_event('magic_chain_updated', …)` | 第 6 条（重连同一契约）天然满足：**别新开一份快照构造** |
| 事件净化入口 | `spectate.py:738 sanitize_event(event, data, room=None)` | 复用，不另写 |
| 禁字段表 | `spectate.py:657 FORBIDDEN_PAYLOAD_KEYS = ('ships','positions','hits','sunk_positions')`；`:675 SNAPSHOT_FORBIDDEN_KEYS` | 新字段必须与之无交集 |
| 坐标键白名单 | `spectate.py:714` 由 `FORBIDDEN_PAYLOAD_KEYS - COORDINATE_KEYS` 推出 | 说明"坐标"已有受控通道可依 |
| 连锁广播点 | `server.py:8228`、`server.py:10842`（`{'chain': room.chain}`） | 两处都经净化函数 |
| 服务端目标归一化 | `server.py:7885 _sanitize_magic_targets(targets)` | 校验 `target_area{x1,y1,x2,y2}`=0..5、`target_line{type∈row/col,index}`=0..5、`target_cells`/`selected_cells` |
| 单格取用 | `server.py:7936 _pick_cell_from_target(target_data)` | 单格卡（克苏鲁之眼等） |

## 3. 完整覆盖清单（交叉验证：客户端选择器 ↔ 服务端校验）

**声明式真源（客户端）**：`static/game.js:11105-11111`

| 卡名 | 目标形状 | 棋盘归属 | 客户端选择器调用点 | 服务端校验点 |
| --- | --- | --- | --- | --- |
| **神威！** | `target_area` 3×3 | **己方或对方**（玩家当场二选一） | `game.js:10595`（self）/ `game.js:10606`（opponent） | `server.py:13580` 分支；`13583` 校验存在；`13588` 取 area；**`13589` 读 `board`（默认 `'opponent'`）**；`13590` 定目标方 |
| **冻结** | `target_area` 3×3 | **对方**（服务端硬编码） | `game.js:10563`（`createBoardAreaPicker(opponentBoard, 3, …)`） | `server.py:13672` 分支；`13674` 校验；`13679` 取 area；`13683` 作用于 `opponent.ships` |
| **探测雷达** | `target_area` 2×2 | **对方**（硬编码） | 同 `game.js:10563` 的 area 分支（size 来自 `game.js:11106`） | `server.py:13930` 分支；`13932` 校验；`13937` 取 area；`13942-13945` 揭示到 `revealed_positions` |
| **轰炸** | `target_line` row/col | **对方**（`game.js:11107 board:'opponent'`） | `game.js:10673`（row）/ `game.js:10674`（col） | `server.py:13725` 起（`'target_line' not in target_data` → `13730` 取 line） |
| **克苏鲁之眼** | 单格 `{x,y}` | **己方**（`game.js:11109 board:'self'`，暴露自己一艘船） | `game.js:10978` | `server.py:11189 confirm_magic_target`；`11051`/`11105` 的 `ship_indices` 路径（`11429` 读 `ship_indices`） |

**已定位但"卡名 ↔ 形状"尚未逐张确认的形状**（下一轮 grep 要补）：

| 形状 | 客户端调用点 | 服务端读点 | 备注 |
| --- | --- | --- | --- |
| `target_cells`（连选格子） | `game.js:10930` | `server.py:7919` | 注释指向「连选」模式（`game.js:10617` 提到硫磺火焰） |
| `selected_cells` | `game.js:11061` | `server.py:7919` | 同上 |
| `ship_indices`（多选自己的船） | `game.js` 经 `confirm_magic_target` | `server.py:11429`；发起见 `7327`/`7351`（仁王之盾） | **不走 `room.chain` 的 targets**，是另一条通道 |

## 4. 待作者拍板的规则问题（**阻塞实现，我没有自行决定**）

**问题**：预览要标注「所属棋盘（谁的）」（第 3 条要求），但**服务端目前不掌握统一、可校验的棋盘归属**：

- `board` 只有**神威！** 一处读（`server.py:13589`），且是**客户端提交**、`_sanitize_magic_targets`（`7885`）**完全不校验 `board`**；
- 冻结/探测雷达/轰炸的"对方"归属只存在于**客户端表**（`game.js:11105-11107`），服务端靠硬编码作用对象体现；
- 神威的 `board` 默认值 `'opponent'` 意味着**漏传即静默按对方处理**（与本项目教训 #2「会兜底的取数不能当判据」同形）。

| 选项 | 做法 | 影响 |
| --- | --- | --- |
| **A（推荐）** | 在**服务端**新增一张镜像表 `AREA_TARGET_BOARDS = {卡名: 'self'\|'opponent'\|'choice'}`，并在 `_sanitize_magic_targets` 里**校验 `board`**；用一条守卫测试**钉住两张表**（按 `tests/test_ship_pick_mirror.py` 的先例：解析 `game.js:11105` 与 `server.py` 的镜像表逐一比对） | 服务端成为棋盘归属的真源；预览可准确映射双方棋盘；增加"两张表必须同步"的维护成本（有测试钉住） |
| **B** | 预览只画**坐标格**，服务端带一个 `board_source: 'client'\|'fixed'` 标记，神威之外的卡一律 `'opponent'`（照抄现状硬编码） | 改动最小、零风险；但"棋盘归属"仍是**散落的口头约定**，背离"同一判断只留一份实现"（教训 #1） |
| **C** | 统一改为客户端**必须显式提交 `board`**（所有区域卡），服务端严格校验 | 契约最干净；但**破坏旧客户端兼容**（老页面不传 `board` 会被拒），需前端发版同步 |

> 选 A 还是 B 会直接改变 `magic_chain_updated` 的公开字段集合，**属于对外契约**，故不自行决定。

## 5. 公开字段设计（草案，待第 4 节定稿）

净化后每个连锁节点只允许出现：

```json
{
  "id": "<ChainItem 标识>",
  "card": "冻结",
  "caster": "<座位标签，沿用 spectate 既有口径>",
  "negated": false,
  "preview": {
    "board": "opponent",
    "shape": "area",
    "cells": [{"x": 1, "y": 2}, ...]
  }
}
```

硬约束：
- `preview` 由**服务端从已确认的 targets 计算**，绝不透传 `target_data` 原对象；
- 只允许 `x`/`y`（0..5 整数）、`board`（枚举）、`shape`（枚举）、`card`（已有）；
- 与 `FORBIDDEN_PAYLOAD_KEYS`（`ships/positions/hits/sunk_positions`）**无交集**；
- **不得调用任何效果逻辑**去"试算"区域（不许提前结算）；
- 选区**未确认前不广播**（第 5 条）：预览只从 `room.chain` 里已入栈节点派生 —— 入栈即已确认，天然满足。

## 6. 实施清单（待执行）

1. `server.py`：新增 `_chain_area_preview(item, room)`（纯函数，只读 `item` 的已确认 targets + 第 4 节的归属表），产出上述字段。
2. `spectate.py`：`_pub_magic_chain`（`:253`）把"剥掉 targets"改为"挂上净化后的 `preview`"，保持**同一函数**服务实时流与快照。
3. `static/game.js`：新增独立预览层（多区域并存、标卡名、重叠可分辨），不改动既有选择/攻击/冻结标记；预览层必须在响应按钮可用**之前**就位。
4. 清理：由"按 `room.chain` 派生"天然获得（节点出栈/被无效化/连锁清空 → 预览随之消失）；另需在连锁结束/取消/对局结束时显式清渲染层残留。
5. 测试：`tests/test_area_preview.py`（覆盖表逐行、双方映射、多节点并存、无效化清理、重连快照同契约、非法目标拒绝、**隐藏信息不泄漏**——按惯例"以别人身份直读 + 两侧都断言"）+ 源码级守卫（不得透传 `target_data`）。
6. 验证：`python -m pytest tests/ -q`（当前基线 **2569 passed**）、`node --check static/game.js`、以及 `tools/chain_preview_check.mjs`。

## 7. 验收方式（主会话可独立复现）

```powershell
cd C:\Users\Administrator\Documents\ds-harness-desktop\WorkSpace\battle_ship1.0
$env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP
python -m pytest tests/test_area_preview.py -q          # 新增用例
python -m pytest tests/ -q                              # 全量（基线 2569）
node --check static/game.js
```
再按 `tools/chain_preview_check.mjs` 的用法起服务端（端口避开 5060/5061、带 `CORS_ORIGINS`、profile 放 `.tmp/`）做真实预览验证。
