---
type: guide
title: "Commissioning"
---

# Commissioning: keeping the lasers where `machine.toml` says

Three procedures, all on the reference [photodiode](hardware/photodiode.md),
all in the window's **Maintenance...** (bottom left, where `machine.toml`
has a photodiode), so none needs the command line:

| Tab | Command | Measures | Writes |
|---|---|---|---|
| **Focus** | (window only) | the spot, pass after pass, while the focus is turned by hand | `xy_centre_mm`, `spot_um` |
| **Photodiode** | `multilbic commission` | each laser's position and spot | `xy_centre_mm`, `spot_um` (and the corner) |
| **Line-up** | `multilbic lineup` | where each laser lands on a cell against laser 3 | `cell_offset_xy_mm` |

Each shows what it found and writes to `machine.toml` only when asked
(D23), each changed line ending in `# focus|commission|lineup <date>`.
Esc or STOP stops any of them at once: motion stops, laser and channel
off, nothing saved. **They move the stage and light lasers; lasers 5 and
6 are infrared, so the box is closed** (Focus is the exception: the box
is open, see below).

**On the Pi, the file written is the repository's own `machine.toml`,
which a deploy resets**: copy it back and commit it before the next
deploy.

## When

- **After any work in the box** (refocusing, replugging, tightening):
  lasers move when handled, by up to 1 mm. Photodiode tab with all six,
  box closed, about 18 min; save. Then a line-up.
- **After focusing a laser**: Focus measures it again before saving.
- **Now and then, or when maps from different lasers disagree**: a
  line-up. It needs no commissioning first.

## Focus

Focus assist (D24). The focus is a hand adjustment at the laser, and by
eye a spot can only be judged to a few tenths of a millimetre. **The box
is open for this**, and the stage moves while your hands are at the
laser, though only about a millimetre round the blade once it is there.

1. Home, then **Maintenance...**, **Focus**: pick the laser and the
   edges (A, the blade at the sample's height; or A and B, to see
   astigmatism), **Start**. The stage homes, brings the photodiode under
   the laser, lights it and passes back and forth across the edge,
   about ±4 spot widths, a pass every 3 s or so.
2. Turn the focus slowly. Each pass shows its 10–90 % width big, the
   best so far, and the mean ± scatter of the last 5; the trace below
   has every pass (A in the accent colour, B grey, the best dashed). A
   change smaller than the scatter is noise. Each pass follows the edge
   if the beam moves, and is fitted with its own light level, so power
   drift doesn't look like focus. Stop once the width rises again, and
   go back to the best.
3. **Done: measure** ends the passes and measures the laser again as
   `commission` does: refocusing moves the beam.
4. **Save to machine.toml** writes the new `xy_centre_mm` and
   `spot_um`; the window carries on with the new file at once, a loaded
   calibration included.

## Photodiode: `commission`

Tick the lasers (all six by default; it says how long that takes),
**Start**. From the command line (`--lasers` defaults to 1,2,3):

```bash
uv run multilbic commission --lasers 1,2,3,4,5,6
uv run multilbic commission --lasers 1,2,3,4,5,6 --write
```

It homes, then for each laser:

1. XY and AB put the middle of the photodiode's open quarter where
   `machine.toml` says the laser is. The channel is read dark, the laser
   comes on, warms up (`--warmup`, 60 s), and is read on the 15 mA range.
   No light there: it searches outwards on a 1 mm grid, 3 mm for a
   measured laser, 8 mm for an unmeasured one.
2. The range for the rest is the smallest holding 3× that reading. A
   pass that reaches the range's limit goes again one range up: the
   light may have been found on an edge, a sliver of the spot.
3. Each blade edge is swept three times, each finer than the last:
   coarse, ±2 mm round where the light was found (`--coarse-feed`,
   0.5 mm/s); medium, ±0.6 mm round that edge (0.15 mm/s); then a slow
   pass up and one down across it (`--fine-feed`, 0.05 mm/s). The coarse
   and medium sweeps fit only from their brightest point towards the
   blade, so a sweep that also crosses the can window's far edge leaves
   it out. The mean of the two fine directions is the edge; their
   difference (backlash plus lag) is printed. An edge counts only if its
   step goes the light's way and is at least half the light seen so far.
4. The power is read again on the open quarter, warm by then, and the
   dark on the same range with the laser off.

Where the two edges cross is the corner as that laser sees it, and each
laser's `xy_centre_mm` moves by however far its view is from the
corner's measured place. **The corner stays**: the photodiode is fixed
to the carriage, so a laser whose view moved is the one that moved, the
reference laser too. Calibrations stay right: each records the
reference laser's position when it was made, and the window moves a
calibration's corner XY with it. Only after moving the photodiode, tick
"The photodiode was moved" (`--new-corner`): the reference laser's view
becomes `[photodiode] corner_ab_mm` (include laser 3). `spot_um` is the
width across the blade at the sample's height; the other edge, 0.4 mm
higher, is printed too.

It saves `commission.json` (every pass's readings, also for a run that
fails or is stopped) and `machine-proposed.toml` in a run folder.
`--write` writes the changes (asking first unless `--yes`). A laser that
can't reach past an edge says so; a channel reporting more than 10 mV
off its bias is reported (the positions stand). `--sim` runs it on the
simulated photodiode; `--sim-offset N=DX,DY` and `--sim-corner DA,DB`
plant errors to see them recovered.

## Line-up

Each laser is placed from the photodiode, but its beam meets the blades
a little above the cell, at its own angle: on the cell it lands tens of
µm from where the blades said, the same way each run
([lasers](hardware/lasers.md#how-well-the-lasers-line-up)). The line-up
measures that on a cell's corner, against the reference laser (3).

1. In the Calibration panel, set the corner on a cell's corner under
   laser 3 (or load such a calibration). The Line-up tab shows the
   corner it will use.
2. Tick the lasers (laser 3 must be one), **Start**. It confirms the
   plan, then maps a 1.2 mm square centred on that corner with every
   laser placed from the photodiode, at 10 µm pixels, 25 µm rows and
   4 mm/s, each laser on its range from the run setup (about 25 min for
   six). The maps show in the run column like any run's.
3. The table gives each laser's two cell edges, its row shift and its
   proposed offset; a `?` marks an edge not found clearly, and that
   laser is left as it is. **Save offsets to machine.toml** writes them.

How the edges are found (`run/lineup.py`): in each laser's map, the
cell's edge crossing the rows (along u) and the one crossing the columns
(along v), each row or column fitted where the rows agree it is, the
median and spread kept. An edge from fewer than 5 rows, or whose rows
disagree by more than 40 µm, is not trusted. Against laser 3's edges,
each laser's difference, turned into XY, is added to the
`cell_offset_xy_mm` its run used; laser 3's stays 0. An offset over
0.5 mm is refused when `machine.toml` loads.

A line-up run made elsewhere (the window, or `multilbic run` on the
centred patch) is read again from the command line:

```bash
uv run multilbic lineup ~/multilbic-runs/<run folder>
uv run multilbic lineup ~/multilbic-runs/<run folder> --write
```

**One line-up has the scatter of one run**, about 20 µm a laser. A
second line-up right after the first shows how much of its proposal is
real; averaging several gives better offsets than any one.
