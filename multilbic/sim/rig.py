"""
The whole machine in simulation, with a sample on the stage.

Builds the three fakes, joins them up and hands back the real drivers
talking to them. The fake SMU's current comes from the synthetic sample
at the spot's position on it, under whichever laser the fake laser board
has lit. That position comes from the fake Marlin's physical stage (X,
Y, A and B, backlash included), the true way XY lines up with AB, and
the true laser positions, so the scan has to recover the pattern from
the same kind of evidence it gets on the machine.

What the rig calls true can differ from `machine.toml` on purpose: a
laser's real position, or the real direction of an XY axis, to see what
a wrong setting does to a map.

`Faults` are the errors the scan is meant to survive. The defaults are
the agreed Phase 3 test case: 5 ms latency on Marlin's replies, 20 µm of
backlash on A and B, the SMU clock running 100 ppm fast, plus noise and
bursts shaped like the bench's. XY gets 0.1 mm of backlash, so placing
moves have to take it up.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from multilbic.clock import Clock
from multilbic.config.machine import MachineConfig
from multilbic.hardware.laser import LaserBoard
from multilbic.hardware.marlin import Marlin
from multilbic.hardware.smu import PhotocurrentSmu
from multilbic.scan.geometry import Calibration, ab_to_xy, xy_to_ab
from multilbic.sim.fake_laser import FakeLaserBoard
from multilbic.sim.fake_marlin import FakeMarlin
from multilbic.sim.fake_smu import FakeMiniSMU, FakeMiniSMUTransport
from multilbic.sim.link import connect
from multilbic.sim.photodiode import SimPhotodiode
from multilbic.sim.sample import SyntheticSample


@dataclass(frozen=True)
class Faults:
    reply_latency_s: float = 0.005
    reply_jitter_s: float = 0.001
    backlash_mm: float = 0.020
    xy_backlash_mm: float = 0.1
    smu_drift_ppm: float = 100.0
    #: The instrument's clock is nowhere near the host's.
    smu_offset_ms: float = 123_456.0
    smu_rate_error: float = 0.01
    smu_burst_s: float = 0.1
    #: The SMU stamps a packet this long after measuring it. 0 in the
    #: Phase 3 case; the bench's 18.6 ms is for the sync check's tests.
    smu_stamp_lag_s: float = 0.0
    noise_a: float = 20e-9
    mains_a: float = 20e-9
    drift_a: float = 40e-9

    @classmethod
    def none(cls) -> Faults:
        return cls(*(0.0 for _ in fields(cls)))


@dataclass
class SimRig:
    machine: MachineConfig
    clock: Clock
    sample: SyntheticSample
    #: Where the sample's corner really is on the carriage: the AB
    #: position that puts it under a laser with XY at that laser's true
    #: position.
    corner_carriage_mm: tuple[float, float]
    faults: Faults = field(default_factory=Faults)
    #: The truth, where it may differ from machine.toml.
    x_along: str | None = None
    y_along: str | None = None
    laser_xy_mm: dict[int, tuple[float, float]] = field(default_factory=dict)
    #: The channels the SMU driver is set up on.
    smu_channels: tuple[int, ...] = (1,)
    #: The photodiode under its blades, on the channel machine.toml
    #: gives it: as machine.toml has it unless given (the truth can
    #: differ, as `laser_xy_mm` can). None without a [photodiode].
    photodiode: SimPhotodiode | None = None

    def __post_init__(self) -> None:
        f = self.faults
        g = self.machine.geometry
        self.x_along = self.x_along or g.x_along
        self.y_along = self.y_along or g.y_along
        for laser in self.machine.lasers:
            self.laser_xy_mm.setdefault(laser.number, laser.xy_centre_mm)
        if self.photodiode is None and self.machine.photodiode is not None:
            self.photodiode = SimPhotodiode.from_config(self.machine)
        self.fake_marlin = FakeMarlin(
            self.machine,
            home_duration_s=1.0,
            backlash_mm={
                "A": f.backlash_mm, "B": f.backlash_mm,
                "X": f.xy_backlash_mm, "Y": f.xy_backlash_mm,
            },
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
            mains_hz=self.machine.mains_hz,
            drift_a=f.drift_a,
            burst_s=f.smu_burst_s,
            stamp_lag_s=f.smu_stamp_lag_s,
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
            FakeMiniSMUTransport(self.fake_smu), self.clock,
            self.smu_channels,
        )

    def spot_carriage(
        self, position: dict[str, float], laser: int
    ) -> tuple[float, float]:
        """Which carriage point (calibration's frame) laser `laser`'s
        spot is on, with the stage at `position`."""
        laser_x, laser_y = self.laser_xy_mm[laser]
        assert self.x_along is not None and self.y_along is not None
        da, db = xy_to_ab(
            self.x_along, self.y_along,
            position["X"] - laser_x, position["Y"] - laser_y,
        )
        return position["A"] + da, position["B"] + db

    def spot_uv(
        self, position: dict[str, float], laser: int
    ) -> tuple[float, float]:
        """Where laser `laser`'s spot is on the sample, in its frame,
        with the stage at `position`."""
        a, b = self.spot_carriage(position, laser)
        return (a - self.corner_carriage_mm[0],
                b - self.corner_carriage_mm[1])

    def true_uv(self, t: float, laser: int) -> tuple[float, float]:
        """Where the spot was on the sample at time `t`."""
        return self.spot_uv(self.fake_marlin.past_stage_position(t), laser)

    def _signal(self, channel: int, t: float) -> float:
        lit = self.fake_laser.active
        pd_channel = (self.machine.photodiode.channel
                      if self.machine.photodiode is not None else None)
        if channel == pd_channel:
            assert self.photodiode is not None
            if not lit:
                return self.photodiode.dark_a
            a, b = self.spot_carriage(self.fake_marlin.stage_position(t), lit)
            return self.photodiode.current(lit, a, b)
        if channel != 1:
            return 0.0
        if not lit:
            return self.sample.dark_a
        u, v = self.spot_uv(self.fake_marlin.stage_position(t), lit)
        nm = self.machine.laser(lit).wavelength_nm
        return self.sample.current(nm, u, v)

    def perfect_calibration(self, sample: str = "synthetic") -> Calibration:
        """The calibration a perfect operator would record: the corner
        exactly under the reference laser with AB at its centre, every
        axis having arrived moving up (so each motor reads half its
        backlash above where its stage is), and the reference laser's
        position as machine.toml has it."""
        g = self.machine.geometry
        f = self.faults
        reference = self.machine.laser(g.reference_laser).xy_centre_mm
        true_reference = self.laser_xy_mm[g.reference_laser]
        centre = self.machine.ab.centre_mm
        stage_ab = (
            centre[0] - f.backlash_mm / 2, centre[1] - f.backlash_mm / 2
        )
        assert self.x_along is not None and self.y_along is not None
        dx, dy = ab_to_xy(
            self.x_along, self.y_along,
            self.corner_carriage_mm[0] - stage_ab[0],
            self.corner_carriage_mm[1] - stage_ab[1],
        )
        half = f.xy_backlash_mm / 2
        corner_xy = (
            true_reference[0] + dx + half, true_reference[1] + dy + half
        )
        return Calibration(
            sample, g.reference_laser, reference, corner_xy, centre,
            self.sample.width_mm, self.sample.height_mm,
            g.x_along, g.y_along, self.machine.ab.home_offset_mm,
        )

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
