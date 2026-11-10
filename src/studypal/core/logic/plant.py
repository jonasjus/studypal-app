"""The study plant on the overview: how well it's doing shows how you stand against your schedule.

Its health follows your pace, meaning the share of topics done minus the share of cram time used,
across every active subject. Ahead of schedule it flowers. On pace it's green and healthy. The
further behind you fall, the more it droops, until it withers. Its size follows how much of the
material is done, so it grows over the term as you tick topics off.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Health(StrEnum):
    SEED = "seed"  # nothing to judge yet: no cram period has started
    BLOOMING = "blooming"  # ahead of schedule
    HEALTHY = "healthy"  # on pace
    THIRSTY = "thirsty"  # a little behind
    WILTING = "wilting"  # well behind
    WITHERED = "withered"  # far behind


# How far behind (share of the material) each step starts. Being just a hair behind counts as on pace.
THIRSTY_FROM = 0.005
WILTING_FROM = 0.10
WITHERED_FROM = 0.25
BLOOMING_FROM = 0.05  # how far ahead it takes to flower

# Leaves on the stem, from a sprout to fully grown.
MIN_LEAVES = 1
MAX_LEAVES = 6

WORDS = {
    Health.SEED: "Planted. It starts growing when your first cram period begins.",
    Health.BLOOMING: "In bloom. You're ahead of schedule.",
    Health.HEALTHY: "Healthy. You're right on schedule.",
    Health.THIRSTY: "A bit thirsty. You're slightly behind. Finish a topic to water it.",
    Health.WILTING: "Wilting. You're falling behind. A few topics will perk it up.",
    Health.WITHERED: "Withered. You're far behind, but it's not too late. Every topic you finish brings it back.",
}


@dataclass(frozen=True)
class Plant:
    health: Health
    leaves: int  # how big it has grown
    pace: float  # done minus elapsed: positive when ahead, negative when behind

    @property
    def words(self) -> str:
        return WORDS[self.health]


def health_for(pace: float, started: bool) -> Health:
    if not started:
        return Health.SEED
    behind = -pace
    if behind >= WITHERED_FROM:
        return Health.WITHERED
    if behind >= WILTING_FROM:
        return Health.WILTING
    if behind > THIRSTY_FROM:
        return Health.THIRSTY
    if pace > BLOOMING_FROM:
        return Health.BLOOMING
    return Health.HEALTHY


def plant(done: float, elapsed: float, started: bool) -> Plant:
    """The plant for the share of topics done (0–1) and the share of cram time used (0–1)."""
    done = min(1.0, max(0.0, done))
    pace = done - elapsed if started else 0.0
    leaves = MIN_LEAVES + round(done * (MAX_LEAVES - MIN_LEAVES))
    return Plant(health=health_for(pace, started), leaves=leaves, pace=pace)
