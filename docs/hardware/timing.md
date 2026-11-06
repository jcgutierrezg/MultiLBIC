---
type: reference
title: "Timing"
---

# Timing: where each sample was

A map needs each sample's position along a row, and the stage moves at
4 mm/s: 1 ms of error is 4 µm. How the code does it is in
[scan](../scan.md#position); this page is what the bench measured, and
why the code does it that way.

## Dating samples

The miniSMU measures at a steady rate, but its stamps saw-tooth: about
every 100 ms they jump 5–8 ms to catch up after falling about 6 %
behind ([smu](smu.md#streaming)). Dated by stamp, samples sat up to
~12 µm off along a row at 4 mm/s, and each jump left 2–3 empty 10 µm
pixels. **Since 0.6.35 each run file keeps the whole stream, and
samples are dated by count**: a straight line of stamp against sample
number over the whole file.

## The sync check

`multilbic sync-check` ([diagnostics](../diagnostics.md#sync-check-the-sync-error-on-one-edge))
measures the timing against step-and-measure, which involves none, on
one straight edge at several speeds. On the test cell's edge along B,
laser 3, 2026-11-04 (`20261104T135122Z_sync_std_test_v2-corner`):

| | Dated by count | Stamps as recorded |
|---|---|---|
| Timing error `L` | **14.9 ms** | 19.9 ms |
| A backlash | **+4.0 µm** | −8.2 µm |
| Lines leave | 4.0 µm RMS | 4.8 µm RMS |
| Alignment / edges, 4 mm/s | 118.3 / 114.9 µm | 133.5 / 132.8 µm |
| Alignment / edges, 5 mm/s | 141.8 / 140.2 µm | 204.8 / 197.4 µm |

- Dated by count, one lag fits every speed, the backlash is positive,
  and the maps' own alignment agrees with the edges to 2–3 µm. Two
  sessions dated by count gave the same `L` and backlash; by stamps the
  backlash came out negative (impossible) both times.
- **Decided**: `ab_backlash_mm` stays 0 (4 µm is within the noise), the
  default speed stays 4 mm/s (rows scatter more at 5), and no hardware
  marker: option C dropped (D33).
- Step-and-measure itself drifted 9–18 µm over a 16-minute session.

## Row replies

Each row is anchored on the `ok` to the `M400` after it. On time it
comes 93–96 ms after the row's `G1` was sent, beyond the modelled move,
steady to half a millisecond in each file (`[ab] row_reply_ms`, 93.5).

**In about one map in six, a stretch of rows has its replies 20–40 ms
late, and the moves are not** (2026-11-05). Placed from the reply,
those rows sat late and the serpentine shift flipped sign (−68 to
−196 µm against the usual +110 to +157 µm at 4 mm/s): forward rows
really drawn on the far side of reverse ones. The late replies all came
about 90 ms after one of the miniSMU's bursts arrived; rows are paced by
those bursts, so a map stays late once it is. Whether Marlin or the Pi
holds the reply back is not known. **Late rows are placed from their
send plus the usual delay** (0.6.47).

**Single rows can start late instead**: the board took the `G1` up
late, so the reply is right and the send isn't (lasers 5 and 6, the
first line-up, 2026-11-05: three rows 27–45 ms late, drawn 100–200 µm
off from the send, within 10–20 µm from the reply). Each late row keeps
whichever placement lines up with the on-time rows of its direction
near it (0.6.51).

## The serpentine shift

What is left is constant per map and puts forward rows one way and
reverse rows the other: about **+20 µm at 1 mm/s and +110 to +157 µm at
4 mm/s** on this machine. The map's alignment measures it per map and
takes half off each direction ([scan](../scan.md#position)).

- It differs a little by laser and spot (10–39 µm at 1 mm/s on the
  first maps), so it is measured per map, not set.
- **Mains in the fit can steer it**: fitted over each whole row, a cell's
  1 mA edge leaked about 1 % into the 50 Hz sines, and laser 6's
  alignment locked onto that (+82 µm where its edge said +137). Fitted
  where the row is flat, it agrees (0.6.49).
