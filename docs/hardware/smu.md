---
type: reference
title: "Source-measure unit"
---

# Source-measure unit (miniSMU)

The same **Undalogic miniSMU MS01** that SMUniversal uses (serial
`LUNAR-TUVOK-7966`), whose bench record there is
`SMUniversal_Lab_Suite/docs/instruments/undalogic-minismu.md`.

- **Channel 1** is the cell, **channel 2** the reference
  [photodiode](photodiode.md), both at 0 V.
- **Envelope**: two channels, four-quadrant, ±12 V, ±180 mA, 2.1 W a
  channel. Five current ranges: **1 µA, 25 µA, 650 µA, 15 mA, 180 mA**.
  On USB-C power alone each channel is limited to 50 mA and the
  instrument can't say which supply it is on, so the 12 V adapter stays
  plugged in.
- **The current limit follows the range**, at its full scale (1 mA on
  autorange); it took limits down to 25 µA. A range that truly clips
  reads its end exactly, 26.8 µA on 25 µA.
- **A limit set before the range is lost**, and **channel 1's
  voltage-mode current limit clamps above what is set**, on its 180 mA
  range, both into laser 5 (2026-11-10; the readings themselves are good
  to 0.1 %):
  - limit 15.5 mA sent before the range: 18.76 mA, what the diode draws
    at that voltage, so no limit at all;
  - with the range first: 2.55 mA for 2.07 mA sent, 2.69 for 2.2, and
    18.06 for 16.85, about 1.05 x the setting plus 0.4 mA.

  - into a 100 ohm resistor (2026-11-11): every voltage from 0 to 4 V
    reached within 2 mV under 40.7 and 60 mA limits, the current at
    V/R; 3.267 V held at 33 mA; a 20 mA limit clamped hard at
    21.18 mA, the voltage pinned at 2.09 V.

  Set the range first, then the limit, and allow for the offset. The
  laser module test measures the gain at a few mA each run and sets
  its limits under it (over-correcting at higher currents), and also
  calls the voltage read 30 mV below the voltage set a clamp.
  `PhotocurrentSmu.prepare` sets limit then range, harmless for a cell
  at 0 V.
- **Firmware 1.4.6**: Undalogic's updater returned HTTP 500. 1.5.0+
  adds the active range to each streamed packet; nothing depends on it.

## Ranges

- **Scans use a fixed range per laser** (D15): autoranging drops 10–15 ms
  of samples at every switch while streaming (2026-10-21: 91 % of the
  gaps exactly where the current crossed 1 µA, and the rate halved). The
  range is checked per sample at calibration (D25) and steps up if it
  clips (D26).
- **On the test cell at 0 V**: the line-ups ran lasers 1 and 3–6 on
  15 mA and laser 2 on 650 µA. On the photodiode: 15 mA for all but
  laser 2.
- **Autorange doesn't stick** for single readings: after each reset the
  first reading or two sit at the 1 µA range's end while it climbs. The
  range check re-reads near a range's top as a safety net.
- **A dark reading counts only on the range it is read on**: runs,
  `commission` and the locate read their dark on the laser's range.

## Streaming

`SOUR<n>:DATA:STREAM`, packets of channel, stamp, volts, amps and a
fifth field (`1,1792432988369,7.1335e-04,-1.5365e-09,0`), stamped in
whole milliseconds by the instrument's clock. Measured 2026-10-19, with
the bulk reader:

| Requested | Delivered (device clock) | Step jitter |
|---|---|---|
| 100 Hz | 100.0 Hz | 0.31 ms |
| 500 Hz | 504.0 Hz | 0.51 ms |
| 1000 Hz | 1008.6 Hz | 0.65 ms |
| 2000 Hz | **1408.6 Hz**, the instrument's ceiling | 0.92 ms |

- **The delivered rate is not the requested one** and varies run to run
  (1000 Hz gave 938 and 1194 Hz once): the device's stamps are the
  reference. Maps stream at 400–1000 Hz (800 Hz at 4 mm/s and 10 µm
  pixels).
- **The Pi needs bulk reads.** `minismu_py` reads a byte per system call
  and fell seconds behind above a few hundred Hz; `SmuStream` reads
  everything waiting at once, and kept up at 1190/s.
- **Packets come in bursts every ~100 ms, and the stamps saw-tooth**:
  between jumps they advance 6 % slow, then jump 5–8 ms, while the
  samples themselves are all there and evenly spaced (2026-11-03: 480
  samples in 599 ms every row). So samples are dated by count, not by
  stamp ([timing](timing.md#dating-samples)).
- **At 1000 Hz a real run loses samples**: about 3 %, a few at a time
  (2026-11-06, one channel, 30 minutes), where 800 Hz maps lose none.
  Those samples' stretches keep their stamps, and the gaps over 4
  pixels show as empty pixels in the picture.
- **The instrument's clock runs +306 ppm** against the Pi's (18 ms a
  minute). Arrival latency: median 52 ms, at most 109 ms, not growing.
- **Two channels** stream separate packets. Stopping one while the other
  streams hangs the library; `SmuStream.stop()` turns every channel off
  first.

## Noise

- **In the box, on a contacted cell**, a map's laser-off baseline sits
  at −0.4 to −20 nA with 0.7–1.5 nA RMS, mostly drift below 0.5 Hz.
  With the room lights on the bench had measured 1.7 µA RMS: the box is
  about a thousand times quieter.
- **Open leads are an antenna**: 14–16 nA RMS at 0 V, 89 % of it at
  50 Hz. A contacted cell's low impedance removes most of that.
- **Mains** (50 Hz and its harmonics) is fitted and removed along each
  row ([scan](../scan.md#cleaning)), which needs at least 400 Hz.
- **Slow drift** (0.2–0.7 Hz, the band a map's features pass in) is left
  in the map: D8, set aside while there is no proper enclosure.
- Offsets on fixed ranges: a few nA on 25 µA, about +90 nA on 650 µA.

## The channel-2 offset state

**For about an hour on 2026-10-29, and again from the start of a run on
10-30, channel 2 read high by about 1.7 % of each range's full scale and
reported its voltage 0.27–0.29 V off**, at 0 V and at −5 V alike: the
measurement's offset, not current through the photodiode. Channel 1,
with the same photodiode, read 250 times less and held 0 V to 0.5 mV.
Then it went, after the leads were swapped and swapped back. Cause
unknown: how the leads sit in the terminals, or a state inside the SMU
(its reset doesn't reboot it).

**What sets and clears it** (2026-11-10, laser module tests, channel 2
on at 0 V, channel 1 at 0 V or 0 A): channel 2 reported +0.16 to +0.30 V
at 0 V and read 1-2 % of each range's full scale high (+155 to +300 µA
on 15 mA, +11.6 µA on 650 µA). It is set by

- a mode command to channel 1 (`FVMI` or `FIMV`);
- channel 1 in current mode with its output off: setting its current
  level, or switching its output off, there.

It is cleared by a fixed-range command to channel 1 (`IRANGE`) or by
switching channel 1's output on. In voltage mode a limit, a level or
the output off after the range leave it clear. Channel 2's own range
commands, a channel reset, and replugging the power, USB and channel
2's leads did not clear it. Autorange hides it (−0.37 µA read in it).
Runs keep channel 1 in voltage mode with its range after its mode,
which is why they rarely meet it; the laser module test parks channel 1
in voltage mode at 0 V before its dark, measures with channel 1's
output on, and refuses any reading with channel 2 more than 10 mV off
0 V.

- A dark on the laser's own fixed range removes the offset from the
  powers; positions don't depend on it.
- A channel at 0 V reporting more than a few mV off is in that state:
  `read` prints the voltage, and `commission` warns over 10 mV.
- Under laser 3 on autorange, either channel hits the 1 mA limit and
  can no longer hold 0 V: bright lasers need a fixed 15 mA range.
