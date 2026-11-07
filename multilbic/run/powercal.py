"""
The photodiode's response to each laser, calibrated with a power meter
(D32 revised): the Maintenance window's Power tab.

The meter is not part of the system: its reading is typed. For one
laser at a time:

1. **The photodiode before**: the open quarter under the laser, the dark
   read, the laser lit and left to warm up, its range chosen from the
   light, then `READ_S` of readings. The laser stays on.
2. **The meter**: its head under the beam at the sample's place (the
   operator jogs there, the laser still on), set to the laser's
   wavelength; its reading typed, in mW.
3. **The photodiode after**: back on the open quarter, the same range,
   read again; then the laser off and the dark read on that range.

The response is the photodiode's light (the mean of before and after,
the dark taken out) over the meter's power, A/W. Before and after apart
by more than `DRIFT_WARN` means the laser moved while the meter was
read: worth doing again. Saved, it goes into the laser's table in
machine.toml as `pd_response_a_w` and `pd_response_date`, with the
readings in a comment, and every map made since rests its EQE on it
(`scan.eqe`).
"""

from __future__ import annotations

import json
import math
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from multilbic.config.machine import MachineConfig, parse
from multilbic.run.commission import (
    Commissioner,
    CommissionError,
    CommissionRequest,
    LaserCommission,
)
from multilbic.run.locate import PowerReading
from multilbic.run.reading import amps
from multilbic.scan.eqe import datasheet_response

#: Each photodiode reading, s.
READ_S = 5.0
#: The laser on the photodiode before its first reading, s: as a run's
#: warm-up (D16).
WARMUP_S = 60.0
#: Before and after further apart than this: worth doing again.
DRIFT_WARN = 0.02
#: A response further than this from the datasheet's is said so: the
#: meter's wavelength setting, or its head not catching the whole beam.
DATASHEET_WARN = 0.25


@dataclass
class PowerCal:
    """One laser's calibration as it goes."""

    laser: int
    wavelength_nm: float
    before: PowerReading | None = None
    meter_mw: float | None = None
    after: PowerReading | None = None
    dark: PowerReading | None = None
    #: The photodiode's range, chosen at the reading before.
    range_a: float | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def drift(self) -> float | None:
        if self.before is None or self.after is None \
                or self.before.current_a == 0:
            return None
        return self.after.current_a / self.before.current_a - 1.0

    @property
    def light_a(self) -> float | None:
        """The photodiode's light: before and after's mean, dark out."""
        if self.before is None or self.after is None or self.dark is None:
            return None
        return ((self.before.current_a + self.after.current_a) / 2
                - self.dark.current_a)

    @property
    def response_a_w(self) -> float | None:
        light = self.light_a
        if light is None or not self.meter_mw:
            return None
        return abs(light) / (self.meter_mw * 1e-3)

    def checks(self) -> list[str]:
        """What is worth a second look in the result."""
        out = []
        d = self.drift
        if d is not None and abs(d) > DRIFT_WARN:
            out.append(f"the photodiode moved {d:+.1%} from before to after: "
                       "the laser drifted while the meter was read; worth "
                       "doing again")
        r = self.response_a_w
        sheet = datasheet_response(self.wavelength_nm)
        if r is not None and math.isfinite(sheet) and \
                abs(r / sheet - 1) > DATASHEET_WARN:
            out.append(f"{r:.3f} A/W is {r / sheet - 1:+.0%} from the "
                       f"datasheet's {sheet:.3f}: check the meter is set to "
                       f"{self.wavelength_nm:g} nm and catches the whole "
                       "beam")
        for reading in (self.before, self.after):
            if reading is not None and reading.reading.at_limit:
                out.append(f"the photodiode reached its range's limit "
                           f"({amps(reading.range_a)})")
        return out

    def lines(self) -> list[str]:
        out = [f"laser {self.laser} ({self.wavelength_nm:g} nm)"]
        if self.before is not None:
            out.append(f"photodiode before: {amps(self.before.current_a)} "
                       f"on the {amps(self.before.range_a)} range")
        if self.meter_mw is not None:
            out.append(f"meter: {self.meter_mw:g} mW")
        if self.after is not None:
            out.append(f"photodiode after: {amps(self.after.current_a)}")
        if self.dark is not None:
            out.append(f"dark: {amps(self.dark.current_a)}")
        if self.drift is not None:
            out.append(f"before to after: {self.drift:+.2%}")
        r = self.response_a_w
        if r is not None:
            sheet = datasheet_response(self.wavelength_nm)
            out.append(f"response: {r:.4f} A/W (datasheet {sheet:.3f})")
        out += [f"! {w}" for w in self.checks() + self.warnings]
        return out

    def as_dict(self) -> dict[str, Any]:
        def reading(r: PowerReading | None) -> dict[str, Any] | None:
            return None if r is None else r.as_dict()

        return {
            "laser": self.laser, "wavelength_nm": self.wavelength_nm,
            "before": reading(self.before), "meter_mw": self.meter_mw,
            "after": reading(self.after), "dark": reading(self.dark),
            "drift": self.drift, "light_a": self.light_a,
            "response_a_w": self.response_a_w,
            "datasheet_a_w": datasheet_response(self.wavelength_nm),
            "warnings": self.checks() + self.warnings,
        }


class PowerCalibrator(Commissioner):
    """The photodiode readings of a calibration, on the open quarter
    (built on commissioning's: going there, the dark, the range)."""

    def read_before(self, cal: PowerCal, warmup_s: float = WARMUP_S,
                    read_s: float = READ_S) -> PowerReading:
        """The dark, the laser lit and warmed up, its range chosen, then
        its reading. The laser is left on."""
        n = cal.laser
        request = CommissionRequest((n,), warmup_s=warmup_s, read_s=1.0)
        r = LaserCommission(n)
        self._range = None
        self.devices.laser.off()
        self._find(r, request)
        if r.range_a is None:
            raise CommissionError(f"laser {n}: no range chosen")
        cal.range_a = r.range_a
        cal.before = self._timed(n, "before", read_s)
        cal.after = cal.dark = None
        return cal.before

    def read_after(self, cal: PowerCal,
                   read_s: float = READ_S) -> tuple[PowerReading, PowerReading]:
        """Back on the open quarter, the same range: the reading after,
        then the dark with the laser off."""
        from multilbic.scan.photodiode import open_quarter_middle

        if cal.before is None or cal.range_a is None:
            raise CommissionError("read the photodiode before first")
        n = cal.laser
        self.devices.laser.select(n)
        self._go(n, open_quarter_middle(self.machine))
        self._range = None
        self._set_range(cal.range_a)
        cal.after = self._timed(n, "after", read_s)
        self.devices.laser.off()
        cal.dark = self._timed(0, "dark", read_s)
        return cal.after, cal.dark

    def _timed(self, laser: int, when: str, seconds: float) -> PowerReading:
        t0 = self.clock.now()
        reading = self._read(laser, seconds)
        t1 = self.clock.now()
        assert self._range is not None
        return PowerReading(laser, when, (t0 + t1) / 2, reading, self._range)


def write_report(folder: Path, cal: PowerCal, *, simulated: bool,
                 provenance: dict[str, Any]) -> Path:
    """The calibration's readings, as a file in the runs folder."""
    import datetime

    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    path = folder / f"{stamp}_powercal_laser{cal.laser}.json"
    data = {"made": stamp, "simulated": simulated, "provenance": provenance,
            **cal.as_dict()}
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return path


_HEADER = re.compile(r"^\s*\[")
_NUMBER = re.compile(r"^\s*number\s*=\s*(\d+)")
_KEYS = {
    "pd_response_a_w": re.compile(r"^(\s*)pd_response_a_w\s*="),
    "pd_response_date": re.compile(r"^(\s*)pd_response_date\s*="),
}


def apply_response(text: str, laser: int, response_a_w: float, when: str,
                   note: str = "") -> str:
    """machine.toml's text with laser `laser`'s `pd_response_a_w` and
    `pd_response_date` set, everything else as it was. Checked by
    loading the result."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if _HEADER.match(line)]
    comment = f"  # power meter {when}" + (f": {note}" if note else "")
    values = {"pd_response_a_w": f"pd_response_a_w = {response_a_w:.4f}"
                                 f"{comment}\n",
              "pd_response_date": f'pd_response_date = "{when}"\n'}
    done = False
    for k in range(len(starts)):
        start = starts[k]
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        if lines[start].strip() != "[[lasers]]":
            continue
        number = next((int(m.group(1)) for i in range(start, end)
                       if (m := _NUMBER.match(lines[i]))), None)
        if number != laser:
            continue
        for key, value in values.items():
            for i in range(start, end):
                m = _KEYS[key].match(lines[i])
                if m:
                    lines[i] = m.group(1) + value
                    break
            else:
                at = end
                while at > start + 1 and not lines[at - 1].strip():
                    at -= 1
                lines.insert(at, value)
                end += 1
        done = True
        break
    if not done:
        raise CommissionError(f"laser {laser} is not in machine.toml")
    out = "".join(lines)
    machine: MachineConfig = parse(tomllib.loads(out), "proposed machine.toml")
    written = machine.laser(laser)
    if written.pd_response_a_w is None or \
            abs(written.pd_response_a_w - response_a_w) > 1e-4 or \
            written.pd_response_date != when:
        raise CommissionError(
            f"writing laser {laser}'s response went wrong: nothing written")
    return out
