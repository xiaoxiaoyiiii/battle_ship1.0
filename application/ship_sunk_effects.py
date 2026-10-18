"""战舰被击沉后的共享副作用。"""


class ShipSunkEffects:
    def __init__(self, *, grant_subsidy, opponent_of, alive_ships,
                 request_ship_pick, sacrifice, emit_player_ships,
                 demon_contract, treasure, emit, log, log_name):
        self._grant_subsidy = grant_subsidy
        self._opponent_of = opponent_of
        self._alive_ships = alive_ships
        self._request_ship_pick = request_ship_pick
        self._sacrifice = sacrifice
        self._emit_player_ships = emit_player_ships
        self._demon_contract = demon_contract
        self._treasure = treasure
        self._emit = emit
        self._log = log
        self._log_name = log_name

    def trigger_trap(self, room, owner_id, sunk_ship):
        opponent_id = self._opponent_of(room, owner_id)
        if not opponent_id or opponent_id not in room.players:
            return
        opponent = room.players[opponent_id]
        need = min(2, len(self._alive_ships(opponent)))
        if need <= 0:
            self._emit('trap_triggered', {
                'owner': owner_id,
                'sunk_positions': [{'x': p.x, 'y': p.y} for p in sunk_ship.positions],
                'sacrificed': 0,
                'message': '陷阱触发，但对方没有可牺牲的战舰',
            }, room=room.id)
            return
        self._emit('trap_triggered', {
            'owner': owner_id,
            'sunk_positions': [{'x': p.x, 'y': p.y} for p in sunk_ship.positions],
            'sacrificed': need,
            'message': f'陷阱触发！对方需牺牲{need}艘战舰',
        }, room=room.id)
        self._log(
            room,
            f'第{room.round}回合 · {self._log_name(room, owner_id)} 的【守株待兔】陷阱被踩中，'
            f'对方需牺牲{need}艘战舰',
            'magic', {'owner': owner_id, 'card': '守株待兔', 'sacrifice': need},
        )
        for _ in range(need):
            picked = self._request_ship_pick(
                room, opponent_id, 'trap_sacrifice',
                '守株待兔：请点选一艘战舰牺牲', allow_duplicate=True)
            if picked is not None:
                self._sacrifice(room, opponent_id, picked, 'trap_sacrifice')

    def on_destroyed(self, room, owner_id, ship):
        self._grant_subsidy(room, owner_id)
        if 'holy_heart' in room.game_effects:
            del room.game_effects['holy_heart']
            self._emit('holy_heart_interrupted', {
                'reason': '有战舰被击沉，无暇圣心效果中断',
            }, room=room.id)
        if getattr(ship, 'trap', False):
            ship.trap = False
            self.trigger_trap(room, owner_id, ship)
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
