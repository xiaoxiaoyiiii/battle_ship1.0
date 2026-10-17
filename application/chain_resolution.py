"""连锁栈逐项结算。"""


class ChainResolution:
    def __init__(self, *, chain_result, apply_effect, log_magic,
                 refund_card, now):
        self._chain_result = chain_result
        self._apply_effect = apply_effect
        self._log_magic = log_magic
        self._refund_card = refund_card
        self._now = now

    def resolve_items(self, room):
        results = []
        while room.chain:
            chain_item = room.chain.pop()
            player_id = chain_item.player_id
            card = chain_item.card
            targets = chain_item.targets
            if chain_item.negated:
                by = getattr(chain_item, 'negated_by', None)
                detail = f'{card.name}被{by}无效化' if by else f'{card.name}被无效化'
                result = self._chain_result(
                    card=card, caster=player_id, success=False, message=detail)
                result.negated_skip = True
                result.negated_by = by
                self._log_magic(room, player_id, card,
                                f'但被{by}无效化' if by else '但被无效化')
                if getattr(card, 'type', None) == '场地' and room.field_magic is not card:
                    room.magic_discard.append(card)
                results.append(result)
                continue

            result = self._apply_effect(room, player_id, card, targets)
            result.caster = player_id
            self._log_magic(
                room, player_id, card,
                result.message if getattr(result, 'success', False) else '',
            )
            if (not getattr(result, 'success', False)
                    and not getattr(result, 'negated_skip', False)):
                self._refund_card(room, player_id, card, result)
            if getattr(result, 'negate_target', False) and room.chain:
                room.chain[-1].negated = True
                room.chain[-1].negated_by = card.name
            results.append(result)
            if result.success:
                entry = {
                    'card': card,
                    'caster': player_id,
                    'timestamp': self._now(),
                    'round': room.round,
                }
                ledger = room.game_effects.get('stolen_cards') or {}
                if id(card) in ledger:
                    entry['stolen'] = True
                room.magic_history.append(entry)
        return results
