"""The window's worker, driven as the window drives it, against the
simulated machine: commands in, events out, Stop, faults."""

import time
from dataclasses import replace

import pytest

from multilbic.clock import ScaledClock
from multilbic.gui.worker import (
    CalibrationChanged,
    Connected,
    LaserChanged,
    Log,
    MachineWorker,
    MapEvent,
    Position,
    Reading,
    RowEvent,
    RunEnded,
    RunStarted,
    State,
)
from multilbic.run.devices import (
    Connection,
    DeviceSetupError,
    machine_lock,
    open_sim,
)
from multilbic.run.session import RunRequest
from multilbic.scan.mapping import BASELINE_ROW
from multilbic.scan.photodiode import (
    open_quarter_middle,
    reach,
)
from multilbic.sim.rig import Faults
from multilbic.sim.scan import sim_machine

SIZE = (0.6, 0.2)
CORNER = (15.0, 16.0)


class Watcher:
    """Drains a worker's events the way the window will, and waits."""

    def __init__(self, worker):
        self.worker = worker
        self.events = []

    def pump(self):
        self.events += self.worker.drain()

    def wait(self, predicate, timeout=60.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError(f"timed out; last events: {self.events[-8:]}")

    def idle(self, timeout=60.0):
        self.wait(lambda: self.worker.state is State.IDLE, timeout)

    def of(self, kind):
        self.pump()
        return [e for e in self.events if isinstance(e, kind)]

    def errors(self):
        return [e.text for e in self.of(Log) if e.error]


@pytest.fixture
def setup(machine):
    """A worker on a simulated machine whose sample sits exactly where a
    perfect calibration says. Yields (worker, watcher, rig, machine)."""
    faults = Faults()
    machine = sim_machine(machine, faults)
    holder = {}

    def connector():
        conn = open_sim(machine, clock=ScaledClock(20.0),
                        corner_carriage_mm=CORNER, size_mm=SIZE,
                        faults=faults)
        holder["rig"] = conn.rig
        return conn

    worker = MachineWorker(machine, connector, sample="cell", poll_s=0.05)
    watch = Watcher(worker)
    assert worker.connect()
    watch.idle()
    yield worker, watch, holder["rig"], machine
    worker.close()


def test_connects_and_reports_firmware(setup):
    worker, watch, rig, machine = setup
    (connected,) = watch.of(Connected)
    assert connected.simulated
    assert set(connected.firmware) == {"marlin", "laser", "smu"}
    assert not watch.errors()


def test_calibration_through_the_worker(setup, tmp_path):
    worker, watch, rig, machine = setup
    truth = rig.perfect_calibration("cell")
    assert worker.start_calibration()
    watch.idle()
    assert watch.of(LaserChanged)[-1].laser == machine.geometry.reference_laser
    # Readings arrive on their own while idle.
    watch.wait(lambda: len(watch.of(Reading)) >= 2)

    x, y = truth.corner_xy_mm
    a, b = truth.corner_ab_mm
    for submit in (
        lambda: worker.move(x=x, y=y, a=a, b=b),
        worker.here,
        lambda: worker.set_size(*SIZE),
        worker.trace,
        lambda: worker.save(tmp_path / "cal.json"),
    ):
        assert submit()
        watch.idle()
    assert not watch.errors()
    change = watch.of(CalibrationChanged)[-1]
    assert change.saved == tmp_path / "cal.json"
    assert change.corner_xy == pytest.approx(truth.corner_xy_mm, abs=1e-4)
    assert change.size == SIZE
    (xy, outline) = change.outline
    assert len(outline) == 5
    # The trace ended back on the corner, really.
    u, v = rig.spot_uv(rig.fake_marlin.stage_position(),
                       machine.geometry.reference_laser)
    assert (u, v) == pytest.approx((0.0, 0.0), abs=1e-3)


def test_one_action_at_a_time(setup):
    worker, watch, rig, machine = setup
    assert worker.home()
    watch.idle()
    start = watch.of(Position)[-1].xyab
    assert worker.jog("x", 1.0)
    # A second jog while the first moves is refused, not queued.
    assert worker.state is State.MOVING
    assert not worker.jog("x", 1.0)
    assert not worker.start_calibration()
    watch.idle()
    end = watch.of(Position)[-1].xyab
    assert end["X"] - start["X"] == pytest.approx(1.0)
    assert not watch.errors()


def test_mistakes_are_reported_and_the_worker_goes_on(setup):
    worker, watch, rig, machine = setup
    assert worker.home()
    watch.idle()
    assert worker.jog("x", 25.0)  # over the 20 mm limit
    watch.idle()
    assert worker.trace()  # no corner yet
    watch.idle()
    errors = watch.errors()
    assert len(errors) == 2
    assert "limited" in errors[0] and "no corner" in errors[1]
    assert worker.jog("x", 0.5)
    watch.idle()
    assert len(watch.errors()) == 2


def test_stop_halts_a_trace_and_the_laser_stays_on(setup):
    worker, watch, rig, machine = setup
    truth = rig.perfect_calibration("cell")
    assert worker.start_calibration(check=truth)
    watch.idle()
    # A tall sample so the trace takes a while: 1 s simulated per side
    # at 2 mm/s is too quick to catch, so make it 10 mm.
    assert worker.set_size(10.0, 10.0)
    watch.idle()
    assert worker.trace()
    watch.wait(lambda: any("tracing" in e.text for e in watch.of(Log)))
    time.sleep(0.05)
    worker.stop()
    assert worker.state is State.STOPPING
    watch.idle()
    assert any(e.text == "trace: stopped" for e in watch.of(Log))
    assert not rig.fake_marlin.moving()
    assert rig.fake_laser.active == machine.geometry.reference_laser
    # Stop while idle turns the laser off.
    worker.stop()
    watch.idle()
    watch.wait(lambda: rig.fake_laser.active == 0)


def request(rig, **options):
    settings = dict(pixel_mm=0.01, pitch_mm=0.05, speed_mm_s=2.0,
                    baseline_s=0.5, warmup_s=0.5)
    settings.update(options)
    return RunRequest(rig.perfect_calibration("cell"), (2,), **settings)


def test_a_run_through_the_worker(setup, tmp_path):
    worker, watch, rig, machine = setup
    assert worker.start_run(request(rig), tmp_path, {"commit": "test"})
    assert worker.state is State.RUNNING
    watch.wait(lambda: watch.of(RunEnded), timeout=120)
    watch.idle()
    (started,) = watch.of(RunStarted)
    (ended,) = watch.of(RunEnded)
    assert ended.outcome.status == "complete", watch.errors()
    assert ended.outcome.folder == started.folder
    rows = [e.row for e in watch.of(RowEvent)]
    n = len(started.plans[0].raster.rows)
    assert rows[0].row == BASELINE_ROW
    assert [r.row for r in rows if r.row >= 0] == list(range(n))
    (mapped,) = watch.of(MapEvent)
    assert mapped.laser.status == "complete"
    assert watch.of(LaserChanged)[-1].laser == 0
    assert rig.fake_laser.active == 0


def test_stop_mid_run(setup, tmp_path):
    worker, watch, rig, machine = setup
    assert worker.start_run(request(rig, warmup_s=0.0), tmp_path, {"commit": "test"})
    watch.wait(lambda: any(e.row.row >= 1 for e in watch.of(RowEvent)),
               timeout=120)
    worker.stop()
    watch.wait(lambda: watch.of(RunEnded), timeout=60)
    watch.idle()
    (ended,) = watch.of(RunEnded)
    assert ended.outcome.status == "stopped"
    assert rig.fake_laser.active == 0
    assert not rig.fake_smu.enabled[1]
    assert not rig.fake_marlin.moving()


def test_a_fault_mid_run_is_reported_and_the_worker_goes_on(setup, tmp_path):
    worker, watch, rig, machine = setup
    assert worker.start_run(request(rig, warmup_s=0.0), tmp_path,
                            {"commit": "test"})
    watch.wait(lambda: any(e.row.row >= 0 for e in watch.of(RowEvent)),
               timeout=120)
    rig.fake_smu.stalled = True
    watch.wait(lambda: watch.of(RunEnded), timeout=60)
    watch.idle()
    (ended,) = watch.of(RunEnded)
    assert ended.outcome.status.startswith("failed")
    assert "StreamFault" in ended.outcome.status
    rig.fake_smu.stalled = False
    assert worker.home()
    watch.idle()


def test_stop_just_after_start_never_starts_the_run(setup, tmp_path):
    worker, watch, rig, machine = setup
    assert worker.start_run(request(rig), tmp_path, {"commit": "test"})
    worker.stop()
    watch.idle()
    # Either it was caught before the session existed, or the session
    # saw the stop at once; never a complete run.
    ended = watch.of(RunEnded)
    if watch.of(RunStarted):
        assert ended and ended[0].outcome.status == "stopped"
    else:
        assert any(e.text.startswith("run: stopped") for e in watch.of(Log))


def test_close_during_a_run_stops_it_safely(machine, tmp_path):
    faults = Faults()
    machine = sim_machine(machine, faults)
    holder = {}

    def connector():
        conn = open_sim(machine, clock=ScaledClock(20.0),
                        corner_carriage_mm=CORNER, size_mm=SIZE,
                        faults=faults)
        holder["rig"] = conn.rig
        return conn

    worker = MachineWorker(machine, connector, poll_s=0.05)
    watch = Watcher(worker)
    worker.connect()
    watch.idle()
    rig = holder["rig"]
    worker.start_run(request(rig, warmup_s=0.0), tmp_path, {"commit": "t"})
    watch.wait(lambda: watch.of(RowEvent), timeout=120)
    worker.close()
    assert worker.state is State.DISCONNECTED
    (ended,) = watch.of(RunEnded)
    assert ended.outcome.status == "stopped"
    assert rig.fake_laser.active == 0


def test_a_failed_connect_leaves_it_disconnected(machine):
    def connector():
        raise DeviceSetupError("no skr port")

    worker = MachineWorker(machine, connector, poll_s=0.05)
    watch = Watcher(worker)
    try:
        assert worker.connect()
        watch.wait(lambda: worker.state is State.DISCONNECTED and watch.errors())
        assert "no skr port" in watch.errors()[0]
        assert not worker.home()  # nothing to home
        assert worker.connect()  # may try again
    finally:
        worker.close()


def test_a_real_run_is_refused_until_directions_are_checked(machine,
                                                            tmp_path):
    unchecked = replace(machine, geometry=replace(
        machine.geometry, directions_measured=False))
    holder = {}

    def connector():
        conn = open_sim(unchecked, clock=ScaledClock(20.0),
                        corner_carriage_mm=CORNER, size_mm=SIZE)
        holder["rig"] = conn.rig
        # As if it were the real machine.
        return Connection(conn.devices, conn.clock, False, rig=conn.rig)

    worker = MachineWorker(unchecked, connector, poll_s=0.05)
    watch = Watcher(worker)
    try:
        worker.connect()
        watch.idle()
        assert worker.start_run(request(holder["rig"]), tmp_path, {})
        watch.idle()
        assert "directions_measured" in watch.errors()[0]
        assert not watch.of(RunStarted)
    finally:
        worker.close()


def test_the_machine_lock_is_held_by_one_process_at_a_time(tmp_path):
    path = tmp_path / "machine.lock"
    first = machine_lock(path)
    try:
        # A second open in this process stands in for a second process:
        # the OS lock is per open file.
        with pytest.raises(DeviceSetupError, match="in use"):
            machine_lock(path)
    finally:
        first.release()
    machine_lock(path).release()



def test_moves_wait_for_home_and_motors_off_undoes_it(setup):
    from multilbic.gui.worker import Homed

    worker, watch, rig, machine = setup
    assert worker.jog("x", 0.1)
    watch.idle()
    assert "home the stage first" in watch.errors()[-1]
    assert worker.home()
    watch.idle()
    assert watch.of(Homed)[-1].homed
    assert worker.motors_off()
    watch.idle()
    assert not watch.of(Homed)[-1].homed
    assert worker.jog("x", 0.1)
    watch.idle()
    assert len(watch.errors()) == 2


def test_checking_ranges_through_the_worker(setup):
    worker, watch, rig, machine = setup
    truth = rig.perfect_calibration("cell")
    assert worker.start_calibration(check=truth)
    watch.idle()
    assert worker.check_ranges([2])
    assert worker.state is State.MOVING
    watch.idle()
    assert not watch.errors()
    change = watch.of(CalibrationChanged)[-1]
    assert change.ranges[2].range_a == 25e-6
    assert any("range 25 uA" in e.text for e in watch.of(Log))
    assert watch.of(LaserChanged)[-1].laser == machine.geometry.reference_laser


def test_readings_include_the_photodiode_when_opened_with_it(machine):
    def connector():
        return open_sim(machine, clock=ScaledClock(20.0),
                        corner_carriage_mm=CORNER, size_mm=SIZE,
                        smu_channels=(1, 2))

    worker = MachineWorker(machine, connector, poll_s=0.05)
    watch = Watcher(worker)
    try:
        worker.connect()
        watch.idle()
        assert worker.home()
        watch.idle()
        x, y, a, b = reach(machine, 3, open_quarter_middle(machine)).xyab
        assert worker.move(x=x, y=y, a=a, b=b)
        watch.idle()
        assert worker.laser(3)
        watch.idle()
        # Laser 3 is beyond autorange's 1 mA limit, which the idle
        # readings are held to: they read at the limit.
        watch.wait(lambda: any(r.photodiode_a and r.photodiode_a < -0.9e-3
                               for r in watch.of(Reading)))
        assert not watch.errors()
    finally:
        worker.close()


# ---- focus assist ----


def focus_worker(machine, tmp_path):
    from importlib import resources

    path = tmp_path / "machine.toml"
    path.write_text(resources.files("multilbic.config").joinpath(
        "machine.toml").read_text(encoding="utf-8"), encoding="utf-8",
        newline="")

    def connector():
        return open_sim(machine, clock=ScaledClock(50.0),
                        corner_carriage_mm=CORNER, size_mm=SIZE,
                        smu_channels=(1, 2))

    worker = MachineWorker(machine, connector, poll_s=0.05,
                           machine_path=path)
    watch = Watcher(worker)
    worker.connect()
    watch.idle()
    return worker, watch, path


def test_focus_through_the_worker_and_save(machine, tmp_path):
    from multilbic.gui.worker import (
        FocusEnded,
        FocusPassed,
        FocusStarted,
        MachineChanged,
    )
    from multilbic.run.focus import FocusRequest

    worker, watch, path = focus_worker(machine, tmp_path)
    try:
        assert worker.start_focus(FocusRequest(2, max_passes=3, read_s=0.3))
        assert worker.state is State.FOCUSING
        # Nothing else while it focuses.
        assert not worker.jog("a", 0.1)
        watch.wait(lambda: watch.of(FocusEnded))
        watch.idle()
        assert watch.of(FocusStarted)
        assert len(watch.of(FocusPassed)) == 3
        (ended,) = watch.of(FocusEnded)
        assert ended.error is None and ended.result.proposal is not None
        # Readings carry on afterwards, and the laser is off.
        assert watch.of(LaserChanged)[-1].laser == 0
        before = len(watch.of(Reading))
        watch.wait(lambda: len(watch.of(Reading)) > before)

        assert worker.save_focus()
        watch.wait(lambda: watch.of(MachineChanged))
        watch.idle()
        text = path.read_text(encoding="utf-8")
        assert "# focus " in text
        assert worker.machine.laser(2).spot_um == pytest.approx(
            ended.result.proposal.spot_um[2], abs=0.06)
        # Saved once: nothing left to save.
        assert worker.save_focus()
        watch.idle()
        assert any("nothing to save" in e for e in watch.errors())
    finally:
        worker.close()


def test_done_and_stop_while_focusing(machine, tmp_path):
    from multilbic.gui.worker import FocusEnded, FocusPassed
    from multilbic.run.focus import FocusRequest

    worker, watch, _ = focus_worker(machine, tmp_path)
    try:
        assert not worker.finish_focus()  # not focusing
        assert worker.start_focus(FocusRequest(2, read_s=0.3))
        watch.wait(lambda: len(watch.of(FocusPassed)) >= 2)
        assert worker.finish_focus()
        watch.wait(lambda: watch.of(FocusEnded))
        watch.idle()
        assert watch.of(FocusEnded)[-1].result.proposal is not None

        assert worker.start_focus(FocusRequest(2, read_s=0.3))
        watch.wait(lambda: len(watch.of(FocusPassed)) >= 4)
        worker.stop()
        watch.wait(lambda: len(watch.of(FocusEnded)) == 2)
        watch.idle()
        assert watch.of(FocusEnded)[-1].result is None
        assert watch.of(LaserChanged)[-1].laser == 0
        assert any("focus: stopped" in e.text for e in watch.of(Log))
    finally:
        worker.close()
