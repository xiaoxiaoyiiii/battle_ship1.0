"""魔法卡目标与船只存活状态规则。"""

def sanitize_magic_targets(targets, card_name=None, *, area_target_boards, board_sides):
    """校验并归一化魔法卡目标坐标；返回 (targets, error_message)。

    仅处理 dict 形态的目标数据（前端 target_area/target_line/target_cells 等），
    数组/None 交由各卡牌分支自行处理。

    ## `board`（棋盘归属）—— 2026-09-27 区域预览批

    归属表在 `area_target_boards`（**全项目唯一一份**，前端那张
    `needsTargetSelection` 是只读镜像，由 `tests/test_area_preview.py` 钉住）：

    * `'self'` / `'opponent'` —— 固定归属，**由服务端按卡名写进 targets**
      （客户端若也传了 `board`，必须与之一致，否则报错；不一致说明两边对这张卡
      的理解已经漂移，静默采用任何一侧都会把预览画到错的棋盘上）；
    * `'choice'`（神威！）—— 客户端**必须**显式提交 `board`，
      缺失或不是 `self`/`opponent` 一律**拒绝**。

    ⚠️ 这里**绝不兜底**：缺归属就报错，不默认成 `'opponent'`。
       旧实现 `apply_magic_effect` 的 `target_data.get('board', 'opponent')`
       就是"漏传即静默按对方处理"（CLAUDE.md 教训 #2），而预览要拿这个值决定
       画在哪块棋盘上 —— 兜底会直接把区域画反。
    ⚠️ `card_name=None`（未登记的卡）时**完全不碰** `board`，保持既有行为。
    """
    if not isinstance(targets, dict):
        return targets, None

    area = targets.get('target_area')
    if isinstance(area, dict):
        for k in ('x1', 'y1', 'x2', 'y2'):
            if k not in area:
                return targets, '目标区域参数缺失'
            try:
                v = int(area[k])
            except (TypeError, ValueError):
                return targets, '目标区域坐标非法'
            if not (0 <= v <= 5):
                return targets, '目标区域坐标超出棋盘范围'
            area[k] = v

    line = targets.get('target_line')
    if isinstance(line, dict):
        if line.get('type') not in ('row', 'col'):
            return targets, '目标行列参数非法'
        try:
            idx = int(line.get('index'))
        except (TypeError, ValueError):
            return targets, '目标行列坐标非法'
        if not (0 <= idx <= 5):
            return targets, '目标行列坐标超出棋盘范围'
        line['index'] = idx

    for key in ('target_cells', 'selected_cells'):
        cells = targets.get(key)
        if isinstance(cells, list):
            for c in cells:
                if not isinstance(c, dict):
                    return targets, '目标格子格式错误'
                try:
                    cx, cy = int(c['x']), int(c['y'])
                except (KeyError, TypeError, ValueError):
                    return targets, '目标格子坐标非法'
                if not (0 <= cx <= 5 and 0 <= cy <= 5):
                    return targets, '目标格子坐标超出棋盘范围'
                c['x'], c['y'] = cx, cy

    declared = area_target_boards.get(card_name)
    if declared is not None:
        supplied = targets.get('board')
        if supplied is not None and supplied not in board_sides:
            return targets, '棋盘归属参数非法（只能是 self / opponent）'
        if declared == 'choice':
            if supplied is None:
                # 神威！：归属由玩家当场二选一 —— 缺失就是缺失，不许猜。
                return targets, '这张卡必须指定作用棋盘（己方或对方）'
            targets['board'] = supplied
        else:
            if supplied is not None and supplied != declared:
                return targets, ('棋盘归属与这张卡不符（%s 只能作用在%s）'
                                 % (card_name, '己方' if declared == 'self' else '对方'))
            # ★ 服务端写回权威归属：预览只认这里写下的值，不认客户端提交的。
            targets['board'] = declared

    return targets, None


def pick_cell_from_target(target_data):
    """从目标数据里取出玩家点选的单个格子 (x, y)；取不到返回 None。

    兼容两种前端形态：
    - `{'target_area': {'x1': x, 'y1': y, ...}}`（single 选择器 → 1x1 区域）
    - `{'x': x, 'y': y}`
    """
    if not isinstance(target_data, dict):
        return None

    area = target_data.get('target_area')
    if isinstance(area, dict):
        try:
            return int(area['x1']), int(area['y1'])
        except (KeyError, TypeError, ValueError):
            return None

    if 'x' in target_data and 'y' in target_data:
        try:
            return int(target_data['x']), int(target_data['y'])
        except (TypeError, ValueError):
            return None

    return None


def is_ship_alive(player, ship):
    """这艘船是否还活着（没沉、也没被牺牲掉）。

    ⚠️ 本项目的「击沉」只减 `player.remaining_ships`，**不会把船从 `player.ships` 里移走**
    —— 沉船留在列表里供复活类效果回收。所以任何「让玩家挑一艘自己的船」的地方都必须
    先过这一层，否则会出这些事：
      · 克苏鲁之眼：对手拿一艘早就沉了的船来「暴露」，等于什么都没暴露
      · 恶魔契约 / 神之宣告：拿沉船抵账 = 零代价发动
      · 仁王之盾：把护盾加在一艘沉船上，白白浪费
    判定同时看两份依据（沉船堆 / 命中数），任一成立即视为已死，避免两边不同步时漏判。
    """
    if ship is None:
        return False
    if ship in (getattr(player, 'sunken_ships', None) or []):
        return False
    positions = getattr(ship, 'positions', None) or []
    hits = getattr(ship, 'hits', None) or []
    return len(hits) < len(positions)


def alive_ships(player):
    """该玩家目前还活着的船（顺序与 player.ships 一致，便于按原下标回传）。"""
    return [sh for sh in (getattr(player, 'ships', None) or []) if is_ship_alive(player, sh)]
