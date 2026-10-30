"""框架无关的 effect 总线（ticket #36）。

纯 domain：不 import Web 框架、Socket 库或数据库驱动，也不 import Room——房间
模块要 import 本模块，反向 import 会成环。房间与玩家一律按鸭子类型访问，只
依赖 room.effects 与 room.players。

三个概念：

- 订阅（Subscription）：某个 hook 事件上的 handler，带优先级与 kind。
- 租约（Lease）：订阅与持久效果的生命周期，按 turn / round / match 边界过期；
  持久效果标记由 flag:<owner>:<flag> 一条租约承载，投影回 effect_flags。
- 投影（project_effect_flags）：effect_flags 只是活跃租约的派生视图，不写业务
  判据。

emit 是同步语义的异步入口：FIFO 队列 + 单次 drain，handler 内再 emit 只入队；
单次 drain 事件数与级联深度都有预算，超限记错误并停掉该次级联，不抛穿主流程。
"""

from __future__ import annotations

import inspect
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Final

LOGGER = logging.getLogger(__name__)

BOUNDARY_TURN: Final[str] = "turn"
BOUNDARY_ROUND: Final[str] = "round"
BOUNDARY_MATCH: Final[str] = "match"
#: 低层在前、高层在后：高层边界连带清掉低层租约。
BOUNDARIES: Final[tuple[str, ...]] = (BOUNDARY_TURN, BOUNDARY_ROUND, BOUNDARY_MATCH)

KIND_FILTER: Final[str] = "filter"
KIND_NOTIFY: Final[str] = "notify"
KINDS: Final[tuple[str, ...]] = (KIND_FILTER, KIND_NOTIFY)

#: 单次 drain 最多处理的事件数；超过即停掉这次级联并记错误。
MAX_EVENTS_PER_DRAIN: Final[int] = 128
#: 事件级联深度上限（顶层事件为 0）；更深的事件被丢弃并记错误。
MAX_CASCADE_DEPTH: Final[int] = 8

#: 未指定优先级时的兜底，落在观察带（见规格 §5 的建议分带）。
DEFAULT_PRIORITY: Final[int] = 40


@dataclass
class Subscription:
    """一条 hook 订阅：同事件内按 (priority, order) 排序执行。"""

    event: str
    handler: Callable[[dict[str, Any]], Any]
    priority: int = DEFAULT_PRIORITY
    kind: str = KIND_NOTIFY
    lease_key: str | None = None
    #: 注册序号，保证同优先级按注册顺序执行。
    order: int = 0


@dataclass
class Lease:
    """一个持久效果的生命周期；到期由 expire() 统一清理。"""

    key: str
    owner: str | None = None
    boundary: str = BOUNDARY_TURN
    uses_left: int | None = None
    #: 投影到 EffectFlags 的标记；后注册的覆盖先注册的。
    flags: dict[str, Any] = field(default_factory=dict)
    #: 卡牌自己的配置，供 handler 读取。
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class _QueuedEvent:
    event: str
    payload: dict[str, Any]
    depth: int


@dataclass
class EffectState:
    """per-room 运行态：订阅表、租约表、事件队列、drain 标记与错误记录。"""

    subscriptions: dict[str, list[Subscription]] = field(default_factory=dict)
    leases: dict[str, Lease] = field(default_factory=dict)
    queue: deque[_QueuedEvent] = field(default_factory=deque)
    draining: bool = False
    errors: list[str] = field(default_factory=list)
    #: 当前正在派发的事件深度（drain 期间有效）。
    depth: int = 0
    #: 全局注册序号，供同优先级稳定排序。
    seq: int = 0

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def record_error(self, message: str) -> None:
        """记错误并继续：日志不静默，主流程不被打断。"""

        self.errors.append(message)
        LOGGER.error("effect bus: %s", message)


def _state(room: Any) -> EffectState:
    state = getattr(room, "effects", None)
    if not isinstance(state, EffectState):
        raise TypeError("room.effects 缺失或不是 EffectState")
    return state


def _handler_label(handler: Callable[..., Any]) -> str:
    return (
        getattr(handler, "__qualname__", None)
        or getattr(handler, "__name__", None)
        or repr(handler)
    )


def subscribe(
    room: Any,
    event: str,
    handler: Callable[[dict[str, Any]], Any],
    *,
    priority: int = DEFAULT_PRIORITY,
    kind: str = KIND_NOTIFY,
    lease_key: str | None = None,
) -> Subscription:
    """注册一条订阅；同一事件可有任意多条，顺序由 (priority, 注册序) 决定。"""

    if not callable(handler):
        raise TypeError("hook handler 必须可调用")
    if kind not in KINDS:
        raise ValueError(f"未知 hook 类型: {kind}")
    state = _state(room)
    if lease_key is not None and lease_key not in state.leases:
        raise ValueError(f"订阅引用了不存在的租约: {lease_key}")
    state.seq += 1
    subscription = Subscription(
        event=event,
        handler=handler,
        priority=int(priority),
        kind=kind,
        lease_key=lease_key,
        order=state.seq,
    )
    state.subscriptions.setdefault(event, []).append(subscription)
    return subscription


def create_lease(
    room: Any,
    key: str,
    *,
    boundary: str = BOUNDARY_TURN,
    owner: str | None = None,
    uses: int | None = None,
    flags: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Lease:
    """新建一个租约；key 必须唯一，边界与次数当场校验（拼错立刻失败）。"""

    state = _state(room)
    if not key:
        raise ValueError("租约 key 不能为空")
    if key in state.leases:
        raise ValueError(f"租约 key 重复: {key}")
    if boundary not in BOUNDARIES:
        raise ValueError(f"未知租约边界: {boundary}")
    if uses is not None and uses <= 0:
        raise ValueError(f"租约 uses 必须是正整数: {uses}")
    lease = Lease(
        key=key,
        owner=owner,
        boundary=boundary,
        uses_left=uses,
        flags=dict(flags or {}),
        payload=dict(payload or {}),
    )
    state.leases[key] = lease
    return lease


def _drop_subscriptions(state: EffectState, lease_key: str) -> None:
    for event in list(state.subscriptions):
        kept = [sub for sub in state.subscriptions[event] if sub.lease_key != lease_key]
        if kept:
            state.subscriptions[event] = kept
        else:
            del state.subscriptions[event]


def expire(room: Any, boundary: str, player_id: str | None = None) -> list[str]:
    """按边界清理租约与绑定订阅；返回被清掉的 key（方便调用方记日志）。

    高层边界连带清低层：round 顺带清掉漏配的 turn 租约，match 清空所有租约。
    给 player_id 时只清 owner 为空或同座的租约（小回合边界按座位结算）。
    """

    state = _state(room)
    if boundary not in BOUNDARIES:
        raise ValueError(f"未知租约边界: {boundary}")
    doomed = BOUNDARIES[: BOUNDARIES.index(boundary) + 1]
    expired: list[str] = []
    for key, lease in list(state.leases.items()):
        if lease.boundary not in doomed:
            continue
        if player_id is not None and lease.owner is not None and lease.owner != player_id:
            continue
        del state.leases[key]
        _drop_subscriptions(state, key)
        expired.append(key)
    return expired


def consume(room: Any, key: str, owner: str | None = None, uses: int = 1) -> bool:
    """消耗租约次数；次数用尽即移除租约与绑定订阅。

    返回 True 表示找到了这个租约且归属匹配（无限次租约也返回 True），
    False 表示租约不存在或不属于该 owner。
    """

    if uses <= 0:
        raise ValueError(f"consume 的 uses 必须是正整数: {uses}")
    state = _state(room)
    lease = state.leases.get(key)
    if lease is None:
        return False
    if owner is not None and lease.owner is not None and lease.owner != owner:
        return False
    if lease.uses_left is not None:
        lease.uses_left -= uses
        if lease.uses_left <= 0:
            del state.leases[key]
            _drop_subscriptions(state, key)
    return True


#: 标记租约的 key 前缀：一个 (座位, 标记) 只有一条租约，重复施放即刷新。
FLAG_LEASE_PREFIX: Final[str] = "flag"


def flag_lease_key(flag: str, owner: str | None) -> str:
    """一个 (座位, 标记) 对应一个租约 key；owner 为空表示全场共用一条。"""

    return f"{FLAG_LEASE_PREFIX}:{owner or '*'}:{flag}"


def get_lease(room: Any, key: str) -> Lease | None:
    """按 key 取租约；不存在返回 None（调用方据此判断效果是否还在）。"""

    return _state(room).leases.get(key)


def remove_lease(room: Any, key: str, *, project: bool = True) -> bool:
    """删掉一条租约与它的绑定订阅；不存在返回 False（幂等，不抛）。"""

    state = _state(room)
    if state.leases.pop(key, None) is None:
        return False
    _drop_subscriptions(state, key)
    if project:
        project_effect_flags(room)
    return True


def _flag_holder(room: Any, owner: str) -> Any:
    """取 owner 当前的 EffectFlags；写之前先确认租约投影得回去。"""

    player = (getattr(room, "players", None) or {}).get(owner)
    if player is None:
        raise ValueError(f"标记租约的 owner 不在房间里: {owner}")
    flags = getattr(player, "effect_flags", None)
    if flags is None:
        raise TypeError(f"玩家 {owner} 没有 effect_flags，无法投影标记")
    return flags


def grant_flag(
    room: Any,
    owner: str,
    flag: str,
    *,
    boundary: str,
    value: Any = True,
    payload: dict[str, Any] | None = None,
) -> Lease:
    """给 owner 注册/刷新一个标记租约并立刻投影（回合中的消费者马上看得到）。

    重复施放复用同一条租约：只刷新投影值，边界由构造点固定，不在这里漂移。
    """

    if not owner:
        raise ValueError("标记租约必须有 owner")
    if boundary not in BOUNDARIES:
        raise ValueError(f"未知租约边界: {boundary}")
    if not hasattr(_flag_holder(room, owner), flag):
        raise ValueError(f"未知的效果标记: {flag}")
    state = _state(room)
    key = flag_lease_key(flag, owner)
    lease = state.leases.get(key)
    if lease is None:
        lease = create_lease(
            room,
            key,
            boundary=boundary,
            owner=owner,
            flags={flag: value},
            payload=payload,
        )
    else:
        if lease.boundary != boundary:
            raise ValueError(
                f"租约 {key} 的边界已固定为 {lease.boundary}，不能用 {boundary} 刷新"
            )
        lease.flags[flag] = value
        if payload:
            lease.payload.update(payload)
    project_effect_flags(room)
    return lease


def adjust_flag(
    room: Any, owner: str, flag: str, delta: int, *, boundary: str
) -> int:
    """把整数标记的投影值加减 delta，并立刻投影；减回 0 即删掉租约。

    返回新值；没有租约且减不到正数时是 0（相当于旧语义里的「本来就是 0」）。
    """

    if not owner:
        raise ValueError("标记租约必须有 owner")
    if boundary not in BOUNDARIES:
        raise ValueError(f"未知租约边界: {boundary}")
    holder = _flag_holder(room, owner)
    if not hasattr(holder, flag):
        raise ValueError(f"未知的效果标记: {flag}")
    state = _state(room)
    key = flag_lease_key(flag, owner)
    lease = state.leases.get(key)
    if lease is None:
        current = int(getattr(holder, flag, 0) or 0)
    else:
        if lease.boundary != boundary:
            raise ValueError(
                f"租约 {key} 的边界已固定为 {lease.boundary}，不能用 {boundary} 调整"
            )
        current = int(lease.flags.get(flag, 0) or 0)
    value = max(0, current + int(delta))
    if value == 0:
        remove_lease(room, key, project=False)
    elif lease is None:
        create_lease(room, key, boundary=boundary, owner=owner, flags={flag: value})
    else:
        lease.flags[flag] = value
    project_effect_flags(room)
    return value


def consume_flag(room: Any, owner: str, flag: str) -> bool:
    """消费一条布尔标记租约（对应旧语义里的「把 flag 置回默认值」）。"""

    if not owner:
        raise ValueError("标记租约必须有 owner")
    if not hasattr(_flag_holder(room, owner), flag):
        raise ValueError(f"未知的效果标记: {flag}")
    return remove_lease(room, flag_lease_key(flag, owner))


def project_effect_flags(room: Any) -> None:
    """把活跃租约的 flags 叠加回每个玩家的 EffectFlags（先重置为默认值）。

    投影只是派生视图：先按座位重置成 dataclass 默认值，再按租约注册顺序
    逐条 setattr，后写覆盖先写。未定义的标记名当场报错（拼错不能静默）。
    """

    state = _state(room)
    for player_id, player in (getattr(room, "players", None) or {}).items():
        current = getattr(player, "effect_flags", None)
        if current is None:
            raise TypeError(f"玩家 {player_id} 没有 effect_flags，无法投影")
        rebuilt = type(current)()
        for lease_key, lease in state.leases.items():
            if lease.owner is not None and lease.owner != player_id:
                continue
            for flag, value in lease.flags.items():
                if not hasattr(rebuilt, flag):
                    raise ValueError(f"租约 {lease_key} 投影了未定义的效果标记: {flag}")
                setattr(rebuilt, flag, value)
        player.effect_flags = rebuilt


def reset_all(room: Any) -> None:
    """整对象重置（败者食尘 / 调试重置）：match 边界清租约后再投影。

    这是"棋盘与效果一起归零"的唯一入口；各调用点自己写 expire+project 迟早
    漏掉投影，把幽灵标记留在 effect_flags 上。
    """

    expire(room, BOUNDARY_MATCH)
    project_effect_flags(room)


def clear(room: Any) -> None:
    """清空订阅、租约与待处理事件（房间重置 / 重摆棋盘 / 终局）。

    错误记录保留：它是这间房间的运行期诊断，清掉等于把 bug 一起扫进地毯下。
    """

    state = _state(room)
    state.subscriptions.clear()
    state.leases.clear()
    state.queue.clear()
    state.draining = False
    state.depth = 0


async def emit(room: Any, event: str, payload: dict[str, Any] | None = None) -> None:
    """发射一个事件：入队后由当前 drain 按 FIFO 统一处理。"""

    state = _state(room)
    data = {} if payload is None else payload
    if not isinstance(data, dict):
        raise TypeError(f"hook 载荷必须是 dict: {type(data).__name__}")
    state.queue.append(
        _QueuedEvent(event=event, payload=data, depth=state.depth + 1 if state.draining else 0)
    )
    if state.draining:
        return
    state.draining = True
    processed = 0
    try:
        while state.queue:
            if processed >= MAX_EVENTS_PER_DRAIN:
                state.record_error(
                    f"单次派发事件数超限({MAX_EVENTS_PER_DRAIN})，已停止本次级联"
                )
                state.queue.clear()
                break
            queued = state.queue.popleft()
            if queued.depth > MAX_CASCADE_DEPTH:
                state.record_error(
                    f"事件级联深度超限(>{MAX_CASCADE_DEPTH})：{queued.event}"
                )
                continue
            processed += 1
            state.depth = queued.depth
            await _dispatch(state, queued.event, queued.payload)
    finally:
        state.draining = False
        state.depth = 0
        # 被取消的 drain 不能把旧事件留给下一次 emit。
        state.queue.clear()


async def _dispatch(state: EffectState, event: str, payload: dict[str, Any]) -> None:
    subscriptions = state.subscriptions.get(event)
    if not subscriptions:
        return
    filters = sorted(
        (sub for sub in subscriptions if sub.kind == KIND_FILTER),
        key=lambda sub: (sub.priority, sub.order),
    )
    notifies = sorted(
        (sub for sub in subscriptions if sub.kind == KIND_NOTIFY),
        key=lambda sub: (sub.priority, sub.order),
    )
    for sub in filters:
        await _invoke(state, sub, payload)
    for sub in notifies:
        # notify 只观察：浅拷贝隔离，改不动真实载荷，也影响不到后面的 notify。
        await _invoke(state, sub, dict(payload))


async def _invoke(
    state: EffectState, subscription: Subscription, payload: dict[str, Any]
) -> None:
    try:
        result = subscription.handler(payload)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # noqa: BLE001 - 记录后继续，绝不静默
        state.record_error(
            f"hook 处理异常 [{subscription.event}] "
            f"{_handler_label(subscription.handler)}: {exc!r}"
        )


__all__ = [
    "BOUNDARIES",
    "BOUNDARY_MATCH",
    "BOUNDARY_ROUND",
    "BOUNDARY_TURN",
    "DEFAULT_PRIORITY",
    "EffectState",
    "KINDS",
    "KIND_FILTER",
    "KIND_NOTIFY",
    "Lease",
    "MAX_CASCADE_DEPTH",
    "MAX_EVENTS_PER_DRAIN",
    "FLAG_LEASE_PREFIX",
    "Subscription",
    "adjust_flag",
    "clear",
    "consume",
    "consume_flag",
    "create_lease",
    "emit",
    "expire",
    "flag_lease_key",
    "get_lease",
    "grant_flag",
    "project_effect_flags",
    "remove_lease",
    "reset_all",
    "subscribe",
]
