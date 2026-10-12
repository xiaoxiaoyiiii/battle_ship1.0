import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.chain_service import build_chain_state
from domain.cards import TargetError, normalize_target
from domain.chain import ChainItemState, ChainRuleError, ChainState


def item(name, ident="1"):
    return ChainItemState(ident, "p1", name, {"x": 1, "y": 2}, 1.0)


def test_normalize_area_and_line():
    assert normalize_target({"target_area": {"x1": 4, "y1": 3, "x2": 1, "y2": 0}})["target_area"] == {
        "x1": 1, "y1": 0, "x2": 4, "y2": 3}
    assert normalize_target({"target_line": {"type": "row", "index": 5}}) == {
        "target_line": {"type": "row", "index": 5}}


def test_normalize_cells_rejects_duplicates_and_out_of_bounds():
    with pytest.raises(TargetError):
        normalize_target({"target_cells": [{"x": 1, "y": 1}, {"x": 1, "y": 1}]})
    with pytest.raises(TargetError):
        normalize_target({"x": 6, "y": 1})


def test_normalize_target_does_not_pass_unknown_keys():
    with pytest.raises(TargetError):
        normalize_target({"target_line": {"type": "row", "index": 1, "evil": True}})


def test_chain_is_lifo_and_requires_closed_window():
    state = ChainState().push(item("A"), "p2")
    state = state.respond("p2", "p1").respond("p1", "p2")
    state, done = state.pass_response("p2", "p1")
    assert not done
    state, done = state.pass_response("p1", "p2")
    assert done
    state, top = state.pop_next()
    assert top.card_name == "A"
    assert state.items == ()


def test_chain_negation_is_explicit():
    state = ChainState().push(item("A"))
    state = state.negate_top("失灵！")
    assert state.items[-1].negated is True
    assert state.items[-1].negated_by == "失灵！"


def test_wrong_responder_is_rejected():
    state = ChainState().push(item("A"), "p2")
    with pytest.raises(ChainRuleError):
        state.pass_response("p1", "p2")


def test_legacy_room_adapter_is_read_only():
    class Room:
        chain = [item("A")]
        chain_window = "p2"
        chain_passes = 1
        chain_waiting = True

    state = build_chain_state(Room())
    assert state.items[0].card_name == "A"
    assert state.waiting_for == "p2"
    assert state.passes == 1
    assert state.window_open is True


def test_domain_chain_does_not_import_framework_modules():
    source = (ROOT / "domain" / "chain.py").read_text(encoding="utf-8")
    assert "flask" not in source.lower()
    assert "socketio" not in source.lower()
