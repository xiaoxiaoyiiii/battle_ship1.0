"""AI 回合结算收敛判据。"""

def unsettled(room, ai_id):
    """**还没结算完**的东西，返回一串可读的原因；全空 = 真的结算完了。

    ★ 这是「上一张牌的效果到底结算完没有」的**唯一判据**（2026-09-22 加）。

    为什么要显式收口成一个判据函数，而不是在循环里散着写 `if`：
      · 作者第二条反馈是「怕出牌的时候太快了，上一个效果还没结算完下一张牌
        已经打出来了」—— 这个问题只有**一处**能回答，散着写就会漏通道；
      · 判据必须覆盖「连锁窗口」**和**「待处理交互」，两者缺一不可：
        `handle_attack` / `handle_use_magic_card` 只拦 `chain_waiting`（见
        server.py 里那两处门禁），而 `pending_placement` 这类待办**只**通过
        `_action_wait_reason` 拦 —— 只看连锁就会漏掉"打完一张放置卡、还没放船
        就接着打下一张"。
      · 与 `_action_wait_reason` 同源但**更宽**：那个只回答"**这个座位**现在
        能不能写操作"，本函数回答"**房间里**还有没有任何东西没落地"。
        大师必须等到后者为空，因为下一张牌可能又开一次连锁窗口。

    各通道的出处（改任何一条都要同时看这里）：
      · `room.chain` / `room.chain_waiting` —— 连锁栈与响应窗口（`resolve_chain` 收尾）
      · `pending_placement`   —— 等玩家放船（`handle_confirm_reinforcement` / `cancel_placement`）
      · `pending_shenji`      —— 等玩家宣言（`handle_confirm_shenji_declare`）
      · `pending_dice_discard`—— 等玩家弃牌（`handle_dice_discard_choose`）
      · `pending_ship_picks`  —— 等玩家点自己的船（`confirm_magic_target` / 同步代选）
      · `priority_continue`   —— 被拦下的阶段转换，等对方响应完再补上

    ⚠️ 一处**有意**收窄：`pending_ship_picks` 只算**属于大师自己**的那些。
       真人名下的选船待办**故意不算** —— 那是在等真人点棋盘，而 `can_play_magic_card`
       与 `_action_wait_reason` 都不把选船待办当门禁（只有"更高优先级的选船挡住
       新的选船卡"那一条，见 `_ship_pick_blocked_reason`）。把它算进来的后果是
       "真人在犹豫点哪艘船时，大师原地空等 12 秒"，看起来就是 AI 卡死。
       要等真人回答的卡在池里本来就没有（克苏鲁之眼已移出，见 §9 的说明）。

    ⚠️ 2026-09-22 第二处**同形状**收窄：`pending_placement` 与 `pending_shenji`
       现在同样**只认施法者是大师自己**的那条（两条都由 `caster` 定位归属）。
       此前它们被算成房间级的"没落地"，于是**真人施法**的放置流程会把 AI 的
       回合拦住空等 —— 作者实报的服务端日志就是这个形状：
         `大师 AI 等待结算收敛超时（放置流程未完成（lanyu@4418b87d-…）），跳过等待继续回合`
       中的 caster 是**真人账号**，AI 白等满 `_MASTER_SETTLE_STEPS × 0.3s`（12 秒）。
       为什么会发生：真人的那个放置流程是**他自己**的待办（`_ai_consume_own_placement`
       就按 `caster == ai_id` 过滤，所以永远不会替他消费），它本该由真人点格子完成、
       或由他交回合时自己承担；大师回合没有义务也没有能力替它收敛。
       反过来说，**被拦下的阶段转换（`priority_continue`）与连锁窗口仍然是房间级**：
       那两条是"AI 自己那一手动完没有"的真门禁，不能一起收窄。
       `_action_wait_reason` 里的 `_shenji_wait_reason` **有意保持不动** ——
       它冻结的是"非施法者能不能写操作"，那是正确的（对方正在宣言时不该抢动作）；
       本函数回答的是另一个问题："大师这一手可以往下走了吗"。
    """
    reasons = []
    if room.chain:
        reasons.append(f'连锁栈还有 {len(room.chain)} 项')
    if room.chain_waiting:
        reasons.append(f'连锁响应窗口还开着（轮到 {room.chain_window}）')
    temp = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
    placement = temp.get('pending_placement')
    if placement and placement.get('caster') == ai_id:
        reasons.append(f"放置流程未完成（{placement.get('kind')}"
                       f"@{placement.get('caster')}）")
    shenji = temp.get('pending_shenji')
    if shenji and shenji.get('caster') == ai_id:
        reasons.append(f"神机妙算宣言未完成（{shenji.get('caster')}）")
    dice = getattr(room, 'pending_dice_discard', None)
    if isinstance(dice, dict):
        waiting = [pid for pid, done in dice.items() if done is False]
        if waiting:
            reasons.append(f'命运骰子弃牌待办未完成（{",".join(map(str, waiting))}）')
    # ★ 无忧梦呓：**已经打出、还没到对方回合**的那份延迟拼点。
    #   与上面那条同源：一条挂着的"还没落地"状态，房间里就不算干净 ——
    #   不登记的话，卡没结算完会被这里判成"已收敛"（漏登记的后果是静默的）。
    #   ⚠️ 它**只可能在对方回合开始时被清掉**，所以正常情况下不会出现在
    #      大师自己的回合里（对局中另一方打出的那张，在大师回合开始时就结算完了）；
    #      一旦出现，这条会与 `_master_settle` 的 12 秒超时日志一起把原因写清楚。
    wuyou = getattr(room, 'pending_wuyou_dreams', None)
    if isinstance(wuyou, dict) and wuyou:
        reasons.append('无忧梦呓的拼点还没结算（'
                       + ','.join(f'{pid}×{n}' for pid, n in wuyou.items()) + '）')
    # ★ 兵粮寸断：**已经打出、还没到对方准备阶段**的那份延迟判定。
    #   只有 `pending_bingliang`（待判定）才算"没结算完"；
    #   `bingliang_skip_draw`（已判定通过、还剩几次跳过）是**已经落地的持续状态**，
    #   正常情况下要跨两个准备阶段，绝不能因为它把房间判成"没收敛"。
    bingliang = getattr(room, 'pending_bingliang', None)
    if isinstance(bingliang, dict) and bingliang:
        reasons.append('兵粮寸断的判定还没结算（'
                       + ','.join(f'{pid}×{n}' for pid, n in bingliang.items()) + '）')
    picks = getattr(room, 'pending_ship_picks', None)
    if isinstance(picks, list):
        mine = [p for p in picks
                if isinstance(p, dict) and p.get('player') == ai_id]
        if mine:
            reasons.append('大师自己的选船待办未完成（'
                           + ','.join(str(p.get('reason')) for p in mine) + '）')
    if getattr(room, 'priority_continue', None):
        reasons.append('被拦下的阶段转换还没补上')
    return reasons



def consume_pending(room_id, ai_id, *, get_room, consume_placement,
                    consume_choice, consume_shenji):
    room = get_room(room_id)
    if room is None:
        return
    consume_placement(room, ai_id)
    room = get_room(room_id)
    if room is None:
        return
    consume_choice(room, ai_id)
    room = get_room(room_id)
    if room is None:
        return
    consume_shenji(room, ai_id)


def settle(room_id, ai_id, *, steps, get_room, consume_pending,
           unsettled, pause, add_log):
    for _ in range(steps):
        room = get_room(room_id)
        if not room or room.state == 'game_over' or room.current_attacker != ai_id:
            return room, False
        consume_pending(room_id, ai_id)
        room = get_room(room_id)
        if not room or room.state == 'game_over' or room.current_attacker != ai_id:
            return room, False
        reasons = unsettled(room, ai_id)
        if not reasons:
            return room, True
        pause(room_id, 0.3)
    room = get_room(room_id)
    if room is not None:
        reasons = '、'.join(unsettled(room, ai_id)) or '未知'
        add_log(room, f'大师 AI 等待结算收敛超时（{reasons}），跳过等待继续回合', 'system')
    return room, True


def consume_placement(room, ai_id, *, get_room, placement_error, cancel, confirm, resolve, log) -> bool:
    """把挂在 AI 名下的**放置流程**（`pending_placement`）逐艘消费掉。

    返回 True = 已经没有待办了。

    这是 §5.1.5 第 1 条「AI 摆放入口」：没有它，`回光返照 / 败者食尘 / 增援 /
    死者苏生 / 滥竽充数 / 绝处逢生 / 神机妙算` 全都会卡死 ——
    打出后 `pending_placement` 挂在**施法者自己**头上（=AI），而 AI 没有放置入口，
    `enter_end_phase` / `end_turn` 又会被 `_action_wait_reason` 拦住，
    回合永远交不出去、真人零提示（§1.1 缺陷 2 的原形）。

    候选格**完全按各卡的规则算**（复用 `placement_error` 这一份实现，
    不复刻合法性判断），brain 只负责在给定候选里挑。
    """
    for _ in range(12):
        room = get_room(room.id)
        if not room or room.state == 'game_over':
            return True
        temp = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
        pending = temp.get('pending_placement')
        if not pending or pending.get('caster') != ai_id:
            return True

        kind = pending.get('kind')
        allow = set()
        if kind == 'last_stand':
            allow = {(int(a[0]), int(a[1]))
                     for a in (room.game_effects.get('last_stand_cells') or [])}
        elif kind == 'shenji_redeploy':
            allow = {(int(a[0]), int(a[1]))
                     for a in (room.game_effects.get('shenji_redeploy_cells') or [])}

        # 候选格 = 全盘枚举后逐格过 `placement_error`（就是玩家点格子时服务端
        # 用的那个校验，所以"AI 挑的格"与"玩家能点的格"必然同一套口径）。
        #
        # ⚠️ `last_stand` 是个例外：绝处逢生已经把**全部**战舰都牺牲掉了
        #    （每艘都 `ships.remove()` 并记进 `sunken_ships`），于是
        #    `placement_error` 的"未被己方船占用"会把**六个候选格全判成非法**
        #    （沉船仍留在 `ships` 里）→ 一个能放的位置都没有 → 流程只能取消，
        #    卡就白打了。服务端对这条路径的合法性是**按 `allowed` 单独校验**的
        #    （见 `confirm` 的 last_stand 分支），
        #    所以这里也照它的口径来：只认白名单，不再过默认规则。
        if kind == 'last_stand':
            legal = sorted(allow)
        else:
            ignore_sunken = kind == 'shenji_redeploy'
            legal = []
            for (x, y) in ((cx, cy) for cx in range(6) for cy in range(6)):
                if allow and (x, y) not in allow:
                    continue
                if placement_error(room, ai_id, x, y, allow_cells=allow,
                                    ignore_sunken=ignore_sunken):
                    continue
                legal.append((x, y))

        if not legal:
            # 没有合法落点：显式取消放置流程（`cancel` 会收尾并
            # 清掉待办），绝不把一个没人能消费的待办留在房间里。
            cancel({'room_id': room.id, 'player_id': ai_id})
            log(room, '大师 AI 的放置流程没有合法落点，已取消', 'system')
            continue

        cell = resolve(room, ai_id, kind, legal)
        if cell is None:
            cancel({'room_id': room.id, 'player_id': ai_id})
            log(room, '大师 AI 的放置流程无法决策，已取消', 'system')
            continue

        resp = confirm({
            'room_id': room.id, 'player_id': ai_id,
            'position': {'x': int(cell[0]), 'y': int(cell[1])}})
        if not (resp and resp.get('status') == 'success'):
            # 被拒说明候选格算错了，再试也是同一批 → 直接取消，别空转
            cancel({'room_id': room.id, 'player_id': ai_id})
            log(room, f'大师 AI 放置被拒（{resp}），已取消放置流程', 'system')
            continue
    return True


def consume_choice(room, ai_id, *, resolve_choice, resolve_ship_pick, confirm, is_ship_alive, consume_ship_pick, runtime, log) -> bool:
    """把挂在 AI 名下的**挑牌/数值选择**（`magic_temp_data` 里的 `*_choice`）消费掉。

    返回 True = 已经没有待办了。

    这是 §5.1.5 那条「待办必须有人消费」在**挑牌通道**上的对应物：
    `桃园结义 / 亡羊补牢 / 明智埋葬 / 灵气复苏` 打出后都会把 `magic_temp_data`
    设成 `type='xxx_choice'` 并等**施法者自己**回一个选择（前端走
    `select_magic_target` → `confirm`）。AI 不自己去回，
    这个待办就永远挂在那里，回合再也交不出去。

    判据与候选**全部复用 `resolve_choice`**（价值表只有一份），
    并且用 `confirm` —— 也就是前端真正在用的那个入口，
    不另写一套结算（CLAUDE.md 教训 #1）。
    """
    if not isinstance(room.magic_temp_data, dict):
        return True
    kind = room.magic_temp_data.get('type')
    if not kind or room.magic_temp_data.get('caster') != ai_id:
        return True

    if kind == 'taoyuan_choice':
        cards = list(room.magic_temp_data.get('cards') or [])
        if not cards:
            return True
        pick = resolve_choice(room, ai_id, kind, cards)
        idx = cards.index(pick) if pick in cards else 0
        # 对方那一张也由 AI 代答（`opponent_choice`）——AI 房间的对方是电脑，
        # 不代答就会停在「等待对方选择」。给它剩下里最值的那张对**对手**是利好，
        # 所以这里按"给我自己后剩下最差的"给对手：价值表升序取第一张其余。
        rest = [i for i in range(len(cards)) if i != idx]
        opp_idx = min(rest, key=lambda i: ai_brain.card_value(
            getattr(cards[i], 'name', cards[i]))) if rest else -1
        resp = confirm({
            'room_id': room.id, 'player_id': ai_id,
            'temp_data_id': kind,
            'target_data': {'caster_choice': idx, 'opponent_choice': opp_idx},
        })
        if not (resp and resp.get('status') == 'success'):
            # 回不去就显式清掉，别留下没人能消费的待办
            room.magic_temp_data = {}
            log(room, f'大师 AI 的桃园结义选择失败（{resp}），已清理待办', 'system')
        return True

    if kind == 'wangyang_choice':
        cards = list(room.magic_temp_data.get('cards') or [])
        if not cards:
            room.magic_temp_data = {}
            return True
        pick = resolve_choice(room, ai_id, kind, cards)
        idx = cards.index(pick) if pick in cards else 0
        # ⚠️ 字段名是 `chosen_index`（`confirm` 的 wangyang 分支读它），
        #    不是 `card_index` —— 写错不会报"字段名错"，只会回一句
        #    「无效的卡牌选择」，看起来像 AI 挑错了牌。
        resp = confirm({
            'room_id': room.id, 'player_id': ai_id,
            'temp_data_id': kind, 'target_data': {'chosen_index': idx}})
        if not (resp and resp.get('status') == 'success'):
            room.magic_temp_data = {}
            log(room, f'大师 AI 的亡羊补牢选择失败（{resp}），已清理待办', 'system')
        return True

    if kind == 'bury_choice':
        candidates = list(room.magic_temp_data.get('candidates') or [])
        if not candidates:
            room.magic_temp_data = {}
            return True
        # 候选是**纯数据 dict**（不能存实例：magic_temp_data 会被原样 emit），
        # 所以这里按 'name' 取价值，`source/index` 由 confirm 自己解回。
        #
        # ★ 口径：**优先埋对方手里最值的那张**。埋牌同时会给自己摸一张
        #   （`_apply_bury_choice` 里已实现），所以"埋对方的"是纯赚；
        #   埋自己牌堆里的牌等于把好牌扔掉再换一张，是净亏。
        #   只有对方手牌为空时才退回去埋牌堆顶里最值的那张。
        opp_side = [c for c in candidates if c.get('source') == 'opponent_hand']
        pool = opp_side or candidates
        best_name = resolve_choice(
            room, ai_id, kind, [c.get('name') for c in pool])
        chosen = next((c for c in pool if c.get('name') == best_name), pool[0])
        idx = candidates.index(chosen)
        resp = confirm({
            'room_id': room.id, 'player_id': ai_id, 'temp_data_id': kind,
            'target_data': {'source': chosen.get('source'),
                            'source_index': chosen.get('index'),
                            'chosen_index': idx}})
        if not (resp and resp.get('status') == 'success'):
            room.magic_temp_data = {}
            log(room, f'大师 AI 的明智埋葬选择失败（{resp}），已清理待办', 'system')
        return True

    if kind == 'shield_choice':
        # 仁王之盾：至多 3 艘**活船**加护盾。这是**多选**通道（`ship_indices`），
        # 与 `pending_ship_picks`（点一艘）和放置流程都不是同一条路。
        # ⚠️ 下标是 `caster.ships` 里的位置，且沉船会被服务端跳过 ——
        #    所以这里必须自己先把沉船剔掉，否则"选 3 艘但只有 1 艘加上盾"。
        caster = room.players.get(ai_id)
        alive_idx = [i for i, sh in enumerate(getattr(caster, 'ships', None) or [])
                     if is_ship_alive(caster, sh)] if caster else []
        if not alive_idx:
            room.magic_temp_data = {}
            consume_ship_pick(room, ai_id, 'shield_choice')
            return True
        # 护盾本身对所有船等价（一次性挡伤），所以选哪几艘**不改变收益**；
        # 仍然走一次 `resolve_ship_pick` 保持"选船只有一份实现"，
        # 由它挑出第一艘，其余按活船顺序补齐到上限（至多 3 艘）。
        first = resolve_ship_pick(room, ai_id, 'shield_choice',
                                           [caster.ships[i] for i in alive_idx],
                                           rng=runtime(room).rng)
        indices = [i for i in alive_idx if caster.ships[i] is first] or [alive_idx[0]]
        for i in alive_idx:
            if len(indices) >= 3:
                break
            if i not in indices:
                indices.append(i)
        resp = confirm({
            'room_id': room.id, 'player_id': ai_id, 'temp_data_id': kind,
            'target_data': {'ship_indices': indices[:3]}})
        if not (resp and resp.get('status') == 'success'):
            room.magic_temp_data = {}
            consume_ship_pick(room, ai_id, 'shield_choice')
            log(room, f'大师 AI 的仁王之盾选择失败（{resp}），已清理待办', 'system')
        return True

    if kind == 'lingqi_choice':
        # 残缺状态安全：`max_ships` 可能是脏值（历史上被客户端字段合并过），
        # 这里绝不让它抛出去 —— 抛在回合循环里就是一个没人消费的待办。
        try:
            max_ships = int(room.magic_temp_data.get('max_ships') or 6)
        except (TypeError, ValueError):
            max_ships = 6
        max_ships = max(1, min(6, max_ships))
        options = list(range(1, max_ships + 1))
        chosen = resolve_choice(room, ai_id, kind, options)
        try:
            chosen = int(chosen)
        except (TypeError, ValueError):
            chosen = max_ships
        chosen = max(1, min(max_ships, chosen))
        resp = confirm({
            'room_id': room.id, 'player_id': ai_id, 'temp_data_id': kind,
            'target_data': {'target_ships': chosen}})
        if not (resp and resp.get('status') == 'success'):
            room.magic_temp_data = {}
            log(room, f'大师 AI 的灵气复苏选择失败（{resp}），已清理待办', 'system')
        return True

    # 不认识的待办类型：不碰（可能是别人/别通道的），交给原来那套逻辑
    return True


def consume_shenji(room, ai_id, *, resolve_choice, confirm, log) -> bool:
    """把挂在 AI 名下的**神机妙算宣言**待办消费掉。

    `神机妙算` 打出后会开一个「宣言一个 0~6 的数字」的窗口
    （`magic_temp_data['pending_shenji']`），并且**冻结对方的写操作**
    （`_action_wait_reason` 里的 `_shenji_wait_reason`）。
    AI 不自己宣言，这个窗口只能等超时，整局就停在那里。

    宣言值交给 `resolve_choice`（与其它挑数值同一份决策），
    落效走 `confirm` —— 玩家真正在用的那个入口。
    """
    if not isinstance(room.magic_temp_data, dict):
        return True
    pending = room.magic_temp_data.get('pending_shenji')
    if not pending or pending.get('caster') != ai_id:
        return True

    # 卡面：宣言 x = "这一大回合我的船数会减少 x 艘"。预言命中则这些船不减少。
    #   候选 0~6（`confirm` 会再夹一次范围）。
    #   ⚠️ 期望值：不宣言（=超时按 0 处理）在"一艘都没掉"时同样无效，
    #      所以这里不能靠"保守填 0"取胜 —— 交给价值函数，用实测对比。
    value = resolve_choice(room, ai_id, 'shenji_predict', list(range(7)))
    try:
        value = max(0, min(6, int(value)))
    except (TypeError, ValueError):
        value = 0
    resp = confirm(
        {'room_id': room.id, 'player_id': ai_id, 'prediction': value})
    if not (resp and resp.get('status') == 'success'):
        # 宣言不了就把窗口拆掉，绝不留下一个冻结对方写操作的死待办
        room.magic_temp_data.pop('pending_shenji', None)
        log(room, f'大师 AI 的神机妙算宣言失败（{resp}），已清理待办', 'system')
    return True


def consume_ship_picks(room, ai_id, *, get_room, top_pick, alive_ships, resolve_ship_pick, runtime, clear_picks, ship_pick_effect, log) -> bool:
    """把挂在 AI 名下的选船待办逐个消费掉（brain 挑船）。

    返回 False = 消费不掉（没有可选的活船等），调用方据此停下。
    """
    for _ in range(8):
        room = get_room(room.id)
        if not room or room.state == 'game_over':
            return False
        entry = top_pick(room, ai_id)
        if not entry:
            return True
        caster = room.players.get(ai_id)
        alive = alive_ships(caster) if caster else []
        if not alive:
            # 没有可选对象：显式清掉，别留一个永远没人能消费的待办
            clear_picks(room, ai_id)
            log(room, '大师 AI 的选船待办无可选战舰，已清理', 'system')
            return True
        picked = resolve_ship_pick(
            room, ai_id, entry.get('reason'), alive, rng=runtime(room).rng)
        if picked is None:
            clear_picks(room, ai_id)
            log(room, '大师 AI 的选船待办无法决策，已清理', 'system')
            return True
        room.pending_ship_picks = [
            p for p in (room.pending_ship_picks or []) if p is not entry]
        ship_pick_effect(room, ai_id, entry, picked)
    return False


def ship_pick_effect(room, ai_id, entry, picked) -> None:
    """把「AI 代选的那艘船」真正结算掉（牺牲 / 加盾 / 触发陷阱）。

    走的是与 `handle_confirm_sacrifice` 同一组内部原语，**不复刻**它们：
    `_SACRIFICE_REASONS` 里的 reason 走牺牲，其余（如 shield_choice）只做记录。
    """
    reason = str(entry.get('reason') or '')
    if reason in _SACRIFICE_REASONS:
        _do_demon_contract_sacrifice(room, ai_id, picked, reason)
    elif reason == 'kraken_eye':
        # 克苏鲁之眼：被窥探的一方暴露位置给施法者（AI 房间由 `_request_ship_pick`
        # 同步代选，正常不会走到这里；兜底时把位置补上，别让效果半途而废）。
        for pos in (getattr(picked, 'positions', None) or []):
            c = _cell_of(pos)
            if c is not None:
                room.players[ai_id].revealed_positions.append(pos)
    _emit_active_effects(room)
