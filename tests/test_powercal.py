"""The photodiode's response to each laser, calibrated with a power meter
(D32 revised): the sums, writing machine.toml, and the whole thing
through the worker on the simulated machine."""

from importlib import resources

import pytest

from multilbic.clock import ScaledClock
from multilbic.config import load
from multilbic.config.machine import parse
from multilbic.gui.worker import (
    LaserChanged,
    MachineChanged,
    MachineWorker,
    PowerCalChanged,
    State,
)
from multilbic.run.commission import CommissionError
from multilbic.run.devices import open_sim
from multilbic.run.locate import PowerReading
from multilbic.run.powercal import PowerCal, apply_response
from multilbic.run.reading import summarise
from multilbic.sim.photodiode import BENCH_FULL_A
from multilbic.sim.rig import Faults
from multilbic.sim.scan import sim_machine
from tests.test_worker import Watcher


def reading(when, amps, laser=3):
    return PowerReading(laser, when, 0.0, summarise(laser, [amps] * 5, 15e-3),
                        15e-3)


def test_the_response_from_the_readings():
    cal = PowerCal(3, 652, before=reading("before", -1.20e-3),
                   meter_mw=2.5, after=reading("after", -1.22e-3),
                   dark=reading("dark", -1e-6, 0))
    assert cal.light_a == pytest.approx(-1.21e-3 + 1e-6)
    assert cal.response_a_w == pytest.approx((1.21e-3 - 1e-6) / 2.5e-3)
    assert cal.drift == pytest.approx(0.01 / 0.6, rel=1e-3)
    assert cal.checks() == []
    text = "\n".join(cal.lines())
    assert "2.5 mW" in text and "response: 0.4836 A/W" in text
    # The laser drifted while the meter was read: said so.
    cal.after = reading("after", -1.30e-3)
    assert any("drifted" in c for c in cal.checks())
    # Far from the datasheet: the meter's wavelength, or a missed beam.
    cal.after = reading("after", -1.20e-3)
    cal.meter_mw = 0.5
    assert any("meter is set to 652 nm" in c for c in cal.checks())
    # Nothing to compute until all of it is in.
    assert PowerCal(3, 652, before=reading("before", -1e-3)).response_a_w \
        is None


def toml_text():
    return resources.files("multilbic.config").joinpath(
        "machine.toml").read_text(encoding="utf-8")


def test_the_response_is_written_into_machine_toml():
    import tomllib

    text = toml_text()
    out = apply_response(text, 3, 0.48367, "2026-11-10",
                         "2.5 mW, photodiode -1.209 mA")
    laser = parse(tomllib.loads(out)).laser(3)
    assert laser.pd_response_a_w == pytest.approx(0.4837)
    assert laser.pd_response_date == "2026-11-10"
    assert "# power meter 2026-11-10: 2.5 mW" in out
    # Every other laser and every comment as they were.
    before, after = parse(tomllib.loads(text)), parse(tomllib.loads(out))
    for n in (1, 2, 4, 5, 6):
        assert after.laser(n) == before.laser(n)
    assert out.count("\n#") == text.count("\n#")
    # Again, the keys are replaced, not added.
    again = apply_response(out, 3, 0.47, "2026-12-01")
    assert again.count("pd_response_a_w =") == out.count("pd_response_a_w =")
    assert parse(tomllib.loads(again)).laser(3).pd_response_date == \
        "2026-12-01"
    with pytest.raises(CommissionError):
        apply_response(text, 9, 0.4, "2026-11-10")


def power_worker(machine, tmp_path):
    faults = Faults()
    machine = sim_machine(machine, faults)
    path = tmp_path / "machine.toml"
    path.write_text(toml_text(), encoding="utf-8", newline="")

    def connector():
        return open_sim(machine, clock=ScaledClock(50.0),
                        corner_carriage_mm=(15.0, 16.0), size_mm=(0.6, 0.2),
                        smu_channels=(1, 2))

    worker = MachineWorker(machine, connector, poll_s=0.05, machine_path=path)
    watch = Watcher(worker)
    worker.connect()
    watch.idle()
    assert worker.home()
    watch.idle()
    return worker, watch, path


def test_a_calibration_through_the_worker_and_save(machine, tmp_path):
    worker, watch, path = power_worker(machine, tmp_path)
    try:
        assert not worker.power_after(2.5)  # nothing read before: refused
        watch.idle()
        assert worker.power_before(3, 0.5)
        assert worker.state is State.COMMISSIONING
        watch.wait(lambda: watch.of(PowerCalChanged), timeout=120)
        watch.idle()
        (first,) = watch.of(PowerCalChanged)
        assert first.error is None, watch.errors()
        assert first.cal.before is not None and first.cal.after is None
        # The laser stays on for the meter.
        assert watch.of(LaserChanged)[-1].laser == 3

        assert worker.power_after(2.5, tmp_path / "runs", {"commit": "t"})
        watch.wait(lambda: len(watch.of(PowerCalChanged)) == 2, timeout=120)
        watch.idle()
        done = watch.of(PowerCalChanged)[-1]
        assert done.error is None, watch.errors()
        cal = done.cal
        # The simulated photodiode's full beam over the meter's 2.5 mW.
        assert cal.response_a_w == pytest.approx(
            abs(BENCH_FULL_A[3]) / 2.5e-3, rel=0.03)
        assert abs(cal.drift) < 0.01
        assert done.report is not None and done.report.exists()
        assert watch.of(LaserChanged)[-1].laser == 0

        assert worker.save_power()
        watch.wait(lambda: watch.of(MachineChanged))
        watch.idle()
        written = load(path).laser(3)
        assert written.pd_response_a_w == pytest.approx(cal.response_a_w,
                                                        abs=1e-4)
        assert worker.machine.laser(3).pd_response_a_w is not None
    finally:
        worker.close()


def test_stop_while_warming_up(machine, tmp_path):
    from multilbic.gui.worker import Log

    worker, watch, _ = power_worker(machine, tmp_path)
    try:
        assert worker.power_before(3, 600.0)
        watch.wait(lambda: any("laser 3 on" in e.text for e in watch.of(Log)))
        worker.stop()
        watch.idle()
        (ended,) = watch.of(PowerCalChanged)
        assert ended.cal is None and ended.error
        assert watch.of(LaserChanged)[-1].laser == 0
        assert not worker.power_after(2.5)
    finally:
        worker.close()
