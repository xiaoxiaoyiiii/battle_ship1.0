"""战舰被击沉后的共享副作用。"""


class ShipSunkEffects:
    def __init__(self, *, grant_subsidy, trigger_trap, emit_player_ships,
                 demon_contract, treasure, emit, log):
        self._grant_subsidy = grant_subsidy
        self._trigger_trap = trigger_trap
        self._emit_player_ships = emit_player_ships
        self._demon_contract = demon_contract
        self._treasure = treasure
        self._emit = emit
        self._log = log

    def on_destroyed(self, room, owner_id, ship):
        self._grant_subsidy(room, owner_id)
        if 'holy_heart' in room.game_effects:
            del room.game_effects['holy_heart']
            self._emit('holy_heart_interrupted', {
                'reason': '有战舰被击沉，无暇圣心效果中断',
            }, room=room.id)
        if getattr(ship, 'trap', False):
            ship.trap = False
            self._trigger_trap(room, owner_id, ship)
        self._emit_player_ships(room, owner_id)

    @staticmethod
    def mark_sunken(player, ship):
        if ship is None:
            return False
        sunken = getattr(player, 'sunken_ships', None)
        if sunken is None:
            player.sunken_ships = sunken = []
        if ship in sunken:
            return False
        sunken.append(ship)
        return True

    def apply(self, room, room_id, attacker_id, defender_id, ship,
              exclude_attacker_from_treasure=True,
              request_demon_contract=True):
        defender = room.players[defender_id]
        defender.remaining_ships -= 1
        self.mark_sunken(defender, ship)
        self.on_destroyed(room, defender_id, ship)
        if request_demon_contract and room.game_effects.get('demon_contract'):
            self._demon_contract(room, defender_id)
        if exclude_attacker_from_treasure:
            self._treasure(room, 1, exclude_player_id=attacker_id)
        else:
            self._treasure(room, 1)
        if 'holy_heart' in room.game_effects:
            del room.game_effects['holy_heart']
            self._emit('holy_heart_interrupted', {
                'reason': '有战舰被击沉，无暇圣心效果中断',
            }, room=room_id)
