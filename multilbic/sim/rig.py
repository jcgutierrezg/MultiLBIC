"""
The whole machine in simulation, with a sample on the stage.

Builds the three fakes, joins them up and hands back the real drivers
talking to them. The fake SMU's current comes from the synthetic sample
at the stage's simulated position, under whichever laser the fake laser
board has lit. The stage position is the fake Marlin's physical one,
backlash included, so the scan has to recover the pattern from the same
kind of evidence it gets on the machine.

`Faults` are the errors the scan is meant to survive. The defaults are
the agreed Phase 3 test case: 5 ms latency on Marlin's replies, 20 µm of
backlash on A and B, the SMU clock running 100 ppm fast, plus noise and
bursts shaped like the bench's.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from multilbic.clock import Clock
from multilbic.config.machine import MachineConfig
from multilbic.hardware.laser import LaserBoard
from multilbic.hardware.marlin import Marlin
from multilbic.hardware.smu import PhotocurrentSmu
from multilbic.scan.geometry import SampleFrame
from multilbic.sim.fake_laser import FakeLaserBoard
from multilbic.sim.fake_marlin import FakeMarlin
from multilbic.sim.fake_smu import FakeMiniSMU, FakeMiniSMUTransport
from multilbic.sim.link import connect
from multilbic.sim.sample import SyntheticSample


@dataclass(frozen=True)
class Faults:
    reply_latency_s: float = 0.005
    reply_jitter_s: float = 0.001
    backlash_mm: float = 0.020
    smu_drift_ppm: float = 100.0
    #: The instrument's clock is nowhere near the host's.
    smu_offset_ms: float = 123_456.0
    smu_rate_error: float = 0.01
    smu_burst_s: float = 0.1
    noise_a: float = 20e-9
    mains_a: float = 20e-9
    drift_a: float = 40e-9

    @classmethod
    def none(cls) -> Faults:
        return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


@dataclass
class SimRig:
    machine: MachineConfig
    clock: Clock
    sample: SyntheticSample
    #: Where the sample's corner really is in AB.
    placement: SampleFrame
    faults: Faults = field(default_factory=Faults)

    def __post_init__(self) -> None:
        f = self.faults
        self.fake_marlin = FakeMarlin(
            self.machine,
            home_duration_s=1.0,
            backlash_mm={"A": f.backlash_mm, "B": f.backlash_mm},
        )
        self.fake_laser = FakeLaserBoard(
            settle_ms=self.machine.laser_board.settle_ms
        )
        self.fake_smu = FakeMiniSMU(
            self.clock,
            signal=self._signal,
            noise_a=f.noise_a,
            device_offset_ms=f.smu_offset_ms,
            drift_ppm=f.smu_drift_ppm,
            rate_error=f.smu_rate_error,
            mains_a=f.mains_a,
            mains_hz=50.0,
            drift_a=f.drift_a,
            burst_s=f.smu_burst_s,
        )
        self.marlin = Marlin(
            connect(
                self.fake_marlin, self.clock,
                f.reply_latency_s, f.reply_jitter_s,
            ),
            self.machine,
            self.clock,
        )
        self.laser = LaserBoard(
            connect(self.fake_laser, self.clock), self.machine, self.clock
        )
        self.smu = PhotocurrentSmu(
            FakeMiniSMUTransport(self.fake_smu), self.clock
        )

    def _signal(self, channel: int, t: float) -> float:
        if channel != 1:
            return 0.0
        lit = self.fake_laser.active
        if not lit:
            return self.sample.dark_a
        position = self.fake_marlin.stage_position(t)
        u, v = self.placement.to_uv(position["A"], position["B"])
        nm = self.machine.laser(lit).wavelength_nm
        return self.sample.current(nm, u, v)

    def open(self) -> None:
        self.marlin.open()
        self.laser.open()
        self.smu.identify()

    def close(self) -> None:
        for device in (self.smu, self.laser, self.marlin):
            try:
                device.close()
            except Exception:  # noqa: S110 - best effort on the way out
                pass
