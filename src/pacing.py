"""Bounded-random pacing between browser page loads / offer submissions.

Burst mitigation (chantier n°2): large runs must not hammer the WP admin with
back-to-back page loads — that is what gets an IP flagged. Pacing is never a
correctness mechanism: every deterministic wait that exists for settling
(dropdown render, blank-page retry) stays where it is.

The randomness is bounded and accounted for: a :class:`Pacer` exposes aggregate
counters via ``snapshot()`` so run logs record exactly how much pacing happened.
``rng`` and ``sleeper`` are injectable, so tests never sleep.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable


def parse_pace_spec(spec: str) -> tuple[float, float]:
    """Parse a CLI pace spec into ``(min_s, max_s)``.

    ``"0"`` → disabled, ``"3"`` → fixed 3 s, ``"2-5"`` → uniform in [2, 5] s.
    """

    text = str(spec).strip()
    parts = text.split("-")
    try:
        if len(parts) == 1:
            lo = hi = float(parts[0])
        elif len(parts) == 2:
            lo, hi = float(parts[0]), float(parts[1])
        else:
            raise ValueError
    except ValueError:
        raise ValueError(f"invalid pace spec {spec!r} — want 'N' or 'MIN-MAX' seconds") from None
    if lo < 0 or hi < 0:
        raise ValueError(f"invalid pace spec {spec!r} — bounds must be >= 0")
    if lo > hi:
        raise ValueError(f"invalid pace spec {spec!r} — min must be <= max")
    return lo, hi


class Pacer:
    """Sleep a bounded-random delay on each ``wait()``; keep aggregate counters."""

    def __init__(
        self,
        min_s: float,
        max_s: float,
        *,
        rng: random.Random | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_s < 0 or max_s < 0:
            raise ValueError("pace bounds must be >= 0")
        if min_s > max_s:
            raise ValueError("pace min must be <= max")
        self.min_s = float(min_s)
        self.max_s = float(max_s)
        self._rng = rng or random.Random()
        self._sleeper = sleeper
        self.waits = 0
        self.total_waited_s = 0.0

    @classmethod
    def from_spec(cls, spec: str, **kwargs: Any) -> "Pacer":
        return cls(*parse_pace_spec(spec), **kwargs)

    @property
    def enabled(self) -> bool:
        return self.max_s > 0

    def wait(self) -> float:
        """Sleep once within the bounds; return the delay (0.0 when disabled)."""

        if not self.enabled:
            return 0.0
        delay = self._rng.uniform(self.min_s, self.max_s)
        self._sleeper(delay)
        self.waits += 1
        self.total_waited_s += delay
        return delay

    def snapshot(self) -> dict[str, Any]:
        return {
            "min_s": self.min_s,
            "max_s": self.max_s,
            "waits": self.waits,
            "total_waited_s": round(self.total_waited_s, 3),
        }
