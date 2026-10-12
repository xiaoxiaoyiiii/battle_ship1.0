"""大厅房间与在线状态的公开投影及等待房回收规则。"""

import time


def lobby_occupied_sids(rooms) -> tuple:
    """一次遍历算出两拨人：真正在打的（in_game）与只是在房里等人的（in_room）。

    ⚠️ **必须区分这两拨**：建房者一按下「创建房间」就坐在自己的房里了，
    而那个房间的 state 是 'waiting' —— 把它算成"对局中"的话，大厅里所有
    开过房的人永远显示"对局中"，而他们其实完全可以被别人拉进一局。
    （浏览器工具实测抓到的：A 建房后在自己那一行显示"对局中"。）
    """
    in_game, in_room = set(), set()
    for room in rooms.values():
        state = getattr(room, 'state', None)
        if state == 'game_over':
            continue
        bucket = in_room if state == 'waiting' else in_game
        for player in room.players.values():
            if player.sid:
                bucket.add(player.sid)
    return in_game, in_room



def lobby_player_status(sid: str, in_game: set, in_room: set, is_matching: bool) -> str:
    """大厅里的四态之一：matching / in_game / in_room / idle。

    ⚠️ 顺序不能反：匹配中**优先于**对局中。匹配成功后队列条目立刻被 pop，
    两者不会同时成立；但先判对局会让"刚配到、还没进房"的一瞬显示成空闲。
    """
    if is_matching:
        return 'matching'
    if sid in in_game:
        return 'in_game'
    if sid in in_room:
        return 'in_room'
    return 'idle'



def recycle_host_waiting_rooms(rooms, player_id: str, drop_room) -> list:
    """回收该玩家**之前主持的、还没人入座**的等待房，返回被回收的 room_id 列表。

    ★ 为什么必须有它（2026-09-18 大厅批上线后实测的缺陷）：
    作者截图里大厅房间列表挂着 **7 间一模一样的房**（同名、同房主、都是 1/2）。
    复现确认「一次点击 = 一间房」（ack 正常、界面也正常跳到自定义房界面），
    所以不是双击/重复绑定 —— 是**玩家每回大厅点一次「创建房间」就多一间，而旧房
    永远不会消失**：

      · 等待房的回收 TTL 是 1 小时（`_WAITING_ROOM_TTL`）；
      · 大厅的可见规则只要求「房主仍在线」，而房主就是他自己 —— 当然一直在线上。

    于是两条规则各自都"没错"，合起来却把 7 间房全留在了榜上。
    规则改成：**一个玩家同时最多主持一间等待中的房**，再次建房 = 换一间。
    （只回收 `waiting` 且房内恰好 1 人、且那个人就是自己的房 —— 已经开打的、
    或者已经有人入座的房一律不碰。）
    """
    reaped = []
    for room_id, room in list(rooms.items()):
        if getattr(room, 'state', None) != 'waiting':
            continue
        entries = list(room.players.items())
        if len(entries) != 1 or entries[0][0] != player_id:
            continue
        drop_room(room_id, '建房时回收自己上一间等待房')
        reaped.append(room_id)
    return reaped



def visible_lobby_rooms(rooms, online_sids) -> list[dict]:
    """大厅房间列表。可见规则见 docs/LOBBY_2026_09_18.md §1.4。

    最容易被漏掉的是第 4 条「房主仍在线」：房间的回收 TTL 是 1 小时
    （_WAITING_ROOM_TTL），房主关掉标签页后房间还要在内存里躺一小时 ——
    不加这条就会在大厅里挂出一堆"点进去没人"的僵尸房。

    第 5 条（**同一房主只列最新的一间**）是防御性的：正常路径下
    `_recycle_host_waiting_rooms` 已经保证一个玩家只有一间等待房，但历史遗留
    （本批上线前建的房）、或者日后新增的建房路径都可能绕过它 —— 列表层再兜一次，
    大厅就永远不会出现"同一个人的一串同名房"。
    """
    online = set(online_sids)
    rows = []
    seen_hosts = set()
    # 按建房时间**倒序**扫：同一房主先命中的就是最新的那一间
    ordered = sorted(rooms.values(),
                     key=lambda r: getattr(r, 'created_at', 0) or 0, reverse=True)
    for room in ordered:
        if getattr(room, 'state', None) != 'waiting':
            continue
        if getattr(room, 'is_ai_room', False):
            continue
        if not bool(getattr(room, 'public', True)):
            continue
        entries = list(room.players.items())
        if len(entries) != 1:
            continue
        host_key, host = entries[0]
        if not host.sid or host.sid not in online:
            continue
        if host_key in seen_hosts:
            continue          # 同一房主的第二间（见上面的第 5 条）
        seen_hosts.add(host_key)
        rows.append({
            'room_id': room.id,
            'name': str(getattr(room, 'name', '') or '') or f'{host.name}的房间',
            'host': host.name,
            'players': 1,
            'capacity': 2,
            'created_at': int(getattr(room, 'created_at', 0) or 0),
        })
    rows.sort(key=lambda r: r['created_at'])
    return rows



def project_lobby_state(*, lobby_manager, room_manager, repository,
                        level_from_xp, rank_view, live_matches,
                        max_players: int, ranked_mode: str) -> dict:
    """组装一份 lobby_state（契约见 docs/LOBBY_2026_09_18.md §1.3）。

    每次广播现算：房间/队列/在线都在内存里，只有等级与段位要查库，且都是
    **批量**接口（一次 IN (...) 取完），绝不逐人查。
    """
    now = time.time()
    presence = lobby_manager.presence()
    members = set(lobby_manager.members())
    in_game, in_room = lobby_occupied_sids(room_manager.get_all_rooms())

    # 队列分 mode 计数（休闲 / 排位共用同一个队列）
    queue = list(room_manager.match_queue)
    ranked_n = sum(1 for e in queue if e.get('mode') == ranked_mode)
    casual_n = len(queue) - ranked_n

    # 按连接时间排序，超出上限直接截断（契约 §5：本批不做分页）
    ordered = sorted(presence.items(), key=lambda kv: kv[1].get('connected_at') or 0)
    ordered = ordered[:max_players]

    uids = [str(row.get('user_id')) for _, row in ordered if row.get('user_id')]
    try:
        xp_map = repository.get_xp_map(uids) if uids else {}
    except Exception:
        xp_map = {}
    try:
        rank_map = repository.get_rank_map(uids) if uids else {}
    except Exception:
        rank_map = {}

    players = []
    for sid, row in ordered:
        uid = row.get('user_id')
        uid_s = str(uid) if uid else ''
        profile = lobby_manager.profile_of(sid)
        level = 1
        if uid_s:
            try:
                level = level_from_xp(int(xp_map.get(uid_s, 0) or 0))
            except Exception:
                level = 1
        rank = None
        points_row = rank_map.get(uid_s) if uid_s else None
        if points_row is not None:
            try:
                points = points_row.get('points') if isinstance(points_row, dict) else points_row
                view = rank_view(points)
                rank = {'tier_id': view['tier_id'], 'tier_name': view['tier_name'],
                        'label': view['label']}
            except Exception:
                rank = None
        players.append({
            'key': sid,
            'name': row.get('name') or '游客',
            'guest': not bool(uid_s),
            'in_lobby': sid in members,
            'status': lobby_player_status(sid, in_game, in_room,
                                           room_manager.has_player_in_match_queue(sid)),
            'avatar': profile.get('avatar') or '',
            'level': level,
            'name_style': profile.get('name_style') or '',
            'title': profile.get('title') or '',
            'rank': rank,
        })

    return {
        'ts': int(now),
        'online_count': len(presence),
        'lobby_count': len(members),
        'queue': {'casual': casual_n, 'ranked': ranked_n},
        'players': players,
        'rooms': visible_lobby_rooms(room_manager.get_all_rooms(), presence.keys()),
        # ★ 进行中的对局（观战入口）。**与 `rooms` 分开**是硬要求：
        #   `rooms` = "点进去入座"，`matches` = "点进去观战"，混在一起玩家会点错。
        #   契约见 docs/LOBBY_2026_09_18.md §1.3。
        'matches': live_matches(),
    }
