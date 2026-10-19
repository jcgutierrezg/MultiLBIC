"""The miniSMU layer: SMUniversal's driver for setup, streaming direct."""

import inspect

import pytest
from minismu_py import SMU

from multilbic.hardware.smu import PhotocurrentSmu, SmuError
from multilbic.sim.fake_smu import FakeMiniSMU, FakeMiniSMUTransport


def make(clock, channels=(1,), **fake_options):
    fake = FakeMiniSMU(clock, **fake_options)
    smu = PhotocurrentSmu(FakeMiniSMUTransport(fake), clock, channels)
    return smu, fake


def test_fake_matches_the_real_library():
    """Every public method of the fake exists on minismu_py.SMU with the
    same parameter names, so code that works on the fake calls the real
    library correctly."""
    for name, method in inspect.getmembers(FakeMiniSMU, inspect.isfunction):
        if name.startswith("_") or name == "device_ms":
            continue
        assert hasattr(SMU, name), f"minismu_py.SMU has no {name}()"
        fake_params = list(inspect.signature(method).parameters)
        real_params = list(inspect.signature(getattr(SMU, name)).parameters)
        assert fake_params == real_params, name


def test_identify_and_firmware(clock):
    smu, _ = make(clock)
    assert "miniSMU" in smu.identify()
    assert smu.firmware == (1, 5, 0)
    assert smu.firmware_streams_range


def test_old_firmware_is_flagged(clock):
    smu, _ = make(clock, firmware="1.4.6")
    smu.identify()
    assert not smu.firmware_streams_range


def test_prepare_and_output(clock):
    smu, fake = make(clock, channels=(1, 2))
    smu.identify()
    smu.prepare(bias_v=0.0, current_limit_a=1e-3)
    assert fake.mode == {1: "FVMI", 2: "FVMI"}
    assert fake.current_limit[1] == pytest.approx(1e-3)
    assert not fake.enabled[1]
    smu.output_on()
    assert fake.enabled == {1: True, 2: True}
    smu.output_off()
    assert fake.enabled == {1: False, 2: False}


def test_stream_rate_and_timestamps(clock):
    smu, _ = make(clock, signal=lambda ch, t: 1e-6)
    smu.identify()
    smu.prepare()
    smu.output_on()
    smu.stream.start(channels=(1,), rate_hz=200.0)
    clock.sleep(2.0)
    stats = smu.stream.stop()
    samples = smu.stream.drain()
    assert len(samples) == stats.samples[1]
    # ~2 s at 200 Hz, plus however long stop() takes on a loaded machine.
    assert 350 <= len(samples) <= 500
    assert stats.rate_hz(1) == pytest.approx(200.0, rel=1e-6)
    assert all(s.current_a == pytest.approx(1e-6) for s in samples)
    stamps = [s.device_ms for s in samples]
    assert stamps == sorted(stamps)


def test_two_channel_stop_switches_both_off(clock):
    # Bench, 2026-10-19: stopping channel 1 while channel 2 still streams
    # makes minismu_py wait for a quiet line that never comes. The fake
    # raises like the library, so this fails if stop() regresses.
    smu, fake = make(clock, channels=(1, 2))
    smu.prepare()
    smu.output_on()
    smu.stream.start(channels=(1, 2), rate_hz=100.0)
    clock.sleep(0.2)
    smu.stream.stop()
    assert not fake._next_due  # nothing left streaming
    smu.output_off()


def test_two_channels_interleave(clock):
    signals = {1: 1e-6, 2: 5e-3}
    smu, _ = make(clock, channels=(1, 2), signal=lambda ch, t: signals[ch])
    smu.prepare()
    smu.output_on()
    smu.stream.start(channels=(1, 2), rate_hz=100.0)
    clock.sleep(1.0)
    stats = smu.stream.stop()
    assert abs(stats.samples[1] - stats.samples[2]) <= 1
    for sample in smu.stream.drain():
        assert sample.current_a == pytest.approx(signals[sample.channel])


def test_device_clock_is_kept_separate_from_host(clock):
    smu, _ = make(clock, device_offset_ms=250.0, drift_ppm=100.0)
    smu.prepare()
    smu.output_on()
    started_ms = clock.wall_ms()
    smu.stream.start(rate_hz=100.0)
    clock.sleep(1.0)
    smu.stream.stop()
    samples = smu.stream.drain()
    # Device stamps carry the injected offset; host receipt times are in
    # clock seconds. Mapping one onto the other is Phase 3's job.
    assert samples[0].device_ms - started_ms == pytest.approx(250.0, abs=30)
    span_ms = samples[-1].device_ms - samples[0].device_ms
    expected_ms = (len(samples) - 1) * 10.0 * (1 + 100e-6)
    # Absolute: stamps are ~1.7e12 ms, so doubles carry ~1e-4 ms of noise.
    assert span_ms == pytest.approx(expected_ms, abs=1e-3)
    assert samples[-1].host_s > samples[0].host_s


def test_garbled_packet_is_counted_not_fatal(clock):
    smu, fake = make(clock)
    smu.prepare()
    smu.output_on()
    fake.garble_next = True
    smu.stream.start(rate_hz=100.0)
    clock.sleep(0.5)
    stats = smu.stream.stop()
    assert stats.parse_errors == 1
    assert stats.samples[1] > 0


def test_commands_refused_while_streaming(clock):
    smu, _ = make(clock)
    smu.prepare()
    smu.output_on()
    smu.stream.start(rate_hz=100.0)
    with pytest.raises(SmuError, match="streaming"):
        smu.measure()
    with pytest.raises(SmuError, match="already streaming"):
        smu.stream.start()
    # output_off stops the stream first rather than refusing: it is the
    # safe-state path.
    smu.output_off()
    assert not smu.stream.running


def test_sink_receives_samples(clock):
    smu, _ = make(clock)
    smu.prepare()
    smu.output_on()
    received = []
    smu.stream.start(rate_hz=100.0, sink=received.append)
    clock.sleep(0.5)
    smu.stream.stop()
    assert received and not smu.stream.drain()
