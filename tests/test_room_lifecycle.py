import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.room_service import build_disconnect_lease, build_match_queue, build_room_lifecycle
from domain.rooms import DisconnectLease, MatchEntry, MatchQueue, RoomLifecycle, RoomRuleError


def test_match_queue_pairs_same_mode_and_does_not_pair_same_user():
    queue = MatchQueue().enqueue(MatchEntry("a", "A", "u", "ranked"))
    queue = queue.enqueue(MatchEntry("b", "B", "u", "ranked"))
    queue = queue.enqueue(MatchEntry("c", "C", "v", "casual"))
    queue = queue.enqueue(MatchEntry("d", "D", "w", "ranked"))
    queue, pair = queue.pick_pair()
    assert pair == (MatchEntry("a", "A", "u", "ranked"), MatchEntry("d", "D", "w", "ranked"))
    assert [entry.sid for entry in queue.entries] == ["b", "c"]


def test_match_queue_rejects_duplicate_sid_and_invalid_mode():
    queue = MatchQueue().enqueue(MatchEntry("a", "A"))
    with pytest.raises(RoomRuleError):
        queue.enqueue(MatchEntry("a", "A2"))
    with pytest.raises(RoomRuleError):
        queue.enqueue(MatchEntry("b", "B", mode="broken"))


def test_disconnect_lease_expiry_is_deterministic():
    lease = DisconnectLease("p1", 7, 30.0)
    assert lease.is_expired(29.9) is False
    assert lease.is_expired(30.0) is True


def test_disconnect_expiry_decision_matches_legacy_policy():
    assert RoomLifecycle("placing_ships", players=("p1", "p2")).disconnect_expiry_action("p1") == "cancel"
    assert RoomLifecycle("attacking", players=("p1", "p2")).disconnect_expiry_action("p1") == "forfeit"
    assert RoomLifecycle("attacking", is_ai_room=True, players=("p1", "ai")).disconnect_expiry_action("p1") == "cancel"
    assert RoomLifecycle("game_over", players=("p1", "p2")).disconnect_expiry_action("p1") == "ignore"
    assert RoomLifecycle("attacking", players=("p1", "p2"), disconnected=("p2",)).disconnect_expiry_action("p1") == "cancel"


def test_legacy_adapters_are_read_only():
    class Manager:
        match_queue = [{"sid": "a", "name": "A", "user_id": None, "mode": "casual"}]

    class Room:
        state = "attacking"
        players = {"p1": object(), "p2": object()}
        disconnected = {"p2": {"token": 3, "deadline": 10.0}}

    assert build_match_queue(Manager()).entries[0].sid == "a"
    lifecycle = build_room_lifecycle(Room())
    assert lifecycle.players == ("p1", "p2")
    lease = build_disconnect_lease(Room(), "p2")
    assert lease == DisconnectLease("p2", 3, 10.0)


def test_room_domain_does_not_import_framework_modules():
    source = (ROOT / "domain" / "rooms.py").read_text(encoding="utf-8").lower()
    assert "flask" not in source
    assert "socketio" not in source
