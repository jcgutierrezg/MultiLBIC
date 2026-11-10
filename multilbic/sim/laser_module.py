"""
A laser module wired straight to the miniSMU's channel 1, with the
photodiode on channel 2: what `multilbic.bench.laser_module` runs
against in simulation.

Three kinds, the cases the probe has to tell apart:

* **regulated**: a diode behind its own constant-current regulator.
  The current rises until the regulator takes over, then stays flat
  however high the voltage goes.
* **resistor**: a diode and a series resistor, nothing else. The current
  keeps rising with the voltage.
* **starved**: regulated, but its regulator needs more voltage than the
  board gives it today (what lasers 1 and 2 look like on the 5 V LM317).
* **rollover**: no regulator, and its light per mA falls off as it
  heats, well before the light ceiling: the bending stop.
* **laser4**: laser 4 as measured, lasing past the 1 mA the miniSMU
  allows a channel while autoranging, then its regulator's soft knee.
* **laser3**: laser 3 as measured, a plain diode until its driver
  switches on, then less current for more light.
* **dummy**: a 100 ohm resistor, for the dry run.

Channel 2 clips as the real one does: at 1 mA while autoranging, at
its range's end on a fixed range.

The numbers are plausible, not measured: they exist to exercise the
probe's stages and its verdicts.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from multilbic.clock import Clock
from multilbic.sim.fake_smu import CURRENT_RANGES_A, FakeMiniSMU


@dataclass(frozen=True)
class ModuleModel:
    kind: str
    #: Diode voltage at 20 mA, and n*kT/q of its exponential.
    vf_20ma: float
    n_vt: float
    #: Series resistance (the resistor, or the wiring and diode's own).
    r_ohm: float
    #: The regulator: its current, and the voltage it needs on top of
    #: the diode's. None for a module with no regulator.
    i_reg_a: float | None
    v_overhead: float
    #: Lasing threshold, and photodiode amps per amp above it.
    i_th_a: float
    pd_slope: float
    #: The voltage the board gives it today.
    v_known: float
    #: Light per amp falls linearly to zero this far above threshold
    #: (thermal rollover); None for a straight line.
    roll_a: float | None = None
    #: A soft regulator: past i_reg_a the module takes more current only
    #: at this many volts per amp, and its diode stays at i_reg_a (laser
    #: 4's knee). None: a hard wall at i_reg_a.
    knee_ohm: float | None = None

    @property
    def i_known(self) -> float:
        """The current it draws on the board today, as a multimeter
        in series would read it."""
        return self.current_at(self.v_known)

    @property
    def _i_s(self) -> float:
        return 0.02 / math.expm1(self.vf_20ma / self.n_vt)

    def _diode_v(self, amps: float) -> float:
        return self.n_vt * math.log1p(max(amps, 0.0) / self._i_s)

    def _diode_r_current(self, volts: float) -> float:
        """Current through the diode and r_ohm at `volts` (bisection)."""
        if volts <= 0:
            return 0.0
        lo, hi = 0.0, volts / self.r_ohm + 1.0
        for _ in range(80):
            mid = (lo + hi) / 2
            if self._diode_v(mid) + mid * self.r_ohm > volts:
                hi = mid
            else:
                lo = mid
        return lo

    def _below_reg_v(self, amps: float) -> float:
        return self._diode_v(amps) + amps * self.r_ohm + self.v_overhead

    def current_at(self, volts: float) -> float:
        if self.i_reg_a is None:
            return self._diode_r_current(volts)
        if self.knee_ohm is not None:
            knee_v = self._below_reg_v(self.i_reg_a)
            if volts > knee_v:
                return self.i_reg_a + (volts - knee_v) / self.knee_ohm
        return min(self.i_reg_a, self._diode_r_current(volts - self.v_overhead))

    def voltage_at(self, amps: float) -> float:
        """The voltage that drives `amps` through it; inf if it can't
        take that much (its regulator holds it below)."""
        if self.i_reg_a is not None:
            if amps >= self.i_reg_a:
                if self.knee_ohm is None:
                    return math.inf
                return (self._below_reg_v(self.i_reg_a)
                        + (amps - self.i_reg_a) * self.knee_ohm)
            return self._below_reg_v(amps)
        return self._diode_v(amps) + amps * self.r_ohm

    def photocurrent(self, amps: float) -> float:
        """The photodiode's reading (negative, as on the machine)."""
        if self.i_reg_a is not None:
            amps = min(amps, self.i_reg_a)  # the diode's share
        x = max(0.0, amps - self.i_th_a)
        if self.roll_a is not None:
            x = min(x, self.roll_a)
            x = x * (1 - x / (2 * self.roll_a))
        lasing = x * self.pd_slope
        glow = min(max(amps, 0.0), self.i_th_a) * self.pd_slope * 0.002
        return -(lasing + glow)


@dataclass(frozen=True)
class DummyLoad:
    """A plain resistor in the module's place, for the dry run."""

    r_ohm: float = 100.0
    kind: str = "dummy"
    v_known: float = 2.0

    @property
    def i_known(self) -> float:
        return self.current_at(self.v_known)

    def current_at(self, volts: float) -> float:
        return max(volts, 0.0) / self.r_ohm

    def voltage_at(self, amps: float) -> float:
        return amps * self.r_ohm

    def photocurrent(self, amps: float) -> float:
        return 0.0


@dataclass
class DriverModule:
    """A module with a driver inside that switches on (laser 3,
    2026-11-10). Below `v_on` its driver is fully on and the module is
    its plain diode; from `v_on` the driver runs it, taking
    `i0_a + di_dv * V` and giving `light0_a + dlight_dv * V` on the
    photodiode, more light than that current gives the diode, until the
    voltage falls below `v_off` or the module is switched off."""

    diode: ModuleModel
    v_on: float
    v_off: float
    i0_a: float
    di_dv: float
    light0_a: float
    dlight_dv: float
    v_known: float
    kind: str = "driver"
    on: bool = False

    @property
    def i_known(self) -> float:
        return self.i0_a + self.di_dv * self.v_known

    def fimv(self, amps: float, v_limit: float) -> tuple[float, float]:
        """(volts, amps) with `amps` forced, held to `v_limit`."""
        if not self.on:
            volts = self.diode.voltage_at(amps)
            if volts < self.v_on:
                return min(volts, v_limit), amps
            self.on = True
        volts = (amps - self.i0_a) / self.di_dv
        if volts < self.v_off:
            self.on = False
            return min(self.diode.voltage_at(amps), v_limit), amps
        if volts > v_limit:
            volts = v_limit
            amps = self.i0_a + self.di_dv * volts
        return volts, amps

    def fvmi(self, volts: float, i_limit: float) -> tuple[float, float]:
        """(volts, amps) with `volts` forced, held to `i_limit`."""
        if self.on and volts < self.v_off:
            self.on = False
        if not self.on and volts >= self.v_on:
            self.on = True
        if self.on:
            amps = self.i0_a + self.di_dv * volts
            if i_limit and amps > i_limit:
                amps = i_limit
                volts = (amps - self.i0_a) / self.di_dv
            return volts, amps
        amps = self.diode.current_at(volts)
        if i_limit and amps > i_limit:
            amps = i_limit
            volts = self.diode.voltage_at(amps)
        return volts, amps

    def light(self, volts: float, amps: float) -> float:
        if self.on:
            return -(self.light0_a + self.dlight_dv * volts)
        return self.diode.photocurrent(amps)


MODULES: dict[str, ModuleModel | DummyLoad | DriverModule] = {
    "regulated": ModuleModel(
        "regulated", vf_20ma=2.05, n_vt=0.05, r_ohm=2.0, i_reg_a=0.028,
        v_overhead=0.35, i_th_a=0.016, pd_slope=0.06, v_known=3.0,
    ),
    "resistor": ModuleModel(
        "resistor", vf_20ma=2.05, n_vt=0.05, r_ohm=33.0, i_reg_a=None,
        v_overhead=0.0, i_th_a=0.012, pd_slope=0.12, v_known=3.0,
    ),
    "starved": ModuleModel(
        "starved", vf_20ma=3.4, n_vt=0.06, r_ohm=3.0, i_reg_a=0.035,
        v_overhead=1.0, i_th_a=0.012, pd_slope=0.03, v_known=4.5,
    ),
    "rollover": ModuleModel(
        "rollover", vf_20ma=2.05, n_vt=0.05, r_ohm=20.0, i_reg_a=None,
        v_overhead=0.0, i_th_a=0.014, pd_slope=0.05, v_known=2.6, roll_a=0.02,
    ),
    # Laser 4 as measured on 2026-11-10: lasing from 16.5 mA at 0.248 A/A
    # on the photodiode, past the 1 mA the autoranging miniSMU allows,
    # and a soft regulator from 22.3 mA (25 ohm, then about 1500).
    "laser4": ModuleModel(
        "laser4", vf_20ma=1.896, n_vt=0.03, r_ohm=25.0, i_reg_a=0.0223,
        v_overhead=0.0, i_th_a=0.0165, pd_slope=0.248, v_known=3.26,
        knee_ohm=1500.0,
    ),
    "dummy": DummyLoad(),
}

#: Laser 3 as measured on 2026-11-10: a plain diode (lasing from 13.1 mA
#: at 0.152 A/A) to 22.5 mA and 2.42 V; past that its driver, 16.0 mA at
#: 3.26 V (the board) to 16.6 mA at 5.5 V, giving 1203 to 1382 uA.
LASER3_DIODE = ModuleModel(
    "laser3", vf_20ma=2.065, n_vt=0.03, r_ohm=15.0, i_reg_a=None,
    v_overhead=0.0, i_th_a=0.01306, pd_slope=0.1518, v_known=2.4,
)


def module(name: str) -> ModuleModel | DummyLoad | DriverModule:
    """A fresh simulated module (a driver keeps state)."""
    if name == "laser3":
        return DriverModule(
            LASER3_DIODE, v_on=2.41, v_off=2.4, i0_a=15.2e-3, di_dv=0.25e-3,
            light0_a=947e-6, dlight_dv=78.5e-6, v_known=3.26,
        )
    return MODULES[name]


class FakeModuleSMU(FakeMiniSMU):
    """The fake miniSMU with a laser module on channel 1 and the
    photodiode, lit by it, on channel 2. Channel 1 sources voltage
    (FVMI, held to its current limit) or current (FIMV, held to its
    voltage limit)."""

    PD_DARK_A = -2e-9
    AUTORANGE_END_A = 1e-3
    #: A fault: channel 2's first `PD_OFFSET_READS` readings off by
    #: `PD_OFFSET_A`, as laser 4's second run read its dark (2026-11-10).
    PD_OFFSET_A = 0.0
    PD_OFFSET_V = 0.0
    PD_OFFSET_READS = 0
    #: A fault: from this module current, the light reads this share low
    #: for this many readings (laser 5's dips, 2026-11-10).
    PD_DIP_FROM_A: float | None = None
    PD_DIP_SHARE = 0.3
    PD_DIP_READS = 0

    def __init__(self, clock: Clock, module: ModuleModel | DummyLoad | DriverModule,
                 seed: int = 0):
        super().__init__(clock, seed=seed)
        self.module = module
        self.level_a = {1: 0.0, 2: 0.0}
        self.voltage_limit = {1: 12.0, 2: 12.0}
        self._noise = random.Random(seed + 7)
        self._offset_left = self.PD_OFFSET_READS
        self._dip_left = self.PD_DIP_READS

    def set_current(self, channel: int, current: float):
        self.level_a[channel] = current

    def set_voltage_protection(self, channel: int, voltage_limit: float):
        self.voltage_limit[channel] = voltage_limit

    def _module_state(self) -> tuple[float, float]:
        """(volts, amps) on channel 1 as it is set now."""
        m = self.module
        if not self.enabled[1]:
            if isinstance(m, DriverModule):
                m.on = False
            return 0.0, 0.0
        if isinstance(m, DriverModule):
            if self.mode[1] == "FIMV":
                return m.fimv(self.level_a[1], self.voltage_limit[1])
            return m.fvmi(self.voltage[1], self.current_limit[1])
        if self.mode[1] == "FIMV":
            amps = self.level_a[1]
            volts = m.voltage_at(amps)
            if volts > self.voltage_limit[1]:
                volts = self.voltage_limit[1]
                amps = m.current_at(volts)
            return volts, amps
        volts = self.voltage[1]
        amps = m.current_at(volts)
        limit = self.current_limit[1]
        if limit and amps > limit:
            amps = limit
            volts = m.voltage_at(limit)
        return volts, amps

    def measure_voltage_and_current(self, channel: int) -> tuple[float, float]:
        volts, amps = self._module_state()
        if channel == 1:
            return (
                volts + self._noise.gauss(0, 1e-3),
                amps + self._noise.gauss(0, 1e-6),
            )
        if not self.enabled[2]:
            return 0.0, 0.0
        light = (self.module.light(volts, amps) if isinstance(self.module, DriverModule)
                 else self.module.photocurrent(amps))
        if self._dip_left > 0 and self.PD_DIP_FROM_A is not None \
                and amps >= self.PD_DIP_FROM_A:
            self._dip_left -= 1
            light *= 1 - self.PD_DIP_SHARE
        pd = self.PD_DARK_A + light + self._noise.gauss(0, 2e-9)
        volts_2 = 0.0
        if self._offset_left > 0:
            self._offset_left -= 1
            pd += self.PD_OFFSET_A
            volts_2 = self.PD_OFFSET_V
        # As the real one: autoranging, held to 1 mA whatever the limit;
        # on a fixed range, no further than its end.
        index = self.current_range[2]
        end = self.AUTORANGE_END_A if self.autorange[2] or index is None \
            else CURRENT_RANGES_A[index]
        return volts_2, max(-end, min(end, pd))
