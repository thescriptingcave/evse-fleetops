from __future__ import annotations

import random

MAX = float("inf")


def walk(value: float, target: float, rate: float, noise: float, rng: random.Random, lo: float, hi: float) -> float:
    """Random-walk `value` toward `target` with bounded noise, clamped to [lo, hi]."""
    value += (target - value) * rate + rng.uniform(-noise, noise)
    if value < lo:
        value = lo
    if value > hi:
        value = hi
    return value


def temperature(target: float, value: float, rng: random.Random) -> float:
    return walk(value, target, 0.12, 0.35, rng, 5.0, 85.0)


def humidity(value: float, rng: random.Random) -> float:
    return walk(value, 52.0 + rng.gauss(0, 4), 0.05, 1.2, rng, 15.0, 98.0)


def vibration(value: float, rng: random.Random) -> float:
    return walk(value, 0.5, 0.3, 0.5, rng, 0.0, 20.0)