# MockSensor.py
from __future__ import annotations

import csv
import math
import random
import time
from pathlib import Path
from typing import Optional, Tuple, List, Callable, Union


class MockSensor:
    """
    Drop-in replacement for Sensor() when Arduino/RPi hardware is unavailable.

    Matches interface:
      - read() -> Tuple[Optional[float], ...] length 5
      - close()

    Scenarios (via scenario_getter):
      - normal
      - poor_efficiency
      - no_flow
      - sensor_stuck
      - noisy
    """

    def __init__(
        self,
        csv_path: Optional[Union[str, Callable[[], str]]] = None,
        loop: bool = True,
        scenario_getter: Optional[Callable[[], str]] = None,
    ):
        self._loop = loop
        self._rows: List[Tuple[Optional[float], ...]] = []
        self._i = 0
        self._t0 = time.time()

        # Support calling style: MockSensor(lambda: DEMO_SCENARIO["name"])
        if callable(csv_path) and scenario_getter is None:
            scenario_getter = csv_path  # type: ignore[assignment]
            csv_path = None

        self._scenario_getter = scenario_getter

        # For sensor_stuck
        self._stuck: Optional[Tuple[Optional[float], ...]] = None

        # CSV replay
        if isinstance(csv_path, str) and csv_path:
            p = Path(csv_path)
            if p.exists():
                self._rows = self._load_csv(p)

    def _load_csv(self, path: Path) -> List[Tuple[Optional[float], ...]]:
        rows: List[Tuple[Optional[float], ...]] = []
        with path.open("r", newline="") as f:
            reader = csv.reader(f)

            def parse_row(r):
                nums = []
                for item in r:
                    try:
                        nums.append(float(item))
                    except Exception:
                        continue
                    if len(nums) == 5:
                        break
                if len(nums) != 5:
                    return None
                return tuple(nums)

            first = next(reader, None)
            if first:
                maybe = parse_row(first)
                if maybe is not None:
                    rows.append(maybe)

            for r in reader:
                maybe = parse_row(r)
                if maybe is not None:
                    rows.append(maybe)

        return rows

    def _scenario(self) -> str:
        if not self._scenario_getter:
            return "normal"
        try:
            return (self._scenario_getter() or "normal").strip().lower()
        except Exception:
            return "normal"

    def read(self) -> Tuple[Optional[float], ...]:
        # CSV replay
        if self._rows:
            row = self._rows[self._i]
            self._i += 1
            if self._i >= len(self._rows):
                self._i = 0 if self._loop else len(self._rows) - 1
            return row

        # Synthetic stream (5 channels)
        t = time.time() - self._t0
        # temp1 = OAT: swing across cold -> warm -> lockout ranges (e.g., ~45°F to ~80°F)
        base1 = 62.5 + 17.5 * math.sin(t / 18)

        # temp2 = MAT: track OAT but clamp at ~55 when economizer "active", and move toward ~75 when locked out
        MAT_MIN_SP = 55.0
        LOCKOUT_OAT = 70.0
        RAT_TEMP = 75.0

        oat = base1
        if oat >= LOCKOUT_OAT:
            mat_ideal = RAT_TEMP
        else:
            mat_ideal = max(MAT_MIN_SP, oat)

        # Add small dynamics so MAT doesn't look perfectly ideal
        base2 = mat_ideal + 1.0 * math.sin(t / 11 + 1.2)

        base3 = 60 + 4 * math.sin(t / 15 + 2.1)
        base4 = 55 + 2 * math.sin(t / 9 + 0.4)
        base5 = 1 + 0.2 * math.sin(t / 7)

        def noise(s: float) -> float:
            return random.uniform(-s, s)

        scenario = self._scenario()

        # sensor_stuck: freeze output once we enter this scenario
        if scenario == "sensor_stuck":
            if self._stuck is None:
                self._stuck = (
                    round(base1 + noise(0.3), 3),
                    round(base2 + noise(0.3), 3),
                    round(base3 + noise(0.3), 3),
                    round(base4 + noise(0.3), 3),
                    round(base5 + noise(0.02), 3),
                )
            return self._stuck
        else:
            self._stuck = None

        # no_flow: collapse channel 5 near zero
        if scenario == "no_flow":
            return (
                round(base1 + noise(0.3), 3),
                round(base2 + noise(0.3), 3),
                round(base3 + noise(0.3), 3),
                round(base4 + noise(0.3), 3),
                round(max(0.0, 0.02 + noise(0.01)), 3),
            )

        # poor_efficiency: boost channel 5 significantly
        if scenario == "poor_efficiency":
            boost = 2.5 + 0.6 * abs(math.sin(t / 6))
            return (
                round(base1 + noise(0.35), 3),
                round(base2 + noise(0.35), 3),
                round(base3 + noise(0.35), 3),
                round(base4 + noise(0.35), 3),
                round(max(0.0, base5 + boost + noise(0.08)), 3),
            )

        # noisy: bigger noise + occasional spike
        if scenario == "noisy":
            spike = 0.0
            if random.random() < 0.08:
                spike = random.choice([-1, 1]) * random.uniform(1.5, 4.0)
            return (
                round(base1 + noise(1.2) + spike, 3),
                round(base2 + noise(1.2) - 0.5 * spike, 3),
                round(base3 + noise(1.2) + 0.3 * spike, 3),
                round(base4 + noise(1.2) - 0.2 * spike, 3),
                round(max(0.0, base5 + noise(0.35) + 0.15 * spike), 3),
            )

        # normal (default)
        return (
            round(base1 + noise(0.3), 3),
            round(base2 + noise(0.3), 3),
            round(base3 + noise(0.3), 3),
            round(base4 + noise(0.3), 3),
            round(base5 + noise(0.02), 3),
        )

    def close(self) -> None:
        return
