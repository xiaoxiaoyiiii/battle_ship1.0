"""重开双方棋盘、绝处逢生与单侧重摆效果。"""

import replay
from application.player_state import EffectFlags
from application.replay_observation import capture_replay_observation

BOARD_CARD_NAMES = frozenset({'败者食尘', '绝处逢生', '回光返照'})


def apply_board_card_effect(
        room, caster_id, card, result, emit, *, ai_seat_places_board_now,
        clear_board_effects, clear_chain_display, clear_multiturn_effects,
        flush_spectate_board_if_dirty, mark_spectate_board_dirty,
        alive_ships, emit_active_effects, emit_player_ships,
        emit_board_attacks, emit_ships_updated, mark_ship_sunken,
        on_ship_destroyed, start_placement):
    """结算棋盘重置类卡牌，返回（已处理，需提前结束）。"""
    if card.name not in BOARD_CARD_NAMES:
        return False, False
    opponent_id = next(p for p in room.players if p != caster_id)
    caster = room.players[caster_id]
    opponent = room.players[opponent_id]
    if card.name == '败者食尘':
        # 卡面："立即重启正常对局但保留双方的手牌。
        #        败者食尘生效的大回合内双方的攻击次数都为0。"
        #
        # 「重启正常对局」= 双方棋盘清空、各回 6 艘重新摆放（作者确认）。
        # ⚠️ 原实现是【交换双方的船数】（caster.max_ships = opponent_ships），
        # 卡面里根本没有这回事 —— 实测玩家反馈"重置后船数不对"即源于此。
        # 这里改为双方一律重置为默认船数（6）。
        DEFAULT_SHIPS = 6
        # 双方棋盘都要换掉 → 除外船不再是这批棋盘上的船；**范围效果也要终止**
        clear_board_effects(room, list(room.players), '败者食尘')
        # 跨回合计数效果一并终止（**在 game_effects 整体清空之前**：
        # 直接清空会让前端收不到清除事件，角标永远挂着）
        clear_multiturn_effects(room, '败者食尘')
        for p_id in room.players:
            player = room.players[p_id]
            player.ships = []
            player.attacks = []
            player.remaining_ships = 0
            player.needs_reset = True
            player.revealed_positions = []
            player.max_ships = DEFAULT_SHIPS
            # 棋盘相关的一次性状态也清掉，避免上一局残留（冻结/无敌/护盾）
            player.sunken_ships = []
            if hasattr(player, 'opponent_attacks'):
                player.opponent_attacks = []
            for ship in list(getattr(player, 'ships', []) or []):
                ship.frozen = False
                ship.invincible = False
                ship.shield = False
                ship.trap = False
        # ★ 第 5 批：双方棋盘整块换新 → 观众那块棋盘跟着清空（与灵气复苏同一句）。
        mark_spectate_board_dirty(room)
        # ★ 回放批：同上（败者食尘也是双方重摆）—— 同一个失效点、第二个消费方。
        replay.note_board_reset(capture_replay_observation(room))
        replay.note_board_replaced(capture_replay_observation(room))

        # 冻结区域记录也一并清掉（重开棋盘后区域标记不该残留）
        if isinstance(room.game_effects, dict):
            room.game_effects.pop('frozen_area', None)

        # 只保留手牌 —— 场地魔法、生效中的效果、弃牌堆统统回到开局状态
        # （作者确认：「只保留手牌，其余全部重置」）
        room.field_magic = None
        room.field_magic_owner = None
        room.game_effects = {}
        room.magic_discard = []
        room.magic_temp_data = {}
        room.chain = []
        room.chain_waiting = False
        room.chain_window = None
        room.chain_passes = 0
        clear_chain_display(room)
        room.last_attack = None
        room.skip_opponent_turn = None
        # 双方的玩家级效果标记清零（EffectFlags 整个换新）
        for p_id in room.players:
            room.players[p_id].effect_flags = EffectFlags()
            room.players[p_id].magic_blocked = False

        # 与灵气复苏同样保存进度：重新摆放完成后回到原先后手与阶段，不重新猜拳。
        room.lingqi_saved_state = {
            'attack_order': list(room.attack_order),
            'current_attacker': room.current_attacker,
            'current_phase': room.current_phase,
            'round': room.round,
            'attacks_remaining': room.attacks_remaining,
        }
        # 复用灵气复苏的"摆放完成即恢复"分支
        room.lingqi_resurgence_applied = True

        room.state = 'placing_ships'
        # 卡面第二句：本大回合内双方攻击次数为 0。
        # 这里先置 0（摆放期间本就没有攻击），摆放完成回到攻击阶段时会再确认一次
        # （见 handle_place_ships 里的 polar_reversal_applied 分支）。
        room.attacks_remaining = 0
        room.polar_reversal_applied = True
        # ⚠️ 大回合级标记：上面 `room.game_effects = {}` 已经清过一次场，
        # 所以必须写在这一行【之后】。它让本大回合内**双方**的攻击次数恒为 0 ——
        # 只靠上面那个一次性标记的话，进战斗阶段时会被按船数重算成 6（实测缺陷）。
        room.game_effects['zero_attacks_round'] = room.round

        for p_id in room.players:
            player = room.players[p_id]
            emit('reset_gameboard', {
                'new_max_ships': player.max_ships,
                'message': '败者食尘生效，双方棋盘已重置为6艘，请重新摆放（手牌保留）'
            }, to=player.sid)

        # ★ 2026-09-22：与回光返照同一形状 —— **AI 当施法者时它自己那一半必须
        #   当场摆完**（详见 `_ai_seat_places_board_now` 与回光返照分支的说明）。
        #   败者食尘是"双方一起重摆"，真人那份 `reset_gameboard` 已经发出去了
        #   （他确实要重新摆，这是卡面要求），但房间不该停在"AI 还没摆"的中间态：
        #   那个中间态里 AI 的自救排在后一个大回合的预算检查后面（异步），
        #   实测会出现"AI 一直 0 艘船、却已经在开炮"的窗口
        #   （`tools/probe_ai_redeploy.py` 的手牌 ['败者食尘'] 一栏）。
        ai_seat_places_board_now(room, caster_id)

        result['message'] = '败者食尘生效：双方棋盘重置为6艘并重新摆放，手牌保留；本大回合双方攻击次数为0'
        # ★ 第 5 批：本分支发出去的全是 `to=<sid>` 单发，`emit` 的收尾不跑 ⇒ 自己收口。
        flush_spectate_board_if_dirty(room)
        # 立即返回：已清空双方战舰并重置为布船阶段，
        # 不能落入末尾"对手剩余船数<=0 则游戏结束"的兜底判断（会误判 game_over）
        return True, True
    # ==== 速阶2 魔法卡 ===

    elif card.name == '绝处逢生':
        # 卡面：牺牲自己所有的战舰，然后在"所有原本有战舰的地方"选一格，
        # 放置唯一一艘战舰；此后击杀对方任何一艘船直接获胜。
        if caster.remaining_ships < 3:
            result['success'] = False
            result['message'] = '需要至少3艘战舰才能发动'
            return True, True
        # 只取【活船】：沉船还留在 caster.ships 里，把它们也算进"牺牲"会重复入堆，
        # 复活类卡牌据此会把已经沉掉的船再恢复一次。
        sacrificed = alive_ships(caster)
        original_cells = [(p.x, p.y) for sh in sacrificed for p in sh.positions]

        # 牺牲 = 走完整击沉流程，不再"凭空消失"：
        #   ① 从 caster.ships 移入 caster.sunken_ships（供复活类回收）
        #   ② 置满命中，让"这艘船已经没了"在双方棋盘与 _is_ship_alive 上口径一致
        #   ③ 触发击沉通用副作用（无瑕圣心中断 / 百亿补贴 / 八方来财 / 恶魔契约）
        #
        # ⚠️ 通用副作用只结算【一次】，不能逐艘调 _on_ship_destroyed ——
        # 那会触发 N 次无瑕圣心中断与 N 次恶魔契约。
        for sh in sacrificed:
            sh.hits = list(sh.positions)  # 满命中 = 已沉
            if sh in caster.ships:
                caster.ships.remove(sh)
            if sh not in caster.sunken_ships:
                mark_ship_sunken(caster, sh)
        caster.remaining_ships = 0

        # ⚠️ 绝处逢生同样是"重摆自己棋盘"（全部牺牲 + 只放 1 艘）：这里也得终止
        #    自己棋盘上的范围效果与除外船 —— 少这一句，除外的船到期会 append 回来
        #    变成幽灵船（本项目实测过 6 艘变 8 艘）。
        clear_board_effects(room, [caster_id], '绝处逢生')

        if sacrificed:
            # ⚠️ 顺序要紧：**先**走击沉结算，**再**清跨回合效果。
            #    `_on_ship_destroyed` 会用 `holy_heart_interrupted`（"因船被沉而中断"）
            #    这个**更具体**的原因清掉无暇圣心；若我们先清，那条路径就什么都找不到，
            #    玩家看到的原因从"有船被击沉"退化成"棋盘被重摆"——语义变糊，
            #    而且 `tests/test_last_stand_and_steal_fix.py` 钉的就是前者。
            #    所以下面那句 `_clear_multiturn_effects` 必须排在击沉结算**之后**
            #    （它负责兜住"没被击沉路径清掉"的那些，比如玩家没牺牲任何船的情况）。
            on_ship_destroyed(room, caster_id, sacrificed[-1])
            # 逐艘公开广播，让双方棋盘都画出"这艘船没了"，而不是无声消失
            for sh in sacrificed:
                # ★ 回放批：自牺牲同样是**双方看得见的沉没** ⇒ 回放的船位时间线
                #   必须留下这几格（否则回放里它们凭空消失）。与上面那句广播同一份数据。
                replay.note_ship_lost(capture_replay_observation(room), caster_id,
                                      [{'x': p.x, 'y': p.y} for p in sh.positions])
                emit('ship_sacrificed', {
                    'player': caster_id,
                    'positions': [{'x': p.x, 'y': p.y} for p in sh.positions],
                    'reason': 'last_stand',
                }, room=room.id)
            emit_ships_updated(room)
            emit_player_ships(room, caster_id)

        # ⚠️ 兜底清理排在这里（击沉结算**之后**）：被 `holy_heart_interrupted`
        #    处理掉的不再重复，没被处理掉的（比如本局没牺牲任何船）由这里收口。
        #    跨回合计数效果是**房间级**的（记的是"再过几回合谁获胜"），
        #    绝处逢生虽只重摆自己的棋盘，也必须终止它们。
        clear_multiturn_effects(room, '绝处逢生')

        # 神机妙算按"沉船差值"判定，牺牲不是被击沉，需同步快照避免误判
        snap = room.game_effects.get(f'prediction_initial_{caster_id}')
        if isinstance(snap, dict):
            snap['sunken'] = len(caster.sunken_ships)

        room.game_effects['last_stand_cells'] = original_cells
        # ⚠️ 必须记下这批候选格是【谁棋盘上的】。两块棋盘各有自己的 0-5 坐标，
        # 不下发归属的话前端无从判断该高亮哪块 —— 实测（2026-09-16 作者反馈）
        # 施法者自己放绝处逢生时，他那几个候选格被画到了**对手棋盘**上，
        # 看着像"敌方可能在这儿"，直接误导他自己的攻击。
        room.game_effects['last_stand_owner'] = caster_id
        # 把"原本有战舰的格子"公开给双方 —— 对方要据此知道唯一一艘新船可能在哪，
        # 而且这些格子必须【能打】。
        #
        # ⚠️ 以前这里只发 ship_sacrificed（reason='last_stand'），前端把它当成
        # 「牺牲的船」画成红叉 —— 而红叉在玩家眼里就是"已打过、别再点了"，
        # 结果对方看着六个叉子根本不知道能打哪儿、也以为打不了（作者实测反馈）。
        # 现在改成下发一份"候选格"名单，前端画成高亮而不是叉。
        cells_payload = [{'x': cx, 'y': cy} for (cx, cy) in original_cells]
        emit('last_stand_cells', {'cells': cells_payload, 'owner': caster_id}, room=room.id)
        # 生效回合内其余魔法卡无效 + 击杀任何船直接获胜
        # ⚠️ 两个标记生命周期不同，别合并：
        #   last_stand     —— 锁卡，换小回合就被清（卡面写的是"在……生效的回合"）
        #   last_stand_win —— 击杀即胜，作者裁定"接下来所有回合"都有效，活到对局结束
        caster.effect_flags.last_stand = True
        caster.effect_flags.last_stand_win = True
        # 角标要在发动当场就亮起来。这里没有走"裁剪返回 True 才发"的那条路
        # （新标记是直接赋值的），所以得显式广播一次。
        emit_active_effects(room)
        start_placement(room, caster_id, 'last_stand', 1)
        result.temp_data_id = 'last_stand_choice'
        result['message'] = '已牺牲全部战舰，请在所有原本有战舰的格子上选择一格放置唯一一艘战舰'

    elif card.name == '回光返照':
        # 只能在自己先手时发动
        if room.attack_order and room.attack_order[0] != caster_id:
            result['success'] = False
            result['message'] = '只能在自己先手时发动'
            return True, True
        # 清空棋盘重新摆放6艘船
        # 棋盘换新 → 除外船不再是这批棋盘上的船；**范围效果也要终止**
        # ⚠️ 只清**自己**棋盘上的（对方棋盘没被重摆，那上面的区域照旧）
        clear_board_effects(room, [caster_id], '回光返照')
        # 同上：跨回合计数效果是房间级的，施法者重摆棋盘就得一起终止
        clear_multiturn_effects(room, '回光返照')
        caster.ships = []
        caster.remaining_ships = 0
        # ⚠️ 要清的是【对方打在我方棋盘上的记录】＝ `opponent.attacks`，
        # 不是 `caster.attacks`。两个数组是不同坐标空间：
        #   · caster.attacks   = 我打在【对方】棋盘上的格子 → 与本次重摆无关；
        #     清掉反而会把我已经探明的格子重新变成可打（白赚一炮）。
        #   · opponent.attacks = 对方打在【我方】棋盘上的格子 → 卡面
        #     「在使用回光返照后，也会清空对方视角中自己的棋盘」清的就是它。
        # 旧实现清错了那一份，于是玩家实测：「原本被打过 / 沉船的格子仍然会
        # 显示在使用回光返照者的棋盘上」。
        room.players[opponent_id].attacks = []
        # 标记需要重新摆放
        room.players[caster_id].needs_reset = True
        # 清空对方视角（显形记录 + 攻击历史一起清，否则前端本地缓存还画着 ✕）
        room.players[opponent_id].revealed_positions = []
        emit_board_attacks(room)
        # ★ 第 5 批：施法者那块棋盘整块换新 → 观众那块也得清空（作者实报的缺陷 ④）。
        #   重摆之后的**新位置仍然保密**：新位置的船没挨过炮，不在 `attacks` 里。
        mark_spectate_board_dirty(room)
        # ★ 回放批：回光返照**只清施法者那一块** → 棋盘标记只记他这一侧
        #   （传 caster_id，不要顺手把对手也标上）。
        replay.note_board_reset(capture_replay_observation(room), caster_id)
        # ★ 回放批：施法者旧棋盘上的"主动牺牲格"也一起作废（他的船全没了）。
        replay.note_board_replaced(capture_replay_observation(room), caster_id)

        # 跳过自己的战斗阶段
        room.current_phase = 'end'

        # ★ 2026-09-20 修（第二版）：让施法者进入**摆放阶段**，只发给他一个人。
        #
        # 卡面：「立即清空自己的棋盘，并在其上重新摆放 6 艘船。**跳过自己的战斗阶段**。
        #        接下来如果对方**在这一个大回合内**对任何一艘自己的船造成了伤害，
        #        那么自己直接判负。」
        #
        # ⚠️ 两条必须点，前一版各自栽过一次：
        #
        # ① **走服务端驱动的 `reset_gameboard`**（与败者食尘同一条路），
        #    而不是靠前端 `applyCardEffect` 的 `case '回光返照'`。
        #    那个 case 是**广播**处理器（双方都跑），会把对手也拽进布船界面，
        #    而且让"谁该重摆"有两份实现（前端 case + 服务端状态）。按 sid 单发天然只有施法者收到。
        #
        # ② `room.state` 显式置为 `'placing_ships'`。
        #    否则 `handle_place_ships` 的收尾判据 `all(len(p.ships) > 0 ...)`
        #    在"对手没被清船"时**恒为真**，直接掉进通用分支 → 收尾不受控。
        #
        # ③ ★ **`max_ships` 必须显式给一个数**。
        #    `Player.max_ships` 初值是 `None`，而 `reset_gameboard` 的
        #    `new_max_ships` 会被前端写进 `gameState.maxShips` ——
        #    传 None 过去，前端 `placedShips >= maxShips` 立刻成立 →
        #    **点格子没反应**，且 `ships` 始终为空 → 「布船数据无效」。
        #    （败者食尘在它那边显式设了 `player.max_ships = DEFAULT_SHIPS`，回光返照漏了。）
        room.state = 'placing_ships'
        room.attacks_remaining = 0          # 摆放期间本就没有攻击
        caster.max_ships = int(caster.max_ships or 6)
        # 标记"这次摆放属于回光返照" → `handle_place_ships` 走**本回合续行**的收尾
        room.huiguang_awaiting_placement = True
        emit('reset_gameboard', {
            'new_max_ships': caster.max_ships,
            'message': '回光返照生效，请重新摆放战舰',
        }, to=caster.sid)

        # ★ 2026-09-22 修：**AI 当施法者时，摆放必须在同一个调用里就地做完。**
        #
        # 上面那份 `reset_gameboard` 是 `to=caster.sid` 单发的，而 AI 的 sid 是
        # `'ai-'+room_id` —— **没有这条 socket 连接**，事件石沉大海；可
        # `room.state` 已经变成 `placing_ships` 了。于是房间停在"等待摆放"，
        # 等的人却是施法者自己（AI）。AI 的自救在 `_ai_master_turn` 的后台循环里
        # （`if room.state == 'placing_ships': _ai_place_board(...)`），那是
        # **异步**的、要等下一圈才跑 —— 中间这段窗口里真人既不在对局里、也没收到
        # 任何事件，表现就是作者实测的「棋盘上一艘船都没有、界面卡没了」。
        #
        # AI 没有 UI 要等，所以它就地摆完：`_ai_place_board` 走的是
        # `handle_place_ships`，也就是**玩家点"确认布船"时同一个入口**，
        # 收尾（`huiguang_awaiting_placement` 分支 → 回到自己的准备阶段、
        # 攻击次数为 0）一份不差。对手因此永远不会看到 `placing_ships`。
        #
        # ⚠️ 必须排在上面那个 emit **之后**：语义仍是"重摆 + 重摆完成"两条事件，
        #    只是不再有中间那段谁都不正常的窗口。
        # ⚠️ `_ai_seat_places_board_now` 内部对真人座位直接返回 False（真人要自己摆），
        #    这里绝不会替真人做选择。
        ai_seat_places_board_now(room, caster_id)

        # 设置效果：如果对方在这一大回合内对自己的船造成伤害，自己直接判负
        room.game_effects['last_chance'] = {
            'caster': caster_id,
            'active': True,
            'round': room.round,
        }

        # ★ 第 6 批：这一分支发出去的全是 `to=<sid>` 单发（`reset_gameboard` 给施法者、
        #   AI 施法时那份甚至没人收），`emit` 的收尾不跑 ⇒ 必须在这里自己收口。
        #   上面 `_mark_spectate_board_dirty` 已经**立刻**发过一帧（那一刻棋盘真的变了、
        #   观众必须知道），但它是"清格之后、`state` 还没推到 placing_ships"的中间态；
        #   这一句用**结算完之后**的真值覆盖掉它 —— 判据口径与其它三张卡一致：
        #   交给 `_flush_spectate_board_if_dirty` 统一收口，不在这里重写发布逻辑。
        flush_spectate_board_if_dirty(room)

        result['message'] = '已清空棋盘，请重新摆放战舰，本回合战斗阶段跳过。若对方在本大回合内对您的船造成伤害，您将直接判负'

    return True, False
