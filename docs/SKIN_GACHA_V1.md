# 卡面皮肤抽卡 v1

本文件记录后端实现口径，接口与字段以仓外约定为准：

`D:\Codex workspace\bridge\skin-gacha-v1-20261115\CONTRACT.md`（v1.0）

总规格见同目录 `SPEC.md`。

## 规则

- 第一批 12 张霓虹赛博皮肤。限定 3 张（失灵！、恶魔契约、绝处逢生），传说 9 张（轰炸、看破！、极限增援、神威！、命运骰子、加百列之光、教皇旨意、火力全开、克苏鲁之眼）。
- `card_key` 对齐前端 `frontend/src/cards/cardArt.ts` 的卡面 slug；`skin_id = neon-<card_key>`。后端卡牌身份仍是中文卡名。
- 只用潮汐徽记：单抽 80、十连 800，一次扣费、同一事务。无折扣、无保底。
- 每抽概率：限定 1%、传说 9%、潮汐碎片 90%。服务器掷骰（`secrets.SystemRandom`，测试可注入）。同档内均匀，不排除已拥有。
- 抽到已拥有皮肤返还 5 碎片；直接抽到碎片得 1 碎片。集齐 12 张后仍可抽，皮肤一律按重复返 5 碎片。碎片保留给下一批。
- 20 碎片兑换未拥有的指定传说，60 碎片兑换未拥有的指定限定。兑换不带 `request_id`，以 `skin_id` 天然幂等，重复提交 409 `skin_already_owned`。
- 皮肤不进入商店直购目录（`SHOP_ITEMS` 不加 `neon-*`），`POST /api/shop/purchase` 购买皮肤走既有 400 `item_unavailable`。
- 纯外观，不影响规则。未点亮图鉴的卡，只要已拥有对应皮肤也可选用。
- 首次抽中或碎片兑换皮肤时，在获得事务内自动装备到对应卡牌；重复皮肤与同一抽卡请求重放不覆盖玩家后续手选。既有装备偏好不批量回填。
- 图鉴提供独立的“已拥有皮肤”筛选，可与点亮状态、速阶、类型和关键词叠加。

## 表结构（0015_card_skins）

接在 `0014_collection` 之后，可逆。`HEAD_REVISION = "0015_card_skins"`。

| 表 | 作用 |
| --- | --- |
| `card_skins_owned` | 拥有记录，主键 `(user_id, skin_id)`，来源 `gacha` / `exchange` |
| `card_skin_shard_wallets` | 碎片余额，`balance >= 0` |
| `card_skin_shard_ledger` | 碎片流水，唯一键 `(user_id, source_kind, source_id)`；抽卡合计记 `skin_gacha`，兑换记 `skin_exchange` |
| `card_skin_selections` | 每卡选用；无行表示默认卡面 |
| `gacha_requests` | 抽卡幂等与首次 200 响应快照，主键 `(user_id, request_id)` |

徽记扣费走既有钱包：`tide_ash.apply_once(user_id, "skin_gacha", request_id, -cost)`。降级删除上述五表，不改 `collection_*`、`tide_ash_*`、`user_cosmetic_rewards`；已产生的 `skin_gacha` 徽记流水保留。

## 接口

- `GET /api/shop/gacha`：卡池状态（公示概率、价格、徽记与碎片余额、12 皮肤 owned、集齐进度）。
- `POST /api/shop/gacha/pull`：`{count: 1|10, request_id}`。同键同 count 重放 200 且 `replayed=true`，不重复扣费；同键不同 count 为 409 `request_id_conflict`。
- `POST /api/shop/gacha/exchange`：`{skin_id}`。
- `PUT /api/collection/skin`：`{card_name, skin: "default"|skin_id}`。
- `GET /api/collection`：每卡新增 `skins`、`owned_skins`、`selected_skin`，顶层新增 `shards`。

未登录 401，错误体为 `{"error":{"code","message","field"}}`。线上字段均为 snake_case。抽卡结果里未出皮肤的 `skin_id` 等为 JSON `null`；公开对局载荷在默认卡面时**省略** `skin_id` 键。

## 出牌冻结点

与熟练光效 `mastery_tier` 并列，字段名 `skin_id`。在合法支付并入链时读取出牌者当时选用并写到 `ChainItem`：

- `services/magic.py` 主动出牌与连锁响应出牌两处；被「盗亦有道」偷来后打出的牌，以实际打出者当时的选用为准。
- 公开连锁：`domain/spectate/rules.py` 的 `PREVIEW_KEYS` 与 `sanitize_preview_item`（覆盖 `magic_chain_updated`、重连快照 `chain`）。
- 连锁结算：`chain_resolved.results[]` 经 `extra['skin_id']` 平铺到结果顶层。
- 观战演出：`domain/viewing.py` 的 `public_cue`；观战帧的 `chain` 走 `public_chain`。
- 录像 v2 随上述冻结帧和 cue 写入，回放不再查当前选用。

手牌、`card_payload`、观战/录像里的 `players.cards` 不带皮肤。旧版录像 v1 的 `_chain_items` 与 `chain_resolving` 的 effect、整局结算载荷均不加 `skin_id`。自定义房、匹配、排位、人机、每日挑战同样适用。
