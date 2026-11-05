"""组合根：配置 -> 日志 -> FastAPI(HTTP/静态/旧页面) -> Socket.IO ASGI。

一条命令启动（在 worktree 根目录）：
    python -m battleship
`app` 是给 uvicorn 用的 ASGI 组合对象，形如：
    uvicorn battleship.main:app
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import socketio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import Settings, load_settings
from .http.routers import admin as admin_router
from .http.routers import battle_pass as battle_pass_router
from .http.routers import shop as shop_router
from .http.routers import support as support_router
from .http.routers import client_promo as client_promo_router
from .http.routers import mailbox as mailbox_router
from .http.routers import auth as auth_router
from .http.routers import chat as chat_router
from .http.routers import contracts as contracts_router
from .http.routers import frontend as frontend_router
from .http.routers import friends as friends_router
from .http.routers import health as health_router
from .http.routers import leaderboard as leaderboard_router
from .http.routers import lobby as lobby_router
from .http.routers import profile as profile_router
from .http.routers import progression as progression_router
from .http.routers import replay as replay_router
from .http.routers import spectate as spectate_router
from .http.routers import stats as stats_router
from .http.routers import tasks as tasks_router
from .http.routers import daily_challenge as daily_challenge_router
from .http.routers import admin_console as admin_console_router
from .http.routers import wallpapers as wallpapers_router
from .infra.assets import AssetPaths
from .infra.health import HealthService
from .infra.logging import configure_logging, get_logger, log_context
from .infra.backup import Maintenance
from .infra.metrics import MetricsRegistry
from .infra.ratelimit import RateLimiter
from .realtime.server import create_socket_server
from .repositories import Database
from .services.ai import AiService
from .services.anticheat import AnticheatService
from .services.auth import AuthService
from .services.battle_pass import BattlePassService
from .services.battle import BattleService
from .services.chat import ChatService
from .services.friends import FriendsService
from .services.gameplay import GameplayService
from .services.lobby import LobbyService
from .services.magic import MagicService
from .services.matchmaking import MatchmakingService
from .services.presence import PresenceService
from .services.progression import ProgressionService
from .services.ranked_seasons import RankedSeasonService
from .services.replays import allowed_for_match, build_replay
from .services.rooms import RoomService
from .services.settlement import SettlementService
from .services.spectators import SpectatorService

logger = get_logger("main")

_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    500: "internal_error",
    503: "service_unavailable",
}


@dataclass
class Application:
    settings: Settings
    fastapi: FastAPI
    sio: socketio.AsyncServer
    asgi: Any
    metrics: MetricsRegistry
    health: HealthService
    assets: AssetPaths
    database: Database
    rooms: RoomService
    gameplay: GameplayService
    battle: BattleService
    magic: MagicService
    settlement: SettlementService
    progression: ProgressionService
    battle_pass: BattlePassService
    anticheat: AnticheatService
    auth: AuthService
    matchmaking: MatchmakingService
    lobby: LobbyService
    presence: PresenceService
    friends: FriendsService
    chat: ChatService
    spectators: SpectatorService
    ai: AiService


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    logger.info("backend starting", extra={"version": __version__})
    # The turn watchdog needs a running loop, so it starts with the ASGI
    # lifespan (ticket #8). `TURN_TIMEOUT_SECONDS=0` makes each sweep a no-op.
    gameplay = getattr(_app.state, "gameplay", None)
    if gameplay is not None:
        gameplay.start()
    maintenance = getattr(_app.state, 'maintenance', None)
    if maintenance is not None:
        maintenance.start()
    magic = getattr(_app.state, "magic", None)
    try:
        yield
    finally:
        if maintenance is not None:
            await maintenance.stop()
        if gameplay is not None:
            await gameplay.stop()
        if magic is not None:
            await magic.stop()
        database = getattr(_app.state, "database", None)
        if database is not None:
            database.dispose()
        logger.info("backend stopping", extra={"version": __version__})


def _error_response(status_code: int, code: str, message: str, field: str | None = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if field:
        error["field"] = field
    return JSONResponse({"error": error}, status_code=status_code)


async def _http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code") or _HTTP_CODES.get(exc.status_code, "http_error"))
        message = str(detail.get("message") or detail)
        field = detail.get("field")
    else:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = str(detail)
        field = None
    return _error_response(exc.status_code, code, message, field)


async def _validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    location = [str(part) for part in first.get("loc", ()) if part not in ("body", "query", "path")]
    field = ".".join(location) or None
    message = str(first.get("msg") or "请求参数校验失败")
    return _error_response(422, "validation_error", message, field)


async def _unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception", extra={"error_type": type(exc).__name__})
    return _error_response(500, "internal_error", "服务器内部错误")


def _seed_game_rng(seed: int) -> None:
    """Make draws/AI deterministic under the frozen contract fixtures.

    The legacy stack imports rich while starting, and rich.style draws one
    24-bit value at import time before any game rule runs. The recorded
    fixtures were produced after that draw, so a candidate backend must consume
    the same single value to land on the same shuffled deck. This is a
    deterministic startup offset, not a new game rule.
    """

    import random

    random.seed(int(seed))
    random.getrandbits(24)


def create_application(settings: Settings | None = None,
                       database: Database | None = None) -> Application:
    settings = settings or load_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json, error_log_path=settings.error_log_path)
    if settings.seed is not None:
        _seed_game_rng(settings.seed)

    metrics = MetricsRegistry()
    assets = AssetPaths.discover()
    database = database or Database.from_settings(settings)
    rate_limiter = RateLimiter()
    # Ticket #18: the real recorder replaces the ticket-9 placeholder, and the
    # allow_replay gate is evaluated once inside the settlement transaction.
    settlement = SettlementService(
        database,
        replay_builder=build_replay,
        replay_gate=lambda winner, loser: allowed_for_match(database, winner, loser),
    )
    # #16 registers first so the anti-cheat verdict exists before the rank hook:
    # a blocked match still settles wins/XP/badges but must not move rank points.
    anticheat = AnticheatService(database)
    anticheat.register(settlement)
    # #15 owns the progression settlement hooks: XP / rank points / badges are
    # written inside the same #9 transaction and emitted around game_over.
    progression = ProgressionService(database)
    progression.register(settlement)
    battle_pass = BattlePassService(database)
    settlement.add_hook(battle_pass.settlement_hook)
    ranked_seasons = RankedSeasonService(database)

    fastapi_app = FastAPI(
        title="Battleship 1.0 backend",
        version=__version__,
        lifespan=_lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    if settings.cors_origins:
        fastapi_app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # L5（issue #32）完整 CSP：前端全部资源同源（构建产物、卡图、头像、音效、
    # Socket 同源连接），无外部字体/脚本；Vue 动态样式需要内联样式放行；头像
    # 本地预览经 blob: URL。/api/docs（Swagger）依赖 CDN 资源，不套全量 CSP，
    # 其嵌框防护由 X-Frame-Options 覆盖。HSTS 随 HTTPS 批次落地。
    _CSP_POLICY = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' blob:; connect-src 'self'; media-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )

    def _apply_security_headers(response, path: str = "") -> None:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if not path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", _CSP_POLICY)

    # L11（issue #32）：按内容类型预检 Content-Length。头像走 multipart（端点内
    # 另有 2MB 图片内容上限，这里放行表单开销），JSON/表单按宽松业务上限拒绝。
    _BODY_LIMITS: tuple[tuple[str, int], ...] = (
        ("multipart/form-data", 8 * 1024 * 1024),
        ("application/json", 256 * 1024),
        ("application/x-www-form-urlencoded", 256 * 1024),
    )
    _DEFAULT_BODY_LIMIT = 256 * 1024

    def _body_limit(content_type: str) -> int:
        for prefix, cap in _BODY_LIMITS:
            if content_type == prefix or content_type.startswith(prefix + ";"):
                return cap
        return _DEFAULT_BODY_LIMIT

    @fastapi_app.middleware("http")
    async def _request_context(request: Request, call_next):
        request_id = (request.headers.get("x-request-id") or "").strip() or uuid.uuid4().hex
        started = time.perf_counter()
        if request.method in ("POST", "PUT", "PATCH"):
            declared = request.headers.get("content-length") or ""
            if declared.isdigit() and int(declared) > _body_limit(
                (request.headers.get("content-type") or "").split(";")[0].strip().lower()
            ):
                # 先耗尽已声明的请求体（有界），让客户端拿到干净的 413，
                # 而不是发送途中被重置连接；超出的字节不进入任何业务处理。
                drained = 0
                async for _chunk in request.stream():
                    drained += len(_chunk)
                    if drained > 64 * 1024 * 1024:
                        break
                metrics.record_http(413, 0.0)
                response = JSONResponse({"error": "请求体过大"}, status_code=413)
                response.headers["X-Request-ID"] = request_id
                _apply_security_headers(response, request.url.path)
                return response
        with log_context(request_id=request_id, method=request.method, path=request.url.path):
            try:
                if request.url.path.startswith('/api/'):
                    ranked_seasons.current()
                response = await call_next(request)
            except Exception:
                duration_ms = (time.perf_counter() - started) * 1000
                metrics.record_http(500, duration_ms)
                logger.exception(
                    "http request failed",
                    extra={"status": 500, "duration_ms": round(duration_ms, 3)},
                )
                raise

            duration_ms = (time.perf_counter() - started) * 1000
            if response.status_code >= 400 and request.url.path in ('/login', '/api/login'):
                logger.warning('登录失败', extra={'status': response.status_code})
            elif response.status_code >= 400 and request.url.path.startswith(('/api/mailbox/', '/api/admin/mailbox/')):
                logger.warning('邮件操作失败', extra={'status': response.status_code})
            metrics.record_http(response.status_code, duration_ms)
            response.headers["X-Request-ID"] = request_id
            _apply_security_headers(response, request.url.path)
            logger.info(
                "http request",
                extra={"status": response.status_code, "duration_ms": round(duration_ms, 3)},
            )
            return response

    fastapi_app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    fastapi_app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    fastapi_app.add_exception_handler(Exception, _unhandled_exception_handler)

    fastapi_app.include_router(health_router.router)
    fastapi_app.include_router(contracts_router.router)
    # Auth owns /login, /register, /logout and /api/login; it must be included
    # before the legacy page router so those paths resolve to the session-aware
    # handlers rather than the read-only template entry.
    fastapi_app.include_router(auth_router.router)
    fastapi_app.include_router(profile_router.router)
    fastapi_app.include_router(progression_router.router)
    fastapi_app.include_router(wallpapers_router.router)
    fastapi_app.include_router(stats_router.router)
    fastapi_app.include_router(tasks_router.router)
    fastapi_app.include_router(daily_challenge_router.router)
    fastapi_app.include_router(leaderboard_router.router)
    fastapi_app.include_router(replay_router.router)
    fastapi_app.include_router(lobby_router.router)
    fastapi_app.include_router(friends_router.router)
    fastapi_app.include_router(chat_router.router)
    fastapi_app.include_router(spectate_router.router)
    fastapi_app.include_router(admin_router.router)
    fastapi_app.include_router(battle_pass_router.router)
    fastapi_app.include_router(shop_router.router)
    fastapi_app.include_router(support_router.router)
    fastapi_app.include_router(client_promo_router.router)
    fastapi_app.include_router(mailbox_router.router)
    fastapi_app.include_router(admin_console_router.router)

    # User-uploaded avatars are the only surviving piece of `static/`; they keep
    # the frozen /static/avatars/... URL so existing profile rows still resolve.
    assets.avatars_dir.mkdir(parents=True, exist_ok=True)
    fastapi_app.mount(
        "/static/avatars",
        StaticFiles(directory=str(assets.avatars_dir)),
        name="static-avatars",
    )
    # 客户端安装包与版本清单（latest.json）；目录为空时壳的更新检查静默跳过。
    assets.clients_dir.mkdir(parents=True, exist_ok=True)
    fastapi_app.mount(
        "/static/clients",
        StaticFiles(directory=str(assets.clients_dir)),
        name="static-clients",
    )

    # Phase 5: exactly one frontend. The built Vue shell is mounted on the same
    # ASGI app; a missing build aborts startup inside install() instead of
    # silently serving an empty page. The SPA router is included last so every
    # API router above wins.
    dist = settings.frontend_dist or assets.frontend_dist
    if not Path(dist).is_absolute():
        dist = assets.root / dist
    build_id = frontend_router.install(fastapi_app, dist)
    logger.info(
        "frontend shell mounted",
        extra={"dist": str(dist), "build": build_id},
    )

    # One presence instance for the room service, the lobby and the friends
    # service (CLAUDE #17: the online table must exist exactly once).
    presence = PresenceService()
    auth = AuthService(database, settings)
    auth.provision_admin_cosmetics()
    rooms = RoomService(
        presence=presence,
        capability_gate=auth.capability_denied,
        turn_timeout_seconds=settings.turn_timeout_seconds,
    )
    gameplay = GameplayService(
        rooms, turn_timeout_seconds=settings.turn_timeout_seconds
    )
    battle = BattleService(rooms, settlement, touch_turn=gameplay.touch_turn)
    from .services.daily_challenge import DailyChallengeService
    daily_challenges = DailyChallengeService(database, rooms, settings.daily_puzzles_path)
    daily_challenges.battle = battle
    rooms.daily_challenges = settlement.daily_challenges = daily_challenges
    fastapi_app.state.daily_challenges = daily_challenges
    magic = MagicService(
        rooms,
        settlement,
        touch_turn=gameplay.touch_turn,
        chain_display_delay_seconds=settings.chain_display_delay_seconds,
    )
    # #11 magic lifecycle seams: judgements at turn starts, effect-flag/board
    # cleanup at big-round boundaries, and AI reset-board completion in-frame.
    gameplay.magic = magic
    gameplay.turn_start_hook = lambda room, _pid: magic.settle_wuyou_dream(room)
    gameplay.draw_skip_hook = magic.consume_bingliang_skip
    gameplay.after_draw_hook = lambda room, _pid: magic.settle_bingliang(room)
    gameplay.round_end_hook = magic.on_new_big_round
    magic.ai_place_hook = gameplay.ai_place_board_now
    # Ticket #8 left two explicit seams; #9 fills both: the turn watchdog fires
    # through the same attack rules, and disconnect forfeits settle for real.
    gameplay.fire_hook = battle.fire
    rooms.forfeit_hook = battle.settle_forfeit
    lobby = LobbyService(rooms, presence, database)
    # Ticket #16: queue/pairing plus the ban gates live in the service; the ban
    # gate is the same AuthService instance used by the HTTP dependencies.
    matchmaking = MatchmakingService(
        rooms, database=database, auth=auth, lobby=lobby
    )
    friends = FriendsService(database, presence, rooms)
    # Legacy _finalize_match pushed recent_opponent to both seats before
    # game_over; the settlement hook keeps that on the single ending funnel.
    settlement.add_hook(friends.recent_opponent_hook)
    chat = ChatService(rooms)
    spectators = SpectatorService(rooms, database)
    # Ticket #13: the AI turn driver (one executor for every difficulty tier).
    ai = AiService(rooms, gameplay, battle, magic, timers=magic.timers)
    gameplay.ai_turn_hook = ai.run_turn
    lobby.spectators = spectators
    sio = create_socket_server(
        settings, metrics, rooms, gameplay, battle, magic, lobby, presence, friends,
        chat, matchmaking, spectators, ai,
        database=database,
    )
    health = HealthService(settings, metrics, version=__version__, socketio_ready=True)

    fastapi_app.state.settings = settings
    fastapi_app.state.metrics = metrics
    fastapi_app.state.health = health
    fastapi_app.state.assets = assets
    fastapi_app.state.sio = sio
    fastapi_app.state.database = database
    fastapi_app.state.rate_limiter = rate_limiter
    fastapi_app.state.rooms = rooms
    fastapi_app.state.gameplay = gameplay
    fastapi_app.state.battle = battle
    fastapi_app.state.magic = magic
    fastapi_app.state.settlement = settlement
    fastapi_app.state.progression = progression
    fastapi_app.state.battle_pass = battle_pass
    fastapi_app.state.ranked_seasons = ranked_seasons
    fastapi_app.state.maintenance = Maintenance(database, ranked_seasons, settings.backup_directory)
    fastapi_app.state.anticheat = anticheat
    fastapi_app.state.auth = auth
    from .services.admin_console import AdminConsole
    fastapi_app.state.admin_console = AdminConsole(auth, rooms, battle, magic, gameplay)
    fastapi_app.state.matchmaking = matchmaking
    fastapi_app.state.lobby = lobby
    fastapi_app.state.presence = presence
    fastapi_app.state.friends = friends
    fastapi_app.state.chat = chat
    fastapi_app.state.spectators = spectators
    fastapi_app.state.ai = ai

    asgi = socketio.ASGIApp(sio, other_asgi_app=fastapi_app, socketio_path="socket.io")
    return Application(
        settings=settings,
        fastapi=fastapi_app,
        sio=sio,
        asgi=asgi,
        metrics=metrics,
        health=health,
        assets=assets,
        database=database,
        rooms=rooms,
        gameplay=gameplay,
        battle=battle,
        magic=magic,
        settlement=settlement,
        progression=progression,
        battle_pass=battle_pass,
        anticheat=anticheat,
        auth=auth,
        matchmaking=matchmaking,
        lobby=lobby,
        presence=presence,
        friends=friends,
        chat=chat,
        spectators=spectators,
        ai=ai,
    )


# uvicorn battleship.main:app
app = create_application().asgi
