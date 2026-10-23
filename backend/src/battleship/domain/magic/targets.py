"""目标区域/形状校验：魔法卡「选几格、必须连成一片、哪个海域」的唯一实现。

为什么单独一层：卡表文字是唯一权威（`domain/magic/data/magic_card.json`），
而目标清洗在 `services/magic.py:sanitize_targets` 里只做坐标范围检查。把形状
规则沉到这里，扣牌/入链之前就能拒绝，且规则只有一份、可被单测直接覆盖。
"""

from __future__ import annotations

from typing import Any, Iterable

#: 矩形区域卡的边长（宽, 高）。3×3 = 神威！/冻结，2×2 = 探测雷达。
AREA_SHAPES: dict[str, tuple[int, int]] = {
    "神威！": (3, 3),
    "冻结": (3, 3),
    "探测雷达": (2, 2),
}

#: 需要「恰好 N 个四邻接连通格」的卡。
CONNECTED_CELLS: dict[str, int] = {
    "硫磺火焰": 6,
}

#: 必须给行列的卡（轰炸）。
LINE_CARDS = frozenset({"轰炸"})

BOARD_MIN = 0
BOARD_MAX = 5


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_area(area: dict[str, Any]) -> tuple[int, int, int, int] | None:
    """把任意两个对角点归一成 (x1, y1, x2, y2)，x1<=x2、y1<=y2。

    前端可能按拖拽起点/终点发送，反向角点属于合法输入；返回 None 表示坐标非法。
    """

    values = [_int(area.get(key)) for key in ("x1", "y1", "x2", "y2")]
    if any(value is None for value in values):
        return None
    x1, y1, x2, y2 = values  # type: ignore[misc]
    if not all(BOARD_MIN <= value <= BOARD_MAX for value in (x1, y1, x2, y2)):
        return None
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def connected(cells: Iterable[tuple[int, int]]) -> bool:
    """四邻接连通性（允许转弯，不要求整行整列）。"""

    unique = list(dict.fromkeys(cells))
    if not unique:
        return False
    remaining = set(unique)
    stack = [unique[0]]
    remaining.discard(unique[0])
    while stack:
        x, y = stack.pop()
        for neighbour in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if neighbour in remaining:
                remaining.discard(neighbour)
                stack.append(neighbour)
    return not remaining


def _cell_pairs(targets: dict[str, Any], key: str = "target_cells") -> list[tuple[int, int]] | None:
    cells = targets.get(key)
    if not isinstance(cells, list):
        return None
    pairs: list[tuple[int, int]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            return None
        x, y = _int(cell.get("x")), _int(cell.get("y"))
        if x is None or y is None:
            return None
        pairs.append((x, y))
    return pairs


def validate(card_name: str, targets: dict[str, Any]) -> str | None:
    """返回错误文案；None 表示通过。会就地归一化 `target_area`。"""

    shape = AREA_SHAPES.get(card_name)
    if shape is not None:
        area = targets.get("target_area")
        if not isinstance(area, dict):
            return "这张卡需要选择目标区域"
        normalized = normalize_area(area)
        if normalized is None:
            return "目标区域坐标超出棋盘范围"
        x1, y1, x2, y2 = normalized
        area.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
        width, height = x2 - x1 + 1, y2 - y1 + 1
        if (width, height) != shape:
            return f"「{card_name}」需要选择 {shape[0]}×{shape[1]} 的区域"

    size = CONNECTED_CELLS.get(card_name)
    if size is not None:
        pairs = _cell_pairs(targets)
        if pairs is None:
            return "这张卡需要选择格子"
        if len(pairs) != size:
            return f"「{card_name}」需要选择恰好{size}个格子"
        if len(set(pairs)) != size:
            return "目标格子有重复"
        if any(not (BOARD_MIN <= x <= BOARD_MAX and BOARD_MIN <= y <= BOARD_MAX) for x, y in pairs):
            return "目标格子坐标超出棋盘范围"
        if not connected(pairs):
            return f"「{card_name}」的{size}个格子必须连成一片"

    if card_name in LINE_CARDS:
        line = targets.get("target_line")
        if not isinstance(line, dict) or line.get("type") not in ("row", "col"):
            return "这张卡需要选择一行或一列"
        index = _int(line.get("index"))
        if index is None or not (BOARD_MIN <= index <= BOARD_MAX):
            return "目标行列坐标超出棋盘范围"

    return None


__all__ = [
    "AREA_SHAPES",
    "CONNECTED_CELLS",
    "LINE_CARDS",
    "connected",
    "normalize_area",
    "validate",
]
