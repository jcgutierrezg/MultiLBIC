"""
The miniSMU: photocurrent on channel 1, the reference photodiode on 2.

Two layers, deliberately:

* **Setup and output control** go through SMUniversal's
  `UndalogicMiniSMU` driver: identification, firmware parsing, reset,
  source mode, bias, current limit, oversampling, output on and off.
  That driver carries SMUniversal's bench findings for this exact unit,
  and none of that is re-derived here.
* **Streaming** goes straight to the vendor library (`minismu_py`),
  because SMUniversal has no use for it and its driver does not wrap it.

Both reach the instrument through one `minismu_py.SMU` object (the
transport's `.client`), so in simulation one fake client serves both
(`multilbic.sim.fake_smu`).

Streaming and commands share one serial connection
-------------------------------------------------
While the instrument streams, every line on the port is a data packet.
A command sent then would have its reply lost among them, and two
threads reading the port would split packets between them. So
`SmuStream` is the only reader while streaming. It is stopped (reader
joined) before `stop_streaming` is sent, and no setup command is
accepted while it runs. Packets that arrive between the reader stopping
and the instrument stopping are discarded by the library's drain. The
scan stops streaming only after the stage has finished the row, so
nothing of value is in that tail.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from multilbic.clock import SYSTEM_CLOCK, Clock

#: Firmware 1.5.0 appends the active current range to every streamed
#: packet, which matters if autoranging switches between nA and µA
#: mid-row. Older firmware streams, but without it.
RECOMMENDED_FIRMWARE = (1, 5, 0)


class SmuError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StreamSample:
    channel: int
    #: Timestamp from the instrument's own clock, in milliseconds.
    device_ms: float
    voltage_v: float
    current_a: float
    #: When the host received it, in the driver's clock seconds. Used to
    #: map the instrument's clock onto the host's (Phase 3). Every
    #: sample in one bulk read shares the same value.
    host_s: float
    #: Fields after the fourth, as text. Firmware 1.4.6 already sends a
    #: fifth, probably the active current range (unverified).
    extra: tuple[str, ...] = ()


@dataclass
class StreamStats:
    samples: dict[int, int] = field(default_factory=dict)
    parse_errors: int = 0
    #: Reads that returned nothing within the port's 1 s timeout.
    idle_reads: int = 0
    #: "bulk" (serial port read directly) or "per-line" (the library).
    reader: str = ""
    #: The port failed mid-stream (unplugged, closed). Reading stops.
    read_error: str | None = None
    first_device_ms: dict[int, float] = field(default_factory=dict)
    last_device_ms: dict[int, float] = field(default_factory=dict)

    def rate_hz(self, channel: int) -> float | None:
        """Achieved rate from the instrument's own timestamps."""
        n = self.samples.get(channel, 0)
        if n < 2:
            return None
        span_ms = self.last_device_ms[channel] - self.first_device_ms[channel]
        return (n - 1) / (span_ms / 1000.0) if span_ms > 0 else None


def parse_packet(line: bytes, host_s: float) -> StreamSample | None:
    """`b"1,1792432988369,7.1335e-04,-1.5365e-09,0"` -> a sample, or
    None if the line is not a data packet."""
    fields = line.strip().split(b",")
    if len(fields) < 4:
        return None
    try:
        channel = int(fields[0])
        device_ms = float(fields[1])
        volts = float(fields[2])
        amps = float(fields[3])
    except ValueError:
        return None
    extra = tuple(f.decode("ascii", "replace") for f in fields[4:])
    return StreamSample(channel, device_ms, volts, amps, host_s, extra)


def _is_idle_read(error: Exception) -> bool:
    # minismu_py turns an empty readline (its 1 s timeout) into
    # SMUException("Failed to parse streaming data: ''").
    return str(error).rstrip().endswith("''")


class SmuStream:
    """Streams timestamped samples from one or both channels."""

    def __init__(self, client, clock: Clock = SYSTEM_CLOCK):
        self._client = client
        self._clock = clock
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._queue: queue.SimpleQueue[StreamSample] = queue.SimpleQueue()
        self._sink: Callable[[StreamSample], None] | None = None
        self._channels: tuple[int, ...] = ()
        self.stats = StreamStats()

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(
        self,
        channels: tuple[int, ...] = (1,),
        rate_hz: float = 1000.0,
        sink: Callable[[StreamSample], None] | None = None,
    ) -> None:
        """Start streaming. Samples go to `sink` if given (called on the
        reader thread, so it must be quick), otherwise to an internal
        queue read with `drain()`."""
        if self.running:
            raise SmuError("already streaming")
        if rate_hz <= 0:
            raise ValueError("rate_hz must be positive")
        self._channels = tuple(channels)
        self._sink = sink
        self._stop.clear()
        self.stats = StreamStats()
        for channel in self._channels:
            self._client.set_sample_rate(channel, rate_hz)
        # Readable timestamps in the file; positions never depend on it.
        self._client.set_time(self._clock.wall_ms())
        for channel in self._channels:
            self._client.start_streaming(channel)
        self._thread = threading.Thread(
            target=self._read_loop, name="smu-stream", daemon=True
        )
        self._thread.start()

    def stop(self) -> StreamStats:
        """Stop the reader, then the instrument. Returns the counts."""
        if self._thread is None:
            return self.stats
        self._stop.set()
        # The reader is blocked in readline for at most the library's
        # 1 s timeout, much less while packets are flowing.
        self._thread.join(timeout=self._clock.to_real(3.0) + 3.0)
        if self._thread.is_alive():
            raise SmuError("stream reader did not stop")
        self._thread = None
        self._stop_instrument()
        return self.stats

    def _stop_instrument(self) -> None:
        """Switch every streaming channel off, then wait for quiet once.

        `minismu_py`'s `stop_streaming(n)` sends `STREAM OFF` for channel
        n and then waits for the line to go quiet. With two channels
        streaming, channel 2 keeps talking while channel 1 is stopped, so
        the wait gives up after 2 s and raises, leaving channel 2
        streaming with its output on. Found on the bench 2026-10-19. So
        every other channel is switched off first with the library's own
        write, and only the last goes through `stop_streaming()` and its
        wait.
        """
        if not self._channels:
            return
        *first, last = self._channels
        for channel in first:
            self._client._write_command(f"SOUR{channel}:DATA:STREAM OFF")
        self._client.stop_streaming(last)

    def drain(self) -> list[StreamSample]:
        """Every sample received so far that has not been drained yet."""
        samples = []
        while True:
            try:
                samples.append(self._queue.get_nowait())
            except queue.Empty:
                return samples

    def _read_loop(self) -> None:
        port = getattr(self._client, "_connection", None)
        if port is not None and hasattr(port, "in_waiting"):
            self.stats.reader = "bulk"
            self._read_bulk(port)
        else:
            # A network connection has no serial port to read in bulk.
            self.stats.reader = "per-line"
            self._read_lines()

    def _read_bulk(self, port) -> None:
        """Read everything waiting, then split it into packets.

        `minismu_py` reads a packet with pyserial's `readline()`, one
        byte per system call. On the Pi that tops out around 750
        packets/s and falls behind the stream, while reading whatever is
        waiting in one call kept up at 1190/s with a flat backlog
        (bench, 2026-10-19). The library still owns the port; this only
        reads it while nothing else does.
        """
        stats = self.stats
        counts, first, last = (
            stats.samples, stats.first_device_ms, stats.last_device_ms,
        )
        emit = self._sink if self._sink is not None else self._queue.put
        pending = b""
        while not self._stop.is_set():
            try:
                chunk = port.read(port.in_waiting or 1)
            except (OSError, TypeError, AttributeError) as exc:
                # pyserial: SerialException (an OSError) when unplugged,
                # TypeError/AttributeError when closed under a read.
                stats.read_error = f"{type(exc).__name__}: {exc}"
                return
            if not chunk:
                stats.idle_reads += 1
                continue
            host_s = self._clock.now()
            lines = (pending + chunk).split(b"\n")
            pending = lines.pop()
            for line in lines:
                if not line.strip():
                    continue
                sample = parse_packet(line, host_s)
                if sample is None:
                    stats.parse_errors += 1
                    continue
                channel = sample.channel
                counts[channel] = counts.get(channel, 0) + 1
                if channel not in first:
                    first[channel] = sample.device_ms
                last[channel] = sample.device_ms
                emit(sample)

    def _read_lines(self) -> None:
        while not self._stop.is_set():
            try:
                channel, t_ms, volts, amps = self._client.read_streaming_data()
            except Exception as exc:  # minismu_py raises SMUException
                if _is_idle_read(exc):
                    self.stats.idle_reads += 1
                else:
                    self.stats.parse_errors += 1
                continue
            sample = StreamSample(
                int(channel), float(t_ms), float(volts), float(amps),
                self._clock.now(),
            )
            stats = self.stats
            stats.samples[sample.channel] = (
                stats.samples.get(sample.channel, 0) + 1
            )
            stats.first_device_ms.setdefault(sample.channel, sample.device_ms)
            stats.last_device_ms[sample.channel] = sample.device_ms
            if self._sink is not None:
                self._sink(sample)
            else:
                self._queue.put(sample)


class PhotocurrentSmu:
    """The miniSMU set up for LBIC: a fixed bias and streamed current.

    `transport` is anything with a `.client` holding a `minismu_py.SMU`
    (or the fake): SMUniversal's `MiniSMUTransport` on the machine.
    """

    def __init__(
        self,
        transport,
        clock: Clock = SYSTEM_CLOCK,
        channels: tuple[int, ...] = (1,),
    ):
        from smuniversal_lab_suite.drivers.undalogic_minismu import (
            UndalogicMiniSMU,
        )

        self._transport = transport
        self.channels = tuple(channels)
        self.drivers = {
            channel: UndalogicMiniSMU(transport, channel=channel)
            for channel in self.channels
        }
        self.stream = SmuStream(transport.client, clock)
        self.identity: str | None = None

    @property
    def firmware(self) -> tuple[int, int, int] | None:
        return self.drivers[self.channels[0]].firmware()

    @property
    def firmware_streams_range(self) -> bool:
        """True if streamed packets include the active current range."""
        firmware = self.firmware
        return firmware is not None and firmware >= RECOMMENDED_FIRMWARE

    def identify(self) -> str:
        self.identity = self.drivers[self.channels[0]].identify()
        return self.identity

    def prepare(
        self,
        bias_v: float = 0.0,
        current_limit_a: float = 1e-3,
        nplc: float | None = None,
    ) -> None:
        """Reset each channel and set it to source `bias_v` and measure
        current. The output stays off until `output_on()`."""
        self._refuse_while_streaming()
        for driver in self.drivers.values():
            driver.reset()
            driver.set_source_function("voltage")
            driver.set_voltage_level(bias_v)
            driver.set_current_limit(current_limit_a)
            if nplc is not None:
                driver.set_nplc(nplc)

    def output_on(self) -> None:
        self._refuse_while_streaming()
        for driver in self.drivers.values():
            driver.output_on()

    def output_off(self) -> None:
        """Every channel off, trying each even if one fails. Stops the
        stream first if it is running, since a command cannot be heard
        over it."""
        if self.stream.running:
            self.stream.stop()
        errors = []
        for channel, driver in self.drivers.items():
            try:
                driver.output_off()
            except Exception as exc:
                errors.append(f"channel {channel}: {exc}")
        if errors:
            raise SmuError("output off failed: " + "; ".join(errors))

    def measure(self, channel: int = 1) -> tuple[float, float]:
        """One (voltage, current) reading, outside streaming."""
        self._refuse_while_streaming()
        return self.drivers[channel].measure()

    def close(self) -> None:
        if self.stream.running:
            self.stream.stop()
        close = getattr(self._transport, "close", None)
        if close is not None:
            close()

    def _refuse_while_streaming(self) -> None:
        if self.stream.running:
            raise SmuError("the instrument is streaming: stop it first")


def open_smu(
    port: str,
    clock: Clock = SYSTEM_CLOCK,
    channels: tuple[int, ...] = (1,),
) -> PhotocurrentSmu:
    """Connect to the real miniSMU on `port`."""
    from smuniversal_lab_suite.core.transports.minismu_transport import (
        MiniSMUTransport,
    )

    transport = MiniSMUTransport()
    transport.connect(port)
    return PhotocurrentSmu(transport, clock, channels)
