"""盗亦有道的连锁/历史取牌效果。"""


class StealEffects:
    """从连锁栈或历史中转移对手最近使用的魔法卡。"""

    CARD_NAME = '盗亦有道'

    def apply(self, room, caster_id, card, result):
        if card.name != self.CARD_NAME:
            return False, False

        stolen_card = None
        stolen_entry = None
        stolen_from_chain = False

        # 连锁按 LIFO 结算；当前项已经出栈，因此栈顶是紧邻下方、
        # 尚未进入 magic_history 的对手卡牌。
        target = room.chain[-1] if room.chain else None
        if target is not None and target.player_id != caster_id:
            stolen_card = target.card
            stolen_from_chain = True
        else:
            # 非连锁路径或栈顶属于自己时，回退到对手最近的历史记录。
            for entry in reversed(room.magic_history):
                if entry['caster'] != caster_id and not entry.get('negated_skip'):
                    stolen_entry = entry
                    stolen_card = entry['card']
                    break

        if stolen_card is None:
            result['success'] = False
            result['message'] = '对方没有使用过魔法卡'
            return True, True

        if stolen_entry is not None and stolen_entry.get('stolen'):
            result['success'] = False
            result['message'] = '该魔法卡已被盗取过'
            return True, True

        # 连锁里的牌还没有历史条目，用对象身份记录已盗取状态；
        # 不能写占位历史，否则结算后会产生可再次盗取的重复记录。
        ledger = room.game_effects.setdefault('stolen_cards', {})
        if id(stolen_card) in ledger:
            result['success'] = False
            result['message'] = '该魔法卡已被盗取过'
            return True, True

        # 从弃牌堆移除同一张牌，保证这是转移而不是复制。
        for i, candidate in enumerate(room.magic_discard):
            if (candidate is stolen_card
                    or (candidate.name == stolen_card.name
                        and candidate.speed == stolen_card.speed)):
                room.magic_discard.pop(i)
                break

        if stolen_from_chain:
            ledger[id(stolen_card)] = True
        else:
            stolen_entry['stolen'] = True
        room.players[caster_id].magic_hand.append(stolen_card)
        result['message'] = f'成功盗取对方的{stolen_card.name}'
        return True, False
