"""卡面皮肤抽卡 v1：大样本概率统计（固定种子、注入 rng、不经 HTTP、不碰数据库）。

被测对象是 `battleship.domain.gacha` 的纯函数：`roll_kind` / `roll_skin` /
`draw_one` / `draw_many`。生产掷骰用 `secrets.SystemRandom`，这里一律换成
`random.Random(固定种子)` 或脚本化 rng，结果可重复。

失败阈值（全部写在断言里，失败信息会带上观测值）：

1. `roll_kind` 100_000 次：限定 1% / 传说 9% / 碎片 90%。
   - 卡方检验 df=2，α=0.01，临界 9.210（超过即判定比例不符）；
   - 同时要求三点比例各自落在期望值 ±0.3 个百分点内（100_000 样本下
     碎片的 99% 置信半径约 0.24pp，±0.3pp 只放行正常抖动）。
2. 档内均匀：`roll_skin` 各 100_000 次。
   - 限定 3 款：df=2，α=0.01，临界 9.210；
   - 传说 9 款：df=8，α=0.01，临界 20.090；
   - 单款比例同时要求 ±0.6 个百分点内。
3. 集齐 12 张后仍可抽：抽到的皮肤一律 `is_new=false`、`shards_gained=5`；
   纯碎片仍是 `shards_gained=1`。
4. 十连内先新后重：同一十连里第一次抽到某皮肤 `is_new=true`，
   之后再抽到同一张按重复返 5 碎片。

阈值是 1% 显著性水平；种子固定，所以失败即代表实现与公示概率不符，
而不是运气问题。
"""
from __future__ import annotations

import random

import pytest

from battleship.domain.gacha import draw_many, draw_one, roll_kind, roll_skin
from battleship.domain.skins import (
    DUPLICATE_SHARDS,
    EXCHANGE_COST,
    RATES,
    SHARD_PER_DRAW,
    SKINS,
    SKINS_BY_ID,
    SKINS_BY_TIER,
)

SEED = 20261115
SAMPLE = 100_000
# 卡方临界值（α=0.01）：df=2 → 9.210；df=8 → 20.090。
CHI2_DF2_0_01 = 9.210
CHI2_DF8_0_01 = 20.090
LIMITED = SKINS_BY_TIER["limited"]
LEGENDARY = SKINS_BY_TIER["legendary"]


class ScriptedRng:
    """按脚本吐值的 rng，用来钉边界与"先新后重"这类确定性行为。"""

    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randrange(self, stop: int) -> int:
        if not self.values:
            raise AssertionError(f"rng 已耗尽，还需要 <{stop}")
        value = self.values.pop(0)
        assert 0 <= value < stop, (value, stop)
        return value


def chi_square(counts: list[int], probs: list[float], total: int) -> float:
    expected = [total * p for p in probs]
    return sum((c - e) ** 2 / e for c, e in zip(counts, expected))


def proportions(counts: list[int], total: int) -> list[float]:
    return [c / total for c in counts]


def test_rates_and_shard_constants_match_the_contract() -> None:
    """公示常量就是统计测试的期望值，先钉死它，避免"改了概率测的还是旧值"。"""
    assert RATES == {"limited": 0.01, "legendary": 0.09, "shard": 0.90}
    assert DUPLICATE_SHARDS == 5
    assert SHARD_PER_DRAW == 1
    assert EXCHANGE_COST == {"legendary": 20, "limited": 60}
    assert len(LIMITED) == 3
    assert len(LEGENDARY) == 9
    assert len(SKINS) == 12


def test_roll_kind_boundaries() -> None:
    """0=限定；1..9=传说；10..99=碎片。边界错一位就是 2%/8% 的实伤。"""
    assert roll_kind(ScriptedRng([0])) == "limited"
    assert roll_kind(ScriptedRng([1])) == "legendary"
    assert roll_kind(ScriptedRng([9])) == "legendary"
    assert roll_kind(ScriptedRng([10])) == "shard"
    assert roll_kind(ScriptedRng([99])) == "shard"


def test_roll_kind_rates_within_1_percent_significance() -> None:
    rng = random.Random(SEED)
    tally = {"limited": 0, "legendary": 0, "shard": 0}
    for _ in range(SAMPLE):
        tally[roll_kind(rng)] += 1

    counts = [tally["limited"], tally["legendary"], tally["shard"]]
    expected = [RATES["limited"], RATES["legendary"], RATES["shard"]]
    assert sum(counts) == SAMPLE

    observed = proportions(counts, SAMPLE)
    statistic = chi_square(counts, expected, SAMPLE)
    assert statistic < CHI2_DF2_0_01, (
        f"卡方 {statistic:.3f} ≥ {CHI2_DF2_0_01}（df=2, α=0.01）；"
        f"观测限定/传说/碎片 = {counts}（期望 {[SAMPLE * p for p in expected]}）"
    )
    for name, got, want in zip(("limited", "legendary", "shard"), observed, expected):
        assert abs(got - want) <= 0.003, (
            f"{name} 观测 {got:.4%} 偏离期望 {want:.2%} 超过 0.3 个百分点"
        )


@pytest.mark.parametrize(
    ("kind", "pool", "critical"),
    [
        ("limited", LIMITED, CHI2_DF2_0_01),
        ("legendary", LEGENDARY, CHI2_DF8_0_01),
    ],
)
def test_roll_skin_uniform_within_tier(kind: str, pool, critical: float) -> None:
    rng = random.Random(SEED + len(pool))
    tally = {skin.skin_id: 0 for skin in pool}
    for _ in range(SAMPLE):
        tally[roll_skin(rng, kind).skin_id] += 1

    counts = [tally[skin.skin_id] for skin in pool]
    assert sum(counts) == SAMPLE
    assert set(tally) == {skin.skin_id for skin in SKINS if skin.tier == kind}

    expected_each = 1 / len(pool)
    statistic = chi_square(counts, [expected_each] * len(pool), SAMPLE)
    assert statistic < critical, (
        f"{kind} 档内卡方 {statistic:.3f} ≥ {critical}（df={len(pool) - 1}, α=0.01）；"
        f"观测 {counts}，期望每款 {SAMPLE / len(pool):.1f}"
    )
    for skin, count in zip(pool, counts):
        assert abs(count / SAMPLE - expected_each) <= 0.006, (
            f"{skin.skin_id} 观测 {count / SAMPLE:.4%} 偏离 1/{len(pool)} 超过 0.6 个百分点"
        )


def test_roll_skin_never_leaves_the_tier() -> None:
    rng = random.Random(SEED + 7)
    for _ in range(2_000):
        limited = roll_skin(rng, "limited")
        legendary = roll_skin(rng, "legendary")
        assert limited.tier == "limited" and limited in LIMITED
        assert legendary.tier == "legendary" and legendary in LEGENDARY


def test_draw_many_after_full_collection_always_pays_duplicates() -> None:
    """集齐 12 张后仍可抽：皮肤一律 is_new=false + 5 碎片，纯碎片仍是 1。"""
    owned = set(SKINS_BY_ID)
    rng = random.Random(SEED + 12)
    skins_seen = 0
    shards_seen = 0
    for _ in range(50):
        for row in draw_many(rng, 10, set(owned)):
            if row["kind"] == "shard":
                shards_seen += 1
                assert row["skin_id"] is None
                assert row["is_new"] is False
                assert row["shards_gained"] == SHARD_PER_DRAW
            else:
                skins_seen += 1
                assert row["skin_id"] in owned
                assert row["is_new"] is False, "集齐后不应再出现 is_new=true"
                assert row["shards_gained"] == DUPLICATE_SHARDS
    # 500 抽里一次皮肤都没有的概率 < 1e-22，出现即说明 roll_kind 坏了。
    assert skins_seen > 0 and shards_seen > 0


def test_ten_pull_first_drop_is_new_later_drop_is_duplicate() -> None:
    """可控序列：同一张传说先抽到（新），同一十连里再抽到（重复 +5）。"""
    target = LEGENDARY[0]
    # 传说档：kind 掷出 1..9；档内索引 0 → 该档第一款。
    rng = ScriptedRng([1, 0, 1, 0])
    results = draw_many(rng, 2, set())
    assert [row["kind"] for row in results] == ["legendary", "legendary"]
    assert results[0]["skin_id"] == target.skin_id
    assert results[0]["is_new"] is True
    assert results[0]["shards_gained"] == 0
    assert results[1]["skin_id"] == target.skin_id
    assert results[1]["is_new"] is False
    assert results[1]["shards_gained"] == DUPLICATE_SHARDS


def test_ten_pull_property_first_seen_new_then_five_shards() -> None:
    """随机十连的不变式：十连内部按 index 依次判定，先见到的是新，重复的返 5。"""
    rng = random.Random(SEED + 99)
    new_rows = 0
    duplicate_rows = 0
    for _ in range(300):
        owned: set[str] = set()
        seen: set[str] = set()
        for row in draw_many(rng, 10, owned):
            if row["kind"] == "shard":
                assert row["shards_gained"] == SHARD_PER_DRAW
                assert row["is_new"] is False
                continue
            skin_id = row["skin_id"]
            assert skin_id is not None
            if skin_id in seen:
                duplicate_rows += 1
                assert row["is_new"] is False
                assert row["shards_gained"] == DUPLICATE_SHARDS
            else:
                new_rows += 1
                assert row["is_new"] is True
                assert row["shards_gained"] == 0
                seen.add(skin_id)
        # draw_many 用的是集合副本：调用方传入的集合不被修改。
        assert owned == set()
    assert new_rows > 0 and duplicate_rows > 0


def test_draw_one_shard_row_shape() -> None:
    row = draw_one(ScriptedRng([99]), set())
    assert row["kind"] == "shard"
    assert row["index"] == 0
    assert row["skin_id"] is None and row["card_key"] is None and row["card_name"] is None
    assert row["is_new"] is False
    assert row["shards_gained"] == SHARD_PER_DRAW


def test_same_seed_repeats_the_same_sequence() -> None:
    """固定种子可重复：同一序列必须逐行相同，否则统计结论不可复核。"""
    def run() -> list[dict]:
        rng = random.Random(SEED)
        return draw_many(rng, 20, set())

    assert run() == run()
