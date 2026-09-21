# -*- coding: utf-8 -*-
"""无头对局驱动器（`tools/headless_game.py`）的回归用例。

这些用例钉的是驱动器本身的契约 —— 它不是产品逻辑，而是**度量工具**：
胜率、卡死率、动作序列能不能复现，全都取决于它。工具假绿比产品假红更危险
（CLAUDE.md 第 10.15 条「工具假红先怀疑工具」，反过来同样成立），
所以这里既测"跑得通"，也测"不许假装跑通了"。

⚠️ 本文件直调 `server.py` 的 handler，所以必须先把 `BATTLESHIP_DB_PATH`
指到临时目录（`tests/conftest.py` 已经做了，这里再兜一次，防止有人单独跑本文件）。
"""
import os
import pathlib
import tempfile

_TMP_DB_DIR = pathlib.Path(tempfile.mkdtemp(prefix='battleship-headless-'))
os.environ.setdefault('BATTLESHIP_DB_PATH', str(_TMP_DB_DIR / 'battleship.db'))

import pytest  # noqa: E402

import server  # noqa: E402
from tools import headless_game as hg  # noqa: E402


def _hard():
    return hg.ExistingAIPolicy('hard')


def _random():
    return hg.RandomPolicy()


def _rooms_snapshot():
    return dict(server.room_manager.get_all_rooms())


# ---------------------------------------------------------------------------
# 1. 一局能正常打完
# ---------------------------------------------------------------------------
def test_full_game_completes_with_winner():
    result = hg.play_game(_hard, _hard, seed=1, max_rounds=60)

    assert not result.stalled, f'不该卡死：{result.stall_reason}'
    assert result.winner in (result.p1, result.p2), f'winner 异常：{result.winner}'
    assert result.rounds >= 1
    assert len(result.actions) < 4000, '动作数应远低于上限'
    # 必须有实际打过的炮 —— 只有"摆船+猜拳"就判胜负说明驱动器漏了回合推进
    assert any(kind == 'attack' for kind, _, _ in result.actions)
    assert any(kind == 'end_turn' for kind, _, _ in result.actions)


def test_default_cap_is_not_hit_for_normal_games():
    """跑一批正常对局：一局都不该撞上限（否则上限设得太松/太紧都失去意义）。"""
    results = hg.run_many(_hard, _hard, games=12, seed=500, max_rounds=60)
    assert not any(r.stalled for r in results), [
        (r.seed, r.stall_reason) for r in results if r.stalled]


# ---------------------------------------------------------------------------
# 2. 可复现：同种子 → 同一个 winner / rounds / 动作序列
# ---------------------------------------------------------------------------
def _seat_normalize(result):
    """把结果里的座位 id 换成 'p1'/'p2'（含 winner）。

    房间 id 是 uuid4、AI 座位 id 是 `'ai-'+room_id` → 两次跑必然不同，
    直接比 `winner` 字符串永远失败。这不是"不确定"，只是 id 空间不同。
    """
    mapping = {result.p1: 'p1', result.p2: 'p2'}
    return {
        'winner': mapping.get(result.winner, result.winner),
        'rounds': result.rounds,
        'hash': result.action_hash(),
        'actions': [(k, mapping.get(p, p), d) for k, p, d in result.actions],
    }


def test_same_seed_is_deterministic():
    first = _seat_normalize(hg.play_game(_hard, _hard, seed=4242, max_rounds=60))
    second = _seat_normalize(hg.play_game(_hard, _hard, seed=4242, max_rounds=60))

    assert first['winner'] == second['winner']
    assert first['rounds'] == second['rounds']
    assert first['hash'] == second['hash']
    assert first['actions'] == second['actions']


def test_determinism_holds_across_a_batch():
    a = hg.run_many(_hard, _hard, games=6, seed=77, max_rounds=60)
    b = hg.run_many(_hard, _hard, games=6, seed=77, max_rounds=60)
    assert [r.action_hash() for r in a] == [r.action_hash() for r in b]


def test_interleaved_runs_do_not_leak_rng():
    """跑一局别的、再跑同种子那局，结果必须一模一样（全局 random 状态要还原）。"""
    baseline = hg.play_game(_hard, _hard, seed=99, max_rounds=60)
    hg.play_game(_random, _random, seed=12345, max_rounds=60)
    again = hg.play_game(_hard, _hard, seed=99, max_rounds=60)
    assert again.action_hash() == baseline.action_hash()


# ---------------------------------------------------------------------------
# 3. 种子确实起作用
# ---------------------------------------------------------------------------
def test_different_seeds_produce_different_games():
    hashes = {hg.play_game(_hard, _hard, seed=s, max_rounds=60).action_hash()
              for s in range(30)}
    # 30 个种子全撞成同一个序列 = 种子没接进随机源
    assert len(hashes) > 5, f'不同种子只产生 {len(hashes)} 种局面，种子疑似没生效'


# ---------------------------------------------------------------------------
# 4. ExistingAIPolicy 真的比随机强（松边界，别写成 flaky）
# ---------------------------------------------------------------------------
def test_hard_policy_beats_random_policy():
    results = hg.run_many(_hard, _random, games=60, seed=9000,
                          max_rounds=40, max_actions=1500)
    stats = hg.summarize(results)
    rate = stats['p1_win_rate']
    # 松边界：只要求"明显强于五五开"，不要求某个具体数值 ——
    # 收紧到 0.8 会把这条用例变成统计彩票（而且那 80% 是 mastervs hard 的指标，
    # 不是 hard vs random 的）。
    assert rate > 0.45, f'hard 胜率只有 {rate:.2%}（{stats}）'
    assert stats['p1_wins'] > stats['p2_wins']


def test_summarize_counts_wins_and_draws():
    results = hg.run_many(_hard, _hard, games=8, seed=31337, max_rounds=60)
    stats = hg.summarize(results)
    assert stats['games'] == 8
    assert stats['p1_wins'] + stats['p2_wins'] + stats['draws'] == 8
    assert stats['elapsed'] > 0


def test_wilson_interval_is_sane():
    low, high = hg.wilson_interval(80, 100)
    assert 0.70 < low < 0.80 < high < 0.90
    # 极端比例：正态近似会给 [1.0, 1.0]，Wilson 不会
    all_low, all_high = hg.wilson_interval(50, 50)
    assert all_high == 1.0 and all_low < 1.0
    assert hg.wilson_interval(0, 0) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# 5. 硬上限：撞上限要记 stalled，既不挂也不抛
# ---------------------------------------------------------------------------
def test_action_cap_reports_stalled_instead_of_hanging():
    result = hg.play_game(_hard, _hard, seed=1, max_actions=12, max_rounds=60)

    assert result.stalled, '动作数被截断时必须记 stalled'
    assert result.stall_reason, 'stalled 必须带原因'
    assert len(result.actions) <= 12 + 4, f'超出上限太多：{len(result.actions)}'
    assert result.final_state, 'stalled 报告必须带房间可观察状态'
    # 可观察状态里要有能定位问题的字段（这正是"卡在哪"的证据）
    for key in ('state', 'phase', 'round', 'current_attacker', 'ships'):
        assert key in result.final_state


def test_round_cap_reports_stalled():
    result = hg.play_game(_hard, _hard, seed=1, max_rounds=1, max_actions=4000)
    assert result.stalled
    assert '回合数' in result.stall_reason


def test_stuck_detector_fires_on_a_frozen_room():
    """策略永远不交回合 → 房间状态不再变化 → 必须在 max_stuck 内判卡死。"""

    class FrozenPolicy(hg.Policy):
        def place_ships(self, room, pid):
            return hg.RandomPolicy().place_ships(room, pid)

        def rps_choice(self, room, pid):
            return 'rock'

        def choose_attack(self, room, pid):
            return None

    result = hg.play_game(FrozenPolicy, FrozenPolicy, seed=3,
                          max_rounds=200, max_actions=5000, max_stuck=25)
    assert result.stalled
    assert '无任何变化' in result.stall_reason


def test_policy_bug_is_recorded_not_raised():
    """策略返回垃圾（非法下标 / 越界坐标）不该把驱动器炸掉。"""

    class BrokenPolicy(hg.Policy):
        def place_ships(self, room, pid):
            return [{'positions': [{'x': 0, 'y': 0}], 'hits': []}]   # 只有 1 艘

        def choose_attack(self, room, pid):
            return (99, 99)

        def choose_card(self, room, pid):
            return 999

    result = hg.play_game(BrokenPolicy, BrokenPolicy, seed=5, max_actions=200)
    assert result.stalled                       # 摆船就不合法 → 应当判卡死
    assert result.violations                    # 而且必须留下"为什么"的痕迹


# ---------------------------------------------------------------------------
# 6. 驱动器不许留下房间
# ---------------------------------------------------------------------------
def test_no_room_left_behind_after_a_game():
    before = set(_rooms_snapshot())
    hg.play_game(_hard, _hard, seed=8, max_rounds=60)
    assert set(_rooms_snapshot()) == before, '对局结束后房间必须被删掉'


def test_no_room_left_behind_when_stalled():
    before = set(_rooms_snapshot())
    result = hg.play_game(_hard, _hard, seed=9, max_actions=5)
    assert result.stalled
    assert set(_rooms_snapshot()) == before


def test_room_is_removed_even_if_run_raises():
    before = set(_rooms_snapshot())

    class Boom(hg.Policy):
        def place_ships(self, room, pid):
            raise RuntimeError('boom')

    result = hg.play_game(Boom, Boom, seed=11)
    assert result.violations
    assert set(_rooms_snapshot()) == before


def test_batch_leaves_no_rooms():
    before = set(_rooms_snapshot())
    hg.run_many(_hard, _hard, games=10, seed=222, max_rounds=60)
    assert set(_rooms_snapshot()) == before


# ---------------------------------------------------------------------------
# 7. 无头前提本身（这些一旦不成立，整套度量就失真）
# ---------------------------------------------------------------------------
def test_handler_calls_run_without_request_context():
    """`_identity_ok` 的"无请求上下文则跳过连接校验"是驱动器的前提，必须实测。"""
    assert server._has_request_context() is False

    room_id = server.room_manager.create_ai_room('probe', '甲', None, 'hard')
    try:
        room = server.room_manager.get_room(room_id)
        ai_id = server._ai_player_id(room)
        assert server._identity_ok(room, ai_id) is True
        # 不在房间里的 id 仍然要被拒（"跳过校验"不是"谁都能操作"）
        assert server._identity_ok(room, 'nobody') is False
    finally:
        server.room_manager.delete_room(room_id)


def test_ai_loop_is_neutralised_during_a_game():
    """驱动器运行期间 `_maybe_run_ai_turn` 必须被换掉，否则会和它抢方向盘。"""
    assert server._maybe_run_ai_turn.__name__ == '_maybe_run_ai_turn'
    with hg.HeadlessGame(_hard, _hard, seed=1, max_rounds=1) as game:
        assert server._maybe_run_ai_turn.__name__ == 'no_op'
        game.run()
    # 退出后必须还原 —— 否则会污染同进程里别的测试
    assert server._maybe_run_ai_turn.__name__ == '_maybe_run_ai_turn'


def test_patches_are_restored_even_when_run_raises():
    original_emit = server.emit

    class Boom(hg.Policy):
        def place_ships(self, room, pid):
            raise RuntimeError('boom')

    hg.play_game(Boom, Boom, seed=12)
    assert server.emit is original_emit
    assert server.db.record_card_use.__name__ == 'record_card_use'


def test_existing_ai_policy_uses_the_real_decision_functions():
    """hard 适配器必须走 server 里那份实现，不能是自己复刻的一套。"""
    room_id = server.room_manager.create_ai_room('probe2', '乙', None, 'hard')
    try:
        room = server.room_manager.get_room(room_id)
        ai_id = server._ai_player_id(room)

        policy = hg.ExistingAIPolicy('hard')
        # 出牌决策 == server._ai_choose_magic_card（含 _AI_SAFE_CARDS 白名单）
        room.players[ai_id].magic_hand = [server.MagicCard('余音绕梁'),
                                          server.MagicCard('败者食尘')]
        room.state = 'attacking'
        room.current_attacker = ai_id
        room.current_phase = 'preparation'
        room.attack_order = [ai_id, 'probe2']
        room.players[ai_id].remaining_ships = 6
        server._recalc_attacker_attacks(room)
        assert policy.choose_card(room, ai_id) == server._ai_choose_magic_card(room, ai_id)
        # 败者食尘不在安全白名单里 → 挑中的必须是余音绕梁
        assert policy.choose_card(room, ai_id) == 0

        # 摆船读回来必须与 server._ai_place_ships 摆的一致
        ships = policy.place_ships(room, ai_id)
        assert len(ships) == len(room.players[ai_id].ships) == 6
        cells = {(c['x'], c['y']) for s in ships for c in s['positions']}
        assert len(cells) == 6, '摆船不许重叠'
    finally:
        server.room_manager.delete_room(room_id)


def test_unknown_policy_name_lists_alternatives():
    with pytest.raises(ValueError) as exc:
        hg.make_policy('nope')
    assert 'hard' in str(exc.value) and 'nope' in str(exc.value)


def test_master_policy_is_registered_not_silently_falling_back():
    """大师必须**真的登记**，不许静默回落到别的策略（那会给出一个假的胜率）。

    这条的前身是「master 还没实现 —— 必须明确报错」。大师落地后契约反转：
    从「必须报错」变成「必须能造出来，且难度真的传下去了」。
    两版守的是同一件事：**别让度量悄悄测了别的东西**。
    """
    assert 'master' in hg.POLICY_FACTORIES
    assert hg.POLICY_FACTORIES['master'] is not None, '会静默回落到别的策略'
    p = hg.make_policy('master')
    assert getattr(p, 'difficulty', None) == 'master'
    assert 'master' in server.AI_DIFFICULTIES


def test_random_policy_only_plays_legal_cards():
    """随机策略必须筛掉"当前打不出去"的卡，否则一局被拒几千次、fuzz 没内容。"""
    results = hg.run_many(_random, _random, games=6, seed=606,
                          max_rounds=40, max_actions=1200)
    rejected = [v for r in results for v in r.violations if '出牌被拒' in v]
    total = sum(len(r.actions) for r in results)
    assert len(rejected) <= total * 0.05, f'出牌被拒占比过高：{len(rejected)}/{total}'


def test_cli_runs_and_reports(monkeypatch, capsys):
    assert hg.main(['--games', '4', '--p1', 'hard', '--p2', 'hard', '--seed', '7']) == 0
    out = capsys.readouterr().out
    assert '卡死局数' in out and 'p1 胜率' in out and '局/秒' in out


def test_cli_rejects_unknown_policy(capsys):
    """未知策略名要在开跑前就报错并退出码 2，而不是跑一半才炸。

    ⚠️ 这里原本拿 `master` 当「未实现」的例子 —— 大师落地后它就合法了，
       所以换成一个真正不存在的名字。测试要跟着现实走，不能反过来。
    """
    with pytest.raises(SystemExit) as exc:
        hg.main(['--games', '1', '--p1', 'no_such_policy'])
    assert exc.value.code == 2


def test_master_policy_is_available():
    """大师已经是可选策略（`POLICY_FACTORIES` 里不再是 None）。

    原先这条断言的是「声明了但未实现」，用来防止**静默回落**到别的策略
    从而报出一个假的胜率。现在大师真的实现了，契约反过来：
    它必须**能造出来**，而且难度真的写进了 `room.ai_difficulty`
    （否则量出来的还是别的档位）。
    """
    p = hg.make_policy('master')
    assert p is not None, 'master 未登记 —— 会静默回落到别的策略'
    assert getattr(p, 'difficulty', None) == 'master'
    assert 'master' in server.AI_DIFFICULTIES


def test_master_vs_hard_runs_without_stalling():
    """★ 大师对困难跑一小批，**一局都不许卡死**。

    卡死是这个功能最贵的失败模式（AI 回合永远交不出去、真人干等）。
    1000 局级的度量在 CI 里太慢，这里取一个能跑得快、又足够撞出
    「打出去的卡留下待办」这类问题的局数。
    """
    results = hg.run_many(lambda: hg.make_policy('master'),
                          lambda: hg.make_policy('hard'), games=60, seed=11)
    stalled = [r for r in results if r.stalled]
    assert not stalled, '大师有 %d 局卡死，例如 seed=%s 原因=%s' % (
        len(stalled), stalled[0].seed if stalled else None,
        stalled[0].stall_reason if stalled else None)
