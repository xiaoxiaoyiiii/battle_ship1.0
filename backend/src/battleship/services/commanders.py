"""指挥官角色系统服务：解锁、选角、领奖、装配、开局装载与对局经验结算。"""

from __future__ import annotations

import random
import time
from typing import Any

from ..domain.anticheat import rules as anticheat_rules
from ..domain.commanders import (
    AI_DAILY_XP_CAP,
    COMMANDER_IDS,
    COMMANDERS,
    DEFAULT_COMMANDER_ID,
    DEFAULT_EQUIPPED,
    MAX_LEVEL,
    UNLOCK_COST_TIDE_ASH,
    CommanderSpec,
    clamp_xp,
    compute_match_commander_xp,
    cst_day_key,
    get_commander,
    level_for_xp,
    xp_progress_view,
)
from ..domain.room import Room
from ..infra.logging import get_logger
from ..repositories import Database, UnitOfWork
from .settlement import SettlementContext

logger = get_logger("commanders")

PROFILE_COSMETIC_KINDS = frozenset({"frame", "card_bg", "title"})


def _unlocked_options_for(claimed: set[int]) -> dict[str, Any]:
    """根据已领取奖励等级集合，派生可装配的外观/语音选项列表。"""
    portraits = ["base"]
    if 10 in claimed:
        portraits.append("ascended")
    if 17 in claimed:
        portraits.append("alt")
    if 20 in claimed:
        portraits.append("ultimate")

    voice_packs = ["base"]
    if 14 in claimed:
        voice_packs.append("skill_2")
    if 19 in claimed:
        voice_packs.append("mastery")

    voices: list[str] = []
    for lvl, key in (
        (2, "voice_greet"),
        (4, "voice_sortie"),
        (6, "voice_skill_1"),
        (8, "voice_victory"),
        (11, "voice_interact"),
        (14, "voice_skill_2"),
        (19, "voice_mastery"),
    ):
        if lvl in claimed:
            voices.append(key)

    intros = ["base"]
    if 15 in claimed:
        intros.append("enhanced")
    if 20 in claimed:
        intros.append("ultimate")

    skill_vfx = ["base"]
    if 15 in claimed:
        skill_vfx.append("exclusive")

    victory_motions = ["base"]
    if 13 in claimed:
        victory_motions.append("exclusive")

    avatars = ["default"]
    if 5 in claimed:
        avatars.append("commander")

    emojis: list[str] = []
    for lvl, key in (
        (3, "emoji_1"),
        (7, "emoji_2"),
        (12, "emoji_3"),
        (16, "emoji_dynamic"),
    ):
        if lvl in claimed:
            emojis.append(key)

    return {
        "portraits": portraits,
        "voice_packs": voice_packs,
        "voices": voices,
        "intros": intros,
        "skill_vfx": skill_vfx,
        "victory_motions": victory_motions,
        "avatars": avatars,
        "emojis": emojis,
    }


def _sanitized_equipped(raw: dict[str, str], unlocked: dict[str, Any]) -> dict[str, str]:
    equipped = dict(DEFAULT_EQUIPPED)
    for key, val in raw.items():
        if key in equipped and isinstance(val, str):
            equipped[key] = val
    if equipped["portrait"] not in unlocked["portraits"]:
        equipped["portrait"] = "base"
    if equipped["voice_pack"] not in unlocked["voice_packs"]:
        equipped["voice_pack"] = "base"
    if equipped["intro"] not in unlocked["intros"]:
        equipped["intro"] = "base"
    if equipped["skill_vfx"] not in unlocked["skill_vfx"]:
        equipped["skill_vfx"] = "base"
    if equipped["victory_motion"] not in unlocked["victory_motions"]:
        equipped["victory_motion"] = "base"
    if equipped["avatar"] not in unlocked["avatars"]:
        equipped["avatar"] = "default"
    if unlocked["emojis"] and equipped["emoji_slot"] not in unlocked["emojis"]:
        equipped["emoji_slot"] = unlocked["emojis"][0]
    elif not unlocked["emojis"]:
        equipped["emoji_slot"] = ""
    return equipped


def _reward_items_payload(spec: CommanderSpec, claimed: set[int], current_level: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lvl in range(2, MAX_LEVEL + 1):
        entry = spec.rewards[lvl]
        unlocked_lv = current_level >= lvl
        is_claimed = lvl in claimed
        rows.append({
            **entry,
            "unlocked": unlocked_lv,
            "claimed": is_claimed,
            "claimable": unlocked_lv and not is_claimed,
        })
    return rows


class CommanderService:
    def __init__(self, database: Database | None = None, *, clock=None) -> None:
        self.database = database
        self.clock = clock or time.time

    # ------------------------------------------------------------------ queries

    def view(self, user_id: str | None, *, now: int | None = None) -> dict[str, Any]:
        ts = int(self.clock()) if now is None else int(now)
        day = cst_day_key(ts)
        if not user_id or self.database is None:
            return self._guest_view(day)

        with self.database.unit_of_work() as uow:
            if not uow.users.get(user_id):
                return self._guest_view(day)
            return self._build_user_view(uow, user_id, day)

    @staticmethod
    def _guest_view(day_cst: str) -> dict[str, Any]:
        commanders = []
        for spec in COMMANDERS:
            data = spec.to_dict()
            unlocked = _unlocked_options_for(set())
            commanders.append({
                **data,
                "owned": False,
                "selected": spec.id == DEFAULT_COMMANDER_ID,
                "unlock_source": None,
                "cost_paid": 0,
                "unlock_cost": 0 if spec.id == DEFAULT_COMMANDER_ID else UNLOCK_COST_TIDE_ASH,
                "progress": xp_progress_view(0),
                "equipped": _sanitized_equipped(dict(DEFAULT_EQUIPPED), unlocked),
                "unlocked_options": unlocked,
                "claimed_levels": [],
                "claimable_levels": [],
                "reward_track": _reward_items_payload(spec, set(), 1),
            })
        return {
            "ok": True,
            "authenticated": False,
            "tide_ash_balance": 0,
            "unlock_cost": UNLOCK_COST_TIDE_ASH,
            "free_initial_available": False,
            "selected_commander_id": DEFAULT_COMMANDER_ID,
            "ai_daily_xp_used": 0,
            "ai_daily_xp_cap": AI_DAILY_XP_CAP,
            "day_cst": day_cst,
            "commanders": commanders,
        }

    @staticmethod
    def _build_user_view(uow: UnitOfWork, user_id: str, day_cst: str) -> dict[str, Any]:
        owned_map = uow.commanders.list_owned(user_id)
        selection = uow.commanders.get_selection(user_id)
        claims_map = uow.commanders.claimed_levels(user_id)
        balance = uow.tide_ash.balance(user_id)
        ai_daily_used = uow.commanders.ai_daily_xp_used(user_id, day_cst)

        free_available = (not owned_map) and (selection is None or not selection["free_claimed"])
        selected_id = (
            selection["selected_commander_id"]
            if selection and selection["selected_commander_id"] in owned_map
            else (next(iter(owned_map)) if owned_map else None)
        )

        commanders = []
        for spec in COMMANDERS:
            owned_row = owned_map.get(spec.id)
            claimed = claims_map.get(spec.id, set())
            is_owned = owned_row is not None
            current_xp = int(owned_row["xp"]) if owned_row else 0
            progress = xp_progress_view(current_xp)
            current_level = int(progress["level"]) if is_owned else 1
            unlocked = _unlocked_options_for(claimed if is_owned else set())
            equipped = _sanitized_equipped(
                owned_row["equipped"] if owned_row else dict(DEFAULT_EQUIPPED),
                unlocked,
            )
            reward_track = _reward_items_payload(spec, claimed, current_level if is_owned else 0)
            claimable_levels = [r["level"] for r in reward_track if r["claimable"]]

            commanders.append({
                **spec.to_dict(),
                "owned": is_owned,
                "selected": spec.id == selected_id,
                "unlock_source": owned_row["unlock_source"] if owned_row else None,
                "cost_paid": owned_row["cost_paid"] if owned_row else 0,
                "unlock_cost": 0 if free_available else UNLOCK_COST_TIDE_ASH,
                "progress": progress,
                "equipped": equipped,
                "unlocked_options": unlocked,
                "claimed_levels": sorted(claimed),
                "claimable_levels": claimable_levels,
                "reward_track": reward_track,
            })

        return {
            "ok": True,
            "authenticated": True,
            "tide_ash_balance": balance,
            "unlock_cost": UNLOCK_COST_TIDE_ASH,
            "free_initial_available": free_available,
            "selected_commander_id": selected_id or DEFAULT_COMMANDER_ID,
            "has_owned_commander": bool(owned_map),
            "ai_daily_xp_used": ai_daily_used,
            "ai_daily_xp_cap": AI_DAILY_XP_CAP,
            "day_cst": day_cst,
            "commanders": commanders,
        }

    # ---------------------------------------------------------------- commands

    def unlock(self, user_id: str | None, commander_id: str, *, now: int | None = None) -> dict[str, Any]:
        ts = int(self.clock()) if now is None else int(now)
        day = cst_day_key(ts)
        if not user_id or self.database is None:
            return {"ok": False, "reason": "unauthorized", "message": "请先登录"}
        spec = get_commander(commander_id)
        if spec is None:
            return {"ok": False, "reason": "invalid_commander", "message": "未知的指挥官角色"}

        with self.database.unit_of_work() as uow:
            if not uow.users.get(user_id):
                return {"ok": False, "reason": "unauthorized", "message": "账号不存在"}
            uow.tide_ash.lock(user_id, now=ts)
            owned_map = uow.commanders.list_owned(user_id)
            selection = uow.commanders.get_selection(user_id)
            if spec.id in owned_map:
                view = self._build_user_view(uow, user_id, day)
                return {
                    **view,
                    "ok": True,
                    "already_owned": True,
                    "unlock_source": owned_map[spec.id]["unlock_source"],
                    "cost_paid": 0,
                    "message": f"你已拥有指挥官「{spec.name}」",
                }

            free_eligible = (not owned_map) and (selection is None or not selection["free_claimed"])
            if free_eligible:
                inserted = uow.commanders.unlock_once(
                    user_id, spec.id, unlock_source="free_initial", cost_paid=0, now=ts
                )
                if not inserted:
                    view = self._build_user_view(uow, user_id, day)
                    return {**view, "ok": True, "already_owned": True, "cost_paid": 0}
                uow.commanders.set_selection(user_id, spec.id, free_claimed=True, now=ts)
                view = self._build_user_view(uow, user_id, day)
                return {
                    **view,
                    "ok": True,
                    "already_owned": False,
                    "unlock_source": "free_initial",
                    "cost_paid": 0,
                    "message": f"已免费解锁首位指挥官「{spec.name}」并设为出战",
                }

            balance = uow.tide_ash.balance(user_id)
            if balance < UNLOCK_COST_TIDE_ASH:
                return {
                    "ok": False,
                    "reason": "insufficient_funds",
                    "message": f"潮汐徽记不足，解锁「{spec.name}」需要 {UNLOCK_COST_TIDE_ASH} 枚",
                    "tide_ash_balance": balance,
                    "unlock_cost": UNLOCK_COST_TIDE_ASH,
                }
            if not uow.tide_ash.apply_once(
                user_id, "commander_unlock", spec.id, -UNLOCK_COST_TIDE_ASH, now=ts
            ):
                view = self._build_user_view(uow, user_id, day)
                if spec.id in uow.commanders.list_owned(user_id):
                    return {**view, "ok": True, "already_owned": True, "cost_paid": 0}
                return {
                    "ok": False,
                    "reason": "conflict",
                    "message": "解锁扣款冲突，请刷新后重试",
                    "tide_ash_balance": uow.tide_ash.balance(user_id),
                }
            inserted = uow.commanders.unlock_once(
                user_id, spec.id, unlock_source="tide_ash", cost_paid=UNLOCK_COST_TIDE_ASH, now=ts
            )
            if not inserted:
                raise RuntimeError("指挥官解锁落库冲突，扣款已回滚")
            view = self._build_user_view(uow, user_id, day)
            return {
                **view,
                "ok": True,
                "already_owned": False,
                "unlock_source": "tide_ash",
                "cost_paid": UNLOCK_COST_TIDE_ASH,
                "message": f"已消耗 {UNLOCK_COST_TIDE_ASH} 潮汐徽记解锁指挥官「{spec.name}」",
            }

    def select(self, user_id: str | None, commander_id: str, *, now: int | None = None) -> dict[str, Any]:
        ts = int(self.clock()) if now is None else int(now)
        day = cst_day_key(ts)
        if not user_id or self.database is None:
            return {"ok": False, "reason": "unauthorized", "message": "请先登录"}
        spec = get_commander(commander_id)
        if spec is None:
            return {"ok": False, "reason": "invalid_commander", "message": "未知的指挥官角色"}

        with self.database.unit_of_work() as uow:
            if not uow.users.get(user_id):
                return {"ok": False, "reason": "unauthorized", "message": "账号不存在"}
            if uow.commanders.get_owned(user_id, spec.id) is None:
                return {"ok": False, "reason": "not_owned", "message": f"尚未解锁指挥官「{spec.name}」"}
            selection = uow.commanders.get_selection(user_id)
            free_claimed = bool(selection["free_claimed"]) if selection else True
            uow.commanders.set_selection(user_id, spec.id, free_claimed=free_claimed, now=ts)
            view = self._build_user_view(uow, user_id, day)
            return {**view, "ok": True, "message": f"已将「{spec.name}」设为出战指挥官"}

    def claim(
        self,
        user_id: str | None,
        commander_id: str,
        level: int | None = None,
        *,
        claim_all: bool = False,
        now: int | None = None,
    ) -> dict[str, Any]:
        ts = int(self.clock()) if now is None else int(now)
        day = cst_day_key(ts)
        if not user_id or self.database is None:
            return {"ok": False, "reason": "unauthorized", "message": "请先登录"}
        spec = get_commander(commander_id)
        if spec is None:
            return {"ok": False, "reason": "invalid_commander", "message": "未知的指挥官角色"}

        with self.database.unit_of_work() as uow:
            if not uow.users.get(user_id):
                return {"ok": False, "reason": "unauthorized", "message": "账号不存在"}
            row = uow.commanders.get_owned(user_id, spec.id)
            if row is None:
                return {"ok": False, "reason": "not_owned", "message": f"尚未解锁指挥官「{spec.name}」"}
            current_level = level_for_xp(int(row.xp or 0))
            already = uow.commanders.claimed_levels(user_id, spec.id).get(spec.id, set())

            if claim_all:
                targets = [lvl for lvl in range(2, current_level + 1) if lvl not in already]
            else:
                if level is None or not isinstance(level, int) or level < 2 or level > MAX_LEVEL:
                    return {"ok": False, "reason": "invalid_level", "message": "无效的奖励等级"}
                if level > current_level:
                    return {
                        "ok": False,
                        "reason": "level_locked",
                        "message": f"「{spec.name}」当前为 {current_level} 级，尚未达到 {level} 级",
                    }
                targets = [level]

            newly_claimed: list[int] = []
            for lvl in targets:
                if not uow.commanders.claim_level_once(user_id, spec.id, lvl, now=ts):
                    continue
                newly_claimed.append(lvl)
                reward = spec.rewards.get(lvl) or {}
                for item in reward.get("items") or ():
                    if item.get("kind") in PROFILE_COSMETIC_KINDS and item.get("id"):
                        uow.commanders.grant_profile_cosmetic(
                            user_id,
                            str(item["kind"]),
                            str(item["id"]),
                            source_level=lvl,
                            now=ts,
                        )
            # 重要：绝不自动覆盖玩家当前已装备的旧档外观！
            view = self._build_user_view(uow, user_id, day)
            return {
                **view,
                "ok": True,
                "newly_claimed": newly_claimed,
                "already_claimed": not bool(newly_claimed),
                "message": (
                    f"已领取「{spec.name}」{len(newly_claimed)} 项成长奖励"
                    if newly_claimed
                    else "对应等级奖励已领取"
                ),
            }

    def equip(
        self,
        user_id: str | None,
        commander_id: str,
        equipped_patch: dict[str, Any] | None,
        *,
        now: int | None = None,
    ) -> dict[str, Any]:
        ts = int(self.clock()) if now is None else int(now)
        day = cst_day_key(ts)
        if not user_id or self.database is None:
            return {"ok": False, "reason": "unauthorized", "message": "请先登录"}
        spec = get_commander(commander_id)
        if spec is None:
            return {"ok": False, "reason": "invalid_commander", "message": "未知的指挥官角色"}
        if not isinstance(equipped_patch, dict):
            return {"ok": False, "reason": "invalid_payload", "message": "装配参数格式不正确"}

        with self.database.unit_of_work() as uow:
            if not uow.users.get(user_id):
                return {"ok": False, "reason": "unauthorized", "message": "账号不存在"}
            row = uow.commanders.get_owned(user_id, spec.id)
            if row is None:
                return {"ok": False, "reason": "not_owned", "message": f"尚未解锁指挥官「{spec.name}」"}
            claimed = uow.commanders.claimed_levels(user_id, spec.id).get(spec.id, set())
            unlocked = _unlocked_options_for(claimed)

            slot_allowed = {
                "portrait": unlocked["portraits"],
                "voice_pack": unlocked["voice_packs"],
                "intro": unlocked["intros"],
                "skill_vfx": unlocked["skill_vfx"],
                "victory_motion": unlocked["victory_motions"],
                "avatar": unlocked["avatars"],
                "emoji_slot": unlocked["emojis"],
            }
            clean_patch: dict[str, str] = {}
            for slot, val in equipped_patch.items():
                if slot not in slot_allowed:
                    continue
                if not isinstance(val, str) or val not in slot_allowed[slot]:
                    return {
                        "ok": False,
                        "reason": "cosmetic_locked",
                        "message": f"所选外观尚未解锁或未领取奖励：{slot}={val}",
                    }
                clean_patch[slot] = val

            uow.commanders.update_equipped(user_id, spec.id, clean_patch, now=ts)
            view = self._build_user_view(uow, user_id, day)
            return {**view, "ok": True, "message": f"已更新「{spec.name}」外观与语音装配"}

    # ------------------------------------------------------------ match loadout

    def resolve_loadout(
        self,
        user_id: str | None,
        requested_commander_id: str | None = None,
        *,
        is_ai: bool = False,
        ai_difficulty: str = "normal",
        rng: Any = None,
    ) -> dict[str, Any]:
        """为进局座位生成服务端权威指挥官装载信息。"""
        if is_ai:
            chosen = (rng or random).choice(COMMANDER_IDS)
            # 不同难度展示递进视觉档位，所有技能保持零战力加成。
            diff_level = {"easy": 1, "normal": 5, "hard": 10, "master": 20}.get(ai_difficulty, 5)
            claimed = {lvl for lvl in (2, 3, 4, 5, 6, 8, 10, 11, 13, 14, 15, 16, 17, 19, 20) if lvl <= diff_level}
            unlocked = _unlocked_options_for(claimed)
            cosmetics = {
                "portrait": unlocked["portraits"][-1],
                "voice_pack": unlocked["voice_packs"][-1],
                "intro": unlocked["intros"][-1],
                "skill_vfx": unlocked["skill_vfx"][-1],
                "victory_motion": unlocked["victory_motions"][-1],
                "avatar": unlocked["avatars"][-1],
                "unlocked_voices": unlocked["voices"],
                "unlocked_emojis": unlocked["emojis"],
                "title": get_commander(chosen).profile_cosmetics["title_20_name"] if 20 in claimed else "",
                "frame": (
                    get_commander(chosen).profile_cosmetics["frame_2"]
                    if 10 in claimed
                    else (get_commander(chosen).profile_cosmetics["frame_1"] if 5 in claimed else "none")
                ),
            }
            return {
                "commander_id": chosen,
                "commander_level": diff_level,
                "cosmetics": cosmetics,
            }

        req_spec = get_commander(requested_commander_id)
        if user_id and self.database is not None:
            with self.database.unit_of_work() as uow:
                owned_map = uow.commanders.list_owned(user_id)
                selection = uow.commanders.get_selection(user_id)
                chosen_id: str | None = None
                if req_spec and req_spec.id in owned_map:
                    chosen_id = req_spec.id
                    free_claimed = bool(selection["free_claimed"]) if selection else True
                    uow.commanders.set_selection(user_id, chosen_id, free_claimed=free_claimed)
                elif selection and selection["selected_commander_id"] in owned_map:
                    chosen_id = selection["selected_commander_id"]
                elif owned_map:
                    chosen_id = next(iter(owned_map))

                if chosen_id and chosen_id in owned_map:
                    row = owned_map[chosen_id]
                    claimed = uow.commanders.claimed_levels(user_id, chosen_id).get(chosen_id, set())
                    unlocked = _unlocked_options_for(claimed)
                    equipped = _sanitized_equipped(row["equipped"], unlocked)
                    profile = uow.social.get_profile(user_id) or {}
                    spec = get_commander(chosen_id)
                    return {
                        "commander_id": chosen_id,
                        "commander_level": int(row["level"]),
                        "cosmetics": {
                            **equipped,
                            "unlocked_voices": unlocked["voices"],
                            "unlocked_emojis": unlocked["emojis"],
                            "title": profile.get("title_id") or (spec.profile_cosmetics["title_20_name"] if 20 in claimed else ""),
                            "frame": profile.get("frame_id") or "none",
                        },
                    }

        fallback_id = req_spec.id if req_spec else DEFAULT_COMMANDER_ID
        unlocked = _unlocked_options_for(set())
        return {
            "commander_id": fallback_id,
            "commander_level": 1,
            "cosmetics": {
                **_sanitized_equipped(dict(DEFAULT_EQUIPPED), unlocked),
                "unlocked_voices": [],
                "unlocked_emojis": [],
                "title": "",
                "frame": "none",
            },
        }

    # -------------------------------------------------------- match settlement

    def settlement_hook(self, room: Room, uow: UnitOfWork, context: SettlementContext) -> None:
        """与普通对局结算在同一 SQLite UoW 内原子提交，按 (user_id, match_id) 严格去重。"""
        facts = context.facts
        if not context.match_id:
            return
        if room.daily_challenge:
            return
        now = int(context.timestamp)
        day = cst_day_key(now)

        if room.is_ai_room:
            mode = "ai"
        elif facts.mode == "custom" or not room.matchmade:
            mode = "custom"
        elif room.mystery_tech:
            mode = "mystery_tech"
        else:
            mode = facts.mode or "casual"

        ac_info = (context.pre or {}).get("anticheat")
        if not isinstance(ac_info, dict) and not room.is_ai_room and facts.count_stats:
            from .anticheat import AnticheatService
            ac_facts = AnticheatService.facts_from_room(room, facts.winner_id, facts.loser_id)
            ac_info = anticheat_rules.evaluate(ac_facts)

        ac_blocked = bool(context.blocked) or bool((ac_info or {}).get("blocked"))
        ac_rules = list((ac_info or {}).get("rules") or ())
        instant_surrender = "instant_surrender" in ac_rules
        if not instant_surrender and not room.is_ai_room:
            from .anticheat import AnticheatService
            ac_facts = AnticheatService.facts_from_room(room, facts.winner_id, facts.loser_id)
            instant_surrender = bool(anticheat_rules.rule_instant_surrender(ac_facts))
            if (
                not instant_surrender
                and getattr(room, "game_over_reason", None) == "surrender"
                and bool(ac_facts.get("battle_started"))
                and 0 <= int(getattr(room, "round", -1) or -1) <= 1
                and ac_facts.get("attacker_total_hits") is None
                and not any(e.get("type") == "attack" for e in (room.game_logs or []))
                and all(not (getattr(p, "attacks", None) or []) for p in room.players.values())
                and not bool((room.replay or {}).get("board_resets") or room.polar_reversal_applied)
            ):
                instant_surrender = True

        seats = (
            (facts.winner_id, facts.winner_user_id, True),
            (facts.loser_id, facts.loser_user_id, False),
        )
        for seat_id, uid, is_winner in seats:
            if not uid or seat_id.startswith("ai-"):
                continue
            player = room.players.get(seat_id)
            if player is None or not player.registered or player.user_id != uid:
                continue
            if not uow.users.get(uid):
                continue

            commander_id = getattr(player, "commander_id", None) or DEFAULT_COMMANDER_ID
            owned_row = uow.commanders.get_owned(uid, commander_id)
            if owned_row is None:
                continue

            # 同局防重：已写过直接跳过，重连/并发重复呼叫不重复累计。
            if uow.commanders.get_xp_event(uid, context.match_id) is not None:
                continue

            before_xp = clamp_xp(int(owned_row.xp or 0))
            before_level = level_for_xp(before_xp)
            ai_used = uow.commanders.ai_daily_xp_used(uid, day) if room.is_ai_room else 0

            decision = compute_match_commander_xp(
                mode=mode,
                is_ai_room=bool(room.is_ai_room),
                daily_challenge=bool(room.daily_challenge),
                rewards_eligible=bool(facts.rewards_eligible),
                is_winner=is_winner,
                game_over_reason=getattr(room, "game_over_reason", None),
                anticheat_blocked=ac_blocked,
                anticheat_rules=ac_rules,
                instant_surrender=instant_surrender,
                current_commander_xp=before_xp,
                ai_daily_used=ai_used,
            )

            after_xp = clamp_xp(before_xp + decision.granted_xp)
            after_level = level_for_xp(after_xp)
            recorded = uow.commanders.record_xp_event_once(
                user_id=uid,
                match_id=str(context.match_id),
                commander_id=commander_id,
                mode=mode,
                is_ai=bool(room.is_ai_room),
                day_cst=day,
                raw_xp=decision.raw_xp,
                granted_xp=decision.granted_xp,
                before_xp=before_xp,
                after_xp=after_xp,
                before_level=before_level,
                after_level=after_level,
                reason=decision.reason,
                now=now,
            )
            if not recorded:
                continue

            spec = get_commander(commander_id)
            claimed = uow.commanders.claimed_levels(uid, commander_id).get(commander_id, set())
            new_claimable = [
                lvl for lvl in range(before_level + 1, after_level + 1)
                if lvl not in claimed and lvl >= 2
            ]
            ai_used_after = ai_used + (decision.granted_xp if room.is_ai_room else 0)
            if player.socket_id:
                context.events.append({
                    "phase": "before",
                    "event": "commander_xp_settled",
                    "to": player.socket_id,
                    "data": {
                        "player_id": seat_id,
                        "commander_id": commander_id,
                        "commander_name": spec.name if spec else commander_id,
                        "mode": mode,
                        "is_ai": bool(room.is_ai_room),
                        "raw_xp": decision.raw_xp,
                        "delta": decision.granted_xp,
                        "reason": decision.reason,
                        "before_xp": before_xp,
                        "after_xp": after_xp,
                        "before_level": before_level,
                        "after_level": after_level,
                        "leveled_up": after_level > before_level,
                        "new_claimable_levels": new_claimable,
                        "ai_daily_xp_used": ai_used_after if room.is_ai_room else None,
                        "ai_daily_xp_cap": AI_DAILY_XP_CAP if room.is_ai_room else None,
                    },
                })
