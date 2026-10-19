"""普通 AI 回合循环。"""

def turn_loop(room_id: str, *, pause, get_room, ai_player, is_master, master_turn, enter_battle, play_magic, choose_attack, attack, enter_end, end_turn, log_error):
    """AI回合：进入战斗阶段→随机攻击至次数耗尽→结束阶段→交出回合。"""
    try:
        pause(room_id, 1)
        room = get_room(room_id)
        if not room or room.state == 'game_over':
            return
        ai_id = ai_player(room)
        if not ai_id or room.current_attacker != ai_id:
            return
        if is_master(room, ai_id):
            return master_turn(room_id, room, ai_id)
        enter_battle({'room_id': room_id, 'player_id': ai_id})

        # 先出一张安全卡（normal / hard 难度）。出牌可能打开连锁响应窗口，
        # 而连锁未结算时攻击会被 attack 门禁拒绝 —— 必须等窗口关闭再开炮，
        # 否则 AI 的攻击会全军覆没、回合草草结束。
        play_magic(room, ai_id)
        for _ in range(40):
            room = get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            if not (room.chain or room.chain_waiting):
                break
            pause(room_id, 0.3)

        for _ in range(40):
            room = get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            if room.attacks_remaining <= 0:
                break
            shot = choose_attack(room, ai_id)
            if shot is None:
                break
            x, y = shot
            attack({'room_id': room_id, 'player_id': ai_id, 'x': x, 'y': y})
            pause(room_id, 0.3)
        room = get_room(room_id)
        if not room or room.state == 'game_over' or room.current_attacker != ai_id:
            return

        # 收尾必须重试：连锁若还没结算完，enter_end_phase / end_turn 会被门禁拒绝，
        # 而 AI 回合没有别的触发点 —— 一旦这里失败，回合就会永远停在 AI 手上，
        # 真人只能干等（此前 AI 不出牌，所以碰不到这个竞态）。
        for _ in range(20):
            room = get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            if room.chain or room.chain_waiting:
                pause(room_id, 0.5)
                continue
            resp = enter_end({'room_id': room_id, 'player_id': ai_id})
            if resp and resp.get('status') == 'success':
                break
            pause(room_id, 0.5)
        pause(room_id, 0.5)

        for _ in range(20):
            room = get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            resp = end_turn({'room_id': room_id, 'player_id': ai_id})
            if resp and resp.get('status') == 'success':
                return
            pause(room_id, 0.5)
    except Exception as e:
        log_error(e)
