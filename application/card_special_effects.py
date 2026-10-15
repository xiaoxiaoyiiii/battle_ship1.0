"""神威！、神之宣告和疗愈的魔法卡效果。

本模块只包含三张特殊魔法卡的结算逻辑。它不依赖 ``server``：对局运行时的
广播、回放、船只选择和其它副作用都通过构造器显式注入，方便在不启动 Socket.IO
服务的情况下测试，也让卡牌结算可以继续从 ``server.py`` 独立演进。
"""


class SpecialCardEffects:
    """结算三张需要较多运行时依赖的特殊魔法卡。"""

    def __init__(
            self, *, opponent_of, add_shenwei_hole, emit,
            replay_note_ship_lost, capture_replay_observation,
            mark_ship_sunken, apply_ship_loss_linkage, finish_game,
            replay_refresh_ships, find_ship_at, alive_ships, shuffle,
            request_ship_pick, sacrifice_ship, revive_sunken_ships,
            emit_ships_updated, emit_player_ships):
        self._opponent_of = opponent_of
        self._add_shenwei_hole = add_shenwei_hole
        self._emit = emit
        self._replay_note_ship_lost = replay_note_ship_lost
        self._capture_replay_observation = capture_replay_observation
        self._mark_ship_sunken = mark_ship_sunken
        self._apply_ship_loss_linkage = apply_ship_loss_linkage
        self._finish_game = finish_game
        self._replay_refresh_ships = replay_refresh_ships
        self._find_ship_at = find_ship_at
        self._alive_ships = alive_ships
        self._shuffle = shuffle
        self._request_ship_pick = request_ship_pick
        self._sacrifice_ship = sacrifice_ship
        self._revive_sunken_ships = revive_sunken_ships
        self._emit_ships_updated = emit_ships_updated
        self._emit_player_ships = emit_player_ships

    def apply_shenwei(self, room, caster_id, card, target_data, result):
        """结算「神威！」。

        与迁出前的兼容入口相同：参数错误时返回 ``result``，正常结算不显式
        返回值（由 ``apply_magic_effect`` 统一返回它自己的 ChainResult）。
        """
        opponent_id = self._opponent_of(room, caster_id)
        caster = room.players[caster_id]
        opponent = room.players[opponent_id]

        # 选定己方/对方棋盘上的 3*3 区域：该区域从棋盘上“扣掉”，区域内战舰
        # 暂时除外，下一个大回合开始时回归原位、区域恢复。
        if 'target_area' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标区域'
            return result
        area = target_data['target_area']
        board = target_data.get('board', 'opponent')  # 'self' | 'opponent'
        target_id = caster_id if board == 'self' else opponent_id
        target_player = room.players[target_id]

        # 收集并移除区域内的战舰。
        excluded_ships = []
        for i in range(len(target_player.ships) - 1, -1, -1):
            ship = target_player.ships[i]
            in_area = any(
                area['x1'] <= pos.x <= area['x2']
                and area['y1'] <= pos.y <= area['y2']
                for pos in ship.positions
            )
            if in_area:
                excluded_ships.append(ship)
                del target_player.ships[i]
                target_player.remaining_ships -= 1

        # 把这片区域从棋盘上扣掉（下个大回合恢复）。
        return_turn = room.round + 1
        self._add_shenwei_hole(room, target_id, area, return_turn)
        self._emit('shenwei_hole', {
            'player': target_id, 'area': area, 'return_turn': return_turn
        }, room=room.id)

        # 卡面：仅当作用于对方棋盘且区域内恰好 1 艘船时，直接死亡。
        if board != 'self' and len(excluded_ships) == 1:
            # 这一支是致死，不是暂时除外：登记沉没格供回放使用。
            ship = excluded_ships[0]
            self._replay_note_ship_lost(
                self._capture_replay_observation(room), target_id,
                [{'x': p.x, 'y': p.y} for p in ship.positions],
            )
            self._mark_ship_sunken(target_player, ship)
            self._apply_ship_loss_linkage(
                room, caster_id, opponent_id, count=1)
            result['message'] = '目标区域内1艘战舰被击沉'
        else:
            room.game_effects.setdefault('excluded_ships', []).append({
                'ships': excluded_ships,
                'player': target_id,
                'return_turn': return_turn,
            })
            if excluded_ships:
                self._apply_ship_loss_linkage(
                    room, caster_id, target_id, count=len(excluded_ships))
            result['message'] = (
                f'目标区域内{len(excluded_ships)}艘战舰被暂时除外')

        self._emit_ships_updated(room)

        # 斩杀线：对方船被清空直接获胜；己方自扣清空则判负。
        if opponent.remaining_ships <= 0 and room.state != 'game_over':
            self._finish_game(
                room, caster_id, opponent_id, '神威！清空对方棋盘')
            result['message'] += '，对方战舰全灭，直接获胜'
        elif caster.remaining_ships <= 0 and room.state != 'game_over':
            self._finish_game(
                room, opponent_id, caster_id, '神威！清空己方棋盘')
            result['message'] += '，己方战舰全灭，判负'

        # 船位/船数全部落定之后再刷新回放船位时间线。refresh 是幂等的，
        # 因此既可覆盖直调 apply_magic_effect 的调用，也不会重复写入快照。
        self._replay_refresh_ships(self._capture_replay_observation(room))

    def apply_divine_decree(self, room, caster_id, card, target_data, result):
        """结算「神之宣告」。"""
        opponent_id = self._opponent_of(room, caster_id)
        caster = room.players[caster_id]

        # 牺牲两艘后至少保留一艘。
        if caster.remaining_ships <= 2:
            result['success'] = False
            result['message'] = '您的船数不足，无法使用神之宣告'
            return result

        # 优先采用玩家点选的两艘；非法/不足时用随机补齐（AI 与老客户端仍可出牌）。
        chosen = []
        cells = target_data.get('selected_cells') if isinstance(target_data, dict) else None
        if isinstance(cells, list):
            for cell in cells:
                try:
                    pos = (int(cell.get('x')), int(cell.get('y')))
                except (AttributeError, TypeError, ValueError):
                    continue
                # alive_only：点到沉船的格子不算数。
                ship_at = self._find_ship_at(caster, pos, alive_only=True)
                if ship_at is not None and ship_at not in chosen:
                    chosen.append(ship_at)

        if len(chosen) < 2:
            pool = [s for s in self._alive_ships(caster) if s not in chosen]
            self._shuffle(pool)
            chosen.extend(pool[:2 - len(chosen)])
        if len(chosen) < 2:
            result['success'] = False
            result['message'] = '您的船数不足，无法使用神之宣告'
            return result

        # 逐个走统一结算：移船、记日志、公开广播及按视角刷船数。
        for sacr in chosen[:2]:
            self._sacrifice_ship(room, caster_id, sacr, 'divine_decree')

        # 获取选择的效果：优先出牌时携带的 effect_choice，回退到临时数据，缺省为 1。
        if isinstance(target_data, dict) and target_data.get('effect_choice'):
            try:
                effect_choice = int(target_data['effect_choice'])
            except (TypeError, ValueError):
                effect_choice = 1
        else:
            try:
                effect_choice = int(room.magic_temp_data.get('effect_choice', 1))
            except (TypeError, ValueError):
                effect_choice = 1

        if effect_choice == 1:
            # 让对方自己选择一艘船；AI 由服务端代选。
            picked = self._request_ship_pick(
                room, opponent_id, 'divine_decree',
                '神之宣告生效：请点选一艘自己的战舰，使其阵亡')
            if picked is not None:
                self._sacrifice_ship(
                    room, opponent_id, picked, 'divine_decree')
                result['message'] = '牺牲两艘战舰，对方一艘战舰被摧毁'
            else:
                result['message'] = '牺牲两艘战舰，等待对方选择阵亡的战舰'
        else:
            # 跳过对方本大回合内的所有阶段（存玩家 ID）。
            room.skip_opponent_stages = opponent_id
            result['message'] = '牺牲两艘战舰，跳过对方本回合所有阶段'

    def apply_healing(self, room, caster_id, card, target_data, result):
        """结算「疗愈」。"""
        caster = room.players[caster_id]
        if not caster.sunken_ships:
            result['success'] = False
            result['message'] = '没有可复活的战舰'
            return result

        # 卡面：选定自己至多两艘被击杀的船并在原地复活。
        count = min(2, len(caster.sunken_ships))
        revived = self._revive_sunken_ships(
            room, caster, count,
            reveal_to=self._opponent_of(room, caster_id),
        )
        self._emit_ships_updated(room)
        self._emit_player_ships(room, caster_id)
        result['message'] = f'疗愈生效，{revived} 艘战舰在原地复活'

    def apply(self, room, caster_id, card, target_data, result):
        """按卡名分派；返回 ``(handled, stop)``。"""
        if card.name == '神威！':
            self.apply_shenwei(room, caster_id, card, target_data, result)
            return True, True
        if card.name == '神之宣告':
            self.apply_divine_decree(
                room, caster_id, card, target_data, result)
            return True, True
        if card.name == '疗愈':
            self.apply_healing(room, caster_id, card, target_data, result)
            return True, True
        return False, False
