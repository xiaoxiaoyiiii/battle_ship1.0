# 暂时隐藏「钢筋铁骨」· 设计稿（2026-09-16）

> 需求（作者原话）：「把钢筋铁骨这张卡牌暂时隐藏，就是让人不能摸到这张牌」
>
> 范围确认：**只保证摸不到**。帮助里的卡牌图鉴仍照常列出这张卡（作者选定）。
> 线上生效需重新部署；**已在进行的对局不受影响**（牌堆是每局房间新建的）。

---

## 1. 现状链路（2026-09-16 grep 实测）

能进手牌的路径只有一条真实链路：

| 位置 | 说明 |
| --- | --- |
| `server.py:458` | 全局卡池 `magic_cards` ← `static/magic_card.json`（43 条） |
| `server.py:404-407` | `init_player_magic`：**仅当 `room.magic_deck` 为空时**复制全局卡池并洗牌 |
| `server.py:421` | `draw_card` 从 `room.magic_deck` `pop(0)` |
| `server.py:5836-5837` | 桃园结义的候选牌同样从 `room.magic_deck` `pop(0)` |
| `server.py:700 / 824` | `@_test_event` 调试事件（默认关闭，需 `ENABLE_TEST_EVENTS=1`） |
| `server.py:7022` | 偷牌效果只可能偷到对方**已有**的牌 |

推论：**牌堆里没有它 ⇒ 谁也摸不到**。收口点唯一，改动可以完全落在牌堆构建处。

## 2. 决策：三选一，采用「牌堆构建处过滤」

| 方案 | 结论 |
| --- | --- |
| ① 牌堆构建处过滤 | **采用**。唯一收口点；全局卡池仍 43 条，卡面数据 / 结算分支 / 前端文案全部保留；复原＝删一个卡名 |
| ② 过滤全局卡池 | 会打破 `tests/test_wuzhongshengyou_draw.py:199`（断言卡池 43）；连调试事件也再拿不到这张卡，影响面更大 |
| ③ 从 `magic_card.json` / `magic_cards.js` 删除 | 破坏前后端一致性测试与 3 个针对性用例（`test_all_magic_cards.py`、`test_defect_fixes_round1.py`、`tools/e2e_magic_cards.py`）；复原要改回多个文件 —— 不符合"暂时" |

## 3. 设计

只改 `server.py`，两处：

```python
# 紧挨 magic_cards 全局之后新增
HIDDEN_CARD_NAMES = {'钢筋铁骨'}

def init_player_magic(self, player_id, magic_cards):
    ...
    if not self.magic_deck:
        self.magic_deck = [c for c in magic_cards if c.name not in HIDDEN_CARD_NAMES]
        random.shuffle(self.magic_deck)
```

**明确不动**：`static/magic_card.json`、`static/magic_cards.js`、`apply_magic_effect` 的钢筋铁骨分支、
`static/game.js` 的提示文案、`_AI_SAFE_CARDS`、帮助 → 卡牌图鉴。

## 4. 怎么复原

把 `'钢筋铁骨'` 从 `HIDDEN_CARD_NAMES` 里删掉（集合留空亦可），部署即恢复，无需回滚任何代码。

## 5. 验证

- 新增 `tests/test_hidden_cards.py`：
  1. 隐藏名单里的卡名必须真实存在于卡池 —— 防手滑拼错导致"隐藏"静默失效
  2. 新建房间的 `magic_deck` 不含它
  3. **把整副牌堆抽干也抽不到它** —— 直接验"摸不到"这个语义，而不是只验一个长度
  4. `server.magic_cards` 仍是 43 条 —— 证明是"隐藏"不是"删除"
  5. 该卡卡面数据仍完整（同上）
- 修正 `tests/test_wuzhongshengyou_draw.py` 里"牌堆 43 条"的过时措辞（改为 卡池 43 / 牌堆 42）
- 全量 `pytest tests/ -q`（基线 790）

## 6. 部署

线上生效需 `bash deploy.sh`（部署后**新开**的对局才会用新牌堆）。
