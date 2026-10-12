"""前七张基础魔法卡的实际效果；返回（已处理，需提前结束）。"""

OPENING_CARD_NAMES = frozenset({
    '余音绕梁', '桃园结义', '无中生有', '亡羊补牢',
    '极限增援', '无暇圣心', '火力全开',
})


def apply_opening_card_effect(room, caster_id, card, result, emit):
    if card.name not in OPENING_CARD_NAMES:
        return False, False
    opponent_id = next(p for p in room.players if p != caster_id)
    caster = room.players[caster_id]
    opponent = room.players[opponent_id]
    if card.name == '余音绕梁':
        # 卡面：只能在自己的准备阶段使用；接下来的「自己的攻击阶段」与
        # 「下一个回合自己的攻击阶段」造成伤害即强制击杀。
        # 因此 forced_kill 是【剩余攻击阶段数】，不是击杀次数：
        # 在 handle_attack 里只判断 >0，进入结束阶段时消耗一次。
        if room.current_phase != 'preparation' or room.current_attacker != caster_id:
            result['success'] = False
            result['message'] = '只能在自己的准备阶段使用'
            return True, True
        room.players[caster_id].effect_flags.forced_kill = 2
        result.message = '接下来两个攻击阶段（本回合与下一回合）将造成强制击杀'
    elif card.name == '桃园结义':
        # 无中生有生效期间双方都不能以任何方式获得魔法卡（原实现直接 pop 牌堆绕过）
        if caster.effect_flags.no_draw or room.players[opponent_id].effect_flags.no_draw:
            result['success'] = False
            result['message'] = '无中生有生效期间，双方无法获得魔法卡'
            return True, True
        # 从牌堆抽取n张牌(n为自己的战舰数)，自己选1张，再给对方选1张，已修复
        n = caster.remaining_ships
        drawn_cards = []

        # 只抽取牌堆中实际存在的牌
        for i in range(min(n, len(room.magic_deck))):
            drawn_cards.append(room.magic_deck.pop(0))

        if drawn_cards:
            # 记录待选择的牌
            room.magic_temp_data = {
                'type': 'taoyuan_choice',
                'caster': caster_id,
                'opponent': opponent_id,
                'cards': drawn_cards,
                'player_deck_backup': []  # 备份，用于记录放回的牌
            }
            result.message = f'抽了{len(drawn_cards)}张牌，请选择'
            result.temp_data_id = 'taoyuan_choice'
            result['cards'] = [{'name': c.name, 'speed': c.speed, 'type': c.type, 'description': c.description} for c in drawn_cards]
            # 通知对手等待
            emit('taoyuan_waiting', {
                'message': '对方正在结算桃园结义效果 请等待'
            }, to=room.players[opponent_id].sid)
        else:
            result.success = False
            result.message = '无法抽取卡牌'

    elif card.name == '无中生有':
        # 抽两张牌，本回合双方无法获得魔法卡。
        #
        # ⚠️ draw_card 可能返回 None（牌堆已空 / 已被 no_draw 挡下 / 摸到重名牌
        # 自动进弃牌堆），旧实现无论实际抽到几张都报"抽了2张牌"——
        # 实测玩家因此以为卡坏了（"手牌只有无中生有时只摸上来一张"，
        # 真实原因是全局共享的 43 张牌堆快摸完了）。
        # 这里按实际抽到的张数给提示，让玩家能区分"规则限制"和"牌堆空了"。
        drawn = 0
        for _ in range(2):
            if room.draw_card(caster_id) is not None:
                drawn += 1
        # 设置禁止抽卡标记
        room.players[caster_id].effect_flags.no_draw = True
        room.players[opponent_id].effect_flags.no_draw = True
        if drawn == 2:
            result.message = '抽了2张牌，本回合双方无法获得魔法卡'
        elif drawn == 1:
            result.message = '只抽到1张牌（牌堆不足），本回合双方无法获得魔法卡'
        else:
            result.message = '牌堆已空，没有抽到牌；本回合双方仍无法获得魔法卡'

    elif card.name == '亡羊补牢':
        # 从弃牌区最新 n 张里挑 1 张进手牌，其余回归弃牌堆。
        # n = 双方剩余船数的最大值（用户裁定）。
        # ⚠️ 候选不含刚打出的亡羊补牢自己：出牌扣牌流程已经把它 append 到
        # magic_discard 末尾，所以先把它 pop 出来暂存，结算后再放回。
        n = max(caster.remaining_ships, opponent.remaining_ships)
        # 暂存刚打出的亡羊补牢自己（位于 magic_discard 末尾）
        own_card = room.magic_discard.pop() if room.magic_discard else None
        # 防御性兜底：理论上 handle_use_magic_card 已经拦过发动条件，
        # 但连锁结算时弃牌堆可能被同批次的别的卡清空，这里再判一次。
        if not room.magic_discard or n <= 0:
            result.success = False
            result.message = '弃牌区没有可挑选的卡牌'
            if own_card is not None:
                room.magic_discard.append(own_card)
            return True, True
        # 从末尾取 min(n, len) 张作为候选（末尾是最新）
        take = min(n, len(room.magic_discard))
        candidates = room.magic_discard[-take:]
        del room.magic_discard[-take:]
        room.magic_temp_data = {
            'type': 'wangyang_choice',
            'caster': caster_id,
            'cards': candidates,         # MagicCard 实例列表（结算时引用同一对象）
            'own_card': own_card,        # 暂存的亡羊补牢自己，结算后回归弃牌堆
        }
        result['cards'] = [
            {'name': c.name, 'speed': c.speed, 'type': c.type, 'description': c.description}
            for c in candidates
        ]
        result.message = f'请从弃牌区最新{len(candidates)}张牌中选1张加入手牌'
        result.temp_data_id = 'wangyang_choice'

    elif card.name == '极限增援':
        # 两个大回合后，船少的一方获胜，已修复
        total_turns = 2
        room.game_effects["reinforcement_check"] = {
            'turn': room.round + total_turns,
            'caster': caster_id,
            'remaining_turns': total_turns,  # 添加剩余回合计数
            # 卡面：不算他生效的这个大回合 → 计数从下一个大回合才开始递减
            'activated_round': room.round,
        }
        # 通知双方客户端，极限增援已激活并显示剩余回合
        emit('reinforcement_activated', {
            'remaining_turns': total_turns
        }, room=room.id)
        result.message = '极限增援已激活，剩余2回合后结算'

    elif card.name == '无暇圣心':
        # 两个大回合后如果双方都没造成伤害，施法者获胜，已修复
        total_turns = 2
        room.game_effects['holy_heart'] = {
            'turn': room.round + total_turns,
            'caster': caster_id,
            'remaining_turns': total_turns,  # 剩余回合计数
            'no_damage': True  # 初始状态：双方都未造成伤害
        }
        # 通知双方客户端，无暇圣心已激活并显示剩余回合
        emit('holy_heart_activated', {
            'remaining_turns': total_turns
        }, room=room.id)
        result.message = '无暇圣心已激活，剩余2回合后结算'

    elif card.name == '火力全开':
        # 本回合攻击次数翻倍。
        #
        # ⚠️ 不能只设标记等 enter_battle_phase 去消费：那是速阶1的卡，
        # can_play_magic_card 允许它在【战斗阶段】使用，而阶段转换早已发生
        # （且 enter_battle_phase 在 phase 已是 battle 时直接返回 error），
        # 标记就永远没人读 —— 实测：战斗阶段打出后 attacks 仍是 6 不翻倍，
        # 标记一直挂着，玩家白扔一张牌还以为生效了。
        # 卡面是「在这一个大回合内自己的攻击阶段时，自己的攻击次数翻倍」，
        # 所以：还在准备阶段就留给 enter_battle_phase 翻（那时才知道最终次数）；
        # 已经进入战斗阶段就【立即】翻当前次数。
        #
        # ⚠️ 基准是【当前攻击次数】attacks_remaining，不是「船数 - 冻结数」。
        # 旧实现按船数重算，会把教皇旨意等场地压过的次数还原回来 ——
        # 作者实测：自己先打教皇旨意（次数归 0），对方火力全开却照样
        # 拿到 2×船数 的次数。翻倍就该是「现在有几次，就变成几次的两倍」，
        # 已经是 0 的话翻倍仍是 0。
        flags = room.players[caster_id].effect_flags
        in_battle = (room.state == 'attacking'
                     and room.current_phase == 'battle'
                     and room.current_attacker == caster_id)
        if in_battle and not flags.double_attacks:
            room.attacks_remaining = max(0, room.attacks_remaining) * 2
            flags.double_attacks = False      # 已当场消费，不再留给阶段转换
            emit('attacks_updated', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining
            }, room=room.id)
            result.message = f'本回合攻击次数翻倍，当前攻击次数为{room.attacks_remaining}'
        else:
            flags.double_attacks = True
            result.message = '本回合攻击次数翻倍'

    return True, False
