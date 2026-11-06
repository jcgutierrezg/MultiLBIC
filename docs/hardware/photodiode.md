---
type: reference
title: "Reference photodiode"
---

# Reference photodiode (channel 2)

A silicon photodiode fixed to the AB carriage, outside the sample area,
under two scalpel blades. It finds every laser's position, measures
each spot by knife edge, focuses lasers live, and places every map from
where its laser really landed ([lasers](lasers.md#the-servo)). What it
was chosen for is in
[architecture](../architecture.md#the-channel-2-reference-photodiode).

**Hamamatsu S1223-01** (RS 415-5722): Si PIN, 320–1100 nm (0.52 A/W at
780 nm), a 3.6 × 3.6 mm chip in a TO-5 can with a flat window, no lens,
and a published spectral curve. Silicon covers all six lasers; parts
with eye-response or daylight filters would miss 5 and 6 or 1–3.

## The mount

On the new stage (built 2026-10-29, 1 cm lower than the old one):

- the can sits 35 mm from the AB centre along A, on the side that
  reaches the beam as A rises;
- **two scalpel blades cross over the chip**, one edge along B (passes
  along A cross it) and one along A, leaving **one quarter of the chip
  open**, towards A− and B− as the builder sees it (`open_a = "-"`,
  `open_b = "-"`). The chip's own edges sit under the window, below
  focus, so the blades are the knife edges;
- **the blade along B is at the sample's height**, the one along A
  0.4 mm above it (`blade_a_above_mm`). `spot_um` is measured across
  the lower one.

**The open side, in the carriage frame.** A point counts by the stage
position that puts it under the beam, and a point towards the stage's
A− has to travel further towards A+ to get there: so a quarter open
towards A− lies at *larger* A in that frame. `Photodiode.open_signs`
turns the builder's signs into the frame. (Read the other way round at
first, commissioning swept away from the blades into the can window's
edge: fixed in 0.6.21.)

**The blades' corner is measured**: `corner_ab_mm = (58.568, 21.016)`
on the carriage, from laser 2's view on 2026-10-30
(`20261030T164634Z_commission`); lasers 1 and 3 saw it within 0.07 mm.
Once measured it stays: the photodiode is fixed to the carriage, so a
laser whose view moves is the one that moved. Only if the photodiode
itself is moved is the corner taken again (`--new-corner`, or "The
photodiode was moved" in the window).

## Reaching it

Lasers 1–3 reach it with X near its 103 mm end; laser 1 has the least
room, about 5 mm past the corner along A. Hence Marlin's limits were
widened rather than the stage rebuilt
([motion](motion.md#what-multilbic-changes-at-every-connect)). Lasers
4–6 sit about 30 mm lower in X and reach it easily.

`scan/photodiode.py` splits a point on the carriage into X, Y, A and B
for a laser, with AB as central as XY's travel allows. **Go to
photodiode** in the window puts the open quarter's middle under the lit
laser.

## Readings

- **Negative**, as the cell reads: it is wired the same way round.
- **0 V is fine**: laser 1 read the same at −5 V. At 1.3–2.0 mA with
  spots under 100 µm the response may bend before any range clips;
  edges don't depend on it, powers may.
- **Ranges**: 15 mA for every laser but laser 2 (650 µA or 25 µA). The
  window's idle readout is held to autorange's 1 mA, so it shows the
  bright lasers as `(limit)`.
- **A power read straight after lighting is good to about 15 %**:
  `commission` reads power after the warm-up.
- **Absolute EQE** would need a calibrated photodiode (for example a
  Thorlabs FDS100-CAL); the S1223-01 gives relative spectral response.
- Its leads came off once during a homing (the first commissioning found
  no light): check they are secure.
- Channel 2 has twice been in an offset state ([smu](smu.md#the-channel-2-offset-state)).
