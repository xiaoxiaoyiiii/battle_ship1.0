"""AI 后台任务的时间与随机源端口。"""
from __future__ import annotations

import random
import time


class AiRuntime:
    def __init__(self, rng=None, sleep=None):
        self.rng = rng if rng is not None else random
        self._sleep = sleep

    def pause(self, seconds: float) -> None:
        (self._sleep or time.sleep)(seconds)


default_runtime = AiRuntime()


def seeded_runtime(seed: int, sleep=None) -> AiRuntime:
    """用显式种子创建单局独立序列；同一输入可重放。"""
    return AiRuntime(rng=random.Random(seed), sleep=sleep)
