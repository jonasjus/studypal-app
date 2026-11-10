from __future__ import annotations

import pytest

from studypal.core.logic.plant import MAX_LEAVES, MIN_LEAVES, Health, Plant, plant


@pytest.mark.parametrize(("done", "elapsed", "health"), [
    (0.60, 0.50, Health.BLOOMING),  # 10% ahead
    (0.53, 0.50, Health.HEALTHY),  # a little ahead isn't enough to flower
    (0.50, 0.50, Health.HEALTHY),
    (0.498, 0.50, Health.HEALTHY),  # a hair behind still counts as on pace
    (0.45, 0.50, Health.THIRSTY),
    (0.38, 0.50, Health.WILTING),
    (0.20, 0.50, Health.WITHERED),
])
def test_health_follows_the_pace(done: float, elapsed: float, health: Health) -> None:
    assert plant(done, elapsed, started=True).health is health


def test_a_seed_before_any_cram_period_starts() -> None:
    p = plant(0.0, 0.0, started=False)
    assert p.health is Health.SEED and p.pace == 0
    # Working ahead before cramming starts doesn't make it flower yet, but it does grow.
    assert plant(0.5, 0.0, started=False).health is Health.SEED


def test_it_grows_with_the_material_done() -> None:
    assert plant(0.0, 0.0, True).leaves == MIN_LEAVES
    assert plant(1.0, 1.0, True).leaves == MAX_LEAVES
    assert plant(0.2, 0.0, True).leaves < plant(0.8, 0.0, True).leaves


def test_every_health_has_words() -> None:
    assert all(Plant(h, MIN_LEAVES, 0.0).words for h in Health)
