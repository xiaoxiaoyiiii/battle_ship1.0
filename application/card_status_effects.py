"""需要选择目标或设置持续状态的魔法卡效果。"""

STATUS_CARD_NAMES = frozenset({
    '灵气复苏', '越战越勇', '饮血', 'Freezing！', '五险一金',
    '明智埋葬', '仁王之盾', '八方来财', '百亿补贴',
    '死者苏生', '看破！', '增援',
})


def apply_status_card_effect(
        room, caster_id, card, result, emit, *,
        grant_extra_attacks, maybe_trigger_wuxian_yijin, field_magic_name,
        register_simple_ship_pick, start_placement):
    """结算一张状态/选择类魔法卡，返回（已处理，需提前结束）。"""
    if card.name not in STATUS_CARD_NAMES:
        return False, False
    opponent_id = next(p for p in room.players if p != caster_id)
    caster = room.players[caster_id]
    opponent = room.players[opponent_id]
    if card.name == '灵气复苏':
        # 计算双方最大船数，已修复
        max_ships = max(caster.remaining_ships, opponent.remaining_ships)
        if max_ships < 1:
            max_ships = 1

        # 存储临时数据，等待玩家选择船数
        room.magic_temp_data = {
            'type': 'lingqi_choice',
            'caster': caster_id,
            'opponent': opponent_id,
            'max_ships': max_ships
        }

        # 设置结果，只发送给施法者
        result.message = '请选择灵气复苏的船数'
        result.temp_data_id = 'lingqi_choice'
        result.max_ships = max_ships

        # 通知对手等待
        emit('lingqi_waiting', {
            'message': '对方正在结算灵气复苏效果 请等待'
        }, to=room.players[opponent_id].sid)

    elif card.name == '越战越勇':
        # 每击沉一艘战舰，攻击次数净增加1
        if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack['ship_sunk']:
            result['success'] = False
            result['message'] = '必须在击沉对方战舰后立即使用'
            return True, True
        # 添加越战越勇效果标记（本大回合内每次击沉都再 +1）
        room.players[caster_id].effect_flags.battle_spirit = True

        # ⚠️ 发动前提就是"刚刚击沉了一艘"，所以那一艘的 +1 必须【当场结算】。
        # 旧实现只挂标记，要等下一发击沉才生效 —— 玩家实测报「打完这张牌攻击次数
        # 没有任何变化，以为卡没生效」，而卡面写的是「攻击次数净增加1」。
        gained = grant_extra_attacks(room, caster_id, 1)
        if gained:
            result['message'] = (f'越战越勇生效：攻击次数 +{gained}'
                                 f'（当前 {room.attacks_remaining} 次），本大回合再击沉战舰还会 +1')
        else:
            result['message'] = '越战越勇生效，本回合击沉战舰时攻击次数净增加1'

    elif card.name == '饮血':
        # 卡面："可在击中对方后选择使用" —— 发动前提是自己上一次攻击【击沉了一艘船】。
        #
        # ⚠️ 判定依据必须是 last_attack['ship_sunk'] 而不是 ['hit']：
        #   hit 只说明那一格有船，ship_sunk 才是"击杀"。
        #   卡面后半句是"接下来每击杀一艘船抽一张牌"，拿 hit 当门槛会让玩家
        #   打中一艘没沉的船就以为能发动，实际摸不到牌。
        last = getattr(room, 'last_attack', None) or {}
        if not (last.get('attacker') == caster_id and last.get('ship_sunk')):
            result['success'] = False
            result['message'] = '需要在击沉对方一艘战舰后才能使用'
            return True, True
        room.players[caster_id].effect_flags.vampire = True

        # 刚打完的那一发「补算」：饮血是在击沉之后才打出的，若只对以后生效，
        # 玩家会觉得自己刚打沉的那艘白沉了。这里立即补摸一张。
        # （每张饮血只补一次 —— 它记录的就是"发动时那一次击沉"。）
        room.draw_card(caster_id)
        emit('message', {'text': '饮血发动，立即抽一张卡'}, to=room.players[caster_id].sid)
        result['message'] = '饮血生效：已为刚才击沉的战舰抽一张牌，接下来每击杀一艘船再抽一张。'

    elif card.name == 'Freezing！':
        # 发动条件（三条缺一不可）：
        #   1. 自己先手（attack_order[0]）
        #   2. 当前是结束阶段
        #   3. 本回合没有让对方船数减少
        if room.attack_order and room.attack_order[0] != caster_id:
            result['success'] = False
            result['message'] = 'Freezing！只能在自己先手的回合发动'
            return True, True
        if room.current_phase != 'end':
            result['success'] = False
            result['message'] = 'Freezing！只能在结束阶段发动'
            return True, True
        # damage_dealt_this_turn 只在击沉对方战舰时累加，等价于「让对方船数减少」
        if caster.damage_dealt_this_turn > 0:
            result['success'] = False
            result['message'] = '本回合已使对方船数减少，无法发动 Freezing！'
            return True, True
        # 跳过对方本回合的所有阶段
        room.skip_opponent_turn = opponent_id
        result['message'] = 'Freezing！生效，跳过对方本回合的所有阶段'

    elif card.name == '五险一金':
        # 教皇旨意生效中本回合任何人都没有攻击次数（场地规则），这张牌一次都触发不了，
        # 直接拒绝出牌，别让它白白浪费。
        if field_magic_name(room) == '教皇旨意':
            result['success'] = False
            result['message'] = '教皇旨意生效中，本回合攻击次数为0，五险一金无法发动'
            return True, True
        # 本回合已经让对方减过船 → 这张牌无论如何都不会再触发了，直接拒绝，别浪费一张卡
        if caster.damage_dealt_this_turn > 0:
            result['success'] = False
            result['message'] = '本回合已造成伤害，无法发动'
            return True, True
        # 只「挂上保险」：真正的 +3 要等本回合攻击次数第一次归零时才结算，
        # 不是一打出就白送 3 次（见 _maybe_trigger_wuxian_yijin）。
        caster.effect_flags.wuxian = True
        if maybe_trigger_wuxian_yijin(room, caster_id):
            # 出牌时攻击次数本来就已是 0：条件当场成立
            result['message'] = '攻击次数已用尽且未造成伤害，攻击次数 +3'
        else:
            result['message'] = '五险一金已生效：用完本回合所有攻击次数且未造成伤害时，攻击次数 +3'

    elif card.name == '明智埋葬':
        # 埋葬对象 = 牌堆中的卡 + 对方手牌（可埋葬对方手里的牌）
        deck = room.magic_deck or []
        opp_hand = opponent.magic_hand or []
        if not deck and not opp_hand:
            result['success'] = False
            result['message'] = '牌堆与对方手牌均为空，无法发动'
            return True, True
        # 候选池：先牌堆，后对方手牌（扁平下标 = 前端展示顺序）。
        # 只存纯数据、不存 MagicCard 实例：magic_temp_data 会被
        # get_magic_temp_data 原样 emit，实例无法 JSON 序列化。
        candidates = []
        for source, pile in (('deck', deck), ('opponent_hand', opp_hand)):
            for i, c in enumerate(pile):
                candidates.append({
                    'source': source, 'index': i, 'name': c.name, 'speed': c.speed,
                    'type': c.type, 'description': c.description,
                })

        room.magic_temp_data = {
            'type': 'bury_choice',
            'caster': caster_id,
            'candidates': candidates,
        }
        # index 是该卡在自己来源列表内的下标，前端回传 source_index 用它精确定位
        result['cards'] = [dict(c) for c in candidates]
        result['message'] = '请选择要埋葬的卡牌（牌堆或对方手牌）'
        result['temp_data_id'] = 'bury_choice'

    elif card.name == '仁王之盾':
        # 选择至多3艘船进入盾牌状态
        if caster.remaining_ships == 0:
            result['success'] = False
            result['message'] = '没有战舰可保护'
            return True, True
        # 记录需要选择的船
        # ⚠️ 这里**不能**改成 `pending_ship_picks` 的选船请求：仁王之盾是"至多 3 艘"
        #    的**多选**（走 `select_magic_target` 的 ship_indices），与
        #    "点一艘船"的 `confirm_sacrifice` 不是同一种交互。
        #    但仍然要在**优先级队列**里登记一条，理由：
        #      · 它同样会占用棋盘选区（前端 `selectingOnBoard`）；
        #      · 别的选船效果要能看到"这个人手上有优先级 40 的选船待办"。
        #    消费点在 `shield_choice` 的确认分支与 `cancel_magic_selection`。
        room.magic_temp_data = {
            'type': 'shield_choice',
            'caster': caster_id,
            'ships': caster.ships
        }
        register_simple_ship_pick(room, caster_id, 'shield_choice',
                                   '仁王之盾：请选择要保护的战舰（至多 3 艘）')
        result['message'] = '请选择要保护的战舰'
        result['temp_data_id'] = 'shield_choice'

    # ==== 速阶3 魔法卡 ====

    elif card.name == '八方来财':
        # 战舰数目主动变化时抽一张牌
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.treasure_hunter = True
        result['message'] = '战舰数目变化时抽一张牌'

    elif card.name == '百亿补贴':
        # 船被击败时攻击次数加3
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.subsidy = True
        result['message'] = '船被击败时攻击次数加3'

    elif card.name == '死者苏生':
        # 复活一艘船：必须有已阵亡的战舰，否则不可用。
        # 没有"6 艘上限"（作者确认：船数只受棋盘格数限制）。
        if not caster.sunken_ships:
            result['success'] = False
            result['message'] = '没有可复活的战舰'
            return True, True
        start_placement(room, caster_id, 'revive', 1)
        result.temp_data_id = 'revive_choice'
        result['message'] = '请选择复活战舰的部署位置（未被攻击过的空格）'

    elif card.name == '看破！':
        # 无效化对方本回合所有魔法卡
        room.players[opponent_id].magic_blocked = True
        result.message = '本回合对方魔法卡被无效化'

    elif card.name == '增援':
        # 召唤一艘战舰：等待玩家选择放置位置。
        # ⚠️ 没有"6 艘上限"这种东西 —— 作者确认船数只受棋盘格数（36 格）限制。
        # 旧实现在 remaining_ships >= 6 时直接拒绝，但那时牌已经离手
        # （handle_use_magic_card 先扣牌再结算），玩家被白吞一张卡。
        start_placement(room, caster_id, 'reinforce', 1)
        result.temp_data_id = 'reinforcement_choice'
        result.message = '请选择增援战舰的部署位置（未被攻击过的空格）'

    return True, False
