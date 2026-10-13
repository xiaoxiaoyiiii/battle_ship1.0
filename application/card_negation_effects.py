"""连锁无效化卡的结算、目标解析与船数变化判据。"""

NEGATION_CARD_NAMES = frozenset({'平等条约', '失灵！', '加百列之光'})

EQUAL_TREATY_NOT_NEGOTIABLE = {
    '恶魔契约': '作者已裁：它造成的「牺牲」不算可被无效化的船数变化',
    '神之宣告': '同上（牺牲两艘自己的船，再让对方牺牲一艘）',
    '命运骰子': '同上（摇到 6 点让对方牺牲）',
    '守株待兔': '同上（陷阱触发后让对方牺牲）',
}


def chain_negation_target(room, self_name):
    """「康正下方那一项」类的目标解析与免疫关系 —— `失灵！` / `平等条约` 共用。

    调用契约：**当前项已经出栈**（`resolve_chain` 先 `pop()` 再 `apply_magic_effect`），
    所以 `room.chain[-1]` 就是"正下方那一项"＝下一个待结算项。

    返回 `(target_item, reason)`：拿到目标时 `reason is None`；免疫 / 没有目标时
    `target_item is None`、`reason` 是给玩家看的文案。

    ⚠️ 为什么必须共用一份：作者裁决「平等条约与失灵！**完全同一套**目标解析与免疫
       关系」。各写一份的话，将来给其中一张加免疫（例如"某卡免疫"）必然漏掉另一张，
       而症状是"康得动/康不动"这种玩家一眼看得出、代码里却看不出的偏差（教训 #1）。
    """
    if not room.chain:
        return None, f'{self_name}只能在连锁中发动：现在没有可无效化的「正下方那一项」'
    target = room.chain[-1]
    tname = getattr(getattr(target, 'card', None), 'name', None)
    if tname == '看破！':
        return None, f'看破！优先于{self_name}，无法无效化'
    if tname == '加百列之光':
        return None, f'加百列之光免疫{self_name}'
    return target, None


class NegationEffects:
    """集中维护无效化结算与船数变化判据；运行时只注入共享棋盘查询和拆场动作。

    实例不持有房间或对局状态。AI 判牌和实际结算共用同一个判据表，
    共享查询由调用方提供，避免在本模块复制存活、空位等规则。
    """

    def __init__(self, *, alive_ships, opponent_of, cell_xy,
                 placement_blocked_cells, lanyu_requirement_reason,
                 tear_down_field_magic):
        self._alive_ships = alive_ships
        self._opponent_of = opponent_of
        self._cell_xy = cell_xy
        self._placement_blocked_cells = placement_blocked_cells
        self._lanyu_requirement_reason = lanyu_requirement_reason
        self._tear_down_field_magic = tear_down_field_magic

        # 卡名、判据与说明是同一份登记；条目变更须遵循现有规则裁定。
        self.ship_change_rules = {
            # ── 击沉类：判据是「这一发真的会沉船」（不是"它属于击沉类"）──
            '轰炸':     (self._treaty_bomb_line_kills,
                         '目标行/列里必须有还活着的船；打在空行/空列上不沉船'),
            '硫磺火焰': (self._treaty_sulfur_kills,
                         '选定的 6 个格子里必须有还活着的船'),
            '溅射':     (self._treaty_splash_kills,
                         '上一发命中格的上下左右四格里必须有仍可被溅射击沉的战舰（护盾无效）'),
            # ── 复活类：判据是「真的会复活」──
            '疗愈':     (self._treaty_revive_has_wreck,
                         '场上没有可复活的沉船时不会复活'),
            '死者苏生': (self._treaty_revive_has_wreck,
                         '同上（与疗愈共用同一个判据函数）'),
            # ── 增加类：判据是「真的会让某方船数 +1」──
            '增援':     (self._treaty_reinforce_has_cell,
                         '棋盘上还有可放置的空格才会真的 +1'),
            '滥竽充数': (self._treaty_lanyu_refills,
                         '与它自己的出牌闸门同一份判据（船数未满 + 有空格）'),
            '神机妙算': (self._treaty_shenji_can_restore,
                         '★ 只判到必要条件（还有活船可沉）：改船数与否要等它自己结算后才宣言 x'),
            # ── 自我牺牲（作者裁决：保持现状、可以被无效化）──
            '绝处逢生': (self._treaty_last_stand_self_sacrifice,
                         '牺牲自己全部战舰 ⇒ 只要有活船就真的会改船数'),
        }


    def _treaty_kill_hits_alive_ship(self, room, target_item, cells):
        """`cells` 里只要有**还活着的**船 ⇒ 这一发真的会沉船（轰炸 / 硫磺火焰共用）。

        两处口径都照产品实现走：目标方 = **施法者的对手**（这两张卡打的都是对方棋盘），
        存活判据用项目唯一那份 `_alive_ships`（`_is_ship_alive`）。
        """
        victim_id = self._opponent_of(room, target_item.player_id)
        victim = room.players.get(victim_id) if victim_id else None
        if victim is None:
            return False
        wanted = {self._cell_xy(c) for c in cells}
        wanted.discard(None)
        if not wanted:
            return False
        return any((p.x, p.y) in wanted
                   for sh in self._alive_ships(victim) for p in sh.positions)


    def _treaty_bomb_line_kills(self, room, target_item):
        """轰炸：选定的**行/列里真的有还活着的船**才会沉（空行/空列 ⇒ 失败）。"""
        targets = target_item.targets if isinstance(target_item.targets, dict) else {}
        line = targets.get('target_line')
        if not isinstance(line, dict):
            return False
        try:
            index = int(line.get('index'))
        except (TypeError, ValueError):
            return False
        if not 0 <= index < 6:
            return False
        if line.get('type') == 'row':
            cells = [{'x': x, 'y': index} for x in range(6)]
        elif line.get('type') == 'col':
            cells = [{'x': index, 'y': y} for y in range(6)]
        else:
            return False
        return self._treaty_kill_hits_alive_ship(room, target_item, cells)


    def _treaty_sulfur_kills(self, room, target_item):
        """硫磺火焰：选定的 6 个格子里真的有还活着的船才会沉。"""
        targets = target_item.targets if isinstance(target_item.targets, dict) else {}
        cells = targets.get('target_cells')
        if not isinstance(cells, list) or len(cells) != 6:
            return False
        return self._treaty_kill_hits_alive_ship(room, target_item, cells)


    def _treaty_splash_kills(self, room, target_item):
        """溅射：它打的是**自己上一发命中格**的上下左右四格 ⇒ 判据必须读同一份数据。

        ⚠️ 溅射的目标**不在** `ChainItem.targets` 里（它读 `room.last_attack`）——
           拿 targets 去判会判成"永远不打人"，等于把它整张卡漏掉。
        溅射按规则无视护盾并强制击沉仍有未受伤格的战舰，因此带盾船也必须纳入判定。
        """
        last = getattr(room, 'last_attack', None) or {}
        if last.get('attacker') != target_item.player_id or not last.get('hit'):
            return False
        try:
            x, y = int(last['x']), int(last['y'])
        except (KeyError, TypeError, ValueError):
            return False
        neighbors = {(x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)}
        neighbors = {(a, b) for (a, b) in neighbors if 0 <= a < 6 and 0 <= b < 6}
        victim_id = self._opponent_of(room, target_item.player_id)
        victim = room.players.get(victim_id) if victim_id else None
        if victim is None:
            return False
        for sh in self._alive_ships(victim):
            hits = {(h.x, h.y) for h in sh.hits}
            if any((p.x, p.y) in neighbors and (p.x, p.y) not in hits for p in sh.positions):
                return True
        return False


    def _treaty_revive_has_wreck(self, room, target_item):
        """疗愈 / 死者苏生：**场上没有可复活的沉船**就复活不了 ⇒ 失败。

        与这两张卡自己的发动判据同一份口径（`caster.sunken_ships` 为空时它们必然
        `success = False`），所以这里读的就是同一个字段，不是另写一套。
        """
        player = room.players.get(target_item.player_id)
        return bool(player is not None and getattr(player, 'sunken_ships', None))


    def _treaty_reinforce_has_cell(self, room, target_item):
        """增援：棋盘上**真的还有可放置的格子**才会 +1。

        与放置流程共用同一份占位口径（`_placement_blocked_cells`，36 格）。
        全被占满（己方船 + 对方打过的格 + 神威扣洞）⇒ 放不下 ⇒ 船数不会变。
        """
        if target_item.player_id not in room.players:
            return False
        return len(self._placement_blocked_cells(room, target_item.player_id)) < 36


    def _treaty_lanyu_refills(self, room, target_item):
        """滥竽充数：真的补得满才有船数变化 —— 直接复用**它自己的出牌闸门**。

        `_lanyu_requirement_reason` 就是它的真实条件（remaining_ships < max_ships
        且至少一个可放置格子）；返回 None 表示"这张牌打下去会真的补船"。
        """
        if target_item.player_id not in room.players:
            return False
        return self._lanyu_requirement_reason(room, target_item.player_id, target_item.card) is None


    def _treaty_shenji_can_restore(self, room, target_item):
        """神机妙算：**只能判到必要条件**（还有活船可沉）。

        ⚠️⚠️ 这张卡做不到"准确预判会不会改船数"，原因在时序上：

          卡面：「宣言一个数目 x，如果对方的结束阶段结束之后自己的船数减少了 x，
                 那么那些原本会减少的船不会减少并重新部署。」
          · `x` 是**神机妙算自己结算时**才开的宣言窗口里由玩家填的
            （`magic_temp_data['pending_shenji']` → `handle_confirm_shenji_declare`）；
          · 平等条约在连锁里**排在它上面 ⇒ 先结算**，此刻 `x` 还没有、基线快照
            （`prediction_initial_<pid>`）也还没拍；
          · 就算有 x，"这一大回合会不会正好沉 x 艘"也要等对方的结束阶段才知道。

          ⇒ 充分条件在这一刻**不存在**。这里只给出必要条件：**还有活船**才可能再减船
            （一艘活船都没有 ⇒ 船数不可能再变 ⇒ 失败）。已单列在报告里请作者裁决。
        """
        player = room.players.get(target_item.player_id)
        return bool(player is not None and self._alive_ships(player))


    def _treaty_last_stand_self_sacrifice(self, room, target_item):
        """绝处逢生：牺牲自己**全部**战舰 ⇒ 只要有活船就真的会改船数。

        作者裁决：「绝处逢生的自牺牲**保持现状**（可以被无效化）—— 作者裁过，别改。」
        ⚠️ 与"牺牲类"（恶魔契约 / 神之宣告 / 命运骰子 / 守株待兔）**不是一回事**：
           那几张是**让别人**牺牲，作者早先已裁过「不算可被无效化的船数变化」⇒ 康不动。
        ⚠️ 新机制下"无效化"= **整张牌被跳过** ⇒ 一艘都不会牺牲
           （旧快照实现回的是 1 艘，那条差异已单列在报告里）。
        """
        player = room.players.get(target_item.player_id)
        return bool(player is not None and self._alive_ships(player))


    def verdict(self, room, target_item):
        """平等条约对**这一项**的判词：`(会不会真的改船数, 人话说明)`。

        这是判据的**唯一**消费口 —— 结算分支只读这里的结果，不许自己再写 `if`。
        """
        name = getattr(getattr(target_item, 'card', None), 'name', None)
        row = self.ship_change_rules.get(name)
        if row is None:
            return False, f'{name}不会造成可被无效化的船数变化'
        fn, why = row
        try:
            ok = bool(fn(room, target_item))
        except Exception as exc:                       # noqa: BLE001 - 兜底不许静默
            # 判据自己炸了 = 这张牌**不确定能不能康** ⇒ 当作康不动，并把原因留痕。
            return False, f'{name}的船数变化判据无法判定（{exc!r}）'
        return ok, why


    def apply(self, room, caster_id, card, result):
        """结算无效化卡，返回（已处理，需提前结束），保留旧入口的收尾语义。"""
        if card.name not in NEGATION_CARD_NAMES:
            return False, False
        # 旧分发中失灵排在类型分支之后，保留异常卡数据的分发优先级。
        if card.name == '失灵！' and card.type in ('判定', '场地'):
            return False, False
        caster = room.players[caster_id]

        if card.name == '平等条约':
            # ★ 2026-09-24 作者裁决：改成**连锁无效化**（`docs/CHAIN_ENGINE_SPEC.md` §1.2
            #   原本的设计），**删掉**原来的"船数变化快照回滚"。原因：那份快照的过期判据
            #   绑在 `room.round`（大回合）上，而 `room.round` 只在 `next_index == 0` 时
            #   递增 ⇒ **对两个座位不等价**（受害方是先手时必被拒，作者实报
            #   「船数改变发生在上一个大回合，无法再无效化」）。
            #
            # 新规则（三条，逐条都只在一个地方实现）：
            #   ① 目标 = **栈中正下方那一项**，与「失灵！」共用 `_chain_negation_target`
            #      （所以看破！/ 加百列之光的免疫、以及"不在连锁里就失败"都自动同口径）；
            #   ② **只有目标真的会造成船数变化时才成功** —— 判据只此一份
            #      （`EQUAL_TREATY_SHIP_CHANGE_RULES` + `_equal_treaty_verdict`）；
            #   ③ 成功 = `negate_target` ⇒ `resolve_chain` 把正下方那一项标 `negated`、
            #      结算时**整项跳过**（不再"先结算再回滚"，所以也不再需要任何台账）。
            target_item, why = chain_negation_target(room, '平等条约')
            if target_item is None:
                result['success'] = False
                result['message'] = why
                return True, True

            # 看破！压制期间自己这一侧的魔法卡一律无效（与失灵！同口径；失灵！那两条
            # 闸门在出牌/响应层就拦掉了，而平等条约在**同一条连锁**里可能被上方刚结算的
            # 看破！压制住 —— 那一帧只有这里看得到）。
            if getattr(caster, 'magic_blocked', False):
                result['success'] = False
                result['message'] = '你已被看破！压制，本回合魔法卡无效，平等条约无法发动'
                return True, True

            would_change, reason = self.verdict(room, target_item)
            if not would_change:
                result['success'] = False
                # 作者原话的文案打头，后面跟这一张卡的**真实理由**（不许只说"没有效果"）。
                result['message'] = f'没有可无效化的船数改变效果（{reason}）'
                return True, True

            result.negate_target = True
            result['message'] = f'将无效化{target_item.card.name}'

        elif card.name == '加百列之光':
            # 无效化：连锁栈里有牌就康「正下方那一项」；没有连锁栈则主动拆场地魔法。
            # （作者裁定：这两条是二选一 —— 这解决了"场地早贴上了、过了一会想反悔"
            #   却因为没有连锁窗口而做不到的问题。）
            #
            # ⚠️ 不判归属：此前要求 chain[-1].player_id != caster_id，导致【自连锁】
            # 时康不掉自己前面打出的牌 —— 实测场景：对方出牌 → 我失灵 → 我又加百列，
            # 结算时加百列看到正下方是自己的失灵就不康，失灵照常无效化了对方那张牌。
            # 作者裁定：同一连锁里后手应能推翻前手，一律康正下方那一项。
            negated_count = 0
            chain_negated = False
            if room.chain:
                result.negate_target = True
                chain_negated = True
                negated_count += 1
            elif room.field_magic is None and room.magic_history \
                    and room.magic_history[-1]['caster'] != caster_id:
                # 既没有连锁项、场上也没有场地：回退到"对方最近用过的那张"
                # （原行为，别让这张卡在这种情形下变成纯粹的空牌）
                room.magic_history.pop()
                chain_negated = True
                negated_count += 1

            # 没有连锁项时：拆掉当前生效的场地魔法（自己贴的与对方贴的都可以拆）
            torn = None
            if not chain_negated and room.field_magic:
                torn = self._tear_down_field_magic(room, caster_id)
                negated_count += 1

            if negated_count == 0:
                result['success'] = False
                result['message'] = '没有可无效化的魔法卡或场地魔法'
                return True, True
            if torn is not None:
                result['message'] = f'成功无效化场地魔法「{getattr(torn, "name", "")}」'
            else:
                result['message'] = '成功无效化连锁中的魔法卡'

        elif card.name == '失灵！':
            # 连锁结算中：康紧邻下方那一项（下一个待结算项）。
            # ⚠️ 与「加百列之光」同口径：不判归属 —— 自连锁时要能康掉自己前面
            # 打出的牌（作者裁定：同一连锁里后手能推翻前手）。
            if room.chain:
                # 目标解析 + 免疫关系与「平等条约」共用同一份实现（`_chain_negation_target`）。
                # 栈非空仍可能命中免疫规则；目标缺失与免疫理由都由共享查询返回。
                target, why = chain_negation_target(room, '失灵！')
                if target is None:
                    result.success = False
                    result.message = why
                    return True, True
                result.negate_target = True
                result.message = f'将无效化{target.card.name}'
                return True, True

            # 没有连锁栈：优先主动拆掉已贴出的场地魔法。
            # 作者裁定 —— 这解决了"场地早贴上了、过了一会想反悔"却因为没有
            # 连锁窗口而做不到的问题（原实现在这种情况下只能回退到历史记录）。
            # 自己贴的与对方贴的都可以拆。
            if room.field_magic:
                torn = self._tear_down_field_magic(room, caster_id)
                result.message = f'成功无效化场地魔法「{getattr(torn, "name", "")}」'
                return True, True

            # 直接调用（无连锁栈、场上也没有场地）时回退历史记录。
            # 卡面："无效化对方使用的上一张魔法卡，被影响的魔法卡必须为当前时段刚使用的。"
            if room.magic_history and room.magic_history[-1]['caster'] != caster_id:
                last_magic = room.magic_history[-1]
                if getattr(last_magic.get('card'), 'name', None) in ('看破！', '加百列之光'):
                    result.success = False
                    result.message = '该魔法免疫失灵！'
                    return True, True
                # 只允许无效化本大回合内刚使用的卡（老条目没有 round 时按旧行为放行）
                if last_magic.get('round', room.round) != room.round:
                    result.success = False
                    result.message = '对方上一张魔法卡不是本回合使用的，失灵！无法无效化'
                    return True, True
                room.magic_history.pop()
                result.message = f'无效化了{last_magic["card"].name}（若其效果已结算则不会回滚）'
                result.negated = last_magic
            else:
                result.success = False
                result.message = '没有可无效化的魔法卡'

        return True, False
