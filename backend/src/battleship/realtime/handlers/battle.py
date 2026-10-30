"""Socket adapters for placement / RPS / phases (ticket #8).

Only protocol translation: resolve the trusted connection identity, delegate to
:class:`GameplayService`, return its ack. No business rule may grow here.
"""

from __future__ import annotations

from typing import Any

import socketio

from ..identity import connection_from_sio
from ...services.battle import BattleService
from ...services.gameplay import GameplayService


def register_battle_handlers(
    sio: socketio.AsyncServer,
    gameplay: GameplayService,
    battle: BattleService | None = None,
) -> None:
    @sio.on("place_ships")
    async def place_ships(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await gameplay.place_ships(connection, data)

    @sio.on("cancel_placement")
    async def cancel_placement(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await gameplay.cancel_placement(connection, data)

    @sio.on("rps_choice")
    async def rps_choice(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await gameplay.rps_choice(connection, data)

    @sio.on("enter_battle_phase")
    async def enter_battle_phase(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await gameplay.enter_battle_phase(connection, data)

    @sio.on("enter_end_phase")
    async def enter_end_phase(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await gameplay.enter_end_phase(connection, data)

    @sio.on("end_turn")
    async def end_turn(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await gameplay.end_turn(connection, data)

    @sio.on('priority_response')
    async def priority_response(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await gameplay.priority.response(connection, data)

    if battle is not None:
        @sio.on("attack")
        async def attack(sid: str, data: dict[str, Any] | None = None) -> dict:
            connection = await connection_from_sio(sio, sid)
            return await battle.attack(connection, data)

        @sio.on("surrender")
        async def surrender(sid: str, data: dict[str, Any] | None = None) -> dict:
            connection = await connection_from_sio(sio, sid)
            return await battle.surrender(connection, data)
