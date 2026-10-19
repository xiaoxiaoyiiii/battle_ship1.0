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
