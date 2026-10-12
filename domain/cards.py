"""卡牌目标的纯规范化模型。

这里只负责把客户端选择转换为稳定、可比较的值；卡牌效果仍由旧实现负责。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class TargetError(ValueError):
    """目标数据不符合领域约束。"""


@dataclass(frozen=True)
class TargetCell:
    x: int
    y: int

    def as_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}


def _coord(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 6:
        raise TargetError("坐标必须是 0..5 的整数")
    return value


def _cell(value: Any) -> TargetCell:
    if not isinstance(value, dict) or set(value) != {"x", "y"}:
        raise TargetError("格子目标只允许 x/y")
    return TargetCell(_coord(value["x"]), _coord(value["y"]))


def normalize_target(target_data: Any) -> dict[str, Any]:
    """复制并规范化旧卡牌入口支持的目标形状。"""
    if not isinstance(target_data, dict):
        raise TargetError("目标必须是对象")
    if "target_area" in target_data:
        area = target_data["target_area"]
        if not isinstance(area, dict) or set(area) != {"x1", "y1", "x2", "y2"}:
            raise TargetError("区域目标字段无效")
        x1, y1, x2, y2 = (_coord(area[k]) for k in ("x1", "y1", "x2", "y2"))
        result: dict[str, Any] = {"target_area": {"x1": min(x1, x2), "y1": min(y1, y2),
                                                   "x2": max(x1, x2), "y2": max(y1, y2)}}
    elif "target_line" in target_data:
        line = target_data["target_line"]
        if not isinstance(line, dict) or set(line) != {"type", "index"}:
            raise TargetError("行列目标字段无效")
        if line["type"] not in ("row", "col"):
            raise TargetError("行列类型无效")
        result = {"target_line": {"type": line["type"], "index": _coord(line["index"])}}
    elif "target_cells" in target_data or "selected_cells" in target_data:
        key = "target_cells" if "target_cells" in target_data else "selected_cells"
        values = target_data[key]
        if not isinstance(values, list) or not values:
            raise TargetError("格子目标不能为空")
        cells = [_cell(value) for value in values]
        if len(set(cells)) != len(cells):
            raise TargetError("格子目标不能重复")
        result = {key: [cell.as_dict() for cell in cells]}
    elif "ship_indices" in target_data:
        values = target_data["ship_indices"]
        if not isinstance(values, list) or not values:
            raise TargetError("船只目标不能为空")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
            raise TargetError("船只索引必须是非负整数")
        if len(set(values)) != len(values):
            raise TargetError("船只索引不能重复")
        result = {"ship_indices": list(values)}
    elif "x" in target_data and "y" in target_data:
        result = _cell(target_data).as_dict()
    else:
        raise TargetError("不支持的目标形状")

    for key in ("board", "effect_choice", "caster_choice", "opponent_choice", "chosen_index",
                "source", "source_index", "card_index", "target_ships"):
        if key in target_data:
            result[key] = target_data[key]
    return result
