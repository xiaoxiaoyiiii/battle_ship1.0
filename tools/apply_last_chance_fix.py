# -*- coding: utf-8 -*-
"""对 server.py 做锚点精确替换（回光返照判负收敛）。每处替换必须恰好命中一次。"""
import io
import re
import sys

PATH = r'd:\develop\battle_ship1.0\server.py'
text = io.open(PATH, encoding='utf-8').read()
orig = text

FUNC = '''def _check_last_chance(room, attacker_id: str, defender_id: str) -> bool:
    """回光返照：对使用者的船造成伤害则其直接判负。返回是否触发。"""
    if room.game_effects.get('last_chance') and room.game_effects['last_chance']['caster'] == defender_id:
        room.state = 'game_over'
        room.winner = attacker_id
        add_game_log(room, f"{room.players[defender_id].name or defender_id} 触发回光返照失败并判负", 'result', {
            'winner': attacker_id,
            'loser': defender_id
        })
        # 记录战绩（若为已登录用户）
        try:
            winner_user_id = room.players[attacker_id].user_id
            loser_user_id = room.players[defender_id].user_id
            if winner_user_id or loser_user_id:
                db.record_match(winner_user_id or attacker_id, loser_user_id or defender_id, getattr(room, 'game_logs', None))
        except Exception:
            pass
        emit('game_over', {'winner': attacker_id}, room=room.id)
        return True
    return False


'''

# 1. 在 attack 事件处理器前插入 _check_last_chance
anchor1 = "@socketio.on('attack')\ndef handle_attack(data):"
assert text.count(anchor1) == 1, 'anchor1 not unique'
text = text.replace(anchor1, FUNC + anchor1, 1)

# 2. 强制击杀分支的内联判负块 -> 统一调用
pattern2 = re.compile(
    r"                # 检查回光返照效果\n"
    r"                if room.game_effects.get\('last_chance'\) and room.game_effects\['last_chance'\]\['caster'\] == defender_id:.*?return \{'status': 'success', 'game_over': True\}\n",
    re.S)
m = pattern2.findall(text)
assert len(m) == 1, f'pattern2 matched {len(m)}'
text = pattern2.sub(
    "                # 检查回光返照效果（统一走 _check_last_chance）\n"
    "                if _check_last_chance(room, attacker_id, defender_id):\n"
    "                    return {'status': 'success', 'game_over': True}\n",
    text, count=1)

# 3. 普通攻击分支：命中记录后插入判负检查
anchor3 = (
    "                else:\n"
    "                    # 记录击中位置\n"
    "                    defender_ships[i].hits = defender_ships[i].hits + [Position(x=target_x, y=target_y)]\n"
)
assert text.count(anchor3) == 1, 'anchor3 not unique'
text = text.replace(anchor3, anchor3 + (
    "\n"
    "                    # 检查回光返照效果：造成伤害即判负（与强制击杀分支一致）\n"
    "                    if _check_last_chance(room, attacker_id, defender_id):\n"
    "                        return {'status': 'success', 'game_over': True}\n"
), 1)

# 4. _do_attack 的内联判负块 -> 统一调用
anchor4 = (
    "                    if room.game_effects.get('last_chance') and room.game_effects['last_chance']['caster'] == defender_id:\n"
    "                        room.state = 'game_over'\n"
    "                        room.winner = attacker_id\n"
    "                        emit('game_over', {'winner': attacker_id}, room=room_id)\n"
    "                        return {'game_over': True}\n"
)
assert text.count(anchor4) == 1, 'anchor4 not unique'
text = text.replace(anchor4, (
    "                    if _check_last_chance(room, attacker_id, defender_id):\n"
    "                        return {'game_over': True}\n"
), 1)

assert text != orig
with io.open(PATH, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
print('4 replacements applied')
