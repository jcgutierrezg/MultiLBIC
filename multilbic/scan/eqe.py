"""
EQE from a map and the photodiode's power readings (D31, D32).

The cell and the photodiode see the same beam, the photodiode before and
after the map (`run.locate.PhotodiodeStops`). The laser's optical power
at a moment is the photodiode's current then, dark taken out, over the
photodiode's response to that laser (A/W). A pixel's EQE, electrons out
over photons in, is then

    EQE = I_cell / P * hc / (q lambda)
        = (I_cell / I_pd) * R * 1239.84 / lambda_nm

with I_pd interpolated in time between the reading before and the one
after, row by row (each row's time the middle of its move). Both
currents are negative as wired, so the EQE comes out positive.

**The response R** comes, in order of preference, from:

1. the run file's header: the photodiode's response to that laser
   measured with a power meter, as `machine.toml` had it when the run
   was made (D32 revised);
2. `machine.toml` as it is now, if measured since;
3. the S1223-01's typical curve (Hamamatsu's datasheet, below): close,
   not this photodiode's own, and steep below 600 nm, where a few nm or
   a reading off the graph is several percent.

What a map's EQE rests on is said wherever it is shown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

#: hc / q in V nm: a photon of `lambda` nm carries 1239.84 / lambda eV.
HC_OVER_Q_NM = 1239.84193

#: The S1223-01's typical photosensitivity, A/W (Ta 25 C): Hamamatsu,
#: "Si PIN photodiodes S1223 series", Cat. No. KPIN1050E02, Feb. 2013.
#: "table": the datasheet's electrical and optical characteristics
#: (660, 780, 830 nm and the 960 nm peak); "graph": read off its spectral
#: response curve (KPINB0143EB) to about 0.01 A/W.
S1223_01_A_W: tuple[tuple[float, float, str], ...] = (
    (320.0, 0.10, "graph"),
    (400.0, 0.17, "graph"),
    (450.0, 0.235, "graph"),
    (500.0, 0.295, "graph"),
    (550.0, 0.345, "graph"),
    (600.0, 0.39, "graph"),
    (660.0, 0.45, "table"),
    (700.0, 0.475, "graph"),
    (780.0, 0.52, "table"),
    (830.0, 0.54, "table"),
    (900.0, 0.565, "graph"),
    (960.0, 0.60, "table"),
)
DATASHEET = "S1223-01 datasheet (typical)"


def datasheet_response(nm: float) -> float:
    """The S1223-01's typical response at `nm`, A/W, straight lines
    between the points above; NaN outside 320-960 nm."""
    points = np.array([(w, r) for w, r, _ in S1223_01_A_W])
    if not points[0, 0] <= nm <= points[-1, 0]:
        return math.nan
    return float(np.interp(nm, points[:, 0], points[:, 1]))


@dataclass(frozen=True)
class Response:
    """The photodiode's response to one laser, and where it comes from."""

    a_w: float
    #: "measured" (a power meter) or "datasheet".
    source: str
    #: When it was measured.
    date: str | None = None
    #: "run" (as when the run was made) or "now" (machine.toml since).
    taken_from: str | None = None

    @property
    def measured(self) -> bool:
        return self.source == "measured"

    def describe(self) -> str:
        if not self.measured:
            return f"photodiode response {self.a_w:.3f} A/W ({DATASHEET})"
        when = f" {self.date}" if self.date else ""
        since = " (measured after the run)" if self.taken_from == "now" else ""
        return (f"photodiode response {self.a_w:.3f} A/W, measured{when}"
                f"{since}")


def response_for(header: dict[str, Any], nm: float,
                 measured_now: tuple[float | None, str | None] = (None, None),
                 ) -> Response | None:
    """The response to use for a run file with `header`, at `nm`;
    `measured_now` is machine.toml's (A/W, date) for that laser. None if
    there is none, not even the datasheet's."""
    a_w = header.get("pd_response_a_w")
    if a_w:
        return Response(float(a_w), "measured", header.get("pd_response_date"),
                        "run")
    now, date = measured_now
    if now:
        return Response(float(now), "measured", date, "now")
    sheet = datasheet_response(nm)
    if math.isfinite(sheet):
        return Response(sheet, "datasheet")
    return None


@dataclass(frozen=True)
class PowerTrack:
    """The photodiode lit by the laser over its map, dark taken out: the
    reading before, the one after (if any), a straight line between."""

    t_before_s: float
    before_a: float
    t_after_s: float | None = None
    after_a: float | None = None

    @classmethod
    def from_header(cls, header: dict[str, Any]) -> PowerTrack | None:
        """From a run file's `power_before`, `power_after` and
        `power_dark`; None without the power before."""
        before = header.get("power_before")
        if not isinstance(before, dict):
            return None
        dark_entry = header.get("power_dark")
        dark = (float(dark_entry["current_a"])
                if isinstance(dark_entry, dict) else 0.0)
        after = header.get("power_after")
        if isinstance(after, dict):
            return cls(float(before["t_s"]), float(before["current_a"]) - dark,
                       float(after["t_s"]), float(after["current_a"]) - dark)
        return cls(float(before["t_s"]), float(before["current_a"]) - dark)

    @property
    def drift(self) -> float | None:
        """After over before, less 1: +0.03 is 3 % more light at the
        end; None without the reading after."""
        if self.after_a is None or self.before_a == 0:
            return None
        return self.after_a / self.before_a - 1.0

    def at(self, t_s: np.ndarray) -> np.ndarray:
        """The photodiode's net current at host times `t_s`: straight
        between the readings, held level beyond them."""
        t = np.asarray(t_s, dtype=float)
        if self.after_a is None or self.t_after_s is None \
                or self.t_after_s <= self.t_before_s:
            return np.full(t.shape, self.before_a)
        return np.interp(t, [self.t_before_s, self.t_after_s],
                         [self.before_a, self.after_a])

    def describe(self) -> str:
        d = self.drift
        if d is None:
            return "power read before the map only"
        return f"power {d:+.1%} from before the map to after"


def row_times(anchors: list[Any], n_rows: int) -> np.ndarray:
    """Each scan row's time, host clock: the middle of its move (from
    its anchor); NaN for a row not scanned."""
    out = np.full(n_rows, np.nan)
    for a in anchors:
        if 0 <= a.index < n_rows:
            out[a.index] = (a.sent_s + a.end_s) / 2
    return out


def eqe_map(values_a: np.ndarray, times_s: np.ndarray, track: PowerTrack,
            response: Response, nm: float) -> np.ndarray:
    """EQE per pixel of `values_a[row, column]` (the cell's current, A,
    baseline taken out), each row at `times_s[row]`; a fraction (0.85 is
    85 %). NaN where the cell has no value or the row no time."""
    i_pd = track.at(times_s)
    with np.errstate(divide="ignore", invalid="ignore"):
        factor = response.a_w * HC_OVER_Q_NM / nm / i_pd
    factor = np.where(np.isfinite(factor), factor, np.nan)
    return np.asarray(values_a, dtype=float) * factor[:, None]
